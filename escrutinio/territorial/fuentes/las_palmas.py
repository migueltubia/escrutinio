"""Ayuntamiento de Las Palmas de Gran Canaria: votaciones del Pleno sacadas de las actas en PDF.

Fuente: página de plenos del Ayuntamiento (https://www.laspalmasgc.es/es/ayuntamiento/pleno-y-comisiones/plenos/),
con una entrada por sesión («Sesión ordinaria de fecha 31.10.2025») y el enlace al acta
(`PL-A-AAAAMMDD-nn-T[-sufijos].pdf`; los sufijos cambian: -TIM, -asa-MC-corr, .report…, así que la
URL se lee de la página y no se construye).

Las actas digitales traen, tras cada asunto, un bloque muy regular:

    CUÓRUM DE VOTACIÓN DE LA MOCIÓN: rechazada por mayoría Número de votantes: 28 [12 (G. P. M.
    Socialista); 9 (G. P. M. Popular); …] Presentes: 28 […] Votos a favor: 11 [9 (G. P. M. Popular);
    1 (G. Mixto-CCa); 1 (no adscrita)] Votos en contra: 14 [12 (G. P. M. Socialista); 2 (G. Mixto-NC-FAC)]
    Abstenciones: 3 (G. P. M. Vox)

que se lee con reglas (fuente «pdf-reglas»): totales, votos por grupo en cada sentido, resultado,
mayoría y asentimiento. El título sale del orden del día del propio acta (en minúsculas) emparejado
con el epígrafe en mayúsculas del cuerpo; si no se empareja, del epígrafe. Cada bloque es una
votación (enmiendas, urgencia, dejar sobre la mesa y votación final van por separado, con subtítulo).

Cobertura: solo las actas con texto, desde la sesión del 28.3.2025 (en septiembre de 2026: 29 actas
digitales, 26 con votaciones, 282 votaciones; todos los bloques «CUÓRUM» se leen). Las anteriores
(2007 a febrero de 2025, también las de 2019-2024 de la lista antigua) son imágenes escaneadas sin
capa de texto (pdffonts no da ninguna fuente) y pesan hasta 160 MB, así que no se descargan: harían
falta OCR. La mediateca Séneca del Ayuntamiento (laspalmasgc.seneca.tv) tiene el orden del día de
cada sesión, pero su API (/api/masters/<id>/timeline.json) pide usuario.
`documentos(ctx)` da las mismas actas digitales para el extractor con LLM (respaldo de las reglas y
de las sesiones con otro formato, como las de honores y distinciones).

Limitaciones:
- Los grupos van con el nombre del acta, normalizado solo en variantes de escritura («NCFAC»,
  «Cca», «No Adscrita»). Cuando el Grupo Mixto vota dividido, el acta separa sus componentes
  («G. Mixto-CCa», «G. Mixto-NC-FAC»), y así se guardan.
- En los empates se guarda cada votación sin resultado (lo decide el voto de calidad, que el
  bloque no recoge); extra["empate"] lo marca.
- La sesión es el número de acta del año (varias sesiones pueden caer el mismo día).
- Las votaciones de sesiones especiales sin bloque «CUÓRUM» (honores, votación secreta) no se
  sacan con reglas: quedan para el LLM.

Incremental: se lee la página de plenos (sin caché) y solo se descargan las actas con fecha igual o
posterior a ctx.desde(cuerpo, margen_dias=120) (las actas se publican uno o dos meses tarde); cada PDF
queda en caché.
"""

import html
import re
import unicodedata

from ... import territorio
from ..modelo import Documento, Votacion, VotoGrupo

CUERPO = "ayto-laspalmas"
BASE = "https://www.laspalmasgc.es"
EXPORT = BASE + "/export/sites/laspalmasgc"
WEB = BASE + "/es/ayuntamiento/pleno-y-comisiones/plenos/"
# Primera acta con capa de texto (28.3.2025). Las anteriores son escaneos.
DESDE_DIGITAL = "2025-03-01"

CUERPOS = [
    territorio.Cuerpo(CUERPO, territorio.num_municipio("35016"), "Ayuntamiento de Las Palmas de Gran Canaria",
                      "Ayto. Las Palmas de GC", "municipal", "CN", 29, dict(territorio.MANDATOS_LOCALES), WEB),
]

