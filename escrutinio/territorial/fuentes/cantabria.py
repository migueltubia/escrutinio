"""Parlamento de Cantabria: actas del Pleno en PDF, votaciones con reglas y catálogo de iniciativas.

Fuente: el listado de actas de sesiones (https://parlamento-cantabria.es/actividad/actas), filtrado
por el órgano «Pleno del Parlamento de Cantabria». Hay un órgano por legislatura y sus ids se leen del
propio formulario, así que una legislatura nueva aparece sola. Cada acta es un PDF corto
(ACTPLnnn-AAAA-MMDDhh.pdf) que resume cada punto del orden del día con su expediente entre corchetes
([11L/4300-0413]) y el resultado de cada votación con los totales (en letra) y, casi siempre, los grupos
por siglas: «resulta aprobado por veintitrés votos a favor (NA, R y P) y once en contra (V y S)».

No hay datos abiertos de votaciones: la página de transparencia remite a la videoteca. Cada punto se vota
con una frase muy regular tras «Sometida/Sometido/Sometidas/Sometidos a votación…»: «es aprobada/rechazada
por <N> votos a favor (<siglas>)[, <N> en contra (<siglas>)][ y <N> abstenciones (<siglas>)]», «aprobada
por unanimidad de los treinta y cinco Diputados y Diputadas que componen la Cámara» (recuento con todo el
Pleno) o, sin cifra, «por unanimidad»/«por asentimiento» (asentimiento, sin recuento). Las siglas de grupo
cambian con la legislatura y con el tiempo dentro de una misma legislatura (el Grupo Ciudadanos pasó a
«Grupo Mixto-Ciudadanos», MC; Vox entró como «Grupo Mixto-Vox», MV; los diputados sin grupo son «NA», de
«Diputado/a no adscrito/a»); se reconocen buscando en la propia acta el nombre completo del grupo («Grupo
Parlamentario Popular», «Grupo Parlamentario Mixto-Vox»…) y expandiendo la sigla a ese nombre. Un empate
se resuelve por el artículo 94 del Reglamento: unas veces con una sola frase que dice que se repitió tres
veces («al producirse la votación en tres ocasiones y persistir el empate…»), otras narrando cada repetición
por separado («…promueve una nueva votación, lográndose el mismo resultado. Se somete a una tercera
votación, alcanzándose idéntico desenlace»); en el segundo caso se guarda una Votacion por cada intento,
todas con el mismo recuento y solo la última con resultado (rechazada). Una investidura (o moción de censura)
se vota por llamamiento y la Presidencia proclama los totales sin desglose por grupo.

En los presupuestos (decenas de enmiendas) y en el debate general anual sobre la orientación política del
Gobierno (decenas de propuestas de resolución, una por grupo), la Presidencia anuncia una sola vez que se
procede a votarlas y cada tanda con el mismo resultado es su propia frase, sin volver a decir «Sometida a
votación»: «Las enmiendas 1, 2 y 3, son rechazadas por…», «La enmienda 24, es rechazada por…», «El voto
particular a la enmienda 50, es rechazado por…», o, por grupo, «P 4, P 6, P 12: Son aprobadas por…» (P, R…
es la sigla del grupo autor). Cada tanda se guarda como una sola Votacion (como hace el propio patrón oro),
con el número de enmienda o de propuesta como subtítulo.

Cuando el acta es un PDF escaneado sin texto (unas 30 de 462, sobre todo de 2020 a 2022), se usa en su lugar
el Diario de Sesiones (serie A): mucho más largo y sin voto por grupo, pero la Presidencia (o la Secretaría)
lee igualmente el recuento tras preguntar «¿Votos a favor?[, ¿votos en contra?][, ¿abstenciones?]» y alguien
proclama «Queda aprobada/rechazada por…» o «Se aprueba/rechaza por…», que las mismas reglas leen (sin grupos
ni expediente fiable, con un título más pobre sacado de lo que se dice justo antes, si lo hay).

`descargar()` da además el catálogo de iniciativas que se votan en Pleno (proyectos y proposiciones de
ley, PNL ante el Pleno, mociones, investiduras…) desde el buscador de tramitación
(/actividad/tramitacion-parlamentaria), ordenado por expediente para que la paginación sea estable:
expediente, tipo, extracto, autor (sacado del «presentada por…» del extracto) y fecha de entrada.

Cobertura: Pleno desde febrero de 2013 (la VIII legislatura, de 2011, solo está completa desde esa
fecha) hasta hoy; IX, X y XI completas (462 actas).
Limitaciones: los números van a veces en letra (siempre, en los recuentos); las siglas de grupo cambian con
la legislatura y no siempre se encuentran en la propia acta (entonces ese grupo se omite del desglose, sin
inventar su nombre). Los títulos vienen de la cabecera del punto, que está en mayúsculas: se pasan a
minúsculas salvo la inicial, sin respetar los nombres propios. La fecha es la del listado; el número de
sesión sale del nombre del fichero, que alguna vez está mal (el acta 24 se publicó como ACTPL025). Si una
sesión tiene dos PDF (acta y adicional, o subidas repetidas), van en un solo documento. Los días en que el
acta (o el Diario, si está escaneada) muestra votaciones pero las reglas no leen ningún recuento usable
(investiduras con papeleta, votaciones secretas, recuentos ilegibles) van a `documentos()` para el LLM.
"""

import hashlib
import html
import re
import unicodedata
import urllib.parse
from datetime import date, timedelta

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import CACHE_DIR
from ..modelo import Documento, Iniciativa, Votacion, VotoGrupo

CUERPO = "parl-CB"
BASE = "https://parlamento-cantabria.es"
LISTADO = BASE + "/actividad/actas"
DIARIOS = BASE + "/actividad/publicaciones/diarios-de-sesiones"
TRAMITACION = BASE + "/actividad/tramitacion-parlamentaria"
CAMPO_ORGANO = "field_organo_relacionado_target_id_verf"

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("CB"), "Parlamento de Cantabria", "Parlamento (Cantabria)", "autonomico", "CB", 35,
           {8: ("VIII", "2011-06-16", "2015-06-18", 39),
            9: ("IX", "2015-06-18", "2019-06-20"),
            10: ("X", "2019-06-20", "2023-06-22"),
            11: ("XI", "2023-06-22", None)},
           web=LISTADO),
]

