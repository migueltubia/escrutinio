"""Pleno del Ayuntamiento de Córdoba: votaciones sacadas con reglas del extracto de acuerdos en PDF.

Fuente: la oficina virtual de actas (https://oficinavirtual.cordoba.es/actas, la misma plataforma
«Audio Vídeo Actas» de eCityclic que Málaga; ver _videoactas.py). El buscador filtrado por el
órgano «Pleno Municipal» lista las sesiones desde 2012 (con el número oficial en el título: «Sesión
18/25 Pl Ordinaria…»); desde 2026 mete ahí también las comisiones permanentes («C.P. …»), que se
descartan. La ficha de cada sesión enlaza el «Extracto de pleno» (desde 2015, a los pocos días de la
sesión) y el acta (unos meses después; en 2012-2014 es el único documento). Los dos tienen el mismo
formato: cada acuerdo lleva su número oficial («N.º 308/25.- PERSONAL.- 3. DICTAMEN …») y la
votación en una frase muy regular:

    Sometido el asunto a votación, el Excmo. Ayuntamiento Pleno por mayoría de 26 votos a favor de
    los representantes de los grupos municipales Popular (15), Socialista (7) y Hacemos Córdoba (4),
    y 3 abstenciones de los representantes del grupo municipal VOX, adoptó los siguientes ACUERDOS…

Además se leen las votaciones de enmiendas y de reclamaciones dentro de un acuerdo («La Enmienda
n.º 3 del grupo municipal VOX es rechazada por mayoría de …»). De ahí salen los totales, el voto de
cada grupo con su número de concejales y el resultado.

El conjunto de datos «Pleno municipal – acuerdos» de datosabiertos.cordoba.es (CKAN, un paquete por
año) no sirve: solo trae unos pocos certificados de acuerdos sueltos en PDF, sin votaciones.

Cobertura: Pleno desde junio de 2012 (mandatos IX a XII), unas 335 sesiones.
Claves: sesion = número oficial de la sesión en el año («18/25» -> 18); numero = 100 × orden del
acuerdo en el documento + n.º de la votación dentro del acuerdo (0 si solo hay una). El número
oficial del acuerdo («308/25») va en extra.
Limitaciones: la unanimidad casi nunca detalla los grupos ni el número de presentes: va sin totales
y con asentimiento. Los títulos están en mayúsculas, como en el documento. No se recogen las
declaraciones de urgencia, las ratificaciones de inclusión en el orden del día ni las peticiones
de retirada. Las abstenciones «así consideradas» (concejal ausente en la votación) suman en el
total pero no llevan grupo. Si una frase da más votos que concejales (erratas), la votación se queda
solo con el resultado. Algunos PDF son imágenes sin texto: si es el extracto (o su descarga falla,
error 500 en dos sesiones de 2021) se usa el acta; cuatro actas de 2013-2014 sin extracto se saltan.
Para una revisión con LLM, `documentos` da un PDF por sesión (el extracto si lo hay).
"""

import re
import urllib.error
from datetime import date, timedelta

from ...territorio import MANDATOS_LOCALES, Cuerpo, num_municipio
from ..contexto import ErrorDescarga
from ..modelo import Documento, Votacion, VotoGrupo
from . import _videoactas as ava

CUERPO = "ayto-cordoba"
BASE = "https://oficinavirtual.cordoba.es/actas"
ORGANO_PLENO = "8ad081674960ec6d014960ec80d1000e"  # «Pleno Municipal» en el buscador (se relee del formulario)
MARGEN_ACTAS = 30  # días de más al recoger por incremental: el extracto tarda unos días en salir

CUERPOS = [
    Cuerpo(CUERPO, num_municipio("14021"), "Ayuntamiento de Córdoba", "Ayto. Córdoba", "municipal", "AN", 29,
           dict(MANDATOS_LOCALES), web="https://oficinavirtual.cordoba.es/actas/"),
]

NOTAS = ("Extracto de acuerdos del Pleno (o el acta) en PDF de la oficina virtual, leído con reglas: totales, voto "
         "por grupo con número de concejales, resultado y enmiendas. Desde 2012. La unanimidad va sin totales "
         "(asentimiento). El dataset CKAN de acuerdos solo tiene certificados sueltos.")

NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
           "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
           "dieciséis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20}
NUM = r"(\d+|" + "|".join(sorted(NUMEROS, key=len, reverse=True)) + r")"

