"""Parlament de les Illes Balears: votaciones del Pleno sacadas con reglas del Diari de Sessions (PDF).

Fuente: la lista anual de diarios del Pleno (https://www.parlamentib.es/Publicacions/Detalle.aspx?criteria=2&year=AAAA),
con un enlace por diario o fascículo (https://web.parlamentib.es/repositori/PUBLICACIONS/11/ple/PL-11-114.pdf,
PL-11-080-02.pdf) y la fecha de la sesión. Un diario de varios días (presupuestos, investidura, debate de política
general) sale en fascículos, cada uno con su fecha: se leen seguidos, porque el epígrafe del punto que se debate solo
aparece en el primero. No hay datos abiertos de votaciones.

Qué se saca: cada recuento que lee la Presidencia justo después de llamar a votar («Votam.», «Votamos.», «Començam a
votar.»), con una fórmula muy regular aunque cambie con los años y el idioma: «17 sí, 31 no, 7 abstencions», «25
votos a favor, 30 en contra», «Vots a favor, 24; vots en contra, 32», «Queden rebutjades per 32 vots en contra; 25 a
favor i cap abstenció». Con voto telemático o por videoconferencia vale el total que da la Presidencia al final
(«...la qual cosa ens dóna un resultat total de 26 sí, 4 no i 22 abstencions»); si solo lee las dos partes («32
votos a favor, 25 en contra y 1 voto telemático a favor») se suman (`extra["suma_remota"]`). Las categorías que la
Presidencia no lee («55 a favor.») quedan en blanco. También las aprobaciones por asentimiento que declara
(«queden aprovats per assentiment») o por unanimidad sin recuento, y las repeticiones de un empate que da por
«Mismo resultado» (con el recuento anterior, `extra["mismo_resultado"]`). El título, el expediente (el número del
registro general de entrada: «RGE 18524/25») y el autor salen del epígrafe del punto del orden del día («III. Moció
RGE núm. 18524/25, presentada pel Grup Parlamentari Socialista, relativa a...»), que se reconoce contra el SUMARI; el
subtítulo es lo que la Presidencia anuncia que se vota («Passam a votar el punt número 2»). El resultado solo va
cuando la Presidencia lo proclama («Queda rebutjada», «se proclama convalidado») y cuadra con los votos a favor y en
contra, salvo que se hable de una mayoría cualificada; si no cuadra, queda en `extra["resultado_no_cuadra"]`.

Resultats de votacions (https://www.parlamentib.es/Actividad/Votacions.aspx): la página enlaza un PDF por sesión
(contingutsweb.parlamentib.es/ASTP/<leg>/votacions/vots_PLE_AAAAMMDD_n.pdf) con el resultado oficial de cada
asunto («Punt núm. 7 aprovat per: Vots emesos 55, Vots a favor 52...»), pero solo del 9-9-2014 al 9-12-2020 y a
menudo agrupando los puntos con el mismo resultado. Para esas fechas se casan con las votaciones del diario (mismo
recuento y, si lo hay, mismo expediente, en orden): de ahí el resultado oficial, los votos emitidos (`presentes`) y
`extra["verificada"]`.

Acceso: si la web del Parlament no responde (desde algunas redes de centros de datos no acepta conexiones), se usa la
copia más reciente del Internet Archive (web.archive.org, marca «id_»); también si una descarga concreta falla.

Cobertura: Pleno de la VIII (2011), IX (2015), X (2019) y XI (2023-) legislaturas; `sesion` es el número del diario
y `numero` el orden de la votación en ese diario y día. Recogida incremental: las listas de los dos últimos años se
piden siempre y se leen los diarios con algún día desde `ctx.desde` (margen de 45 días); los PDF, que no cambian,
quedan en caché. Limitaciones: sin voto por grupo ni nominal (el voto es electrónico y no se publica); las votaciones
secretas o con varios candidatos (Mesa, senadores, investidura por llamamiento) y los recuentos a mano alzada o
interrumpidos no se leen con reglas; las erratas del diario («Vots a favor, 26; vots en contra; 33») dejan en blanco
la cifra afectada y las imposibles (más votos que escaños) todos los totales (`extra["totales_descartados"]`; si
tampoco hay resultado proclamado, la votación no se da). Los
días en que se vota pero las reglas no encuentran ningún recuento van a `documentos()` para el LLM; para saberlo hay
que leer el diario, así que solo se miran los ya descargados y los más recientes.
"""

import html
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import CACHE_DIR, UA_NAVEGADOR, Contexto, ErrorDescarga, contexto_tls
from ..modelo import Documento, Iniciativa, Votacion

CUERPO = "parl-IB"
WEB = "https://www.parlamentib.es"
LISTA = WEB + "/Publicacions/Detalle.aspx?criteria=2&year={any}"
VOTACIONS = WEB + "/Actividad/Votacions.aspx"
ARCHIVO = "http://web.archive.org/web/{marca}id_/"

# Fechas de las sesiones constitutivas (diario núm. 1 de cada legislatura).
LEGISLATURAS = {
    8: ("VIII", "2011-06-07", "2015-06-18"),
    9: ("IX", "2015-06-18", "2019-06-20"),
    10: ("X", "2019-06-20", "2023-06-20"),
    11: ("XI", "2023-06-20", None),
}
PRIMER_ANY = 2011

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("IB"), "Parlament de les Illes Balears", "Parlament (Illes Balears)", "autonomico",
           "IB", 59, LEGISLATURAS, web=WEB + "/Publicacions/Detalle.aspx?criteria=2"),
]

ACTIVO = True
NOTAS = ("Votaciones del Pleno con reglas sobre el Diari de Sessions en PDF (catalán y castellano): totales que lee la "
         "Presidencia tras cada «Votam.» (con el total final si hay voto telemático), asentimientos, resultado cuando "
         "se proclama, título, autor y expediente (RGE) del epígrafe del orden del día. Del 9-9-2014 al 9-12-2020, "
         "resultado oficial y votos emitidos de los PDF de «Resultats de votacions» cuando casan. Sin voto por grupo "
         "ni nominal. VIII a XI legislaturas (desde 2011). Los días en que las reglas no leen ningún recuento "
         "(investiduras, elecciones secretas, votos a mano alzada) van al LLM. Si la web no responde, copia del "
         "Internet Archive.")

ENLACE_RE = re.compile(r"<li class='enlacePdf'><a href='([^']+\.pdf)'[^>]*>\s*<span class='pdfIcono'></span>\s*"
                       r"<span class='titolNotes'>([^<]*)</span>\s*<span class='descNotes'>([^<]*)</span>")
PDF_RE = re.compile(r"/PL-(\d{2})-(\d{3})(?:-(\d{2}))?\.pdf$", re.I)
FECHA_RE = re.compile(r"(\d{1,2}) d(?:e |')(\w+) de (\d{4})")
MESOS = {m: i for i, m in enumerate(("gener", "febrer", "març", "abril", "maig", "juny", "juliol", "agost", "setembre",
                                     "octubre", "novembre", "desembre"), 1)}

_ORIGEN = []


# ---------------------------------------------------------------- acceso

def _origen(ctx):
    """¿Responde la web del Parlament? Se comprueba una vez por ejecución."""
    if not _ORIGEN:
        try:
            urllib.request.urlopen(urllib.request.Request(WEB, headers={"User-Agent": UA_NAVEGADOR}), timeout=20,
                                   context=contexto_tls())
            _ORIGEN.append(True)
        except urllib.error.HTTPError:
            _ORIGEN.append(True)  # responde, aunque sea con error
        except Exception as e:  # noqa: BLE001 (red caída, conexión rechazada o agotada)
            _ORIGEN.append(False)
            ctx.log(f"  ! {CUERPO}: {WEB} no responde ({type(e).__name__}); se usa la copia del Internet Archive")
            ctx.aviso(CUERPO, "copia", f"{WEB} no responde ({type(e).__name__})")
    return _ORIGEN[0]


def _archivo(ctx, url, cache=None, caduca_dias=None):
    if not (cache and (CACHE_DIR / f"{cache}.gz").exists()):
        time.sleep(2)  # el Internet Archive corta las conexiones si se le pide deprisa
    return ctx.fetch(ARCHIVO.format(marca=date.today().strftime("%Y%m%d")) + url, cache=cache, caduca_dias=caduca_dias)


def _bajar(ctx, url, cache=None, caduca_dias=None):
    """La web del Parlament; si no responde o falla, la copia más reciente del Internet Archive."""
    if _origen(ctx):
        try:
            return ctx.fetch(url, cache=cache, caduca_dias=caduca_dias)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            ctx.log(f"  ! {CUERPO}: {url}: HTTP {e.code}; se prueba la copia del Internet Archive")
        except ErrorDescarga as e:
            ctx.log(f"  ! {CUERPO}: {e}; se prueba la copia del Internet Archive")
    return _archivo(ctx, url, cache=cache, caduca_dias=caduca_dias)


# ---------------------------------------------------------------- listas de diarios

