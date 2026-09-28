"""Cortes de Castilla-La Mancha: votaciones del Pleno sacadas con reglas del Diario de Sesiones (PDF).

Fuente: el buscador del Diario de Sesiones (https://www.cortesclm.es/web2/paginas/diario.php, que va
dentro de un iframe de la web). Un POST a cdiario.php con la legislatura y el tipo «pleno» devuelve
todos los diarios del Pleno de esa legislatura con su número y fecha, y cada uno está en una URL fija:
publicaciones/diario/pleno/pleno{leg}/pdf/{num:03d}.pdf.

Qué se saca: el diario anuncia cada votación con una llamada muy regular de la Presidencia («¿Diputadas
y diputados que votan a favor? 4. ¿... en contra? 17. ¿... se abstienen? 12.», a veces abreviada «¿Votos
a favor? ... ¿Votos en contra? ... ¿Abstenciones?», con «No hay» o «Ninguno» cuando la cifra es cero) y
la propia Presidencia repite el recuento en una frase de resumen («El resultado de la votación es el
siguiente: 33 diputadas y diputados presentes, 4 votos a favor, 17 en contra, 12 abstenciones, por lo
que se rechaza...», o, en diarios más antiguos, «En consecuencia, con 4 votos a favor..., queda
rechazada...»). Las dos lecturas casi siempre coinciden; cuando no, se prefiere la que cuadra con los
presentes (la otra suele haberse comido una cifra: «3» por «13»). El voto telemático que la Presidencia
suma aparte («28 presentes, más los 5 que ejercen su derecho telemático») se añade al recuento.

El orden del día, al principio de cada diario, numera los puntos con su expediente («expediente
11/MOC-00001»); el anuncio de cada votación en el cuerpo del diario («Pasamos al segundo punto del
orden del día...», «En relación con el tercer punto...») permite emparejar cada votación con su punto
para sacar el expediente. Un «Debate General» (varias iniciativas acumuladas, sin expediente único)
acaba en una «Propuesta de Resolución» por grupo, cada una con su propia votación: el título es el
asunto del debate y el subtítulo y el autor, el grupo que la presenta («En primer lugar, se somete a
votación la Propuesta de Resolución presentada por el Grupo Parlamentario Vox»). No se publica el voto
por grupo ni el nominal (solo se puede deducir por la aritmética de grupos, que no se calcula aquí). Las
votaciones por papeletas a varios candidatos (Mesa, senadores) no dan un recuento a favor/en contra y no
se leen con reglas; van al LLM, igual que las investiduras por llamamiento y los recuentos ilegibles.

Cobertura: Pleno desde la VIII legislatura (junio de 2011) hasta hoy, unos 360 diarios.
Limitaciones: el certificado TLS de la web no valida (cadena incompleta), así que se descarga sin
verificarlo; una sesión de varios días va en un solo diario con la fecha del primero; no hay datos
estructurados (el buscador de iniciativas, /kiniciativas, no responde).
"""

import re
import unicodedata

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import CACHE_DIR
from ..modelo import TIPOS_INICIATIVA, Documento, Votacion

CUERPO = "parl-CM"
BASE = "https://www.cortesclm.es/web2/paginas/"
BUSCADOR = BASE + "diario.php"

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("CM"), "Cortes de Castilla-La Mancha", "Cortes (Castilla-La Mancha)", "autonomico",
           "CM", 33,
           {8: ("VIII", "2011-06-16", "2015-06-18", 49),
            9: ("IX", "2015-06-18", "2019-06-19"),
            10: ("X", "2019-06-19", "2023-06-22"),
            11: ("XI", "2023-06-22", None)},
           web=BUSCADOR),
]

NOTAS = ("Votaciones del Pleno con reglas sobre el Diario de Sesiones en PDF: la llamada de la Presidencia "
         "(«¿Diputadas y diputados que votan a favor?...») y su frase de resumen («El resultado de la votación "
         "es el siguiente: N presentes, N a favor...»), con el voto telemático sumado cuando se anuncia aparte; "
         "se prefiere la lectura que cuadra con los presentes. El expediente sale del orden del día, emparejado "
         "con el anuncio de cada votación («Pasamos al segundo punto...»); un Debate General acaba en una "
         "Propuesta de Resolución por grupo (título el asunto, subtítulo y autor el grupo). Sin voto por grupo "
         "ni nominal. VIII a XI legislaturas (desde 2011). Las votaciones por papeletas a varios candidatos, las "
         "investiduras por llamamiento y los recuentos que las reglas no pueden leer van al LLM. Certificado TLS "
         "roto: se descarga sin verificar.")