NOTAS = ("Actas del Pleno en PDF (laspalmasgc.es). Votos por grupo y totales con reglas del bloque "
         "«CUÓRUM DE VOTACIÓN». Solo desde marzo de 2025: las actas anteriores son escaneos sin texto "
         "(harían falta OCR). Los empates quedan sin resultado; el Grupo Mixto dividido se guarda por "
         "componentes.")


# ------------------------------------------------------------------ sesiones

def _decodificar(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1")


def _absoluta(href):
    href = html.unescape(href)
    if href.startswith("http"):
        return href
    if href.startswith("/.galleries"):
        return EXPORT + href
    return BASE + href


def sesiones(ctx):
    """Sesiones de la página de plenos con acta, de la más reciente a la más antigua."""
    pagina = _decodificar(ctx.fetch(WEB))
    out = []
    for trozo in re.split(r"<h2[ >]", pagina)[1:]:
        cab = re.sub(r"<[^>]+>", " ", trozo.split("</h2>")[0])
        cab = re.sub(r"\s+", " ", html.unescape(cab)).strip()
        f = re.search(r"de fecha (\d{1,2})[./](\d{1,2})[./](\d{4})", cab)
        a = re.search(r'<a href="([^"]+\.pdf)"[^>]*>\s*Acta\s*</a>', trozo.split("<h2")[0])
        if not f or not a:
            continue
        fecha = f"{f.group(3)}-{int(f.group(2)):02d}-{int(f.group(1)):02d}"
        url = _absoluta(a.group(1))
        n = re.search(r"PL-(?:A-)?\d{8}-(\d{1,2})-", url)
        out.append({"fecha": fecha, "url": url, "numero": int(n.group(1)) if n else 0, "titulo": cab,
                    "tipo": _tipo_sesion(cab)})
    vistos, unicas = set(), []
    for s in sorted(out, key=lambda s: (s["fecha"], s["numero"]), reverse=True):
        if s["url"] not in vistos:
            vistos.add(s["url"])
            unicas.append(s)
    return unicas


def _tipo_sesion(cab):
    c = cab.lower()
    if "extraordinaria" in c:
        return "extraordinaria" + (" y urgente" if "urgente" in c else "")
    return "ordinaria" if "ordinaria" in c else None


def _a_recoger(ctx, sesiones_):
    # Las actas se firman y publican uno o dos meses después de la sesión: margen amplio (las ya
    # descargadas salen de la caché).
    desde = ctx.desde(CUERPO, margen_dias=120)
    for s in sesiones_:
        if s["fecha"] < DESDE_DIGITAL or (desde and s["fecha"] < desde):
            break
        yield s


def _texto_bruto(ctx, url):
    nombre = re.sub(r"[^\w.-]+", "_", url.rsplit("/", 1)[-1])
    pdf = ctx.fetch(url, cache=f"{CUERPO}/actas/{nombre}")
    return ctx.pdf_texto(pdf, layout=False)


# ------------------------------------------------------------------ texto

RUIDO = [
    re.compile(r"Código Seguro De Verificación.*?\(art\. 27 Ley 39/2015\)\.", re.S),
    re.compile(r"^Excmo\. Ayuntamiento Pleno de Las Palmas de Gran Canaria\. Acta n[úu]m\..*$", re.M),
    re.compile(r"^(?:BORRADOR DEL )?ACTA N[ÚUúu]M\. ?\d+.*$", re.M | re.I),
    re.compile(r"^\s*Página \d+ de \d+\s*$", re.M),
    # Cabecera de página partida en líneas (poppler): «BORRADOR DEL ACTA» / «Núm. 6» / «Fecha: 25.4.2025».
    re.compile(r"^\s*(?:BORRADOR DEL ACTA|N[úu]m\. ?\d+|Fecha: ?\d{1,2}\.\d{1,2}\.\d{4})\s*$", re.M),
    re.compile(r"^\*{5,}\s*$", re.M),
]


def limpiar(texto):
    """Quita el pie de firma electrónica que se repite en cada página y las líneas vacías."""
    texto = texto.replace("\f", "\n")
    for r in RUIDO:
        texto = r.sub("\n", texto)
    return "\n".join(ln.strip() for ln in texto.split("\n") if ln.strip())


def _norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^0-9A-Za-z]+", " ", s).upper().strip()


def _mayusculas(s):
    letras = [c for c in s if c.isalpha()]
    return len(letras) >= 8 and sum(c.isupper() for c in letras) / len(letras) > 0.85


