"""Pleno del Ayuntamiento de Málaga: votaciones sacadas con reglas de las actas en PDF.

Fuente: la plataforma de videoactas (https://videoactas.malaga.eu, «Audio Vídeo Actas» de eCityclic;
ver _videoactas.py). El buscador filtrado por el órgano «Pleno Municipal» lista todas las sesiones
desde junio de 2019 y la ficha de cada una enlaza el orden del día y, cuando se aprueba (uno o dos
meses después), el acta firmada en PDF. El acta transcribe cada punto con su debate y termina con
un apartado «VOTACIÓN» de redacción muy regular:

    El Excmo. Ayuntamiento Pleno, por 28 votos a favor (16 del Grupo Municipal Popular, 10 del Grupo
    Municipal Socialista y 2 del Grupo Municipal Vox) y 2 abstenciones (del Grupo Municipal Con
    Málaga), dio su aprobación al Dictamen…

o, en las votaciones separadas, «Puntos 2, 7 y 9: Desestimados por 12 votos a favor (…) y 18 votos
en contra (…)». De ahí salen los totales, el voto de cada grupo (con número de concejales) y el
resultado. Los dictámenes transcriben antes la votación de la comisión, que se descarta: solo
cuentan los apartados «VOTACIÓN» que nombran al Pleno o traen votaciones separadas que no son de la
comisión. Los títulos salen del índice del vídeo de la ficha, en minúsculas; si no está, del
encabezado del punto en el acta (en mayúsculas).

Cobertura: Pleno desde el 15 de junio de 2019 (mandatos XI y XII), unas 135 actas; faltan las
sesiones recientes cuya acta aún no se ha publicado.
Claves: sesion = AAAAMMDD de la sesión; numero = 100 × orden del punto en el acta + n.º de la
votación dentro del punto (0 si solo hay una). Si hay dos plenos el mismo día (5 veces), el orden de
los puntos del segundo empieza en 51.
Limitaciones: dos actas de 2024 (27 de junio y 9 de julio) son imágenes escaneadas sin texto y se
saltan. La unanimidad sin recuento («por unanimidad de los miembros asistentes») va sin totales y
con asentimiento; si el acta nombra los grupos presentes, cada uno lleva «si». Las votaciones de
urgencia y de retirada de puntos no se recogen. Para una revisión con LLM, `documentos` da las actas.
"""

import re
import urllib.error
from datetime import date, timedelta

from ...territorio import MANDATOS_LOCALES, Cuerpo, num_municipio
from ..contexto import ErrorDescarga
from ..modelo import Documento, Votacion, VotoGrupo
from . import _videoactas as ava

CUERPO = "ayto-malaga"
BASE = "https://videoactas.malaga.eu/actas"
ORGANO_PLENO = "8a817cc36b225b16016b225b48ac000d"  # «Pleno Municipal» en el buscador (se relee del formulario)
MARGEN_ACTAS = 90  # días de más al recoger por incremental: el acta se publica meses después

CUERPOS = [
    Cuerpo(CUERPO, num_municipio("29067"), "Ayuntamiento de Málaga", "Ayto. Málaga", "municipal", "AN", 31,
           dict(MANDATOS_LOCALES), web="https://videoactas.malaga.eu"),
]

NOTAS = ("Actas del Pleno en PDF (videoactas.malaga.eu) leídas con reglas: totales, voto por grupo con número "
         "de concejales y resultado. Desde junio de 2019; las actas salen uno o dos meses después de la sesión. "
         "Dos actas de 2024 son imágenes sin texto. Unanimidad sin recuento: sin totales, con asentimiento.")