FILA_RE = re.compile(r'Pleno n[úu]m\.\s*(\d+)\s*</div></td>\s*<td><div align="left">([^<]*)</div></td>\s*'
                     r'<td><div align="center">(\d{2})-(\d{2})-(\d{4})</div></td>\s*'
                     r'<td>\s*<a href="([^"]+\.pdf)"', re.S)
OPCION_RE = re.compile(r'<option value="(\d+)"\s*>\s*[IVXLC]+ Legislatura')


def _html(ctx, url, data=None, cache=None):
    return ctx.fetch(url, data=data, cache=cache, inseguro=True).decode("iso-8859-1", "replace")


def _legislaturas(ctx):
    """Legislaturas declaradas, de la más reciente a la más antigua (avisa si la web ya tiene otra)."""
    declaradas = CUERPOS[0].legislaturas
    en_web = {int(n) for n in OPCION_RE.findall(_html(ctx, BUSCADOR))}
    for n in sorted(en_web - set(declaradas)):
        if n > max(declaradas):
            ctx.log(f"  ! {CUERPO}: la web ya tiene la legislatura {romano(n)}, sin declarar en CUERPOS")
    return sorted(declaradas, reverse=True)


def _diarios(ctx, leg):
    """Diarios del Pleno de una legislatura: [(fecha, número, url)], del más reciente al más antiguo."""
    cerrada = CUERPOS[0].legislaturas[leg][2] is not None
    datos = {"legislatura": leg, "tipo": "pleno", "organo": "0", "anyo": "", "diarioses": "", "fecha2": "",
             "fecha3": "", "Submit": "Buscar"}
    # El listado de una legislatura cerrada ya no cambia: se guarda; el de la actual, no.
    h = _html(ctx, BASE + "cdiario.php", data=datos, cache=f"{CUERPO}/listados/pleno{leg}.html" if cerrada else None)
    h = re.sub(r"(?s)<!--.*?-->", "", h)
    filas = []
    for num, organo, d, m, a, ruta in FILA_RE.findall(h):
        if organo.strip().lower().startswith("pleno"):
            filas.append((f"{a}-{m}-{d}", int(num), BASE + ruta))
    return sorted(set(filas), reverse=True)


def _nombre(url):
    return re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/diario/", 1)[-1])


def _texto_diario(ctx, url):
    """Texto del diario (la web necesita descargar sin verificar el certificado)."""
    raw = ctx.fetch(url, cache=f"{CUERPO}/diarios/{_nombre(url)}", inseguro=True)
    return ctx.pdf_texto(raw, layout=False)


def texto(ctx, doc):
    return _texto_diario(ctx, doc.url)


# ---------------------------------------------------------------- texto: limpieza de cabeceras y pies

MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
DIAS = "Lunes|Martes|Mi[ée]rcoles|Jueves|Viernes|S[áa]bado|Domingo"
# cabecera/pie de página: «Sesión Plenaria» / «XI Legislatura» / «Diario de Sesiones núm. N» / fecha / «Pág. N»
# (el orden y qué líneas salen varía según la época del diario)
RUIDO_SOLO_RE = re.compile(
    r"^(?:SESI[ÓO]N PLENARIA|Sesi[oó]n Plenaria|[IVXLC]{1,6} Legislatura|"
    r"Diario de Sesiones(?: del Pleno)?\s*n[uú]m\.?\s*\d+\.?|"
    r"P[aá]g\.?\s*\d+\.?)$", re.I)
FECHA_LINEA_RE = re.compile(
    r"^(?:(?:" + DIAS + r"),?\s+)?\d{1,2}(?:\s+y\s+\d{1,2})?\s+de\s+(?:" + MESES + r")\s+de\s+\d{4}\.?$", re.I)
ORADOR_RE = re.compile(r"^(?:SE[ÑN]OR|SE[ÑN]ORA|DON|DO[ÑN]A)\b.*:")


def _lineas_utiles(texto_crudo):
    """Líneas del diario sin las cabeceras/pies de página ni las líneas de fecha sueltas."""
    out = []
    for ln in texto_crudo.replace("\f", "\n").splitlines():
        ln = ln.strip()
        if not ln or RUIDO_SOLO_RE.match(ln) or FECHA_LINEA_RE.match(ln):
            continue
        out.append(ln)
    return out


# ---------------------------------------------------------------- números en letra

_UNIDADES = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
             "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
             "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
             "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
             "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
_DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60}
_NEGATIVOS = {"ninguno", "ninguna", "ningun", "no"}


