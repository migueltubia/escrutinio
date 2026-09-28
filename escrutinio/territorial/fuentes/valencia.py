"""Corts Valencianes: votaciones nominales en XML (2019-2020) y reglas sobre el Diari de Sessions del Ple.

Fuentes
- Votaciones (datos estructurados): https://www.cortsvalencianes.es/es/parlament-obert/transparencia/actividad/votaciones
  Un XML por sesión plenaria (…/sites/default/files/votacion/doc/X_025.xml) con una fila por
  diputado y votación: fecha y hora, sesión, asunto, nombre, grupo, voto (A FAVOR, EN CONTRA, SE
  ABSTIENE, NO VOTA, NO PRESENTE) y presencia. Solo hay 11 sesiones de la X legislatura: 7 a 16
  (25-9-2019 a 5-3-2020) y 25 (14/15-10-2020); 250 votaciones, 181 de ellas de los presupuestos de 2020. Comprobado en septiembre de 2026:
  no hay XML de la XI legislatura ni de las sesiones 17 a 24, el filtro de legislatura solo ofrece
  la X y los nombres de fichero vecinos (X_017, XI_001…) dan 404.
- Histórico (…/votaciones/historico): PDF mensuales «votaciones_<mes>_<año>.pdf» de septiembre de
  2014 a octubre de 2018 con el resultado de cada votación en texto («F.10 C.52 ABS.29», «s'aprova
  per 79 vots a favor i 9 en contra»), sin voto por grupo ni fecha exacta en las sesiones de varios
  días. No se usan: el Diari de Sessions trae lo mismo con la fecha de cada día.
- Diari de Sessions del Ple (con reglas, y con el LLM cuando las reglas no llegan): la consulta
  https://www.cortsvalencianes.es/es/consulta_dscv es una aplicación JavaScript que llama por POST a
  /publicaciones-CV/:
    obtenerListaNumerosDS (idioma=ca_VA, rpp=-1, f_legislatura=XI) -> [{clave_dscv, numero, fecha_sesion}]
    obtenerSumarioDS (f_clave_dscv) -> puntos del orden del día y urlPdf/urlHtml
  El PDF de cada número es /publicaciones-CV/obtenerPdfDS?f_clave_dscv=<clave>&idioma=ca_VA (la
  clave lleva espacios: «XI  001000»). El texto está en valenciano y castellano según quién hable.
  Hay PDF con texto desde la V legislatura (1999); los de la I a la IV son escaneados. Algunas
  peticiones no devuelven PDF (el servidor lo genera al vuelo y a veces falla): se registran y se
  saltan.

  El SUMARI de cada diario (sus primeras páginas) no es un simple índice: narra cada punto del orden
  del día (título, expedient RE, grup que el presenta) seguido de «Intervenció(ns) de...» y, si es
  vota, de una frase muy regular que no aparece en la transcripció literal que sigue: «Votació:
  s'aprova per 52 vots a favor, 9 en contra i 37 abstencions.», «Votació de l'esmena a la totalitat:
  es rebutja per 46 vots en contra i 36 vots a favor.», «Votació: s'aprova per unanimitat/per
  assentiment.». Con eso basta para leer casi todas las votaciones sin tocar la transcripció; el PDF
  se saca con pdftotext -raw (no -layout), porque en dos columnas o entre páginas «-layout» reordena
  mal el texto y hace que un ítem parezca acabar antes de su votación.

Qué se genera
- descargar(): primero las votaciones de los XML (voto nominal —NO PRESENTE cuenta como no_vota—,
  voto por grupo y totales contados; expediente = número de registro de entrada, el primero que
  aparece en el título; título y subtítulo; tipo de iniciativa y de votación cuando el título lo deja
  claro; `sesion` es el número de sesión plenaria y `numero`, el orden por hora; el XML no dice si se
  aprobó, así que `resultado` queda en None). Después, con reglas sobre el SUMARI (fuente
  «pdf-reglas»), las votaciones de los días que los XML no cubren: título, expediente (RE) y grupo
  que presenta del propio punto del SUMARI; subtítulo de lo que anuncia «Votació de...» (o de la
  etapa —«Debat de totalitat», «Validació o derogació», «Presa en consideració»— si no lo dice);
  a_favor/en_contra/abstenciones tal como se leen (una categoría no mencionada, como «cap en contra»
  implícito, queda en None); asentimiento y resultado «aprobada» por unanimitat/assentiment sin
  recuento; resultado solo cuando el verbo («s'aprova»/«es rebutja») cuadra con los totales (o se cita
  mayoria absoluta/qualificada). `sesion` es el número del diario (no el de la sesión plenaria: una
  sesión de dos días tiene dos diarios y hay días con dos diarios) y `numero`, el orden de lectura en
  el SUMARI. Sin voto por grupo ni nominal: el SUMARI no los da.
- documentos(): un Documento por diario del Diari de Sessions del Ple desde la V legislatura, salvo
  los días cubiertos por los XML o en los que las reglas ya han leído alguna votación. Solo entra si,
  además, el propio diario da alguna señal de que se vota («votació», «escrutini», «papereta») y las
  reglas no han sacado ninguna: investiduras y elecciones por papeleta o escrutinio nombre a nombre,
  votaciones secretas y los plenos de presupuestos (el SUMARI solo dice «Debat i votació del dictamen
  ... Continuació»; el detalle de cada esmena o secció se lee en la transcripció, con la lectura de la
  Secretaria, no en el SUMARI). Como listar los documentos no debe bajarse todo el archivo en una CI
  sin caché, solo se analizan los diarios ya descargados y los RECIENTES últimos.

Limitaciones: sin voto por grupo ni nominal fuera de los XML. Cuando un projecte de llei agrupa varias
esmenes a la totalitat bajo un único punto (con un subepígrafe «Esmena presentada pel Grup X» por
cada una) y el SUMARI lista los resultados aparte, al final, el grupo de cada resultado se toma de la
propia frase «Votació de l'esmena presentada pel Grup X»: si esa frase repite mal el nombre del grupo
(pasa alguna vez), el grupo queda equivocado aunque el recuento y el orden sean correctos. Los días en
que las reglas leen alguna votación pero no todas las que hubo (recuento en una fórmula rara, columnas
mal enlazadas) no se completan con el LLM: solo se manda un diario entero si no se ha leído ninguna. El
título de algunas votaciones del XML de presupuestos (sesión 13) es solo «Punt 2»; se completa con el
del punto 2 de la misma sesión y queda marcado en `extra`. Las votaciones de los presupuestos del XML
no dicen qué enmienda o sección se vota.
"""