# «N.º 308/25.- PERSONAL.- 3. DICTAMEN …»
ACUERDO_RE = re.compile(r"N\s*\.?\s*[º°o]\s*(\d{1,4})\s*/\s*(\d{2})\s*\.\s*-?\s*(?=[A-ZÁÉÍÓÚÑ“\"(])")
SESION_RE = re.compile(r"Sesi[oó]n\s+(?:Ordinaria\s+|Extraordinaria\s+(?:y\s+Urgente\s+)?)?0*(\d{1,2})\s*/\s*(\d{2})\b", re.I)
FRASE_RE = re.compile(r"[.:;][”\"»]?\s|[.:;]?[”»\"](?=[A-ZÁÉÍÓÚ¿¡])|\.-\s*|\.(?=[A-ZÁÉÍÓÚ][a-záéíóú])|\]\s*\.?\s*")
PIE_RE = re.compile(r"\b\d{1,3}\s+de\s+\d{1,3}\b")  # «2 de 46», pie de página
# Arranque del recuento: «por mayoría de 26 votos…», «por unanimidad», «por 15 votos…»
ANCLA_RE = re.compile(r"\bpor\s+(?:(?:la\s+)?mayor[ií]a\s+(?:absoluta\s+)?(?:de\s+)?)?(?=" + NUM + r"\s+votos?|unanimidad)", re.I)
# Sentido del voto, con número o sin él («y los votos a favor de los grupos…»), y con las erratas habituales
# («15 votos a de los…» por «a favor», «votos a en contra»).
TOKEN_RE = re.compile(NUM[:-1] + r"|los|las|la|el)\s+(votos?\s+(?:a\s+)?favor|votos?\s+(?:a\s+)?en\s+contra|"
                      r"votos?\s+de\s+abstenci[oó]n|abstenci[oó]n(?:es)?|votos?\s+a(?=\s+(?:de|del)\s))\b", re.I)
FIN_CLAUSULA_RE = re.compile(r"\s*,?\s*(?:ACUERDA|acuerda|adopt|acord|aprob|resultando|que\s+result|decayendo|rechaz|"
                             r"desestim|estim|queda|toma|ratific|y\s+en\s+consecuencia|debiendo|"
                             r"por\s+(?:lo\s+)?tanto|por\s+lo\s+que|siendo)|"
                             r"(?<!\bart)(?<!\bSr)(?<!\bSra)(?<!\bD)(?<!\bn)(?<!Excmo)(?<!Ilmo)"
                             r"\.(?:\s|(?=[A-ZÁÉÍÓÚ][a-záéíóú]))|\.-|:\s|;|$")
# La frase que lleva a «por …» tiene que ser de una votación del Pleno.
VOTO_PREVIO_RE = re.compile(r"Pleno|votaci[oó]n|\bse\s+vota|\bvotad|(?:aprobad|rechazad|desestimad|estimad)[oa]s?\s*,?\s*$|"
                            r"\b(?:es|son|queda|quedan|resulta|resultan|resultó|resultaron|resultando)\s+\w+\s*,?\s*$", re.I)
EXCLUIR_RE = re.compile(r"urgencia|ratificaci[oó]n|inclusi[oó]n|\bse\s+aprob[oó]|\bfue(?:ron)?\s+aprobad|tal\s+y\s+como|"
                        r"como\s+se\s+aprob|retirada|retirar", re.I)
OTRO_ORGANO_RE = re.compile(r"Junta\s+General|Consejo|Comisi[oó]n|Junta\s+de\s+(?:Gobierno|Portavoces)|\bMesa\b", re.I)
PLENO_PREVIO_RE = re.compile(r"Pleno|votaci[oó]n|\bse\s+vota|\bvotad", re.I)
RECHAZADA_RE = re.compile(r"rechaz|desestim|no\s+(?:se\s+)?aprueb|no\s+prosper|no\s+toma", re.I)
APROBADA_RE = re.compile(r"aprob|ACUERDA|acuerda|adopt|estimad|estima\b|toma\s+conocimiento|ratific|"
                         r"acord[oó]\s+(?!desestim|rechaz|no\b)\w+", re.I)
SENTIDO = {"favor": "si", "contra": "no", "absten": "abstencion"}


def _numero(s):
    s = s.lower()
    return int(s) if s.isdigit() else NUMEROS.get(s)


# ---------------------------------------------------------------------------------------------- texto

def _plano(texto):
    """Texto en una línea, sin pies de página («2 de 46»), sellos de firma ni saltos."""
    texto = re.sub(r"[•▪◦]", " ", texto.replace("\f", " "))     # viñetas de lista
    return _quitar_sellos(re.sub(r"\s+", " ", PIE_RE.sub(" ", texto)).strip())


