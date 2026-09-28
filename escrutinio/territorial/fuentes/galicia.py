"""Parlamento de Galicia: votaciones del Pleno sacadas con reglas del Diario de Sesións (PDF, en gallego).

Fuente: el Diario de Sesións do Parlamento de Galicia (DSPG), serie Pleno, un PDF por día de sesión con
URL predecible (…/BibliotecaDiarioSesions/D{legislatura}{número de 4 cifras}.pdf; la serie de la
Diputación Permanente, DP…, no se usa). No hay datos abiertos de votaciones. Los últimos 100 diarios
con su fecha salen del RSS (/Rss/Dspg); los anteriores se recorren por número (el buscador de boletines
pagina mal y repite o salta resultados) y la fecha se lee de la portada del PDF.

El sumario de cada diario resume cada votación en una frase muy regular, que es lo que se lee aquí:
«Votación da Moción do G. P. …, sobre …: rexeitada por 33 votos a favor, 37 votos en contra e ningunha
abstención. (Páx. 45.)». El expediente (12/MOC-000131) se busca en la orde do día del mismo diario
comparando el asunto; si no se reconoce sin dudas, queda en None.

La web está detrás de Akamai, que responde 403 a Python con su lista de cifrados TLS por defecto y sin
cabeceras de navegador: aquí se usa un abridor propio con los cifrados «DEFAULT» de OpenSSL y cabeceras de
Chrome (Contexto.fetch no permite cambiar el contexto TLS). La caché es la misma de Contexto.

Cobertura: Pleno de las legislaturas X (2016), XI y XII (la actual), unos 400 diarios.
Detalle: totales (a favor, en contra, abstenciones) y resultado publicado; no hay voto por grupo ni
nominal. Las elecciones por papeleta (Mesa, senadores) y los asentimientos sin recuento no se recogen.
Limitaciones: el diario se publica unas dos semanas después de la sesión; el expediente falta cuando el
sumario resume el asunto con otras palabras que la orde do día (y en propuestas de resolución).
"""

import gzip
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import CACHE_DIR, Contexto, ErrorDescarga
from ..modelo import Documento, Votacion

CUERPO = "parl-GA"
WEB = "https://www.parlamentodegalicia.gal"
RSS = WEB + "/Rss/Dspg"
PDF = "https://www.parlamentodegalicia.es/sitios/web/BibliotecaDiarioSesions/D{leg:02d}{num:04d}.pdf"
PDF_RE = re.compile(r"/D(\d{2})(\d{4})\.pdf$", re.I)
# Legislaturas cerradas: último diario de la serie Pleno (comprobado el 26-9-2026: el siguiente da 404).
ULTIMO = {10: 148, 11: 155}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("GA"), "Parlamento de Galicia", "Parlamento (Galicia)", "autonomico", "GA", 75,
           {10: (romano(10), "2016-10-21", "2020-08-07"),
            11: (romano(11), "2020-08-07", "2024-03-18"),
            12: (romano(12), "2024-03-18", None)},
           web=WEB),
]

NOTAS = ("Diario de Sesións del Pleno (PDF en gallego) leído con reglas: totales y resultado de cada votación "
         "desde el sumario, expediente buscado en la orde do día. Sin voto por grupo ni nominal. X, XI y XII. "
         "Web tras Akamai: abridor propio con cifrados TLS «DEFAULT» y cabeceras de navegador.")

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/140.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "gl-ES,gl;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
}

MESES = {m: i for i, m in enumerate(("xaneiro", "febreiro", "marzo", "abril", "maio", "xuño", "xullo", "agosto",
                                     "setembro", "outubro", "novembro", "decembro"), 1)}
CABECERA_RE = re.compile(r"lexislatura\.?\s*Serie Pleno\.?\s*Número\s*(\d+)\.?\s*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})")
RUIDO_RE = re.compile(r"^(CSV:.*|Verificación:.*|https://sede\.parlamentodegalicia\S*|\d{1,4}|\*|"
                      r"[XVI]+ lexislatura\. Serie Pleno\..*|DIARIO DE SESIÓNS DO PARLAMENTO DE GALICIA|"
                      r"Asinado dixitalmente.*|Data: .*|Razón: .*|Localización: .*)$", re.I)
