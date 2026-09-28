"""Parlamento de La Rioja: votaciones del Pleno sacadas con reglas del Diario de Sesiones (PDF).

Fuente: el listado de diarios de sesiones
(https://www.parlamento-larioja.org/recursos-de-informacion/publicaciones-oficiales/diarios-de-sesiones),
filtrable por legislatura (?getLegislatura=11&b_start:int=0, diez por página, del más reciente al más
antiguo). Cada diario (dspr-<leg>-<núm>) se sirve directamente como PDF. No hay datos abiertos de
votaciones ni exportación del buscador de iniciativas.

Qué se saca: el SUMARIO de cada diario resume cada punto con su expediente (11L/PNLP-0366) y una
línea muy regular con el resultado: «Votación: la proposición no de ley queda aprobada por 19 votos a
favor, 2 votos en contra y 11 abstenciones», o varias separadas por «;» cuando se vota por apartados.
En la X y la IX legislatura suele traer además los grupos de cada sentido por siglas
(«17 votos a favor (GPC, GPP y Sra. Moreno ‒GPM‒)»), que se guardan como voto por grupo. El título y el
autor salen del ORDEN DEL DÍA del propio diario.

Con el voto electrónico (desde 2022), el cuerpo trae cada votación con la misma fórmula: anuncio de la
Presidencia, «(Los señores diputados emiten su voto)» y la lectura del secretario («El resultado de la
votación es: 13 votos a favor, 17 votos en contra y 2 abstenciones»). Esas lecturas se casan en orden con
el sumario (programación dinámica; solo si la solución óptima es única): así se verifica cada votación
(`extra["verificada"]`), se pone el recuento a lo aprobado «por unanimidad» y, sobre todo, se desglosan los
proyectos de ley, que el sumario despacha con «tras las sucesivas votaciones, la ley queda aprobada»: cada
votación del cuerpo (enmiendas, articulado, conjunto) pasa a ser una votación con el anuncio de subtítulo.
Si no casa, queda la votación resumen sin totales (`extra["resumen"]`).

Cobertura: Pleno de la IX (2015), X (2019) y XI (2023-) legislaturas; el número de diario va en
`sesion` (el de sesión plenaria, que no siempre coincide, en `extra`).
Limitaciones: la fecha es la del primer día si la sesión dura varios; las elecciones de la Mesa y las
votaciones secretas con varios candidatos no se recogen; lo aprobado «por unanimidad» sin recuento
leído queda como asentimiento; las erratas imposibles del sumario (más votos que escaños) dejan los
totales en blanco (`extra["totales_descartados"]`). Los diarios se publican con semanas o meses de retraso.
"""

import re
import unicodedata

from ...territorio import Cuerpo, num_parlamento
from ..modelo import Iniciativa, Votacion, VotoGrupo

CUERPO = "parl-RI"
BASE = "https://www.parlamento-larioja.org"
DIARIOS = BASE + "/recursos-de-informacion/publicaciones-oficiales/diarios-de-sesiones"

LEGISLATURAS = {
    9: ("IX", "2015-06-18", "2019-06-20"),
    10: ("X", "2019-06-20", "2023-06-22"),
    11: ("XI", "2023-06-22", None),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("RI"), "Parlamento de La Rioja", "Parlamento (La Rioja)", "autonomico", "RI", 33,
           LEGISLATURAS, web=DIARIOS),
]

NOTAS = ("Votaciones del Pleno con reglas sobre el Diario de Sesiones en PDF: expediente, totales, resultado y, en "
         "la IX y la X, grupos por siglas (sumario); con voto electrónico, verificación con las lecturas del "
         "secretario, recuento de lo aprobado por unanimidad y desglose de las votaciones de los proyectos de ley. "
         "IX, X y XI legislaturas. Los diarios se publican con semanas o meses de retraso.")

# Siglas de grupo que usa el sumario -> nombre del grupo.
GRUPOS = {
    "GPP": "Grupo Parlamentario Popular", "GPS": "Grupo Parlamentario Socialista",
    "GPC": "Grupo Parlamentario Ciudadanos", "GPM": "Grupo Parlamentario Mixto",
    "GPV": "Grupo Parlamentario Vox", "GPPIU": "Grupo Parlamentario Podemos-Izquierda Unida",
    "GPPOD": "Grupo Parlamentario Podemos", "GPPR": "Grupo Parlamentario Partido Riojano",
}

