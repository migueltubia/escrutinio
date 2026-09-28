"""Cortes de Castilla y León: votaciones del Pleno sacadas con reglas del Diario de Sesiones en HTML.

Fuente: la página del Diario de Sesiones de cada legislatura
(https://www.ccyl.es/RecursosInformacion/DiarioDeSesiones?Legislatura=11&SeriePublicacion=DS(P))
lleva incrustado en JSON (`var model = [...]`) el catálogo de diarios del Pleno: número, fecha de la
sesión, estado (0 definitivo, 1 borrador) y enlace al PDF (sirdoc.ccyl.es/.../DSPLN1100060A.pdf). Cada
diario definitivo tiene una «Versión TXT» en HTML
(/Publicaciones/TextoEntradaDiario?Legislatura=11&SeriePublicacion=DS(P)&NumeroPublicacion=60) con
el orden del día, el sumario y el texto marcado: cada intervención en su bloque y cada iniciativa con
una marca `CabeceraIniciativa tag="PNL/000735"`. No hay datos abiertos de votaciones.

Qué se saca: cada recuento que lee la Presidencia, que sigue siempre la misma fórmula («Votos emitidos:
ochenta. Votos a favor: cincuenta y dos. En contra: veintiocho. Abstenciones: cero. Queda aprobada la
proposición no de ley»), con los números en letra; el expediente es la última marca de iniciativa antes
del recuento; el subtítulo, lo que la Presidencia anuncia que se vota (punto, enmiendas, artículos...).
También las aprobaciones por asentimiento («¿Puede entenderse aprobada por asentimiento...?»). Título y
autor salen del orden del día del propio diario (o de la lectura del secretario si el punto no trae el
expediente).

Cobertura: Pleno de la IX (2015), X (2019), XI (2022) y XII (2026-) legislaturas; `sesion` es el número
del diario (una sesión de varios días tiene un diario por día, cada uno con su fecha).
Limitaciones: solo totales (el voto es electrónico pero no se publica por grupo ni nominal; en las
investiduras, por llamamiento, el diario trae el «Sí»/«No» de cada procurador, pero sin grupo, y no se
recoge); los diarios en borrador se saltan hasta que son definitivos; en las votaciones secretas los
votos en blanco van en `extra`. Cuando la Presidencia se corrige al leer el recuento se toma la lectura
que cuadra con los votos emitidos; si ninguna cuadra (erratas del diario, a veces anotadas con «[sic]»),
queda `extra["no_cuadra"]`, y si la suma supera los escaños los totales se dejan en blanco
(`extra["totales_descartados"]`). El debate de presupuestos se vota por secciones sin marca de iniciativa:
esas votaciones se atribuyen al proyecto de presupuestos del orden del día (con su expediente si lo trae).
"""

import html
import json
import re
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from ...territorio import Cuerpo, num_parlamento
from ..modelo import Iniciativa, Votacion

CUERPO = "parl-CL"
BASE = "https://www.ccyl.es"
CATALOGO = BASE + "/RecursosInformacion/DiarioDeSesiones?Legislatura={leg}&SeriePublicacion=DS(P)"
TEXTO = BASE + "/Publicaciones/TextoEntradaDiario?Legislatura={leg}&SeriePublicacion=DS(P)&NumeroPublicacion={num}"
PDF = "https://sirdoc.ccyl.es/sirdoc/PDF/PUBLOFI/DS/PLN/{leg}L/DSPLN{leg:02d}{num:05d}A.pdf"
FICHA = BASE + "/Publicaciones/PublicacionesIniciativa?Legislatura={leg}&CodigoIniciativa={tipo}&NumeroExpediente={num}"

LEGISLATURAS = {
    9: ("IX", "2015-06-16", "2019-06-21", 84),
    10: ("X", "2019-06-21", "2022-03-10"),
    11: ("XI", "2022-03-10", "2026-04-14"),
    12: ("XII", "2026-04-14", None, 82),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("CL"), "Cortes de Castilla y León", "Cortes (Castilla y León)", "autonomico", "CL",
           81, LEGISLATURAS, web=BASE + "/RecursosInformacion/DiarioDeSesiones?SeriePublicacion=DS(P)"),
]