INICIO_RE = re.compile(r"^(Ábrese|Retómase|Reanúdase) a sesión")
ORADOR_RE = re.compile(r"^(O|A) (señor |señora )?[A-ZÁÉÍÓÚÑ]{4,}[A-ZÁÉÍÓÚÑ ]*( \([^)]*\))?:")
PAX_RE = re.compile(r"\(P[áa]x[^)]*\)\s*\.?\s*$")
VOTO_RE = re.compile(r"^Votación (?P<asunto>.+?):\s*(?P<res>(?:aprobad|rexeitad)[oa]s?)?\s*(?:por\s+)?"
                     r"(?P<votos>[^:]*?\ba favor\b[^:]*?|unanimidade[^:]*?)\s*\.?\s*\(P[áa]x", re.S)
FAVOR_RE = re.compile(r"(\d+|ningún|un) votos? a favor")
CONTRA_RE = re.compile(r"(\d+|ningún|un)(?: votos?)? en contra")
ABST_RE = re.compile(r"(\d+|ningunha|unha) abstenci[óo]ns?")
EXPEDIENTE_RE = re.compile(r"\b(\d{1,2}/[A-ZÑ]{2,6}-\d{3,6})\b")
ITEM_RE = re.compile(r"^(\d+\.\s?\d+\s|Punto (\d+|único)\.)")
# Núcleo del asunto: lo anterior (texto transaccionado, emendas…, ditame…) va al subtítulo.
NUCLEO_RE = re.compile(r"(Proposición non de lei|Proposición de lei|Proxecto de lei|Iniciativa lexislativa popular|"
                       r"Decreto[- ]lei|Decreto lexislativo|propostas? de resolución|límite de gasto|"
                       r"Proxecto de orzamentos|Moción)", re.I)
CONECTOR_RE = re.compile(r"(\s*,)?\s+(sobre|d[aoe]s?|aos?|ás?|á|a|o|as|os|entre|relativ[oa]s? a)\s*$", re.I)
TIPOS = [("proposición non de lei", "pnl"), ("proposición no de lei", "pnl"), ("moción", "mocion"), ("proxecto de orzamentos", "presupuesto"),
         ("límite de gasto", "presupuesto"), ("proxecto de lei", "pl"), ("proposición de lei", "ppl"),
         ("iniciativa lexislativa popular", "ilp"), ("decreto lei", "dl"), ("decreto-lei", "dl"),
         ("proposta de resolución", "control"), ("propostas de resolución", "control")]
PREFIJOS_EXP = {"pnl": ("PNP",), "mocion": ("MOC",), "pl": ("PL",), "ppl": ("PPL", "PPLC", "PPLI"), "ilp": ("ILP",),
                "dl": ("DL", "DLE")}

_ABRIDOR = None


# ---------------------------------------------------------------- descarga

def _abridor():
    global _ABRIDOR
    if _ABRIDOR is None:
        tls = ssl.create_default_context()
        tls.set_ciphers("DEFAULT")  # con la lista de cifrados propia de Python, Akamai responde 403
        _ABRIDOR = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls))
    return _ABRIDOR


def _bajar(ctx, url, cache=None, caduca_dias=None, metodo="GET"):
    """Como Contexto.fetch (misma caché en disco), pero con el abridor que acepta Akamai."""
    ruta = CACHE_DIR / f"{cache}.gz" if cache else None
    if ruta and ruta.exists() and not (caduca_dias is not None and time.time() - ruta.stat().st_mtime > caduca_dias * 86400):
        return gzip.decompress(ruta.read_bytes())
    ultimo = None
    for intento in range(4):
        try:
            req = urllib.request.Request(url, headers=CABECERAS, method=metodo)
            with _abridor().open(req, timeout=90) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 410):
                raise
            ultimo = e
        except Exception as e:  # red, timeouts
            ultimo = e
        time.sleep(1.5 * (intento + 1))
    else:
        raise ErrorDescarga(f"No se pudo descargar {url}: {ultimo}")
    if ruta is not None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(gzip.compress(raw))
    if ctx.pausa:
        time.sleep(ctx.pausa)
    return raw