# Tipo de expediente (11L/<TIPO>-0000) -> tipo de iniciativa.
TIPOS = {
    "PNLP": "pnl", "PNLC": "pnl", "PNL": "pnl", "MOCI": "mocion", "MOC": "mocion",
    "PL": "pl", "PLP": "presupuesto", "PPL": "ppl", "PPLD": "ppl", "PPLP": "ppl", "ILP": "ilp", "ILM": "ilp",
    "DL": "dl", "DLEY": "dl", "RDL": "dl", "I": "investidura", "MC": "investidura", "CC": "investidura",
    "INFO": "control", "INF": "control", "PLAN": "control", "COMU": "control", "CG": "control",
    "INTE": "control", "POP": "control", "IFCP": "control", "CCE": "acuerdo", "CIN": "acuerdo", "DIC": "acuerdo",
    "IEPC": "organizacion", "EPPR": "organizacion", "ND": "organizacion", "REG": "organizacion",
}

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
ITEM_LISTADO_RE = re.compile(r'href="%s/dspr-(\d+)-(\d+)"\s+class="summary url"' % re.escape(DIARIOS))
CABECERA_RE = re.compile(r"(Sesi[oó]n\s+Plenaria|Diputaci[oó]n\s+Permanente)\s+n\.?\s*[º°o]\s*(\d+),?\s+celebrada\s+"
                         r"(?:el\s+d[ií]a|los\s+d[ií]as)\s+(.{3,90}?\d{4})", re.I | re.S)
RUIDO_RE = re.compile(r"^(?:\d+(?:\s+\d+)*|P[áa]gina\s+\d+|DIARIO DE SESIONES DEL PARLAMENTO DE LA RIOJA.*|"
                      r"P-D\s*/\s*N[úu]mero\s+\d+.*|N[úu]mero\s+\d+\s*/\s*Dep[óo]sito Legal.*|P-D|"
                      r"\d{1,2} de [a-záéíóú]+ de \d{4})$")  # la fecha de la cabecera de página, a veces en su línea
EXPEDIENTE_RE = re.compile(r"^(\d{1,3}L/([A-ZÑ]{1,6})-\d{2,5})-?\.\s*(.*)$")
INICIATIVA_RE = re.compile(r"(\d{1,3}L/[A-ZÑ]{1,6}-\d{2,5})")
CUERPO_INICIO_RE = re.compile(r"^SESI[ÓO]N (?:PLENARIA|CONSTITUTIVA)\b.*\bCELEBRADA\b|^\(Se (?:inicia|reanuda) la sesi[óo]n")
AUTOR_RE = re.compile(r"[‒–—]\s*(Grupos? Parlamentari[oa]s? [^.‒–—]+)")
LINEA_VOTO_RE = re.compile(r"^(?:Votaci[oó]n(?:es)?\b|Sometid[oa]s? a votaci[oó]n|Tras ser sometid[oa]s? a votaci[oó]n|"
                           r"Efectuad[oa] (?:la votaci[oó]n|el escrutinio))", re.I)
HABLA_RE = re.compile(r"^(?:EL|LA|LOS|LAS)\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]+(?:\s*\([^)]*\))?\s*:")
PARECE_VOTO_RE = re.compile(r"votos?\b|votaci|a favor|en contra|abstenci|unanimidad|asentimiento|aprobad|rechazad", re.I)
NUM = r"(\d+|una?|ninguna?|cero)"


def _entero(s):
    s = (s or "").lower()
    if s.isdigit():
        return int(s)
    return {"un": 1, "una": 1, "uno": 1, "ningun": 0, "ninguno": 0, "ninguna": 0, "cero": 0}.get(s)


def _fecha(texto):
    dia = re.search(r"\b(\d{1,2})\b", texto)
    mes = re.search(r"\bde\s+([a-záéíóú]+)", texto, re.I)
    anio = re.search(r"\b(\d{4})\b", texto)
    if not (dia and mes and anio) or mes.group(1).lower() not in MESES:
        return None
    return f"{anio.group(1)}-{MESES[mes.group(1).lower()]:02d}-{int(dia.group(1)):02d}"


# ---------------------------------------------------------------- listado

def _diarios(ctx, leg):
    """Números de diario de una legislatura, del más reciente al más antiguo."""
    vistos, inicio = set(), 0
    while True:
        h = ctx.texto(f"{DIARIOS}?getLegislatura={leg}&b_start:int={inicio}")
        nuevos = sorted({int(n) for lg, n in ITEM_LISTADO_RE.findall(h) if int(lg) == leg} - vistos, reverse=True)
        yield from nuevos
        vistos.update(nuevos)
        if not nuevos or f"b_start:int={inicio + 10}" not in h:
            return
        inicio += 10


# ---------------------------------------------------------------- texto del diario

def _lineas(texto):
    """Líneas útiles del diario (sin cabeceras, pies ni números de página)."""
    return [ln.strip() for ln in texto.replace("\f", "\n").splitlines() if ln.strip() and not RUIDO_RE.match(ln.strip())]