import gzip
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import CACHE_DIR, Contexto
from ..modelo import Documento, Votacion, VotoGrupo, VotoNominal

CUERPO = "parl-VC"
WEB = "https://www.cortsvalencianes.es"
LISTADO = WEB + "/es/parlament-obert/transparencia/actividad/votaciones?items_per_page=100"
API_DS = WEB + "/publicaciones-CV/"

# Fechas de la sesión constitutiva (diario número 1 de cada legislatura). 89 escaños hasta 2007; 99 desde
# la VII (Estatuto de 2006).
LEGISLATURAS = {
    5: ("V", "1999-07-09", "2003-06-12", 89),
    6: ("VI", "2003-06-12", "2007-06-14", 89),
    7: ("VII", "2007-06-14", "2011-06-09", 99),
    8: ("VIII", "2011-06-09", "2015-06-11", 99),
    9: ("IX", "2015-06-11", "2019-05-16"),
    10: ("X", "2019-05-16", "2023-06-26"),
    11: ("XI", "2023-06-26", None),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("VC"), "Corts Valencianes", "Corts (C. Valenciana)", "autonomico", "VC", 99,
           LEGISLATURAS, web=WEB),
]

ACTIVO = True
NOTAS = __doc__

SENTIDO = {"A FAVOR": "si", "EN CONTRA": "no", "SE ABSTIENE": "abstencion", "NO VOTA": "no_vota",
           "NO PRESENTE": "no_vota"}
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
         "gener": 1, "febrer": 2, "març": 3, "maig": 5, "juny": 6, "juliol": 7, "agost": 8, "setembre": 9,
         "novembre": 11, "desembre": 12}
ROMANOS = {romano(n): n for n in range(1, 30)}

ENTRADA_RE = re.compile(
    r'item-title-simple">([^<]*)</div>.*?<time datetime="(\d{4}-\d{2}-\d{2})[^"]*".*?href="([^"]*/([IVXL]+)_(\d+)\.xml)"',
    re.S)
RE_RE = re.compile(r"\(\s*RE\s+n[úu]m(?:ero|\.)?\s*([\d.]+)[^)]*\)", re.I)
PUNTO_RE = re.compile(r"\s*(?:PUNT\s+[ÚU]NIC\s*\.?\s*-?|Punt\s*(\d+)\s*[.\-:]*|(\d+)\s*[.\-]+)\s*", re.I)


# ---------------------------------------------------------------------------- votaciones (XML)

def _fecha_titulo(titulo):
    """«Sesión Ordinaria 25 de 14 de Octubre de 2020» -> 2020-10-14."""
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})\s*$", titulo.strip())
    if not m or m.group(2).lower() not in MESES:
        return None
    return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _sesiones_xml(ctx):
    """[(legislatura, sesion, inicio, fin, tipo, url)] de la página de votaciones, lo más reciente primero."""
    vistas = {}
    for pagina in range(10):
        h = ctx.texto(LISTADO + (f"&page={pagina}" if pagina else ""), cache=f"{CUERPO}/votaciones_{pagina}.html",
                      caduca_dias=7)
        nuevas = 0
        for titulo, fin, url, leg, ses in ENTRADA_RE.findall(h):
            clave = (ROMANOS.get(leg), int(ses))
            if clave[0] is None or clave in vistas:
                continue
            titulo = html.unescape(titulo).strip()
            tipo = "extraordinaria" if "xtraordin" in titulo.lower() else "ordinaria"
            vistas[clave] = (*clave, _fecha_titulo(titulo) or fin, fin, tipo, urllib.parse.urljoin(WEB, url))
            nuevas += 1
        if not nuevas or 'rel="next"' not in h:
            break
    return [vistas[k] for k in sorted(vistas, reverse=True)]