NOTAS = ("Votaciones del Pleno con reglas sobre las actas en PDF: cada punto se vota con una frase regular "
         "(«es aprobada/rechazada por N votos a favor (siglas)...», unanimidad con o sin recuento, empates "
         "resueltos por el artículo 94); las siglas de grupo (que cambian con la legislatura, incluso a media "
         "legislatura) se expanden buscando el nombre completo del grupo en la propia acta. Si el acta está "
         "escaneada, el Diario de Sesiones, sin voto por grupo. Pleno desde 2013 (VIII incompleta), IX a XI "
         "completas. Los días con votación que las reglas no consiguen leer (investiduras por llamamiento con "
         "papeleta, votaciones secretas, recuentos ilegibles) van al LLM. Catálogo de iniciativas de Pleno "
         "(VIII a XI) desde el buscador de tramitación.")

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
OPCION_RE = re.compile(r'<option value="(\d+)"[^>]*>\s*Pleno del Parlamento[^<]*</option>')
FILA_RE = re.compile(r'<a href="(/sites/default/files/actas/[^"]+)"[^>]*>([^<]*)</a>.*?<time [^>]*>([^<]*)<', re.S)
FECHA_RE = re.compile(r"(\d{1,2}),\s*([a-záéíóú]+),\s*(\d{4})", re.I)
NUM_RE = re.compile(r"ACTPL\s*0*(\d+)", re.I)
DIARIO_RE = re.compile(r'<a href="(/publicaciones/diariodesesion/[^"]+)"[^>]*>([^<]*)</a>')
PDF_DIARIO_RE = re.compile(r'href="((?:https://parlamento-cantabria\.es)?/sites/default/files/[^"]+\.pdf)"', re.I)
FASCICULO_RE = re.compile(r"fasc[^\d]{0,8}(\d+)", re.I)
SELECT_RE = r'<select[^>]*name="{}"[^>]*>(.*?)</select>'
OPCIONES_RE = re.compile(r'<option value="(\d+)"[^>]*>([^<]+)</option>')
EXPEDIENTE_RE = re.compile(
    r'<a href="(/actividad/tramitacion/[^"]+)"[^>]*>([^<]+)</a>.*?field-tipo-expediente">(.*?)</td>.*?'
    r'field-fecha-evento">.*?(\d{2})/(\d{2})/(\d{4}).*?</td>.*?field-extracto">(.*?)</td>', re.S)
# El último «presentada por…» del extracto (antes puede citarse la interpelación de otro autor).
AUTOR_RE = re.compile(r".*presen-?\s?tad[oa]s?(?: por)? (?:el |la |los |las )?(.+?)\.?$", re.I | re.S)

# Tipos de expediente del buscador que se votan en Pleno -> clave de modelo.TIPOS_INICIATIVA
TIPOS_EXPEDIENTE = {
    "proyectos de ley": "pl",
    "proposiciones de ley": "ppl",
    "proposiciones de ley de iniciativa legislativa popular": "ilp",
    "proyecto de ley de presupuestos generales de la comunidad autónoma": "presupuesto",
    "proposiciones no de ley ante el pleno": "pnl",
    "mociones": "mocion",
    "investidura": "investidura",
    "moción de censura": "investidura",
    "cuestión de confianza": "investidura",
    "debate general sobre la orientación política del gobierno": "control",
    "designación de senador": "organizacion",
    "designaciones y nombramientos": "organizacion",
}
ROMANOS = {romano(n): n for n in range(1, 30)}


def _organos_pleno(ctx):
    """Ids del órgano «Pleno del Parlamento de Cantabria» (uno por legislatura) en el formulario."""
    h = ctx.texto(LISTADO)
    ids = []
    for oid in OPCION_RE.findall(h):
        if oid not in ids:
            ids.append(oid)
    return ids


def _fecha(texto):
    m = FECHA_RE.search(texto)
    if not m or m.group(2).lower() not in MESES:
        return None
    return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _actas(ctx, organo, desde):
    """Actas del Pleno de un órgano, de la más reciente a la más antigua: [(fecha, url)]."""
    filas, pagina = [], 0
    while True:
        h = ctx.texto(f"{LISTADO}?{CAMPO_ORGANO}={organo}&page={pagina}")
        nuevas = []
        for ruta, titulo, cuando in FILA_RE.findall(h):
            fecha = _fecha(cuando)
            if fecha and titulo.strip().startswith("Pleno"):
                nuevas.append((fecha, BASE + ruta))
        filas += nuevas
        if not nuevas or f"page={pagina + 1}" not in h or (desde and min(f for f, _ in nuevas) < desde):
            return filas
        pagina += 1


def _numero(url):
    m = NUM_RE.search(urllib.parse.unquote(url.rsplit("/", 1)[-1]))
    return int(m.group(1)) if m else 0


def _principal(urls):
    """El PDF principal de una sesión: el que no es un adicional ni una copia (sufijo _0)."""
    return sorted(urls, key=lambda u: (bool(re.search(r"adic|_\d+\.pdf$", u, re.I)), len(u), u))[0]


def _dias_pleno(ctx, desde):
    """Sesiones plenarias con acta, de la más reciente a la más antigua: [(fecha, sesion, principal, otros)]."""
    grupos = {}  # (fecha, sesión) -> [urls]
    for organo in _organos_pleno(ctx):
        for fecha, url in _actas(ctx, organo, desde):
            if desde and fecha < desde:
                continue
            grupos.setdefault((fecha, _numero(url)), []).append(url)
    out = []
    for (fecha, sesion), urls in sorted(grupos.items(), reverse=True):
        principal = _principal(urls)
        otros = sorted(u for u in set(urls) if u != principal)
        out.append((fecha, sesion, principal, otros))
    return out


def documentos(ctx):
    """Días con acta cuyo texto (o el del Diario, si está escaneada) muestra alguna votación pero de los que
    las reglas no consiguen leer ningún recuento usable: para el LLM.

    Para saberlo hay que leer el texto entero: se miran los ya descargados (en esta ejecución o antes) y los
    RECIENTES últimos, para que listar los documentos en una ejecución sin caché (GitHub Actions) no
    descargue todo el archivo cada día.
    """
    desde = ctx.desde(CUERPO)
    dias = _dias_pleno(ctx, desde)
    n = 0
    for i, (fecha, sesion, principal, otros) in enumerate(dias):
        if desde and fecha < desde:
            continue
        legislatura = CUERPOS[0].legislatura_de(fecha)
        if legislatura is None:
            continue
        if i >= RECIENTES and not _en_cache(principal, otros):
            continue
        doc = Documento(CUERPO, fecha, principal, sesion=sesion, formato="pdf", idioma="es", legislatura=legislatura,
                        titulo=f"Acta n.º {sesion} de la sesión plenaria" if sesion else "Acta del Pleno",
                        extra={"otros_pdf": otros} if otros else {})
        escanos = CUERPOS[0].escanos_de(legislatura)
        try:
            t = texto(ctx, doc)
        except Exception as e:  # web caída, PDF corrupto…: se reintenta en la próxima ejecución
            ctx.log(f"  ! {CUERPO}: acta {sesion} ({fecha}) no disponible ({type(e).__name__}: {e})")
            continue
        votos = _votos_de_texto(t, escanos)
        if not votos and _hay_senal_voto(t):
            yield doc
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