def _plano(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def _numero_de_palabra(s):
    p = _plano(s)
    if p in _NEGATIVOS:
        return 0
    if p in _UNIDADES:
        return _UNIDADES[p]
    m = re.match(r"^(treinta|cuarenta|cincuenta|sesenta)(?:\s+y\s+(\w+))?$", p)
    if m:
        return _DECENAS[m.group(1)] + (_UNIDADES.get(m.group(2), 0) if m.group(2) else 0)
    return None


def _entero(s):
    if s is None:
        return None
    s = s.strip().strip(".").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    return _numero_de_palabra(s)


# ---------------------------------------------------------------- lectura de recuentos

_PAR = r"(?:\([^)]{0,60}\)\.?\s*)*"  # una acotación entre la pregunta y la respuesta, p. ej. «(Pausa).»
_VAL = r"(No\s+hay\.?|[A-Za-zÁÉÍÓÚáéíóúÑñ]+(?:\s+y\s+[a-zá-ú]+)?\.?|\d{1,3}\.?)"

FAVOR_Q_RE = re.compile(r"¿[^?]{0,110}?(?:vot[ae]n?|votos?)\s+a\s+favor[^?]{0,60}\?\s*" + _PAR + _VAL, re.I)
CONTRA_Q_RE = re.compile(r"¿[^?]{0,110}?en\s+contra[^?]{0,60}\?\s*" + _PAR + _VAL, re.I)
ABST_Q_RE = re.compile(r"¿[^?]{0,110}?(?:absti[ée]nen?|abstenci[oó]n)[^?]{0,60}\?\s*" + _PAR + _VAL, re.I)
NOHAY_CONTRA_RE = re.compile(
    r"No\s+hay(?:\s+diputad\w+(?:\s+y\s+diputad\w+)?\s+que\s+vot[ae]n?)?\s+(?:votos?\s+)?en\s+contra|"
    r"ning[uú]n\s+voto\s+en\s+contra|(?:diputad\w+(?:\s+y\s+diputad\w+)?\s+que\s+)?vot[ae]n?\s+en\s+contra\s+no\s+hay|"
    r"\bninguno\s+en\s+contra\b", re.I)
NOHAY_ABST_RE = re.compile(
    r"No\s+hay(?:\s+ning\w+)?\s+abstenci[oó]n(?:es)?|ninguna\s+abstenci[oó]n|sin\s+abstenci[oó]n(?:es)?|"
    r"no\s+habiendo\s+abstenci[oó]n(?:es)?|no\s+se\s+abstien\w*|\bni\s+se\s+abstien\w*|"
    r"no\s+hay,?\s+por\s+tanto,?\s+abstenci[oó]n(?:es)?", re.I)
TELEMATICO_RE = re.compile(
    r"m[áa]s\s+(?:l[oa]s?\s+)?(\d{1,3}|[a-záéíóú]+)\s+(?:que\s+ejerce\w*\s+su\s+derecho\s+)?telem[áa]tic\w*", re.I)

RESULTADO_ANCLA_RE = re.compile(r"[Ee]l\s+resultado\s+de\s+la\s+votaci[oó]n\s+es(?:\s+el\s+siguiente)?:?\s*", re.I)
ASENTIMIENTO_RE = re.compile(
    r"[SsQq]e\s+aprueba(?:n)?\s*,?\s*(?:por\s+lo\s+tanto,?\s*)?por\s+asentimiento\.|"
    r"[Qq]ueda(?:n)?\s+aprobad[oa]s?\s+por\s+asentimiento\.", re.I)
# votación por papeletas a varios candidatos (Mesa, senadores...): no da un recuento a favor/en contra
CANDIDATURA_RE = re.compile(
    r"votos?\s+(?:para|a\s+favor\s+de)\s+(?:don|do[ñn]a)\s+[A-ZÁÉÍÓÚÑ]|"
    r"votos?\s+en\s+blanco.{0,60}votos?\s+nul[oa]s|papeletas?\b", re.I)

PRESENTES_RE = re.compile(
    r"(\d{1,3})\s+diputad\w+(?:\s+y\s+diputad\w+)?\s+presentes|"
    r"diputad\w+(?:\s+y\s+diputad\w+)?\s+presentes:?\s*(\d{1,3})", re.I)
FAVOR2_RE = re.compile(r"(\d{1,3})\s+votos?\s+a\s+favor|votos?\s+a\s+favor:?\s*(\d{1,3})", re.I)
CONTRA2_RE = re.compile(
    r"(\d{1,3})\s+(?:votos?\s+)?en\s+contra|(?:votos?\s+)?en\s+contra:?\s*(\d{1,3})|(ning[uú]n\s+(?:voto\s+)?en\s+contra)",
    re.I)
ABST2_RE = re.compile(r"(\d{1,3})\s+abstenci\w*|abstenci\w*:?\s*(\d{1,3})|(ninguna\s+abstenci[oó]n)", re.I)
RESULT_RE = re.compile(r"\b(aprob\w+|rechaz\w+|desestim\w+|decae|decaen)\b", re.I)

VENTANA_RESUMEN = 320  # caracteres tras el verbo del resultado en los que se buscan los campos, como mucho
VENTANA_ROLL = 700     # si no se encuentra el verbo, hasta dónde se considera la lectura


def _valor_pregunta(m, bloque):
    """Entero de la respuesta a una pregunta de la llamada («12.», «No hay.», «Ninguno»), con el voto
    telemático sumado si la Presidencia lo anuncia justo después («28 presentes, más los 5 telemáticos»)."""
    if not m:
        return None
    v = m.group(1)
    base = 0 if _plano(v).startswith("no hay") else _entero(v)
    if base is not None:
        mt = TELEMATICO_RE.search(bloque, m.end(), m.end() + 80)
        if mt:
            extra = _entero(mt.group(1))
            if extra is not None:
                base += extra
    return base


def _leer_llamada(bloque):
    """(a_favor, en_contra, abstenciones) leídos de las preguntas de la Presidencia en `bloque`."""
    favor = _valor_pregunta(FAVOR_Q_RE.search(bloque), bloque)
    contra = _valor_pregunta(CONTRA_Q_RE.search(bloque), bloque)
    if contra is None and NOHAY_CONTRA_RE.search(bloque):
        contra = 0
    abst = _valor_pregunta(ABST_Q_RE.search(bloque), bloque)
    if abst is None and NOHAY_ABST_RE.search(bloque):
        abst = 0
    return favor, contra, abst


def _leer_resumen(ventana):
    """(presentes, a_favor, en_contra, abstenciones, resultado) de la frase con que la Presidencia resume
    la votación (antes o después del verbo del resultado, según la época del diario)."""
    mp = PRESENTES_RE.search(ventana)
    presentes = _entero(next((g for g in (mp.groups() if mp else ()) if g), None)) if mp else None
    mf = FAVOR2_RE.search(ventana)
    favor = _entero(next((g for g in mf.groups() if g), None)) if mf else None
    mc = CONTRA2_RE.search(ventana)
    contra = (0 if mc.group(3) else _entero(mc.group(1) or mc.group(2))) if mc else None
    ma = ABST2_RE.search(ventana)
    abst = (0 if ma.group(3) else _entero(ma.group(1) or ma.group(2))) if ma else None
    mr = RESULT_RE.search(ventana)
    resultado = ("aprobada" if mr.group(1).lower().startswith("aprob") else "rechazada") if mr else None
    return presentes, favor, contra, abst, resultado


def _combinar_totales(llamada, resumen, escanos):
    """Reconcilia el recuento de la llamada y el de la frase resumen.

    Con las dos lecturas completas y distintas, gana la que cuadre con los presentes (la otra suele
    haberse comido una cifra, «3» por «13»); si solo hay una lectura completa, o las dos coinciden, se usa
    esa sin exigir que cuadre con los presentes (puede haber presentes que no votan). Si hay dos lecturas
    completas y distintas y ninguna cuadra con los presentes, se descartan los totales.
    """
    fav_l, con_l, abs_l = llamada
    presentes, fav_r, con_r, abs_r, resultado = resumen
    extra = {}

    def total(a, b, c):
        return None if a is None or b is None or c is None else a + b + c

    tot_l, tot_r = total(fav_l, con_l, abs_l), total(fav_r, con_r, abs_r)
    distintas = tot_l is not None and tot_r is not None and (fav_l, con_l, abs_l) != (fav_r, con_r, abs_r)
    if distintas and presentes is not None:
        if tot_l == presentes:
            fav, con, abst = fav_l, con_l, abs_l
        elif tot_r == presentes:
            fav, con, abst = fav_r, con_r, abs_r
            extra["lectura_secretaria_no_cuadra"] = f"llamada {fav_l}-{con_l}-{abs_l}"
        else:
            extra["totales_no_cuadran"] = f"llamada {fav_l}-{con_l}-{abs_l} / resumen {fav_r}-{con_r}-{abs_r} / presentes {presentes}"
            fav = con = abst = None
    elif distintas:
        fav, con, abst = fav_l, con_l, abs_l  # sin presentes con que decidir: manda el recuento en vivo
        extra["discrepancia_resumen"] = f"{fav_r}-{con_r}-{abs_r}"
    else:
        fav = fav_l if fav_l is not None else fav_r
        con = con_l if con_l is not None else con_r
        abst = abs_l if abs_l is not None else abs_r
    if fav is not None and sum(x or 0 for x in (fav, con, abst)) > escanos:
        extra["totales_descartados"] = f"{fav}-{con}-{abst}"
        fav = con = abst = None
    return fav, con, abst, presentes, resultado, extra


# ---------------------------------------------------------------- orden del día

ITEM_RE = re.compile(r"^(\d{1,2})\.\s+(.*)$")
DOTS_TAIL_RE = re.compile(r"\.{3,}\s*\d*\s*$")
SOLO_NUM_RE = re.compile(r"^\d{1,4}$")
EXPEDIENTE_RE = re.compile(r"(\d{1,2}[A-Za-z]?/[A-ZÑ]{2,6}-\d{4,6})")


def _orden_dia(lineas):
    """[{"numero", "texto"}] de los puntos del orden del día, al principio del diario."""
    limite = next((k for k, l in enumerate(lineas) if ORADOR_RE.match(l)), min(len(lineas), 400))
    items, i, esperado = [], 0, 1
    while i < limite:
        m = ITEM_RE.match(lineas[i])
        if m and int(m.group(1)) == esperado:
            partes = [m.group(2)]
            i += 1
            while i < limite:
                if DOTS_TAIL_RE.search(partes[-1]):
                    break
                m2 = ITEM_RE.match(lineas[i])
                if m2 and int(m2.group(1)) == esperado + 1:
                    break
                if SOLO_NUM_RE.match(lineas[i]):
                    i += 1
                    continue
                partes.append(lineas[i])
                i += 1
            items.append({"numero": esperado, "texto": DOTS_TAIL_RE.sub("", " ".join(partes)).strip()})
            esperado += 1
        else:
            i += 1
    return items


def _expediente_item(item):
    """Expediente «propio» del punto: el que sigue a la palabra «expediente»; si no, None si hay varios
    (un Debate General acumula iniciativas de varios expedientes: no hay uno solo que valga)."""
    if item is None:
        return None
    t = item["texto"]
    m = re.search(r"expedientes?\s+" + EXPEDIENTE_RE.pattern, t, re.I)
    if m:
        return m.group(1)
    todos = EXPEDIENTE_RE.findall(t)
    return todos[0] if len(todos) == 1 else None


# ---------------------------------------------------------------- anuncio de cada votación: punto, título, autor

ORDINALES = {"primer": 1, "segundo": 2, "tercer": 3, "cuarto": 4, "quinto": 5, "sexto": 6, "septimo": 7,
             "octavo": 8, "noveno": 9, "decimo": 10}
ORDINAL_PUNTO_RE = re.compile(
    r"\b(?:En relaci[oó]n con el|Pasamos(?:,?\s*por consiguiente,?)?\s*a[l]?|Damos paso al|"
    r"Corresponde(?:\s+ahora)?\s+al|Continuamos con el|Iniciamos el|Debatimos(?:\s+ahora)?\s+el|El|La|Los)\s+"
    r"(?P<ord>primer|segundo|tercer|cuarto|quinto|sexto|s[ée]ptimo|octavo|noveno|d[ée]cimo)[oa]?\s*"
    r"(?:y\s+[uú]ltimo\s+)?punto\b", re.I)
DEBATE_GENERAL_RE = re.compile(
    r"Debate\s+General\s+relativo\s+a\s+(?P<titulo>.+?)(?:\s*\(se\s+acumulan|\.\s|\.$|,\s*\()", re.I)
PROPUESTA_RES_RE = re.compile(
    r"Propuesta\s+de\s+Resoluci[oó]n(?:\s+al\s+Debate\s+General)?\s+presentada\s+por\s+el\s+"
    r"(Grupo\s+Parlamentario\s+[^.,\n¿]+?)(?:\.\s|\.$|,|\s*¿|$)", re.I)
GRUPO_RE = re.compile(
    r"Grupo\s+Parlamentario\s+[A-ZÁÉÍÓÚÑa-záéíóúñ][\w\sÁÉÍÓÚÑáéíóúñ.\-]*?"
    r"(?=[,.;:)¿]|\s+(?:como|relativ|para|que|del|de\s+la|de\s+las|de\s+los|porque)\b|$)")
RELATIVA_A_RE = re.compile(r"relativ[ao]\s+a\s+(.+?)(?:\.\s|\.$)", re.I)
SOBRE_RE = re.compile(
    r"sobre\s+(?:el|la)\s+((?:Proyecto|Proposici[oó]n)\s+de\s+[Ll]ey.+?|Dictamen.+?)(?:,\s*expediente|\.\s|\.$)", re.I)

TIPOS_ITEM = [
    ("dl", r"decreto[- ]ley"),
    ("presupuesto", r"presupuestos?\s+generales"),
    ("pl", r"proyecto\s+de\s+ley"),
    ("ppl", r"proposici[oó]n\s+de\s+ley"),
    ("ilp", r"iniciativa\s+legislativa\s+(?:popular|municipal)"),
    ("pnl", r"proposici[oó]n\s+no\s+de\s+ley"),
    ("mocion", r"\bmoci[oó]n\b"),
    ("investidura", r"investidura|moci[oó]n\s+de\s+censura|cuesti[oó]n\s+de\s+confianza"),
    ("organizacion", r"reglamento\s+de\s+las\s+cortes|elecci[oó]n|designaci[oó]n|nombramiento|toma\s+de\s+posesi[oó]n|"
                     r"incompatibilidad|creaci[oó]n\s+de\s+una\s+comisi[oó]n|comisi[oó]n\s+de\s+investigaci[oó]n"),
    ("control", r"debate\s+general|interpelaci[oó]n|comparecencia|informe\s+|\bplan\b"),
    ("acuerdo", r"dictamen|convenio|acuerdo"),
]


def _tipo_de(texto_):
    p = _plano(texto_)
    for tipo, patron in TIPOS_ITEM:
        if re.search(patron, p):
            return tipo
    return "otro"


def _tipo_votacion_de(tipo, contexto):
    """catalogos.TIPOS_VOTACION, cuando se deduce claramente del tipo de iniciativa o de lo que anuncia
    la Presidencia («enmienda», «toma en consideración»…)."""
    c = _plano(contexto)
    if tipo in ("pnl", "mocion", "control", "investidura"):
        return tipo
    if re.search(r"toma\s+en\s+consideracion", c):
        return "toma_consideracion"
    if re.search(r"enmiendas?\b|voto\s+particular", c):
        return "enmiendas"
    if tipo == "dl" and re.search(r"convalida", c):
        return "convalidacion"
    if tipo == "organizacion":
        return "nombramiento" if re.search(r"elecci|designaci|nombramiento", c) else "organizacion"
    if re.search(r"articulad|articulo|disposici|seccion|anexo", c) and tipo in ("pl", "ppl", "presupuesto"):
        return "articulado"
    if re.search(r"conjunto\s+del\s+(?:texto|dictamen|proyecto)|votacion\s+final", c) and tipo in ("pl", "ppl", "presupuesto"):
        return "conjunto"
    return None


def _ultimo(rx, texto_):
    matches = list(rx.finditer(texto_))
    return matches[-1] if matches else None


class _Estado:
    """El punto del orden del día que está en curso mientras se recorre el cuerpo del diario."""

    def __init__(self):
        self.titulo = None
        self.autor = None
        self.expediente = None
        self.tipo = None


def _actualizar_estado(estado, ventana, items):
    """Actualiza `estado` con la transición de punto (si la hay) en `ventana`; devuelve (subtítulo,
    autor, tipo) propios de este evento en concreto cuando es una Propuesta de Resolución."""
    m_punto = _ultimo(ORDINAL_PUNTO_RE, ventana)
    if m_punto:
        numero = ORDINALES[_plano(m_punto.group("ord"))]
        item = items[numero - 1] if 0 < numero <= len(items) else None
        resto = ventana[m_punto.end():]
        m_dg = DEBATE_GENERAL_RE.search(resto) or (DEBATE_GENERAL_RE.search(item["texto"]) if item else None)
        if m_dg:
            estado.titulo = re.sub(r"\s+", " ", m_dg.group("titulo")).strip(" .,")
            estado.autor, estado.expediente, estado.tipo = None, None, "control"
        else:
            estado.expediente = _expediente_item(item)
            m_rel = RELATIVA_A_RE.search(resto) or (RELATIVA_A_RE.search(item["texto"]) if item else None)
            m_sob = None if m_rel else (SOBRE_RE.search(resto) or (SOBRE_RE.search(item["texto"]) if item else None))
            if m_rel:
                estado.titulo = re.sub(r"\s+", " ", m_rel.group(1)).strip(" .,")
            elif m_sob:
                estado.titulo = re.sub(r"\s+", " ", m_sob.group(1)).strip(" .,")
            elif item:
                estado.titulo = item["texto"][:300]
            m_grupo = _ultimo(GRUPO_RE, resto[:400]) or (_ultimo(GRUPO_RE, item["texto"]) if item else None)
            estado.autor = m_grupo.group(0).strip() if m_grupo else None
            estado.tipo = _tipo_de((item["texto"] if item else "") + " " + resto[:200])
    elif RELATIVA_A_RE.search(ventana) or GRUPO_RE.search(ventana):
        # no se ha encontrado la transición de punto (redacción distinta, o punto ya en curso), pero el
        # propio anuncio de la votación suele bastar («se somete a votación la moción..., relativa a...»)
        m_rel = _ultimo(RELATIVA_A_RE, ventana)
        if m_rel:
            estado.titulo = re.sub(r"\s+", " ", m_rel.group(1)).strip(" .,")
        m_grupo = _ultimo(GRUPO_RE, ventana[-400:])
        if m_grupo:
            estado.autor = m_grupo.group(0).strip()
    # una Propuesta de Resolución vale para este evento en concreto; no cambia el punto en curso
    m_pdr = _ultimo(PROPUESTA_RES_RE, ventana)
    if m_pdr and estado.tipo == "control":
        grupo = re.sub(r"\s+", " ", m_pdr.group(1)).strip(" .,")
        return f"Propuesta de Resolución del {grupo}", grupo, "control"
    return None, None, None


# ---------------------------------------------------------------- eventos de voto

def _eventos(texto_crudo, escanos):
    """[dict] de las votaciones que las reglas leen en un diario, en orden."""
    lineas = _lineas_utiles(texto_crudo)
    plano = re.sub(r"\s+", " ", " ".join(lineas)).strip()
    items = _orden_dia(lineas)
    anclas = [(m.start(), "roll", m) for m in FAVOR_Q_RE.finditer(plano)]
    anclas += [(m.start(), "resumen", m) for m in RESULTADO_ANCLA_RE.finditer(plano)]
    anclas += [(m.start(), "asentimiento", m) for m in ASENTIMIENTO_RE.finditer(plano)]
    anclas.sort(key=lambda t: t[0])
    estado, cursor, out = _Estado(), 0, []
    for k, (pos, kind, m) in enumerate(anclas):
        if pos < cursor:
            continue
        subt, aut_ev, tipo_ev = _actualizar_estado(estado, plano[cursor:pos], items)
        if kind == "asentimiento":
            cursor = m.end()
            out.append({"titulo": estado.titulo, "subtitulo": subt, "autor": aut_ev or estado.autor,
                        "expediente": None if subt else estado.expediente, "tipo": tipo_ev or estado.tipo,
                        "a_favor": None, "en_contra": None, "abstenciones": None, "presentes": None,
                        "resultado": "aprobada", "asentimiento": True, "extra": {}, "lectura": m.group(0)})
            continue
        # «roll» (con preguntas) o «resumen» (recuento sin preguntas, diarios más antiguos): el verbo del
        # resultado se busca en una ventana amplia, sin pasar nunca de la siguiente llamada a votación
        siguiente_roll = next((a[0] for a in anclas[k + 1:] if a[1] == "roll"), len(plano))
        tope = min(pos + 900, len(plano), siguiente_roll)
        bloque = plano[pos:tope]
        if CANDIDATURA_RE.search(bloque):
            cursor = tope  # votación por papeletas a varios candidatos: no hay recuento a favor/en contra
            continue
        mr = RESULT_RE.search(bloque)
        fin_bloque = pos + (mr.end() if mr else min(len(bloque), VENTANA_ROLL))
        ventana = plano[pos:min(fin_bloque + VENTANA_RESUMEN, len(plano), siguiente_roll)]
        llamada = _leer_llamada(ventana) if kind == "roll" else (None, None, None)
        resumen = _leer_resumen(ventana)
        cursor = fin_bloque
        fav, con, ab, presentes, resultado, extra = _combinar_totales(llamada, resumen, escanos)
        extra["lectura"] = ventana.strip()[:250]
        unanime = bool(re.search(r"unanimidad", ventana, re.I))
        out.append({"titulo": estado.titulo, "subtitulo": subt, "autor": aut_ev or estado.autor,
                    "expediente": None if subt else estado.expediente, "tipo": tipo_ev or estado.tipo,
                    "a_favor": fav, "en_contra": con, "abstenciones": ab, "presentes": presentes,
                    "resultado": resultado, "asentimiento": unanime and fav is None, "extra": extra})
    return out


def _hay_senal_de_voto(texto_crudo):
    """¿Se vota en este diario? (para decidir si, sin votos leídos, hay que mandarlo al LLM)."""
    plano = re.sub(r"\s+", " ", " ".join(_lineas_utiles(texto_crudo)))
    return bool(FAVOR_Q_RE.search(plano) or RESULTADO_ANCLA_RE.search(plano) or ASENTIMIENTO_RE.search(plano))


# ---------------------------------------------------------------- Votacion

def _votacion(leg, num, fecha, url, n, ev):
    tipo = ev["tipo"]
    contexto = f"{ev.get('subtitulo') or ''} {ev['extra'].get('lectura', '')}"
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=ev["titulo"] or (ev["subtitulo"] or "").strip() or "(sin título)",
        sesion=num, numero=n, legislatura=leg,
        subtitulo=ev["subtitulo"], expediente=ev["expediente"],
        tipo_iniciativa=tipo if tipo in _TIPOS_VALIDOS else None,
        tipo_votacion=_tipo_votacion_de(tipo, contexto), autor=ev["autor"],
        a_favor=ev["a_favor"], en_contra=ev["en_contra"], abstenciones=ev["abstenciones"], presentes=ev["presentes"],
        asentimiento=ev["asentimiento"], resultado=ev["resultado"],
        url=url, fuente="pdf-reglas", extra=ev["extra"])