def _partes(lineas):
    """(orden del día, sumario, cuerpo) como listas de líneas."""
    try:
        i = next(k for k, ln in enumerate(lineas) if ln == "SUMARIO")
    except StopIteration:
        return lineas, [], []
    j = next((k for k in range(i + 1, len(lineas)) if CUERPO_INICIO_RE.match(lineas[k])), len(lineas))
    return lineas[:i], lineas[i + 1:j], lineas[j:]


def _exp(m, leg):
    """Expediente de una coincidencia, corrigiendo erratas del prefijo («111L/» por «11L/»)."""
    cod = m if isinstance(m, str) else m.group(1)
    pre, resto = cod.split("L/", 1)
    if int(pre) != leg and pre.endswith(str(leg)):
        cod = f"{leg}L/{resto}"
    return cod


def _termina(linea):
    """¿Acaba aquí la frase? (punto final que no sea de una abreviatura)."""
    return bool(re.search(r"[.:]$", linea)) and not re.search(r"\b(?:Sr|Sra|Sres|D|Dña|n\.º|núm)\.$", linea)


def _orden_del_dia(lineas, leg):
    """expediente -> (título, autor) según el ORDEN DEL DÍA."""
    fichas, k = {}, 0
    while k < len(lineas):
        m = EXPEDIENTE_RE.match(lineas[k])
        if not m:
            k += 1
            continue
        titulo, autor, k = [m.group(3)], None, k + 1
        while k < len(lineas) and not _termina(titulo[-1]) and not EXPEDIENTE_RE.match(lineas[k]) \
                and not lineas[k].isupper():
            titulo.append(lineas[k])
            k += 1
        # autores: una línea «Nombre ‒ Grupo Parlamentario X.» por firmante, o «Gobierno de La Rioja.»
        autores = []
        while k < len(lineas) and not EXPEDIENTE_RE.match(lineas[k]) and not lineas[k].isupper():
            g = ["Gobierno de La Rioja"] if lineas[k].startswith("Gobierno de La Rioja") else \
                [x.strip() for x in AUTOR_RE.findall(lineas[k])]
            if not g:
                break
            autores += [x for x in g if x not in autores]
            k += 1
        tit = " ".join(titulo).strip()
        firma = re.search(r"[‒–—]\s*Grupos? Parlamentari", tit)
        if firma:  # «Título. Nombre ‒ Grupo Parlamentario X. Toma en consideración...» en una sola línea
            autores = [x.strip() for x in AUTOR_RE.findall(tit)] + autores
            corte = tit.rfind(". ", 0, firma.start())
            tit = tit[:corte + 1] if corte > 0 else tit
        autor = ", ".join(dict.fromkeys(autores)) or None
        fichas.setdefault(_exp(m, leg), (tit, autor))
    return fichas


def _reflujo(lineas):
    """Une las líneas partidas por la maquetación: cada línea pasa a ser una frase (o una cabecera)."""
    out = []
    for ln in lineas:
        if out and not _termina(out[-1]) and not out[-1].isupper() and not EXPEDIENTE_RE.match(ln) \
                and not ln.isupper() and not re.match(r"(?:Votaci[oó]n|Sometid[oa]|Tras ser sometid|Efectuad)", ln):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return out


def _bloques_sumario(lineas, leg):
    """[(expediente, título del sumario, texto del bloque de votación)] en orden."""
    lineas = _reflujo(lineas)
    bloques, exp, tit, k, sin_titulo = [], None, None, 0, False
    while k < len(lineas):
        ln = lineas[k]
        m = EXPEDIENTE_RE.match(ln)
        if m:
            exp, tit, sin_titulo = _exp(m, leg), m.group(3), False
            k += 1
            continue
        if ln.isupper() and len(ln) > 8:  # cabecera de sección: el punto anterior se acaba
            exp, tit, sin_titulo = None, None, True
            k += 1
            continue
        if sin_titulo and not LINEA_VOTO_RE.match(ln):  # punto sin expediente: su primera línea es el título
            tit, sin_titulo = ln, False
        if LINEA_VOTO_RE.match(ln):
            partes = [ln]
            k += 1
            # tras «Votaciones:», cada frase siguiente que hable de votos es otra votación
            plural = bool(re.match(r"^Votaciones\b", ln, re.I)) or ln.rstrip().endswith(":")
            while plural and k < len(lineas) and not EXPEDIENTE_RE.match(lineas[k]) and not lineas[k].isupper():
                sig = lineas[k]
                if LINEA_VOTO_RE.match(sig) or sig.startswith("Se ") or not PARECE_VOTO_RE.search(sig):
                    break
                partes.append(sig)
                k += 1
            texto = " ".join(partes)
            # «Votación de la iniciativa 11L/MOCI-0031: ...», «Votación de la Proposición no de Ley 9L/PNLP-0141: ...»
            cab = re.match(r"^Votaci[oó]n(?:es)?\b([^:]{0,160}):", texto, re.I)
            otros = INICIATIVA_RE.findall(cab.group(1)) if cab else []
            if len(set(otros)) == 1:
                bloques.append((_exp(otros[0], leg), None, texto))
            else:
                bloques.append((exp, tit, texto))
            continue
        k += 1
    return bloques


