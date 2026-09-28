"""Parlament de Catalunya: Diari de Sessions del Ple (DSPC-P, PDF en catalán): totales por reglas y documentos para LLM.

Fuente: el buscador de publicaciones oficiales del nuevo portal (Oracle APEX, «siap-cerca/cerca-de-documents»),
filtrado por tipo PUB_DSPCP y legislatura. Sus resultados se cargan por AJAX (wwv_flow.ajax) y dan, por Diario,
el número («DSPC-P 110»), la fecha, las sesiones que recoge («50.3, ordinària 51.1, específica») y el enlace al
PDF en la API REST (api/siapcerca/v1/document?id_document=…). La API solo sirve documentos y expedientes por
identificador, sin listados; las fichas de expediente y los «Acords» de cada sesión dan el resultado del trámite
pero no los votos. No hay datos abiertos de votaciones (el portal de la Generalitat solo tiene el SIIP de
iniciativas del Govern, sin votos).

`descargar` saca del Diario cada votación con reglas (fuente «pdf-reglas»): la Presidencia dice siempre
«Comença la votació.» y a continuación el resultado en frases fijas («Aquest punt ha estat aprovat per 99 vots a
favor, 35 vots en contra i cap abstenció», «Han estat aprovades per unanimitat», «El resultat de la votació ha
estat…»). El asunto es el último epígrafe del Diario («Moció subsegüent… (continuació) 302-00284/15», que da
título y expediente) y el subtítulo, la fórmula previa de la Presidencia («Votem el punt 2»). No hay voto por
grupo ni nominal; «per unanimitat» sin cifras queda sin totales y con resultado «aprobada».
El resultado es el que dice la Presidencia, nunca se deduce de los votos: con su negación («Aquest punt no ha
quedat aprovat», «tampoc han quedat aprovats»), el último verbo si se corrige («ha quedat aprovat… Perdó, ha quedat
rebutjat»), «validat/derogat» en los decretos ley y «(no) es tramitarà com a projecte de llei» cuando lo votado es
esa tramitación; sin las consecuencias que no son lo votado («aquesta iniciativa queda rebutjada», «el decret llei
que hem aprovat»). Si aun así no cuadra con los totales por mayoría simple, se respeta cuando el texto habla de
mayoría absoluta o reforzada (mayoria="absoluta" si es absoluta) y, si no, se deja con extra["aviso_resultado"]
(son erratas del propio Diario: 5 de 11.836).
`documentos` da los mismos Diarios para el extractor LLM (si se usan los dos, las votaciones se duplicarían).

Cobertura: legislaturas XII (2018), XIV (2021; en la fuente «XIII-XIV», código 13) y XV (2024). `sesion` es el
número del Diario (uno por día de pleno). Limitaciones: depende del marcado de APEX (pInstance, pSalt,
pPageItemsProtected y el ajaxIdentifier del informe «resultats_cerca»); el servidor corta a veces conexiones
TCP (se reintenta); las votaciones por asentimiento o anteriores al primer epígrafe no se recogen.
"""

import html
import json
import re
import urllib.parse

from ...territorio import Cuerpo, num_parlamento, romano
from ..modelo import Documento, Votacion

CODIGO = "parl-CT"
CUERPOS = [
    Cuerpo(CODIGO, num_parlamento("CT"), "Parlament de Catalunya", "Parlament (Cataluña)", "autonomico", "CT", 135,
           {12: (romano(12), "2018-01-17", "2021-03-12"),
            14: (romano(14), "2021-03-12", "2024-06-10"),
            15: (romano(15), "2024-06-10", None)},
           web="https://www.parlament.cat"),
]
NOTAS = ("DSPC-P (PDF en catalán), XII, XIV y XV legislatura, listado por el buscador APEX del portal (AJAX). "
         "descargar: totales y resultado de cada votación por reglas («Comença la votació…»), con expediente y "
         "título del epígrafe; sin voto por grupo. El resultado es el dicho (negaciones y correcciones incluidas); "
         "si contradice los totales sin mayoría reforzada, extra.aviso_resultado. documentos: los mismos Diarios "
         "para LLM (no usar ambos).")