SELLO_2015_RE = re.compile(r"FIRMADO POR ID\. FIRMA C[óo]digo Seguro de verificaci[óo]n:.{0,600}?"
                           r"PÁGINA\s+\S+\s+\d{2}/\d{2}/\d{4}\s+\d+/\d+")
FIN_SELLO_RE = re.compile(r"CES?T\b(?:\s+\d{2}/\d{2}/\d{4}\s+[\d:]+\s+CES?T\b)*|URL DE VALIDACI[ÓO]N\s+\S+|PÁG\.\s*\d+\s+DE\s+\d+")


def _quitar_sellos(plano):
    """Quita los sellos de firma electrónica que el PDF repite en cada página y cortan las frases.

    «FIRMADO POR ID. FIRMA Código Seguro de verificación: … PÁGINA … 27/10/2015 1/35» (hasta 2019) y
    «FIRMANTE … CÓDIGO CSV … FECHA Y HORA … CET … URL DE VALIDACIÓN https://… | PÁG. 2 DE 24» (después).
    """
    plano = SELLO_2015_RE.sub(" ", plano)
    trozos, pos = [], 0
    for m in re.finditer(r"FIRMANTE\s", plano):
        if m.start() < pos:
            continue
        finales = [f.end() for f in FIN_SELLO_RE.finditer(plano, m.end(), min(len(plano), m.end() + 800))]
        if not finales:
            continue
        trozos.append(plano[pos:m.start()])
        pos = finales[-1]
    trozos.append(plano[pos:])
    return re.sub(r"\s+", " ", " ".join(trozos))


def _acuerdos(plano, anio):
    """Divide el documento en acuerdos: [(numero_oficial, titulo, area, texto)].

    Cada acuerdo empieza por «N.º nnn/aa.-». Dentro de un acuerdo pueden citarse otros (acuerdos
    de la Junta de Gobierno transcritos, «N.º 402/21.- …»), así que se toma la cadena más larga de
    números crecientes y casi seguidos (saltos de hasta 5) con el año de la sesión.
    """
    cands = [(m.start(), m.end(), int(m.group(1))) for m in ACUERDO_RE.finditer(plano) if int(m.group(2)) == anio % 100]
    if not cands:
        return []
    mejor = [1] * len(cands)
    previo = [-1] * len(cands)
    for i in range(len(cands)):
        for j in range(i):
            if 0 < cands[i][2] - cands[j][2] <= 5 and mejor[j] + 1 > mejor[i]:
                mejor[i], previo[i] = mejor[j] + 1, j
    i = max(range(len(cands)), key=lambda k: (mejor[k], -k))
    cadena = []
    while i >= 0:
        cadena.append(cands[i])
        i = previo[i]
    cadena.reverse()
    out = []
    for k, (ini, fin, num) in enumerate(cadena):
        hasta = cadena[k + 1][0] if k + 1 < len(cadena) else len(plano)
        cuerpo = plano[fin:hasta]
        # El encabezado va en mayúsculas; el texto del acuerdo empieza en la primera palabra en minúsculas
        # («.- Leído el punto…», «. Examinado el expediente…», «RUEGOS Y PREGUNTAS Se formulan…»).
        m = re.search(r"[.\s]*-?\s*(?=\b[A-ZÁÉÍÓÚ]?[a-záéíóúñ]{3,}\b)", cuerpo[10:])
        corte = m.start() + 10 if m else min(len(cuerpo), 400)
        cabecera, texto = cuerpo[:min(corte, 800)], cuerpo[min(corte, 800):]
        area, titulo = _titulo(cabecera)
        out.append((f"{num}/{anio % 100:02d}", titulo, area, texto))
    return out


def _titulo(cabecera):
    """(área, título) de «PERSONAL.- 3. DICTAMEN DE LA COMISIÓN …»."""
    cabecera = re.sub(r"[.\s-]+(?:[A-ZÁÉÍÓÚ][a-záéíóú]?)?$", "", cabecera.strip()).strip(" .-")
    m = re.match(r"(.{2,120}?)\s*\.\s*-?\s*\(?\s*(\d+(?:\.\d+)*)\s*\.?\s*\)?\s*(?=[A-ZÁÉÍÓÚÑ“\"(])(.*)$", cabecera)
    if not m:
        # Sin número de orden: «ÓRGANO DE PLANIFICACIÓN ECONÓMICO PRESUPUESTARIA.- MOCIÓN DEL ILMO. SR. …»
        m = re.match(r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/()-]{2,90}?)\s*\.\s*-\s*()(.{20,})$", cabecera)
        if not m:
            return None, cabecera
    area, resto = m.group(1).strip(" .-"), m.group(3).strip(" .-")
    if re.match(r"(MOCI[OÓ]N|DECLARACI[OÓ]N|PROPOSICI[OÓ]N|ENMIENDA|COMPARECENCIA|PREGUNTA|RUEGO)", area, re.I):
        return area, f"{area} {resto}"
    return area, resto or area


