"""Juntas Generales de Álava, Bizkaia y Gipuzkoa (parlamentos forales).

Las tres cámaras publican los totales de cada votación del Pleno, cada una a su manera:

- Álava (jjggalava.eus, Liferay con certificado mal encadenado): el buscador de expedientes
  responde en JSON (`/expedientes?p_p_id=…WSSearchPortlet&p_p_lifecycle=2&p_p_resource_id=
  /integration-search/search-expedients`, 5 por página, filtro por tipo `C-9`, `B-1`…). La ficha de
  cada expediente (`/detalle-exp?t=E&leg=12&num=3609`, HTML sin JavaScript) lista sus trámites y,
  en los del Pleno, «Resultados de la votación» con emitidos, a favor, en contra, abstenciones y
  nulos. Se recorren los tipos que pueden llegar al Pleno (normativos, mociones, censura,
  declaraciones…) de la legislatura 12 (2023) hacia atrás; hay totales desde la VIII (2007) al
  menos. Solo totales y resultado, sin voto por grupo. Las votaciones en comisión se descartan.
  Cada expediente se devuelve también como Iniciativa.
- Gipuzkoa (bngipuzkoa.eus, JSP sin JavaScript): la relación de sesiones del Pleno
  (`relacion_de_sesiones_por_organos_resultados.jsp?legislatura=12&desttra=15&…&indice=0`, 10
  sesiones por página) trae el orden del día con el expediente de cada asunto y, en parte de
  ellos, «Resultado de la votación» (presentes, sí, no, abstenciones). Solo totales, sin
  resultado explícito. Desde julio de 2005. No todos los asuntos votados traen el resultado:
  las sesiones sin ninguno se ofrecen como documentos (acta en PDF) para el LLM.
- Bizkaia (jjggbizkaia.eus, Liferay): no hay buscador de iniciativas usable (la página
  /es/iniciativas es solo una ficha vacía). La relación anual de plenos (`/es/plenos`, recurso
  `cambioAnyo`, JSON) enlaza las actas en PDF de apps.bizkaia.eus/SIGP, bilingües a dos columnas.
  Las actas recientes (comprobado de 2013 a 2026) traen un bloque fijo «VOTACIÓN / Votos
  Emitidos: N / Votos a favor: N (grupos) / Votos en contra … / Abstenciones … / ACUERDOS» (desde
  2021 con un guion delante de cada línea), que se lee con reglas (fuente «pdf-reglas») sobre el
  texto en el orden del PDF (pdftotext -raw: así el bloque en castellano sale entero y el de euskera
  detrás): totales, sentido de cada grupo (las siglas bilingües del acta, EAb/NV, EHB, SV/ES,
  GPV/BTP, GM/TB-EB…, se pasan al nombre del grupo para que se reconozca el partido), el resultado
  cuando el acuerdo lo dice, el asunto de la última ficha («Iniciativa Originaria…») y la frase que
  presenta la votación. De 2011 a 2020 casi todas las votaciones van en una tabla sin grupos
  («Botoak guztira / Votos emitidos 49 / Aldekoak / Votos a favor 22…», resultado en «Queda, por
  tanto, aprobado»), que se lee igual; hasta 2013 no hay ficha y el asunto es el enunciado del punto
  del orden del día («…que dice: “Debate y Resolución de la PROPOSICIÓN NO DE NORMA…”»). Las actas
  sin ninguna votación leída se ofrecen como documentos para el LLM. Solo actas del Pleno, no de
  los plenos de control.

`sesion`: número oficial del Pleno en Álava («Pleno Nº 108», se repite en cada legislatura) y
AAAAMMDD en Gipuzkoa y Bizkaia. `numero`: en Álava, número de expediente × 100 + orden de la
votación dentro del expediente en esa sesión (no es el orden real en la sesión); en Gipuzkoa y
Bizkaia, sesión del día × 10000 + orden en el acta o en el orden del día.

Recogida incremental: Álava descarta los expedientes cerrados antes de `desde` y deja de paginar
un tipo cuando los expedientes se abrieron más de un año antes; Gipuzkoa y Bizkaia recorren las
sesiones de la más reciente a la más antigua y paran en `desde`.
"""

import html
import json
import re
import urllib.parse
from datetime import date, timedelta

from ...territorio import NUM_JUNTAS, Cuerpo
from ..modelo import Documento, Iniciativa, Votacion, VotoGrupo

ACTIVO = True
NOTAS = __doc__

# Mandatos forales: coinciden con las elecciones municipales (fechas de constitución de los
# ayuntamientos, como territorio.MANDATOS_LOCALES, que no llega tan atrás).
MANDATOS_FORALES = {
    5: ("V", "1995-06-17", "1999-07-03"),
    6: ("VI", "1999-07-03", "2003-06-14"),
    7: ("VII", "2003-06-14", "2007-06-16"),
    8: ("VIII", "2007-06-16", "2011-06-11"),
    9: ("IX", "2011-06-11", "2015-06-13"),
    10: ("X", "2015-06-13", "2019-06-15"),
    11: ("XI", "2019-06-15", "2023-06-17"),
    12: ("XII", "2023-06-17", None),
}

ALAVA = "https://www.jjggalava.eus"
BIZKAIA = "https://jjggbizkaia.eus"
GIPUZKOA = "https://www.bngipuzkoa.eus/WAS/CORP/DJGPortalWEB"