def _clausulas(bloque):
    """Separa un bloque de votación en cláusulas (una por votación)."""
    t = re.sub(r"^Votaci[oó]n(?:es)?\b[^:]{0,160}:\s*", "", bloque.strip(), flags=re.I)
    partes, nivel, actual = [], 0, ""
    for ch in t:
        nivel += ch == "("
        nivel -= ch == ")"
        if ch == ";" and nivel <= 0:
            partes.append(actual)
            actual = ""
        else:
            actual += ch
    partes.append(actual)
    out = []
    for p in partes:  # frases separadas por punto (formato de la IX legislatura)
        out += re.split(r"(?<!\bSr)(?<!\bSra)(?<!\bD)(?<!\bDña)\.\s+(?=[A-ZÁÉÍÓÚ«\"])", p)
    # dos votaciones en una frase: «el punto 2 es aprobado por 21 votos..., y los puntos 3 y 5 son aprobados por...»
    final = []
    for c in out:
        while True:
            m = next((x for x in re.finditer(r",\s+y\s+(?=[^,;]{0,160}?\bpor (?:\d+|unanimidad|asentimiento)\b)", c)
                      if re.search(r"\bpor (?:\d+|unanimidad|asentimiento)\b", c[:x.start()])), None)
            if not m:
                break
            final.append(c[:m.start()])
            c = c[m.end():]
        final.append(c)
    return [c.strip(" .") for c in final if c.strip(" .")]


def _grupos(lista, sentido, acum):
    """Añade a `acum` (grupo -> {sentidos}) lo que dice una lista «GPC, GPP y Sra. X ‒GPM‒»."""
    for tok in re.split(r",\s*|\s+y\s+", lista):
        tok = tok.strip()
        m = re.search(r"[‒–—-]\s*(GP[A-Za-z]+)\s*[‒–—-]", tok)
        sigla = m.group(1) if m else (tok if re.fullmatch(r"GP[A-Za-z]+", tok) else None)
        if sigla:
            acum.setdefault(sigla.upper(), set()).add(sentido)


def _analizar(clausula):
    """Datos de una cláusula de votación, o None si no es una votación que se pueda leer."""
    c = re.sub(r"\s+", " ", clausula)
    low = c.lower()
    if len(re.findall(r"votos? (?:a favor de|para) (?:d\.|doña|don)", low)) >= 2:
        return None  # elección con varios candidatos: no es un sí/no
    d = {"texto": c, "a_favor": None, "en_contra": None, "abstenciones": None, "asentimiento": False,
         "unanimidad": False, "resultado": None, "grupos": {}, "repeticiones": 1, "en_blanco": None}
    m = re.search(r"(\d+) (?:votos? )?a favor(?:\s*\(([^)]*)\))?", c)
    if m:
        d["a_favor"] = int(m.group(1))
        if m.group(2):
            _grupos(m.group(2), "si", d["grupos"])
    m = re.search(r"(\d+|ning[uú]n) (?:votos? )?en contra(?:\s*\(([^)]*)\))?", c)
    if m:
        d["en_contra"] = _entero(m.group(1).replace("ú", "u"))
        if m.group(2):
            _grupos(m.group(2), "no", d["grupos"])
    m = re.search(NUM + r" abstenci(?:ón|ones)(?:\s*\(([^)]*)\))?", c, re.I)
    if m:
        d["abstenciones"] = _entero(m.group(1))
        if m.group(2):
            _grupos(m.group(2), "abstencion", d["grupos"])
    m = re.search(r"(\d+) votos? en blanco", c)
    if m:
        d["en_blanco"] = int(m.group(1))
    if "por asentimiento" in low:
        d["asentimiento"] = True
    if "unanimidad" in low:
        d["unanimidad"] = True
        if d["a_favor"] is not None:
            d["en_contra"] = d["en_contra"] if d["en_contra"] is not None else 0
            d["abstenciones"] = d["abstenciones"] if d["abstenciones"] is not None else 0
    m = re.search(r"(?:(aprobad|rechazad)[oa]s?|se (aprueba|rechaza)n?|\b(decae|decaen))\b"
                  r"(?=[^.;]{0,40}\b(?:por|en primera)\b)", low) \
        or re.search(r"(aprobad|rechazad|designad|investid|elegid)[oa]s?\b|\b(decae|decaen)\b", low)
    if m:
        verbo = next(g for g in m.groups() if g)
        d["resultado"] = "rechazada" if verbo.startswith(("rechaz", "deca")) else "aprobada"
    if re.search(r"primera,? segunda y tercera votaci", low):
        d["repeticiones"] = 3
    elif re.search(r"primera y segunda votaci", low):
        d["repeticiones"] = 2
    sucesivas = bool(re.search(r"(?:sucesivas|diferentes|distintas|correspondientes) votaciones", low))
    if d["a_favor"] is None and d["en_contra"] is None and not d["asentimiento"] and not d["unanimidad"] \
            and not (sucesivas and d["resultado"]):
        return None
    if d["resultado"] is None and d["a_favor"] is None:
        return None
    # sujeto: lo que va antes del verbo («los apartados 1 y 2 de la proposición no de ley»)
    s = re.sub(r"^(?:tras ser )?sometid[oa]s? a votaci[oó]n,?\s*", "", c.strip(" ,"), flags=re.I)
    m = re.match(r"^(?:quedan?\s+|resultan?\s+|son\s+|es\s+)?(?:aprobad|rechazad)[oa]s?\s+(.+?)\s+por\s", s)
    if m:  # «quedan aprobados los puntos a) y d) por...», «rechazados los puntos b) y c) por...»
        s = m.group(1)
    else:
        s = re.split(r"\b(?:queda|quedan|resulta|resultan|es|son|se aprueba|se aprueban|se rechaza|se rechazan|"
                     r"obtiene|decae|decaen)\b|,?\s+por\s+(?=\d)", s, maxsplit=1)[0]
    d["sujeto"] = s.strip(" ,") or None
    d["elidido"] = bool(re.match(r"^[^,;]{1,160},\s+por\s+\d", c))  # «el apartado 3, por 17 votos a favor...»
    # «tras las sucesivas votaciones, la ley queda aprobada»: resumen de varias votaciones que solo están en el cuerpo
    d["sucesivas"] = sucesivas and d["a_favor"] is None
    return d