def _partir(desc):
    """Título, subtítulo, expediente, punto y datos extra de la descripción de una votación."""
    d = desc.replace("\r", "").strip()
    punto = None
    m = PUNTO_RE.match(d)
    if m and m.end():
        punto = int(m.group(1) or m.group(2)) if (m.group(1) or m.group(2)) else 1
        d = d[m.end():]
    lineas = [x.strip() for x in d.split("\n") if x.strip()]
    principal = lineas[0] if lineas else ""
    sub = " ".join(lineas[1:]) or None
    titulo, expediente, extra = principal, None, {}
    m = RE_RE.search(principal)
    if m:
        expediente = "RE-" + m.group(1).replace(".", "").strip()
        b = re.search(r"BOCV?\s*(?:n[úu]m(?:ero|\.)?\s*)?(\d+)", m.group(0))
        if b:
            extra["bocv"] = int(b.group(1))
        resto = principal[m.end():]
        limpio = re.sub(r"(?i)(?:sense\s+c|c)riteri\s+del\s+consell\.?(?:\s*\(RE[^)]*\))?\.?", " ", resto)
        limpio = re.sub(r"\s+", " ", limpio).strip(" .")
        if not resto.strip(" ."):
            titulo = principal[:m.end()]
        elif re.match(r"\s*\.?\s*[A-ZÀ-Ú]", resto):
            titulo = principal[:m.end()]
            if limpio:
                sub = f"{limpio}. {sub}" if sub else limpio
            if re.search(r"(?i)criteri\s+del\s+consell", resto):
                extra["criteri_consell"] = not re.search(r"(?i)sense\s+criteri", resto)
    return titulo.strip(" ."), (sub.strip(" .") if sub else None), expediente, punto, extra


def _autor(titulo):
    m = re.search(r"(?i)presentad[ae]s?\s+(?:pel|pels|per|por\s+el|por\s+los)\s+"
                  r"((?:grups?\s+parlamentaris?|grupos?\s+parlamentarios?|GP)\s*[^()]+?)\s*(?:\(|$)", titulo)
    return m.group(1).strip(" ,.") if m else None


def _tipos(titulo, sub):
    t, s = titulo.lower(), (sub or "").lower()
    if re.search(r"proposici[óo]n?\s+no\s+de\s+(?:llei|ley)", t):
        return "pnl", "pnl"
    if re.search(r"\bmoci[óo]n?\b", t):
        return "mocion", "mocion"
    if re.search(r"projecte de llei de press|proyecto de ley de presupuestos", t) or (
            re.search(r"pressupostos de la generalitat per a l.exercici", t) and "proposici" not in t):
        tipo = "presupuesto"
    elif re.search(r"projecte de llei|proyecto de ley", t):
        tipo = "pl"
    elif re.search(r"proposici[óo]n?\s+de\s+(?:llei|ley)", t):
        tipo = "ppl"
    elif re.search(r"decret[o\s-]+(?:llei|ley)", t):
        tipo = "dl"
    elif re.search(r"comissi[óo] (?:especial )?d.(?:investigaci|estudi)|comisi[óo]n (?:especial )?de (?:investigaci|estudio)"
                   r"|reglament", t):
        tipo = "organizacion"
    elif re.search(r"fiscalitzaci|fiscalizaci|compte general|cuenta general", t):
        tipo = "control"
    else:
        tipo = "otro"
    voto = None
    if re.search(r"esmen\w* a la totalitat|enmienda a la totalidad|debat de totalitat|debate de totalidad", t + " " + s):
        voto = "totalidad"
    elif (re.search(r"presa en consideraci|toma en consideraci", t) and tipo in ("ppl", "organizacion")
          and (not s or re.search(r"presa en consideraci|toma en consideraci|ordin[àa]ria", s))):
        voto = "toma_consideracion"
    elif tipo == "dl" and re.search(r"validaci[óo]|derogaci[óo]", t + " " + s):
        voto = "convalidacion"
    elif tipo == "organizacion":
        voto = "organizacion"
    elif tipo == "control":
        voto = "control"
    elif re.match(r"(?:article|artículo|exposici[óo] de motius)", s):
        voto = "articulado"
    elif re.match(r"totalitat", s):
        voto = "conjunto"
    return tipo, voto


SOLO_PUNTO_RE = re.compile(r"(?:\s*Punt\s*(\d+)\s*)+", re.I)


def _punto(desc):
    m = SOLO_PUNTO_RE.fullmatch(desc)
    return int(m.group(1)) if m else _partir(desc)[3]