# ------------------------------------------------------------------ orden del día y epígrafes

VOTO_RE = re.compile(r"^[CQ]U[ÓO]RUM DE VOTACI[ÓO]N\b")
EPIGRAFE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*|ÚNICO|UNICO)\s*[.:]?\s*[-–]?\s+(\S.{6,})$")
PARTE_RE = re.compile(r"^[A-D]\)\s+PARTE\b")
CORTE_TITULO = re.compile(
    r"\s(?:\((?:Se vota|Se toma raz[oó]n|Asuntos|---)[^)]*\)|[A-D]\) PARTE\b|Enmienda presentada\b|Se procede a\b|"
    r"(?:[A-ZÁÉÍÓÚÑ]{2,}[ ,]+){3,}[A-ZÁÉÍÓÚÑ]{2,})")


def _corta_titulo(cuerpo):
    """Quita lo que se pega detrás del título en el índice (área siguiente, «(Se vota)»…)."""
    for m in CORTE_TITULO.finditer(" " + cuerpo):
        if m.start() > 0 and re.search(r"[a-zá-úñ]", cuerpo[:m.start()]):
            return cuerpo[:m.start()].strip()
    return cuerpo.strip()


def _fin_indice(lineas, inicio):
    """Línea donde acaba el orden del día y empieza el desarrollo de la sesión.

    Es la frase «Se procede a continuación a tratar…», la primera votación, la segunda aparición
    de una misma parte («A) PARTE RESOLUTIVA») o un epígrafe en mayúsculas que repite uno del índice.
    """
    vistos, partes = set(), set()
    for i in range(inicio + 1, len(lineas)):
        ln = lineas[i]
        if VOTO_RE.match(ln) or re.match(r"(?i)^Se procede a continuaci[óo]n a tratar", ln):
            return i
        if PARTE_RE.match(ln):
            if ln[0] in partes:
                return i
            partes.add(ln[0])
            continue
        m = EPIGRAFE_RE.match(ln)
        if m:
            clave = _norm(m.group(2))[:40]
            if _mayusculas(m.group(2)) and clave in vistos:
                return i
            vistos.add(clave)
    return len(lineas)


def orden_del_dia(lineas):
    """Asuntos del orden del día (en minúsculas) que encabeza el acta: [(número, título)]."""
    inicio = next((i for i, ln in enumerate(lineas) if _norm(ln) == "ORDEN DEL DIA"), None)
    if inicio is None:
        return []
    fin = _fin_indice(lineas, inicio)
    bloque = re.sub(r"(?:(?<=\s)|^)[ÚU]NICO\s*[.:]\s", "1. ", " ".join(lineas[inicio + 1:fin]))
    trozos = re.split(r"(?:(?<=\s)|^)(\d{1,2}(?:\.\d{1,2})*)\s?\.\s+(?=[A-ZÁÉÍÓÚÑ¿«\"“])", bloque)
    out = []
    for num, cuerpo in zip(trozos[1::2], trozos[2::2]):
        titulo = _corta_titulo(cuerpo)
        if len(titulo) < 8 or _mayusculas(titulo):
            continue
        out.append((num, titulo.rstrip(" .;")))
    return out


def _numeros(num):
    return [int(x) for x in num.split(".") if x.isdigit()] or [1]


def _sigue(prev, c):
    """¿El epígrafe numerado c puede venir después de prev (hermano, subapartado o siguiente)?"""
    if not prev:
        return all(x == 1 for x in c[1:])
    for k in range(len(prev), 0, -1):
        base = prev[:k - 1] + [prev[k - 1] + 1]
        if c[:k] == base and all(x == 1 for x in c[k:]):
            return True
    return c[:len(prev)] == prev and len(c) > len(prev) and all(x == 1 for x in c[len(prev):])


def _prefijo_comun(a, b):
    k = 0
    for x, y in zip(a, b):
        if x != y:
            break
        k += 1
    return k