_TIPOS_VALIDOS = set(TIPOS_INICIATIVA)

_ANALISIS = {}  # url -> (texto, [eventos]): descargar() y documentos() analizan el mismo diario una sola vez


def _analisis(ctx, url, escanos):
    if url not in _ANALISIS:
        try:
            texto_ = _texto_diario(ctx, url)
        except Exception as e:  # web caída o PDF corrupto: se reintenta en la próxima ejecución
            ctx.log(f"  ! {CUERPO}: {url} no disponible ({type(e).__name__}: {e})")
            return None
        _ANALISIS[url] = (texto_, _eventos(texto_, escanos))
    return _ANALISIS[url]


def descargar(ctx):
    desde = ctx.desde(CUERPO, margen_dias=30)
    n_total = 0
    for leg in _legislaturas(ctx):
        fin = CUERPOS[0].legislaturas[leg][2]
        if desde and fin and fin < desde:
            break
        escanos = CUERPOS[0].escanos_de(leg)
        for fecha, num, url in _diarios(ctx, leg):
            if desde and fecha < desde:
                break
            an = _analisis(ctx, url, escanos)
            if an is None:
                continue
            _texto_, eventos = an
            n = 0
            for ev in eventos:
                if ev["resultado"] is None and ev["a_favor"] is None and not ev["asentimiento"]:
                    continue  # ni resultado ni totales: no aporta nada, y probar.py lo rechazaría
                n += 1
                yield _votacion(leg, num, fecha, url, n, ev)
                n_total += 1
                if ctx.limite and n_total >= ctx.limite:
                    return