def _existe(ctx, url):
    try:
        _bajar(ctx, url, metodo="HEAD")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def _cache_pdf(leg, num):
    return f"{CUERPO}/dspg/D{leg:02d}{num:04d}.pdf"


def _texto_pdf(ctx, leg, num):
    return Contexto.pdf_texto(_bajar(ctx, PDF.format(leg=leg, num=num), cache=_cache_pdf(leg, num)), layout=False)


# ---------------------------------------------------------------- listado de diarios

def _rss(ctx):
    """{(legislatura, número): fecha} de los últimos diarios de la serie Pleno."""
    fechas = {}
    try:
        raiz = ET.fromstring(_bajar(ctx, RSS))
    except (ErrorDescarga, urllib.error.HTTPError, ET.ParseError) as e:
        ctx.log(f"  ! {CUERPO}: RSS no disponible ({e}); se sigue por número")
        return fechas
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for e in raiz.findall("a:entry", ns):
        m = PDF_RE.search(e.findtext("a:id", "", ns))
        fecha = (e.findtext("a:published", "", ns) or "")[:10]
        if m and re.match(r"\d{4}-\d{2}-\d{2}$", fecha):
            fechas[(int(m.group(1)), int(m.group(2)))] = fecha
    return fechas


def _diarios(ctx):
    """[(legislatura, número, fecha o None)] de la serie Pleno, del más reciente al más antiguo."""
    fechas = _rss(ctx)
    declaradas = CUERPOS[0].legislaturas
    for (leg, _n) in sorted(fechas):
        if leg not in declaradas:
            ctx.log(f"  ! {CUERPO}: hay diarios de la legislatura {leg}, que no está declarada")
    ultimo = dict(ULTIMO)
    for leg in declaradas:
        if leg in ultimo:
            continue
        n = max([k[1] for k in fechas if k[0] == leg], default=0)
        fallos, prueba = 0, n + 1  # por si el RSS va con retraso
        while fallos < 2:
            if _existe(ctx, PDF.format(leg=leg, num=prueba)):
                n, fallos = prueba, 0
            else:
                fallos += 1
            prueba += 1
        ultimo[leg] = n
    for leg in sorted(declaradas, reverse=True):
        for num in range(ultimo.get(leg, 0), 0, -1):
            yield leg, num, fechas.get((leg, num))


def _fecha_texto(texto):
    m = CABECERA_RE.search(texto[:6000])
    if not m or m.group(3).lower() not in MESES:
        return None
    return f"{m.group(4)}-{MESES[m.group(3).lower()]:02d}-{int(m.group(2)):02d}"


def documentos(ctx):
    desde = ctx.desde(CUERPO)
    n = 0
    for leg, num, fecha in _diarios(ctx):
        if fecha is None:  # fuera del RSS: la fecha sale de la portada (el PDF queda en caché para el texto)
            try:
                fecha = _fecha_texto(_texto_pdf(ctx, leg, num))
            except urllib.error.HTTPError as e:
                ctx.log(f"  ! {CUERPO}: DSPG {leg}/{num}: HTTP {e.code}")
                continue
            if not fecha:
                ctx.log(f"  ! {CUERPO}: DSPG {leg}/{num} sin fecha en la portada")
                continue
        if desde and fecha < desde:
            return
        yield Documento(CUERPO, fecha, PDF.format(leg=leg, num=num), sesion=num, formato="pdf", idioma="gl",
                        titulo=f"Diario de Sesións, {romano(leg)} lexislatura, serie Pleno, n.º {num}", legislatura=leg)
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    m = PDF_RE.search(doc.url)
    return _texto_pdf(ctx, int(m.group(1)), int(m.group(2)))


# ---------------------------------------------------------------- lectura del diario

def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _lineas(texto):
    return [x.strip() for x in texto.splitlines() if x.strip() and not RUIDO_RE.match(x.strip())]