def _empareja(titulo, num, orden):
    """Título del orden del día que corresponde a un epígrafe en mayúsculas (o None).

    Gana el que comparte el prefijo más largo (muchos empiezan igual: «Moción que formula el Grupo
    Político Municipal Popular relativa a…») y, a igualdad, el del mismo número.
    """
    n = _norm(titulo)
    mejor, puntos = None, (0, False)
    for numero, t in orden:
        m = _norm(t)
        k = _prefijo_comun(n, m)
        if k < min(20, len(n), len(m)) or k < 0.5 * min(len(n), len(m)):
            continue
        p = (k, numero == num)
        if p > puntos:
            mejor, puntos = t, p
    if mejor:
        return mejor
    # Redacción distinta en el índice y en el epígrafe («Aprobación, si procede, de las actas…» /
    # «APROBACIÓN DE ACTAS…»): mismo número y bastantes palabras en común.
    palabras = {w for w in n.split() if len(w) > 3}
    mejor, puntos = None, 0
    for numero, t in orden:
        if numero != num:
            continue
        comunes = len(palabras & {w for w in _norm(t).split() if len(w) > 3})
        if comunes >= 3 and comunes >= 0.4 * len(palabras) and comunes > puntos:
            mejor, puntos = t, comunes
    return mejor


def _frase(s):
    s = s.strip().rstrip(".")
    return s[:1].upper() + s[1:].lower()


# ------------------------------------------------------------------ bloques de votación

ETIQUETA_RE = re.compile(r"(N[úu]mero de votantes|VOTANTES|Votantes|Presentes|PRESENTES|Votos a favor|VOTOS A FAVOR|"
                         r"Votos en contra|VOTOS EN CONTRA|Abstenciones|ABSTENCIONES)\s*:", re.I)
CONTINUA_RE = re.compile(r"^(?:N[úu]mero de votantes|VOTANTES|Presentes|Votos a favor|Votos en contra|Abstenciones|"
                         r"\d+\s*[\[(]|\[)", re.I)


def _sigue_bloque(acumulado, siguiente):
    """¿La línea siguiente pertenece aún al bloque «CUÓRUM»?

    Según el pdftotext (xpdf o poppler) el bloque sale en una línea por párrafo o partido en
    líneas físicas («… 3 (G. P.» / «M. Vox); 1 (no adscrita)]»), así que se sigue mientras falte
    cerrar un corchete o paréntesis, la cabecera no tenga aún sus dos puntos o la línea empiece
    por otra etiqueta.
    """
    if CONTINUA_RE.match(siguiente):
        return True
    if len(acumulado) > 2500 or EPIGRAFE_RE.match(siguiente) or re.match(r"(?i)INCIDENCIAS|La señora|El señor", siguiente):
        return False
    if ":" not in acumulado:
        return len(acumulado) < 300
    if not ETIQUETA_RE.search(acumulado):
        return len(siguiente) < 80          # la frase de la cabecera sigue en otra línea («… mayoría» / «absoluta»)
    # Un paréntesis sin cerrar por errata no debe tragarse el párrafo siguiente (línea larga de prosa).
    corta = len(siguiente) < 160 or bool(re.search(r"[\])]", siguiente[:80]))
    if corta and (acumulado.count("[") > acumulado.count("]") or acumulado.count("(") > acumulado.count(")")):
        return True
    return corta and acumulado.rstrip().endswith((";", ",", "(", "[", ":"))


def _grupo(nombre):
    n = re.sub(r"\s+", " ", nombre).strip(" ;,.")
    n = re.sub(r"(?i)^concejala?\s+", "", n)
    low = n.lower()
    if "adscrit" in low:
        return "No adscritos" if "adscritos" in low else ("No adscrita" if "adscrita" in low else "No adscrito")
    n = re.sub(r"\s*([-/])\s*", r"\1", n)
    n = n.replace("NCFAC", "NC-FAC")
    n = re.sub(r"\bC[Cc][Aa]\b", "CCa", n)
    n = re.sub(r"Mixto(?=[A-Z])", "Mixto-", n)
    n = re.sub(r"^(?:G\.\s*P\.\s*M\.?|GPM)\s*", "G. P. M. ", n)
    n = re.sub(r"^G\.\s*(?=Mixto)", "G. ", n)
    n = re.sub(r"^G\. Mixto\s+", "G. Mixto-", n)
    if re.fullmatch(r"(?:NC-FAC|USP|CCa)(?:/(?:NC-FAC|USP|CCa))*", n):
        n = "G. Mixto-" + n  # componente del Grupo Mixto escrito sin el grupo
    return n


