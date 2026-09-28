"""Asamblea Regional de Murcia: votaciones del Pleno sacadas con reglas de las actas (PDF).

Fuente: «Actas de Pleno y Comisiones» (https://www.asambleamurcia.es/arm/actas/pleno), con una carpeta
por legislatura («Undécima Legislatura (2023 a 2027)») y dentro una página por año que enlaza cada
acta («Acta de la sesión 131 del Pleno de la Cámara celebrada el 17 de junio de 2026»,
/ACTAS11L/ORGANOS%20DE%20LA%20CAMARA/PLENO/2026/061709-131.pdf). El acta es corta (unas 8 páginas),
lleva el expediente de cada punto (11L/MOCP-1234, 11L/PPL-0029) y el resultado de cada votación con
los totales en letra y, casi siempre, los grupos: «resulta aprobada por veintisiete votos a favor
(Grupos Parlamentarios Popular y Vox), quince votos en contra (...) y ninguna abstención».

Qué se saca: cada punto del orden del día se anuncia con su número, su expediente y su título («1.-
11L/MOCP-0820 MOCIÓN EN PLENO SOBRE...FORMULADA POR EL G.P. VOX»); dentro, cada «Sometida a
votación...», «Votada...» o «Efectuada la votación...» que termina en «es/resulta aprobada/rechazada
por N votos a favor (grupos), M votos en contra (grupos) y K abstenciones (grupos)» (los números en
letra) da una votación, con el grupo o la persona que se cita en cada paréntesis; lo que se anuncia
justo antes (una enmienda, un punto, la moción en su nueva redacción...) es el subtítulo. Las
aprobaciones «por unanimidad» sin recuento quedan como asentimiento. Un empate se repite hasta tres
veces («se produce un empate», «se obtiene idéntico resultado»): cada intento es una votación; solo el
último, cuando se proclama, lleva resultado. En el debate general sobre la actuación del Gobierno se
votan, una a una, las propuestas de resolución de cada grupo.

No hay datos estructurados: el buscador de iniciativas (wwwold.asambleamurcia.es/armnet) da 403 y el
Diario de Sesiones (PDF, publicaciones/diario-de-sesiones) llega con más retraso que el acta y es una
transcripción completa. La web tiene el certificado TLS roto: todo se pide con inseguro=True.

Cobertura: Pleno de la IX, X y XI legislaturas (junio de 2015 a hoy), unas 390 actas; cada sesión (un
día) tiene su número y su acta. Las carpetas «X Legislatura» y «Sin categorizar» (duplicadas o
antiguas) no se leen.
Limitaciones: el acta se publica semanas después de la sesión (firmada); los números van en letra; la
fecha es la del listado (primer día si la sesión dura dos). Las actas de la IX y la X son escaneadas
con capa de OCR: el texto tiene ruido (letras cambiadas, barras que marcan saltos de línea), aunque
las frases de votación suelen leerse; cuando el ruido estropea el recuento, la sesión queda para leer
aparte. Los nombres de grupo con ruido se comparan con los grupos de la Asamblea y lo que no se parece a
ninguno se descarta. Las investiduras con votación nominal (llamamiento uno a uno) y las designaciones
por papeleta secreta (varias candidaturas, sin «a favor»/«en contra») tampoco se leen con reglas.
"""

import difflib
import re
import unicodedata
import urllib.parse
from collections import Counter
from datetime import date

from ...territorio import Cuerpo, num_parlamento
from ..contexto import CACHE_DIR, Contexto
from ..modelo import Documento, Iniciativa, Votacion, VotoGrupo

CUERPO = "parl-MC"
BASE = "https://www.asambleamurcia.es"
RAIZ = BASE + "/arm/actas/pleno"

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("MC"), "Asamblea Regional de Murcia", "Asamblea Regional (Murcia)", "autonomico",
           "MC", 45,
           {9: ("IX", "2015-06-15", "2019-06-11"),
            10: ("X", "2019-06-11", "2023-06-14"),
            11: ("XI", "2023-06-14", None)},
           web=RAIZ),
]

NOTAS = ("Votaciones del Pleno con reglas sobre el acta en PDF: cada punto del orden del día con su expediente y "
         "título, y cada «Sometida a votación... es aprobada/rechazada por N votos a favor (grupos), M en contra "
         "(grupos) y K abstenciones (grupos)» (números en letra), con asentimiento cuando se aprueba por unanimidad "
         "sin recuento y las tres repeticiones de un empate. Sin datos estructurados (buscador de iniciativas con "
         "403). IX a XI (desde junio de 2015). Certificado TLS roto (inseguro). El acta se publica semanas después "
         "de la sesión. IX y X escaneadas (OCR con ruido: se pierden los días en que el recuento no se lee limpio). "
         "Las investiduras con votación nominal y las designaciones por papeleta secreta van al LLM.")

ORDINALES = {"novena": 9, "décima": 10, "decima": 10, "undécima": 11, "undecima": 11, "duodécima": 12,
             "duodecima": 12, "decimotercera": 13}
MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
CARPETA_RE = re.compile(r'href="(/arm/actas/pleno/([A-Za-zÁÉÍÓÚáéíóú%0-9]+)-Legislatura-%28(\d{4})-a-(\d{4})%29)"', re.I)
ANIO_RE = re.compile(r'href="(/arm/actas/pleno/[^"/]+/(\d{4}))"')
ACTA_RE = re.compile(r'href="([^"]+\.pdf)"[^>]*>\s*(Acta de la sesi[oó]n\s+(\d+)\s+del Pleno[^<]*?celebrada el\s+'
                     r'(\d{1,2}) de ([a-záéíóú]+) de (\d{4}))\s*<', re.I)

# Bloque de firmas y pie que se repiten en cada página de las actas firmadas (XI).
RUIDO_RE = re.compile(r"^(LA|EL) (PRESIDENT[AE]|SECRETARI[AO] PRIMER[AO]|LETRAD[AO]-SECRETARI[AO] GENERAL)\b|"
                      r"\d\d/\d\d/\d{4} \d\d:\d\d$|^(FIRMADO POR\s*)+$|^ASAMBLEA REGIONAL DE MURCIA$|"
                      r"^Código Seguro de Verificación|^Acta Pleno n|^La comprobación de la autenticidad|"
                      r"^Pág\. \d+ de \d+$|^\d{1,3}$")


def _html(ctx, url, caduca):
    return ctx.fetch(url, inseguro=True, cache=f"{CUERPO}/listados/{Contexto.clave(url)}.html",
                     caduca_dias=caduca).decode("utf-8", "replace")


def _legislaturas(ctx):
    """[(número, url de la carpeta)] de la más reciente a la más antigua."""
    vistas = {}
    for href, ordinal, _ini, _fin in CARPETA_RE.findall(_html(ctx, RAIZ, 1)):
        n = ORDINALES.get(urllib.parse.unquote(ordinal).lower())
        if n in CUERPOS[0].legislaturas and n not in vistas:
            vistas[n] = BASE + href
    return sorted(vistas.items(), reverse=True)


def _listado(ctx):
    """Documento de cada acta del Pleno, de la más reciente a la más antigua, respetando ctx.desde."""
    desde = ctx.desde(CUERPO, margen_dias=45)  # el acta se firma semanas después de la sesión
    ultima = max(CUERPOS[0].legislaturas)
    for leg, url in _legislaturas(ctx):
        cerrada = leg != ultima
        anios = sorted({(int(a), BASE + h) for h, a in ANIO_RE.findall(_html(ctx, url, 30 if cerrada else 1))},
                       reverse=True)
        for anio, url_anio in anios:
            if desde and anio < int(desde[:4]):
                return
            filas = ACTA_RE.findall(_html(ctx, url_anio, 30 if cerrada or anio < date.today().year else 0.5))
            for href, titulo, sesion, dia, mes, a in filas:
                if mes.lower() not in MESES:
                    continue
                fecha = f"{a}-{MESES[mes.lower()]:02d}-{int(dia):02d}"
                if desde and fecha < desde:
                    continue
                yield Documento(CUERPO, fecha, urllib.parse.urljoin(BASE, href), sesion=int(sesion), formato="pdf",
                                idioma="es", titulo=re.sub(r"\s+", " ", titulo), legislatura=leg)


SELLO_RE = re.compile(r"^Acta\s+sesi[oó]n\s+plenaria.*SEFYCU|^MURCIA$", re.I)
# la relación de asistentes (al margen del texto, en columna aparte) que el flujo del PDF intercala
# tras el sello de cada página: un nombre por línea, siempre con «Don»/«Doña» en mayúscula inicial (en
# el cuerpo del acta, «don»/«doña» va en minúscula salvo al empezar frase), o el rótulo de un cargo.
ASISTENTE_RE = re.compile(
    r"^(?:Do[ñn]a?|D\.ª)\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑñ.'’-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑñ.'’-]*){0,5}\s*[.,]?$|"
    r"^(?:Presidenta|Presidente|Vicepresidentas?|Vicepresidentes?|Secretarias?(?:\s+[12ªº]\S*)?|"
    r"Secretarios?(?:\s+[12ºª]\S*)?|Asistentes|Se[ñn]ores?\s+asistentes|Miembros\s+del\s+[oó]rgano|"
    r"Miembros\s+del\s+Consejo\s+de\s+Gobierno)\s*:?\s*$", re.I)
NOMBRE_FIRMA_RE = re.compile(
    r"^[A-ZÁÉÍÓÚÑ][a-záéíóúñ'’-]+(?:\s+(?:de|del|la|las|los|[A-ZÁÉÍÓÚÑ][a-záéíóúñ'’-]+)){1,5}$")
# palabras que nunca son parte del nombre de quien firma cada página (para no confundirlo con un grupo,
# un órgano o una institución que se repita varias veces en el acta)
NO_FIRMA_RE = re.compile(r"Grupo|Parlamentari|Consejo|Gobierno|Asamblea|Regi[oó]n|Comisi[oó]n|Mesa|C[aá]mara", re.I)