def _votaciones_xml(ctx, leg, ses, tipo_sesion, url):
    raw = ctx.fetch(url, cache=f"{CUERPO}/xml/{romano(leg)}_{ses:03d}.xml")
    grupos = {}  # (fecha y hora, asunto) -> filas: cada votación tiene una fila por diputado
    for f in ET.fromstring(raw).findall("ROW"):
        grupos.setdefault(((f.findtext("FECHA") or "").strip(), f.findtext("DESCRIPCION2") or ""), []).append(f)
    # Asunto completo de cada punto, para las votaciones cuyo asunto es solo «Punt 2».
    asunto_punto = {}
    for _hora, desc in sorted(grupos):
        if not SOLO_PUNTO_RE.fullmatch(desc):
            asunto_punto.setdefault(_punto(desc), desc)
    # El XML no va en orden: se numeran por hora (y por punto si coinciden).
    for numero, clave in enumerate(sorted(grupos, key=lambda c: (c[0], _punto(c[1]) or 0, c[1])), 1):
        hora, desc = clave
        extra = {"hora": hora[11:], "tipo_sesion": tipo_sesion}
        solo = SOLO_PUNTO_RE.fullmatch(desc)
        if solo and int(solo.group(1)) in asunto_punto:
            desc = asunto_punto[int(solo.group(1))]
            extra["titulo_deducido_del_punto"] = int(solo.group(1))
        titulo, sub, expediente, punto, mas = _partir(desc)
        extra.update(mas)
        if punto:
            extra["punto"] = punto
        nominal, por_grupo, presentes = [], {}, 0
        for f in grupos[clave]:
            voto = (f.findtext("VOTO") or "").strip().upper()
            if voto not in SENTIDO:
                raise ValueError(f"{url}: voto desconocido {voto!r}")
            nombre = " ".join(x for x in ((f.findtext("NOMBRE") or "").strip(), (f.findtext("APELLIDO1") or "").strip(),
                                          (f.findtext("APELLIDO2") or "").strip()) if x)
            grupo = (f.findtext("GRUPO") or "").strip()
            if not nombre:  # filas vacías (sesión 15: 8 «NO PRESENTE» sin diputado ni grupo)
                extra["filas_sin_diputado"] = extra.get("filas_sin_diputado", 0) + 1
                continue
            nominal.append(VotoNominal(nombre, grupo, SENTIDO[voto]))
            por_grupo.setdefault(grupo, Counter())[SENTIDO[voto]] += 1
            presentes += voto != "NO PRESENTE"
        cuenta = Counter(n.sentido for n in nominal)
        extra["no_presentes"] = len(nominal) - presentes
        tipo, voto = _tipos(titulo, sub)
        yield Votacion(
            cuerpo=CUERPO, fecha=hora[:10], titulo=titulo or desc.strip(), sesion=ses, numero=numero, legislatura=leg,
            subtitulo=sub, expediente=expediente, tipo_iniciativa=tipo, tipo_votacion=voto, autor=_autor(titulo),
            a_favor=cuenta["si"], en_contra=cuenta["no"], abstenciones=cuenta["abstencion"], no_votan=cuenta["no_vota"],
            presentes=presentes,
            grupos=[VotoGrupo(g, si=c["si"], no=c["no"], abstencion=c["abstencion"], no_vota=c["no_vota"])
                    for g, c in sorted(por_grupo.items())],
            nominal=nominal, url=url, fuente="xml", extra=extra,
        )


def descargar(ctx):
    desde = ctx.desde(CUERPO)
    n = 0
    for leg, ses, _inicio, fin, tipo, url in _sesiones_xml(ctx):
        if desde and fin < desde:
            break
        for v in sorted(_votaciones_xml(ctx, leg, ses, tipo, url), key=lambda v: v.numero, reverse=True):
            if desde and v.fecha < desde:
                continue
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    # Días que los XML no cubren: se leen con reglas sobre el SUMARI del Diari de Sessions.
    for leg, fecha, numero_ds, _clave, url in _diarios_reglas(ctx, desde):
        an = _analizar_diario(ctx, url)
        if an is None:
            ctx.log(f"  ! {CUERPO}: diario {numero_ds} ({fecha}) no devuelve PDF; se salta")
            continue
        votos, _señal = an
        for k, v in enumerate(votos, 1):
            vo = _votacion_ds(leg, fecha, numero_ds, url, k, v)
            if vo is None:
                continue
            yield vo
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


# ---------------------------------------------------------------------------- Diari de Sessions

def _json_ds(raw):
    import json

    t = raw.decode("iso-8859-15", "replace").replace("\t", " ").replace("\r\n", " ")
    d = json.loads(t)
    if d.get("estat") != "correcte":
        raise ValueError(f"Corts: respuesta de error del Diari de Sessions: {d.get('missatge')}")
    return d["dades"]


def _lista_ds(ctx, leg):
    """Números del Diari de Sessions del Ple de una legislatura: [{clave_dscv, numero, fecha_sesion}]."""
    rom = romano(leg)
    actual = LEGISLATURAS[leg][2] is None
    datos = {"idioma": "ca_VA", "rpp": "-1", "f_legislatura": rom}
    d = _json_ds(ctx.fetch(API_DS + "obtenerListaNumerosDS", data=datos, cache=f"{CUERPO}/dscv/lista_{rom}.json",
                           caduca_dias=0.5 if actual else None))
    numeros = list(d.get("numeros") or [])
    total = int(d.get("total") or 0)
    while len(numeros) < total:  # la respuesta se corta en 200
        datos = {**datos, "rpp": "200", "member": str(len(numeros) + 1)}
        mas = _json_ds(ctx.fetch(API_DS + "obtenerListaNumerosDS", data=datos,
                                 cache=f"{CUERPO}/dscv/lista_{rom}_{len(numeros) + 1}.json",
                                 caduca_dias=0.5 if actual else None)).get("numeros") or []
        if not mas:
            break
        numeros.extend(mas)
    return numeros