def _elemento(texto):
    """«12 (G. P. M. Socialista)», «3 (G. Mixto-NC-FAC/USP» o «1 G. Mixto CCa» -> (12, grupo)."""
    m = re.match(r"\s*(\d+)\s*\(?\s*(.+?)\s*\)?\s*$", texto, re.S)
    if not m or not re.search(r"[A-Za-z]", m.group(2)):
        return None
    return int(m.group(1)), _grupo(m.group(2))


def _lista(seg):
    """«25 [12 (G. P. M. Socialista); 9 (…)]», «3 (G. P. M. Vox)» o «ninguno» -> (total, [(n, grupo)])."""
    seg = seg.strip()
    if re.match(r"(?i)ningun[oa]s?\b|cero\b", seg):
        return 0, []
    m = re.match(r"(\d+)\s*(.*)$", seg, re.S)
    if not m:
        return None, []
    total, resto = int(m.group(1)), m.group(2).strip()
    if resto.startswith("["):
        resto = resto[1:resto.rfind("]")] if "]" in resto else resto[1:]
        # A veces falta el «;» entre grupos: «3 (G. P. M. Vox) 1 (G. Mixto-CCa)».
        resto = re.sub(r"\)\s*(?=\d+\s*\()", ");", resto)
        grupos = [e for e in map(_elemento, resto.split(";")) if e]
    elif resto.startswith("("):
        e = _elemento(f"{total} {resto[:resto.find(')') + 1] if ')' in resto else resto}")
        grupos = [e] if e else []
    else:
        grupos = []
    return total, grupos


def parsear_bloque(texto):
    """Bloque «CUÓRUM DE VOTACIÓN …» -> dict con subtítulo, resultado, totales y grupos."""
    cab, _, resto = texto.partition(":")
    que = re.sub(r"^[CQ]U[ÓO]RUM DE VOTACI[ÓO]N\s*", "", cab).strip()
    marcas = list(ETIQUETA_RE.finditer(resto))
    frase = (resto[:marcas[0].start()] if marcas else resto).strip()
    listas = {}
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(resto)
        clave = _norm(m.group(1))
        clave = {"NUMERO DE VOTANTES": "VOTANTES"}.get(clave, clave)
        listas.setdefault(clave, _lista(resto[m.end():fin]))
    f = frase.lower()
    if "rechaz" in f or "desestim" in f:
        resultado = "rechazada"
    elif "empate" in f:
        resultado = None
    elif re.search(r"aprob|ratific|asentimiento|estimad|unanim", f):
        resultado = "aprobada"
    else:
        resultado = None
    return {
        "que": que,
        "frase": frase,
        "resultado": resultado,
        "empate": "empate" in f,
        "mayoria": "absoluta" if "absoluta" in f else ("simple" if "simple" in f else None),
        "asentimiento": "asentimiento" in f,
        "unanimidad": "unanim" in f,
        "votantes": listas.get("VOTANTES", (None, []))[0],
        "presentes": listas.get("PRESENTES", (None, []))[0],
        "si": listas.get("VOTOS A FAVOR"),
        "no": listas.get("VOTOS EN CONTRA"),
        "abst": listas.get("ABSTENCIONES"),
    }


def _grupos_voto(b):
    por = {}
    for clave, campo in (("si", "si"), ("no", "no"), ("abst", "abstencion")):
        for n, g in (b[clave] or (None, []))[1]:
            d = por.setdefault(g, {"si": 0, "no": 0, "abstencion": 0})
            d[campo] += n
    out = []
    for g, d in por.items():
        sentidos = [k for k, v in d.items() if v]
        out.append(VotoGrupo(g, si=d["si"], no=d["no"], abstencion=d["abstencion"],
                             sentido=sentidos[0] if len(sentidos) == 1 else ("dividido" if sentidos else None)))
    return out


def _tipo_iniciativa(t):
    n = _norm(t)
    if "MOCION" in n:
        return "mocion"
    if re.search(r"\b(ORDENANZA|REGLAMENTO)\b", n):
        return "ordenanza"
    if "PRESUPUESTO GENERAL" in n and not re.search(r"MODIFICACION|LIQUIDACION|EJECUCION PRESUPUESTARIA|CUENTA GENERAL", n):
        return "presupuesto"
    if re.search(r"\b(ACTAS? DE (LAS )?SESION|DESIGNACION|REPRESENTANTE|NOMBRAMIENTO|COMISIONES DE PLENO|"
                 r"AREAS DE GOBIERNO|ORGANOS COLEGIADOS|COMPATIBILIDAD|TOMA DE POSESION|NO ADSCRIT|"
                 r"CUESTION DE ORDEN|URGENCIA DE LA CONVOCATORIA)", n):
        return "organizacion"
    if re.search(r"\b(COMPARECENCIA|PREGUNTA|DACION DE CUENTA|TOMA DE (CONOCIMIENTO|RAZON))\b", n):
        return "control"
    return "acuerdo"