NUMEROS = {"un": 1, "uno": 1, "una": 1, "el": 1, "la": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
           "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
           "quince": 15, "dieciséis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20}
NUM = r"(\d+|" + "|".join(sorted((k for k in NUMEROS if k not in ("el", "la")), key=len, reverse=True)) + r")"

# Encabezado de punto: «PUNTO Nº 12.-», «PUNTO nº U.3.-», «PUNTO U.1.-», «Punto nº U.1.»
PUNTO_RE = re.compile(r"PUNTO\s+(?:N\s*[º°o]\.?\s*)?((?:U\s*[.\-]?\s*)?\d{1,3}|[ÚU]NICO)\s*(?:\.\s*-|\.|-)", re.I)
PIE_RE = re.compile(r"^(?:-?\s*\d{1,3}\s*-?|\d{1,3}\s*/\s*\d{1,3}|AYUNTAMIENTO DE MÁLAGA|SECRETARÍA GENERAL(?: DEL PLENO)?|"
                    r"Ayuntamiento de Málaga Avenida Cervantes.*|\+34 951.*|URL de Verificación.*)$", re.I)
# Cabecera de página («Sesión ordinaria Pleno de 31/07/2025», «Pleno ordinario 28/11/19»), a veces pegada al texto.
CABECERA_RE = re.compile(r"(?:Sesión|Pleno)\s+(?:\S+\s+){0,2}?(?:de\s+)?(?:Pleno\s+)?(?:de\s+)?\d{1,2}/\d{2}/\d{2,4}", re.I)
VOTACION_RE = re.compile(r"\bVOTACI[ÓO]N\b")
# Resto de «Este punto se encuentra en el siguiente enlace del documento audiovisual del acta:» pegado al título.
RESTO_ENLACE_RE = re.compile(r"\s*(?:del\s+)?acta:\s*$")
# Encabezado de punto pegado a la frase anterior («…se debatieron conjuntamente: PUNTO Nº 27.- MOCIÓN…»).
ENCABEZADO_PEGADO_RE = re.compile(r"(?<=[.:])[ \t]+(?=PUNTO\s+N[º°o]\s*(?:U\s*[.\-]?\s*)?\d{1,3}\s*\.-\s*[A-ZÁÉÍÓÚ])")
# Votación del Pleno: «El Excmo. Ayuntamiento Pleno, por …» (no la de la comisión ni el resumen final).
PLENO_RE = re.compile(r"(?<!Comisión del )(?<!Comisión de )(?<!Comisión )\b(?:Excmo\.\s*)?(?:Ayuntamiento\s+)?"
                      r"(?-i:Pleno),?\s+(?:en\s+votación\s+\w+,?\s+)?por\s+(?!el\s+número)(?!sustitución)(?=" + NUM +
                      r"\s+votos?|unanimidad|mayoría)", re.I)
# Votación separada: «Puntos 1º y 3º: Aprobados por …», «ACUERDO SEGUNDO: Desestimado por …»
SEPARADA_RE = re.compile(r"(?<![\w-])((?:Puntos?|PUNTOS?|Acuerdos?|ACUERDOS?|Enmiendas?|ENMIENDAS?)\b[^:;()]{0,160}?)"
                         r"\s*(?::|\.-)\s*(Aprobad[oa]s?|Desestimad[oa]s?|Rechazad[oa]s?)\s+(?:por\s+)?"
                         r"(?=" + NUM + r"\s+votos?|unanimidad|mayoría)", re.I)
TOKEN_RE = re.compile(r"\s*(?:,|;)?\s*(?:\by\b|\be\b)?\s*(?:con\s+)?" + NUM +
                      r"\s+(votos?\s+(?:a\s+)?favor|votos?\s+en\s+contra|votos?\s+de\s+abstenci[oó]n|abstenci[oó]n(?:es)?)",
                      re.I)
COMISION_RE = re.compile(r"\bComisi[oó]n\s+(?:del?\s+Pleno\s*,?\s*)?(?:acord|procedi|por\s+unanimidad)|"
                         r"Dictaminad[oa]s?\s+favorablemente|dictaminar\s+favorablemente", re.I)
GRUPO_SUELTO_RE = re.compile(r"\s+((?:de\s+los\s+representantes\s+)?(?:del|de\s+la|de\s+los|de)\s+(?:Grupos?\s+Municipal(?:es)?|"
                             r"Concejal(?:a|es)?\s+no\s+adscrit)[^,;()]*?)(?=\s*(?:,|;|\by\s+" + NUM + r"\s|\be\s+" + NUM +
                             r"\s|\bdio\b|\bacord|\badopt|\.\s|$))", re.I)
EXCLUIR_RE = re.compile(r"urgencia|retira(?:r|da)\s+(?:el|este|del)|retirada\s+del", re.I)
APROBADA_RE = re.compile(r"dio su aprobaci[oó]n|aprob[oó]\b|acord[oó],?\s+(?!desestim|rechaz|no\b)\w+|adopt[oó]|"
                         r"aprobad[oa]s?\b|estimad[oa]s?\b", re.I)
RECHAZADA_RE = re.compile(r"desestim|rechaz|no (?:fue |resultó )?aprobad|no prosper", re.I)
SENTIDO = {"favor": "si", "contra": "no", "absten": "abstencion"}


def _numero(s):
    s = s.lower()
    return int(s) if s.isdigit() else NUMEROS.get(s)


def _id_punto(s):
    """Id normalizado de un punto: «02» -> «2», «u.1» -> «U.1», «U - 3» -> «U-3»."""
    s = re.sub(r"\s+", "", s.upper()).replace("Ú", "U")
    m = re.match(r"(U[.\-]?)?0*(\d+)$", s)
    return (m.group(1) or "") + m.group(2) if m else s


def _sin_signo(pid):
    return pid.replace(".", "").replace("-", "")


# ---------------------------------------------------------------------------------------------- texto

def _lineas(texto):
    """Líneas del acta sin cabeceras ni pies de página, con los párrafos partidos por un salto de página unidos."""
    out = []
    texto = ENCABEZADO_PEGADO_RE.sub("\n", texto.replace("\f", "\n"))
    for linea in texto.split("\n"):
        s = linea.strip()
        c = CABECERA_RE.match(s) or (len(s) < 90 and CABECERA_RE.search(s))
        if c:
            s = (s[:c.start()] + " " + s[c.end():]).strip()
        if not s or PIE_RE.match(s):
            continue
        if out and not re.search(r"[.:;!?»”\")]$", out[-1]) and re.match(r"[a-záéíóúñü(0-9]", s):
            out[-1] += " " + s
        else:
            out.append(s)
    return out


def _puntos(lineas):
    """Divide el acta en puntos: [(id, titulo_del_encabezado, [líneas])].

    El acta empieza con un índice de puntos; el cuerpo empieza en el primer encabezado que repite un
    id del índice. En el cuerpo solo cuentan los encabezados con un id del índice que aún no ha
    salido: así se ignoran los puntos citados dentro de un dictamen («PUNTO Nº U-1» de la comisión
    cuando el del Pleno es «U.1»). Si el índice y el cuerpo escriben distinto un punto urgente («U1»
    y «U.1»), vale el encabezado sin el signo siempre que más adelante no salga el id exacto.
    """
    vistos, inicio = [], None
    for i, l in enumerate(lineas):
        ids = [_id_punto(m.group(1)) for m in PUNTO_RE.finditer(l)]
        if not ids:
            continue
        if PUNTO_RE.match(l) and ids[0] in vistos and not re.search(r"\.{4,}\s*\d+\s*$", l):
            inicio = i
            break
        vistos.extend(ids)
    cuerpo = lineas[inicio or 0:]
    cabeceras = [(i, _id_punto(m.group(1))) for i, l in enumerate(cuerpo) for m in [PUNTO_RE.match(l)] if m]
    pendientes = list(dict.fromkeys(vistos)) if inicio is not None else None
    aceptadas = {}
    for k, (i, pid) in enumerate(cabeceras):
        if pendientes is None:
            if pid not in aceptadas.values():
                aceptadas[i] = pid
        elif pid in pendientes:
            pendientes.remove(pid)
            aceptadas[i] = pid
        else:
            iguales = [p for p in pendientes if _sin_signo(p) == _sin_signo(pid)]
            if iguales and not any(q == iguales[0] for _, q in cabeceras[k + 1:]):
                pendientes.remove(iguales[0])
                aceptadas[i] = pid
    puntos = []
    for i, l in enumerate(cuerpo):
        if i in aceptadas:
            m = PUNTO_RE.match(l)
            puntos.append([aceptadas[i], l[m.end():].strip(" .-\t"), []])
        elif puntos:
            resto = RESTO_ENLACE_RE.sub("", l)
            if not puntos[-1][2] and resto and not re.search(r"[a-záéíóúñ]", resto) and len(puntos[-1][1]) < 400:
                puntos[-1][1] += " " + resto    # el título en mayúsculas sigue en la línea siguiente
            else:
                puntos[-1][2].append(l)
    return [(p, re.sub(r"^(?:del\s+)?acta:\s*", "", RESTO_ENLACE_RE.sub("", t)).strip(" .-"), ls) for p, t, ls in puntos]


def _titulos_video(puntos_video):
    """Títulos del índice del vídeo por id de punto."""
    out = {}
    for t in puntos_video:
        m = re.match(r"\s*" + PUNTO_RE.pattern, t, re.I)
        if m:
            out.setdefault(_sin_signo(_id_punto(m.group(1))), re.sub(r"\s+", " ", t[m.end():]).strip(" .-\t"))
    return out


# ------------------------------------------------------------------------------------------ votaciones

def _grupos(lista, total):
    """[(grupo, n|None)] de «16 del Grupo Municipal Popular, 10 del Grupo Municipal Socialista y 2 del …»."""
    # Notas dentro de la lista: «-incluido el voto a distancia del Sr. X, en los términos del art. 101 bis
    # del R.O.P.-», «-incluidos los votos a distancia del Sr. X-», «– Sra. Martín Ortiz»
    lista = re.sub(r"\s*-?\s*incluid[oa]s?\s.*?R\.\s*O\.\s*P\.\s*-?", "", lista)
    lista = re.sub(r"\s*[-–]\s*(?:incluid|Sr\b|Sra\b|D\.|Dª)[^()]*?(?:[-–](?=\s*(?:,|y\b|e\b|$))|$)", "", lista)
    # Restos de cabecera o pie de página cuando la lista cruza de página («64/111», «SECRETARÍA GENERAL»)
    lista = re.sub(r"\b\d{1,3}/\d{1,3}\b|SECRETARÍA GENERAL(?: DEL PLENO)?|AYUNTAMIENTO DE MÁLAGA|\([^()]*\)", " ", lista)
    lista = re.sub(r"\s+", " ", lista).strip(" .,")
    num = NUM[1:-1]
    partes = re.split(r"\s*,\s*(?:y\s+|e\s+)?|\s+(?:y|e)\s+(?=(?:" + num + r"|el|la)?\s*(?:votos?\s+(?:a\s+distancia\s+)?)?"
                      r"(?:del?\b|de\s+la\b|de\s+los\b|por\s+el\b|Grupo\b))|\s+(?=\d+\s+del\s+Grupo\b)", lista, flags=re.I)
    out = []
    for p in partes:
        m = re.match(r"(?:(?:ambos|ambas|todos|todas)\s+)?(?:(" + num + r"|el|la)\s*)?(?:votos?\s+(?:a\s+distancia\s+)?)?"
                     r"(?:(?:concejal(?:es|as?)?|miembros?|representantes?)\s+)?"
                     r"(?:(?:del|de\s+la|de\s+los|de\s+las|de|por\s+el)\s+|(?=Grupo\b))(.+)$", p.strip(), re.I)
        if not m:
            continue
        n = _numero(m.group(1)) if m.group(1) else None
        nombre = re.sub(r"^(?:(?:los|las|la|el)\s+)?(?:representantes?|concejal(?:es|as?)?)\s+(?:del|de\s+la|de\s+los)\s+(?=Grupo)",
                        "", m.group(2).strip(" .-–"), flags=re.I)
        nombre = re.sub(r"^.*?\b(?=Grupo\s+Municipal)", "", nombre) if re.match(r"(?:del\s|Sesión)", nombre) else nombre
        if re.match(r"Grupos\s+Municipales\s+", nombre, re.I):     # «de los Grupos Municipales Socialista y Con Málaga»
            varios = re.split(r"\s*,\s*|\s+y\s+", re.sub(r"^Grupos\s+Municipales\s+", "", nombre, flags=re.I))
            out += [("Grupo Municipal " + v.strip()[:1].upper() + v.strip()[1:], None) for v in varios if v.strip()]
            continue
        if re.match(r"Grupo\b", nombre, re.I):
            g = re.sub(r"^(?:(?:Grupo|Municipal)\s+)+", "", nombre + " ", flags=re.I)
            g = re.sub(r"\s*[-–]?\s*incluid[oa]s?\b.*$|\s+(?:y|e)$|(?<=[a-z])\d+$", "", g.strip())
            g = re.sub(r"\b(\w+) \1\b", r"\1", g)                  # «Popular Popular»
            if not g or len(g) > 40 or re.search(r"\d|\.", g):
                continue                # nota a pie de página o texto de otra cosa metido en la lista
            nombre = "Grupo Municipal " + g[:1].upper() + g[1:]
        elif re.match(r"concejal[a]?\s+no\s+adscrit", nombre, re.I):
            nombre = "Concejal no adscrito"
        elif re.match(r"concejal(?:es|as)\s+no\s+adscrit", nombre, re.I):
            nombre = "Concejales no adscritos"
        else:
            continue                    # una persona u otra cosa que no es un grupo
        out.append((nombre, n))
    if len(out) == 1 and out[0][1] is None:
        out = [(out[0][0], total)]
    return out


def _parentesis(texto, i):
    """Contenido del paréntesis que abre en texto[i] (con paréntesis anidados) y posición final."""
    nivel = 0
    for j in range(i, min(len(texto), i + 600)):
        if texto[j] == "(":
            nivel += 1
        elif texto[j] == ")":
            nivel -= 1
            if nivel == 0:
                return texto[i + 1:j], j + 1
    return None, i


def _clausula(texto):
    """Lee el recuento que empieza en `texto` (justo después de «por»).

    Devuelve (totales {si,no,abstencion}, grupos {nombre: {sentido: n}}, unanimidad, fin) o None.
    """
    m = re.match(r"\s*(?:mayoría\s+(?:absoluta\s+|simple\s+)?(?:de\s+)?)?unanimidad\b", texto, re.I)
    if m:
        fin = m.end()
        tramo = re.split(r",\s*(?:y\s+)?(?:dio|acord|adopt|aprob|desestim)|\.\s+[A-ZÁÉÍÓÚ]", texto[fin:fin + 500])[0]
        n = re.search(r"(?:de\s+(?:los|las)\s+|\()" + NUM + r"\s+(?:miembros|concejal|asistentes|votos|presentes)", tramo, re.I)
        grupos = {}
        i = tramo.find("(")
        if i >= 0:
            dentro, _ = _parentesis(tramo, i)
            lista = _grupos(dentro, None) if dentro and re.search(r"Grupo|adscrit", dentro, re.I) else None
            for nombre, k in lista or []:
                grupos.setdefault(nombre, {})["si"] = k
        total = _numero(n.group(1)) if n else None
        return {"si": total, "no": 0 if total is not None else None, "abstencion": 0 if total is not None else None}, \
            grupos, True, fin + len(tramo)
    pos, totales, grupos, n_tokens = 0, {}, {}, 0
    while True:
        m = TOKEN_RE.match(texto, pos)
        if not m:
            break
        n = _numero(m.group(1))
        sentido = next(v for k, v in SENTIDO.items() if k in m.group(2).lower())
        totales[sentido] = totales.get(sentido, 0) + (n or 0)
        pos = m.end()
        n_tokens += 1
        p = re.match(r"\s*\(", texto[pos:])
        suelto = GRUPO_SUELTO_RE.match(texto, pos)
        if p:
            dentro, fin = _parentesis(texto, pos + p.end() - 1)
            if dentro is not None:
                pos = fin
                for nombre, k in _grupos(dentro, n) or []:
                    grupos.setdefault(nombre, {})[sentido] = k
        elif suelto:                    # «17 votos a favor del Grupo Municipal Popular y 14 abstenciones…»
            pos = suelto.end()
            for nombre, k in _grupos(suelto.group(1), n) or []:
                grupos.setdefault(nombre, {})[sentido] = k
    if not n_tokens:
        return None
    for s in ("si", "no", "abstencion"):
        totales.setdefault(s, 0)
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


def _resultado(etiqueta, resto, unanimidad):
    if etiqueta:
        return "rechazada" if RECHAZADA_RE.search(etiqueta) else "aprobada"
    if RECHAZADA_RE.search(resto):
        return "rechazada"
    if APROBADA_RE.search(resto) or unanimidad:
        return "aprobada"
    return None


def _anclas(plano, separadas=True):
    """Inicios de votación del Pleno en un texto aplanado: [(inicio, fin, etiqueta|None)].

    Se descartan las declaraciones de urgencia y las retiradas de puntos (frase previa) y las
    votaciones citadas entre comillas (acuerdos anteriores transcritos).
    """
    anclas = [(m.start(), m.end(), None) for m in PLENO_RE.finditer(plano)]
    if separadas:
        anclas += [(m.start(), m.end(), (m.group(1).strip(), m.group(2))) for m in SEPARADA_RE.finditer(plano)]
    out = []
    for a in sorted(anclas):
        previo = plano[max(0, a[0] - 160):a[0]]
        if EXCLUIR_RE.search(previo[previo.rfind(".") + 1:] if "." in previo else previo):
            continue
        if re.search(r"[“\"«]\s*(?:El\s+)?$", previo):
            continue
        out.append(a)
    return out


def _bloques_pleno(texto):
    """Tramos del punto con votaciones del Pleno, ya aplanados.

    El punto se corta por los encabezados «VOTACIÓN». Los dictámenes transcriben antes la votación
    de la comisión, que no cuenta: un tramo es del Pleno si lo nombra («El Excmo. Ayuntamiento
    Pleno, por…») o si trae votaciones separadas y no es de la comisión («La Comisión del Pleno
    acordó…», «Dictaminado favorablemente…»). Un punto puede tener varios tramos del Pleno (asuntos
    debatidos juntos bajo un mismo encabezado).
    """
    cortes = [m.start() for m in VOTACION_RE.finditer(texto)]
    if not cortes:
        tramos = [texto]
    else:
        tramos = [texto[a:b] for a, b in zip(cortes, cortes[1:] + [len(texto)])]
    out = []
    for t in tramos:
        plano = re.sub(r"\s+", " ", t)
        if PLENO_RE.search(plano) or (SEPARADA_RE.search(plano) and not COMISION_RE.search(plano)):
            out.append(plano)
    return out


def votaciones_punto(lineas):
    """Votaciones del Pleno en las líneas de un punto: [(subtitulo, datos)], y las frases sin leer."""
    votos, fallos = [], []
    for plano in _bloques_pleno("\n".join(lineas)):
        v, f = _votaciones_tramo(plano)
        votos += v
        fallos += f
    return votos, fallos


def _votaciones_tramo(plano):
    anclas = _anclas(plano)
    votos, fallos, fin_anterior = [], [], -1
    for ini, fin, etiqueta in anclas:
        if ini < fin_anterior:
            continue
        proxima = min([b[0] for b in anclas if b[0] >= fin] + [len(plano)])
        r = _clausula(plano[fin:proxima])
        if not r:
            fallos.append(plano[ini:ini + 250])
            continue
        totales, grupos, unanimidad, largo = r
        fin_anterior = fin + largo
        siguiente = min([a[0] for a in anclas if a[0] > fin_anterior] + [len(plano)])
        resto = plano[fin_anterior:min(siguiente, fin_anterior + 400)]
        subtitulo = None
        if etiqueta:
            subtitulo = re.sub(r"\s+", " ", etiqueta[0]).strip(" :.-")
            subtitulo = subtitulo[0].upper() + subtitulo[1:].lower() if subtitulo.isupper() else subtitulo
        votos.append((subtitulo, {
            "totales": totales, "grupos": _voto_grupos(grupos), "unanimidad": unanimidad,
            "resultado": _resultado(etiqueta[1] if etiqueta else None, resto, unanimidad),
            "enmienda": bool(etiqueta and re.match(r"enmienda", etiqueta[0], re.I)),
        }))
    return votos, fallos


def _parece_votado(lineas):
    """Si el punto parece tener una votación del Pleno (para medir lo que no se lee)."""
    return bool(_anclas(re.sub(r"\s+", " ", "\n".join(lineas)), separadas=False))


# ------------------------------------------------------------------------------------------- tipos

def _tipo(titulo):
    t = titulo.lower()
    if re.search(r"\bmoci[oó]n\b|\bproposici[oó]n urgente\b", t):
        return "mocion"
    if re.search(r"aprobaci[oó]n (?:inicial |definitiva )?(?:del )?presupuesto general|presupuesto general (?:del|de la|para)", t):
        return "presupuesto"
    if re.search(r"\bordenanza|\breglamento\b", t):
        return "ordenanza"
    if re.search(r"aprobaci[oó]n de(?:l| las?) actas?\b|nombramiento|representantes?|\bcese\b|composici[oó]n|"
                 r"retribuciones de los miembros|r[ée]gimen de dedicaci[oó]n|personal eventual|periodicidad de las sesiones", t):
        return "organizacion"
    if re.search(r"comparecencia|conocimiento|informe|dar cuenta|dación", t):
        return "control"
    return "acuerdo"


def _autor(titulo):
    m = re.search(r"moci[oó]n\s+(?:urgente\s+)?(?:que\s+presenta\s+)?(?:de\s+(?:la|el|los|las)\s+)?"
                  r"(?:(?:portavoz|concejal|concejala|concejales|portavoces)[^,]*?\s+)?(?:del|de)\s+(Grupo\s+Municipal\s+[^,.;]+?)"
                  r"(?:,|\s+relativ|\s+referid|\s+en\s+relaci|\s+sobre|\s+para|\s+por\s+la|\s+de\s+apoyo|\s+respecto|\s+instando|$)",
                  titulo, re.I)
    if m:
        g = re.sub(r"\s+", " ", m.group(1)).strip()
        return "Grupo Municipal " + re.sub(r"^Grupo\s+Municipal\s+", "", g, flags=re.I)
    return None


def _titulo_legible(t):
    return re.sub(r"\s+", " ", t).strip(" .-")


# ------------------------------------------------------------------------------------------ recogida

def _es_acta(doc):
    return doc[2].strip().lower() == "acta" or doc[2].strip().lower().startswith("acta ")


def _sesiones(ctx):
    """Plenos con acta, del más reciente al más antiguo: (sesión del buscador, acta, puntos del índice del vídeo).

    A cada sesión le añade «orden_base»: 0, o 50 para el segundo pleno del mismo día.
    """
    desde = ctx.desde(CUERPO)
    if desde:
        desde = (date.fromisoformat(desde) - timedelta(days=MARGEN_ACTAS)).isoformat()
    organo = ava.organo(ctx, BASE, "Pleno Municipal", ORGANO_PLENO)
    lista = [s for s in ava.sesiones(ctx, BASE, organo, desde)
             if not re.search(r"aplazad|demorad|desconvocad|suspendid", s["titulo"], re.I)]
    # Dos plenos el mismo día: el segundo (por hora) numera sus puntos desde 51.
    por_dia = {}
    for s in sorted(lista, key=lambda s: (s["fecha"], s["hora"])):
        s["orden_base"] = 50 * len(por_dia.setdefault(s["fecha"], []))
        por_dia[s["fecha"]].append(s["id"])
    for s in lista:
        try:
            docs, puntos = ava.ficha(ctx, BASE, s, cache=f"{CUERPO}/sesiones/{s['id']}.html",
                                     falta=lambda d: not any(_es_acta(x) for x in d))
        except (ErrorDescarga, urllib.error.URLError) as e:
            ctx.log(f"  ! {CUERPO} {s['fecha']}: ficha sin cargar ({e})")
            continue
        actas = [d for d in docs if _es_acta(d)]
        if actas:
            yield s, actas[0], puntos


def _texto_acta(ctx, doc_id, url):
    pdf = ctx.fetch(url, cache=f"{CUERPO}/actas/{doc_id}.pdf", timeout=180)
    return ctx.pdf_texto(pdf, layout=False)


def _revisar_grupos(votos):
    """Quita el voto por grupo de las votaciones con una errata evidente en el acta.

    A veces el acta nombra mal un grupo («12 votos en contra (10 del Grupo Municipal Popular…)»
    cuando eran del Socialista) y el grupo sale partido en dos sentidos con más concejales de los
    que tiene. El tamaño de cada grupo se estima con el mayor número que tiene en un solo sentido en
    las votaciones de la sesión; si un grupo «dividido» lo supera, esa votación se queda sin voto
    por grupo (los totales siguen). Devuelve cuántas se han corregido.
    """
    tam = {}
    for v in votos:
        for g in v["datos"]["grupos"]:
            if g.sentido != "dividido":
                n = g.si or g.no or g.abstencion
                if n:
                    tam[g.grupo] = max(tam.get(g.grupo, 0), n)
    malas = 0
    for v in votos:
        for g in v["datos"]["grupos"]:
            if g.sentido == "dividido" and sum(x or 0 for x in (g.si, g.no, g.abstencion)) > tam.get(g.grupo, 99):
                v["datos"]["grupos"] = []
                malas += 1
                break
    return malas


def votaciones_acta(texto, titulos=None):
    """Votaciones del Pleno en el texto de un acta.

    Devuelve (votaciones, estadística). Cada votación es un dict con orden (del punto en el acta),
    k (n.º dentro del punto, 0 si solo hay una), punto, titulo, subtitulo y datos (totales, grupos,
    unanimidad, resultado, enmienda).
    """
    titulos = titulos or {}
    est = {"puntos": 0, "con_votacion": 0, "leidos": 0, "sin_leer": [], "grupos_quitados": 0}
    out = []
    for orden, (pid, cabecera, ls) in enumerate(_puntos(_lineas(texto)), 1):
        est["puntos"] += 1
        votos, fallos = votaciones_punto(ls)
        if _parece_votado(ls) or votos:
            est["con_votacion"] += 1
            est["leidos"] += bool(votos)
        est["sin_leer"] += fallos
        titulo = _titulo_legible(titulos.get(_sin_signo(pid)) or cabecera or f"Punto {pid}")
        for k, (subtitulo, d) in enumerate(votos, 1 if len(votos) > 1 else 0):
            out.append({"orden": orden, "k": k, "punto": pid, "titulo": titulo, "subtitulo": subtitulo, "datos": d})
    est["grupos_quitados"] = _revisar_grupos(out)
    est["incoherentes"] = _quitar_incoherentes(out)
    return [v for v in out if v["datos"]["resultado"] or v["datos"]["totales"]["si"] is not None
            or v["datos"]["unanimidad"]], est


def _quitar_incoherentes(votos):
    """Deja sin totales ni grupos las votaciones con más votos que concejales (frase mal escrita en el acta)."""
    malas = 0
    for v in votos:
        t = v["datos"]["totales"]
        if sum(x or 0 for x in t.values()) > CUERPOS[0].escanos:
            v["datos"]["totales"] = {"si": None, "no": None, "abstencion": None}
            v["datos"]["grupos"] = []
            malas += 1
    return malas


def _sin_texto(texto):
    """Si el PDF es una imagen escaneada: casi no hay palabras en minúsculas (solo números sueltos o nada)."""
    palabras = len(re.findall(r"\b[a-záéíóúñ]{4,}\b", texto))
    return palabras < 45 or palabras * 1000 < 10 * len(re.sub(r"\s", "", texto))


def descargar(ctx):
    n, con_votacion, leidos = 0, 0, 0
    for s, (doc_id, _fichero, _nombre, url), puntos_video in _sesiones(ctx):
        try:
            texto = _texto_acta(ctx, doc_id, url)
        except (ErrorDescarga, urllib.error.URLError) as e:
            ctx.log(f"  ! {CUERPO} {s['fecha']}: acta sin descargar ({e})")
            continue
        if _sin_texto(texto):
            ctx.log(f"  ! {CUERPO} {s['fecha']}: el acta no tiene texto (PDF escaneado), se salta: {url}")
            continue
        votos, est = votaciones_acta(texto, _titulos_video(puntos_video))
        con_votacion += est["con_votacion"]
        leidos += est["leidos"]
        if est["sin_leer"]:
            ctx.log(f"  · {CUERPO} {s['fecha']}: {len(est['sin_leer'])} frases de votación sin leer, "
                    f"p. ej.: {est['sin_leer'][0][:160]}")
        if est["grupos_quitados"]:
            ctx.log(f"  · {CUERPO} {s['fecha']}: {est['grupos_quitados']} votaciones sin voto por grupo por una errata del acta")
        for v in votos:
            d, t = v["datos"], v["datos"]["totales"]
            tipo = _tipo(v["titulo"])
            yield Votacion(
                cuerpo=CUERPO, fecha=s["fecha"], titulo=v["titulo"], sesion=int(s["fecha"].replace("-", "")),
                numero=100 * (s["orden_base"] + v["orden"]) + v["k"], subtitulo=v["subtitulo"],
                tipo_iniciativa=tipo,
                tipo_votacion="enmiendas" if d["enmienda"] else ("mocion" if tipo == "mocion" else None),
                autor=_autor(v["titulo"]) if tipo == "mocion" else None,
                a_favor=t["si"], en_contra=t["no"], abstenciones=t["abstencion"],
                asentimiento=d["unanimidad"] and t["si"] is None,
                resultado=d["resultado"], grupos=d["grupos"], url=url, fuente="pdf-reglas",
                extra={"punto": v["punto"], "sesion_videoactas": s["url"]},
            )
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    ctx.log(f"  {CUERPO}: {leidos} de {con_votacion} puntos con votación leídos")


def documentos(ctx):
    n = 0
    for s, (doc_id, _fichero, _nombre, url), _puntos_video in _sesiones(ctx):
        yield Documento(cuerpo=CUERPO, fecha=s["fecha"], url=url, sesion=int(s["fecha"].replace("-", "")),
                        titulo=s["titulo"], extra={"id": doc_id, "sesion_videoactas": s["url"]})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    """Texto del acta (con la misma caché que descargar)."""
    return _texto_acta(ctx, doc.extra["id"], doc.url)
