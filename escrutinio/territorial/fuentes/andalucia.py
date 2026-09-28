"""Parlamento de Andalucía: «Sentido del voto» del Pleno (un PDF por sesión) y catálogo de iniciativas.

Fuente: el buscador «Sentido del voto» (composicionyfuncionamiento/resultadosvotaciones.do) lista, por
legislatura y con `sinpaginacion=1`, un PDF por sesión (pdf.do?tipodoc=diario&id=…) que genera el
sistema de voto electrónico. Cada votación trae el título general del debate con el expediente
(«13-26/PNLP-000014, PROPOSICIÓN NO DE LEY…»), fecha y hora, número de votación, protocolo y sesión, una
tabla por grupo (presentes, votos delegados y totales de sí, no, abstenciones y blancos, ausentes) y la
lista nominal por grupo y sentido. El título, el proponente y el estado de cada iniciativa salen de su
ficha en el buscador de iniciativas (busquedaavanzada.do?numexp=…), que se devuelve como Iniciativa.

Cobertura: legislaturas IX (mayo de 2012) a XIII; antes no hay PDF, y en la XI falta el periodo del voto
telemático (sesiones 29 a 59, de marzo de 2020 a septiembre de 2021). Detalle: nominal, por grupo y
totales. `sesion` es el número oficial de la sesión plenaria (el del listado; el contador del sistema
de voto que imprime el PDF va en extra["sesion_pdf"]) y `numero`, el «VOTACIÓN Nº» del PDF.
Limitaciones:
- El PDF no dice qué se vota dentro del asunto (el «título particular» va siempre vacío) ni el
  resultado: `subtitulo` solo lleva la fase cuando el título la nombra («Debate final», «Toma en
  consideración»…) y `resultado` va a None.
- «Blancos» (presente sin pulsar) y ausentes van como no_vota. Hasta marzo de 2020 el voto delegado sale
  entre los ausentes con el sentido entre paréntesis («(SI)080 …»); desde 2021, en su sentido con «(*)».
- La tabla a veces no cuadra consigo misma (extra["descuadres"]); el voto de cada grupo sale de presentes
  + delegados y el total, de la columna de totales.
- Solo se da el voto nominal si cuadra, grupo a grupo, con la tabla y ningún aviso del PDF dice que un
  escaño figura con el nombre de otro diputado; si no (escaño sin nombre «... ..., ..», nota aclaratoria),
  queda el voto por grupo y extra["nominal_descartado"] dice por qué.
- Se lee el PDF en orden de contenido (`pdftotext -raw`, igual en poppler y xpdf; sin pdftotext,
  ctx.pdf_texto con pypdf): el modo -layout de xpdf 4 mezcla las columnas de los listados.
"""

import html
import re
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import ErrorDescarga
from ..modelo import Iniciativa, Votacion, VotoGrupo, VotoNominal

CODIGO = "parl-AN"
CUERPOS = [
    Cuerpo(CODIGO, num_parlamento("AN"), "Parlamento de Andalucía", "Parlamento (Andalucía)", "autonomico", "AN", 109,
           {9: (romano(9), "2012-04-19", "2015-04-16"),
            10: (romano(10), "2015-04-16", "2018-12-27"),
            11: (romano(11), "2018-12-27", "2022-07-14"),
            12: (romano(12), "2022-07-14", "2026-06-11"),
            13: (romano(13), "2026-06-11", None)},
           web="https://www.parlamentodeandalucia.es/webdinamica/portal-web-parlamento/composicionyfuncionamiento/"
               "resultadosvotaciones.do"),
]
NOTAS = ("PDF «Sentido del voto» del Pleno, uno por sesión, leído con reglas: nominal, por grupo y totales, "
         "IX-XIII legislatura (desde mayo de 2012; sin PDF de marzo de 2020 a septiembre de 2021). Título, "
         "proponente y estado de la ficha de cada iniciativa. Sin resultado oficial ni qué se vota dentro del asunto "
         "(el PDF no lo trae); blancos y ausentes = no_vota; el nominal se descarta si no cuadra con la tabla del "
         "grupo o una nota avisa de escaños con otro nombre (extra.nominal_descartado).")