RECIENTES = 15  # actas que se comprueban aunque no estén en caché, para acotar una ejecución sin caché


def _pdf_en_cache(url):
    nombre = re.sub(r"[^A-Za-z0-9._-]", "_", urllib.parse.unquote(url.rsplit("/", 1)[-1]))
    carpeta = CACHE_DIR / CUERPO / "actas"
    return carpeta.is_dir() and any(carpeta.glob(f"*-{nombre}.gz"))


def _en_cache(principal, otros):
    return _pdf_en_cache(principal) and all(_pdf_en_cache(u) for u in otros)


def _pdf(ctx, url, carpeta):
    nombre = re.sub(r"[^A-Za-z0-9._-]", "_", urllib.parse.unquote(url.rsplit("/", 1)[-1]))
    return ctx.fetch(url, cache=f"{CUERPO}/{carpeta}/{ctx.clave(url)}-{nombre}")


def _texto_diario(ctx, doc):
    """Texto del Diario de Sesiones (serie A) de la sesión: los PDF de cada punto, fascículo a fascículo."""
    if not doc.sesion:
        return ""
    fin = (date.fromisoformat(doc.fecha) + timedelta(days=4)).isoformat()
    q = urllib.parse.urlencode({"field_fecha_evento_value[min]": doc.fecha, "field_fecha_evento_value[max]": fin})
    patron = re.compile(rf"(?:n[º°o]\.?\s*|sesi[oó]n\s+){doc.sesion}(?!\d)(?!\s*[-.]?\s*B)", re.I)
    paginas = {ruta: titulo for ruta, titulo in DIARIO_RE.findall(ctx.texto(f"{DIARIOS}?{q}")) if patron.search(titulo)}
    partes = []
    for ruta in sorted(paginas, key=lambda r: int((FASCICULO_RE.search(paginas[r]) or [0, 0])[1])):
        h = ctx.texto(BASE + ruta, cache=f"{CUERPO}/diarios/{ctx.clave(ruta)}.html")
        # Un PDF por punto del orden del día («Punto 3 Pleno 108…», «Punto único 1-A»), sin el sumario ni
        # los PDF genéricos del menú de la web.
        pdfs = [u for u in dict.fromkeys(PDF_DIARIO_RE.findall(h)) if "sumario" not in u.lower()]
        puntos = [u for u in pdfs if "punto" in urllib.parse.unquote(u).lower()]
        for url in puntos or [u for u in pdfs if "/files/diarios/" in u]:
            partes.append(ctx.pdf_texto(_pdf(ctx, urllib.parse.urljoin(BASE, url), "diarios"), layout=False))
    return "\n\n".join(partes)


def texto(ctx, doc):
    """Texto del acta (y de sus PDF adicionales, sin repetir los idénticos); si está escaneada, el del Diario."""
    partes, vistos = [], set()
    for url in [doc.url, *(doc.extra or {}).get("otros_pdf", [])]:
        raw = _pdf(ctx, url, "actas")
        clave = hashlib.sha1(raw).hexdigest()
        if clave in vistos:
            continue
        vistos.add(clave)
        partes.append(ctx.pdf_texto(raw, layout=False))
    t = "\n\n".join(partes)
    if len(t.strip()) < 500:
        diario = _texto_diario(ctx, doc)
        if diario.strip():
            return f"[Acta escaneada sin texto: Diario de Sesiones del Pleno n.º {doc.sesion}]\n\n{diario}"
    return t


# ---------------------------------------------------------------------- números en letra

_UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "ninguno": 0, "ninguna": 0, "ningun": 0,
}
_DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
# formas acentuadas (tal como aparecen en el texto) de los números de una sola palabra y de las decenas, para
# el patrón que reconoce una cifra en letra sin confundirla con una palabra cualquiera («votos», «ninguna»…)
_PALABRAS_UNIDAD = (
    "cero", "un", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
    "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
    "veinte", "veintiuno", "veintiún", "veintiuna", "veintidós", "veintitrés", "veinticuatro", "veinticinco",
    "veintiséis", "veintisiete", "veintiocho", "veintinueve", "ningún", "ninguno", "ninguna",
)
_PALABRAS_DECENA = ("treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa")
_PALABRA_UNIDAD_RE = "|".join(sorted(_PALABRAS_UNIDAD, key=len, reverse=True))
_PALABRA_DECENA_RE = "|".join(sorted(_PALABRAS_DECENA, key=len, reverse=True))