NOTAS = ("Votaciones del Pleno con reglas sobre la versión HTML del Diario de Sesiones: expediente, totales "
         "(votos emitidos, a favor, en contra, abstenciones), resultado y asentimientos. Sin voto por grupo ni "
         "nominal. IX a XII legislaturas. Los diarios en borrador se recogen cuando pasan a definitivos.")

# Tipo de expediente (PNL/000735) -> tipo de iniciativa.
TIPOS = {"PNL": "pnl", "M": "mocion", "PL": "pl", "PPL": "ppl", "ILP": "ilp", "DLEY": "dl", "DL": "dl",
         "PREA": "ppl", "PLE": "ppl",  # reforma del Estatuto; proposición de ley ante el Congreso
         "I": "control", "CI": "control", "COMP": "control", "PLAN": "control", "PROG": "control", "DPG": "control",
         "DI": "otro", "RA": "organizacion", "REG": "organizacion", "COM": "organizacion", "EOT": "organizacion",
         "ESE": "organizacion", "SI": "investidura", "MC": "investidura", "C": "acuerdo", "ACUER": "acuerdo"}

# Iniciativas que no se votan (preguntas, interpelaciones, declaraciones institucionales): su marca en el diario no
# cambia el expediente vigente, para no colgarles las votaciones que vengan después (p. ej. las del presupuesto).
SIN_VOTO = {"I", "DI", "POP", "POC", "PE", "PO", "PREG"}

UNIDADES = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
            "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
            "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
            "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
            "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
            "ninguno": 0, "ninguna": 0, "ningun": 0, "nadie": 0,
            "siente": 7}  # errata frecuente del transcriptor («treinta y siente»); la suma con los emitidos lo confirma
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}

NUM = r"(\d+|no hay|[a-záéíóúñ]+(?:(?: y)? [a-záéíóúñ]+)?)"
EMITIDOS_RE = re.compile(r"Votos emitidos:?\s*" + NUM, re.I)
A_FAVOR_RE = re.compile(r"(?:Votos\s+)?(?:a favor(?: de la propuesta)?|favorables(?: a la propuesta| a la candidatura)?)"
                        r":?\s*" + NUM + r"|\bS[ií]:\s*" + NUM, re.I)
EN_CONTRA_RE = re.compile(r"(?:Votos\s+)?(?:e[nm] contra|contrarios|negativos):?\s*" + NUM + r"|\bNo:\s*" + NUM, re.I)
# «Abstenciones: veintinueve... perdón, veintiocho.» -> se queda la cifra corregida
CORRECCION_RE = re.compile(r"(\d+|[a-záéíóúñ]+(?: y [a-záéíóúñ]+)?)\s*(?:\.{2,}|…)\s*-?\s*perd[oó]n\s*-?\s*,\s*"
                           r"(\d+|[a-záéíóúñ]+(?: y [a-záéíóúñ]+)?)(?=[.;,\s])", re.I)
# «Votos emitidos: setenta y... setenta y ocho, perdón.» -> la segunda cifra
CORRECCION2_RE = re.compile(r"(\d+|[a-záéíóúñ]+(?: y)?)\s*(?:\.{2,}|…)\s*(\d+|[a-záéíóúñ]+(?: y [a-záéíóúñ]+)?),?\s+"
                            r"perd[oó]n\b", re.I)
ABST_RE = re.compile(r"Abstenciones:?\s*" + NUM + r"|\b(una|ninguna|\d+|[a-záéíóúñ]+(?: y [a-záéíóúñ]+)?)\s+abstenci", re.I)
BLANCO_RE = re.compile(r"(?:Votos\s+)?en blanco:?\s*" + NUM, re.I)
NULOS_RE = re.compile(r"(?:Votos\s+)?nulos:?\s*" + NUM, re.I)
RESULTADO_RE = re.compile(r"\b(aprobad|rechazad|investid|designad|elegid|proclamad|convalidad|derogad|ratificad|"
                          r"denegad)[oa]s?\b|"
                          r"\b(decae|decaen)\b|"
                          r"\bse (aprueba|rechaza)n?\b", re.I)
EXPEDIENTE_RE = re.compile(r"\b([A-Z]{1,6})/(\d{6})\b")
RELLENO_RE = re.compile(r"\s*(?:\[[^\]]*\]\.?|Comienza la votaci[oó]n\.?|Iniciamos la votaci[oó]n\.?|"
                        r"Se inicia la votaci[oó]n\.?|El resultado de la votaci[oó]n es el siguiente\.?)\s*", re.I)