WEB = "https://www.parlamentodeandalucia.es/webdinamica/portal-web-parlamento/"
LISTADO = (WEB + "composicionyfuncionamiento/resultadosvotaciones.do?seleccion=publicadosen&legislatura={}"
           "&desderango=&hastarango=&desdemes=&desdeanyo=&hastames=&hastaanyo=&terminos="
           "&accion=Ver+Sentido+del+voto&sinpaginacion=1")
PDF = WEB + "pdf.do?tipodoc=diario&id={}"
FICHA = WEB + "actividadparlamentaria/todaslasiniciativas/busquedaavanzada.do?numexp={}&accion=Ver+iniciativa"
PARALELO = 4

DOC_RE = re.compile(r'href="[^"]*pdf\.do\?tipodoc=diario&(?:amp;)?id=(\d+)"[^>]*>(.*?)</a>', re.S)
DOC_TXT_RE = re.compile(r"(\d\d)/(\d\d)/(\d{4}) Documento número (\d+) correspondiente a la sesión número (\d+)")
TITULO_RE = re.compile(r"^TÍTULO GENERAL DEL DEBATE:?$", re.M)
FECHA_RE = re.compile(r"^(\d\d)/(\d\d)/(\d{4})\s+(\d\d:\d\d:\d\d)$")
CAMPO_RE = re.compile(r"^(VOTACIÓN Nº|PROTOCOLO|SESIÓN)\s+(\d+)$")
CABECERA_RE = re.compile(r"^TOTAL((?:\s+[A-Z_]{1,3})*)$")
FILA_RE = re.compile(r"^(PRESENTES|VOTOS DELEGADOS|SI|NO|ABSTENCIONES|BLANCOS|TOTAL SI|TOTAL NO|TOTAL ABSTENCIONES|"
                     r"TOTAL BLANCOS|DIPUTADOS PRESENTES|DIPUTADOS AUSENTES|TOTAL DIPUTADOS)((?:\s+\d{3})+)$")
SECCION_RE = re.compile(r"^\*{3}\s*(.+?)\s*\*{3}$")
MARCA = r"\((?:\*|S[IÍ]|NO|ABS|BL)\)"
PARTE_RE = re.compile(rf"\s+(?={MARCA}\s?\d{{3}}(?:\s|$))|(?<!\))\s+(?=\d{{3}}(?:\s|$))")
GRUPO_RE = re.compile(r"^(?:G\.\s?P\.|GRUPO|DIPUTAD[OA]S NO ADSCRIT)", re.I)
ENTRADA_RE = re.compile(r"^(?:\((?P<pre>\*|S[IÍ]|NO|ABS|BL)\)\s?)?(?P<num>\d{3})(?:\s+(?P<nombre>.*?))?"
                        r"(?:\s*\((?P<post>\*|S[IÍ]|NO|ABS|BL)\))?$")
EXPEDIENTE_RE = re.compile(r"(?<![\d/-])(?:\d{1,2}-\d\d/)?[A-Z]{1,5}[-/]\d{6}\b")

SECCIONES = {"SÍ": "si", "SI": "si", "NO": "no", "ABSTENCIONES": "abstencion", "BLANCOS": "blanco", "AUSENTES": "ausente"}
MARCAS = {"SI": "si", "SÍ": "si", "NO": "no", "ABS": "abstencion", "BL": "no_vota"}
ESCANOS = 109

# Código del expediente -> tipo de iniciativa (modelo.TIPOS_INICIATIVA).
TIPOS = {
    "PNLP": "pnl", "PNLC": "pnl", "M": "mocion", "I": "mocion", "PL": "pl", "PPL": "ppl", "PPPL": "ppl",
    "ILP": "ilp", "ILPA": "ilp", "DL": "dl", "CCG": "control", "DG": "control", "ICG": "control", "DEC": "control",
    "OAPP": "control", "APP": "control", "CC": "organizacion", "COM": "organizacion", "PRR": "organizacion",
    "LEG": "organizacion", "CSRT": "acuerdo", "CONV": "acuerdo", "MUGP": "acuerdo", "RI": "acuerdo",
}
# Fase del debate que nombra el título -> (subtítulo, tipo de votación).
FASES = [
    (r"DEBATE DE TOTALIDAD|ENMIENDAS? A LA TOTALIDAD", "Debate de totalidad", "totalidad"),
    (r"TOMA EN CONSIDERACI[OÓ]N", "Toma en consideración", "toma_consideracion"),
    (r"RATIFICACI[OÓ]N.*TRAMITACI[OÓ]N COMO PROYECTO DE LEY", "Ratificación de la tramitación como proyecto de ley",
     "tramitacion_ley"),
    (r"CONVALIDACI[OÓ]N O DEROGACI[OÓ]N", "Convalidación o derogación", None),
    (r"DEBATE FINAL", "Debate final", None),
    (r"MOCI[OÓ]N CONSECUENCIA", "Moción consecuencia de interpelación", None),
]