RECIENTES = 12  # diarios que documentos() mira aunque no estén en caché, para no bajar todo el archivo en CI


def _en_cache(url):
    return (CACHE_DIR / CUERPO / "diarios" / f"{_nombre(url)}.gz").exists()


def documentos(ctx):
    """Diarios en los que se vota pero las reglas no leen ninguna votación (para el LLM): votaciones por
    papeletas a varios candidatos, investiduras por llamamiento y recuentos que las reglas no entienden.

    Para saberlo hay que leer el diario: se miran los ya descargados (por `descargar`, en esta ejecución
    o antes) y los RECIENTES últimos, para no bajar todo el archivo en una ejecución sin caché (CI).
    """
    desde = ctx.desde(CUERPO, margen_dias=30)
    n = 0
    for leg in _legislaturas(ctx):
        fin = CUERPOS[0].legislaturas[leg][2]
        if desde and fin and fin < desde:
            break
        escanos = CUERPOS[0].escanos_de(leg)
        diarios = _diarios(ctx, leg)
        for k, (fecha, num, url) in enumerate(diarios):
            if desde and fecha < desde:
                break
            if k >= RECIENTES and not _en_cache(url):
                continue
            an = _analisis(ctx, url, escanos)
            if an is None:
                continue
            texto_, eventos = an
            if eventos or not _hay_senal_de_voto(texto_):
                continue
            yield Documento(CUERPO, fecha, url, sesion=num, formato="pdf", idioma="es", legislatura=leg,
                            titulo=f"Diario de Sesiones del Pleno n.º {num} ({romano(leg)} legislatura)")
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