def _orde_do_dia(lineas):
    """[(expedientes, texto normalizado, texto)] de los puntos de la orde do día."""
    items, actual, dentro = [], None, False
    for x in lineas:
        if x == "SUMARIO" or INICIO_RE.match(x) or ORADOR_RE.match(x):
            break
        if x.upper().startswith("ORDE DO DÍA"):
            dentro = True
        elif dentro and (ITEM_RE.match(x) or actual is None):  # sin número: «Debate anual sobre política xeral…»
            actual = [x]
            items.append(actual)
        elif actual is not None:
            actual.append(x)
    out = []
    for it in items:
        t = " ".join(it)
        exps = EXPEDIENTE_RE.findall(t)
        if exps:
            out.append((exps, _norm(t), t))
    return out


def _entradas_sumario(lineas):
    """Frases «Votación …: … (Páx. N.)» del sumario, unidas aunque crucen un salto de página."""
    inicio = lineas.index("SUMARIO") + 1 if "SUMARIO" in lineas else 0  # alguna vez falta el rótulo
    out, buf = [], None
    for x in lineas[inicio:]:
        if ORADOR_RE.match(x):  # empieza el cuerpo del diario
            break
        if x.startswith("Votación ") and (buf is None or ":" not in buf):
            buf = x  # los rótulos («Votación das mocións») no llevan resultado: se descartan
        elif buf is not None:
            buf += " " + x
        else:
            continue
        if PAX_RE.search(buf) or len(buf) > 3000:
            out.append(buf)
            buf = None
    return out


def _num(s):
    return {"ningún": 0, "ningunha": 0, "un": 1, "unha": 1}.get(s, None) if not s.isdigit() else int(s)


def _separar(asunto):
    """(título, subtítulo) a partir de lo que sigue a «Votación»."""
    asunto = re.sub(r"^(d[aoe]s?|de)\s+", "", asunto.strip())
    m = NUCLEO_RE.search(asunto)
    if not m or m.start() == 0:
        return asunto[:1].upper() + asunto[1:], None
    pre = asunto[:m.start()]
    while CONECTOR_RE.search(pre):
        pre = CONECTOR_RE.sub("", pre)
    tit = asunto[m.start():]
    return tit[:1].upper() + tit[1:], (pre[:1].upper() + pre[1:]) or None


def _tipo(titulo):
    t = titulo.lower()
    for clave, tipo in TIPOS:
        if t.startswith(clave):
            return tipo
    if "orzamentos" in t or "gasto non financeiro" in t:
        return "presupuesto"
    if "comisión de investigación" in t:
        return "organizacion"
    return None


def _tipo_votacion(tipo, titulo, subtitulo, asunto):
    sub = (subtitulo or ("" if tipo else titulo)).lower()  # sin núcleo reconocido, lo votado va en el título
    if "totalidade" in sub:
        return "totalidad"
    if re.search(r"\bemendas?\b|\bvotos? particular", sub):  # «texto autoemendado» no es una emenda
        return "enmiendas"
    if "toma en consideración" in asunto.lower():
        return "toma_consideracion"
    if sub.startswith("texto articulado"):
        return "articulado"
    if sub.startswith("ditame") and tipo in ("pl", "ppl", "ilp"):
        return "conjunto"
    if tipo == "dl" and "convalidación" in asunto.lower():
        return "convalidacion"
    return {"pnl": "pnl", "mocion": "mocion", "control": "control"}.get(tipo)


def _autor(tipo, titulo):
    if tipo == "pl":
        return "Xunta de Galicia"
    m = re.search(r"\bd[oa] (G\. ?P\. .+?)(?=,| sobre | e |$)", titulo)
    return m.group(1).strip() if m else None