def _fecha(texto):
    m = FECHA_RE.search(html.unescape(texto).lower())
    if not m or m.group(2) not in MESOS:
        return None
    return f"{m.group(3)}-{MESOS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def _lista(ctx, any_):
    """[(legislatura, número, fascículo, fecha, url, descripción)] de la lista anual de diarios del Pleno."""
    viejo = any_ < date.today().year - 1
    cache = f"{CUERPO}/llistes/{any_}.html" if viejo else None
    try:
        h = _bajar(ctx, LISTA.format(any=any_), cache=cache, caduca_dias=90).decode("utf-8", "replace")
    except (urllib.error.HTTPError, ErrorDescarga) as e:
        ctx.log(f"  ! {CUERPO}: lista de {any_} no disponible ({e})")
        return []
    out = []
    for url, fecha, desc in ENLACE_RE.findall(h):
        m, f = PDF_RE.search(url), _fecha(fecha)
        if m and f:
            out.append((int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), f, url,
                        re.sub(r"\s+", " ", html.unescape(desc)).strip()))
    return out


def _diarios(ctx, desde=None):
    """Diarios del Pleno, del más reciente al más antiguo: [(legislatura, número, [(fascículo, fecha, url, desc)])].

    Con `desde`, solo los que tienen algún fascículo de esa fecha en adelante (pero con todos sus fascículos).
    """
    for any_ in range(date.today().year, PRIMER_ANY - 1, -1):
        if desde and str(any_) < desde[:4]:
            return
        diarios = {}
        for leg, num, fasc, fecha, url, desc in _lista(ctx, any_):
            if leg in LEGISLATURAS:
                diarios.setdefault((leg, num), {})[fasc] = (fasc, fecha, url, desc)
        for (leg, num), partes in sorted(diarios.items(), key=lambda kv: (max(p[1] for p in kv[1].values()), kv[0]),
                                         reverse=True):
            partes = sorted(partes.values())
            if desde and max(p[1] for p in partes) < desde:
                return
            yield leg, num, partes


def _nombre(url):
    m = PDF_RE.search(url)
    return f"PL-{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")


def _texto_pdf(ctx, url):
    """Texto del PDF de un diario o fascículo (en caché: los diarios publicados no cambian)."""
    return Contexto.pdf_texto(_bajar(ctx, url, cache=f"{CUERPO}/ple/{_nombre(url)}.pdf"), raw=True)


# ---------------------------------------------------------------- texto del diario

CABECERA_RE = re.compile(r"DIARI DE SESSIONS DEL PLE\s*/\s*N[úu]m", re.I)
ACOTACION_RE = re.compile(r"^\([^()]*\)$")  # «(Alguns aplaudiments)», «(Remor de veus)»
ORADOR_RE = re.compile(r"^(?:EL|LA|ELS|LES)\s+(?:SRA?|SRES|SRS)\.?\s+\S")
PRESIDENCIA_RE = re.compile(r"^(?:EL|LA)\s+SRA?\.?\s+(?:VICE)?PRESIDENTA?(?:\s+(?:PRIMERA?|SEGONA?|TERCERA?))?$")
EPIGRAFE_RE = re.compile(r"^(?:(?P<rom>[IVX]{1,5})(?:\.\s?\d{1,2})?(?:[.)]|(?<=[IVX]{2}),)|(?P<unic>Punt\s+[úu]nic)\s*[.:]-?|"
                         r"(?P<arab>\d{1,2})\))\s*(?P<resto>\S.*)$")
# un «1) ...» solo es epígrafe si empieza como una iniciativa (bajo «Punt únic.- PROPOSICIONS NO DE LLEI:»)
INICIATIVA_RE = re.compile(r"(?:Proposici|Moci|Projecte|Proposta|Debat|Dictamen|Presa|Decret|Compareixen|Elecci|"
                           r"Designaci|Votaci|Informe|Esmena)")
ABREVIATURA_RE = re.compile(r"(?:\b(?:Sr|Sra|Srs|Sres|núm|Núm|Hble|Excm|Excma|Molt|art|pàg|Dª|Mt|etc)|\s[A-ZÀ-Ú]|"
                            r"^[A-ZÀ-Ú])\.$")
PUNTOS_RE = re.compile(r"(?:\s*\.\s*){3,}\s*(?:\d{1,5}|fascicle\s+\d+)?\s*(?=\s|$)")
PAGINA_RE = re.compile(r"(?:(?:\s*\.\s*){3,}\s*(?:\d{1,5}|fascicle\s+\d+)?|(?<=[.)])\s*(?:\d{1,5}|fascicle\s+\d+))\s*$")
ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]