def _recuento(t):
    """(sí, no, abstenciones) de lo que lee el secretario, o None si no se entiende."""
    t = t.lower()
    si = re.search(r"(\d+) votos? a favor|\bs[ií][,:]? (\d+)|votos a favor[,:]? (\d+)", t)
    no = re.search(r"(\d+) (?:votos? )?en contra|votos contrarios[,:]? (\d+)|\bno[,:]? (\d+)|en contra[,:]? (\d+)", t)
    ab = re.search(r"(\d+) abstenci|abstenciones[,:]? (\d+)", t)
    val = lambda m: next((int(g) for g in m.groups() if g), None) if m else None  # noqa: E731
    n_si, n_no, n_ab = val(si), val(no), val(ab)
    if n_no is None and re.search(r"ning[uú]n (?:voto en contra|no)\b|sin votos? en contra", t):
        n_no = 0
    if n_ab is None and re.search(r"ninguna abstenci|sin abstenci|0 abstenci", t):
        n_ab = 0
    return (n_si, n_no, n_ab) if n_si is not None else None


def _lecturas(cuerpo):
    """Votaciones del cuerpo del diario, en orden: una por cada «(Los señores diputados emiten su voto)».

    Cada una es {cuenta: (sí, no, abst) o None, anuncio: lo que la Presidencia dice que se vota, resultado}.
    """
    out, fin_anterior = [], 0
    for k, ln in enumerate(cuerpo):
        if not re.search(r"emiten su voto", ln, re.I):
            continue
        contexto = " ".join(cuerpo[fin_anterior:k])  # todo lo dicho desde la votación anterior
        j = next((x for x in range(k + 1, min(k + 4, len(cuerpo))) if re.match(r"^(?:EL|LA) SEÑORA? SECRETARI", cuerpo[x])),
                 None)
        fin_anterior = (j if j is not None else k) + 1
        lectura = ""
        if j is not None:  # la lectura puede seguir en las líneas siguientes
            lectura, m = cuerpo[j].split(":", 1)[-1], j + 1
            while m < len(cuerpo) and not HABLA_RE.match(cuerpo[m]) and not cuerpo[m].startswith("("):
                lectura += " " + cuerpo[m]
                m += 1
        # anuncio: la última intervención de la Presidencia antes del voto
        previo, i = [], k - 1
        while i >= 0 and len(previo) < 8 and "emiten su voto" not in cuerpo[i]:
            previo.insert(0, cuerpo[i])
            if HABLA_RE.match(cuerpo[i]):
                break
            i -= 1
        texto = " ".join(previo)
        texto = texto.split(":", 1)[1] if HABLA_RE.match(texto) else texto
        texto = re.sub(r"\s*(?:Se (?:inicia|da inicio a) la votaci[oó]n|Comienza la votaci[oó]n|Se da inicio a la misma)\.?",
                       " ", texto).strip()
        frases = re.split(r"(?<=[.?!])\s+", texto)
        anuncio = next((f for f in reversed(frases) if re.search(r"\bvot", f, re.I)), frases[-1] if frases else "")
        despues = next((x for x in cuerpo[(j or k) + 1:(j or k) + 4] if re.match(r"^(?:EL|LA) SEÑORA? PRESIDENT", x)), "")
        r = re.search(r"\b(aprobad|rechazad)[oa]s?\b|\b(decae|decaen)\b", despues.split(":", 1)[-1], re.I)
        resultado = None
        if r:
            resultado = "aprobada" if (r.group(1) or "").lower().startswith("aprob") else "rechazada"
        out.append({"cuenta": _recuento(lectura) if lectura else None, "anuncio": anuncio.strip()[:400],
                    "resultado": resultado, "lectura": lectura.strip()[:200], "contexto": contexto[-3000:]})
    return out