def _expediente(tipo, titulo, orde):
    """Expediente del punto de la orde do día que trata el mismo asunto, si se reconoce sin dudas.

    Se comparan las palabras del título (grupo, autores y asunto) con las de cada punto: el bueno
    comparte más del 75 % y el siguiente queda muy por debajo.
    """
    if not orde or tipo in (None, "control"):
        return None
    palabras = [p for p in dict.fromkeys(_norm(titulo).split()) if len(p) > 3][:40]
    if len(palabras) < 3:
        return None
    prefijos = PREFIJOS_EXP.get(tipo)
    candidatos = {}
    for exps, texto, _t in orde:
        propios = [e for e in exps if not prefijos or e.split("/", 1)[1].split("-")[0] in prefijos]
        if propios:
            vocab = set(texto.split())
            nota = sum(p in vocab for p in palabras) / len(palabras)
            candidatos[propios[0]] = max(nota, candidatos.get(propios[0], 0))
    orden = sorted(candidatos.items(), key=lambda kv: -kv[1])
    if not orden or orden[0][1] < 0.75 or (len(orden) > 1 and orden[0][1] - orden[1][1] < 0.25):
        return None
    return orden[0][0]


def votaciones_diario(texto, leg, num, url, fecha=None):
    """Votaciones del sumario de un diario (texto de pdftotext sin -layout)."""
    fecha = _fecha_texto(texto) or fecha
    if not fecha:
        return []
    lineas = _lineas(texto)
    orde = _orde_do_dia(lineas)
    out = []
    for frase in _entradas_sumario(lineas):
        m = VOTO_RE.match(re.sub(r"\s+", " ", frase))
        if not m:
            continue
        votos = m.group("votos")
        fav, con, abst = (FAVOR_RE.search(votos), CONTRA_RE.search(votos), ABST_RE.search(votos))
        a_favor = _num(fav.group(1)) if fav else None
        en_contra = _num(con.group(1)) if con else (0 if a_favor is not None else None)
        abstenciones = _num(abst.group(1)) if abst else (0 if a_favor is not None else None)
        res = (m.group("res") or "").lower()
        resultado = "aprobada" if res.startswith("aprobad") else "rechazada" if res.startswith("rexeitad") else None
        if "unanimidade" in votos and not res:
            resultado = "aprobada"
        if a_favor is None and resultado is None:
            continue
        if sum(x or 0 for x in (a_favor, en_contra, abstenciones)) > 75:
            a_favor = en_contra = abstenciones = None
            if resultado is None:
                continue
        asunto = m.group("asunto").strip()
        titulo, subtitulo = _separar(asunto)
        tipo = _tipo(titulo)
        expediente = _expediente(tipo, titulo, orde)
        if tipo == "control" and len(orde) == 1:  # propuestas de resolución de un debate (12/DEBA-000002)
            expediente = orde[0][0][0]
            debate = re.sub(r"^(Punto (\d+|único)\.|\d+\.\s?\d+)\s*", "", orde[0][2]).split(".")[0].strip()
            titulo = f"{debate}. {titulo}"
        out.append(Votacion(
            cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=num, numero=len(out) + 1, legislatura=leg,
            subtitulo=subtitulo, expediente=expediente, tipo_iniciativa=tipo,
            tipo_votacion=_tipo_votacion(tipo, titulo, subtitulo, asunto), autor=_autor(tipo, titulo),
            a_favor=a_favor, en_contra=en_contra, abstenciones=abstenciones, resultado=resultado,
            url=url, fuente="pdf-reglas", extra={"dspg": num}))
    return out


def descargar(ctx):
    desde = ctx.desde(CUERPO)
    n = 0
    for leg, num, fecha in _diarios(ctx):
        if desde and fecha and fecha < desde:
            return
        url = PDF.format(leg=leg, num=num)
        try:
            t = _texto_pdf(ctx, leg, num)
        except urllib.error.HTTPError as e:
            ctx.log(f"  ! {CUERPO}: DSPG {leg}/{num}: HTTP {e.code}")
            continue
        fecha = _fecha_texto(t) or fecha
        if not fecha:
            ctx.log(f"  ! {CUERPO}: DSPG {leg}/{num} sin fecha en la portada")
            continue
        if desde and fecha < desde:
            return
        vots = votaciones_diario(t, leg, num, url, fecha)
        for v in vots:
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