def _es_firma_repetida(linea, frecuencia):
    return bool(linea) and frecuencia[linea] >= 3 and not NO_FIRMA_RE.search(linea) and bool(NOMBRE_FIRMA_RE.match(linea))


def texto(ctx, doc):
    """Texto del acta sin el pie de página ni las firmas. Las actas firmadas digitalmente (XI
    legislatura) repiten en cada página el sello «FIRMADO POR... » y el nombre de quien firma
    (Presidencia, Secretarías), que el flujo del PDF intercala en mitad de frases («votos en contra»
    puede quedar partido por el sello de una página); se quitan por su propio patrón (RUIDO_RE, el
    rótulo del acta y «MURCIA» sueltos) y, lo que quede, por repetirse igual varias veces en el
    documento sin ser el nombre de un grupo ni de un órgano. El PDF se pide sin verificar el
    certificado (la web lo tiene roto)."""
    pdf = ctx.fetch(doc.url, inseguro=True, cache=f"{CUERPO}/docs/{Contexto.clave(doc.url)}.pdf")
    brutas = [l for l in Contexto.pdf_texto(pdf, layout=False).split("\n")
              if not RUIDO_RE.search(l.strip()) and not SELLO_RE.search(l.strip())
              and not ASISTENTE_RE.match(l.strip())]
    frecuencia = Counter(l.strip() for l in brutas)
    lineas = [l for l in brutas if not _es_firma_repetida(l.strip(), frecuencia)]
    return re.sub(r"\n\s*\n+", "\n\n", "\n".join(lineas)).strip()


def _en_cache(url):
    return (CACHE_DIR / CUERPO / "docs" / f"{Contexto.clave(url)}.pdf.gz").exists()


# ---------------------------------------------------------------- números en letra

UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "ningun": 0, "ninguno": 0, "ninguna": 0,
}
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}

NUM = (r"(\d{1,2}"
       r"|ning[uú]n[ao]?|cero"
       r"|un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve"
       r"|diez|once|doce|trece|catorce|quince"
       r"|dieci(?:s[eé]is|siete|ocho|nueve)"
       r"|veinte|veinti(?:[uú]n[oó]?|d[oó]s|tr[eé]s|cuatro|cinco|s[eé]is|siete|ocho|nueve)"
       r"|(?:treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)"
       r"(?:\s+y\s+(?:un[oa]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve))?"
       r")")