# ---------------------------------------------------------------------------------------- listado


def _documentos(ctx, desde):
    """PDF de sesión publicados, del más reciente al más antiguo: (leg, fecha, sesion, documento, id)."""
    for leg in sorted(CUERPOS[0].legislaturas, reverse=True):
        _rom, _ini, fin, *_ = CUERPOS[0].legislaturas[leg]
        if desde and fin and fin < desde:
            return
        # Las legislaturas cerradas ya no cambian: su listado va a la caché.
        cache = f"{CODIGO}/listado-L{leg}.html" if fin else None
        pagina = ctx.fetch(LISTADO.format(leg), cache=cache).decode("latin-1")  # dice utf-8, pero es latin-1
        docs = []
        for ident, txt in DOC_RE.findall(pagina):
            txt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt))).strip()
            m = DOC_TXT_RE.search(txt)
            if m:
                d, mes, a, doc, ses = m.groups()
                docs.append((leg, f"{a}-{mes}-{d}", int(ses), int(doc), ident))
        for doc in sorted(set(docs), key=lambda x: (x[1], x[2], x[3]), reverse=True):
            if desde and doc[1] < desde:
                return
            yield doc


def _con_pdf(ctx, docs):
    """(doc, bytes del PDF), bajando PARALELO a la vez. La tanda se baja entera antes de devolverla, para no
    pedir PDF mientras se piden las fichas (nunca más de PARALELO peticiones a la vez)."""
    def bajar(doc):
        try:
            return doc, ctx.fetch(PDF.format(doc[4]), cache=f"{CODIGO}/L{doc[0]}/diario{doc[4]}.pdf")
        except (urllib.error.HTTPError, ErrorDescarga) as e:
            ctx.log(f"  {CODIGO}: no se pudo bajar el PDF {doc[4]} ({doc[1]}): {e}")
            return doc, None

    docs = iter(docs)
    with ThreadPoolExecutor(PARALELO) as ex:
        while True:
            tanda = [d for _, d in zip(range(PARALELO), docs)]
            if not tanda:
                return
            yield from list(ex.map(bajar, tanda))


def _texto_pdf(ctx, pdf):
    """Texto en el orden del contenido (el de los listados), con el mismo pdftotext que el resto (el de
    poppler, que es el de GitHub Actions). Sin pdftotext, el de ctx.pdf_texto (pypdf)."""
    texto = ctx.pdf_texto(pdf, raw=True)
    return texto if texto.strip() else ctx.pdf_texto(pdf, layout=False)


# ---------------------------------------------------------------------------------------- PDF


def _enteros(s):
    return [int(x) for x in s.split()]


def _entradas(linea):
    """Entradas de una línea del listado nominal: [(escaño, nombre, marca)]. Nombre vacío si no hay."""
    out = []
    for parte in PARTE_RE.split(linea):
        m = ENTRADA_RE.match(parte.strip())
        if not m:
            return None
        # «Rodríguez-Rubio Vázquez, Mª Teresa<f», «… < f>»: una marca pegada al nombre en algunos PDF.
        nombre = re.sub(r"\s*<\s*f\s*>?$", "", re.sub(r"\s+,", ",", (m.group("nombre") or "").strip()))
        if not re.search(r"[^\W\d_]{2}", nombre):
            nombre = ""
        out.append((m.group("num"), nombre, m.group("pre") or m.group("post")))
    return out


def _nombre_grupo(linea):
    # Una errata de la fuente: «grupooo PSOE DE ANDALUCÍA» (XI legislatura).
    return re.sub(r"(?i)^grupo+\s+(?!parlamentario|mixto)", "G.P. ", linea.strip())