def _plano(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _numero(s):
    """Número escrito en cifra o en letra («cuarenta y cuatro», «ninguno», «no hay»); None si no se entiende."""
    if s is None:
        return None
    s = _plano(s).strip()
    if s.isdigit():
        return int(s)
    if s == "no hay":
        return 0
    p = [x for x in s.split() if x != "y"]
    if not p:
        return None
    if len(p) == 2 and p[0] in DECENAS and UNIDADES.get(p[1], 99) < 10:  # «cuarenta y cuatro» o «cuarenta cuatro»
        return DECENAS[p[0]] + UNIDADES[p[1]]
    return UNIDADES.get(p[0], DECENAS.get(p[0]))  # la primera palabra («treinta Queda» sin punto)


def _limpio(fragmento):
    t = html.unescape(re.sub(r"<[^>]+>", "", fragmento)).replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _fecha(valor):
    """«/Date(1702422000000)/» (medianoche en Madrid, en milisegundos UTC) -> AAAA-MM-DD."""
    ms = int(re.search(r"-?\d+", valor).group())
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms, hours=12)).date().isoformat()


# ---------------------------------------------------------------- catálogo

def _catalogo(ctx, leg):
    """[(número, fecha, estado, eventos)] de los diarios del Pleno de una legislatura, del último al primero."""
    h = ctx.texto(CATALOGO.format(leg=leg))
    m = re.search(r"var model\s*=\s*(\[.*?\]);\s*\n", h, re.S)
    if not m:
        raise RuntimeError(f"{CUERPO}: la página del Diario de Sesiones de la legislatura {leg} no trae el catálogo")
    filas = []
    for d in json.loads(m.group(1)):
        if d.get("SeriePublicacion") == "DS(P)" and int(d.get("Legislatura") or 0) == leg:
            filas.append((int(d["NumeroPublicacion"]), _fecha(d["FechaPublicacion"]), d.get("Estado"),
                          (d.get("EventosEnPublicacion") or "").strip()))
    return sorted(filas, reverse=True)


# ---------------------------------------------------------------- diario

def _secciones(h):
    """(orden del día, texto) de la pestaña de texto enriquecido."""
    i, j = h.find('id="pilltextoenriquecido"'), h.find('id="pilltextoplano"')
    r = h[i:j] if i >= 0 else h
    a, b, c = r.find('class="OrdenDiaDiario"'), r.find('class="SumarioDiario"'), r.find('class="TextoDiario"')
    return (r[a:b] if a >= 0 and b > a else ""), (r[c:] if c >= 0 else "")


def _autor(texto):
    m = re.search(r"\b(?:presentad[oa]s?|formulad[oa]s?)(?: a la Junta de Castilla y León)? por (?:el |los |la )?(.+?),\s+"
                  r"(?=instando|para |relativ|sobre |con |a fin|que |consecuencia|de |en |por la que|publicad|y )", texto)
    return m.group(1).strip() if m else None


def _sin_cortesia(t):
    """Quita «Gracias. Quinto punto del orden del día:», «Procedemos a someter a votación...» del principio."""
    t = re.sub(r"^(?:muchas |muy bien[,.]? )?gracias[,.]?\s*(?:señora? (?:secretari[oa]|president[ea])[,.]?\s*)?", "",
               t, flags=re.I)
    t = re.sub(r"^[\wéáí]+ punto(?: del orden del día)?[.:]\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:y,? )?(?:en (?:primer|segundo|tercer|cuarto|quinto) lugar,? |finalmente,? |a continuación,? )?"
               r"(?:procedemos a |se procede (?:ahora |a continuación )?a |vamos a )?(?:someter a votación|votar|votamos)"
               r"(?:,? en los términos fijados por sus? proponentes?,?)?\s+", "", t, flags=re.I)
    return t[:1].upper() + t[1:] if t else t