# ------------------------------------------------------------------------------------------ votaciones

def _grupos(espec, total):
    """[(grupo, n|None)] de «de los representantes de los grupos municipales Popular (15), Socialista (7) y VOX (3)».

    Admite nombres con comas («IU,LV-CA (4)»), el voto de calidad («Socialista (8 = 7 + el voto de
    calidad)») y el voto de un concejal no adscrito dentro de la lista («… y 1 voto del Concejal no
    adscrito»). Si algún nombre no parece de grupo (frases que explican una abstención), se descarta
    la lista entera: mejor sin voto por grupo que con uno inventado.
    """
    espec = re.sub(r"\s+", " ", espec).strip(" ,.")
    espec = re.sub(r"^(?:y|e)\s+", "", espec)
    # «de conformidad con el art. 83 del ROG [del Excmo. Ayuntamiento de Córdoba], por el Grupo Municipal …»
    espec = re.sub(r"^de\s+conformidad\s+con\s+el\s+art\.?\s*\d+\s+del\s+(?:ROG|Reglamento\s+Org[aá]nico(?:\s+Municipal)?)"
                   r"(?:\s+del\s+Excmo\.\s+Ayuntamiento\s+de\s+C[oó]rdoba)?,?\s*", "", espec, flags=re.I)
    # «1 abstención de uno de los representantes del grupo…», «de un representante del grupo…»
    espec = re.sub(r"^de\s+(?:uno|una|dos|tres|\d+)\s+de\s+(?=(?:los|las)\s)", "de ", espec, flags=re.I)
    espec = re.sub(r"^de\s+(?:un|una|dos|tres|\d+)\s+(?=(?:representantes?|concejal))", "de ", espec, flags=re.I)
    # «… del grupo municipal Socialista así considerada en virtud de lo previsto en el art. 82 del Reglamento…»
    espec = re.sub(r"\s*,?\s+(?:así\s+considerad|en\s+virtud\s+de|de\s+conformidad\s+con|"
                   r"seg[uú]n\s+(?:lo\s+(?:previsto|establecido)|el\s+art)).*$", "", espec, flags=re.I)
    # «Mixto (Unión Cordobesa) (1)» -> «Mixto - Unión Cordobesa (1)»
    espec = re.sub(r"\s*\(([^()\d]+)\)(?=\s*\(\d)", r" - \1", espec)
    out = []
    adscrito = re.search(r",?\s*(?:y\s+)?" + NUM + r"\s+(?:votos?\s+)?(?:del|de\s+la)\s+concejal[a]?\s+no\s+adscrit[oa]\b",
                         espec, re.I)
    if adscrito:
        out.append(("Concejal no adscrito", _numero(adscrito.group(1))))
        espec = (espec[:adscrito.start()] + espec[adscrito.end():]).strip(" ,.")
    m = re.match(r"(?:de|del|por)\s+(?:(?:los|las|la|el)\s+)?(?:(?:representantes?|concejal(?:es|as?)?|miembros?)\s+"
                 r"(?:de\s+(?:los|las|la)\s+|del\s+))?(?:grupos?\s+(?:políticos?\s+)?municipal(?:es)?\s*,?\s*)?(.*)$", espec, re.I)
    if not m:
        return out
    lista = m.group(1).strip()
    if re.match(r"(?:concejal[a]?\s+)?no\s+adscrit", lista, re.I) or re.match(r"concejal[a]?\s+no\s+adscrit", espec, re.I):
        return out + [("Concejal no adscrito", total)]
    con_numero = re.findall(r"(?:\s*(?:,|\by\b|\be\b)\s*)*([^()]+?)\s*\((\d+)[^)]*\)", lista)
    if con_numero:
        resto = re.sub(r"[^()]+?\s*\(\d+[^)]*\)", "", lista[:lista.rfind(")") + 1]).strip(" ,.ye")
        grupos = [(_nombre_grupo(n), int(k)) for n, k in con_numero]
    else:
        resto = ""
        nombres = [x for x in re.split(r"\s*,\s*(?![A-Z]{2,}\b-)|\s+(?:y|e)\s+", lista) if x.strip()]
        grupos = [(_nombre_grupo(n), total if len(nombres) == 1 else None) for n in nombres]
    if resto or not all(_parece_grupo(g) for g, _ in grupos):
        return out
    return out + grupos