def _autor(t):
    m = re.search(r"(?i)moci[óo]n que formulan? (?:el |la |los |las )?(.+?),? (?:relativa|para|sobre|en relaci[óo]n|"
                  r"instando|con motivo|de apoyo|a fin)", t)
    if m:
        return m.group(1).strip(" ,")
    if re.search(r"(?i)proposici[óo]n de la alcaldesa|proposici[óo]n del alcalde", t):
        return "Alcaldía"
    return None


def _tipo_votacion(que, tipo_ini, unica):
    """Tipo de votación. En las mociones con varias votaciones sin rótulo, las primeras suelen ser
    enmiendas que el acta no nombra: solo se marca «mocion» la rotulada o la única del asunto."""
    q = _norm(que)
    if "ENMIENDA" in q:
        return "enmiendas"
    if "URGENCIA" in q or "SOBRE LA MESA" in q or "RETIRADA" in q:
        return "organizacion"
    if tipo_ini == "mocion" and ("MOCION" in q or (not q and unica)):
        return "mocion"
    return None


def votaciones_acta(texto, sesion, url):
    """Votaciones (Votacion) de un acta ya limpia. `sesion` es el dict de sesiones()."""
    lineas = texto.split("\n")
    orden = orden_del_dia(lineas)
    inicio = next((i for i, ln in enumerate(lineas) if _norm(ln) == "ORDEN DEL DIA"), None)
    # Sesiones de un solo asunto: su título vale para todas las votaciones (el epígrafe del cuerpo
    # a veces no va en mayúsculas).
    prev, titulo, epigrafe = [], (orden[0][1] if len(orden) == 1 else None), None
    bloques, sin_titulo = [], 0
    i = _fin_indice(lineas, inicio) if inicio is not None else 0
    while i < len(lineas):
        ln = lineas[i]
        if _mayusculas(ln) and not EPIGRAFE_RE.match(ln):
            # «ÁREA DE GOBIERNO DE … ÓRGANO DE GESTIÓN PRESUPUESTARIA 1. PRESUPUESTO GENERAL …»
            m = re.search(r"\s(\d{1,2}(?:\.\d{1,2})*\s*\.\s+[A-ZÁÉÍÓÚÑ«“\"].*)$", ln)
            if m:
                ln = m.group(1)
        if PARTE_RE.match(ln):
            prev = []
        elif re.match(r"^CUESTI[ÓO]N DE ORDEN\s*$", ln):
            titulo, epigrafe = "Cuestión de orden", None
        elif VOTO_RE.match(ln):
            inicio_bloque = i
            partes = [ln]
            while i + 1 < len(lineas) and not VOTO_RE.match(lineas[i + 1]) and _sigue_bloque(" ".join(partes), lineas[i + 1]):
                i += 1
                partes.append(lineas[i])
            antes = " ".join(lineas[max(0, inicio_bloque - 4):inicio_bloque])[-400:]
            bloques.append((titulo, epigrafe, " ".join(partes), antes))
        else:
            m = EPIGRAFE_RE.match(ln)
            if m and _mayusculas(m.group(2)):
                cand = m.group(2)
                if i + 1 < len(lineas) and _mayusculas(lineas[i + 1]) and not EPIGRAFE_RE.match(lineas[i + 1]) \
                        and not VOTO_RE.match(lineas[i + 1]) and not cand.rstrip().endswith((")", ".")):
                    cand += " " + lineas[i + 1]
                num = _numeros(m.group(1))
                bueno = _empareja(cand, m.group(1) if m.group(1)[0].isdigit() else "1", orden)
                # Con índice, solo cuentan los epígrafes que están en él (en el texto hay listas
                # numeradas en mayúsculas); sin índice, los que siguen la numeración.
                if bueno or (not orden and _sigue(prev, num)):
                    prev = num
                    titulo = bueno or _frase(cand)
                    epigrafe = m.group(1)
        i += 1
    out = []
    por_asunto = {}
    for tit, epi, _b, _a in bloques:
        por_asunto[(tit, epi)] = por_asunto.get((tit, epi), 0) + 1
    for n, (tit, epi, bloque, antes) in enumerate(bloques, 1):
        unica = por_asunto[(tit, epi)] == 1
        b = parsear_bloque(bloque)
        if b["resultado"] is None and not b["empate"]:
            # «CUÓRUM DE VOTACIÓN: mayoría absoluta»: el resultado va en la frase anterior
            # («…se somete el asunto a votación, resultando aprobado por…»).
            ms = list(re.finditer(r"(?i)\b(?:resulta(?:ndo)?|queda(?:ndo)?|es|fue|siendo)\s+(aprobad|rechazad|desestimad|"
                                  r"ratificad)", antes))
            m = ms[-1] if ms else None
            if m:
                b["resultado"] = "rechazada" if m.group(1).lower() in ("rechazad", "desestimad") else "aprobada"
        if tit is None:
            sin_titulo += 1
            tit = "Asunto sin identificar"
        a_favor = b["si"][0] if b["si"] else None
        en_contra = b["no"][0] if b["no"] else None
        abst = b["abst"][0] if b["abst"] else None
        if b["resultado"] is None and a_favor is None and not b["asentimiento"]:
            continue
        tipo = _tipo_iniciativa(tit)
        extra = {"epigrafe": epi, "frase": b["frase"][:200]}
        rgp = re.search(r"(?i)\bRGP\s*n[úu]m\.?\s*(\d+)", tit)
        if rgp:
            extra["rgp"] = rgp.group(1)
        if b["empate"]:
            extra["empate"] = True
        if sesion.get("tipo"):
            extra["sesion_tipo"] = sesion["tipo"]
        out.append(Votacion(
            cuerpo=CUERPO, fecha=sesion["fecha"], titulo=tit, sesion=sesion["numero"], numero=n,
            subtitulo=("Votación " + b["que"].lower()) if b["que"] else None,
            tipo_iniciativa=tipo, tipo_votacion=_tipo_votacion(b["que"], tipo, unica), autor=_autor(tit),
            a_favor=a_favor, en_contra=en_contra, abstenciones=abst,
            presentes=b["presentes"] if b["presentes"] is not None else b["votantes"],
            asentimiento=b["asentimiento"], resultado=b["resultado"], mayoria=b["mayoria"],
            grupos=_grupos_voto(b), url=sesion["url"], fuente="pdf-reglas", extra=extra))
    return out, len(bloques), sin_titulo