def _bloque(lineas):
    """Una votación del PDF (las líneas desde el título general hasta la siguiente). Devuelve dict."""
    v = {"titulo": [], "filas": {}, "grupos_nominal": [], "nota": [], "particular": [], "obs": [], "malas": []}
    i, n = 0, len(lineas)
    while i < n and not FECHA_RE.match(lineas[i]):
        v["titulo"].append(lineas[i])
        i += 1
    if i == n:
        return None
    d, m, a, hora = FECHA_RE.match(lineas[i]).groups()
    v["fecha"], v["hora"] = f"{a}-{m}-{d}", hora
    i += 1
    estado, seccion_tabla = "cabecera", None
    grupo = sentido = None
    for linea in lineas[i:]:
        if linea.startswith("PARLAMENTO DE ANDALUCÍA"):
            continue
        if estado in ("cabecera", "particular"):
            m = CAMPO_RE.match(linea)
            if m and estado == "cabecera":
                v[{"VOTACIÓN Nº": "numero", "PROTOCOLO": "protocolo", "SESIÓN": "sesion"}[m.group(1)]] = int(m.group(2))
            elif linea.startswith("TÍTULO PARTICULAR DEL DEBATE"):
                estado = "particular"
            elif linea.startswith("PRESIDE LA VOTACIÓN"):
                v["preside"] = linea.split(":", 1)[1].strip() or None
                estado = "tabla"
            elif CABECERA_RE.match(linea):  # sin «PRESIDE» (no pasa, pero por si acaso)
                v["codigos"] = [c for c in CABECERA_RE.match(linea).group(1).split() if c.strip("_")]
                estado = "tabla"
            elif estado == "particular":
                v["particular"].append(linea)
            elif not re.match(r"^\(\*\)\s*NOTA ACLARATORIA$|^NOTA ACLARATORIA$", linea):
                v["nota"].append(linea)
            continue
        if estado == "tabla":
            m = CABECERA_RE.match(linea)
            if m:
                v["codigos"] = [c for c in m.group(1).split() if c.strip("_")]
                continue
            m = FILA_RE.match(linea)
            if m:
                etiqueta, valores = m.group(1), _enteros(m.group(2))
                if etiqueta in ("PRESENTES", "VOTOS DELEGADOS"):
                    seccion_tabla = etiqueta
                elif etiqueta in ("SI", "NO", "ABSTENCIONES", "BLANCOS"):
                    etiqueta = f"{seccion_tabla} {etiqueta}"
                v["filas"][etiqueta] = valores
                if etiqueta == "TOTAL DIPUTADOS":
                    estado = "nominal"
                continue
            (v["obs"] if re.search(r"[^\W\d_]{3}", linea) else v["malas"]).append(linea)
            continue
        # Listado nominal.
        m = SECCION_RE.match(linea)
        if m:
            sentido = SECCIONES.get(m.group(1).upper())
            if sentido is None or grupo is None:
                v["malas"].append(linea)
            continue
        if re.match(rf"^(?:{MARCA}\s?)?\d{{3}}(?:\s|$)", linea):
            entradas = _entradas(linea)
            if entradas is None or grupo is None or sentido is None:
                v["malas"].append(linea)
                continue
            for num, nombre, marca in entradas:
                # Voto delegado del formato antiguo: entre los ausentes, con el sentido entre paréntesis.
                s = MARCAS.get((marca or "").upper(), "no_vota") if sentido == "ausente" else sentido
                grupo["entradas"].append((num, nombre, s, marca))
            continue
        if GRUPO_RE.match(linea):
            grupo = {"nombre": _nombre_grupo(linea), "entradas": []}
            sentido = None
            v["grupos_nominal"].append(grupo)
        else:  # advertencias del servicio («Por error al ejercer el voto delegado…», «INCIDENCIA EN RESULTADOS»)
            (v["obs"] if re.search(r"[^\W\d_]{3}", linea) else v["malas"]).append(linea)
    return v