def _parece_grupo(nombre):
    """Nombre corto de grupo, sin palabras de una frase («que», «se encontraba», «D.ª»…)."""
    n = nombre.replace("Grupo Municipal ", "", 1)
    return (1 < len(n) <= 40 and re.match(r"[A-ZÁÉÍÓÚÑa-záéíóú]", n) is not None
            and not re.search(r"\b(?:que|se|en|el|la|los|las|durante|momento|Acuerda|ACUERDA|Con)\b|"
                              r"\b(?:D\.|Dª|D\.ª|Sr\.?|Sra\.?)(?=\s|$)|[Gg]rupo|abstenci|\bvoto", n))


def _nombre_grupo(n):
    n = re.sub(r"\s+", " ", n).strip(" ,.-")
    if re.search(r"concejal[a]?\s+no\s+adscrit", n, re.I):
        return "Concejal no adscrito"
    n = re.sub(r"^(?:(?:y|e)\s+)?(?:(?:del|de\s+los|de\s+la|de|el|los)\s+)?(?:grupos?\s+(?:políticos?\s+)?municipal(?:es)?\s*,?\s*)?",
               "", n, flags=re.I)
    n = re.sub(r"\.[A-ZÁÉÍÓÚ]{3,}.*$|\.?\s*\[.*$|\s+(?:y|e)$", "", n)   # «VOX.URGENCIAS…», «Popular.[SE PRODUCE DEBATE]»
    n = n[:1].upper() + n[1:]
    n = re.sub(r"(?<=[a-z])(?=Córdoba)", " ", n)             # «CiudadanosCórdoba»
    return "Grupo Municipal " + n


def _clausula(texto):
    """Lee el recuento de `texto` (justo después de «por [mayoría de]»).

    Devuelve (totales {si,no,abstencion}, grupos {nombre: {sentido: n}}, unanimidad, fin) o None.
    """
    m = re.match(r"\s*unanimidad\b", texto, re.I)
    if m:
        tramo = texto[m.end():m.end() + 200]
        n = re.match(r"\s*(?:de\s+(?:los|las|sus)\s+)?" + NUM + r"\s+(?:miembros|concejal|capitulares|asistentes|presentes)",
                     tramo, re.I)
        total = _numero(n.group(1)) if n else None
        return ({"si": total, "no": 0 if total is not None else None, "abstencion": 0 if total is not None else None},
                {}, True, m.end() + (n.end() if n else 0))
    tokens = []
    pos = 0
    while True:
        t = TOKEN_RE.match(texto, pos)
        if not t:
            break
        sentido = next((v for k, v in SENTIDO.items() if k in t.group(2).lower()), "si")  # «votos a de…»
        siguiente = re.search(r"(?:,\s*|\s+)(?:y\s+|e\s+)?(?=" + TOKEN_RE.pattern + ")", texto[t.end():], re.I)
        fin = FIN_CLAUSULA_RE.search(texto, t.end())
        corte = t.end() + siguiente.start() if siguiente else len(texto)
        if fin and fin.start() < corte:
            corte = fin.start()
            tokens.append((_numero(t.group(1)), sentido, texto[t.end():corte]))
            pos = corte
            break
        tokens.append((_numero(t.group(1)), sentido, texto[t.end():corte]))
        pos = t.end() + siguiente.end() if siguiente else corte
    if not tokens:
        return None
    totales, grupos = {"si": 0, "no": 0, "abstencion": 0}, {}
    for n, sentido, espec in tokens:
        lista = _grupos(espec, n)
        if n is None:        # «… y los votos a favor de los grupos municipales PSOE (7) y Hacemos Córdoba (4)»
            n = sum(k for _, k in lista) if lista and all(k is not None for _, k in lista) else None
        if totales[sentido] is not None:
            totales[sentido] = None if n is None else totales[sentido] + n
        for nombre, k in lista:
            grupos.setdefault(nombre, {})[sentido] = k
    return totales, grupos, False, pos


def _voto_grupos(grupos):
    out = []
    for nombre, sentidos in grupos.items():
        if len(sentidos) == 1:
            s, n = next(iter(sentidos.items()))
            out.append(VotoGrupo(nombre, **{s: n}, sentido=s))
        else:
            out.append(VotoGrupo(nombre, si=sentidos.get("si"), no=sentidos.get("no"),
                                 abstencion=sentidos.get("abstencion"), sentido="dividido"))
    return out