def url_pdf(clave):
    return API_DS + "obtenerPdfDS?" + urllib.parse.urlencode({"f_clave_dscv": clave, "idioma": "ca_VA"},
                                                             quote_via=urllib.parse.quote)


def _texto_pdf_diario(ctx, url):
    """Texto (con pdftotext -raw, que conserva el orden de lectura entre columnas y saltos de página) del PDF de
    un diario. El servidor lo genera al pedirlo y alguna vez responde vacío: se reintenta y no se guarda en la
    caché hasta tener un PDF de verdad. None si tras los reintentos no hay PDF (se registra y se salta)."""
    ruta = ctx.carpeta(CUERPO) / "docs" / f"{Contexto.clave(url)}.pdf.gz"
    if ruta.exists():
        raw = gzip.decompress(ruta.read_bytes())
    else:
        raw = b""
        for intento in range(4):
            raw = ctx.fetch(url, timeout=120)
            if raw[:5] == b"%PDF-":
                break
            time.sleep(3 * (intento + 1))
        else:
            return None
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(gzip.compress(raw))
    return Contexto.pdf_texto(raw, raw=True)


# ---------------------------------------------------------------------------- Diari de Sessions: reglas
#
# El SUMARI de cada diario (las primeras páginas) no es un simple índice: narra cada punto del orden del día
# (título, expedient RE, qui l'ha presentat) seguido de «Intervenció(ns) de...» y, si es vota, de una frase muy
# regular: «Votació: s'aprova per 52 vots a favor, 9 en contra i 37 abstencions.», «Votació de l'esmena a la
# totalitat: es rebutja per 46 vots en contra i 36 vots a favor.», «Votació: s'aprova per unanimitat/per
# assentiment.». Esa frase no aparece en el cos del diari (la transcripció literal, que ve después), así que basta
# con leer el SUMARI para sacar casi todas las votaciones sin tocar la transcripció.
#
# El texto de -raw a veces pega dos palabras sin espacio en un salto de línea («BOCVnúmero», «ComunitatValenciana»)
# o corta una palabra con «l·l»/apóstrofo al final de línea («Excel·» + «lent», «l'» + «esmena»); `_unir_parrafo`
# lo recompone.

RUIDO_LINEA_RE = re.compile(
    r"^(?:P[àa]g(?:ina)?\.?\s*\d+\.?|"
    r"N[uú]mero\s+\d+\s*[•¦]\s*\d{1,2}-\d{1,2}-\d{4}(?:\s+P[àa]g\.?\s*\d+)?|"
    r"N[uú]mero\s+\d+\s*[•¦]\s*\d{4}|"
    r"N[uú]mero\s+\d+\s+[IVXLCM]+\s+Legislatura(?:\s+Any\s+\d{4})?|"
    r"N[uú]mero\s+\d+\s+\d{1,2}\.\d{1,2}\.\d{4}(?:\s+P[àa]gina\s+\d+)?|"
    r"Diari de sessions n[uú]mero\s+\d+|DIARI DE SESSIONS(?:\s+DIARIO DE SESIONES)?|DIARIO DE SESIONES|"
    r"CORTS VALENCIANES|SUMARI|"
    r"\(Primera reuni[óo]\)|"
    r"\d{1,2}\.\d{2}\.\d{4}|"
    r"\d{1,6})$", re.I)
PAGINA_LEADER_RE = re.compile(r"(?:\s*\.){3,}\s*(?:p[àa]gina\s+)?\d{0,6}\s*$", re.I)  # dot-leader (+ página): deja un punto
PAGINA_PEGADA_RE = re.compile(r"\s+p[àa]gina\s+\d{1,6}\s*$|(?<=[a-zà-ÿ0-9)%])\s+\d{3,6}\s*$", re.I)  # página pegada
CABECERA_PAGINA_RE = re.compile(
    r"Sessi[oó]\s+plen[àa]ria\s+(?:celebrada|realitzada)\s+el\s+dia\s+.{0,40}?\d{4}\s*(?:\([^)]*\)\s*)?"
    r"Presid[èe]ncia\s+(?:de\s+la|del)\s+Molt\s+Excel·lent\s+Senyor\w*\s+[^.]{0,60}?"
    r"(?:N[uú]mero\s+\d+\s*[•¦][^.]{0,40}?)?(?:[IVXLCM]+\s+Legislatura\s*)?"
    r"(?:N[uú]mero\s+\d+\s*[•¦]\s*\d{1,2}-\d{1,2}-\d{4}(?:\s+P[àa]g\.?\s*\d+)?)?", re.I)
INICIO_TEXTO_RE = re.compile(r"^\(\s*(?:Comen[çc]a|Es\s+repr[eé]n|Se\s+reprén)\s+la\s+(?:sessió|reuni[óo])\b[^)]*\)\s*",
                              re.I)


def _lineas_utiles(texto):
    out = []
    for ln in texto.replace("\f", "\n").splitlines():
        ln = ln.strip()
        if ln and not RUIDO_LINEA_RE.match(ln):
            out.append(ln)
    return out