def _titulo(texto):
    """Título legible de un punto del orden del día: sin numeración, expediente, autor ni referencia al boletín."""
    t = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", _sin_cortesia(texto))
    t = re.sub(r",?\s*publicad[oa]s? en el Bolet[ií]n Oficial.*$", "", t)
    t = EXPEDIENTE_RE.sub("", t)
    t = re.sub(r",\s*(?:presentad[oa]s?|formulad[oa]s?)(?: a la Junta de Castilla y León)? por (?:el |los |la )?.+?,\s+"
               r"(?=instando|para |relativ|sobre |con |a fin|que |consecuencia|de |en |por la que|y )", " ", t)
    t = re.sub(r"^(Moción|Interpelación|Proposición [Nn]o de [Ll]ey|Proposición de Ley|Proyecto de Ley),\s+", r"\1 ", t)
    t = re.sub(r"\s*,\s*,", ",", t)
    t = re.sub(r"\s+,", ",", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,.")


def _orden_del_dia(fragmento):
    """expediente -> (título, autor)."""
    fichas = {}
    for p in re.findall(r"<p[^>]*>(.*?)</p>", fragmento, re.S):
        t = _limpio(p)
        for tipo, num in EXPEDIENTE_RE.findall(t):
            fichas.setdefault(f"{tipo}/{num}", (_titulo(t), _autor(t)))
    return fichas


def _parrafos(fragmento):
    """[(orador, expediente vigente, texto)] del texto de la sesión, en orden."""
    out, orador, exp = [], None, None
    for attrs, inner in re.findall(r"<p([^>]*)>(.*?)</p>", fragmento, re.S):
        t = _limpio(inner)
        if 'class="Orador"' in attrs:
            orador = t
            continue
        if "CabeceraIniciativa" in attrs:
            m = EXPEDIENTE_RE.search(re.search(r'tag="([^"]*)"', attrs, re.S).group(1) if "tag=" in attrs else t)
            if m and m.group(1) not in SIN_VOTO:
                exp = f"{m.group(1)}/{m.group(2)}"
                out.append((orador, exp, None))  # marca: separa la lectura del secretario
            continue
        if not t:
            continue
        m = re.match(r"^.{0,120}?\b([A-Z]{1,6})/(\d{4,6})\s*$", t) if len(t) < 150 else None
        if m and m.group(1) not in SIN_VOTO:  # rótulo «Votación Enmiendas PL/000024», «... lectura única PPL/00027»
            exp = f"{m.group(1)}/{int(m.group(2)):06d}"
        out.append((orador, exp, t))
    return out


def _cuenta(segmento):
    """Totales de un recuento «Votos emitidos: ...» (None donde no se lee).

    La Presidencia a veces se corrige sobre la marcha («Abstenciones: treinta y seis. Perdón, en contra: treinta
    y seis. Abstenciones: cero»): se prueba con la primera y con la última cifra de cada concepto y se queda la
    lectura que cuadra con los votos emitidos (si ninguna cuadra, la última si hubo corrección).
    """
    def corrige(m):
        return m.group(2) if _numero(m.group(1)) is not None and _numero(m.group(2)) is not None else m.group(0)

    seg = CORRECCION_RE.sub(corrige, segmento)
    seg = CORRECCION2_RE.sub(corrige, seg)
    seg = re.sub(r"\[[^\]]*\]", " ", seg)  # notas del transcriptor: «[sic]», «[el marcador refleja...]»

    def lectura(ultima):
        d = {}
        for clave, rx in (("emitidos", EMITIDOS_RE), ("a_favor", A_FAVOR_RE), ("en_contra", EN_CONTRA_RE),
                          ("abstenciones", ABST_RE), ("en_blanco", BLANCO_RE), ("nulos", NULOS_RE)):
            valores = [v for v in (_numero(next((g for g in m.groups() if g), None)) for m in rx.finditer(seg))
                       if v is not None]
            d[clave] = (valores[-1] if ultima else valores[0]) if valores else None
        if re.search(r"sin votos? (?:negativos|en contra)", seg, re.I):
            d["en_contra"] = 0 if d["en_contra"] is None else d["en_contra"]
            if re.search(r"ni abstenciones", seg, re.I) and d["abstenciones"] is None:
                d["abstenciones"] = 0
        return d

    def cuadra(d):
        return d["emitidos"] is not None and d["emitidos"] == sum(
            d[k] or 0 for k in ("a_favor", "en_contra", "abstenciones", "en_blanco", "nulos"))

    primera, ultima = lectura(False), lectura(True)
    if cuadra(primera):
        return primera
    if cuadra(ultima) or re.search(r"perd[oó]n|\.{3}|…", seg, re.I):
        return ultima
    return primera


def _resultado(texto):
    m = RESULTADO_RE.search(texto or "")
    if not m:
        return None
    palabra = next(g for g in m.groups() if g).lower()
    return "rechazada" if palabra.startswith(("rechaz", "deca", "derog", "deneg")) else "aprobada"


def _anuncio(parrafos, i, previo):
    """Lo que la Presidencia anuncia que se vota (texto antes del recuento o párrafo anterior)."""
    pre = RELLENO_RE.sub(" ", previo).strip()
    if len(pre) < 25:
        for k in range(i - 1, max(i - 3, -1), -1):
            orador, _exp, t = parrafos[k]
            if t is None or orador != parrafos[i][0] or "Votos emitidos" in t:
                break
            pre = (RELLENO_RE.sub(" ", t).strip() + " " + pre).strip()
            if len(pre) >= 25:
                break
    pre = re.sub(r"\s{2,}", " ", pre).strip()
    if len(pre) > 400:
        corte = pre.rfind(". ", 0, 400)
        pre = pre[:corte + 1] if corte > 100 else pre[:400] + "…"
    return pre or None


OBJETO_RE = re.compile(r"(?:someter a votación|sometemos a votación|votamos|votar|votaremos|votación de)"
                       r"(?:,? (?:en primer lugar|a continuación|ahora|finalmente),?)?\s+(?:la |las |el |los )?"
                       r"(enmiendas?|artículos?|dictamen|disposici|exposición|proposición de ley|proyecto de ley|"
                       r"toma en consideración|convalidación|propuesta de tramitación|trámite)", re.I)


def _tipo_votacion(tipo, texto):
    t = (texto or "").lower()
    if tipo == "investidura":
        return "investidura"
    m = OBJETO_RE.search(t)  # lo que se vota según la Presidencia manda sobre lo que se mencione después
    if m:
        obj = m.group(1)
        if obj.startswith("enmienda"):
            return "enmiendas"
        if obj.startswith(("artículo", "dictamen", "disposici", "exposición")):
            return "articulado"
        if obj in ("proposición de ley", "proyecto de ley"):
            return "conjunto" if tipo in ("pl", "ppl", "ilp", "presupuesto") else None
        if obj == "toma en consideración":
            return "toma_consideracion"
        if obj == "convalidación":
            return "convalidacion"
        if obj in ("propuesta de tramitación", "trámite"):
            return "organizacion"
    if "totalidad" in t:
        return "totalidad"
    if "toma en consideración" in t:
        return "toma_consideracion"
    if "convalidaci" in t:
        return "convalidacion"
    if "tramitación como proyecto de ley" in t:
        return "tramitacion_ley"
    if "lectura única" in t and "tramitación" in t:
        return "organizacion"
    if "investidura" in t or "candidato a la presidencia" in t:
        return "investidura"
    if re.search(r"designaci|senador|vocales|miembros del consejo", t):
        return "nombramiento"
    if "enmienda" in t and tipo not in ("pnl", "mocion"):
        return "enmiendas"
    if tipo in ("pl", "ppl", "ilp", "presupuesto") and re.search(
            r"\bartículos (?:n[úu]meros? )?\d|exposición de motivos|disposici[oó]n(?:es)? (?:adicional|final|transitoria|derogatoria)", t):
        return "articulado"
    if tipo in ("pnl", "mocion"):
        return tipo
    return None


def _votaciones(h):
    """(fichas del orden del día, [dict] de votaciones) de la versión HTML de un diario."""
    orden, texto = _secciones(h)
    fichas = _orden_del_dia(orden)
    parrafos = _parrafos(texto)
    # El debate del presupuesto se vota por secciones sin marca de iniciativa: lo votado antes de cualquier marca en
    # un diario cuyo orden del día trae el proyecto de presupuestos es de ese proyecto.
    presupuestos = None
    for p in re.findall(r"<p[^>]*>(.*?)</p>", orden, re.S):
        t = _limpio(p)
        if re.search(r"Proyecto de Ley de Presupuestos Generales", t, re.I):
            m = EXPEDIENTE_RE.search(t)
            presupuestos = (_titulo(t), f"{m.group(1)}/{m.group(2)}" if m else None)
            break
    lecturas = {}  # expediente -> primera lectura del secretario tras su marca (título si no está en el orden)
    for k, (orador, exp, t) in enumerate(parrafos):
        if t is None and exp and exp not in fichas and exp not in lecturas:
            sig = next((x for x in parrafos[k + 1:k + 4] if x[2] and x[0] and "SECRETARI" in x[0]), None)
            if sig:
                lecturas[exp] = _titulo(sig[2])[:500]
    votos = []
    for i, (orador, exp, t) in enumerate(parrafos):
        if not t:
            continue
        pos = t.find("Votos emitidos")
        if pos >= 0:
            fin = RESULTADO_RE.search(t, pos)
            segmento = t[pos:fin.start() if fin else pos + 400]
            d = _cuenta(segmento)
            if d["a_favor"] is None and d["en_contra"] is None:
                continue
            resto = t[pos + len(segmento):]
            if _resultado(resto) is None:
                siguiente = next((x[2] for x in parrafos[i + 1:i + 3] if x[2]), "")
                resto = siguiente[:400] if "Votos emitidos" not in siguiente[:400] else ""
            anuncio = _anuncio(parrafos, i, t[:pos])
            if exp and not exp.startswith("DL") and re.search(r"convalidaci[oó]n del (?:real )?decreto", anuncio or "", re.I):
                exp = None  # el decreto-ley no lleva marca propia: la vigente es la del punto anterior
            d.update(expediente=exp, anuncio=anuncio, resultado=_resultado(resto),
                     asentimiento=False, texto=t[pos:pos + 400],
                     presupuestos=presupuestos if exp is None and not any(x[2] is None for x in parrafos[:i]) else None)
            votos.append(d)
            continue
        if "asentimiento" in t and "¿" in t and "?" in t[t.find("¿"):]:
            # «¿Puede entenderse aprobada por asentimiento...? [Queda aprobada]»: vale si la Presidencia lo
            # da por aprobado en la misma intervención y nadie pide votación
            cierre = t.find("?", t.find("¿")) + 1
            despues = t[cierre:]
            sig = next((x for x in parrafos[i + 1:i + 3] if x[2]), None)
            if not despues.strip() and sig and sig[0] == orador:
                despues = sig[2][:300]
            if not re.search(r"\b(?:aprobad|aprueb)", despues, re.I):
                continue
            if any(x[2] and "Votos emitidos" in x[2] for x in parrafos[i + 1:i + 4]):
                continue  # hubo objeción y se votó
            pregunta = t[t.find("¿"):cierre]
            # lo aprobado: «¿Puede entenderse aprobada por asentimiento la dación de cuentas de...?»
            objeto = re.sub(r"^¿\s*[\w ]{0,40}?(?:aprobad[oa]s?|aprobarse)\s+", "", pregunta, flags=re.I)
            objeto = re.sub(r"\s*por asentimiento\s*", " ", objeto, flags=re.I).strip(" ?")
            anuncio = objeto[:1].upper() + objeto[1:] if len(objeto) > 25 else \
                (_anuncio(parrafos, i, t[:t.find("¿")]) or pregunta)
            d = {"emitidos": None, "a_favor": None, "en_contra": None, "abstenciones": None, "en_blanco": None,
                 "nulos": None, "expediente": exp, "anuncio": anuncio,
                 "resultado": "aprobada", "asentimiento": True, "texto": t[:400]}
            votos.append(d)
    return fichas, lecturas, votos


def _votacion(leg, num, fecha, n, v, fichas, lecturas, eventos):
    exp = v["expediente"]
    titulo, autor = fichas.get(exp, (None, None)) if exp else (None, None)
    if exp is None and v.get("presupuestos"):
        titulo, exp = v["presupuestos"]
    propio = _sin_cortesia(v["anuncio"]) if v["anuncio"] and not exp else None
    if propio and len(propio) < 60 and eventos:
        propio = None  # anuncio demasiado escueto: mejor el asunto del catálogo
    titulo = titulo or lecturas.get(exp) or propio or eventos or v["anuncio"] or v["texto"]
    tipo = TIPOS.get(exp.split("/")[0], "otro") if exp else None
    if (tipo in ("pl", None) and "presupuestos generales" in (titulo or "").lower()) or v.get("presupuestos"):
        tipo = "presupuesto"
    contexto = " ".join(x for x in (v["anuncio"], v["texto"], titulo if not exp else "") if x)
    if tipo is None and re.search(r"investidura|candidato a la presidencia", contexto, re.I):
        tipo = "investidura"
    extra = {"texto": v["texto"]}
    for k in ("en_blanco", "nulos"):
        if v.get(k) is not None:
            extra[k] = v[k]
    suma = sum(v[k] or 0 for k in ("a_favor", "en_contra", "abstenciones", "en_blanco", "nulos"))
    if v["emitidos"] is not None and suma != v["emitidos"]:
        extra["no_cuadra"] = f"emitidos {v['emitidos']}, suma {suma}"
    if sum(v[k] or 0 for k in ("a_favor", "en_contra", "abstenciones")) > CUERPOS[0].escanos_de(leg):
        # lectura imposible (errata del diario, «Cincuenta abstenciones» por cinco): el texto queda en extra
        extra["totales_descartados"] = f"{v['a_favor']}-{v['en_contra']}-{v['abstenciones']}"
        v = {**v, "a_favor": None, "en_contra": None, "abstenciones": None}
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=num, numero=n, legislatura=leg,
        subtitulo=v["anuncio"] if v["anuncio"] and v["anuncio"] != titulo else None, expediente=exp,
        tipo_iniciativa=tipo, tipo_votacion=_tipo_votacion(tipo, contexto), autor=autor,
        a_favor=v["a_favor"], en_contra=v["en_contra"], abstenciones=v["abstenciones"], presentes=v["emitidos"],
        asentimiento=v["asentimiento"], resultado=v["resultado"],
        url=TEXTO.format(leg=leg, num=num), fuente="html-reglas", extra={**extra, "pdf": PDF.format(leg=leg, num=num)})