def votaciones_pdf(texto):
    """Votaciones (dicts en bruto) del texto `pdftotext -raw` de un PDF de sesión y el aviso del documento.

    El aviso es la nota que a veces precede a la primera votación («NOTA ACLARATORIA: … las votaciones que
    aparecen como realizadas por el diputado X las realiza realmente Y») o las observaciones finales sobre
    escaños con el nombre del diputado anterior: en esos casos el nombre del listado no es fiable.
    """
    lineas = []
    for ln in texto.replace("\f", "\n").splitlines():
        ln = ln.strip()
        # pypdf a veces parte la fila de la tabla: «PRESENTES» en una línea y los números en la siguiente.
        if lineas and re.fullmatch(r"\d{3}(?:\s+\d{3})*", ln) and re.fullmatch(r"[A-Z ]+", lineas[-1]) \
                and FILA_RE.match(lineas[-1] + " 000"):
            lineas[-1] += " " + ln
        elif ln:
            lineas.append(ln)
    inicios = [k for k, ln in enumerate(lineas) if TITULO_RE.match(ln)]
    out = []
    for a, b in zip(inicios, inicios[1:] + [len(lineas)]):
        v = _bloque(lineas[a + 1:b])
        if v:
            out.append(v)
    preambulo = " ".join(lineas[:inicios[0]] if inicios else lineas)
    aviso = None
    if "NOTA ACLARATORIA" in preambulo:
        aviso = preambulo[preambulo.index("NOTA ACLARATORIA"):].split("Nota aclaratoria sobre listados")[0].strip()
    elif any("entenderse sustituid" in ln for ln in lineas):
        aviso = "El PDF avisa de escaños que figuran con el nombre del diputado al que sustituyen"
    return out, aviso


FILAS = ("PRESENTES", "PRESENTES SI", "PRESENTES NO", "PRESENTES ABSTENCIONES", "PRESENTES BLANCOS", "VOTOS DELEGADOS",
         "VOTOS DELEGADOS SI", "VOTOS DELEGADOS NO", "VOTOS DELEGADOS ABSTENCIONES", "VOTOS DELEGADOS BLANCOS",
         "TOTAL SI", "TOTAL NO", "TOTAL ABSTENCIONES", "TOTAL BLANCOS", "DIPUTADOS AUSENTES", "TOTAL DIPUTADOS")
SENTIDOS_TABLA = {"si": "SI", "no": "NO", "abstencion": "ABSTENCIONES", "blanco": "BLANCOS"}


def _tabla(v):
    """Tabla por grupo y total: (por_grupo, total, descuadres) o (None, None, error).

    La tabla es redundante (total = suma de los grupos; TOTAL SÍ = presentes sí + delegados sí) y a veces
    no cuadra: una celda de un grupo mal, el total de ausentes o de diputados de más, un blanco o un voto
    delegado que no es de ningún grupo. El voto de cada grupo se toma de presentes + delegados (la celda
    «TOTAL» de grupo es la que falla) y el de la cámara, de la columna de totales; los descuadres quedan
    anotados.
    """
    codigos, filas = v.get("codigos"), v["filas"]
    if not codigos or any(f not in filas or len(filas[f]) != len(codigos) + 1 for f in FILAS):
        # Tabla rota (sin columnas de grupo): quedan los totales de la cámara, si están.
        if not all(f"TOTAL {x}" in filas for x in ("SI", "NO", "ABSTENCIONES")):
            return None, None, "tabla ilegible"
        total = {s: filas[f"TOTAL {x}"][0] for s, x in SENTIDOS_TABLA.items() if f"TOTAL {x}" in filas}
        for clave, fila in (("presentes", "PRESENTES"), ("delegados", "VOTOS DELEGADOS"), ("ausentes", "DIPUTADOS AUSENTES"),
                            ("diputados", "TOTAL DIPUTADOS")):
            total[clave] = filas[fila][0] if fila in filas else None
        if total["diputados"]:
            total["diputados"] = min(total["diputados"], ESCANOS)
        return None, total, ["tabla por grupos incompleta"]
    descuadres = [f"{f}: total {filas[f][0]}, suma de grupos {sum(filas[f][1:])}" for f in FILAS
                  if filas[f][0] != sum(filas[f][1:])]
    por_grupo = {}
    for k, c in enumerate(codigos, 1):
        g = {s: filas[f"PRESENTES {x}"][k] + filas[f"VOTOS DELEGADOS {x}"][k] for s, x in SENTIDOS_TABLA.items()}
        descuadres += [f"TOTAL {x} de {c}: {filas[f'TOTAL {x}'][k]}, presentes + delegados {g[s]}"
                       for s, x in SENTIDOS_TABLA.items() if filas[f"TOTAL {x}"][k] != g[s]]
        g.update(diputados=filas["TOTAL DIPUTADOS"][k], ausentes=filas["DIPUTADOS AUSENTES"][k])
        por_grupo[c] = g
    total = {s: filas[f"TOTAL {x}"][0] for s, x in SENTIDOS_TABLA.items()}
    total.update(presentes=filas["PRESENTES"][0], delegados=filas["VOTOS DELEGADOS"][0],
                 ausentes=filas["DIPUTADOS AUSENTES"][0], diputados=min(filas["TOTAL DIPUTADOS"][0], ESCANOS))
    return por_grupo, total, descuadres