def _unir_parrafo(lineas):
    t = ""
    for ln in lineas:
        ln = PAGINA_PEGADA_RE.sub("", PAGINA_LEADER_RE.sub(".", ln)).strip()
        if not ln:
            continue
        if t.endswith("-") and ln[:1].islower():
            t = t[:-1] + ln
        elif t.endswith(("·", "’", "'")):
            t = t + ln
        else:
            t = f"{t} {ln}" if t else ln
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?<=[a-zà-ÿ0-9])(?=[A-ZÀ-Ú])", " ", t)  # «ComunitatValenciana» -> palabras separadas
    t = re.sub(r"\b(BOCV|DOGV|RE|GP)(?=[a-zà-ÿ])", r"\1 ", t)  # «BOCVnúmero» -> «BOCV número»
    return t


# Un ítem del orden del día empieza justo tras un punto y aparte con una de estas palabras.
_TIPO_PALABRAS = (
    r"Decret[ -]llei|Decreto[ -]ley|Projecte de llei|Proyecto de ley|Proposici[óo]n?\s+(?:no\s+)?de\s+(?:llei|ley)|"
    r"Moci[óo]n?(?:\s+subseg[üu]ent)?|Interpel·laci[óo]|Interpelaci[óo]n|Pregunt(?:a|es|as)|"
    r"Compareixen[çc]a|Comparecencia|Declaraci[óo]n?\s+institucional|"
    r"Dictamen|Informe|Elecci[óo]n?|Designaci[óo]n?|Ratificaci[óo]n?|Proposta (?:de|d['’])|Propuesta (?:de|del)|"
    r"Compte general|Cuenta general|Jurament|Juramento|Presa de possessi[óo]|Toma de posesi[oó]n|"
    r"Presa en consideraci[óo]|Toma en consideraci[oó]n|"
    r"Constituci[óo]n?|Debat (?:de|sobre|i)|Debate (?:de|sobre)|Convocat[òo]ria|Convocatoria|Comunicaci[óo]n?|"
    r"Iniciativa legislativa popular"
)
ITEM_INICIO_RE = re.compile(r"(?:(?<=[.:)])\s+|^)(?=(?:" + _TIPO_PALABRAS + r"))", re.I)
_ITEM_O_VOTACIO = r"Votaci[oó]\b|" + _TIPO_PALABRAS
INTERVENCIO_RE = re.compile(r"\bIntervenci[oó](?:ns?)?\b", re.I)
RE_SUMARI_RE = re.compile(r"\bRE\s*(?:n[úu]m(?:ero|\.)?)?\s*(\d[\d.]*)", re.I)
BOCV_SUMARI_RE = re.compile(r"\b(BOCV|DOGV)\b\.?\s*(?:n[úu]mero|n[úu]m\.?)?\s*(\d+)", re.I)
ETAPA_RE = re.compile(
    r"[.,]?\s*(Validaci[oó]\s+o\s+derogaci[oó][nñ]?|Debat\s+(?:de|i)\s+totalitat|Debate\s+de\s+totalidad|"
    r"Debat\s+i\s+votaci[oó]|Presa\s+en\s+consideraci[oó](?:,?\s+si\s+escau)?|"
    r"Toma\s+en\s+consideraci[oó]n(?:,?\s+si\s+procede)?|Debat\s+sobre\s+la\s+totalitat)\s*$", re.I)

# Votació[ de <subtítol>]: <verb> per <recompte>. El cuerpo acaba en el primer punto; si al diario le falta ese
# punto (pasa alguna vez), en el arranque del siguiente ítem o votación, para no comerse su cabecera.
VOTACIO_RE = re.compile(
    r"Votaci[oó]\s*(?P<sub>[^:.]*?)\s*:\s*(?P<cuerpo>[^.]{1,220}?(?:\.|(?=\s+(?:" + _ITEM_O_VOTACIO + r"))))", re.I)
NUM = r"(\d{1,3}|cap|una?|zero|cero)"
FAVOR_RE = re.compile(NUM + r"\s+(?:vots?\s+)?a\s+favor", re.I)
CONTRA_RE = re.compile(NUM + r"\s+(?:vots?\s+)?en\s+contra", re.I)
ABST_RE = re.compile(NUM + r"\s+(?:vots?\s+)?abstenci\w*", re.I)
NULOS_RE = re.compile(NUM + r"\s+(?:vots?\s+)?nuls?\b", re.I)
APROBADA_RE = re.compile(r"s['’]aprov\w*|s['’]accept\w*|es\s+valid\w*|queda\s+validat\w*|s['’]apropa\w*", re.I)
RECHAZADA_RE = re.compile(r"es\s+rebutja\w*|es\s+rebutgen\w*|es\s+rebuitja\w*|es\s+rebujta\w*", re.I)
UNANIME_RE = re.compile(r"per\s+(?:unanimitat|assentiment)", re.I)
MAYORIA_RE = re.compile(r"majoria\s+(absoluta|qualificada|de\s+tres\s+cinquenes|de\s+dos\s+ter[çc]os)", re.I)
SEÑAL_VOTO_RE = re.compile(r"votaci[oó]|escrutini|paperet[ae]|papelet[ae]", re.I)


def _entero(s):
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    return {"cap": 0, "un": 1, "una": 1, "zero": 0, "cero": 0}.get(s)