def _descargar_diario(ctx, leg, num):
    return ctx.texto(TEXTO.format(leg=leg, num=num), cache=f"{CUERPO}/txt/{leg}-{num:03d}.html")


def _por_adelantado(pool, funcion, elementos, adelanto=3):
    """[(elemento, funcion(elemento))] en orden, con hasta `adelanto` descargas en marcha a la vez."""
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
    desde = ctx.desde(CUERPO, margen_dias=45)  # un diario en borrador puede tardar semanas en ser definitivo
    n_total, iniciativas = 0, set()
    for leg in sorted(LEGISLATURAS, reverse=True):
        fin = LEGISLATURAS[leg][2]
        if desde and fin and fin < desde:
            break
        diarios = []
        for num, fecha, estado, eventos in _catalogo(ctx, leg):
            if desde and fecha < desde:
                break
            if estado not in (0, None):
                ctx.log(f"  {CUERPO}: DS(P) {num}/{leg} del {fecha} en borrador; se recogerá cuando sea definitivo")
                continue
            diarios.append((num, fecha, eventos))
        # hasta 3 descargas a la vez, pero se procesan en orden (del más reciente al más antiguo)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for (num, fecha, eventos), h in _por_adelantado(pool, lambda d: _descargar_diario(ctx, leg, d[0]), diarios):
                fichas, lecturas, votos = _votaciones(h)
                for n, v in enumerate(votos, 1):
                    exp = v["expediente"]
                    if exp and exp not in iniciativas and (exp in fichas or exp in lecturas):
                        iniciativas.add(exp)
                        tipo, numero = exp.split("/")
                        tit, autor = fichas.get(exp, (lecturas.get(exp), None))
                        yield Iniciativa(CUERPO, exp, tit, legislatura=leg, tipo_iniciativa=TIPOS.get(tipo, "otro"),
                                         autor=autor, url=FICHA.format(leg=leg, tipo=tipo, num=int(numero)))
                    vo = _votacion(leg, num, fecha, n, v, fichas, lecturas, eventos)
                    if vo.resultado is None and vo.a_favor is None and not vo.asentimiento:
                        ctx.log(f"  {CUERPO}: DS(P) {num}/{leg}, votación {n} sin resultado ni totales legibles: "
                                f"{v['texto'][:120]}")
                        continue
                    yield vo
                    n_total += 1
                    if ctx.limite and n_total >= ctx.limite:
                        return