def _nominal(v, por_grupo):
    """Nombre del grupo de cada código de la tabla y voto nominal si cuadra: (nombres, [VotoNominal] o None, motivo).

    Los grupos del listado van en el mismo orden que las columnas de la tabla (sin los que no tienen
    diputados). Cada grupo tiene que dar los mismos sí, no y abstenciones que la tabla, tantas entradas
    como diputados y todas con nombre.
    """
    con_diputados = [c for c in v["codigos"] if por_grupo[c]["diputados"]]
    gn = v["grupos_nominal"]
    if len(gn) != len(con_diputados):
        return {}, None, f"{len(gn)} grupos en el listado y {len(con_diputados)} en la tabla"
    nombres = {c: g["nombre"] for c, g in zip(con_diputados, gn)}
    nominal, motivos = [], []
    if v["malas"]:
        motivos.append(f"líneas del listado ilegibles: {' | '.join(v['malas'])[:120]}")
    for c, g in zip(con_diputados, gn):
        t = por_grupo[c]
        cuenta = Counter(s for _n, _nom, s, _m in g["entradas"])
        if any(cuenta[s] != t[s] for s in ("si", "no", "abstencion")) or len(g["entradas"]) != t["diputados"]:
            motivos.append(f"{c}: el listado no cuadra con la tabla")
        sin_nombre = [n for n, nom, _s, _m in g["entradas"] if not nom]
        if sin_nombre:
            motivos.append(f"{c}: escaño {', '.join(sin_nombre)} sin nombre")
        nominal += [VotoNominal(nom, g["nombre"], s if s in ("si", "no", "abstencion") else "no_vota")
                    for _n, nom, s, _m in g["entradas"]]
    if motivos:
        return nombres, None, "; ".join(motivos)
    return nombres, nominal, None


# ---------------------------------------------------------------------------------------- fichas


def _expedientes(titulo):
    return [e.rstrip(".") for e in EXPEDIENTE_RE.findall(titulo)]


def _ficha(ctx, expediente, cerrada):
    """Campos de la ficha de una iniciativa ({} si no la hay). «diarios»: PDF de sentido del voto que enlaza."""
    numexp = re.sub(r"/([A-Z]+)/(\d+)$", r"/\1-\2", expediente)
    try:
        pagina = ctx.fetch(FICHA.format(numexp), cache=f"{CODIGO}/iniciativas/{numexp.replace('/', '_')}.html",
                           caduca_dias=None if cerrada else 30).decode("utf-8", "replace")
    except (urllib.error.HTTPError, ErrorDescarga) as e:
        ctx.log(f"  {CODIGO}: ficha de {expediente}: {e}")
        return {}
    if "Expediente:" not in pagina:
        return {}
    campos = {}
    for dt, dd in re.findall(r'<dt class="col-sm-4">(.*?)</(?:dt|span)>\s*<dd class="col-sm-8">(.*?)</dd>', pagina, re.S):
        clave = html.unescape(re.sub(r"<[^>]+>", "", dt)).strip().rstrip(":")
        valor = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dd))).strip(" |")
        if valor:
            campos[clave] = valor
    campos["diarios"] = re.findall(r'tipodoc=diario&(?:amp;)?id=(\d+)"[^>]*>\s*Sentido del voto', pagina)
    campos["url"] = FICHA.format(numexp)
    return campos