def _cuenta(cuerpo):
    """{a_favor, en_contra, abstenciones, nulos} de después de «per»; None si no se lee ningún «a favor»."""
    m = FAVOR_RE.search(cuerpo)
    if not m:
        return None
    d = {"a_favor": _entero(m.group(1))}
    m = CONTRA_RE.search(cuerpo)
    d["en_contra"] = _entero(m.group(1)) if m else None
    m = ABST_RE.search(cuerpo)
    d["abstenciones"] = _entero(m.group(1)) if m else None
    m = NULOS_RE.search(cuerpo)
    d["nulos"] = _entero(m.group(1)) if m else None
    return d


def _limpia_sub(sub):
    if not sub or not sub.strip():
        return None
    s = re.sub(r"^(?:de\s+la\s+|de\s+les\s+|de\s+l[’']|del\s+|dels\s+|de\s+|d[’'])", "", sub.strip(), flags=re.I)
    s = s.strip(" ,.")
    return (s[:1].upper() + s[1:]) if s else None


def _titulo_item(bloque):
    """(título, etapa, expediente, autor, extra) de la cabecera de un punto del SUMARI."""
    t = INICIO_TEXTO_RE.sub("", bloque.strip())
    t = CABECERA_PAGINA_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,")
    t = re.sub(r"(?:\s*\.){3,}\s*$", "", t).strip(" .,")  # dot-leader suelto que no se quitó línea a línea
    if len(t) < 6:
        return None, None, None, None, {}
    exp, extra = None, {}
    m = RE_SUMARI_RE.search(t)
    if m:
        exp = "RE-" + m.group(1).replace(".", "")
    mb = BOCV_SUMARI_RE.search(t)
    if mb:
        extra[mb.group(1).lower()] = int(mb.group(2))
    t = re.sub(r"\(\s*RE\b[^)]*\)", "", t, count=1, flags=re.I)
    t = re.sub(r"\bP[àa]gina\s+\d+\.?", "", t, flags=re.I)  # «Pàgina 3.»: referencia de página en el sumario antiguo
    t = re.sub(r"\s+([.,])", r"\1", t).strip()
    autor = _autor(t)
    if autor:
        t = re.sub(r",?\s*presentad[ae]s?\s+(?:pel|pels|per)\s+[^.]*", "", t, count=1, flags=re.I)
    etapa = None
    me = ETAPA_RE.search(t)
    if me:
        etapa = me.group(1).strip()
        t = t[:me.start()]
    t = re.sub(r"\s+", " ", t).strip(" .,")
    return (t or None), etapa, exp, autor, extra


_TRAS_VOTACIO_RE = re.compile(r"\s*(?=(?:" + _TIPO_PALABRAS + r"))", re.I)


def _votos_sumario(texto):
    """[dict] de las votaciones que el SUMARI de un diario da, en el orden en que aparecen.

    No hace falta acotar el texto al SUMARI: la frase «Votació: ...» que se lee aquí no aparece en la
    transcripció literal que sigue (esa usa otra fórmula, «El resultat de la votació és de...»); además, en
    algunos formatos «SUMARI» se repite como cabecera de página y no sirve de límite fiable.
    """
    votos = []
    base = 0
    votaciones = list(VOTACIO_RE.finditer(texto, base))
    # Un ítem empieza tras un punto y aparte (ITEM_INICIO_RE) o justo después del recuento de una votación, aunque
    # al diario le falte el punto que debería separarlos (pasa alguna vez con el SUMARI antiguo).
    posiciones = {m.start() for m in ITEM_INICIO_RE.finditer(texto, base)}
    for vm in votaciones:
        m = _TRAS_VOTACIO_RE.match(texto, vm.end())
        if m:
            posiciones.add(m.end())
    posiciones = sorted(posiciones)
    for vm in votaciones:
        sub_bruto, cuerpo = vm.group("sub"), vm.group("cuerpo")
        ini = max([p for p in posiciones if p <= vm.start()], default=base)
        mi = INTERVENCIO_RE.search(texto, ini, vm.start())
        titulo, etapa, expediente, autor, extra = _titulo_item(texto[ini:(mi.start() if mi else vm.start())])
        if not titulo:
            continue
        if not expediente and sub_bruto:
            m2 = RE_SUMARI_RE.search(sub_bruto)
            if m2:
                expediente = "RE-" + m2.group(1).replace(".", "")
        subtitulo = _limpia_sub(sub_bruto) or etapa
        unanime = bool(UNANIME_RE.search(cuerpo))
        recuento = None if unanime else _cuenta(cuerpo)
        if not unanime and recuento is None:
            continue  # no se ha podido leer el recuento (candidatura por papeleta, votació secreta...)
        resultado = "aprobada" if APROBADA_RE.search(cuerpo) else ("rechazada" if RECHAZADA_RE.search(cuerpo) else None)
        mm = MAYORIA_RE.search(cuerpo)
        if unanime:
            resultado = resultado or "aprobada"
        elif (resultado and recuento and recuento["a_favor"] is not None and recuento["en_contra"] is not None
              and not mm and (resultado == "aprobada") != (recuento["a_favor"] > recuento["en_contra"])):
            extra = {**extra, "resultado_no_cuadra": resultado}
            resultado = None
        if recuento and recuento.get("nulos") is not None:
            extra = {**extra, "nulos": recuento["nulos"]}
        votos.append({
            "titulo": titulo, "subtitulo": subtitulo if subtitulo != titulo else None, "expediente": expediente,
            "autor": autor, "tipo_texto": f"{titulo} {etapa or ''}".strip(),
            "a_favor": None if unanime else (recuento or {}).get("a_favor"),
            "en_contra": None if unanime else (recuento or {}).get("en_contra"),
            "abstenciones": None if unanime else (recuento or {}).get("abstenciones"),
            "asentimiento": unanime, "resultado": resultado,
            "mayoria": "absoluta" if mm and "absolut" in mm.group(1).lower() else None,
            "extra": extra,
        })
    return votos