def _subtitulo(frase):
    """Qué se vota dentro del acuerdo, si no es el asunto entero: enmiendas y reclamaciones."""
    m = None
    for m in re.finditer(r"\b(Enmiendas?\b.*?)(?=\s*(?:,|;|:|\(|\s(?:que|es|son|queda|quedan|result\w*|anteriormente|"
                         r"transcrita|trascrita|citada|con\s+fecha|cuyo|suscrita|presentada|formulada|planteada)\b)|$)",
                         frase, re.I):
        pass                              # la última mención es la que se vota
    if m:
        s = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")[:120]
        autor = re.search(r"(?:presentada|formulada|suscrita|planteada)s?\s+por\s+(?:el|los)\s+(grupos?\s+municipal(?:es)?\s+"
                          r"[A-ZÁÉÍÓÚ][^,;:.]*?)(?=\s*(?:,|;|:|\.|\s(?:que|es|son|queda|result\w*)\b)|$)", frase, re.I)
        if autor and not re.search(r"\bgrupo", s, re.I) and not re.match(r"grupos", autor.group(1), re.I):
            s += " del " + re.sub(r"\s+", " ", autor.group(1)).strip()
        return s[0].upper() + s[1:], "enmiendas"
    if re.search(r"reclamaci[oó]n|alegaci[oó]n", frase, re.I):
        n = re.search(r"alegaci[oó]n\s+n[úu]mero\s+(\d+)|alegaci[oó]n\s+n\.?\s*[º°o]\s*(\d+)", frase, re.I)
        return ("Reclamación" + (f" (alegación {n.group(1) or n.group(2)})" if n else "")), None
    if re.search(r"votaci[oó]n\s+separada|punto\s+\w+\s+de\s+la\s+moci", frase, re.I):
        p = re.search(r"((?:puntos?|acuerdos?)\s+[\wº, y]+?)\s*(?:de\s+la|,|:|$)", frase, re.I)
        return (p.group(1).strip().capitalize() if p else "Votación separada"), None
    return None, None


def votaciones_acuerdo(texto):
    """Votaciones del Pleno en el texto de un acuerdo: [(subtitulo, tipo_votacion, datos)] y frases sin leer."""
    votos, fallos, fin_anterior = [], [], -1
    anclas = list(ANCLA_RE.finditer(texto))
    for a in anclas:
        if a.start() < fin_anterior:
            continue
        frase = _frase(texto, a.start())
        if not _frase_de_votacion(frase) or _citada(frase):
            continue                      # no es una votación del Pleno, o va entre comillas (cita)
        proxima = min([b.start() for b in anclas if b.start() >= a.end()] + [len(texto)])
        r = _clausula(texto[a.end():proxima])
        if not r:
            fallos.append(texto[max(0, a.start() - 80):a.start() + 200])
            continue
        totales, grupos, unanimidad, largo = r
        previo = texto[max(0, fin_anterior, a.start() - 1500):a.start()]   # para la etiqueta («Enmienda n.º 2: …»)
        fin_anterior = a.end() + largo
        despues = texto[fin_anterior:min(proxima, fin_anterior + 200)]
        despues = re.split(r"\.\s+[A-ZÁÉÍÓÚ]|\.-", despues)[0]
        if RECHAZADA_RE.search(frase[-120:]) or RECHAZADA_RE.search(despues[:120]):
            resultado = "rechazada"
        elif APROBADA_RE.search(frase[-120:]) or APROBADA_RE.search(despues[:160]) or unanimidad:
            resultado = "aprobada"
        else:
            resultado = None
        etiquetada = re.search(r"enmienda|reclamaci|alegaci|votaci[oó]n\s+separada", frase, re.I)
        subtitulo, tipo_votacion = _subtitulo(frase if etiquetada else previo)
        votos.append((subtitulo, tipo_votacion, {"totales": totales, "grupos": _voto_grupos(grupos),
                                                 "unanimidad": unanimidad, "resultado": resultado}))
    return votos, fallos


def _frase_de_votacion(frase):
    """Si lo que precede a «por mayoría/unanimidad» es una votación del Pleno (no una cita ni otro órgano)."""
    if EXCLUIR_RE.search(frase) or not VOTO_PREVIO_RE.search(frase):
        return False
    return not (OTRO_ORGANO_RE.search(frase) and not PLENO_PREVIO_RE.search(frase))