def _fichas(ctx, expedientes, cerrada):
    with ThreadPoolExecutor(PARALELO) as ex:
        return dict(zip(expedientes, ex.map(lambda e: _ficha(ctx, e, cerrada), expedientes)))


def _resolver(ctx, expediente, leg, fecha, ident, cerrada):
    """Expediente publicado sin «legislatura-año/» («PNLP-000025»): el de la ficha que enlaza este mismo PDF."""
    for anyo in range(int(fecha[:4]), int(CUERPOS[0].legislaturas[leg][1][:4]) - 1, -1):
        candidato = f"{leg}-{anyo % 100:02d}/{expediente}"
        if ident in _ficha(ctx, candidato, cerrada).get("diarios", ()):
            return candidato
    return None


# ---------------------------------------------------------------------------------------- votaciones


def _tipo_iniciativa(codigo, titulo):
    if codigo == "PL" and "PRESUPUESTO DE LA COMUNIDAD" in titulo:
        return "presupuesto"
    if codigo in TIPOS:
        return TIPOS[codigo]
    for patron, tipo in ((r"ORDEN DEL D[IÍ]A|REGLAMENTO|REFORMA DEL PARLAMENTO", "organizacion"),
                         (r"^MOCI[OÓ]N|MOCI[OÓ]N CONSECUENCIA", "mocion"), (r"DECRETO[ -]LEY", "dl"),
                         (r"CUENTA GENERAL", "control"), (r"COMISI[OÓ]N DE INVESTIGACI[OÓ]N", "organizacion")):
        if re.search(patron, titulo):
            return tipo
    return "otro"


def _fase(titulo, tipo, codigo):
    """(subtítulo, tipo de votación) que se deducen del título general del debate."""
    for patron, sub, tv in FASES:
        if re.search(patron, titulo):
            return sub, tv
    tv = {"pnl": "pnl", "mocion": "mocion"}.get(tipo)
    if codigo in ("CCG", "DG", "ICG"):
        tv = "control"
    elif codigo in ("CC", "COM") or re.search(r"ORDEN DEL D[IÍ]A", titulo):
        tv = "organizacion"
    return None, tv


def _limpiar_titulo(titulo, expedientes):
    for e in expedientes:
        titulo = titulo.replace(e, " ")
    titulo = re.sub(r"\s+([,.])", r"\1", re.sub(r"\s+", " ", titulo))
    return titulo.strip(" ,.-") or None


def _votacion(b, titulo, ex, expediente, ficha, leg, sesion, numdoc, url, aviso):
    """Votacion a partir de una votación en bruto del PDF: (Votacion o None, motivo sin nominal o error)."""
    por_grupo, total, descuadres = _tabla(b)
    if total is None:
        return None, descuadres
    nombres, nominal, motivo = _nominal(b, por_grupo) if por_grupo else ({}, None, "tabla por grupos incompleta")
    if nominal and (aviso or b["nota"]):
        nominal, motivo = None, "nota aclaratoria: " + (" ".join(b["nota"]) or aviso)
    codigo = re.search(r"([A-Z]+)[-/]\d+$", expediente).group(1) if expediente else None
    tipo = _tipo_iniciativa(codigo, titulo)
    subtitulo, tipo_votacion = _fase(titulo, tipo, codigo)
    if b["particular"]:
        subtitulo = " ".join(b["particular"])
    grupos = [VotoGrupo(nombres.get(c, c), t["si"], t["no"], t["abstencion"],
                        t["diputados"] - t["si"] - t["no"] - t["abstencion"])
              for c, t in (por_grupo or {}).items() if t["diputados"]]
    extra = {"documento": numdoc, "hora": b["hora"], "protocolo": b.get("protocolo"), "preside": b.get("preside"),
             "titulo_debate": titulo, "votos_delegados": total["delegados"], "blancos": total.get("blanco"),
             "ausentes": total["ausentes"]}
    if b.get("sesion") != sesion:
        extra["sesion_pdf"] = b.get("sesion")
    if ex and ex[0] != expediente:
        extra["expediente_pdf"] = ex[0]
    if len(ex) > 1:
        extra["expedientes"] = ex
    if b["nota"]:
        extra["nota"] = " ".join(b["nota"])
    if b["obs"]:
        extra["observaciones"] = " ".join(b["obs"])
    if descuadres:
        extra["descuadres"] = descuadres
    if motivo:
        extra["nominal_descartado"] = motivo
    si, no, ab = total["si"], total["no"], total["abstencion"]
    return Votacion(
        cuerpo=CODIGO, fecha=b["fecha"], titulo=ficha.get("Extracto") or _limpiar_titulo(titulo, ex) or titulo,
        sesion=sesion, numero=b["numero"], legislatura=leg, subtitulo=subtitulo, expediente=expediente,
        tipo_iniciativa=tipo, tipo_votacion=tipo_votacion, autor=ficha.get("Proponente"), a_favor=si, en_contra=no,
        abstenciones=ab, no_votan=total["diputados"] - si - no - ab if total["diputados"] else None,
        presentes=total["presentes"], grupos=grupos, nominal=nominal or [], url=url, fuente="pdf-reglas",
        extra=extra), motivo