_ANALISIS_DS = {}  # url -> ([dict] de votaciones, ¿hay señal de que se vota?) | None si no hay PDF


def _analizar_diario(ctx, url):
    if url not in _ANALISIS_DS:
        texto = _texto_pdf_diario(ctx, url)
        if texto is None:
            _ANALISIS_DS[url] = None
        else:
            unido = _unir_parrafo(_lineas_utiles(texto))
            _ANALISIS_DS[url] = (_votos_sumario(unido), bool(SEÑAL_VOTO_RE.search(unido)))
    return _ANALISIS_DS[url]


def _votacion_ds(leg, fecha, numero_ds, url, k, v):
    tipo, tipo_voto = _tipos(v["tipo_texto"], v["subtitulo"])
    a, c, ab = v["a_favor"], v["en_contra"], v["abstenciones"]
    extra = v["extra"]
    escanos = CUERPOS[0].escanos_de(leg)
    if sum(x or 0 for x in (a, c, ab)) > escanos:
        extra = {**extra, "totales_descartados": f"{a}-{c}-{ab}"}  # más votos que escaños: lectura imposible
        a = c = ab = None
    resultado = v["resultado"]
    if resultado is None and a is None and not v["asentimiento"]:
        return None
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=v["titulo"], sesion=numero_ds, numero=k, legislatura=leg,
        subtitulo=v["subtitulo"], expediente=v["expediente"], tipo_iniciativa=tipo, tipo_votacion=tipo_voto,
        autor=v["autor"], a_favor=a, en_contra=c, abstenciones=ab,
        asentimiento=v["asentimiento"], resultado=resultado, mayoria=v["mayoria"],
        url=url, fuente="pdf-reglas", extra=extra)


def _diarios_reglas(ctx, desde):
    """(legislatura, fecha, número de diario, clave, url) de los diarios no cubiertos por los XML, del más
    reciente al más antiguo."""
    cubiertos = [(ini, fin) for _l, _s, ini, fin, _t, _u in _sesiones_xml(ctx)]
    for leg in sorted(LEGISLATURAS, reverse=True):
        fin_leg = LEGISLATURAS[leg][2]
        if desde and fin_leg and fin_leg < desde:
            break
        diarios = sorted(_lista_ds(ctx, leg), key=lambda x: (x["fecha_sesion"], int(x["numero"])), reverse=True)
        for ds in diarios:
            f = ds["fecha_sesion"]
            fecha = f"{f[:4]}-{f[4:6]}-{f[6:8]}"
            if desde and fecha < desde:
                break
            if any(ini <= fecha <= fin for ini, fin in cubiertos):
                continue
            yield leg, fecha, int(ds["numero"]), ds["clave_dscv"], url_pdf(ds["clave_dscv"])


RECIENTES = 12  # diarios que documentos() lee aunque no estén en caché, para saber si hace falta el LLM


def _en_cache(url):
    return (CACHE_DIR / CUERPO / "docs" / f"{Contexto.clave(url)}.pdf.gz").exists()


def documentos(ctx):
    """Diarios en los que el SUMARI muestra que se vota pero las reglas no leen ninguna votación: para el LLM.

    Para saberlo hay que leer el diario: se miran los ya descargados (por `descargar`, en esta ejecución o antes)
    y los RECIENTES últimos, así que sin caché (GitHub Actions) listar los documentos no baja todo el archivo.
    """
    desde = ctx.desde(CUERPO)
    n = 0
    for k, (leg, fecha, numero_ds, clave, url) in enumerate(_diarios_reglas(ctx, desde)):
        if not (k < RECIENTES or _en_cache(url)):
            continue
        an = _analizar_diario(ctx, url)
        if an is None:
            continue  # sin PDF no se sabe si hacía falta el LLM; se reintentará en la próxima ejecución
        votos, señal = an
        if votos or not señal:
            continue
        yield Documento(
            cuerpo=CUERPO, fecha=fecha, url=url, sesion=numero_ds, formato="pdf", idioma="va",
            titulo=f"Diari de Sessions del Ple núm. {numero_ds} ({romano(leg)} legislatura)", legislatura=leg,
            extra={"clave_dscv": clave, "numero_ds": numero_ds,
                   "html": API_DS + "obtenerHtmlDS?" + urllib.parse.urlencode(
                       {"f_clave_dscv": clave, "idioma": "ca_VA"}, quote_via=urllib.parse.quote)},
        )
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    t = _texto_pdf_diario(ctx, doc.url)
    if t is None:
        raise RuntimeError(f"Corts: el Diari de Sessions no devuelve un PDF: {doc.url}")
    return t