def _frase(texto, fin):
    """Lo que va desde el principio de la frase hasta `fin` (la frase acaba en «. », «.- », «: », «; » o «].»)."""
    ini = max(0, fin - 1500)
    for m in FRASE_RE.finditer(texto, ini, fin):
        ini = m.end()
    return texto[ini:fin]


def _citada(frase):
    """Si la frase va entre comillas: una votación anterior citada, no la de esta sesión."""
    f = frase.lstrip()
    return f[:1] in "\"“«" or f.count("“") > f.count("”") or f.count("«") > f.count("»")


def _parece_votado(texto):
    for a in ANCLA_RE.finditer(texto):
        frase = _frase(texto, a.start())
        if _frase_de_votacion(frase) and not _citada(frase):
            return True
    return False


def votaciones_documento(texto, anio):
    """Votaciones del Pleno en un extracto o acta: (lista de dicts, estadística)."""
    est = {"acuerdos": 0, "con_votacion": 0, "leidos": 0, "sin_leer": []}
    out = []
    for orden, (acuerdo, titulo, area, cuerpo) in enumerate(_acuerdos(_plano(texto), anio), 1):
        est["acuerdos"] += 1
        votos, fallos = votaciones_acuerdo(cuerpo)
        if votos or _parece_votado(cuerpo):
            est["con_votacion"] += 1
            est["leidos"] += bool(votos)
        est["sin_leer"] += fallos
        for k, (subtitulo, tipo_votacion, d) in enumerate(votos, 1 if len(votos) > 1 else 0):
            out.append({"orden": orden, "k": k, "acuerdo": acuerdo, "titulo": titulo, "area": area,
                        "subtitulo": subtitulo, "tipo_votacion": tipo_votacion, "datos": d})
    est["incoherentes"] = _quitar_incoherentes(out)
    return [v for v in out if v["datos"]["resultado"] or v["datos"]["totales"]["si"] is not None
            or v["datos"]["unanimidad"]], est


def _quitar_incoherentes(votos):
    """Deja sin totales ni grupos las votaciones con más votos que concejales (frase mal escrita en el documento)."""
    malas = 0
    for v in votos:
        t = v["datos"]["totales"]
        if sum(x or 0 for x in t.values()) > CUERPOS[0].escanos:
            v["datos"]["totales"] = {"si": None, "no": None, "abstencion": None}
            v["datos"]["grupos"] = []
            malas += 1
    return malas


# ------------------------------------------------------------------------------------------- tipos

def _tipo(titulo, area):
    t = f"{area or ''} {titulo}".lower()
    if re.search(r"\bmoci[oó]n\b", t):
        return "mocion"
    if re.search(r"declaraci[oó]n institucional", t):
        return "otro"
    if re.search(r"presupuesto general|presupuestos generales", t) and not re.search(r"modificaci|cr[ée]dito|error", t):
        return "presupuesto"
    if re.search(r"\bordenanza|\breglamento\b", t):
        return "ordenanza"
    if re.search(r"borrador(?:es)? de(?:l)? actas?|nombramiento|representantes?|\bcese\b|composici[oó]n|toma de posesi|"
                 r"credencial|personal eventual|r[ée]gimen de dedicaci|retribuciones|fecha de (?:la )?celebraci|calendario|"
                 r"junta de portavoces|urgencia", t):
        return "organizacion"
    if re.search(r"toma(?:r)? (?:de )?conocimiento|dar cuenta|dación|informe|comparecencia|ruegos|preguntas", t):
        return "control"
    return "acuerdo"


def _autor(titulo, area):
    m = re.match(r"MOCI[OÓ]N\s+(?:URGENTE\s+)?DEL\s+GRUPO\s+(?:POLÍTICO\s+)?MUNICIPAL\s+(.+?)$", (area or "").strip(), re.I)
    if m:
        return "Grupo Municipal " + m.group(1).strip(" .-")
    return None


# ------------------------------------------------------------------------------------------ recogida

def _elegir_documentos(docs):
    """Extracto (preferido) y acta de la ficha, en ese orden."""
    extractos = [d for d in docs if "extracto" in d[2].lower() or "extracto" in d[1].lower()]
    actas = [d for d in docs if d[2].strip().lower() == "acta"]
    return extractos[:1] + actas[:1]