def _plano(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _numero_es(texto):
    """Entero en letra («treinta y cinco», «diecinueve», «ocho») o en dígitos; None si no se reconoce."""
    p = _plano(texto).strip()
    if not p:
        return None
    if p.isdigit():
        return int(p)
    if p in _UNIDADES:
        return _UNIDADES[p]
    if p in _DECENAS:
        return _DECENAS[p]
    m = re.match(r"^(treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)\s+y\s+(\w+)$", p)
    if m and m.group(2) in _UNIDADES:
        return _DECENAS[m.group(1)] + _UNIDADES[m.group(2)]
    return None


# ---------------------------------------------------------------------- limpieza del texto del acta

PAGINA_RE = re.compile(r"(?m)^[ \t]*\d{1,4}(?:\.\d{1,3})?[ \t]*$")


def _aplanar(t):
    """Texto del acta en una sola línea, sin las marcas de página («71.6») que pdftotext deja sueltas."""
    t = (t or "").replace("\x0c", "\n").replace("\r\n", "\n").replace("\r", "\n")
    t = PAGINA_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _frase(t):
    """Cabecera en mayúsculas del acta -> frase legible (sin respetar nombres propios)."""
    t = re.sub(r"\s+", " ", t or "").strip(" ,.;:-")
    if not t:
        return None
    if t == t.upper():
        t = t.capitalize()
    return t


# ---------------------------------------------------------------------- grupos parlamentarios (siglas)

_GRUPOS_CONOCIDOS = [
    (re.compile(r"\bmixto[\s-]+ciudadanos\b", re.I), "MC", "Grupo Parlamentario Mixto-Ciudadanos"),
    (re.compile(r"\bmixto[\s-]+vox\b", re.I), "MV", "Grupo Parlamentario Mixto-Vox"),
    (re.compile(r"\bmixto[\s-]+podemos\b", re.I), "MP", "Grupo Parlamentario Mixto-Podemos"),
    (re.compile(r"(?<!mixto-)(?<!mixto )\bpodemos\b", re.I), "Po", "Grupo Parlamentario Podemos Cantabria"),
    (re.compile(r"\bpopular\b", re.I), "P", "Grupo Parlamentario Popular"),
    (re.compile(r"\bsocialista\b", re.I), "S", "Grupo Parlamentario Socialista"),
    (re.compile(r"\bregionalista\b", re.I), "R", "Grupo Parlamentario Regionalista"),
    (re.compile(r"(?<!mixto-)(?<!mixto )\bciudadanos\b", re.I), "C", "Grupo Parlamentario Ciudadanos"),
    (re.compile(r"(?<!mixto-)(?<!mixto )\bvox\b", re.I), "V", "Grupo Parlamentario Vox"),
    (re.compile(r"\bgrupo\s+(?:parlamentario\s+)?mixto\b(?!\s*[\s-]*(?:ciudadanos|vox|podemos))", re.I), "M",
     "Grupo Parlamentario Mixto"),
]
NA_RE = re.compile(r"\bdiputad([oa])s?\s+no\s+adscrit([oa])s?\b", re.I)


def _grupos_documento(flat):
    """{sigla: nombre completo del grupo} con los grupos que se mencionan en esta acta."""
    tabla = {}
    for rx, sigla, nombre in _GRUPOS_CONOCIDOS:
        if sigla not in tabla and rx.search(flat):
            tabla[sigla] = nombre
    m = NA_RE.search(flat)
    if m:
        tabla["NA"] = f"Diputad{m.group(1)} no adscrit{m.group(2)}"
    return tabla


def _grupos_de(contenido, tabla, sentido):
    """[VotoGrupo] de un paréntesis de siglas («NA, MC, S, P y R»); descarta lo que no se reconoce (p. ej.
    el nombre de un diputado que vota distinto de su grupo)."""
    if not contenido:
        return []
    out = []
    siglas = sorted(tabla, key=len, reverse=True)
    for token in re.split(r"\s*(?:,|;|\by\b)\s*", contenido.strip(" .")):
        token = token.strip(" .-")
        i = 0
        while i < len(token):
            for sigla in siglas:
                if token[i:i + len(sigla)] == sigla:
                    out.append(VotoGrupo(tabla[sigla], sentido=sentido))
                    i += len(sigla)
                    break
            else:
                break  # resto no reconocible: se descarta sin inventar
    return out


# ---------------------------------------------------------------------- recuento de una votación

_NUM_TXT = (r"(?:\d{1,3}|(?:" + _PALABRA_DECENA_RE + r")\s+y\s+(?:" + _PALABRA_UNIDAD_RE + r")|" +
           _PALABRA_DECENA_RE + "|" + _PALABRA_UNIDAD_RE + ")")
FAVOR_RE = re.compile(rf"\b({_NUM_TXT})\s+votos?\s+a\s+favor(?:\s*\(([^)]{{1,150}})\))?", re.I)
CONTRA_RE = re.compile(rf"\b({_NUM_TXT})\s+(?:votos?\s+)?en\s+contra(?:\s*\(([^)]{{1,150}})\))?", re.I)
ABST_RE = re.compile(rf"\b({_NUM_TXT})\s+abstenci[oó]n(?:es)?(?:\s*\(([^)]{{1,150}})\))?", re.I)
NINGUN_CONTRA_RE = re.compile(r"\bning[uú]n\s+voto\s+en\s+contra\b", re.I)
NINGUNA_ABST_RE = re.compile(r"\bninguna\s+abstenci[oó]n\b", re.I)
UNANIME_N_RE = re.compile(
    r"unanimidad\s+de\s+los?\s+([a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)\s+diputad", re.I)
UNANIME_RE = re.compile(r"\bpor\s+unanimidad\b", re.I)
ASENTIMIENTO_RE = re.compile(r"\bpor\s+asentimiento\b", re.I)
RESULTADO_RE = re.compile(r"\b(aprobad[oa]s?|rechazad[oa]s?|desestimad[oa]s?|desechad[oa]s?|apru[eé]ba[n]?|"
                          r"rechaza[n]?)\b", re.I)
EMPATE_A_RE = re.compile(r"\bempat[eo]\s+a\s+(\d{1,2})\b", re.I)
# dónde acaba el «objeto» de la votación (lo que se vota) y empieza el veredicto, para recortar el subtítulo
VEREDICTO_RE = re.compile(
    r"\b(?:es|son)\s+(?=aprobad[oa]s?\b|rechazad[oa]s?\b|desestimad[oa]s?\b|desechad[oa]s?\b)|"
    r"\bel\s+resultado\s+(?:de\s+la\s+(?:misma|votaci[oó]n)\s+)?es\s+de\b|\bse\s+obtiene\s+empate\s*:", re.I)


def _resultado_de(t):
    m = RESULTADO_RE.search(t)
    if not m:
        return None
    p = _plano(m.group(1))
    return "aprobada" if p.startswith(("aprobad", "aprueb", "aprob")) else "rechazada"


def _lectura(u, escanos, tabla):
    """{a_favor, en_contra, abstenciones, grupos, asentimiento, resultado} de un tramo con un recuento, o
    None si no se lee ningún voto ni unanimidad."""
    fav, con, abst = FAVOR_RE.search(u), CONTRA_RE.search(u), ABST_RE.search(u)
    a_favor = _numero_es(fav.group(1)) if fav else None
    en_contra = _numero_es(con.group(1)) if con else None
    abstenciones = _numero_es(abst.group(1)) if abst else None
    if en_contra is None and NINGUN_CONTRA_RE.search(u):
        en_contra = 0
    if abstenciones is None and NINGUNA_ABST_RE.search(u):
        abstenciones = 0
    grupos = []
    for m, sentido in ((fav, "si"), (con, "no"), (abst, "abstencion")):
        if m and m.group(2):
            grupos += _grupos_de(m.group(2), tabla, sentido)
    asentimiento = False
    resultado = _resultado_de(u)
    mu = UNANIME_N_RE.search(u)
    if a_favor is None and mu:
        a_favor = _numero_es(mu.group(1)) or escanos
        en_contra, abstenciones = 0, 0
        resultado = resultado or "aprobada"
    elif a_favor is None and (UNANIME_RE.search(u) or ASENTIMIENTO_RE.search(u)):
        asentimiento = True
        resultado = resultado or "aprobada"
    elif a_favor is None:
        me = EMPATE_A_RE.search(u)
        if me:
            a_favor = en_contra = int(me.group(1))
    if a_favor is None and en_contra is None and abstenciones is None and not asentimiento:
        return None
    if resultado is None and a_favor is not None and en_contra is not None and a_favor == en_contra:
        resultado = "rechazada"  # un empate que no se resuelve a favor nunca se aprueba
    extra = {}
    if sum(x or 0 for x in (a_favor, en_contra, abstenciones)) > escanos:
        extra["totales_descartados"] = f"{a_favor}-{en_contra}-{abstenciones}"  # lectura imposible: más votos que escaños
        a_favor = en_contra = abstenciones = None
        grupos = []
    return {"a_favor": a_favor, "en_contra": en_contra, "abstenciones": abstenciones, "grupos": grupos,
            "asentimiento": asentimiento, "resultado": resultado, "extra": extra}


# ---------------------------------------------------------------------- artículo 94 (empates repetidos)

REPITE_2_RE = re.compile(
    r"promueve\s+una\s+nueva\s+votaci[oó]n,?\s+(?:logr[aá]ndose|obteni[eé]ndose|consigui[eé]ndose)\s+el\s+mismo\s+resultado",
    re.I)
REPITE_3_RE = re.compile(
    r"tercera\s+votaci[oó]n[^.]{0,80}?(?:alcanz[aá]ndose|logr[aá]ndose|obteni[eé]ndose)\s+"
    r"(?:id[eé]ntico\s+desenlace|el\s+mismo\s+resultado)", re.I)


def _repeticiones(u, base):
    """Copias de `base` (mismo recuento) por cada repetición explícita de una votación empatada («…promueve
    una nueva votación, lográndose el mismo resultado. Se somete…a una tercera votación…»)."""
    extra = []
    if REPITE_2_RE.search(u):
        extra.append({**base, "resultado": None})
        if REPITE_3_RE.search(u):
            extra.append({**base, "resultado": base["resultado"] or "rechazada"})
    return extra


# ---------------------------------------------------------------------- cabeceras de punto

CABECERA_RE = re.compile(r"(?:VOTACI[ÓO]N\s+DEL\s+)?PUNTO\s+(?:(\d{1,3})|([ÚU]NICO))\s*[.\-–—:]+\s*", re.I)
EXP_RE = re.compile(r"\[\s*(\d{1,2}L)\s*/\s*([\d\s-]{3,12})\s*\]", re.I)
PRESENTADA_RE = re.compile(r"presentad[oa]s?\s+por\s+(?:el\s+|la\s+|los\s+|las\s+)?(.{3,120}?)(?:\.\s*\(BOPCA|\.\s*$|$)",
                           re.I | re.S)


def _normaliza_exp(prefijo, digitos):
    d = re.sub(r"\s+", "", digitos)
    if "-" not in d and len(d) >= 7:
        d = d[:4] + "-" + d[4:]
    return f"{prefijo.upper()}/{d}"


def _tipo_de_cabecera(cab):
    c = _plano(cab)
    if re.search(r"presupuestos\s+generales|proyecto\s+de\s+ley\s+de\s+presupuestos", c):
        return "presupuesto"
    if re.search(r"decreto\s*-?\s*ley", c):
        return "dl"
    if re.search(r"proyecto\s+de\s+ley", c):
        return "pl"
    if re.search(r"iniciativa\s+legislativa\s+popular", c):
        return "ilp"
    if re.search(r"proposicion\s+de\s+ley\b", c):
        return "ppl"
    if re.search(r"proposicion\s+no\s+de\s+ley", c):
        return "pnl"
    if re.search(r"mocion\s+de\s+censura|cuestion\s+de\s+confianza|investidura|candidat[oa]\s+a\s+(?:la\s+)?"
                 r"president", c):
        return "investidura"
    if re.search(r"\bmocion\b", c):
        return "mocion"
    if re.search(r"designacion|eleccion\s+de|nombramiento", c):
        return "organizacion"
    if re.search(r"orientacion\s+politica|comunicacion\s+del\s+gobierno", c):
        return "control"
    return None


def _autor_de_cabecera(cab, tipo):
    m = PRESENTADA_RE.search(cab)
    txt = m.group(1) if m else cab
    grupos = [nombre for rx, _s, nombre in _GRUPOS_CONOCIDOS if rx.search(txt)]
    if grupos:
        return " y ".join(dict.fromkeys(grupos))
    mna = NA_RE.search(txt)
    if mna:
        return f"Diputad{mna.group(1)} no adscrit{mna.group(2)}"
    if not m and tipo in ("pl", "presupuesto"):
        return "Gobierno de Cantabria"
    return None


def _titulo_de_cabecera(cab):
    m = re.search(r"relativ[oa]s?\s+a\s+", cab, re.I)
    if m:
        resto = cab[m.end():]
    else:
        m2 = re.search(r"(proyecto\s+de\s+ley|proposici[oó]n\s+(?:de\s+ley|no\s+de\s+ley)|moci[oó]n|"
                       r"iniciativa\s+legislativa\s+popular)", cab, re.I)
        resto = cab[m2.start():] if m2 else cab
    resto = re.split(r",?\s*presentad[oa]s?\s+por\b", resto, maxsplit=1, flags=re.I)[0]
    resto = re.sub(r"\(BOPCA.*$", "", resto, flags=re.I)
    resto = re.sub(r"\[[^\[\]]*\]\s*$", "", resto)  # el expediente entre corchetes, si queda al final
    return _frase(resto)


def _subtitulo_de(objeto):
    o = re.sub(r"\s+", " ", objeto or "").strip(" ,.")
    o = re.sub(r"^(?:y|e)\b\s*", "", o, flags=re.I).strip(" ,.")
    if len(o) < 4:
        return None
    if re.match(r"^(?:la\s+)?toma\s+en\s+consideraci[oó]n\b", o, re.I):
        return "Toma en consideración"
    m = re.search(r"con\s+la\s+incorporaci[oó]n\s+de\s+la\s+enmienda\s+(?:presentada|transaccional)"
                 r"(?:\s+(?:propuesta\s+)?por\s+(?:el|los|la|las)\s+(.+?))?,?\s*que\s+sustituye\s+al\s+texto\s+inicial",
                 o, re.I)
    if m:
        return f"Texto con la enmienda de sustitución de {m.group(1)}" if m.group(1) else \
            "Texto con la enmienda de sustitución"
    generico = {"la propuesta de resolucion", "el dictamen", "la mocion", "la proposicion no de ley",
               "el proyecto de ley", "la proposicion de ley", "el texto", "la iniciativa", "el voto particular"}
    if _plano(o) in generico:
        return None
    return _frase(o)


def _tipo_votacion(tipo, contexto):
    c = _plano(contexto)
    if tipo == "investidura":
        return "investidura"
    if "toma en consideracion" in c:
        return "toma_consideracion"
    if "enmienda a la totalidad" in c or ("totalidad" in c and "enmiend" in c):
        return "totalidad"
    if re.search(r"enmiendas?|voto particular", c):
        return "enmiendas"
    if re.search(r"articulos?|disposicion|texto articulado", c):
        return "articulado"
    if tipo == "pnl":
        return "pnl"
    if tipo == "mocion":
        return "mocion"
    if tipo == "control":
        return "control"
    if tipo == "organizacion":
        return "nombramiento" if re.search(r"eleccion|designacion", c) else "organizacion"
    if tipo == "dl":
        return "convalidacion"
    if tipo in ("pl", "ppl", "ilp", "presupuesto") and re.search(r"conjunto|dictamen|texto definitivo", c):
        return "conjunto"
    return None


# ---------------------------------------------------------------------- votación por llamamiento (investidura)

INVESTIDURA_RE = re.compile(
    r"Concluida\s+la\s+votaci[oó]n,?\s+la\s+Presidencia\s+proclama\s+que\s+la?\s+candidat[oa].{0,250}?"
    r"ha\s+obtenido\s+([a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)\s+votos?\s+a\s+favor,?\s+"
    r"([a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)\s+(?:votos?\s+)?en\s+contra\s+y\s+"
    r"([a-záéíóúñ]+(?:\s+y\s+[a-záéíóúñ]+)?)\s+abstencion(?:es)?\s*;?\s*y,?\s+por\s+lo\s+tanto,?\s+"
    r"(no\s+)?ha\s+(?:alcanzado|obtenido)\s+la\s+(mayor[ií]a\s+absoluta|mayor[ií]a\s+simple|confianza)", re.I | re.S)


def _votos_investidura(flat, meta):
    votos = []
    for i, m in enumerate(INVESTIDURA_RE.finditer(flat), 1):
        a_favor, en_contra, abstenciones = (_numero_es(m.group(k)) for k in (1, 2, 3))
        rechazada = bool(m.group(4))
        mayoria_txt = _plano(m.group(5))
        mayoria = "absoluta" if "absoluta" in mayoria_txt else ("simple" if "simple" in mayoria_txt else None)
        orden = "Primera" if i == 1 else "Segunda" if i == 2 else f"{i}.ª"
        subtitulo = f"{orden} votación" + (f", por mayoría {mayoria}" if mayoria else "")
        votos.append({**meta, "a_favor": a_favor, "en_contra": en_contra, "abstenciones": abstenciones,
                      "grupos": [], "asentimiento": False, "resultado": "rechazada" if rechazada else "aprobada",
                      "mayoria": mayoria, "subtitulo": subtitulo, "tipo_votacion": "investidura", "_pos": m.start()})
    return votos


# ---------------------------------------------------------------------- señal de que hay votaciones (para documentos())

SENAL_VOTO_RE = re.compile(
    r"Sometid[oa]s?\s+a\s+votaci[oó]n|Efectuada\s+la\s+votaci[oó]n|Concluida\s+la\s+votaci[oó]n|"
    r"Se\s+procede\s+a\s+la\s+votaci[oó]n|Se\s+somete(?:n)?\s+a\s+votaci[oó]n|"
    r"\bVotos?\s+a\s+favor\b|\bqueda(?:n)?\s+aprobad|\bqueda(?:n)?\s+rechazad|\bpor\s+unanimidad\b|"
    r"\bpor\s+asentimiento\b|\bescrutinio\b|\bproclamad[oa]\b|\belegid[oa]s?\b|\bpapeletas?\b|"
    r"\bvotaci[oó]n\s+(?:secreta|p[uú]blica)\b", re.I)


def _hay_senal_voto(texto_bruto):
    return bool(SENAL_VOTO_RE.search(texto_bruto))


# ---------------------------------------------------------------------- disparadores de un recuento

TRIGGER_RE = re.compile(r"\bSometid[oa]s?\s+(?:a\s+votaci[oó]n|votaci[oó]n)\b|\bEfectuada?s?\s+la\s+votaci[oó]n\b|"
                        r"\bSe\s+procede\s+a\s+la\s+votaci[oó]n\s+del\s+[Dd]ictamen\b|"
                        r"\bSe\s+somete(?:n)?\s+a\s+votaci[oó]n(?:\s+separada)?\b", re.I)

# Votaciones en bloque, sin disparador propio: la Presidencia anuncia una sola vez «se procede a la votación
# de las enmiendas, con el siguiente resultado» y cada tanda (una enmienda o varias con el mismo resultado)
# es su propia frase («Las enmiendas 1, 2 y 3, son rechazadas por...», «La enmienda 24, es rechazada por...»);
# lo mismo con los votos particulares o, en el debate general, con las propuestas de resolución por grupo.
LOTE_ENMIENDA_RE = re.compile(
    r"\b(?P<etq>Las\s+enmiendas|La\s+enmienda|Los\s+votos\s+particulares\s+a\s+las\s+enmiendas|"
    r"El\s+voto\s+particular\s+a\s+la\s+enmienda)\s*:?\s+(?:n[uú]meros?\s+)?"
    r"(?P<lista>\d[\d,\sy]*?)\s*,?\s+(?:son|es)\s+(?:aprobad[oa]s?|rechazad[oa]s?)\s+por\s+[^.]{1,200}\.", re.I)
_SIGLA_PROPUESTA = r"(?:MC|MV|Po|NA|[PSRVCM])"
LOTE_PROPUESTA_RE = re.compile(
    rf"\b(?P<lista>{_SIGLA_PROPUESTA}\s*\d+(?:\s*,\s*{_SIGLA_PROPUESTA}?\s*\d+)*)\s*:\s*(?i:son|es)\s+"
    r"(?i:aprobad[oa]s?|rechazad[oa]s?)\s+por\s+[^.]{1,200}\.")
GRUPO_PROPUESTAS_RE = re.compile(r"PROPUESTAS?\s+DE\s+RESOLUCI[OÓ]N\s+DEL\s+(GRUPO\s+PARLAMENTARIO\s+\S+"
                                 r"(?:[\s-]+\S+)?)\s*:", re.I)


def _analiza_acta(texto_bruto, escanos):
    """[dict] de las votaciones que las reglas leen en el texto de un acta (o del Diario), en orden."""
    flat = _aplanar(texto_bruto)
    tabla = _grupos_documento(flat)
    cabeceras = list(CABECERA_RE.finditer(flat))
    metas = {}
    for i, m in enumerate(cabeceras):
        num = m.group(1) or "unico"
        limite = cabeceras[i + 1].start() if i + 1 < len(cabeceras) else min(len(flat), m.end() + 1200)
        resto = flat[m.end():limite]
        mb = EXP_RE.search(resto)
        cab_txt = resto[:mb.end()] if mb else resto[:700]
        expediente = _normaliza_exp(*mb.groups()) if mb else None
        tipo = _tipo_de_cabecera(cab_txt)
        meta = {"titulo": _titulo_de_cabecera(cab_txt) or _frase(cab_txt[:200]), "expediente": expediente,
                "tipo_iniciativa": tipo, "autor": _autor_de_cabecera(cab_txt, tipo), "_cab": cab_txt}
        actual = metas.get(num)
        if not actual or len(cab_txt) > len(actual.get("_cab", "")):
            metas[num] = meta

    def punto_de(pos):
        num = "unico"
        for m in cabeceras:
            if m.start() > pos:
                break
            num = m.group(1) or "unico"
        return num

    disparadores = list(TRIGGER_RE.finditer(flat))
    votos, cubierto = [], []
    for i, m in enumerate(disparadores):
        fin = disparadores[i + 1].start() if i + 1 < len(disparadores) else len(flat)
        for c in cabeceras:
            if m.end() < c.start() < fin:
                fin = c.start()
                break
        unidad = flat[m.start():fin]
        cubierto.append((m.start(), fin))
        base = _lectura(unidad, escanos, tabla)
        if base is None:
            continue
        meta = metas.get(punto_de(m.start()), {})
        # el objeto (lo que se vota) acaba donde empieza el recuento o el veredicto, lo que venga antes
        cortes = [x.start() for x in (FAVOR_RE.search(unidad), CONTRA_RE.search(unidad), ABST_RE.search(unidad),
                                      VEREDICTO_RE.search(unidad), UNANIME_RE.search(unidad),
                                      ASENTIMIENTO_RE.search(unidad)) if x]
        corte = min(cortes) if cortes else len(unidad)
        objeto = unidad[len(TRIGGER_RE.match(unidad).group(0)) if TRIGGER_RE.match(unidad) else 0:corte]
        entrada = {**meta, "subtitulo": _subtitulo_de(objeto), **base, "_pos": m.start()}
        entrada["tipo_votacion"] = _tipo_votacion(meta.get("tipo_iniciativa"), f"{objeto} {meta.get('titulo') or ''}")
        votos.append(entrada)
        for rep in _repeticiones(unidad, base):
            votos.append({**meta, "subtitulo": entrada["subtitulo"], **rep, "_pos": m.start() + 0.5,
                         "tipo_votacion": entrada["tipo_votacion"]})

    # votaciones en bloque (enmiendas, votos particulares, propuestas de resolución del debate general): la
    # Presidencia anuncia una sola vez que se procede a votarlas y cada tanda es su propia frase, sin disparador.
    def _cubierto(pos):
        return any(a <= pos < b for a, b in cubierto)

    for m in LOTE_ENMIENDA_RE.finditer(flat):
        if _cubierto(m.start()):
            continue
        base = _lectura(m.group(0), escanos, tabla)
        if base is None:
            continue
        meta = metas.get(punto_de(m.start()), {})
        etq = {"las enmiendas": "Enmiendas", "la enmienda": "Enmienda",
              "los votos particulares a las enmiendas": "Votos particulares a las enmiendas",
              "el voto particular a la enmienda": "Voto particular a la enmienda"}.get(
            _plano(m.group("etq")), _frase(m.group("etq")))
        votos.append({**meta, "subtitulo": f"{etq} {re.sub(r'\\s+', ' ', m.group('lista')).strip()}", **base,
                     "tipo_votacion": "enmiendas", "_pos": m.start()})
        cubierto.append((m.start(), m.end()))

    vistos_lote = set()
    for m in LOTE_PROPUESTA_RE.finditer(flat):
        # una maquetación a varias columnas a veces hace que pdftotext repita literalmente una frase: no se
        # cuenta dos veces la misma tanda de propuestas con el mismo resultado
        if _cubierto(m.start()) or m.group(0) in vistos_lote:
            continue
        vistos_lote.add(m.group(0))
        base = _lectura(m.group(0), escanos, tabla)
        if base is None:
            continue
        meta = dict(metas.get(punto_de(m.start()), {}))
        lista = re.sub(r"\s*,\s*", ", ", re.sub(_SIGLA_PROPUESTA + r"\s*", "", m.group("lista"))).strip(" ,")
        grp = GRUPO_PROPUESTAS_RE.search(flat[max(0, m.start() - 1500):m.start()])
        if grp:
            meta["autor"] = _autor_de_cabecera(grp.group(1), None) or _frase(grp.group(1))
        else:
            sigla = re.match(_SIGLA_PROPUESTA, m.group("lista").strip())
            if sigla and sigla.group(0) in tabla:
                meta["autor"] = tabla[sigla.group(0)]
        votos.append({**meta, "subtitulo": f"Propuesta{'s' if ',' in lista else ''} de resolución n.º {lista}",
                     **base, "tipo_votacion": "control", "_pos": m.start()})
        cubierto.append((m.start(), m.end()))

    votos += _votos_investidura(flat, {"titulo": metas.get("unico", {}).get("titulo"),
                                       "expediente": metas.get("unico", {}).get("expediente"),
                                       "tipo_iniciativa": "investidura", "autor": None})
    votos.sort(key=lambda v: v["_pos"])
    return votos


PREGUNTA_VOTOS_RE = re.compile(r"¿\s*Votos?\s+a\s+favor\b[^?¿]{0,25}\?", re.I)
PUNTO_DIARIO_RE = re.compile(
    r"(?:Punto\s+n[uú]mero\s+\d{1,3}|Propuesta(?:s)?(?:\s+(?:del\s+Grupo\s+\S+(?:\s+\S+){0,2}|"
    r"n[uú]mero\s+[\d,\sy]+))?)[^.?]*$", re.I)


def _diario_votos(texto_bruto, escanos):
    """Votaciones del Diario de Sesiones (acta escaneada): la Presidencia pregunta «¿Votos a favor?[, ¿votos
    en contra?][, ¿abstenciones?]», la Secretaría lee el recuento y la Presidencia proclama el resultado
    («Queda aprobada/rechazada…», «Se aprueba por…»); sin grupos ni expediente, con un título pobre (el
    número de punto o de propuesta que se menciona justo antes, si lo hay)."""
    flat = _aplanar(texto_bruto)
    votos = []
    preguntas = list(PREGUNTA_VOTOS_RE.finditer(flat))
    for i, m in enumerate(preguntas):
        fin = preguntas[i + 1].start() if i + 1 < len(preguntas) else min(len(flat), m.end() + 400)
        tramo = flat[m.end():fin]
        base = _lectura(tramo[:280], escanos, {})
        if base is None:
            continue
        if base.get("resultado") is None:
            vm = RESULTADO_RE.search(tramo)
            if vm:
                base["resultado"] = _resultado_de(vm.group(0))
        mp = PUNTO_DIARIO_RE.search(flat[max(0, m.start() - 200):m.start()])
        titulo = _frase(mp.group(0)) if mp else None
        votos.append({"titulo": titulo or "Punto del orden del día", "expediente": None, "tipo_iniciativa": None,
                     "autor": None, "subtitulo": None, "tipo_votacion": None, **base, "_pos": m.start()})
    votos.sort(key=lambda v: v["_pos"])
    return votos


def _votos_de_texto(texto_bruto, escanos):
    if texto_bruto.lstrip().startswith("[Acta escaneada"):
        return _diario_votos(texto_bruto, escanos)
    return _analiza_acta(texto_bruto, escanos)


def _votacion(fecha, sesion, legislatura, url, n, v):
    extra = dict(v.get("extra") or {})
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=v.get("titulo") or "Punto del orden del día", sesion=sesion, numero=n,
        legislatura=legislatura, subtitulo=v.get("subtitulo"), expediente=v.get("expediente"),
        tipo_iniciativa=v.get("tipo_iniciativa"), tipo_votacion=v.get("tipo_votacion"), autor=v.get("autor"),
        a_favor=v.get("a_favor"), en_contra=v.get("en_contra"), abstenciones=v.get("abstenciones"),
        asentimiento=bool(v.get("asentimiento")), resultado=v.get("resultado"),
        mayoria=v.get("mayoria") if v.get("mayoria") in ("absoluta", "simple") else None, grupos=v.get("grupos") or [],
        url=url, fuente="pdf-reglas", extra=extra)