CODIGO_FUENTE = {12: "12", 14: "13", 15: "15"}  # la XIV figura como «XIII-XIV», código 13
BUSCADOR = "https://www.parlament.cat/ext/r/pcat_portal/siap-cerca/cerca-de-documents"
AJAX = "https://www.parlament.cat/ext/wwv_flow.ajax"
POR_PAGINA = 100
FILA_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELDA_RE = re.compile(r"<td[^>]*headers=\"([A-Z_]+)\"[^>]*>(.*?)</td>", re.S)
PDF_RE = re.compile(r'href="(https://www\.parlament\.cat/api/siapcerca/v1/document\?id_document=(\d+))"')


def _limpia(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


class _Buscador:
    """Sesión APEX del buscador de documentos: una página y tantas peticiones AJAX como páginas de resultados."""

    def __init__(self, ctx):
        self.ctx = ctx
        q = {"clear": "100", "p100_tipus_document": "PUB_DSPCP", "p100_ordenacio": "LEG_DESC_TITOL_DESC",
             "p100_cerca_executada": "S"}
        self.pagina = ctx.texto(BUSCADOR + "?" + urllib.parse.urlencode(q))
        m = re.search(r'apex\.widget\.report\.init\("resultats_cerca","([^"]+)",\{"pageItems":"([^"]*)"', self.pagina)
        ctxp = re.search(r'p_context=([^"&]+)', self.pagina)
        if not m or not ctxp:
            raise RuntimeError("Cataluña: el buscador APEX ha cambiado (no se encuentra el informe «resultats_cerca»)")
        self.ajax_id = json.loads(f'"{m.group(1)}"')
        self.items = [i.lstrip("#") for i in m.group(2).split(",") if i]
        self.url_ajax = f"{AJAX}?p_context={ctxp.group(1)}"

    def _valor(self, id_):
        for patron in (rf'id="{id_}"[^>]*value="([^"]*)"', rf'value="([^"]*)"[^>]*id="{id_}"'):
            m = re.search(patron, self.pagina)
            if m:
                return html.unescape(m.group(1))
        return None

    def pagina_resultados(self, leg_fuente, desplazamiento):
        fijos = {"P100_TIPUS_DOCUMENT": "PUB_DSPCP", "P100_LEGISLATURA": leg_fuente, "P100_CERCA_EXECUTADA": "S",
                 "P100_ORDENACIO": "LEG_DESC_TITOL_DESC", "P100_PAGE_OFFSET": str(desplazamiento),
                 "P100_PAGE_LIMIT": str(POR_PAGINA)}
        valores = [{"n": i, "v": fijos.get(i, self._valor(i + "_HIDDENVALUE") or self._valor(i) or "")}
                   for i in self.items]
        p_json = {"pageItems": {"itemsToSubmit": valores, "protected": self._valor("pPageItemsProtected"),
                                "rowVersion": "", "formRegionChecksums": []}, "salt": self._valor("pSalt")}
        datos = urllib.parse.urlencode({
            "p_flow_id": self._valor("pFlowId"), "p_flow_step_id": self._valor("pFlowStepId"),
            "p_instance": self._valor("pInstance"), "p_debug": "", "p_request": "PLUGIN=" + self.ajax_id,
            "p_widget_action": "reset", "p_json": json.dumps(p_json)}).encode()
        h = self.ctx.texto(self.url_ajax, data=datos, headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"})
        if "report_table_resultats_cerca" not in h and "t-Report" not in h:
            raise RuntimeError("Cataluña: respuesta AJAX inesperada del buscador")
        filas = []
        for fila in FILA_RE.findall(h):
            celdas = {k: _limpia(v) for k, v in CELDA_RE.findall(fila)}
            pdf = PDF_RE.search(fila)
            m_num = re.match(r"DSPC-P\s*(\d+)", celdas.get("TITOL_DOCUMENT", ""))
            m_fecha = re.match(r"(\d{2})/(\d{2})/(\d{4})$", celdas.get("DATA_DOCUMENT", ""))
            if pdf and m_num and m_fecha:
                filas.append({"num": int(m_num.group(1)), "url": pdf.group(1), "id": int(pdf.group(2)),
                              "fecha": f"{m_fecha.group(3)}-{m_fecha.group(2)}-{m_fecha.group(1)}",
                              "sesiones": celdas.get("SESSIONS", "")})
        return filas, h.count('headers="TITOL_DOCUMENT"')


def _diarios(ctx):
    """Documento de cada DSPC-P, del más reciente al más antiguo, hasta `ctx.desde`."""
    cuerpo = CUERPOS[0]
    desde = ctx.desde(CODIGO)
    buscador = None
    for n in sorted(cuerpo.legislaturas, reverse=True):
        rom, ini, fin = cuerpo.legislaturas[n][:3]
        if desde and fin and fin < desde:
            return
        # Todo el listado de la legislatura antes de descargar nada: la sesión APEX caduca si se deja parada.
        filas, desplazamiento = [], 0
        while True:
            try:
                buscador = buscador or _Buscador(ctx)
                pagina, n_filas = buscador.pagina_resultados(CODIGO_FUENTE[n], desplazamiento)
            except Exception:  # sesión APEX caducada o respuesta rara: una sesión nueva y otro intento
                buscador = _Buscador(ctx)
                pagina, n_filas = buscador.pagina_resultados(CODIGO_FUENTE[n], desplazamiento)
            filas += pagina
            if n_filas < POR_PAGINA or (desde and pagina and pagina[-1]["fecha"] < desde):
                break
            desplazamiento += POR_PAGINA
        vistos = set()
        for f in filas:
            if f["num"] in vistos:
                continue
            vistos.add(f["num"])
            if desde and f["fecha"] < desde:
                return
            if cuerpo.legislatura_de(f["fecha"]) != n:
                ctx.log(f"  Cataluña: DSPC-P {f['num']}/{rom} con fecha {f['fecha']} fuera de la legislatura")
                continue
            sesiones = re.sub(r"\s+(?=\d+\.\d+,)", "; ", f["sesiones"])
            yield Documento(CODIGO, f["fecha"], f["url"], sesion=f["num"], formato="pdf", idioma="ca",
                            titulo=f"Diari de Sessions del Parlament de Catalunya, sèrie P, núm. {f['num']} "
                                   f"({rom} legislatura)" + (f": sessió {sesiones}" if sesiones else ""),
                            legislatura=n, extra={"id_document": f["id"], "sessions": f["sesiones"]})


def documentos(ctx):
    for i, doc in enumerate(_diarios(ctx), 1):
        yield doc
        if ctx.limite and i >= ctx.limite:
            return


# ---------------------------------------------------------------- totales por reglas

EXP = r"\d{3}-\d{5}/\d{2}"
RUIDO_RE = re.compile(  # números de página y cabeceras («DSPC-P 110 23 de juliol de 2026», «Sessió 50.3», «S essió 50.3»)
    r"[ \t\ufeff]*(?:\d{1,4}|DSPC-P \d+(?: \d{1,2} d\S{1,3} ?\w+ de \d{4})?|\d{1,2} d\S{1,3} ?\w+ de \d{4}|"
    r"S ?essi(?:ó|ons) [\d.]+(?:(?:,| i) [\d.]+)*)[ \t]*")
ENCABEZADO_RE = re.compile(rf"^(?P<titulo>[A-ZÀ-Ú«].{{5,600}}?)\s+(?P<exps>{EXP}(?:\s*(?:,| i)\s*{EXP})*)$")
MARCA_RE = re.compile(r"\x01(\d+)\x01")
ORADOR_RE = re.compile(r"(?:El|La) (?:vice)?president[a]?(?: (?:primer|primera|segon|segona))?$")
VOTA_RE = re.compile(r"Comença la votació")
# Fórmula de la Presidencia antes de cada votación («Votem el punt 2», «Conjuntament votarem els punts 10 i 11»);
# no las frases de los oradores («Votarem a favor…»).
FRASE_VOTEM_RE = re.compile(
    r"(?:^|[.?!)]\s)((?:(?:I|Ara|Doncs|Bé|Molt bé|Seguidament|A continuació)[,.]?\s+)*"
    r"(?:(?:[Cc]onjuntament,?\s+)?[Vv]ot(?:em|arem)|[Pp]assem a votar|[Ss]otmetem a votació)\b"
    r"(?!\s+(?:a favor|en contra|que|sí|no|abstenció|diferent|igual|el que|tot)\b)[^.]{0,300})")
def _paraules():
    """Números en letra del 0 al 199 («cap», «quaranta-dos», «cent deu») -> valor."""
    u = ["", "un", "dos", "tres", "quatre", "cinc", "sis", "set", "vuit", "nou", "deu", "onze", "dotze", "tretze",
         "catorze", "quinze", "setze", "disset", "divuit", "dinou"]
    desenes = {2: "vint", 3: "trenta", 4: "quaranta", 5: "cinquanta", 6: "seixanta", 7: "setanta", 8: "vuitanta",
               9: "noranta"}
    base = {"cap": 0, "una": 1, "dues": 2, **{p: i for i, p in enumerate(u) if p}}
    for d, p in desenes.items():
        base[p] = d * 10
        for i in range(1, 10):
            for q in ([u[i], "una", "u"] if i == 1 else [u[i], "dues"] if i == 2 else [u[i]]):
                base[f"{p}-i-{q}" if d == 2 else f"{p}-{q}"] = d * 10 + i
    return {**base, "cent": 100, **{f"cent {p}": 100 + v for p, v in base.items() if v}}


PARAULES = _paraules()
NUM = r"\b(\d+|" + "|".join(sorted(map(re.escape, PARAULES), key=len, reverse=True)) + r")"
A_FAVOR_RE = re.compile(NUM + r"\s+(?:vots?\s+)?(?:a\s+favor|afirmatius|positius|favorables)", re.I)
EN_CONTRA_RE = re.compile(NUM + r"\s+(?:vots?\s+)?(?:en\s+contra|negatius)", re.I)
ABST_RE = re.compile(NUM + r"\s+abs\W{0,3}tenci(?:ó|ons)", re.I)
NO_VOTAN_RE = re.compile(NUM + r"\s+diputats?(?:\s+o\s+diputades)?\s+(?:que\s+)?no\s+han\s+votat", re.I)
# Resultado dicho por la Presidencia. La negación va pegada al verbo («Aquest punt no ha quedat aprovat», «tampoc
# han quedat aprovats», «no queden aprovats», «tampoc s'ha aprovat»): sin ella, «no ha quedat aprovat» se leía como
# aprobado (casi todos los errores de la XIV).
RESULTADO_RE = re.compile(
    r"(?:\b(?P<neg>no|tampoc)\s+(?:s['’]\s?)?(?:(?:ha|han|queda|queden|resta|resten|està|estan)\s+)?"
    r"(?:(?:quedat|estat)\s+)?)?"
    r"\b(?P<verbo>aprova|rebutja|valida|convalida|deroga)(?:t|da|ts|des)\b", re.I)
# Frase que ya anuncia la votación siguiente: su «aprovat» no es de esta votación.
ANUNCIO_RE = re.compile(r"\b(?:[Vv]ot(?:em|arem)|[Pp]assem a|[Ss]otmetem|[Cc]omença la votació)\b")
# La Presidencia se corrige a sí misma («ha quedat aprovat… Perdó, ha quedat rebutjat»): vale el último verbo.
CORRECCION_RE = re.compile(r"perd[óo]\b|disculp|\bai\b|rectific|m['’]he equivocat|t(?:é|enen)[^.]{0,20}raó|ja no sé", re.I)
# Decretos ley: primero se vota la validación («ha estat validat / derogat») y, si algún grupo lo pide, la tramitación
# como proyecto de ley, cuyo resultado es «(no) es tramitarà com a projecte de llei» (y no el «ha quedat validat» que
# se repite en la misma frase). Qué se vota lo dice la Presidencia antes: la última mención de una u otra.
TRAMITACION_RE = re.compile(
    r"\b(no\s+)?es\s+tramitar(?:à|an)\s+(?:\S+\s+){0,4}?com\s+a\s+projectes?\s+de\s+llei", re.I)
TRAMITAR_RE = re.compile(r"(?:tramit\w*|tràmit)[^.]{0,80}?com a (?:projecte de llei|decret llei)", re.I)
VALIDACION_RE = re.compile(r"\b(?:con)?validació\b", re.I)
# Consecuencias que no son el resultado de lo votado: «(atès que l'esmena a la totalitat ha estat aprovada,) aquesta
# iniciativa queda rebutjada», «el decret llei que hem aprovat», «queda aprovat, com hem dit, el Decret llei…».
CONSECUENCIA_RE = re.compile(
    r"\b(?:aquesta|la)\s+(?:iniciativa|proposició(?:\s+de\s+llei)?|projecte(?:\s+de\s+llei)?)\s+"
    r"(?:queda|resta)\s+rebutjad[ao]|\bque\s+hem\s+aprovat|queda\s+aprovat,\s+com\s+hem\s+dit", re.I)
MAYORIA_RE = re.compile(r"majoria\s+(absoluta|qualificada|reforçada|de\s+(?:dos\s+terços|tres\s+cinquenes))", re.I)
TIPOS = [  # (patrón sobre el título, tipo_iniciativa, tipo_votacion)
    (r"pressupost", "presupuesto", None), (r"Decret llei", "dl", "convalidacion"),
    (r"Projecte de llei", "pl", None), (r"Proposició de llei", "ppl", None),
    (r"^Proposta de resolució", "pnl", "pnl"), (r"^Moció", "mocion", "mocion"),
    (r"investidura|qüestió de confiança|moció de censura", "investidura", "investidura"),
    (r"^(Designació|Elecció|Procediment per a (designar|elegir)|Proposta de designació|Situació de compatibilitat)",
     "organizacion", "nombramiento"),
    (r"^(Informe|Compareixença|Debat (general|sobre)|Sessió informativa|Dictamen de la Comissió d.Investigació)",
     "control", "control"),
]


def _n(x):
    return int(x) if x.isdigit() else PARAULES[x.lower()]


def _es_titulo(linea):
    return bool(re.match(r"[A-ZÀ-Ú«]", linea)) and len(linea) < 600 and not linea.endswith((".", ":", "?", "!"))


def _flujo(texto):
    """Texto seguido del Diario, con los epígrafes cambiados por marcas \\x01n\\x01.

    El epígrafe es un párrafo propio: el título (una o varias líneas, sin punto final) y el expediente al final de
    la última línea o en una línea aparte. Vale para la salida de pdftotext (poppler o xpdf) y de pypdf.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    texto = re.sub(r"(?<=[a-zà-úç·])-\n(?=[a-zà-úç])", "", texto)  # guionado de final de línea (poppler)
    partes, epigrafes, en_bloque = [], [], 0  # en_bloque: líneas seguidas (sin línea en blanco) al final de partes
    for linea in texto.split("\n"):
        linea = " ".join(linea.split())
        if not linea:
            en_bloque = 0
            continue
        if RUIDO_RE.fullmatch(linea):
            continue
        m = ENCABEZADO_RE.match(linea)
        solo = re.fullmatch(rf"{EXP}(?:\s*(?:,| i)\s*{EXP})*", linea)
        if not (solo or (m and not m.group("titulo").rstrip().endswith((".", ":", "?", "!")))):
            partes.append(linea)
            en_bloque += 1
            continue
        # Título: la parte de la línea antes del expediente y las líneas anteriores del mismo párrafo que no
        # cierran frase (pdftotext de xpdf: una línea por párrafo; poppler: el párrafo partido en líneas).
        trozos, quitadas = ([m.group("titulo")] if m else []), 0
        while quitadas < min(en_bloque, 5 - len(trozos)):
            previa = partes[-1 - quitadas]
            if previa.startswith("\x01") or previa.endswith((".", ":", "?", "!", "»")) or ORADOR_RE.match(previa):
                break
            trozos.insert(0, previa)
            quitadas += 1
        titulo = " ".join(trozos)
        if not _es_titulo(titulo):
            partes.append(linea)
            en_bloque += 1
            continue
        del partes[len(partes) - quitadas:]
        titulo = re.sub(r"\s*\((?:continuació|continua- ?ció)\)\s*$", "", titulo).strip()
        epigrafes.append((titulo, re.findall(EXP, m.group("exps") if m else linea)))
        partes.append(f"\x01{len(epigrafes) - 1}\x01")
        en_bloque = 0
    return " ".join(partes), epigrafes


def votaciones_diario(doc, texto):
    """Votaciones de un DSPC-P con sus totales, por las frases fijas que siguen a «Comença la votació»."""
    flujo, epigrafes = _flujo(texto)
    marcas = [(m.start(), m.end(), int(m.group(1))) for m in MARCA_RE.finditer(flujo)]
    votos = list(VOTA_RE.finditer(flujo))
    salida, fin_anterior = [], 0
    for i, m in enumerate(votos):
        previas = [x for x in marcas if x[0] < m.start()]
        if not previas:
            continue
        _ini_ep, fin_ep, idx = previas[-1]
        tope = min([votos[i + 1].start() if i + 1 < len(votos) else len(flujo)]
                   + [x[0] for x in marcas if x[0] > m.end()][:1])
        ventana = flujo[m.end():min(tope, m.end() + 450)]
        frases = re.split(r"(?<=[.])\s+(?=[A-ZÀ-Ú])", ventana.strip(" .–"), maxsplit=2)
        k = 0
        if len(frases) > 1 and not re.search(
                r"a\s+favor|en\s+contra|abs\W{0,3}tenci|unanimitat|afirmatius|negatius", frases[0]):
            k = 1
        cuenta = frases[k]
        # El resultado va en la frase de los votos, en la anterior o en la siguiente («Per tant, no queden aprovats…»),
        # pero no en la que ya anuncia la votación siguiente.
        resultado_txt = " ".join(frases[:k + 1] + [f for f in frases[k + 1:k + 2] if not ANUNCIO_RE.search(f)])
        af, ec, ab = A_FAVOR_RE.search(cuenta), EN_CONTRA_RE.search(cuenta), ABST_RE.search(cuenta)
        unanimitat = "unanimitat" in cuenta
        if not (af or ec or ab or unanimitat):
            continue
        a_favor, en_contra, abst = (_n(x.group(1)) if x else None for x in (af, ec, ab))
        if sum(x or 0 for x in (a_favor, en_contra, abst)) > 135:
            continue
        previo = flujo[max(fin_anterior, fin_ep):m.start()]
        # Cada «aprovat / rebutjat / validat / derogat» (con su negación) en orden, o el «(no) es tramitarà com a
        # projecte de llei» si lo votado es la tramitación de un decreto ley: vale el primero, o el último si la
        # Presidencia se corrige.
        limpio = CONSECUENCIA_RE.sub(lambda x: " " * len(x.group(0)), resultado_txt)
        tramites = [x.end() for x in TRAMITAR_RE.finditer(previo)]
        validaciones = [x.end() for x in VALIDACION_RE.finditer(previo)]
        dichos = []
        if tramites and (not validaciones or tramites[-1] > validaciones[-1]):
            dichos = [(x.start(), not x.group(1)) for x in TRAMITACION_RE.finditer(limpio)]
        if not dichos:
            dichos = [(x.start(), (x.group("verbo").lower() not in ("rebutja", "deroga")) != bool(x.group("neg")))
                      for x in RESULTADO_RE.finditer(limpio)]
        resultado = None
        if dichos:
            aprueba = dichos[-1][1] if CORRECCION_RE.search(resultado_txt) else dichos[0][1]
            resultado = "aprobada" if aprueba else "rechazada"
        elif unanimitat:
            resultado = "aprobada"
        if a_favor is None and resultado is None:  # frase que no se entiende del todo: mejor no dar nada
            continue
        votem = FRASE_VOTEM_RE.findall(previo)
        subtitulo = votem[-1].strip(" .") if votem else None
        titulo, exps = epigrafes[idx]
        tipo_ini = tipo_vot = None
        for patron, ti, tv in TIPOS:
            if re.search(patron, titulo, 0 if patron.startswith("^") else re.I):
                tipo_ini, tipo_vot = ti, tv
                break
        if tipo_ini in ("pl", "ppl", "presupuesto") and subtitulo:
            tipo_vot = ("totalidad" if re.search(r"totalitat", subtitulo + " " + titulo, re.I) else
                        "enmiendas" if re.search(r"esmen|vots? particulars?", subtitulo, re.I) else
                        "articulado" if re.search(r"article|disposici", subtitulo, re.I) else
                        "conjunto" if re.search(r"conjunt|final", subtitulo, re.I) else None)
        no_votan = NO_VOTAN_RE.search(resultado_txt)
        extra = {"expedientes": exps} if len(exps) > 1 else {}
        mayoria = None
        if resultado and a_favor is not None and en_contra is not None and \
                (resultado == "aprobada") != (a_favor > en_contra):
            # El resultado dicho no cuadra con la mayoría simple: se respeta si el texto habla de una mayoría
            # reforzada (Estatut, ley electoral, nombramientos…); si no, se deja y se avisa.
            mq = MAYORIA_RE.search(previo[-600:] + " " + resultado_txt)
            if mq:
                mayoria = "absoluta" if mq.group(1).lower() == "absoluta" else None
                extra["mayoria_texto"] = mq.group(0)
            else:
                extra["aviso_resultado"] = (f"el Diario dice {resultado} con {a_favor} a favor y {en_contra} en contra: "
                                            f"«{resultado_txt[:200]}»")
        salida.append(Votacion(
            CODIGO, doc.fecha, titulo, sesion=doc.sesion, numero=len(salida) + 1, legislatura=doc.legislatura,
            subtitulo=subtitulo, expediente=exps[0] if exps else None, tipo_iniciativa=tipo_ini or "otro",
            tipo_votacion=tipo_vot, a_favor=a_favor, en_contra=en_contra, abstenciones=abst,
            no_votan=_n(no_votan.group(1)) if no_votan else None, resultado=resultado, mayoria=mayoria,
            url=doc.url, fuente="pdf-reglas", extra=extra))
        fin_anterior = m.end()
    return salida


def descargar(ctx):
    """Totales de cada votación del Pleno sacados del DSPC-P con reglas (sin voto por grupo)."""
    n = 0
    for doc in _diarios(ctx):
        raw = ctx.fetch(doc.url, cache=f"{CODIGO}/docs/{ctx.clave(doc.url)}.pdf")
        for v in votaciones_diario(doc, ctx.pdf_texto(raw, layout=False)):
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