def _sesiones(ctx):
    """Plenos con extracto o acta, del más reciente al más antiguo: (sesion, numero, [documentos])."""
    desde = ctx.desde(CUERPO)
    if desde:
        desde = (date.fromisoformat(desde) - timedelta(days=MARGEN_ACTAS)).isoformat()
    organo = ava.organo(ctx, BASE, "Pleno Municipal", ORGANO_PLENO)
    for s in ava.sesiones(ctx, BASE, organo, desde):
        if re.search(r"C\.\s*P\.|Comisi[oó]n|aplazad|desconvocad|suspendid", s["titulo"], re.I):
            continue
        m = SESION_RE.search(s["titulo"])
        if not m or int(m.group(2)) != int(s["fecha"][2:4]):
            ctx.log(f"  ! {CUERPO} {s['fecha']}: sesión sin número oficial en el título, se salta: {s['titulo']}")
            continue
        try:
            docs, _ = ava.ficha(ctx, BASE, s, cache=f"{CUERPO}/sesiones/{s['id']}.html",
                                falta=lambda d: not _elegir_documentos(d))
        except (ErrorDescarga, urllib.error.URLError) as e:
            ctx.log(f"  ! {CUERPO} {s['fecha']}: ficha sin cargar ({e})")
            continue
        elegidos = _elegir_documentos(docs)
        if elegidos:
            yield s, int(m.group(1)), elegidos


def _texto(ctx, doc_id, url):
    pdf = ctx.fetch(url, cache=f"{CUERPO}/docs/{doc_id}.pdf", timeout=180)
    return ctx.pdf_texto(pdf, layout=False)


def _sin_texto(texto):
    """Si el PDF es una imagen escaneada: casi no hay palabras en minúsculas (solo números sueltos o nada)."""
    palabras = len(re.findall(r"\b[a-záéíóúñ]{4,}\b", texto))
    return palabras < 45 or palabras * 1000 < 10 * len(re.sub(r"\s", "", texto))


def descargar(ctx):
    n, con_votacion, leidos = 0, 0, 0
    for s, num_sesion, docs in _sesiones(ctx):
        texto = url = None
        for doc_id, _fichero, _nombre, u in docs:       # el extracto y, si falla o es un escaneo, el acta
            try:
                t = _texto(ctx, doc_id, u)
            except (ErrorDescarga, urllib.error.URLError) as e:
                ctx.log(f"  ! {CUERPO} {s['fecha']}: documento sin descargar ({e})")
                continue
            if _sin_texto(t):
                ctx.log(f"  ! {CUERPO} {s['fecha']}: el documento no tiene texto (PDF escaneado): {u}")
                continue
            texto, url = t, u
            break
        if not texto:
            continue
        votos, est = votaciones_documento(texto, int(s["fecha"][:4]))
        con_votacion += est["con_votacion"]
        leidos += est["leidos"]
        if not est["acuerdos"]:
            ctx.log(f"  ! {CUERPO} {s['fecha']}: no se encuentran acuerdos numerados en {url}")
        if est["sin_leer"]:
            ctx.log(f"  · {CUERPO} {s['fecha']}: {len(est['sin_leer'])} frases de votación sin leer, "
                    f"p. ej.: {est['sin_leer'][0][:160]}")
        for v in votos:
            d, t = v["datos"], v["datos"]["totales"]
            tipo = _tipo(v["titulo"], v["area"])
            yield Votacion(
                cuerpo=CUERPO, fecha=s["fecha"], titulo=v["titulo"], sesion=num_sesion,
                numero=100 * v["orden"] + v["k"], subtitulo=v["subtitulo"], tipo_iniciativa=tipo,
                tipo_votacion=v["tipo_votacion"] or ("mocion" if tipo == "mocion" else None),
                autor=_autor(v["titulo"], v["area"]) if tipo == "mocion" else None,
                a_favor=t["si"], en_contra=t["no"], abstenciones=t["abstencion"],
                asentimiento=d["unanimidad"] and t["si"] is None,
                resultado=d["resultado"], grupos=d["grupos"], url=url, fuente="pdf-reglas",
                extra={"acuerdo": v["acuerdo"], "sesion_oficina_virtual": s["url"]},
            )
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    ctx.log(f"  {CUERPO}: {leidos} de {con_votacion} acuerdos con votación leídos")


def documentos(ctx):
    n = 0
    for s, num_sesion, docs in _sesiones(ctx):
        doc_id, _fichero, nombre, url = docs[0]
        yield Documento(cuerpo=CUERPO, fecha=s["fecha"], url=url, sesion=num_sesion, titulo=s["titulo"],
                        extra={"id": doc_id, "documento": nombre, "sesion_oficina_virtual": s["url"]})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    """Texto del extracto o acta (con la misma caché que descargar)."""
    return _texto(ctx, doc.extra["id"], doc.url)