def _plano(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _lineas(texto):
    """Líneas útiles del diario: sin cabeceras de página, vacías ni el pie de imprenta."""
    out = []
    for ln in texto.replace("\f", "\n").splitlines():
        ln = ln.strip()
        if not ln or CABECERA_RE.search(ln):
            continue
        if ln == "Redacció i Administració":
            break
        out.append(ln)
    return out


def _orador(lineas, k):
    """(nombre, líneas que ocupa) si en la línea k empieza el nombre de un orador («EL SR. PRESIDENT:»)."""
    if not ORADOR_RE.match(lineas[k]):
        return None
    txt, n = lineas[k], 1
    while ":" not in txt and n < 3 and k + n < len(lineas):
        txt += " " + lineas[k + n]
        n += 1
    if not txt.endswith(":"):
        return None
    nombre = txt[:-1].strip()
    if re.search(r"[a-zà-ÿ]", re.sub(r"\([^)]*\)?", "", nombre)):
        return None  # minúsculas fuera del paréntesis del cargo: es texto
    return nombre, n


def _presidencia(orador):
    return bool(orador) and bool(PRESIDENCIA_RE.match(re.sub(r"\s*\(.*$", "", orador)))


def _acaba(t):
    return t.endswith(".") and not ABREVIATURA_RE.search(t)


def _une(partes):
    t = ""
    for p in partes:
        if t.endswith("-") and p[:1].islower():
            t = t[:-1] + p
        else:
            t = f"{t} {p}" if t else p
    return re.sub(r"\s+", " ", t).strip()


def _sumario(lineas):
    """(epígrafes del SUMARI, números romanos que usa) de un diario o fascículo."""
    try:
        i = lineas.index("SUMARI")
    except ValueError:
        return [], set()
    fin = next((k for k in range(i + 1, len(lineas)) if _orador(lineas, k)), len(lineas))
    # cada epígrafe acaba con la página («. . . . 950», «... Balears. 4726», «fascicle 1»); lo que queda detrás sin
    # página ya es el texto de la sesión
    items, actual = [], []
    for ln in lineas[i + 1:fin]:
        m = PAGINA_RE.search(ln)
        actual.append(ln[:m.start()] if m else ln)
        if m:
            item = PUNTOS_RE.sub(" ", _une(actual)).strip(" .")
            if len(item) > 8:
                items.append(item)
            actual = []
    romanos = {m.group("rom") for m in (EPIGRAFE_RE.match(x) for x in lineas[i + 1:fin]) if m and m.group("rom")}
    return items, romanos


def _epigrafe(lineas, k, validos):
    """(epígrafe, línea siguiente) si en la línea k empieza un epígrafe del orden del día; si no, None."""
    m = EPIGRAFE_RE.match(lineas[k])
    if not m or not m.group("resto")[:1].isupper() or not (
            m.group("unic") or m.group("rom") in validos or m.group("arab") and INICIATIVA_RE.match(m.group("resto"))):
        return None
    partes, j = [lineas[k]], k + 1
    while not _acaba(partes[-1]) and j < len(lineas) and j - k < 10 and not _orador(lineas, j):
        partes.append(lineas[j])
        j += 1
    return (_une(partes), j) if _acaba(partes[-1]) else None


def _segmentos(lineas, romanos, epigrafe=None):
    """([(orador, epígrafe, texto)], último epígrafe) del texto de la sesión: un trozo por intervención y epígrafe.

    Un epígrafe es una línea que empieza con el número romano de un punto del SUMARI («III.», «IV.2)») o «Punt
    únic.», y sigue hasta el punto final; el epígrafe vigente pasa al fascículo siguiente.
    """
    validos = romanos or set(ROMANOS)
    try:
        inicio = next(k for k in range(len(lineas)) if _orador(lineas, k))
    except StopIteration:
        return [], epigrafe
    # el primer epígrafe puede ir entre el SUMARI y el primer orador
    fin_sumario = max((k for k in range(inicio) if PUNTOS_RE.search(lineas[k])), default=-1)
    for k in range(max(fin_sumario + 1, inicio - 12), inicio):
        e = _epigrafe(lineas, k, validos)
        if e:
            epigrafe = e[0]
            break
    segs, orador, buf = [], None, []

    def cierra():
        if buf:
            segs.append((orador, epigrafe, " ".join(buf)))
            buf.clear()

    k = inicio
    while k < len(lineas):
        o = _orador(lineas, k)
        if o:
            cierra()
            orador = o[0]
            k += o[1]
            continue
        e = _epigrafe(lineas, k, validos)
        if e:
            cierra()
            epigrafe, k = e
            continue
        if not ACOTACION_RE.match(lineas[k]):
            buf.append(lineas[k])
        k += 1
    cierra()
    return segs, epigrafe


# ---------------------------------------------------------------- recuentos

LLAMADA_RE = re.compile(r"(?<![\wÀ-ÿ])(?:[Vv]ot(?:am|em|amos)|[Cc]omen[çc]am\s+(?:a\s+votar|la\s+votaci[óo])|"
                        r"(?:[Cc]omenzamos|[Ii]niciamos|[Pp]rocedemos\s+a)\s+(?:la\s+)?votaci[óo]n)\s*\.")
NUM = r"(\d{1,2}|cap|un|una|ningun[ao]?|ningún|cero|zero)"
_VOTS = r"(?:vots?\s+|votos?\s+)?(?:telem[àá]tics?\s+|presencials?\s+)?"
_ANTES = r"(?<![\w.-])(?<!\d,)"  # no a media cifra («4.1,4.2») ni pegado a una palabra


def _cifra_delante(sentido):
    """«17 sí», «54 vots, sí», «23, sí»; en la forma con coma la palabra no puede llevar su propia cifra detrás
    («Vots a favor 20, vots en contra 34, abstencions 5»: el 20 y el 34 no son de la palabra que sigue)."""
    fin = "" if sentido.endswith(r"\b") else r"(?![\wà-ÿ])"
    # la cifra que sigue es de esta palabra si no lleva la suya («21, sí, 31 no» sí vale)
    suya = (r"(?!\s*[,:]?\s*(?:\d{1,2}|cap)\b(?!\s*,?\s*(?:vots?\s+|votos?\s+)?(?:s[íi]\b|no\b|a\s+favor|en\s+contra|"
            r"abstenci|afirmatiu|negatiu)))")
    return (_ANTES + NUM + r"(?:\s+vots?\s*,?\s*|\s*)" + _VOTS + sentido + fin + "|" +
            _ANTES + NUM + r"\s*,\s*(?!vots?\b|votos?\b)" + _VOTS + sentido + fin + suya)


FAVOR_RE = re.compile(_cifra_delante(r"(?:a\s*favors?|favorables?|afirmatius?|positius?|s[íi])") +
                      r"|(?:vots?|votos?)\s+(?:a\s*favor|favorables?|afirmatius?)(?:\s+de[l]?\s+[^,;:\d]{0,40}?)?\s*[,:]?\s+"
                      + NUM + r"(?![\d/])|(?<![\w-])s[íi]\s*[,:]\s*(\d{1,2}|cap)(?![\d/])", re.I)
CONTRA_RE = re.compile(_cifra_delante(r"(?:en\s*contra|contraris?|negatius?|no)") +
                       r"|(?:vots?\s+|votos?\s+)?(?:en\s*contra|contraris?|negatius?)\s*[,:]?\s+" + NUM + r"(?![\d/])"
                       r"|(?<![\w-])no\s*[,:]\s*(\d{1,2}|cap)(?![\d/])", re.I)
ABST_RE = re.compile(_cifra_delante(r"abstenci\w*\b") + r"|abstenci(?:ons|ones|ó|ón)\s*[,:]?\s+" + NUM + r"(?![\d/])",
                     re.I)
BLANC_RE = re.compile(r"(?<![\w-])" + NUM + r"\s+(?:vots?\s+|votos?\s+)?en\s+blanc", re.I)
NULS_RE = re.compile(r"(?<![\w-])" + NUM + r"\s+(?:vots?\s+|votos?\s+)?nuls?\b", re.I)
EMPATE_A_RE = re.compile(r"\b(?:empat(?:e)?|embate)\s+a\s+(\d{1,2})\b", re.I)
# «Queda aprovat per 55 vots, és a dir, per unanimitat»
UNANIME_N_RE = re.compile(r"\bper\s+(\d{1,2})\s+vots,?\s+(?:és\s+a\s+dir,?\s+)?per\s+unanimitat", re.I)
_GRUPO = r"(?=\d{1,2}\s*(?:vots?\s+|votos?\s+)?(?:s[íi]\b|a\s*favor|afirmatius?|favorables))"
# Resultado final cuando hay voto presencial y a distancia: se lee lo que viene después.
TOTAL_RE = re.compile(r"resulta(?:t|do)s?\s*(?:total|global|final|definitiu)(?:\s+(?:és|es|són|son|de))?|"
                      r"resulta(?:t|do)\s*de\s*la\s*votaci[óo]n?(?!\s*presencial)(?:\s+(?:és|es|són|son))?|"
                      r"resulta(?:t|do)\s+de\s+(?=\d)|\bresultat\s*:\s*" + _GRUPO + "|"
                      r",\s*s[óo]n\s+(?=\d{1,2}\s+vots?\s+afirmatius)|"
                      r"\b(?:per\s+tant|por\s+tanto|en\s+total)\s*[,:]?\s+(?:s[óo]n\s+)?" + _GRUPO + "|"
                      r"\bs[óo]n\s+(?:de\s+)?" + _GRUPO + "|"
                      r"votaci[óo]n?\s+(?:final|definitiva)\s+(?:queda\s+amb\s+|és\s+|es\s+|de\s+)?|"
                      r"(?:que\s+)?(?:ens\s+|nos\s+)?d[óo]n(?:a|an|en)\s+(?:una\s+votaci[óo]\s+de\s+)?" + _GRUPO + "|"
                      r"\bfa\s+un\s+total\s+de\s+|perd[óo]n?\s*-?\s*,?\s*" + _GRUPO + "|"
                      r"\ben\s+realitat\s+(?:és|són|es)\s*:?\s*|"  # nota del diario que corrige la lectura
                      r"(?:videoconfer\w*|telem[àá]tic\w*)[^;:.\d]{0,30}[;,.]\s*" + _GRUPO + "|"
                      # «1 vot negatiu per videoconferència: 24 sí, 30 no», «Per videoconferència 1 vot negatiu: 23 sí»
                      # (los dos puntos presentan el total porque el voto a distancia ya se ha dicho)
                      r"(?:un|\d{1,2})\s+vots?\s+(?:\w+\s+){0,2}?(?:per\s+)?(?:videoconfer\w*|telem[àá]tic\w*)(?:\s+\w+)?\s*:\s*"
                      + _GRUPO + "|"
                      r"(?:videoconfer\w*|telem[àá]tic\w*)\s+(?:un|\d{1,2})\s+vots?\s+\w+\s*:\s*" + _GRUPO, re.I)
REMOTO_RE = re.compile(r"telem[àá]tic|videoconfer|vid?e?conferència", re.I)
# «23 vots a favor, perquè hi ha un vot telemàtic»: la cifra ya lo incluye
REMOTO_INCLUIDO_RE = re.compile(r",?\s*perquè\s+hi\s+ha\s+(?:(?:un|una|\d{1,2})\s+)?vots?\s+telem[àá]tics?|"
                                r",?\s*(?:hi\s+ha\s+|hay\s+|\(\s*)?\d{1,2}\s+presencials?\s+(?:i|y)\s+(?:un|una|\d{1,2})\s+"
                                r"(?:vots?\s+)?telem[àá]tics?\s*\)?", re.I)
CONTINUA_RE = re.compile(r"\s*(?:\S+\s+){0,5}?(?:telem[àá]tic|videoconfer|vid?e?conferència|la qual cosa|lo que (?:nos )?da|"
                         r"d[óo]na|resulta(?:t|do)|votaci[óo]n?\s+final|en total|"
                         r"(?:vots?\s+(?:en\s+contra|a\s+favor)|abstencions?)\s*[,:]?\s*\d|"
                         r"(?:no|s[íi]|abstencions?|en\s+contra)\s*[,:]\s*(?:\d|cap\b))", re.I)
TRAS_REMOTO_RE = re.compile(r"\s*(?:(?:per\s+tant|por\s+tanto|en\s+total|total)\s*[,:]?\s+(?:s[óo]n\s+)?)?" + _GRUPO,
                            re.I)
# «25 vots a favor, més un vot telemàtic, que fan 26 sí»: vale la cifra final
_SENTIDO = r"(?:a\s+favor|en\s+contra|s[íi]|no|afirmatius|negatius|abstencions?)"
QUE_FAN_RE = re.compile(r"\b\d{1,2}\s+(?:vots?\s+)?(?:presencials\s+)?(" + _SENTIDO + r")?\s*,?\s*m[ée]s\s+(?:un|una|\d{1,2})"
                        r"\s+(?:vots?\s+)?(?:telem[àá]tics?(?:\s+" + _SENTIDO + r")?|de\s+[^,;]{1,40}?)\s*,?\s+"
                        r"(?:(?:que\s+(?:fan|fa|dóna|dona)|s[óo]n)\s+"
                        r"(\d{1,2})(\s+(?:vots?\s+)?" + _SENTIDO + r")?|(\d{1,2})(\s+(?:vots?\s+)?" + _SENTIDO + r"))", re.I)
# Votos a distancia que se leen aparte y sin total («..., 2 abstenciones y 1 voto telemático en contra»)
PARTE_REMOTA_RE = re.compile(r"(?:,|;|\by\b|\bi\b|\bm[ée]s\b|\bmás\b)\s*(?:també\s+|también\s+|a\s+m[ée]s,?\s+)?"
                             r"(?:hi\s+ha\s+|hay\s+)?(?:un|una|\d{1,2})\s+"
                             r"(?:(?:vots?|votos?)\s+(?:telem[àá]tics?|telem[áa]ticos?|per\s+videoconfer)|"
                             r"abstenci\w*\s+telem)", re.I)
# ... o como una segunda lectura («Vots telemàtics: 2 a favor, 1 en contra i cap abstenció»)
PARTE_REMOTA2_RE = re.compile(r"[.;]\s*(?:i\s+|y\s+)?(?:els\s+|los\s+)?(?:vots?|votos?)\s+(?:telem[àá]tics?|telem[áa]ticos?|"
                              r"per\s+videoconfer\w*|por\s+videoconferencia)\s*(?:s[óo]n\s*|:)", re.I)
CUENTA_REMOTA_RE = re.compile(r"(un|una|\d{1,2})\s+(?:vots?|votos?)\s+(?:telem[àá]tics?|telem[áa]ticos?)?\s*"
                              r"(?:per\s+videoconfer\w*\s+)?(?:,?\s*(?:de|del)\s+(?:la\s+|el\s+)?(?:Sra?\.|senyora?|señora?)"
                              r"[^,;.]{1,50}?,?\s+)?(?:de\s+(?:votaci[óo]n?\s+)?)?(a\s+favor|afirmatius?|positius?|en\s+contra|"
                              r"negatius?|abstenci\w*)|(un|una|\d{1,2})\s+(abstenci\w*)\s+(?:telem|per\s+videoconfer)", re.I)
MISMO_RE = re.compile(r"^(?:y\s+|i\s+)?(?:el\s+)?(?:mismo|mateix)\s+resulta|^(?:se\s+repite|es\s+repeteix)\s+el\s+resulta",
                      re.I)
UNANIMIDAD_RE = re.compile(r"^[^.?!\d]{0,40}?\b(?:unanimitat|unanimidad)\b(?![^.?!]{0,40}\d)", re.I)


def _entero(s):
    s = _plano(s)
    if s.isdigit():
        return int(s)
    return {"un": 1, "una": 1, "cap": 0, "ningun": 0, "ninguno": 0, "ninguna": 0, "cero": 0, "zero": 0}.get(s)


def _valor(rx, t):
    m = rx.search(t)
    if not m:
        return None, None
    return _entero(next(g for g in m.groups() if g)), m.start()


def _que_fan(m):
    total = m.group(2) or m.group(4)
    sentido = m.group(3) or m.group(5) or (" " + m.group(1) if m.group(1) else "")
    return f"{total}{sentido}"


def _simple(t):
    """Recuento de una lectura sin votos a distancia."""
    t = re.sub(r"\b(\d{1,2})\s+(?:un|una)\s+(?=s[íi]\b)", r"\1 ", t)  # «31 un sí»
    d = {}
    for k, rx in (("a_favor", FAVOR_RE), ("en_contra", CONTRA_RE), ("abstenciones", ABST_RE), ("en_blanco", BLANC_RE),
                  ("nulos", NULS_RE)):
        d[k] = _valor(rx, t)[0]
    m = FAVOR_RE.search(t)
    if m and re.search(r"s[íi]$", m.group(0), re.I) and d["en_contra"] is None and d["abstenciones"] is None:
        return None  # «sería el 13, sí»: un «sí» suelto no es una lectura de votos
    m = EMPATE_A_RE.search(t)
    if m and d["a_favor"] is None:
        d["a_favor"] = d["en_contra"] = int(m.group(1))
    m = UNANIME_N_RE.search(t)
    if m and d["a_favor"] is None:
        d.update(a_favor=int(m.group(1)), en_contra=0, abstenciones=0)
    if d["a_favor"] is None:
        return None
    if d["en_contra"] is None and re.search(r"\bcap\s+(?:vot\s+)?(?:en\s+contra|no)\b|ning[uú]n\s+voto\s+en\s+contra", t, re.I):
        d["en_contra"] = 0
    return d


def _cuenta(t):
    """{a_favor, en_contra, abstenciones, en_blanco, nulos} de una lectura de resultados («17 sí, 31 no, 7 abstencions»).

    Con voto telemático o por videoconferencia vale el total que da la Presidencia al final («...la qual cosa ens dóna
    un resultat total de 26 sí, 4 no i 22 abstencions»); si no lo da pero lee las dos partes, se suman. None si no se
    leen votos a favor.
    """
    t = REMOTO_INCLUIDO_RE.sub("", QUE_FAN_RE.sub(_que_fan, t))
    # «els vots per videoconferència són 5 vots a favor...» presenta la parte a distancia, no el total
    totales = [m for m in TOTAL_RE.finditer(t)
               if not (re.match(r"s[óo]n", m.group(0), re.I) and REMOTO_RE.search(t[max(0, m.start() - 35):m.start()]))]
    if totales and FAVOR_RE.search(t, totales[-1].end()) and not REMOTO_RE.search(t, totales[-1].end()):
        return _simple(t[totales[-1].end():])
    if not REMOTO_RE.search(t):
        return _simple(t)
    # sin marca de total: el último recuento completo que venga, en otra frase, después de los votos a distancia
    ultimo = list(REMOTO_RE.finditer(t))[-1].end()
    for m in reversed(list(FAVOR_RE.finditer(t, ultimo))):
        if (CONTRA_RE.search(t[m.end():m.end() + 40]) or ABST_RE.search(t[m.end():m.end() + 40])) \
                and re.search(r"[.;?]", t[ultimo:m.start()]):
            return _simple(t[m.start():])
    return _suma_remota(t)


def _suma_remota(t):
    """Presencial más a distancia cuando la Presidencia lee las dos partes y no da el total
    («32 votos a favor, 25 en contra y 1 voto telemático a favor»). None si la parte a distancia no se entiende."""
    m2 = PARTE_REMOTA2_RE.search(t)
    if m2 and not REMOTO_RE.search(t[:m2.start()]):
        d, r = _simple(t[:m2.start()]), _simple(t[m2.end():])
        if d is None or r is None or REMOTO_RE.search(t[m2.end():]):
            return None
        for k in ("a_favor", "en_contra", "abstenciones"):
            d[k] = None if d[k] is None and r[k] is None else (d[k] or 0) + (r[k] or 0)
        d["suma_remota"] = True
        return d
    m = PARTE_REMOTA_RE.search(t)
    if not m or REMOTO_RE.search(t[:m.start()]):
        return None
    # la parte a distancia llega hasta el «;» o el punto; lo que sigue vuelve a ser el recuento general
    punto_y_coma = t.find(";", m.end())
    fin = min(punto_y_coma if punto_y_coma >= 0 else len(t), _fin_frase(t, m.end()))
    d = _simple(f"{t[:m.start()]} {t[fin:]}")
    remoto = t[m.start():fin]
    cuentas = CUENTA_REMOTA_RE.findall(remoto)
    if d is None or not cuentas or len(re.findall(r"\b(?:\d{1,2}|un|una)\s+(?:vots?|votos?|abstenci)", remoto, re.I)) \
            != len(cuentas):
        return None
    for n1, s1, n2, s2 in cuentas:
        n, s = _entero(n1 or n2), _plano(s1 or s2)
        k = "a_favor" if s.startswith(("a favor", "afirmat", "positi")) else \
            "en_contra" if s.startswith(("en contra", "negati")) else "abstenciones"
        d[k] = (d[k] or 0) + n
    d["suma_remota"] = True
    return d


FIN_FRASE_RE = re.compile(r"(?:\.{1,3}|…)(?=\s+[A-ZÀ-ÚÇ¿¡(«\"\d]|\s*$)|[?!](?=\s)")
APROBADA_RE = re.compile(
    r"\b(?:queda|queden|quedan|quedaria|quedarien|resulta|resulten|resultan)\s+(?:per\s+tant,?\s+|por\s+tanto,?\s+|així\s+)?"
    r"(?:aprovad|aprovat|aprobad|validad|validat|convalidad|convalidat|ratificad|ratificat|acceptad|"
    r"pres[ao]s?\s+en\s+consideraci)|"
    r"\bse\s+proclama\s+(?:convalidad|aprobad|validad)|\bes\s+pren(?:en)?\s+en\s+consideraci|"
    r"\bse\s+toma(?:n)?\s+en\s+consideraci|\bun\s+cop\s+(?:validat|convalidat|aprovad)|"
    r"\buna\s+vez\s+(?:convalidad|aprobad|validad)|\bser[àá]\s+tramitad[oa]\s+com[oa]?\s+(?:a\s+)?pro[jy]ec|"
    r"\bse\s+aprueba(?:n)?\s+por\b|\bs['’]aprova(?:en|n)?\s+per\b|"
    r"(?:^|[.;]\s*)(?:per\s+tant,?\s+|por\s+tanto,?\s+)?(?:aprovad[ao]s?|aprovats?|aprobad[ao]s?|validat|convalidad[oa]|"
    r"convalidat)\b", re.I)
RECHAZADA_RE = re.compile(
    r"\b(?:queda|queden|quedan|quedaria|quedarien|resulta|resulten|resultan)\s+(?:per\s+tant,?\s+|por\s+tanto,?\s+)?"
    r"(?:rebutjad|rebutjat|rechazad|derogad|derogat|desestimad|decaigu)|\bno\s+es\s+pren(?:en)?\s+en\s+consideraci|"
    r"\bno\s+se\s+toma(?:n)?\s+en\s+consideraci|\bno\s+es\s+tramit|\bno\s+se\s+tramit|\bse\s+rechaza(?:n)?\s+por\b|"
    r"\bno\s+ser[àá]\s+tramitad|\bno\s+queda(?:n)?\s+(?:aprovad|aprovat|aprobad)|\bno\s+sale\s+adelante|"
    r"\bes\s+rebutja(?:en|n)?\s+per\b|"
    r"(?:^|[.;]\s*)(?:per\s+tant,?\s+|por\s+tanto,?\s+)?(?:rebutjad[ao]s?|rebutjats?|rechazad[ao]s?|derogat)\b", re.I)
MAYORIA_RE = re.compile(r"majoria\s+(absoluta|qualificada|de\s+dos\s+terços|de\s+tres\s+cinquenes)|"
                        r"mayoría\s+(absoluta|cualificada|de\s+dos\s+tercios|de\s+tres\s+quintos)|"
                        r"(dos\s+terços|tres\s+cinquenes|dos\s+tercios|tres\s+quintos)", re.I)
EMPATE_RE = re.compile(r"\bempat\b|\bempate\b", re.I)
ASENT_RE = re.compile(r"(?:aprovad[ao]s?|aprovats?|aprobad[ao]s?|acceptad[ao]s?|aprova(?:en|n)?|aprueba(?:n)?)\s*,?\s*"
                      r"(?:per|por)\s+(?:assentiment|asentimiento)", re.I)
ASENT_DECLARA_RE = re.compile(
    r"^(?:(?:bé|bien|molt bé|muy bien|d['’]acord|de acuerdo|idò|doncs|pues|per\s+tant|por\s+tanto|així|gràcies|gracias),?\s+)*"
    r"(?:[^.?!]{0,80}?\s)?(?:queda|queden|quedan|s['’]aprova|s['’]aproven|se\s+aprueba|se\s+aprueban|"
    r"(?:el|la|els|les|lo|los)\s+donam|s['’]entén|s['’]entenen|es\s+dona|es\s+donen|són|son)\s", re.I)


def _fin_frase(t, desde=0):
    m = FIN_FRASE_RE.search(t, desde)
    while m and ABREVIATURA_RE.search(t[:m.end()]):
        m = FIN_FRASE_RE.search(t, m.end())
    return m.end() if m else len(t)


def _frases(t, maximo=4):
    """Las primeras frases de `t`, con su posición: [(inicio, fin)]."""
    out, i = [], 0
    while i < len(t) and len(out) < maximo:
        f = _fin_frase(t, i)
        if t[i:f].strip():
            out.append((i, f))
        i = f
    return out


def _resultado(texto):
    """«aprobada»/«rechazada» si la Presidencia lo proclama en `texto`; None si no lo dice."""
    if RECHAZADA_RE.search(texto):
        return "rechazada"
    if APROBADA_RE.search(texto):
        return "aprobada"
    return None


def _lectura(t, previo=None):
    """(recuento, inicio, fin) de la lectura de resultados en lo dicho tras «Votam.»; None si no la hay.

    La lectura puede ir tras alguna frase corta sin cifras («Muy bien.», «¿Funciona correctamente?»); se toma la
    primera frase cuyos votos a favor o en contra aparezcan al principio (o «el mismo resultado» de una repetición).
    """
    saltado = 0
    for i, f in _frases(t, maximo=14):
        frase = t[i:f]
        s = frase.lstrip(" .,;:")
        if MISMO_RE.match(s) and previo:
            d = {k: previo.get(k) for k in ("a_favor", "en_contra", "abstenciones", "en_blanco", "nulos")}
            return {**d, "mismo": True}, i, f
        pf, pc = _valor(FAVOR_RE, s)[1], _valor(CONTRA_RE, s)[1]
        pe = EMPATE_A_RE.search(s)
        # hasta dónde puede empezar la cifra: al principio, tras dos puntos («...el resultat següent: 49 sí») o en una
        # proclamación («Queda aprovada l'esmena del Grup ... al punt 1, per 39 a favor»)
        tope = 160 if re.match(r"(?:per\s+tant,?\s+)?(?:queda|queden|quedan|quedaria|no\s+es\s+pren|es\s+pren|resulta)\b",
                                s, re.I) else 70

        def cerca(p):
            return p is not None and (p <= tope or s[:p].rstrip().endswith(":"))

        if cerca(pf) or cerca(pc) or (pe and pe.start() <= 40):
            fin = f
            for _ in range(4):  # voto a distancia: el total va en las frases siguientes
                sig = t[fin:_fin_frase(t, fin)]
                cifras = FAVOR_RE.search(sig) or CONTRA_RE.search(sig) or ABST_RE.search(sig)
                if not ((CONTINUA_RE.match(sig[:90]) and (cifras or REMOTO_RE.search(sig)))
                        or (REMOTO_RE.search(t[i:fin]) and TRAS_REMOTO_RE.match(sig[:60]))):
                    break
                fin += len(sig)
            if fin - i > 450:
                return None
            d = _cuenta(t[i:fin])
            if d:
                return d, i, fin
        elif UNANIMIDAD_RE.match(s):  # «Vots a favor? Unanimitat.»: aprobada sin recuento
            return {"a_favor": None, "en_contra": None, "abstenciones": None, "en_blanco": None, "nulos": None,
                    "unanimidad": True}, i, f
        # frase que no es la lectura: se salta si es corta y no habla de votos (o se interrumpe: «Vots a favor...»)
        saltado += len(s)
        interrumpida = s.endswith(("?", "...", "…", "!"))
        if len(s) > 110 or saltado > 350 or LLAMADA_RE.search(s) or not interrumpida and (
                SENAL_RE.search(s) or re.search(r"\b\d{1,2}\s+(?:vots?|votos?)\b", s, re.I)):
            return None
    return None


def _bloques(segs):
    """Intervenciones de la Presidencia [(epígrafe, texto)], juntando una que acaba en «Votam.» sin lectura con la
    siguiente de la Presidencia si entre medias solo hay respuestas breves (el voto de un diputado a distancia)."""
    out, i = [], 0
    while i < len(segs):
        orador, epigrafe, texto = segs[i]
        i += 1
        if not _presidencia(orador):
            continue
        while True:
            ll = list(LLAMADA_RE.finditer(texto))
            if not ll or _lectura(texto[ll[-1].end():]) is not None or len(texto) - ll[-1].end() > 200:
                break
            j = i
            while j < len(segs) and j - i < 3 and not _presidencia(segs[j][0]) and len(segs[j][2]) < 150:
                j += 1
            if j < len(segs) and j > i and _presidencia(segs[j][0]) and segs[j][1] == epigrafe:
                texto = f"{texto} {segs[j][2]}"
                i = j + 1
            else:
                break
        out.append((epigrafe, texto))
    return out


def _votos(segs):
    """[dict] de las votaciones de una serie de intervenciones, en orden."""
    votos = []
    for epigrafe, texto in _bloques(segs):
        eventos, usado = [], []
        llamadas = list(LLAMADA_RE.finditer(texto))
        inicio, previo = 0, None
        for n, m in enumerate(llamadas):
            siguiente = llamadas[n + 1].start() if n + 1 < len(llamadas) else len(texto)
            tramo = texto[m.end():siguiente]
            lec = _lectura(tramo, previo)
            if lec is None:
                continue
            d, a, b = lec
            anuncio = texto[inicio:m.start()].strip()
            resto = tramo[b:]
            corte = _fin_frase(resto)
            if len(resto[:corte].strip()) < 60:
                corte = _fin_frase(resto, corte)
            despues = resto[:min(corte, 350)].strip()
            frase = tramo[a:b].strip()
            unanime = bool(d.pop("unanimidad", False))
            d.update(anuncio=anuncio, lectura=frase, despues=despues, epigrafe=epigrafe, asentimiento=unanime,
                     resultado="aprobada" if unanime else _resultado(frase) or _resultado(despues),
                     mayoria=MAYORIA_RE.search(f"{anuncio[-300:]} {frase} {despues}"),
                     empate=bool(EMPATE_RE.search(despues)))
            eventos.append((m.start(), d))
            usado.append((m.end() + a, m.end() + b))  # la lectura: un asentimiento dentro de ella no es otra votación
            inicio, previo = m.end() + b, d
        # aprobaciones por asentimiento que declara la Presidencia fuera de un recuento
        for a, b in _frases(texto, maximo=10 ** 6):
            s = texto[a:b].strip()
            if not ASENT_RE.search(s) or s.endswith("?") or re.search(r"vot(?:s|os)\s+a\s+favor|\d+\s+a\s+favor", s, re.I) \
                    or any(x <= a < y for x, y in usado) or not ASENT_DECLARA_RE.match(s) \
                    or re.match(r"^(?:si|se)\s", _plano(s)) and not re.match(r"^se\s+aprueba", _plano(s)):
                continue
            previo_txt = texto[max(0, a - 300):a]
            eventos.append((a, {"a_favor": None, "en_contra": None, "abstenciones": None, "en_blanco": None,
                                "nulos": None, "anuncio": previo_txt[previo_txt.rfind(". ") + 1:].strip() or s,
                                "lectura": s, "despues": "", "epigrafe": epigrafe, "asentimiento": True,
                                "resultado": "aprobada", "mayoria": None, "empate": False}))
        votos.extend(d for _p, d in sorted(eventos, key=lambda e: e[0]))
    return votos


# ---------------------------------------------------------------- epígrafes: título, expediente, tipo, autor

RGE_RE = re.compile(r"RGE\s*n[úu]m\.?\s*(\d{1,6})\s*/\s*(\d{2})\b", re.I)
TIPOS = [
    ("pnl", r"proposicio\s*no\s*de\s*llei|proposicion\s*no\s*de\s*ley|proposicionsnodellei|proposicions\s*no\s*de\s*llei"),
    ("investidura", r"mocio\s*de\s*censura|questio\s*de\s*confian|investidura"),
    ("mocion", r"\bmocio(?!\s*de\s*censura)|\bmocion\b"),
    ("ilp", r"iniciativa\s*legislativa\s*popular"),
    ("ppl", r"proposicio(?:ns)?\s*de\s*llei|proposicion\s*de\s*ley"),
    ("pl", r"projecte\s*de\s*llei|proyecto\s*de\s*ley"),
    ("dl", r"decret\s*-?\s*llei|decreto\s*-?\s*ley"),
    ("control", r"propostes\s*de\s*resolucio|compareixenca|debat\s*general|comunicacio\s*del\s*govern|"
                r"limit\s*maxim\s*de\s*despesa|compte\s*general|informe\s*sobre\s*el\s*compliment|\bpla\s"),
    ("organizacion", r"reglament\s*del\s*parlament|elecci|designaci|incompatibilitat|estatut\s*dels\s*diputats|"
                     r"creacio\s*d.\s*una\s*comissio|comissio\s*no\s*permanent|comissio\s*d.investigacio|"
                     r"sessions\s*extraordinaries|composicio|senador|consell\s*consultiu|comissions\s*permanents|"
                     r"sindicatura|defensor"),
]


def _normaliza_epigrafe(t):
    """Arregla las palabras que el PDF pega en los epígrafes («MocióRGEnúm.20034/25,presentadapelGrup»)."""
    t = re.sub(r"(?<=[a-zà-ÿ])(?=RGE)", " ", t)
    t = re.sub(r"RGE\s*n[úu]m\.?\s*(?=\d)", "RGE núm. ", t)
    t = re.sub(r"(\d{2}),(?=[a-zA-ZÀ-ÿ])", r"\1, ", t)
    t = re.sub(r"presentad([ao]s?)(pel|pels|per)\b", r"presentad\1 \2", t)
    t = re.sub(r"\b(pel|pels|del|dels)(?=Grup)", r"\1 ", t)
    t = re.sub(r"(?<=Grup)(?=Parlamentari)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _rge(num, any_):
    return f"RGE {int(num)}/{any_}"


def _expedientes(t):
    """Expedientes (RGE) del epígrafe, el de la iniciativa primero.

    El de la iniciativa es el que sigue a «Moció», «Proposició (no) de llei», «Projecte de llei»; si no, el de
    «(escrit RGE núm. ...)» o «(RGE núm. ...)»; si no, el primero que no sea de una interpelación, pregunta o enmienda.
    """
    cands = []
    for m in RGE_RE.finditer(t):
        antes = _plano(t[max(0, m.start() - 40):m.start()])
        if re.search(r"(?:projecte\s*de\s*llei|proposicio\s*(?:no\s*)?de\s*llei|proposiciodellei|proposicionodellei|"
                     r"mocio|mocion|proposicion\s*(?:no\s*)?de\s*ley)\s*$", antes):
            rango = 1
        elif re.search(r"(?:escrits?|\()\s*$", antes):
            rango = 2
        elif re.search(r"(?:interpel\S*|pregunta|esmenes?|enmiendas?)\s*(?:,?\s*de\s+devolucio,?|,?\s*amb\s+text\s+alternatiu,?)?\s*$",
                       antes):
            rango = 9
        else:
            rango = 3
        cands.append((rango, m.start(), _rge(m.group(1), m.group(2))))
    return [c[2] for c in sorted(cands)]


_AUTOR = (r"(?:Grups?\s+Parlamentari|Govern\s+de\s+les\s+Illes|Ajuntament|Consell\s+(?:Insular|de\s+(?:Mallorca|Menorca|"
          r"Eivissa|Formentera))|Mesa\s+del|Diputaci)")


def _autor(t):
    """Quién presenta la iniciativa: «presentada pel Grup Parlamentari X» o «RGE núm. 4653/13, del Grup ...»."""
    m = re.search(r"presentad[ao]s?\s+(?:pel|pels|per\s+(?:el|la|els|les|l['’]))\s*(" + _AUTOR + r"[^,()]*?)(?=,|\.|\)|$)", t) \
        or re.search(r"\d{2}\s*,\s*(?:(?:rectificad[ao]|complementad[ao])\s+amb\s+l['’]escrit\s+RGE\s*núm\.\s*\d+/\d{2},\s*)?"
                     r"(?:del|dels|de\s+l['’]|de\s+la)\s+(" + _AUTOR + r"[^,.()]*?)(?=,|\.|\)|$)", t)
    return m.group(1).strip() if m else None


def _ficha(epigrafe):
    """{titulo, expedientes, tipo, autor} de un epígrafe del orden del día."""
    m = EPIGRAFE_RE.match(epigrafe)
    t = _normaliza_epigrafe(m.group("resto") if m else epigrafe)
    t = re.sub(r"^[-–—.\s]+|^Si\s+(?:n['’]és\s+el\s+cas|escau|pertoca),\s*", "", t)
    t = t[:1].upper() + t[1:]
    exps = _expedientes(t)
    autor = _autor(t)
    tit = t
    if exps:
        n, a = exps[0][4:].split("/")
        tit = re.sub(r"\s*\((?:escrits?\s+)?RGE\s*núm\.\s*%s\s*/\s*%s\b[^)]*\)" % (n, a), "", tit, count=1)
        tit = re.sub(r",?\s*(?:escrits?\s+)?RGE\s*núm\.\s*%s\s*/\s*%s\b" % (n, a), "", tit, count=1)
    tit = re.sub(r",?\s*(?:rectificad[ao]|complementad[ao])\s+amb\s+l['’]escrit\s+RGE\s*núm\.\s*\d+/\d{2}|"
                 r",?\s*ajornad[ao]\s+a\s+la\s+sessió\s+anterior", "", tit)
    tit = re.sub(r",?\s*presentad[ao]s?\s+(?:pel|pels|per\s+(?:el|la|els|les|l['’]))\s*" + _AUTOR + r"[^,()]*(?=[,)]|$)", "",
                 tit, count=1)
    if autor:
        tit = re.sub(r",\s*(?:del|dels|de\s+l['’]|de\s+la)\s+" + re.escape(autor) + r"(?=,)", "", tit, count=1)
    tit = re.sub(r"^Debat i (?:la )?votació sobre la (?:con)?validació o (?:la )?derogació del\s+", "Convalidació del ",
                 tit, flags=re.I)
    # «Debat i votació del dictamen de la Comissió X del Projecte de llei, de consells insulars» -> «Projecte de llei de
    # consells insulars»
    ley = re.match(r"^(?:Debat|Dictamen|Elaboració|Presa|Votació)\b.*?\b((?:Projecte|Proposició) de llei),?\s+"
                   r"((?:de|del|dels|per|pel|pels|sobre|relativa|d['’])\b.*)$", tit)
    if ley:
        tit = f"{ley.group(1)} {ley.group(2)}"
    tit = re.sub(r"\s+,", ",", re.sub(r",\s*,", ",", tit))
    tit = re.sub(r"^((?:Moció|Proposició(?: no)? de llei|Projecte de llei|Proposició de llei)),\s+", r"\1 ", tit)
    tit = re.sub(r"\b(Moció|de llei),\s+(relativa|relatiu|sobre|per\s+a|per\s+la|per\s+unes?|de\s+)", r"\1 \2", tit)
    tit = tit.strip(" .,;")
    p = _plano(t)
    trobats = [(mm.start(), k) for k, rx in TIPOS for mm in [re.search(rx, p)] if mm]
    tipo = min(trobats)[1] if trobats else "otro"
    if tipo in ("pl", "ppl") and re.search(r"pressuposts?\s*generals|presupuestos\s*generales", p):
        tipo = "presupuesto"
    return {"titulo": tit[:600], "expedientes": exps, "tipo": tipo, "autor": autor}


def _tipo_votacion(tipo, anuncio, titulo, previo=None):
    """Tipo de votación (catalogos.TIPOS_VOTACION); `previo` es el de la votación anterior del mismo asunto."""
    a, t = _plano(anuncio), _plano(titulo)
    if tipo == "investidura":
        return "investidura"
    tramitar = r"tramit\w*\s+com[oa]?\s+(?:a\s+)?(?:un\s+)?pro[jy]ec(?:te|to)\s+de\s+(?:llei|ley)"
    # tras convalidar un decreto ley se vota si se tramita como proyecto de ley (lo que se dice después de la
    # convalidación ya anuncia esa segunda votación, así que no sirve para distinguirlas)
    if re.search(tramitar, a) or (tipo == "dl" and previo in ("convalidacion", "tramitacion_ley")):
        return "tramitacion_ley"
    if re.search(r"totalitat|totalidad", a) or (re.search(r"esmen\w*\s+a\s+la\s+totalitat|debat\s+de\s+totalitat", t)
                                                 and not re.search(r"articl|articul|seccio|disposici", a)):
        return "totalidad"
    if tipo == "dl":
        return "convalidacion"
    if re.search(r"pres[ae]s?\s+en\s+consideracio|pren(?:\s+o\s+no)?\s+en\s+consideracio|toma\s+en\s+consideracion", f"{a} {t}"):
        return "toma_consideracion"
    if tipo == "ppl" and not re.search(r"dictamen|lectura\s+unica|esmen|enmiend|articl|articul|disposici|conjunt", f"{a} {t}"):
        return "toma_consideracion"  # una proposición de ley va al Pleno sin dictamen solo para tomarla en consideración
    if re.search(r"lectura\s+unica|procediment\s+directe|sessions\s+extraordinaries", f"{a} {t}"):
        return "organizacion"
    if tipo in ("pl", "ppl", "ilp", "presupuesto"):
        # lo primero que se nombra decide: «l'esmena 9486», «els articles 22, 26 ... (als quals no es mantenen esmenes)»;
        # «Esmena 9486.», «la 7940, del Grup ...», «13970.»: se votan enmiendas por su número
        esmena = re.search(r"esmen|enmiend|vots?\s+particulars?", a)
        article = re.search(r"articl|articul|disposici|exposicio|preambul|\btitol|\btitulo|annex|anexo|seccio|seccion|"
                            r"capitol|capitulo|estat\w*\s+de\s+(?:despeses|ingressos)|quantitat|cantidad|limit", a)
        if esmena and (not article or esmena.start() < article.start()) or re.match(
                r"^(?:i\s+|y\s+|ara\s+)?(?:(?:passam\s+a\s+)?vot\w*\s+)?(?:la\s+|les\s+|las\s+)?(?:rge\s+num\.\s*)?"
                r"\d{3,6}(?:/\d{2})?\b", a):
            return "enmiendas"
        if article:
            return "articulado"
        if re.search(r"conjunt|totalitat\s+del\s+(?:dictamen|projecte|text)|votacio\s+final|dictamen", a):
            return "conjunto"
        return None
    if tipo in ("pnl", "mocion"):
        return tipo
    if tipo == "organizacion":
        return "nombramiento" if re.search(r"elecci|designaci|senador", t) else "organizacion"
    if tipo == "control":
        return "control"
    return None


CORTESIA_RE = re.compile(r"^(?:(?:moltes\s+)?gràcies|(?:muchas\s+)?gracias|molt\s+bé|muy\s+bien|bé|bien|d['’]acord|"
                         r"de\s+acuerdo|idò|doncs|pues|vale)[,.]?\s+", re.I)
# frases que no dicen qué se vota: llamadas genéricas y cortesías
GENERICA_RE = re.compile(
    r"^(?:senyor[ae]s\s+i\s+senyor[ae]s\s+diputad[ae]s,?\s*|señor[ae]s\s+diputad[oa]s,?\s*)?"
    r"(?:(?:idò|doncs|bé|pues|per\s+tant|por\s+tanto|molt\s+bé|muy\s+bien|d['’]acord|de\s+acuerdo),?\s*)*(?:ara\s+|ahora\s+)?"
    r"(?:(?:passam|pasamos|procedim|procedemos|començam|comenzamos|vamos|anam|iniciam|iniciamos)\s+(?:a\s+)?"
    r"(?:votar|la\s+votaci[óo]n?|les\s+votacions|a\s+la\s+votaci[óo]n?)|comença\s+la\s+votació|començam|comenzamos|"
    r"votaci[óo]n?)[.,]?$|"
    r"^(?:(?:moltes\s+)?gràcies|(?:muchas\s+)?gracias|molt\s+bé|muy\s+bien|bé|bien|d['’]acord|de\s+acuerdo|vale|"
    r"silenci|silencio)\b[^.?!]{0,60}[.?!]?$", re.I)


def _subtitulo(anuncio):
    """Lo que la Presidencia anuncia que se vota: las últimas frases antes de «Votam.» (sin cortesías ni la llamada)."""
    a = re.sub(r"\s+", " ", anuncio or "").strip()
    frases = [LLAMADA_RE.sub("", a[i:f]).strip() for i, f in _frases(a, maximo=10 ** 6)]
    frases = [fr for fr in frases if fr and not GENERICA_RE.match(fr)]
    sel = []
    for fr in reversed(frases):
        sel.insert(0, fr)
        if len(" ".join(sel)) > 60 or re.search(r"vot|punt|esmen|enmiend|articl|artícul", fr, re.I):
            break
    s = CORTESIA_RE.sub("", " ".join(sel)).strip()
    if not s:
        return None
    if len(s) > 350:
        corte = s.rfind(". ", 0, 350)
        s = s[corte + 2:] if 0 < corte < len(s) - 40 else s[-350:]
    return s[:1].upper() + s[1:] if s else None


# ---------------------------------------------------------------- diario completo

SENAL_RE = re.compile(r"vots?\s+a\s+favor|votos?\s+a\s+favor|\d+\s+s[íi]\b|abstencions|abstenciones", re.I)
RECIENTES = 12  # diarios que `documentos()` lee aunque no estén en caché
_MEMO = {}


def _analizar(ctx, leg, num, partes):
    """Votaciones de un diario (todos sus fascículos, en orden): {"dias": [(fecha, [url], [dict])], "sin_leer": [...]}.

    `sin_leer` son los días en que la Presidencia llama a votar o lee votos pero las reglas no sacan ninguno.
    """
    clave = (leg, num, tuple(p[2] for p in partes))
    if clave in _MEMO:
        return _MEMO[clave]
    romanos, fasciculos = set(), []
    for _fasc, fecha, url, _desc in partes:
        try:
            lineas = _lineas(_texto_pdf(ctx, url))
        except (urllib.error.HTTPError, ErrorDescarga) as e:
            # sin memo: se reintenta en la próxima ejecución (el margen de `desde` lo vuelve a pedir)
            ctx.log(f"  ! {CUERPO}: {_nombre(url)} no disponible ({e}); se salta el diario núm. {num}")
            return {"dias": [], "sin_leer": []}
        items, rom = _sumario(lineas)
        romanos |= rom
        fasciculos.append((fecha, url, lineas, items))
    epigrafe, dias = None, {}
    unico = next((it for _f, _u, _l, it in fasciculos if len(it) == 1), [None])[0]
    for fecha, url, lineas, items in fasciculos:
        segs, epigrafe = _segmentos(lineas, romanos, epigrafe)
        votos = _votos(segs)
        por_defecto = items[0] if len(items) == 1 else unico
        for v in votos:
            v["url"] = url
            if not v["epigrafe"] and por_defecto:
                v["epigrafe"] = por_defecto
        senal = any(_presidencia(o) and (LLAMADA_RE.search(t) or SENAL_RE.search(t)) for o, _e, t in segs)
        d = dias.setdefault(fecha, {"urls": [], "votos": [], "senal": False})
        d["urls"].append(url)
        d["votos"].extend(votos)
        d["senal"] = d["senal"] or senal
    out = {"dias": [(f, d["urls"], d["votos"]) for f, d in sorted(dias.items(), reverse=True)],
           "sin_leer": [(f, d["urls"]) for f, d in sorted(dias.items(), reverse=True) if d["senal"] and not d["votos"]]}
    _MEMO[clave] = out
    return out


# ---------------------------------------------------------------- «Resultats de votacions» (2014-2020)

VOTS_PLE_RE = re.compile(r"href='(https?://contingutsweb\.parlamentib\.es/[^']*vots_PLE_(\d{8})_(\d+)\.pdf)'", re.I)
SUJETO_RE = re.compile(r"(?:\b|^)(?:no\s+)?(?:aprovad|aprovat|rebutjad|rebutjat|validad|validat|convalidad|convalidat|"
                       r"derogad|derogat|designad|designat|elegid|elegit|pres[ao]?\s+en\s+consideraci|decaigu|acceptad|"
                       r"ratificad|ratificat)\w*\b[^:]{0,160}(?::|\.)$", re.I)
CIFRA_RE = re.compile(r"^(Vots emesos|Vots vàlids|Vots a favor|Vots en contra|Abstencions|Vots en blanc|Vots nuls)"
                      r"[^\d]{0,40}?(\d{1,2})$", re.I)
CLAVES_CIFRA = {"vots emesos": "emitidos", "vots a favor": "a_favor", "vots en contra": "en_contra",
                "abstencions": "abstenciones"}
_RESULTATS = {}


def _resultats_indice(ctx):
    """{fecha: [url]} de los PDF de resultados del Pleno (la página dejó de actualizarse en diciembre de 2020)."""
    if "indice" not in _RESULTATS:
        try:
            h = _bajar(ctx, VOTACIONS, cache=f"{CUERPO}/votacions.html", caduca_dias=30).decode("latin-1")
        except (urllib.error.HTTPError, ErrorDescarga) as e:
            ctx.log(f"  ! {CUERPO}: «Resultats de votacions» no disponible ({e})")
            h = ""
        i = h.find("div_cos_PLE")
        j = h.find("div_header_", i + 1) if i >= 0 else -1
        indice = {}
        for url, dia, orden in VOTS_PLE_RE.findall(h[i:j] if i >= 0 else ""):
            fecha = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
            indice.setdefault(fecha, []).append((int(orden), url.replace(chr(92), "/")))
        _RESULTATS["indice"] = {f: [u for _o, u in sorted(x)] for f, x in indice.items()}
    return _RESULTATS["indice"]


def _resultats(ctx, url):
    """[{titulo, expediente, sujeto, resultado, unanimidad, emitidos, a_favor, en_contra, abstenciones}] de un PDF."""
    if url in _RESULTATS:
        return _RESULTATS[url]
    try:
        pdf = _bajar(ctx, url, cache=f"{CUERPO}/votacions/{url.rsplit('/', 1)[-1]}")
    except (urllib.error.HTTPError, ErrorDescarga) as e:
        ctx.log(f"  ! {CUERPO}: {url} no disponible ({e})")
        return []
    _RESULTATS[url] = entradas = _entradas_resultats(pdf, url)
    return entradas


def _entradas_resultats(pdf, url):
    entradas, titulo, buf, actual = [], None, [], None
    for ln in _lineas(Contexto.pdf_texto(pdf, raw=True)):
        if ln.startswith(("Votacions de la sessió", "Per a una informació")):
            continue
        m = CIFRA_RE.match(ln)
        if m and actual is not None:
            clave = CLAVES_CIFRA.get(m.group(1).lower())
            if clave:
                actual[clave] = int(m.group(2))
            continue
        if SUJETO_RE.search(ln) and len(ln) < 250:
            # el título acaba en la última línea con punto final; lo que sigue es el principio del sujeto
            corte = max((k + 1 for k, x in enumerate(buf) if _acaba(x)), default=0)
            if corte:
                titulo = _une(buf[:corte])
            sujeto = _une(buf[corte:] + [ln])
            p = _plano(sujeto)
            actual = {"titulo": titulo, "expediente": (_expedientes(titulo or "") or [None])[0], "sujeto": sujeto,
                      "resultado": "rechazada" if re.search(r"rebutja|derogat|derogad|decaigu|^no\s", p) else "aprobada",
                      "unanimidad": "unanimitat" in p or "assentiment" in p, "url": url}
            entradas.append(actual)
            buf = []
            continue
        buf.append(ln)
        actual = None
    return entradas


def _verificar(ctx, fecha, votos):
    """Casa las votaciones de un día con los «Resultats de votacions» (mismo recuento y expediente, en orden)."""
    entradas = [e for url in _resultats_indice(ctx).get(fecha, []) for e in _resultats(ctx, url)]
    p = 0
    for v in votos:
        if v["asentimiento"] or v["a_favor"] is None:
            continue
        for q in range(p, len(entradas)):
            e = entradas[q]
            if e["expediente"] and v.get("expediente") and e["expediente"] != v["expediente"]:
                continue
            if not (e["expediente"] and v.get("expediente")) and q > p + 3:
                break
            if e.get("a_favor") is not None:
                ok = e["a_favor"] == v["a_favor"] and e.get("en_contra", 0) == (v["en_contra"] or 0) \
                    and e.get("abstenciones", 0) == (v["abstenciones"] or 0)
            else:  # «aprovats per unanimitat»: sin votos en contra ni abstenciones y con mayoría de la cámara
                ok = e["unanimidad"] and not v["en_contra"] and not v["abstenciones"] and v["a_favor"] > 30
            if ok:
                v["oficial"] = e
                p = q
                break


# ---------------------------------------------------------------- votaciones

def _votacion(leg, num, fecha, n, v, previo=None):
    """Votacion de un recuento; `previo` es el tipo de la votación anterior del mismo asunto en el diario."""
    ficha = _ficha(v["epigrafe"]) if v["epigrafe"] else None
    if ficha and re.match(r"(?:pregunta|interpel)", _plano(ficha["titulo"])):
        ficha = None  # las preguntas e interpelaciones no se votan: el epígrafe del punto votado no se ha reconocido
    exps = ficha["expedientes"] if ficha else []
    exp = exps[0] if exps else None
    for m in RGE_RE.finditer((v["anuncio"] or "")[-400:]):  # el punto concreto de un epígrafe con varias iniciativas
        if _rge(m.group(1), m.group(2)) in exps:
            exp = _rge(m.group(1), m.group(2))
    subtitulo = v["lectura"] if v["asentimiento"] else _subtitulo(v["anuncio"])
    titulo = ficha["titulo"] if ficha else (subtitulo or v["lectura"])
    tipo = ficha["tipo"] if ficha else None
    extra = {"diario": _nombre(v["url"]), "lectura": v["lectura"]}
    if v["despues"]:
        extra["despues"] = v["despues"][:300]
    for k in ("en_blanco", "nulos"):
        if v.get(k) is not None:
            extra[k] = v[k]
    if v.get("mismo"):
        extra["mismo_resultado"] = True  # «Mismo resultado»: el recuento es el de la votación anterior
    if v.get("suma_remota"):
        extra["suma_remota"] = True  # presencial más los votos a distancia que la Presidencia lee aparte
    a, c, ab = v["a_favor"], v["en_contra"], v["abstenciones"]
    if v["empate"] or (a is not None and a == c):
        extra["empate"] = True  # en el Parlament un empate se vota hasta tres veces: cada votación va aparte
    if sum(x or 0 for x in (a, c, ab)) > CUERPOS[0].escanos_de(leg):
        extra["totales_descartados"] = f"{a}-{c}-{ab}"  # errata del diario o lectura imposible
        a = c = ab = None
    mayoria = None
    if v["mayoria"]:
        extra["mayoria_citada"] = v["mayoria"].group(0)
        if "absolut" in v["mayoria"].group(0).lower():
            mayoria = "absoluta"
    presentes = None
    resultado = v["resultado"]
    oficial = v.get("oficial")
    if oficial:
        extra["verificada"] = True
        extra["resultats"] = oficial["url"]
        if oficial.get("emitidos") and oficial["emitidos"] >= sum(x or 0 for x in (a, c, ab)):
            presentes = oficial["emitidos"]
        resultado = resultado or oficial["resultado"]

    def cuadra(res):
        return res is None or a is None or c is None or v["mayoria"] or (res == "aprobada") == (a > c)

    if not cuadra(resultado):
        extra["resultado_no_cuadra"] = resultado  # la proclamación no casa con los votos: no se usa
        resultado = oficial["resultado"] if oficial and oficial["resultado"] != resultado and cuadra(oficial["resultado"]) \
            else None
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=num, numero=n, legislatura=leg,
        subtitulo=subtitulo if subtitulo and subtitulo != titulo else None, expediente=exp,
        tipo_iniciativa=tipo, tipo_votacion=_tipo_votacion(tipo, f"{subtitulo or ''} {(v['anuncio'] or '')[-300:]}", titulo,
                                                    previo) if ficha else None,
        autor=ficha["autor"] if ficha else None, a_favor=a, en_contra=c, abstenciones=ab, presentes=presentes,
        asentimiento=v["asentimiento"], resultado=resultado, mayoria=mayoria, url=v["url"], fuente="pdf-reglas",
        extra=extra)


def _por_adelantado(pool, funcion, elementos, adelanto=3):
    """[(elemento, funcion(elemento))] en orden, con hasta `adelanto` trabajos en marcha a la vez."""
    pendientes, it = deque(), iter(elementos)
    for x in it:
        pendientes.append((x, pool.submit(funcion, x)))
        if len(pendientes) >= adelanto:
            break
    while pendientes:
        x, futuro = pendientes.popleft()
        siguiente = next(it, None)
        if siguiente is not None:
            pendientes.append((siguiente, pool.submit(funcion, siguiente)))
        yield x, futuro.result()


def descargar(ctx):
    desde = ctx.desde(CUERPO, margen_dias=45)  # un diario puede publicarse semanas después de la sesión
    n_total, iniciativas = 0, set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for (leg, num, _partes), an in _por_adelantado(pool, lambda d: _analizar(ctx, *d), _diarios(ctx, desde)):
            for fecha, _urls, votos in an["dias"]:
                if desde and fecha < desde:
                    continue
                if "2014-09-01" <= fecha <= "2020-12-31" and fecha in _resultats_indice(ctx):
                    for v in votos:
                        f = _ficha(v["epigrafe"]) if v["epigrafe"] else None
                        v["expediente"] = f["expedientes"][0] if f and f["expedientes"] else None
                    _verificar(ctx, fecha, votos)
                previos = {}  # epígrafe -> tipo de su última votación (convalidación y luego tramitación)
                for k, v in enumerate(votos, 1):
                    vo = _votacion(leg, num, fecha, k, v, previos.get(v["epigrafe"]))
                    previos[v["epigrafe"]] = vo.tipo_votacion
                    if vo.resultado is None and vo.a_favor is None and not vo.asentimiento:
                        ctx.log(f"  {CUERPO}: {vo.extra['diario']} ({fecha}), votación {k} sin totales posibles ni "
                                f"resultado: {v['lectura'][:100]}")
                        continue
                    if vo.expediente and (leg, vo.expediente) not in iniciativas:
                        iniciativas.add((leg, vo.expediente))
                        yield Iniciativa(CUERPO, vo.expediente, vo.titulo, legislatura=leg,
                                         tipo_iniciativa=vo.tipo_iniciativa, autor=vo.autor, url=vo.url)
                    yield vo
                    n_total += 1
                    if ctx.limite and n_total >= ctx.limite:
                        return


def _en_cache(url):
    return (CACHE_DIR / CUERPO / "ple" / f"{_nombre(url)}.pdf.gz").exists()


def documentos(ctx):
    """Días de diario en que se vota pero las reglas no leen ningún recuento (para el LLM).

    Para saberlo hay que leer el diario: se miran los ya descargados (por `descargar`, en esta ejecución o antes) y
    los RECIENTES últimos; así, sin caché (GitHub Actions), listar los documentos no baja todo el archivo cada día.
    """
    desde = ctx.desde(CUERPO, margen_dias=45)
    candidatos = (d for k, d in enumerate(_diarios(ctx, desde))
                  if k < RECIENTES or all(_en_cache(p[2]) for p in d[2]))
    n = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for (leg, num, partes), an in _por_adelantado(pool, lambda d: _analizar(ctx, *d), candidatos):
            for fecha, urls in an["sin_leer"]:
                if desde and fecha < desde:
                    continue
                fasc = [p for p in partes if p[2] in urls]
                extra = re.sub(r"^Núm\.? \d+,?( fascicle \d+)?( [XVI]+ legislatura)?\s*", "", fasc[0][3])
                titulo = f"Diari de Sessions del Ple, {romano(leg)} legislatura, núm. {num}" + \
                    (f". {extra}" if extra else "")
                yield Documento(CUERPO, fecha, urls[0], sesion=num, formato="pdf", idioma="ca", titulo=titulo,
                                legislatura=leg, extra={"fasciculos": urls})
                n += 1
                if ctx.limite and n >= ctx.limite:
                    return


def texto(ctx, doc):
    return "\n\n".join(_texto_pdf(ctx, url) for url in doc.extra.get("fasciculos") or [doc.url])