def _plano(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _menciona(titulo, contexto):
    """¿Nombra el texto la ley del título? (las cuatro primeras palabras con contenido tras «de ley»)."""
    t = _plano(titulo).split(" ley ", 1)[-1]
    genericas = ("para", "sobre", "como", "entre", "aprueba", "modifica", "regula", "establece", "medidas", "rioja")
    palabras = [w for w in re.findall(r"[a-z]{4,}", t) if w not in genericas][:4]
    c = _plano(contexto)
    return bool(palabras) and all(w in c for w in palabras)


def _alinear(votos, lecturas):
    """Casa las votaciones del sumario con las del cuerpo; None si no hay una única forma óptima de hacerlo.

    Una votación con totales consume tantas lecturas como repeticiones (empates) y deben coincidir, o ninguna
    (a veces no hay lectura en el cuerpo); una aprobada por asentimiento no consume ninguna; una «por unanimidad»
    sin recuento, una o ninguna; y un bloque «tras las sucesivas votaciones» (proyectos de ley), todas las que
    caigan en su hueco (al menos una). Una lectura que no case con nada penaliza. Se maximiza lo casado.
    Devuelve, por votación del sumario, la lista de lecturas que le corresponden (o None si no casó).
    """
    def encaja(v, lec):
        c = lec["cuenta"]
        if c is None:
            return False
        if v["a_favor"] is None:  # unanimidad
            return (c[1] or 0) == 0 and (c[2] or 0) == 0
        return c[0] == v["a_favor"] and (v["en_contra"] is None or c[1] is None or c[1] == v["en_contra"]) and \
            (v["abstenciones"] is None or c[2] is None or c[2] == v["abstenciones"])

    R = len(lecturas)
    # primera lectura cuyo contexto nombra la ley de cada bloque: ahí empieza (se nombra también en cada enmienda)
    primera = {i: next((j for j, lec in enumerate(lecturas) if _menciona(v.get("titulo_ley") or "", lec["contexto"])),
                       None) for i, v in enumerate(votos) if v.get("sucesivas")}

    def opciones(i, j):
        """[(lecturas que se saltan, lecturas que consume la votación i, puntos)] desde la lectura j.

        Las lecturas sueltas se saltan (con penalización) justo antes de la siguiente votación que consume, y
        solo hasta la primera que le encaja: así cada forma de casar se cuenta una vez.
        """
        v = votos[i]
        if v.get("sucesivas"):  # el bloque empieza mejor donde la Presidencia nombra la ley
            extra = 1 if j < R and j == primera.get(i) else 0
            return [(0, n, extra) for n in range(1, R - j + 1)] + [(0, 0, -1)]
        ops = [(0, 0, 0)]
        if v["a_favor"] is None and v["asentimiento"] and not v["unanimidad"]:
            return ops
        n = 1 if v["a_favor"] is None else v["repeticiones"]
        for s in range(0, R - j - n + 1):
            if all(encaja(v, x) for x in lecturas[j + s:j + s + n]):
                ops.append((s, n, 2 - s))
                break
        return ops

    memo = {}

    def mejor(i, j):  # (puntos, nº de soluciones óptimas hasta 2) para votos[i:] y lecturas[j:]
        if i == len(votos):
            return -(R - j), 1
        if (i, j) not in memo:
            best, cnt = None, 0
            for s, n, p in opciones(i, j):
                sub, c = mejor(i + 1, j + s + n)
                if best is None or sub + p > best:
                    best, cnt = sub + p, c
                elif sub + p == best:
                    cnt = min(2, cnt + c)
            memo[(i, j)] = (best, cnt)
        return memo[(i, j)]

    if not votos or not lecturas or len(votos) * R > 20000:
        return None
    puntos, soluciones = mejor(0, 0)
    if soluciones != 1 or puntos < 0 or (puntos == 0 and not any(v.get("sucesivas") for v in votos)):
        return None
    asignado, i, j = [None] * len(votos), 0, 0
    while i < len(votos):
        objetivo = mejor(i, j)[0]
        for s, n, p in opciones(i, j):
            if mejor(i + 1, j + s + n)[0] + p == objetivo:
                # una votación con totales que no consume lectura queda sin verificar (None)
                asignado[i] = lecturas[j + s:j + s + n] if n or votos[i]["a_favor"] is None and \
                    not votos[i].get("sucesivas") else None
                i, j = i + 1, j + s + n
                break
    return asignado


def _tipo_votacion(tipo, texto):
    t = texto.lower()
    if "lectura única" in t or "tramitación directa" in t or "retirada" in t:
        return "organizacion"
    if "toma en consideración" in t:
        return "toma_consideracion"
    if "totalidad" in t:
        return "totalidad"
    if "convalidaci" in t:
        return "convalidacion"
    if tipo in ("pnl", "mocion", "investidura"):
        return tipo
    if re.search(r"designad|senador", t):
        return "nombramiento"
    if tipo in ("pl", "ppl", "presupuesto", "ilp", "dl"):
        m = re.search(r"vota(?:ci[oó]n|r|mos)? (?:de |del |a )?(?:la |las |el |los )?(?:resto de (?:las |los )?)?"
                      r"(enmiendas?|art[ií]culos?|exposici[oó]n|disposici|t[ií]tulo|conjunto|dictamen|secci[oó]n)", t) \
            or re.search(r"\b(enmiendas?)\b", t)
        if m:
            obj = m.group(1)
            return "enmiendas" if obj.startswith("enmienda") else "conjunto" if obj == "conjunto" else "articulado"
        if re.search(r"(?:proyecto|proposición) de ley (?:queda|es|resulta)|\bla ley queda", t):
            return "conjunto"
    return None


def _diario(ctx, leg, num):
    """(fecha, sesión plenaria, url, votaciones [dict]) de un diario, o None si no es del Pleno."""
    url = f"{DIARIOS}/dspr-{leg}-{num}"
    pdf = ctx.fetch(url, cache=f"{CUERPO}/diarios/dspr-{leg}-{num:03d}.pdf")
    texto = ctx.pdf_texto(pdf, layout=False)
    m = CABECERA_RE.search(texto[:4000])
    if not m:
        ctx.log(f"  ! {CUERPO}: diario {leg}-{num} sin cabecera reconocible")
        return None
    if not m.group(1).lower().startswith("sesi"):
        return None  # Diputación Permanente
    fecha = _fecha(m.group(3))
    lineas = _lineas(texto)
    orden, sumario, cuerpo = _partes(lineas)
    fichas = _orden_del_dia(orden, leg)
    votos = []
    for exp, tit, bloque in _bloques_sumario(sumario, leg):
        # «Votación del Proyecto de Ley de Presupuestos dictaminado: ...»: la ley se nombra por el título
        cab = re.match(r"^Votaci[oó]n(?:es)?\s+de[l ].*?(?:Proyecto|Proposición) de Ley\b([^:]{0,160}):", bloque, re.I)
        palabras = [w for w in re.findall(r"[a-z]{4,}", _plano(cab.group(1)))
                    if w not in ("dictaminado", "dictaminada", "para", "sobre")] if cab else []
        if palabras:
            candidatos = [e for e, (t, _a) in fichas.items() if re.search(r"/(?:PL|PPL|PPLD|PLP|ILP)\w*-", e)
                          and all(w in _plano(t) for w in palabras)]
            if len(candidatos) == 1:
                exp, tit = candidatos[0], fichas[candidatos[0]][0]
        anterior = None
        for c in _clausulas(bloque):
            d = _analizar(c)
            if d:
                if d["resultado"] is None and d["elidido"] and anterior and anterior["resultado"]:
                    d["resultado"] = anterior["resultado"]  # verbo sobrentendido: el de la cláusula anterior
                d["expediente"], d["titulo_sumario"] = exp, tit
                d["titulo_ley"] = (fichas.get(exp) or (None,))[0] or tit or ""  # título completo, para `_menciona`
                votos.append(d)
                anterior = d
    asignado = _alinear(votos, _lecturas(cuerpo))
    if asignado:
        final = []
        for v, lecs in zip(votos, asignado):
            if v.get("sucesivas") and lecs:  # proyecto de ley: cada votación del cuerpo es una votación
                for lec in lecs:
                    c = lec["cuenta"] or (None, None, None)
                    final.append({"texto": f"{lec['anuncio']} | {lec['lectura']}", "a_favor": c[0], "en_contra": c[1],
                                  "abstenciones": c[2], "asentimiento": False, "unanimidad": False,
                                  "resultado": lec["resultado"], "grupos": {}, "repeticiones": 1, "en_blanco": None,
                                  "sujeto": lec["anuncio"] or None, "elidido": False, "expediente": v["expediente"],
                                  "titulo_sumario": v["titulo_sumario"], "verificada": True, "del_cuerpo": True})
                continue
            if lecs:
                v["verificada"] = True
            if lecs and v["a_favor"] is None and v["unanimidad"]:
                v["a_favor"], v["en_contra"], v["abstenciones"] = lecs[-1]["cuenta"][0], 0, 0
            final.append(v)
        votos = final
    return fecha, int(m.group(2)), url, votos, fichas


def _votacion(leg, num, sesion_pleno, fecha, url, n, v, fichas):
    exp = v["expediente"]
    titulo, autor = fichas.get(exp, (None, None)) if exp else (None, None)
    titulo = titulo or v.get("titulo_sumario") or v["sujeto"] or v["texto"]
    m = re.match(r"\d+L/([A-ZÑ]+)-", exp or "")
    tipo = TIPOS.get(m.group(1)) if m else None
    if tipo is None and m:
        tipo = "otro"
    if tipo == "pl" and "presupuestos generales" in titulo.lower():
        tipo = "presupuesto"
    grupos = []
    for sigla, sentidos in sorted(v["grupos"].items()):
        grupos.append(VotoGrupo(GRUPOS.get(sigla, sigla), sentido=sentidos.pop() if len(sentidos) == 1 else "dividido"))
    extra = {"diario": num, "sesion_plenaria": sesion_pleno,
             ("texto_cuerpo" if v.get("del_cuerpo") else "texto_sumario"): v["texto"]}
    if v.get("sucesivas"):
        extra["resumen"] = True  # «tras las sucesivas votaciones...»: el detalle está en el cuerpo del diario
    if v.get("verificada"):
        extra["verificada"] = True
    if v["repeticiones"] > 1:
        extra["empate"] = True
    if v["en_blanco"] is not None:
        extra["en_blanco"] = v["en_blanco"]
    if v["unanimidad"]:
        extra["unanimidad"] = True
    if sum(v[k] or 0 for k in ("a_favor", "en_contra", "abstenciones")) > CUERPOS[0].escanos_de(leg):
        # errata del diario (p. ej. «28 votos a favor» por 18): el texto queda en extra, los números no se usan
        extra["totales_descartados"] = f"{v['a_favor']}-{v['en_contra']}-{v['abstenciones']}"
        v = {**v, "a_favor": None, "en_contra": None, "abstenciones": None}
    asent = (v["asentimiento"] or v["unanimidad"]) and v["a_favor"] is None
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=num, numero=n, legislatura=leg,
        subtitulo=v["sujeto"] if v["sujeto"] and v["sujeto"] != titulo else None,
        expediente=exp, tipo_iniciativa=tipo, tipo_votacion=_tipo_votacion(tipo, v["texto"]), autor=autor,
        a_favor=v["a_favor"], en_contra=v["en_contra"], abstenciones=v["abstenciones"],
        asentimiento=asent, resultado=v["resultado"] or ("aprobada" if asent else None),
        grupos=grupos, url=url, fuente="pdf-reglas", extra=extra)