def _cuerpo(clave, nombre, web):
    return Cuerpo(f"jjgg-{clave}", NUM_JUNTAS[clave], f"Juntas Generales de {nombre}", f"JJGG {nombre}",
                  "provincial", "PV", 51, dict(MANDATOS_FORALES), web, "Juntas Generales")


CUERPOS = [
    _cuerpo("alava", "Álava", f"{ALAVA}/expedientes"),
    _cuerpo("bizkaia", "Bizkaia", f"{BIZKAIA}/es/plenos"),
    _cuerpo("gipuzkoa", "Gipuzkoa", f"{GIPUZKOA}/relacion_de_sesiones_por_organos.jsp?idioma=es"),
]
POR_CODIGO = {c.codigo: c for c in CUERPOS}


# ---------------------------------------------------------------------- utilidades

def _limpio(s):
    s = re.sub(r"(?s)<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _leg_de(fecha):
    for n, (_r, ini, fin) in sorted(MANDATOS_FORALES.items()):
        if ini <= fecha and (fin is None or fecha < fin):
            return n
    return None


def _hoy():
    return date.today().isoformat()


def _antes(fecha, dias):
    return (date.fromisoformat(fecha) - timedelta(days=dias)).isoformat()


class _Cupo:
    """Cuenta las votaciones devueltas para respetar ctx.limite."""

    def __init__(self, limite):
        self.limite = limite or 0
        self.n = 0

    def lleno(self):
        return bool(self.limite) and self.n >= self.limite


# ====================================================================== Álava

A_PORTLET = "es_alava_ws_tools_ws_search_portlet_WSSearchPortlet"
A_NS = f"_{A_PORTLET}_"
A_BUSQUEDA = (f"{ALAVA}/expedientes?p_p_id={A_PORTLET}&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
              f"&p_p_cacheability=cacheLevelPage&p_p_resource_id=%2Fintegration-search%2Fsearch-expedients")

# Tipos de expediente que pueden votarse en el Pleno -> clave de TIPOS_INICIATIVA.
A_TIPOS = {
    "C-9": "mocion", "B-1": "pl", "B-2": "ppl", "B-12": "pl", "B-9": "presupuesto", "B-11": "presupuesto",
    "B-6": "dl", "B-13": "dl", "B-3": "ilp", "B-4": "otro", "B-5": "acuerdo", "B-15": "acuerdo",
    "B-14": "acuerdo", "B-8": "control", "B-7": "organizacion", "B-10": "organizacion",
    "C-1": "control", "C-28": "control", "C-22": "control", "C-23": "control", "C-25": "control",
    "C-6": "investidura", "C-7": "investidura", "C-8": "investidura", "C-15": "investidura",
    "C-16": "organizacion", "C-19": "organizacion", "C-21": "acuerdo", "C-26": "acuerdo",
    "C-27": "acuerdo", "C-30": "acuerdo", "C-31": "acuerdo",
}
A_ESTADOS = {"AC": "aprobada", "RC": "rechazada"}
A_PLENO_RE = re.compile(r"^Pleno\b[^()]*?N\S*\s*(\d+)\s*\((\d{4}-\d{2}-\d{2})\)")
A_VOTO_RE = re.compile(r"<li>\s*Voto\s+([^:<]+?)\s*:\s*(\d+)")


def _a_expedientes(ctx, leg, tipo):
    """Expedientes de un tipo en una legislatura, del más reciente al más antiguo (5 por página)."""
    pagina = 1
    while True:
        url = f"{A_BUSQUEDA}&legislatura={leg}&{A_NS}currentPage={pagina}"
        raw = ctx.fetch(url, data={f"{A_NS}expedient-type": tipo}, inseguro=True,
                        headers={"X-Requested-With": "XMLHttpRequest"})
        datos = json.loads(raw.decode("utf-8"))
        lista = (datos.get("data") or {}).get("expedientes") or []
        yield from lista
        if len(lista) < 5 or pagina > 400:
            return
        pagina += 1


def _a_tipo_votacion(bloque, tipo_ini):
    b = bloque.lower()
    if b.startswith("enmienda a la totalidad") or "totalidad" in b[:40]:
        return "totalidad"
    if b.startswith(("enmienda", "voto particular")):
        return "enmiendas"
    if b.startswith("dictamen"):
        return "conjunto"
    if b.startswith("toma en consideraci"):
        return "toma_consideracion"
    if b.startswith("propuesta de resoluci"):
        return "control"
    if tipo_ini == "mocion":
        return "mocion"
    if tipo_ini == "dl":
        return "convalidacion"
    if tipo_ini == "investidura":
        return "investidura"
    return None


def _a_votaciones(html_ficha, exp, tipo_ini, url):
    """Votaciones del Pleno en la ficha HTML de un expediente de Álava."""
    cuerpo = "jjgg-alava"
    leg = exp["legislatura"]
    num = exp["numero_expediente"]
    orden = {}
    i = html_ficha.find('class="listado-tramites"')
    for bloque in re.split(r'<div class="bloque mb-5">', html_ficha[i:])[1:]:
        m = re.search(r'<h3 class="titulo-bloque">(.*?)</h3>', bloque, re.S)
        cab = _limpio(m.group(1)) if m else ""
        clase, _, autor_tramite = cab.partition("/")
        m = re.search(r"<h4>(.*?)</h4>", bloque, re.S)
        texto = _limpio(m.group(1)) if m else None
        for entrada in re.split(r'<div class="info-entrada">', bloque)[1:]:
            mt = re.search(r'<span class="tipo">(.*?)</span>', entrada, re.S)
            organo = _limpio(mt.group(1)) if mt else ""
            mp = A_PLENO_RE.match(organo)
            if not mp:
                continue
            me = re.search(r'<span class="estado ([A-Z]+)">(.*?)</span>', entrada, re.S)
            estado = me.group(1) if me else None
            votos = {k.strip().lower(): int(v) for k, v in A_VOTO_RE.findall(entrada)}
            resultado = A_ESTADOS.get(estado)
            if not votos and not resultado:
                continue  # decaída, retirada, debatida sin votación…
            sesion, fecha = int(mp.group(1)), mp.group(2)
            orden[sesion] = orden.get(sesion, 0) + 1
            principal = clase.strip().lower().startswith(("iniciativa", "moción", "mocion"))
            video = re.search(r'href="(https://mediateca\.jjggalava\.eus/watch\?[^"]+)"', entrada)
            yield Votacion(
                cuerpo=cuerpo, fecha=fecha, titulo=_limpio(exp.get("asunto")) or texto or "",
                sesion=sesion, numero=num * 100 + orden[sesion], legislatura=leg,
                subtitulo=None if principal else (f"{clase.strip()}: {texto}" if texto else clase.strip() or None),
                expediente=exp.get("expediente_editado"), tipo_iniciativa=tipo_ini,
                tipo_votacion=_a_tipo_votacion(clase.strip(), tipo_ini),
                autor=exp.get("nombre_grupo") or exp.get("autor") or None,
                a_favor=votos.get("favorable"), en_contra=votos.get("contrario"),
                abstenciones=votos.get("abstención", votos.get("abstencion")),
                presentes=votos.get("emitido"), resultado=resultado, url=url, fuente="html",
                extra={k: v for k, v in {
                    "organo": organo, "estado": _limpio(me.group(2)) if me else None,
                    "nulos": votos.get("nulo"), "autor_tramite": autor_tramite.strip() or None,
                    "video": html.unescape(video.group(1)) if video else None}.items() if v is not None},
            )


def _alava(ctx, cupo):
    cuerpo = "jjgg-alava"
    desde = ctx.desde(cuerpo)
    vistos = set()
    for leg in sorted(MANDATOS_FORALES, reverse=True):
        _rom, ini, fin = MANDATOS_FORALES[leg]
        if desde and fin and fin < desde:
            return
        for tipo, tipo_ini in A_TIPOS.items():
            for exp in _a_expedientes(ctx, leg, tipo):
                if cupo.lleno():
                    return
                apertura, cierre = exp.get("fecha_apertura") or "", exp.get("fecha_cierre")
                if desde and apertura and apertura < _antes(desde, 400):
                    break
                if desde and cierre and cierre < desde:
                    continue
                num = exp.get("numero_expediente")
                if not num or (leg, num) in vistos:
                    continue
                vistos.add((leg, num))
                url = f"{ALAVA}/detalle-exp?t=E&leg={leg}&num={num}"
                yield Iniciativa(
                    cuerpo=cuerpo, expediente=exp.get("expediente_editado") or f"{leg}/{num}",
                    titulo=_limpio(exp.get("asunto")) or "(sin título)", legislatura=leg,
                    tipo_iniciativa=tipo_ini, autor=exp.get("nombre_grupo") or exp.get("autor") or None,
                    fecha_presentacion=apertura or None, resultado=None, url=url,
                    extra={k: v for k, v in {
                        "tipo": exp.get("expediente_particular_texto"), "fecha_cierre": cierre,
                        "titulo_eu": _limpio(exp.get("asunto_e")) or None}.items() if v},
                )
                # La ficha de un expediente cerrado hace tiempo ya no cambia.
                cerrado = bool(cierre) and cierre < _antes(_hoy(), 30)
                ficha = ctx.fetch(url, cache=f"{cuerpo}/exp/{leg}_{num}.html" if cerrado else None,
                                  inseguro=True).decode("utf-8", "replace")
                for v in _a_votaciones(ficha, exp, tipo_ini, url):
                    if desde and v.fecha < desde:
                        continue
                    yield v
                    cupo.n += 1
                    if cupo.lleno():
                        return


# ====================================================================== Gipuzkoa

G_LISTA = f"{GIPUZKOA}/relacion_de_sesiones_por_organos_resultados.jsp"
G_PLENO = 15  # «desttra» del Pleno


def _g_tipo(texto):
    t = (texto or "").lower()
    for clave, tipo in (("proyecto de norma foral", "pl"), ("proposición de norma foral", "ppl"),
                        ("proposicion de norma foral", "ppl"), ("decreto foral", "dl"),
                        ("presupuesto", "presupuesto"), ("propuesta de resoluci", "pnl"),
                        ("proposición no de norma", "pnl"), ("moción de censura", "investidura"),
                        ("cuestión de confianza", "investidura"), ("diputado general", "investidura"),
                        ("diputada general", "investidura"), ("moción", "mocion"), ("mocion", "mocion"),
                        ("declaración institucional", "acuerdo"), ("dictamen", "acuerdo"),
                        ("iniciativa legislativa popular", "ilp"), ("iniciativa normativa popular", "ilp"),
                        ("política general", "control"), ("politica general", "control"),
                        ("comparecencia", "control"), ("pregunta", "control"), ("interpelaci", "control"),
                        ("informe", "control"), ("cuenta general", "control")):
        if clave in t:
            return tipo
    return "otro" if t else None


def _g_tipo_votacion(etiqueta, tipo_ini):
    e = (etiqueta or "").lower()
    if "enmienda" in e and "totalidad" in e:
        return "totalidad"
    if "enmienda" in e or "voto particular" in e:
        return "enmiendas"
    if "toma en consideraci" in e:
        return "toma_consideracion"
    if "convalidaci" in e:
        return "convalidacion"
    if "propuesta_resoluci" in e or "propuesta de resoluci" in e:
        return "pnl"
    if "moci" in e and tipo_ini == "mocion":
        return "mocion"
    return None


def _g_pagina(ctx, leg, indice, cachear):
    ini = MANDATOS_FORALES[leg][1]
    fin = MANDATOS_FORALES[leg][2] or f"{date.today().year + 1}-12-31"
    q = {"legislatura": leg, "desttra": G_PLENO, "fechadesde": f"01-01-{ini[:4]}",
         "fechahasta": f"31-12-{fin[:4]}", "indice": indice, "idioma": "es"}
    url = f"{G_LISTA}?{urllib.parse.urlencode(q)}"
    raw = ctx.fetch(url, cache=f"jjgg-gipuzkoa/lista/{leg}_{indice}.html" if cachear else None)
    return raw.decode("iso-8859-1")


def _g_sesiones(ctx, leg):
    """Sesiones del Pleno de una legislatura, de la más reciente a la más antigua."""
    cachear = MANDATOS_FORALES[leg][2] is not None and MANDATOS_FORALES[leg][2] < _antes(_hoy(), 60)
    primera = _g_pagina(ctx, leg, 0, cachear)
    m = re.search(r"P\S*gina\s+\d+\s+de\s+(\d+)", primera)
    paginas = int(m.group(1)) if m else 1
    for p in range(paginas - 1, -1, -1):
        h = primera if p == 0 else _g_pagina(ctx, leg, p * 10, cachear)
        dl = h[h.find('<dl class="sesiones">'):h.find("</dl>")]
        sesiones = re.findall(r"<dt>.*?(\d{2})-(\d{2})-(\d{4}):?\s*</dt>\s*<dd>(.*?)</dd>", dl, re.S)
        # Varias sesiones el mismo día: se numeran por orden de aparición.
        orden, lista = {}, []
        for d, mth, y, cuerpo_html in sesiones:
            fecha = f"{y}-{mth}-{d}"
            orden[fecha] = orden.get(fecha, 0) + 1
            lista.append((fecha, orden[fecha], cuerpo_html))
        yield from reversed(lista)


def _g_asuntos(cuerpo_html):
    for m in re.finditer(r'<p class="asunto">\s*Asunto\s*(\d+)\D*?</p>(.*?)(?=<p class="asunto">|</ol>)', cuerpo_html, re.S):
        n, bloque = int(m.group(1)), m.group(2)
        mt = re.search(r"<p>(.*?)</p>", bloque, re.S)
        titulo = _limpio(mt.group(1)) if mt else ""
        mp = re.search(r"<span>Proponente:</span>(.*?)</p>", bloque, re.S)
        me = re.search(r"<span>N\S*mero de Expediente:</span>\s*(?:<a href=\"([^\"]+)\"[^>]*>)?\s*([0-9]+/[A-Z]/[0-9]+/[0-9]+)", bloque, re.S)
        mti = re.search(r"<span>Tipo de Expediente:</span>(.*?)</p>", bloque, re.S)
        votos = []
        # Una lista puede traer varias votaciones seguidas, cada una encabezada por su etiqueta
        # («Votación enmiendas mantenidas», «Votación del dictamen en su conjunto»…). Los campos a
        # cero a veces se omiten: se quedan en None.
        for mu in re.finditer(r"Resultado de la votaci\S*</strong></p>\s*<ul>(.*?)</ul>", bloque, re.S):
            actual = None
            for et, k, v in re.findall(r'<span style="color: black">(.*?)</span>|<span>([^<]+)</span>\s*(\d+)', mu.group(1), re.S):
                if not k:
                    actual = (_limpio(et).lstrip("- ").strip(), {})
                    votos.append(actual)
                    continue
                if actual is None:
                    actual = ("", {})
                    votos.append(actual)
                actual[1][_limpio(k).rstrip(":").lower()] = int(v)
        yield {
            "n": n, "titulo": titulo, "proponente": _limpio(mp.group(1)) if mp else None,
            "expediente": me.group(2) if me else None,
            "url": urllib.parse.urljoin(G_LISTA, html.unescape(me.group(1))) if me and me.group(1) else None,
            "tipo": _limpio(mti.group(1)) if mti else None, "votos": votos,
        }


def _g_documentos(cuerpo_html):
    return {_limpio(t): urllib.parse.urljoin(G_LISTA, html.unescape(u))
            for u, t in re.findall(r'<a href="([^"]*BajarArchivoCifradoServlet[^"]*)"[^>]*>(.*?)<img', cuerpo_html, re.S)}


def _gipuzkoa(ctx, cupo, documentos=False):
    cuerpo = "jjgg-gipuzkoa"
    desde = ctx.desde(cuerpo)
    vistas = set()
    for leg in sorted((n for n in MANDATOS_FORALES if n >= 7), reverse=True):
        fin = MANDATOS_FORALES[leg][2]
        if desde and fin and fin < desde:
            return
        for fecha, orden_dia, cuerpo_html in _g_sesiones(ctx, leg):
            if desde and fecha < desde:
                return
            if cupo.lleno():
                return
            asuntos = list(_g_asuntos(cuerpo_html))
            sesion = int(fecha.replace("-", ""))
            docs = _g_documentos(cuerpo_html)
            con_votos = any(a["votos"] for a in asuntos)
            if documentos:
                if not con_votos and docs.get("Acta"):
                    yield Documento(cuerpo=cuerpo, fecha=fecha, url=docs["Acta"], sesion=sesion, formato="pdf",
                                    idioma="es", titulo=f"Acta del Pleno de {fecha}", legislatura=leg,
                                    extra={"diario": docs.get("Diario de Sesiones"), "orden_en_el_dia": orden_dia,
                                           "bilingue": True})
                    cupo.n += 1
                continue
            for a in asuntos:
                tipo_ini = _g_tipo(a["tipo"])
                if a["expediente"] and a["expediente"] not in vistas:
                    vistas.add(a["expediente"])
                    yield Iniciativa(cuerpo=cuerpo, expediente=a["expediente"], titulo=a["titulo"] or "(sin título)",
                                     legislatura=leg, tipo_iniciativa=tipo_ini, autor=a["proponente"],
                                     url=a["url"], extra={"tipo": a["tipo"]} if a["tipo"] else {})
                for k, (etiqueta, c) in enumerate(a["votos"], 1):
                    if "votos si" not in c and "presentes" not in c:
                        continue
                    yield Votacion(
                        cuerpo=cuerpo, fecha=fecha, titulo=a["titulo"] or a["expediente"] or "(sin título)",
                        sesion=sesion, numero=orden_dia * 10000 + a["n"] * 10 + k, legislatura=leg,
                        subtitulo=etiqueta or None, expediente=a["expediente"], tipo_iniciativa=tipo_ini,
                        tipo_votacion=_g_tipo_votacion(etiqueta, tipo_ini), autor=a["proponente"],
                        a_favor=c.get("votos si"), en_contra=c.get("votos no"), abstenciones=c.get("abstenciones"),
                        presentes=c.get("presentes"), url=docs.get("Acta") or a["url"], fuente="html",
                        extra={k2: v for k2, v in {"en_blanco": c.get("en blanco"), "nulos": c.get("nulos"),
                                                    "ficha": a["url"]}.items() if v is not None},
                    )
                    cupo.n += 1
                    if cupo.lleno():
                        return


# ====================================================================== Bizkaia

B_PORTLET = "net_bizkaia_iybnwinc_HistoricoPlenoPortavocesPortlet_INSTANCE_nACIOUjoBXHz"
B_ANYO = (f"{BIZKAIA}/es/plenos?p_p_id={B_PORTLET}&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view"
          f"&p_p_resource_id=cambioAnyo&p_p_cacheability=cacheLevelPage")
B_PRIMER_ANYO = 2000
# Bloque en castellano; desde 2021 cada línea lleva un guion delante («- Votos a favor: 14 (EHB, EB)»), en
# 2015-2018 a veces un «•», y el bloque en euskera («Botoak guztira / Aldekoak / Aurkakoak / Abstentzinoak») va
# detrás y no se lee.
B_VOTO_RE = re.compile(
    r"Votos\s+Emitidos:\s*(\d+)[\s\-–•]*Votos\s+a\s+favor:\s*(\d+)\s*(?:\(([^)]*)\))?[\s\-–•]*"
    r"Votos\s+en\s+contra:\s*(\d+)\s*(?:\(([^)]*)\))?[\s\-–•]*Abstenciones:\s*(\d+)\s*(?:\(([^)]*)\))?", re.I)
# 2011-2020: tabla con las etiquetas en los dos idiomas y la cifra detrás, casi siempre sin grupos
# («Botoak guztira / Votos emitidos 49 / Aldekoak / Votos a favor 22 / Aurkakoak / Votos en contra 20 /
# Abstentzioak / Abstenciones 7 / Balio bakoak / Votos nulos 0»), con números de página en medio («– 5 –»).
# Mismos grupos de captura que B_VOTO_RE.
_B_HUECO = r"(?:[\s\-–•./]|\d{1,3}(?!\d))*?"
_B_CIFRA = r"\s*:?\s*(\d+)\s*(?:\(([^)]*)\))?"
B_TABLA_RE = re.compile(
    r"Botoak\s+guztira\s*/\s*Votos\s+emitidos\s*:?\s*(\d+)" + _B_HUECO + r"Aldekoak\s*/\s*Votos\s+a\s+favor" + _B_CIFRA
    + _B_HUECO + r"Aurkakoak\s*/\s*Votos\s+en\s+contra" + _B_CIFRA + _B_HUECO + r"Abstentzi\w*\s*/\s*Abstenciones"
    + _B_CIFRA, re.I)
# Hasta 2013 no hay ficha («Iniciativa Originaria…»): el asunto es el enunciado del punto del orden del día.
B_PUNTO_RE = re.compile(r"(?i)punto(?:\s+[a-zé]+)?\s+del\s+orden\s+del\s+d[ií]a(?:,?\s+que\s+dice\s*:?|\s*:)")
B_CABECERA_RE = re.compile(r"(?i)(?:[a-z]\)\s*)?(?:votaci[oó]n|botoak|bozketea)\s*:?")  # «b) Votación: b) Botoak:»
# Pie de cada página del acta; se cuela en medio de lo que salta de página.
B_PIE_RE = re.compile(r"(?s)Egiaztapen\s+Kode.*?(?:jjggbizkaia\.eus\s*\d*|$)")
# Lo que no es un grupo dentro de sus paréntesis: el pie, el bloque en euskera de la otra columna cuando la
# lista salta de columna («(GM/TB, GPV/BTP, Botoak guztira: 50 Aldekoak: 39 (GM/TB, …») y los votos de un
# grupo que se divide («EB -2-»).
B_RUIDO_GRUPOS_RE = re.compile(
    B_PIE_RE.pattern + r"|(?i:Botoak\s+guztira|Aldekoak|Aurkakoak|Abstent\w+)\s*:?\s*\d*\s*\(?|-\s*\d+\s*-")
# Donde acaba el asunto: la ficha sigue en euskera («Jatorrizko ekimena», «3.- Ekimenari…») o salta de página.
B_FIN_ASUNTO = (r"Documento Principal:|Boletines:|Expediente:|INCIDENCIAS|Jatorrizko ekimena|"
                r"\d+\.-\s*(?:Ekimen|Hurrengo|Honako|Idatzi)|Egiaztapen|$")
# Siglas de los grupos en el bloque «VOTACIÓN» (en mayúsculas) -> nombre del grupo, que partidos.py reconoce.
B_GRUPOS = {
    "EAB/NV": "Euzko Abertzaleak / Nacionalistas Vascos", "NV": "Euzko Abertzaleak / Nacionalistas Vascos",
    "EHB": "EH Bildu", "EHBILDU": "EH Bildu", "EH BILDU": "EH Bildu", "BILDU": "Bildu",
    "SV": "Socialistas Vascos", "SV/ES": "Socialistas Vascos",
    "GPV": "Grupo Popular Vizcaíno", "GPV/BTP": "Grupo Popular Vizcaíno", "BTP/GPV": "Grupo Popular Vizcaíno",
    "PB": "Podemos Bizkaia", "EB": "Elkarrekin Bizkaia",
    "GM/TB": "Grupo Mixto",                                                # X: un juntero solo
    "GM/TB-PPB": "Grupo Mixto-PP de Bizkaia", "GM/TBPPB": "Grupo Mixto-PP de Bizkaia",  # XI
    "TB/GM-PPB": "Grupo Mixto-PP de Bizkaia",
    "GM/TB-EB": "Grupo Mixto-Elkarrekin Bizkaia",                           # XII
}


def _b_sesiones(ctx, anyo):
    cachear = anyo < date.today().year - 1
    raw = ctx.fetch(f"{B_ANYO}&_{B_PORTLET}_anyo={anyo}", cache=f"jjgg-bizkaia/anyo/{anyo}.json" if cachear else None,
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    datos = json.loads(raw.decode("utf-8", "replace"))
    salida = []
    for s in datos.get("historicoSesiones") or []:
        m = re.match(r"(\d{2})-(\d{2})-(\d{4})\s*(\d{2}):?(\d{2})?", s.get("fecha") or "")
        if not m:
            continue
        d, mth, y, hh, mm = m.groups()
        docs = {}
        for u in s.get("urlDocumento") or []:
            docs.setdefault((u.get("tipoDoc") or "").strip(), (u.get("urlDocumento") or "").replace(" ", "%20"))
        salida.append((f"{y}-{mth}-{d}", int(hh + (mm or "00")), docs))
    salida.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return salida


def _b_tipo(texto):
    t = (texto or "").lower()
    for clave, tipo in (("proposición no de norma", "pnl"), ("proposicion no de norma", "pnl"),
                        ("moción", "mocion"), ("mocion", "mocion"), ("proyecto de norma", "pl"),
                        ("proposición de norma", "ppl"), ("decreto foral norma", "dl"),
                        ("decreto foral normativo", "dl"), ("presupuesto", "presupuesto"),
                        ("convenio", "acuerdo"), ("declaración institucional", "acuerdo"),
                        ("comparecencia", "control"), ("cuenta general", "control")):
        if clave in t:
            return tipo
    return "otro" if t else None


def _b_siglas(clave):
    """Siglas conocidas seguidas en una clave («EAB/NVSV/ES», «EHB SV/ES»: falta la coma); None si sobra algo."""
    trozos, i = [], 0
    while i < len(clave):
        sigla = max((k for k in B_GRUPOS if clave.startswith(k, i)), key=len, default=None)
        if not sigla:
            return None
        trozos.append(sigla)
        i += len(sigla)
        while i < len(clave) and clave[i] == " ":
            i += 1
    return trozos


def _b_nombres(texto):
    """Nombres de los grupos de una lista del acta («EHB, EAb/NV, SV/ES»)."""
    for g in B_RUIDO_GRUPOS_RE.sub(",", texto or "").split(","):
        g = re.sub(r"\s*([/-])\s*", r"\1", re.sub(r"\s+", " ", g)).strip()  # «GM/TB-⏎PPB»
        g = re.sub(r"^\d+\s+", "", g)                                        # número de página
        siglas = _b_siglas(g.upper()) if g else None
        if siglas:
            yield from (B_GRUPOS[k] for k in siglas)
        elif g:
            yield g


def _b_grupos(favor, contra, abst):
    listas = {"si": favor, "no": contra, "abstencion": abst}
    sentidos = {}
    for sentido, texto in listas.items():
        for g in _b_nombres(texto):
            sentidos.setdefault(g, set()).add(sentido)
    return [VotoGrupo(grupo=g, sentido=(next(iter(s)) if len(s) == 1 else "dividido")) for g, s in sentidos.items()]


def _b_plano(texto):
    """Texto en una línea y sin los guiones de partir palabra de las actas antiguas («Viz- caino»)."""
    return re.sub(r"(?<=[a-záéíóúñ])- (?=[a-záéíóúñ])", "", re.sub(r"\s+", " ", texto))


def _b_frase(texto):
    """Última frase en castellano que presenta una votación («Se somete a votación la enmienda nº 2 del grupo…»;
    la de euskera que la sigue dice «bozketa»)."""
    plano = _b_plano(B_PIE_RE.sub(" ", texto))
    # Sin el número de página ni rótulos («VOTACIÓN BOTOAK», «INCIDENCIAS GORA-BEHERAK») delante, y sin el
    # acuerdo de la votación anterior ni el enunciado del punto («3.- Examen, debate y votación…»).
    frases = [re.sub(r"^\d+\s+|^(?:[A-ZÁÉÍÓÚÑ/-]{2,}\s+)+(?=[A-ZÁÉÍÓÚ][a-záéíóúñ])", "", f)
              for f in re.split(r"(?<=[.:])\s+", plano) if not re.match(r"ACUERDOS|\d+\.-", f)]
    frases = [f for f in frases if re.search(r"(?i)\b(?:vota(?:ci[oó]n|r|n|d[ao]s?)?|somete)\b", f)
              and re.search(r"[a-zA-Z]{3}", B_CABECERA_RE.sub("", f))]
    return frases[-1][:300] if frases else None


def _b_punto(texto):
    """(asunto, autor) del enunciado de un punto del orden del día («…que dice: “Debate y Resolución de la
    PROPOSICIÓN NO DE NORMA presentada por el Grupo Bildu relativa al Puerto de Santurtzi. (1)”»)."""
    plano = _b_plano(texto)
    # Hasta las comillas, las notas «(1)» o el texto en euskera.
    m = re.match(r"\s*[“\"«]?(.*?)\s*(?:\(\d\)|[”\"»]|Lehenengo|Lehendakari|Batzar|Ondoren|Hori eta gero|Horren"
                 r"|Jarraian|Quorumerako|$)", plano)
    asunto = m.group(1).strip(" .")[:400]
    if not re.search(r"(?i)\b(?:de|del|la|el|los|las|por|sobre|y)\b", asunto):
        asunto = ""  # el enunciado en castellano no va detrás: lo que sigue ya es euskera («Bildutako…»)
    autor = re.search(r"presentad[ao]s?\s+por\s+(?:el\s+|los\s+)?(Grupos?\s+.+?)\s+(?:relativ|sobre|en\s+relaci|,)",
                      asunto)
    return asunto or None, autor.group(1) if autor else None


def _b_votaciones(texto, fecha, sesion, url):
    """Votaciones de un acta de Bizkaia: el bloque fijo «VOTACIÓN» y la tabla de 2011-2020."""
    bloques = sorted([*B_VOTO_RE.finditer(texto), *B_TABLA_RE.finditer(texto)], key=lambda b: b.start())
    for k, m in enumerate(bloques, 1):
        fin_previo = bloques[k - 2].end() if k > 1 else 0
        ini_siguiente = bloques[k].start() if k < len(bloques) else len(texto)
        # La ficha del asunto votado es la última antes de la votación (las enmiendas y las propuestas de
        # resolución de un mismo asunto pueden estar muy lejos de ella); hasta 2013, el enunciado del punto.
        ctx_ini = texto.rfind("Iniciativa Originaria:", 0, m.start())
        punto = max((p.end() for p in B_PUNTO_RE.finditer(texto, 0, m.start())), default=-1)
        if punto > ctx_ini:
            titulo, autor = _b_punto(texto[punto:punto + 800])
            tipo_ini, expediente = _b_tipo(titulo), None
        else:
            trozo = re.sub(r"\s+", " ", texto[ctx_ini:m.start()]) if ctx_ini >= 0 else ""
            tipo = re.search(r"Iniciativa Originaria:\s*(.*?)\s*\(R\.E\.", trozo)
            asunto = re.search(r"Asunto:\s*(.*?)\s*(?:" + B_FIN_ASUNTO + ")", trozo)
            exped = re.search(r"Expediente:\s*([0-9]+/[A-Z]/[0-9]+/[0-9]+)", trozo)
            ficha_autor = re.search(r"Autor:\s*(.*?)\s*Asunto:", trozo)
            tipo_ini = _b_tipo(tipo.group(1) if tipo else None)
            titulo = asunto.group(1).strip() if asunto and asunto.group(1).strip() else (tipo.group(1) if tipo else None)
            expediente = exped.group(1) if exped else None
            autor = ficha_autor.group(1).strip() if ficha_autor else None
        frase = _b_frase(texto[max(fin_previo, m.start() - 3000):m.start()])
        # El acuerdo va detrás, a veces después del bloque en euskera: hasta la votación siguiente.
        posterior = texto[m.end():min(m.end() + 1200, ini_siguiente)]
        acuerdo = re.search(r"(?im)^\s*ACUERDOS\b(?:\s+ERABAGIAK)?[ \t]*\n?\s*([^\n]+)", posterior)
        resultado = None
        if acuerdo:
            a = acuerdo.group(1).lower()
            if a.startswith(("rechazar", "no aprobar", "no tomar", "desestimar", "no convalidar", "se rechaza",
                             "no se aprueba")):
                resultado = "rechazada"
            elif a.startswith(("aprobar", "convalidar", "ratificar", "tomar en consideración", "tomar en consideracion",
                               "se aprueba")):
                resultado = "aprobada"
        # Tras la tabla: «Queda, por tanto, rechazada.»
        queda = re.search(r"(?i)\bquedan?,?\s+(?:por\s+(?:lo\s+)?tanto,?\s+)?(aprobad|rechazad|desestimad)",
                          posterior[:600])
        if resultado is None and queda:
            resultado = "aprobada" if queda.group(1).lower() == "aprobad" else "rechazada"
        yield Votacion(
            cuerpo="jjgg-bizkaia", fecha=fecha, titulo=titulo or "(sin título)", sesion=sesion, numero=k,
            legislatura=_leg_de(fecha), subtitulo=frase, expediente=expediente,
            tipo_iniciativa=tipo_ini, tipo_votacion={"mocion": "mocion", "pnl": "pnl", "dl": "convalidacion"}.get(tipo_ini),
            autor=autor, a_favor=int(m.group(2)), en_contra=int(m.group(4)),
            abstenciones=int(m.group(6)), presentes=int(m.group(1)), resultado=resultado,
            grupos=_b_grupos(m.group(3), m.group(5), m.group(7)), url=url, fuente="pdf-reglas",
            extra={"acuerdo": acuerdo.group(1).strip()} if acuerdo else {},
        )


def _b_texto_acta(ctx, url):
    raw = ctx.fetch(url, cache=f"jjgg-bizkaia/actas/{ctx.clave(url)}.pdf")
    if raw[:5] != b"%PDF-":
        return ""
    # En el orden del flujo del PDF cada bloque de votación sale entero y seguido (sin -raw, el de 2021 en
    # adelante se mezcla con el de euskera de la otra columna).
    return ctx.pdf_texto(raw, layout=False, raw=True)


def _bizkaia(ctx, cupo, documentos=False):
    cuerpo = "jjgg-bizkaia"
    desde = ctx.desde(cuerpo)
    for anyo in range(date.today().year, B_PRIMER_ANYO - 1, -1):
        if desde and f"{anyo}-12-31" < desde:
            return
        orden = {}
        sesiones = _b_sesiones(ctx, anyo)
        # Orden dentro del día (de la más temprana a la más tardía) para numerar.
        for fecha, hora, _docs in sorted(sesiones):
            orden[(fecha, hora)] = len([1 for (f, h) in orden if f == fecha]) + 1
        for fecha, hora, docs in sesiones:
            if desde and fecha < desde:
                return
            if cupo.lleno():
                return
            acta = docs.get("Acta")
            if not acta:
                continue
            sesion = int(fecha.replace("-", ""))
            try:
                texto = _b_texto_acta(ctx, acta)
            except Exception as e:  # noqa: BLE001  (PDF roto o servidor caído: se sigue con el resto)
                ctx.log(f"  ! jjgg-bizkaia {fecha}: acta sin leer ({e})")
                continue
            votos = list(_b_votaciones(texto, fecha, sesion, acta))
            if documentos:
                if not votos:
                    yield Documento(cuerpo=cuerpo, fecha=fecha, url=acta, sesion=sesion, formato="pdf", idioma="es",
                                    titulo=f"Acta del Pleno de {fecha}", legislatura=_leg_de(fecha),
                                    extra={"diario": docs.get("Diario de Sesiones"), "hora": hora, "bilingue": True})
                    cupo.n += 1
                continue
            for v in votos:
                v.numero += orden[(fecha, hora)] * 10000
                yield v
                cupo.n += 1
                if cupo.lleno():
                    return


# ====================================================================== contrato

def _reparto(limite, partes):
    """Con límite (pruebas), cada Junta recibe su parte para que salgan las tres."""
    return -(-limite // partes) if limite else 0


def descargar(ctx):
    """Votaciones del Pleno e iniciativas de las tres Juntas Generales, de lo más reciente a lo más antiguo."""
    for fuente in (_alava, _gipuzkoa, _bizkaia):
        yield from fuente(ctx, _Cupo(_reparto(ctx.limite, 3)))


def documentos(ctx):
    """Actas del Pleno sin votaciones estructuradas (Gipuzkoa sin resultados; Bizkaia fuera de las reglas)."""
    yield from _gipuzkoa(ctx, _Cupo(_reparto(ctx.limite, 2)), documentos=True)
    yield from _bizkaia(ctx, _Cupo(_reparto(ctx.limite, 2)), documentos=True)


def texto(ctx, doc):
    """Texto del acta: PDF (Bizkaia y Gipuzkoa) descargado con caché. El de Bizkaia, en el orden del PDF, como lo
    leen las reglas (sin -raw se mezclan las dos columnas, castellano y euskera)."""
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/actas/{ctx.clave(doc.url)}.pdf")
    if raw[:5] == b"%PDF-":
        return ctx.pdf_texto(raw, layout=False, raw=doc.cuerpo == "jjgg-bizkaia")
    return _limpio(raw.decode("utf-8", "replace"))