def _iniciativa(expediente, ficha, leg, tipo):
    f = ficha.get("Fecha creación", "")
    return Iniciativa(
        CODIGO, expediente, ficha["Extracto"], legislatura=leg, tipo_iniciativa=tipo, autor=ficha.get("Proponente"),
        resultado=ficha.get("Estado"), url=ficha["url"],
        fecha_presentacion=f"{f[6:]}-{f[3:5]}-{f[:2]}" if re.match(r"\d\d/\d\d/\d{4}$", f) else None,
        extra={k: ficha[k] for k in ("Tipo", "Procedimiento", "Número de registro") if k in ficha})


def descargar(ctx):
    desde = ctx.desde(CODIGO, margen_dias=42)
    vistas, n = set(), 0
    for doc, pdf in _con_pdf(ctx, _documentos(ctx, desde)):
        if pdf is None:
            continue
        leg, fecha_doc, sesion, numdoc, ident = doc
        cerrada = CUERPOS[0].legislaturas[leg][2] is not None
        url = PDF.format(ident)
        brutas, aviso = votaciones_pdf(_texto_pdf(ctx, pdf))
        if not brutas:
            ctx.log(f"  {CODIGO}: sin votaciones en {url}")
            continue
        titulos = [" ".join(b["titulo"]) for b in brutas]
        exps = [_expedientes(t) for t in titulos]
        resueltos = {e[0]: e[0] if "/" in e[0] else _resolver(ctx, e[0], leg, fecha_doc, ident, cerrada)
                     for e in exps if e}
        fichas = _fichas(ctx, sorted({e for e in resueltos.values() if e}), cerrada)
        orden_dl, descartes = Counter(), Counter()
        for b, titulo, ex in zip(brutas, titulos, exps):
            if "numero" not in b:
                ctx.log(f"  {CODIGO}: votación sin número en {url}: {titulo[:80]}")
                continue
            expediente = (resueltos.get(ex[0]) or ex[0]) if ex else None
            ficha = fichas.get(expediente) or {}
            v, motivo = _votacion(b, titulo, ex, expediente, ficha, leg, sesion, numdoc, url, aviso)
            if v is None:
                ctx.log(f"  {CODIGO}: {url} votación {b['numero']}: {motivo}")
                continue
            if motivo:
                clave = motivo.split(":")[0] if motivo.startswith(("nota", "líneas")) else motivo.split(": ", 1)[-1]
                descartes[re.sub(r"\d+", "N", clave)] += 1
            # Decretos-leyes: la 1.ª votación convalida y la 2.ª, si la hay, decide la tramitación como proyecto de ley.
            if v.tipo_iniciativa == "dl" and v.subtitulo == "Convalidación o derogación":
                orden_dl[v.expediente or titulo] += 1
                v.tipo_votacion = {1: "convalidacion", 2: "tramitacion_ley"}.get(orden_dl[v.expediente or titulo])
            if ficha.get("Extracto") and (leg, expediente) not in vistas:
                vistas.add((leg, expediente))
                yield _iniciativa(expediente, ficha, leg, v.tipo_iniciativa)
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
        if descartes:
            ctx.log(f"  {CODIGO}: {url} ({fecha_doc}): sin voto nominal en {sum(descartes.values())} votaciones "
                    f"({'; '.join(f'{k} ×{x}' for k, x in descartes.items())})")