def descargar(ctx):
    desde = ctx.desde(CUERPO, margen_dias=45)  # los diarios salen con meses de retraso: margen amplio
    n_total, iniciativas = 0, set()
    for leg in sorted(LEGISLATURAS, reverse=True):
        fin = LEGISLATURAS[leg][2]
        if desde and fin and fin < desde:
            break
        for num in _diarios(ctx, leg):
            r = _diario(ctx, leg, num)
            if not r:
                continue
            fecha, sesion_pleno, url, votos, fichas = r
            if not fecha:
                ctx.log(f"  ! {CUERPO}: diario {leg}-{num} sin fecha")
                continue
            if desde and fecha < desde:
                return
            for n, v in enumerate(votos, 1):
                exp = v["expediente"]
                if exp and exp not in iniciativas and exp in fichas:
                    iniciativas.add(exp)
                    m = re.match(r"\d+L/([A-ZÑ]+)-", exp)
                    yield Iniciativa(CUERPO, exp, fichas[exp][0], legislatura=leg,
                                     tipo_iniciativa=TIPOS.get(m.group(1), "otro") if m else None,
                                     autor=fichas[exp][1], url=url)
                vo = _votacion(leg, num, sesion_pleno, fecha, url, n, v, fichas)
                if vo.resultado is None and vo.a_favor is None and not vo.asentimiento:
                    ctx.log(f"  {CUERPO}: diario {leg}-{num}, votación {n} sin resultado ni totales legibles: {v['texto'][:120]}")
                    continue
                yield vo
                n_total += 1
                if ctx.limite and n_total >= ctx.limite:
                    return