def _plano(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _entero(s):
    if s is None:
        return None
    p = _plano(s).strip()
    if p.isdigit():
        return int(p)
    m = re.match(r"^(treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)(?:\s+y\s+(\w+))?$", p)
    if m:
        return DECENAS[m.group(1)] + (UNIDADES.get(m.group(2), 0) if m.group(2) else 0)
    return UNIDADES.get(p)


# ---------------------------------------------------------------- texto corrido

def _aplanar(texto_acta):
    """Una sola línea de texto: une las palabras que el PDF partió a final de línea («mo-\\ndificación») y
    cambia por espacios las barras que el escaneado mete donde el original partía una línea («votos/ a favor»)."""
    partes = []
    for ln in texto_acta.replace("\f", "\n").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if partes and partes[-1].endswith("-") and ln[:1].islower():
            partes[-1] = partes[-1][:-1] + ln
        else:
            partes.append(ln)
    t = " ".join(partes).replace("/", " ")
    return re.sub(r"\s+", " ", t).strip()


ABREV_RE = re.compile(r"\b(?:Sr|Sra|Sres|D|D[ñn]a|Dr|Dra|G\.?P|N|N[ºo°]|art|p[aá]g|n[uú]m)\.$", re.I)


def _fin_frase(t, desde):
    i = desde
    while True:
        m = re.search(r"\.(?=\s|$)", t[i:])
        if not m:
            return len(t)
        j = i + m.end()
        if not ABREV_RE.search(t[:j]):
            return j
        i = j


def _inicio_frase(t, hasta):
    corte = 0
    for m in re.finditer(r"\.(?=\s)", t[:hasta]):
        j = m.end()
        if not ABREV_RE.search(t[:j]):
            corte = j
    return corte


# ---------------------------------------------------------------- puntos del orden del día

PALABRAS_INICIATIVA = (r"MOCI[OÓ]N|PROPOSICI[OÓ]N|PROYECTO\s+DE\s+LEY|INTERPELACI[OÓ]N|COMPARECENCIA|"
                       r"DESIGNACI[OÓ]N|ELECCI[OÓ]N|DEBATE|CONVALIDACI[OÓ]N|DECRETO[- ]LEY|PRESUPUESTOS?|"
                       r"DICTAMEN|TOMA\s+EN\s+CONSIDERACI[OÓ]N|AMPLIACI[OÓ]N|CREACI[OÓ]N|REGLAMENTO|CENSURA|"
                       r"CONFIANZA|INVESTIDURA|NOMBRAMIENTO|ACUERDO|INFORME|CUENTA\s+GENERAL|MODIFICACI[OÓ]N|"
                       r"RATIFICACI[OÓ]N|DECLARACI[OÓ]N|PREGUNTA")
MARCADOR_RE = re.compile(
    r"(?:^|(?<=[.\):]\s))(?:(?P<num>\d{1,2})\.-\s*|(?P<rom>[IVXLCM]{1,6})\.-?\s*(?=[A-ZÁÉÍÓÚÑ0-9])|"
    r"(?:ASUNTO\s+)?(?P<unico>[UÚ]NICO)\s*\.-?\s*)")
EXPEDIENTE_ITEM_RE = re.compile(r"(\d{1,2}L)\s+([A-Z][A-Z0-9]{1,7}-\d{2,5})\b")
REGISTRO_RE = re.compile(r"\(N[º°.o]*\s*(?:DE\s+)?REGISTRO[^)]*\)\s*\.?", re.I)
FIN_ASUNTOS_RE = re.compile(r"\bno\s+habiendo\s+m[aá]s\s+asuntos\b|\bse\s+levant[oó]\s+la\s+sesi[oó]n\b", re.I)

_MINUSCULAS_NOMBRE = {"de", "del", "la", "las", "los", "y", "el", "al", "en"}


def _normaliza_nombre(s):
    palabras = s.strip().lower().split()
    out = []
    for i, p in enumerate(palabras):
        if i > 0 and p in _MINUSCULAS_NOMBRE:
            out.append(p)
        else:
            out.append("-".join(t[:1].upper() + t[1:] for t in p.split("-") if t))
    return " ".join(out)


PREFIJO_TITULO_RE = re.compile(
    r"^(?:MOCI[OÓ]N(?:\s+EN\s+PLENO)?|INTERPELACI[OÓ]N(?:\s+EN\s+PLENO)?)\s+SOBRE\s+", re.I)


def _titulo_legible(cabecera):
    t = REGISTRO_RE.sub("", cabecera).strip(" .,")
    resto = PREFIJO_TITULO_RE.sub("", t, count=1)
    base = resto if len(resto) > 12 else t
    base = base.lower().strip(" .,")
    return (base[:1].upper() + base[1:]) if base else t


AUTOR_ITEM_RE = re.compile(
    r"FORMULAD[AO]S?\s+POR\s+(?:EL\s+|LA\s+|LOS\s+|LAS\s+)?(?:D\.?[^,]*?,\s*DEL\s+)?"
    r"(?:GRUPOS?\s+PARLAMENTARIOS?|G\.?\s*P\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9'’\.\- ]*?)(?=\s*\(|\s*\.|$)", re.I)

TIPOS_TITULO = (
    ("investidura", r"investidura|mo[cç]i[oó]n\s+de\s+censura|cuesti[oó]n\s+de\s+confianza"),
    ("pnl", r"proposici[oó]n\s+no\s+de\s+ley"),
    ("ppl", r"proposici[oó]n\s+de\s+ley"),
    ("pl", r"proyecto\s+de\s+ley"),
    ("ilp", r"iniciativa\s+legislativa\s+(?:popular|municipal)"),
    ("dl", r"decreto[- ]ley"),
    ("presupuesto", r"presupuestos?\s+(?:generales|de\s+la\s+comunidad)"),
    ("mocion", r"\bmoci[oó]n\b"),
    ("control", r"pregunta|interpelaci[oó]n|comparecencia|propuestas?\s+de\s+resoluci[oó]n|"
               r"debate\s+general\s+sobre|cuenta\s+general|informe\s+(?:anual|sobre)"),
    ("organizacion", r"designaci[oó]n|elecci[oó]n|nombramiento|creaci[oó]n\s+de\s+(?:la\s+|una\s+)?comisi[oó]n|"
                     r"reglamento\s+de\s+la\s+c[aá]mara|reforma\s+del\s+reglamento|toma\s+de\s+posesi[oó]n"),
    ("acuerdo", r"declaraci[oó]n\s+institucional|dictamen|propuesta\s+de\s+acuerdo"),
)


def _tipo_iniciativa(texto_item):
    p = texto_item or ""
    for tipo, patron in TIPOS_TITULO:
        if re.search(patron, p, re.I):
            return tipo
    return "otro"


def _valido_epigrafe(resto):
    cabeza = resto[:220]
    return bool(EXPEDIENTE_ITEM_RE.match(cabeza) or re.search(PALABRAS_INICIATIVA, cabeza[:200], re.I))


def _epigrafes(flat):
    """[(posición, titulo, expediente, autor, tipo)] de los puntos del orden del día, en orden."""
    fin_texto = len(flat)
    m_fin = FIN_ASUNTOS_RE.search(flat)
    if m_fin:
        fin_texto = m_fin.start()
    out = []
    for m in MARCADOR_RE.finditer(flat, 0, fin_texto):
        resto = flat[m.end():m.end() + 600]
        if not _valido_epigrafe(resto):
            continue
        cabecera = resto[:_fin_bruta(resto)]
        me = EXPEDIENTE_ITEM_RE.match(cabecera)
        expediente = f"{me.group(1)}/{me.group(2)}" if me else None
        cabecera_titulo = cabecera[me.end():] if me else cabecera
        ma = AUTOR_ITEM_RE.search(cabecera)
        autor = _normaliza_nombre(ma.group(1)) if ma else None
        if autor:
            autor = f"Grupo Parlamentario {autor}"
        titulo = _titulo_legible(cabecera_titulo)
        tipo = _tipo_iniciativa(cabecera)
        out.append((m.start(), titulo, expediente, autor, tipo))
    return out


def _fin_bruta(resto, maximo=450):
    """Dónde acaba la cabecera de un punto: en el «(Nº registro ...).», o si no, en el primer punto real."""
    s = resto[:maximo]
    m = re.search(r"\(N[º°.o]*\s*(?:DE\s+)?REGISTRO[^)]*\)\s*\.", s, re.I)
    if m:
        return m.end()
    for mm in re.finditer(r"\.(?=\s|$)", s):
        if not ABREV_RE.search(s[:mm.end()]):
            return mm.end()
    return len(s)


def _item_de(items, pos):
    elegido = None
    for p, *resto in items:
        if p <= pos:
            elegido = resto
        else:
            break
    return elegido


# ---------------------------------------------------------------- grupos por votación

GRUPO_PLAIN_RE = re.compile(
    r"Grupos?\s+Parlamentarios?\s+(.+?)(?=$|;|\.\s|\.$|\s*(?:,\s*)?(?:y\s+)?(?:Sr|Sra|Sres)\.?\s)", re.I)
ADJUNTO_RE = re.compile(
    r"(?:Sr|Sra|Sres)\.?\s+[^,()]+?,\s+del\s+Grupos?\s+Parlamentarios?\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ'’-]*)", re.I)


def _lista_nombres(s):
    partes = re.split(r"\s*,\s*y\s+|\s*,\s*|\s+y\s+(?=[A-ZÁÉÍÓÚÑ])", s.strip())
    out = []
    for p in partes:
        p = re.sub(r"^y\s+|\s+y$", "", p.strip(" .")).strip()
        if p:
            out.append(p)
    return out


GRUPO_PREFIJO_RE = re.compile(r"^grupos?\s+parlamentarios?\s+", re.I)
# Grupos de la IX a la XI (una legislatura nueva puede traer otros). Las actas escaneadas los escriben con
# ruido («Soplalista», «Mixfco», «Vo^») o pegados sin coma («Popular Socialista»).
GRUPOS_ARM = {"popular": "Popular", "socialista": "Socialista", "podemos": "Podemos",
              "ciudadanos": "Ciudadanos-Partido de la Ciudadanía", "vox": "Vox", "mixto": "Mixto"}
# un paréntesis que el OCR no cierra se come el recuento siguiente («Mixto y veinte en contra (Grupos
# Parlamentarios Popular…»): de ahí en adelante son los grupos de otro sentido
OTRO_RECUENTO_RE = re.compile(r"\b(?:en\s+contra|a\s+favor|abstenci)", re.I)


def _grupo_arm(texto, corte):
    parecido = difflib.get_close_matches(texto, GRUPOS_ARM, n=1, cutoff=corte)
    return parecido[0] if parecido else None


def _grupos_arm(nombre):
    """Grupos de la Asamblea que nombra un trozo del acta: los que se parecen palabra a palabra o, si no hay
    ninguno, el que se parece a todo junto («Social i s1 'a»). Personas y trozos de frase no dan ninguno."""
    if re.search(r"\bno\s+particip", nombre, re.I):  # «(El Grupo Parlamentario Mixto no participa en la votación)»
        return []
    plano = re.sub(r"partido\s+de\s+la\s+ciudadan\w*", " ", _plano(nombre))
    claves = [c for c in (_grupo_arm(p, 0.8) for p in re.findall(r"[a-z]{2,}", plano)) if c]
    if not claves:
        claves = [c for c in [_grupo_arm(re.sub(r"[^a-z]", "", plano), 0.66)] if c]
    return [GRUPOS_ARM[c] for c in dict.fromkeys(claves)]


def _entidades(parte):
    """Nombres de grupo implicados en un paréntesis de resultado («Grupos Parlamentarios X, Y y Sr. Z, del
    Grupo Parlamentario Mixto»): los grupos citados enteros y los grupos de las personas citadas a título
    individual (siempre del Grupo Mixto, que no vota en bloque). Lo que no se reconoce como un grupo
    («excepto Sra. X», el nombre de una persona) se descarta en vez de forzarlo."""
    ents = set()
    m = GRUPO_PLAIN_RE.search(parte or "")
    if m:
        for nombre in _lista_nombres(m.group(1)):
            if OTRO_RECUENTO_RE.search(nombre):
                break
            if not (2 < len(nombre) < 60) or not nombre[:1].isupper() or re.search(r"\bexcepto\b", nombre, re.I):
                continue
            ents.update(f"Grupo Parlamentario {g}" for g in _grupos_arm(GRUPO_PREFIJO_RE.sub("", nombre)))
    for gm in ADJUNTO_RE.finditer(parte or ""):
        ents.update(f"Grupo Parlamentario {g}" for g in _grupos_arm(gm.group(1)))
    return ents


def _voto_grupos(favor, contra, abst):
    conteo = {}
    for sentido, ents in (("si", favor), ("no", contra), ("abstencion", abst)):
        for e in ents:
            conteo.setdefault(e, set()).add(sentido)
    return [VotoGrupo(g, sentido=next(iter(s)) if len(s) == 1 else "dividido") for g, s in conteo.items()]


# ---------------------------------------------------------------- recuentos

FAVOR_RE = re.compile(NUM + r"s?\s+(?:votos?\s+)?a\s+favor\s*(?:\(([^)]*)\))?", re.I)
# la Presidencia no siempre repite «votos» en la segunda cifra: «... a favor, ninguno en contra y...»
CONTRA_RE = re.compile(NUM + r"s?\s+(?:votos?\s+)?en\s+contra\s*(?:\(([^)]*)\))?", re.I)
ABST_RE = re.compile(NUM + r"s?\s+abstenci(?:[oó]n|ones)\s*(?:\(([^)]*)\))?", re.I)
RESULT_WORD_RE = re.compile(r"\b(aprobad[oa]s?|rechazad[oa]s?|desestimad[ao]s?)\b", re.I)
EMPATE_RE = re.compile(r"\bempate\b", re.I)
VERBO_RE = re.compile(r"\b(?:es|son|resulta|resultan|queda|quedan)\b", re.I)
UNANIME_RE = re.compile(r"\bunanimidad\b|\basentimiento\b", re.I)
AUTOR_VOTO_RE = re.compile(
    r"(?:del|de\s+la|presentad[ao]\s+por(?:\s+el|\s+la)?|(?<!\w)por(?:\s+el|\s+la)?)\s+"
    r"Grupos?\s+Parlamentarios?\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ'’-]*(?:\s+(?:de|del|la|las|los)\s+"
    r"[\wÁÉÍÓÚÑñ'’-]+)*)", re.I)

LEAD_RE = re.compile(
    r"^(?:Sometid[ao]s?\s+a\s+votaci[oó]n(?:\s+conjunta)?,?\s*|"
    r"Votad[ao]s?\s+(?:nuevamente\s+|de\s+nuevo\s+)?|"
    r"Efectuada\s+la\s+votaci[oó]n(?:\s+de)?,?\s*|"
    r"Realizada\s+la\s+(?:tercera\s+(?:y\s+[uú]ltima\s+)?)?votaci[oó]n(?:\s+de)?,?\s*|"
    r"Realizado\s+el\s+c[oó]mputo[^,]*,?\s*|"
    r"A\s+continuaci[oó]n,?\s*(?:se\s+vota[n]?\s*)?|"
    r"Seguidamente,?\s*(?:se\s+vota[n]?\s*)?|"
    r"En\s+primer\s+lugar\s+se\s+somete[n]?\s+a\s+votaci[oó]n(?:\s+conjunta)?\s*|"
    r"Se\s+inicia(?:\s+este\s+punto)?(?:\s+con\s+la\s+votaci[oó]n\s+conjunta\s+de)?\s*|"
    r"Procede[^,]*?realizar\s+)+", re.I)


TRAIL_RE = re.compile(
    r",?\s*(?:que\s+tambi[eé]n|que\s+asimismo|que|tambi[eé]n|en\s+votaci[oó]n|sometida?\s+a\s+votaci[oó]n|\by)\s*$",
    re.I)


def _limpia_sujeto(bruto):
    s = LEAD_RE.sub("", bruto.strip(" ,"))
    s = re.sub(r"\s+", " ", s).strip(" ,")
    for _ in range(3):
        t = TRAIL_RE.sub("", s).strip(" ,")
        if t == s:
            break
        s = t
    return s or None


def _sujeto_y_resultado(flat, ini_frase, fin_pos_trigger, fin_frase, empate_forzado=False):
    """(sujeto, resultado, empate) de la frase que rodea una lectura de resultado."""
    ventana = flat[ini_frase:fin_frase]
    rs = list(RESULT_WORD_RE.finditer(ventana))
    resultado = None
    if rs:
        resultado = "aprobada" if rs[-1].group(1).lower().startswith("aprobad") else "rechazada"
    empate = empate_forzado or bool(EMPATE_RE.search(ventana))
    verbos = list(VERBO_RE.finditer(flat, ini_frase, fin_pos_trigger))
    sujeto_fin = verbos[-1].start() if verbos else fin_pos_trigger
    sujeto = _limpia_sujeto(flat[ini_frase:sujeto_fin])
    return sujeto, resultado, empate


def _lecturas_recuento(flat):
    """[(inicio, fin, a_favor, en_contra, abstenciones, sujeto, resultado, empate, grupos)] en orden."""
    out = []
    consumido_hasta = 0
    for mf in FAVOR_RE.finditer(flat):
        if mf.start() < consumido_hasta:
            continue
        mc = CONTRA_RE.search(flat, mf.end(), mf.end() + 180)
        tras_contra = mc.end() if mc else mf.end()
        ma = ABST_RE.search(flat, tras_contra, tras_contra + 180)
        fin_tally = ma.end() if ma else tras_contra
        ini_frase = _inicio_frase(flat, mf.start())
        fin_frase = _fin_frase(flat, fin_tally)
        sujeto, resultado, empate = _sujeto_y_resultado(flat, ini_frase, mf.start(), fin_frase)
        a_favor = _entero(mf.group(1))
        en_contra = _entero(mc.group(1)) if mc else None
        abstenciones = _entero(ma.group(1)) if ma else None
        favor_e = _entidades(mf.group(2))
        contra_e = _entidades(mc.group(2)) if mc else set()
        abst_e = _entidades(ma.group(2)) if ma else set()
        grupos = _voto_grupos(favor_e, contra_e, abst_e)
        out.append((ini_frase, fin_frase, a_favor, en_contra, abstenciones, sujeto, resultado, empate, grupos))
        consumido_hasta = fin_frase
    return out


def _lecturas_unanimidad(flat, ocupado):
    out = []
    for mu in UNANIME_RE.finditer(flat):
        if any(a <= mu.start() < b for a, b in ocupado):
            continue
        ini_frase = _inicio_frase(flat, mu.start())
        fin_frase = _fin_frase(flat, mu.end())
        ventana = flat[ini_frase:fin_frase]
        if re.search(r"rechazad[oa]s?|desestimad[oa]s?", ventana, re.I):
            continue  # «no se aprueba por asentimiento»: no llega a darse (raro, pero por si acaso)
        verbos = list(VERBO_RE.finditer(flat, ini_frase, mu.start()))
        sujeto_fin = verbos[-1].start() if verbos else mu.start()
        sujeto = _limpia_sujeto(flat[ini_frase:sujeto_fin])
        out.append((ini_frase, fin_frase, sujeto))
    return out


# ---------------------------------------------------------------- señal de que se vota (para documentos())

SENAL_RE = re.compile(
    r"votos?\s+a\s+favor|votos?\s+en\s+contra|abstenci[oó]n(?:es)?|por\s+unanimidad|\bempate\b|"
    r"votaci[oó]n\s+nominal|votos?\s+emitidos", re.I)


# ---------------------------------------------------------------- Votacion

TIPO_VOTACION_RE = (
    ("totalidad", r"enmienda[s]?\s+de\s+totalidad|enmienda\s+a\s+la\s+totalidad"),
    ("enmiendas", r"enmienda"),
    ("toma_consideracion", r"toma\s+(?:en|de)\s+consideraci[oó]n"),
    ("control", r"propuesta[s]?\s+de\s+resoluci[oó]n"),
    ("articulado", r"\bpunto|\bart[ií]culo|articulado|disposici[oó]n"),
)


def _tipo_votacion(tipo, sujeto, titulo):
    if tipo == "investidura":
        return "investidura"
    t = f"{sujeto or ''} {titulo or ''}"
    for clave, patron in TIPO_VOTACION_RE:
        if re.search(patron, t, re.I):
            return clave
    if tipo == "dl":
        return "convalidacion"
    if tipo in ("pnl", "mocion", "control"):
        return tipo
    if tipo in ("pl", "ppl", "presupuesto"):
        return "conjunto"
    if tipo == "organizacion":
        return "nombramiento" if re.search(r"elecci[oó]n|designaci[oó]n|nombramiento", t, re.I) else "organizacion"
    return None


def _ficha_voto(doc, item, sujeto):
    """(titulo, subtitulo, expediente, tipo_iniciativa, tipo_votacion, autor) comunes a una votación."""
    titulo, expediente, autor_item, tipo = item if item else (doc.titulo or "Pleno", None, None, "otro")
    autor = autor_item
    ma = AUTOR_VOTO_RE.search(sujeto or "")
    if ma:
        autor = f"Grupo Parlamentario {_normaliza_nombre(ma.group(1))}"
    subtitulo = sujeto if sujeto and _plano(sujeto) != _plano(titulo) else None
    return titulo, subtitulo, expediente, tipo, _tipo_votacion(tipo, sujeto, titulo), autor


def _votacion(doc, item, n, a_favor, en_contra, abstenciones, sujeto, resultado, empate, grupos):
    titulo, subtitulo, expediente, tipo, tipo_votacion, autor = _ficha_voto(doc, item, sujeto)
    extra = {}
    if empate:
        extra["empate"] = True
    escanos = CUERPOS[0].escanos_de(doc.legislatura)
    if sum(x or 0 for x in (a_favor, en_contra, abstenciones)) > escanos:
        extra["totales_descartados"] = f"{a_favor}-{en_contra}-{abstenciones}"
        a_favor = en_contra = abstenciones = None
    if resultado and a_favor is not None and en_contra is not None and (resultado == "aprobada") != (a_favor > en_contra):
        extra["resultado_no_cuadra"] = resultado
        resultado = None
    return Votacion(
        cuerpo=CUERPO, fecha=doc.fecha, sesion=doc.sesion, numero=n, legislatura=doc.legislatura, titulo=titulo,
        subtitulo=subtitulo, expediente=expediente, tipo_iniciativa=tipo, tipo_votacion=tipo_votacion, autor=autor,
        a_favor=a_favor, en_contra=en_contra, abstenciones=abstenciones, resultado=resultado, grupos=grupos,
        url=doc.url, fuente="pdf-reglas", extra=extra)


def _votacion_unanime(doc, item, n, sujeto):
    titulo, subtitulo, expediente, tipo, tipo_votacion, autor = _ficha_voto(doc, item, sujeto)
    return Votacion(
        cuerpo=CUERPO, fecha=doc.fecha, sesion=doc.sesion, numero=n, legislatura=doc.legislatura, titulo=titulo,
        subtitulo=subtitulo, expediente=expediente, tipo_iniciativa=tipo, tipo_votacion=tipo_votacion, autor=autor,
        asentimiento=True, resultado="aprobada", url=doc.url, fuente="pdf-reglas", extra={})


def _votos_de_acta(ctx, doc):
    """([Votacion], ¿hay señal de que se vota?) de un acta."""
    texto_acta = texto(ctx, doc)
    flat = _aplanar(texto_acta)
    # un acta escaneada sin capa de OCR legible da un texto casi vacío: no se sabe si hay votos, así que
    # se manda igualmente a documentos() en vez de darla calladamente por sin votar
    senal = len(flat) < 300 or bool(SENAL_RE.search(flat))
    if not senal or doc.legislatura is None:
        return [], senal
    items = _epigrafes(flat)
    recuentos = _lecturas_recuento(flat)
    unanimes = _lecturas_unanimidad(flat, [(a, b) for a, b, *_ in recuentos])
    eventos = [(r[0], "recuento", r[2:]) for r in recuentos]
    eventos += [(a, "unanime", (sujeto,)) for a, b, sujeto in unanimes]
    eventos.sort(key=lambda e: e[0])
    votos, n = [], 0
    for pos, tipo_evento, datos in eventos:
        item = _item_de(items, pos)
        n += 1
        if tipo_evento == "recuento":
            a_favor, en_contra, abstenciones, sujeto, resultado, empate, grupos = datos
            votos.append(_votacion(doc, item, n, a_favor, en_contra, abstenciones, sujeto, resultado, empate, grupos))
        else:
            (sujeto,) = datos
            votos.append(_votacion_unanime(doc, item, n, sujeto))
    return votos, senal


_ANALISIS = {}


def _analisis(ctx, doc):
    if doc.url not in _ANALISIS:
        _ANALISIS[doc.url] = _votos_de_acta(ctx, doc)
    return _ANALISIS[doc.url]


# ---------------------------------------------------------------- descargar() y documentos()

def descargar(ctx):
    n_total, iniciativas = 0, set()
    for doc in _listado(ctx):
        try:
            votos, _senal = _analisis(ctx, doc)
        except Exception as e:  # PDF roto, web caída puntual...
            ctx.log(f"  ! {CUERPO}: {doc.url} no se pudo leer ({type(e).__name__}: {e})")
            continue
        for v in votos:
            if v.expediente and (v.legislatura, v.expediente) not in iniciativas and v.titulo:
                iniciativas.add((v.legislatura, v.expediente))
                yield Iniciativa(CUERPO, v.expediente, v.titulo, legislatura=v.legislatura,
                                 tipo_iniciativa=v.tipo_iniciativa, autor=v.autor, url=v.url)
            yield v
            n_total += 1
            if ctx.limite and n_total >= ctx.limite:
                return


RECIENTES = 15  # actas que documentos() mira aunque no estén en caché, para un runner sin caché (Actions)


def documentos(ctx):
    """Actas del Pleno en las que el texto muestra que se vota pero las reglas no leen ninguna votación (para
    el LLM): investiduras con llamamiento nominal, designaciones por papeleta secreta y días en que el ruido
    del escaneado (IX y X legislaturas) estropea el recuento."""
    n = 0
    for i, doc in enumerate(_listado(ctx)):
        if not (i < RECIENTES or _en_cache(doc.url)):
            continue
        try:
            votos, senal = _analisis(ctx, doc)
        except Exception as e:
            ctx.log(f"  ! {CUERPO}: {doc.url} no se pudo leer ({type(e).__name__}: {e})")
            continue
        if votos or not senal:
            continue
        yield doc
        n += 1
        if ctx.limite and n >= ctx.limite:
            return