def _numero_acta(bruto):
    """Número de acta del año, del encabezado («Número 16/2025») o del pie («Acta núm. 17 (O)»)."""
    m = (re.search(r"(?m)^\s*N[úu]mero (\d{1,2})/\d{4}\s*$", bruto[:3000])
         or re.search(r"Acta n[úu]m\. ?(\d{1,2}) \(", bruto))
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------ conector

def descargar(ctx):
    n = 0
    total_bloques = total_votos = total_sin_titulo = 0
    for s in _a_recoger(ctx, sesiones(ctx)):
        bruto = _texto_bruto(ctx, s["url"])
        if len(bruto.strip()) < 2000:
            ctx.log(f"  {CUERPO}: acta sin texto (¿escaneada?) {s['url']}")
            continue
        texto = limpiar(bruto)
        if not s["numero"]:
            s = dict(s, numero=_numero_acta(bruto))
        votos, bloques, sin_titulo = votaciones_acta(texto, s, s["url"])
        total_bloques += bloques
        total_votos += len(votos)
        total_sin_titulo += sin_titulo
        for v in votos:
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    ctx.log(f"  {CUERPO}: {total_votos} votaciones de {total_bloques} bloques «CUÓRUM»"
            f" ({total_sin_titulo} sin asunto identificado)")


def documentos(ctx):
    n = 0
    for s in _a_recoger(ctx, sesiones(ctx)):
        yield Documento(cuerpo=CUERPO, fecha=s["fecha"], url=s["url"], sesion=s["numero"], formato="pdf",
                        idioma="es", titulo=s["titulo"], extra={"sesion_tipo": s["tipo"]} if s["tipo"] else {})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    """Texto del acta sin los pies de firma de cada página (se reutiliza la caché de descargar)."""
    return limpiar(_texto_bruto(ctx, doc.url))