# ---------------------------------------------------------------------- catálogo de iniciativas

def _limpia(fragmento):
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragmento))
    t = re.sub(r"\bE \[", "[", t)  # «E [11L/4100-0371]»: la E es el icono del enlace al expediente
    t = re.sub(r"(?<=[^\W\d]) \+ (?=[^\W\d])", " ", t)  # «Grupo + Parlamentario Popular»: resto de un enlace
    return re.sub(r"\s+", " ", t).strip()


def _opciones(h, campo):
    m = re.search(SELECT_RE.format(re.escape(campo)), h, re.S)
    return [(v, _limpia(t)) for v, t in OPCIONES_RE.findall(m.group(1))] if m else []


def _catalogo_iniciativas(ctx, desde):
    """Iniciativas que se votan en Pleno, del buscador de tramitación (de la legislatura más reciente a la
    más antigua). Generador aparte para que su propio tope de `ctx.limite` no corte las votaciones."""
    n = 0
    h = ctx.texto(TRAMITACION)
    tipos = [v for v, t in _opciones(h, "field_tipo_expediente_target_id") if t.lower() in TIPOS_EXPEDIENTE]
    legs = []
    for v, t in _opciones(h, "field_legislatura_agora_target_id"):
        leg = ROMANOS.get(t.split()[0])
        if leg in CUERPOS[0].legislaturas:
            fin = CUERPOS[0].legislaturas[leg][2]
            if not (desde and fin and fin < desde):
                legs.append((leg, v))
    base = [("field_tipo_expediente_target_id[]", t) for t in tipos] + [("order", "field_numexp"), ("sort", "desc")]
    if desde:
        base.append(("field_fecha_evento_value[min]", desde))
    for leg, valor in sorted(legs, reverse=True):
        pagina = 0
        while True:
            q = urllib.parse.urlencode(base + [("field_legislatura_agora_target_id", valor), ("page", pagina)])
            h = ctx.texto(f"{TRAMITACION}?{q}")
            filas = EXPEDIENTE_RE.findall(h)
            for ruta, expediente, tipo, d, m, a, extracto in filas:
                tipo, extracto = _limpia(tipo), _limpia(extracto)
                clave = TIPOS_EXPEDIENTE.get(tipo.lower(), "otro")
                m_autor = AUTOR_RE.search(extracto)
                autor = m_autor.group(1).strip() if m_autor and len(m_autor.group(1)) < 200 else None
                if not autor and clave in ("pl", "presupuesto"):
                    autor = "Gobierno de Cantabria"  # los proyectos de ley los presenta siempre el Gobierno
                yield Iniciativa(CUERPO, expediente.strip(), extracto, legislatura=leg,
                                 tipo_iniciativa=clave, autor=autor,
                                 fecha_presentacion=f"{a}-{m}-{d}", url=BASE + ruta, extra={"tipo": tipo})
                n += 1
                if ctx.limite and n >= ctx.limite:
                    return
            if not filas or f"page={pagina + 1}" not in h:
                break
            pagina += 1


def descargar(ctx):
    """Iniciativas que se votan en Pleno (catálogo del buscador de tramitación) y, por cada sesión plenaria
    dentro de `ctx.desde`, las votaciones que las reglas leen de su acta."""
    desde = ctx.desde(CUERPO)
    yield from _catalogo_iniciativas(ctx, desde)

    n_total = 0
    for fecha, sesion, principal, otros in _dias_pleno(ctx, desde):
        if desde and fecha < desde:
            continue
        legislatura = CUERPOS[0].legislatura_de(fecha)
        if legislatura is None:
            continue
        escanos = CUERPOS[0].escanos_de(legislatura)
        doc = Documento(CUERPO, fecha, principal, sesion=sesion, extra={"otros_pdf": otros} if otros else {})
        try:
            t = texto(ctx, doc)
        except Exception as e:
            ctx.log(f"  ! {CUERPO}: acta {sesion} ({fecha}) no disponible ({type(e).__name__}: {e})")
            continue
        votos = _votos_de_texto(t, escanos)
        for k, v in enumerate(votos, 1):
            yield _votacion(fecha, sesion, legislatura, principal, k, v)
            n_total += 1
            if ctx.limite and n_total >= ctx.limite:
                return
