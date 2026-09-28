"""Cabildos canarios y Consells insulars de Baleares: actas del Pleno para el extractor LLM.

Solo publican el acta en PDF, con el voto por grupo en texto libre. Este conector lista las actas y
el extractor (territorial/actas_llm.py) saca las votaciones. Solo se incluyen las instituciones
cuya lista de actas se puede recorrer sin navegador y cuyas actas traen el voto.

- Cabildo de Lanzarote (cabildo-lanzarote): portal de transparencia
  (transparencia.cabildodelanzarote.com, «Sesiones de pleno»). La página carga con JavaScript,
  pero lee una API JSON pública (/api/v1/entity-record/index-all?dynamic_entity_uuid=…) que
  devuelve todas las sesiones de una vez: fecha, tipo, convocatoria, acta (PDF y formato abierto)
  y vídeo. Cobertura: enero de 2022 a diciembre de 2025, 61 actas. En septiembre de 2026 aún no
  había actas de 2026, y las anteriores a 2022 no están en este portal. Actas en castellano, largas (100-500 páginas) y casi literales. El voto
  va por punto: «A favor: 19, En contra: 0, Abstenciones: 1» y «Votaron a favor: GRUPO POPULAR…».
  En 2022 lo escriben como «en votación ordinaria y por unanimidad, ACUERDA…».
- Consell de Mallorca (consell-mallorca): «Arxiu de sessions plenàries (PDF)» de la seu
  electrònica, una carpeta Liferay por año (portlet LlistaCarpeta). Cobertura: enero de 2013 a
  diciembre de 2016, 79 actas (con la sesión constitutiva de 2015). Desde
  2017 el acta oficial es la videoacta de la mediateca Séneca (mallorca.seneca.tv), que solo da el
  orden del día y el vídeo, sin texto de las votaciones. Actas en catalán, con frases como
  «s'aprova per devuit vots a favor (PP), deu vots en contra (PSOE) i quatre abstencions (MÉS per
  Mallorca)».

Incremental: la lista se pide entera en cada ejecución (una llamada a la API en Lanzarote y cinco
páginas en Mallorca, cuyo archivo está cerrado y se guarda 30 días). Se recorre de lo más reciente
a lo más antiguo, parando en `ctx.desde(cuerpo)`. Los PDF se guardan en la caché de actas_llm.

Limitaciones:
- `sesion` es AAAAMMDD * 10 + k: k es el orden de la sesión dentro del día (hay días con dos o tres
  plenos). Se calcula sobre la lista completa, así que no cambia entre ejecuciones.
- Lanzarote: el portal tiene errores de carga. Hay registros con la fecha mal puesta (p. ej. el
  pleno del 14-01-2022 figura como 14-12-2022, y el del 21-03-2024 como 23-02-2024) y actas
  cruzadas entre registros (las del 5 y el 9 de febrero de 2024). Si el nombre del fichero del
  acta, o si no el de la convocatoria, trae otra fecha y la diferencia pasa de 3 días, se usa esa.
  La del portal queda en extra["fecha_portal"]. También hay campos intercambiados (tipo y
  año). Las actas que solo están en ODT o DOCX (la del 27-11-2023 y dos ficheros «Errores.docx»)
  se saltan. Dos de 2024 solo están en TXT (en Windows-1252, por eso el módulo define `texto`) y
  se dan con formato «txt».
- No se incluyen porque no hay forma limpia de sacar actas con votos (septiembre de 2026):
  · Cabildo de Tenerife: el portal de transparencia (Next.js) trae en __NEXT_DATA__ la lista de
    plenos y actas de 2019 a 2026. Pero el acta es solo un índice de puntos con un enlace
    «Acuerdo:» a sede.tenerife.es/verifirma, que pide identificarse con Cl@ve. El texto del acta
    no trae el voto.
  · Cabildo de Gran Canaria: las actas (cabildo.grancanaria.com/documents/38405/…) son muy
    completas («Votos a favor: 26 - Votos en contra: 2 (…VOX)») y se descargan con UA de
    navegador. Pero el listado «sesiones-del-pleno?anyo=AAAA» sale vacío, también en navegador, y
    lo mismo pasa con el buscador. La API headless y el RSS devuelven 503 (Imperva). Las fichas de
    sesión (/w/sesión-ordinaria-de-pleno-DD/MM/AAAA) no son enumerables.
  · Consell de Mallorca desde 2017: solo hay videoacta (Séneca). La API de la línea de tiempo pide
    identificarse.
"""

import json
import re
import urllib.error
import urllib.parse
from datetime import date

from ...territorio import MANDATOS_LOCALES, NUM_CABILDOS, NUM_CONSELLS, Cuerpo
from ..contexto import Contexto, ErrorDescarga
from ..modelo import Documento

NOTAS = __doc__

LEGISLATURAS = dict(MANDATOS_LOCALES)

LANZAROTE_WEB = "https://transparencia.cabildodelanzarote.com"
LANZAROTE_API = (LANZAROTE_WEB + "/api/v1/entity-record/index-all"
                 "?dynamic_entity_uuid=7ef3af52-78b3-4b37-9402-a60fbace05d5")
MALLORCA_WEB = "https://seu.conselldemallorca.net"
MALLORCA_ARXIU = MALLORCA_WEB + "/arxiu-de-sessions-plenaries-pdf-"

CUERPOS = [
    Cuerpo("cabildo-lanzarote", NUM_CABILDOS["lanzarote"], "Cabildo Insular de Lanzarote",
           "Cabildo de Lanzarote", "provincial", "CN", 23, LEGISLATURAS,
           LANZAROTE_WEB + "/sesiones-pleno", "Cabildos insulares"),
    Cuerpo("consell-mallorca", NUM_CONSELLS["mallorca"], "Consell Insular de Mallorca",
           "Consell de Mallorca", "provincial", "IB", 33, LEGISLATURAS,
           MALLORCA_ARXIU, "Consells insulars"),
]
_POR_CODIGO = {c.codigo: c for c in CUERPOS}

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


# ---------------------------------------------------------------------------- comunes

def _sesiones(items):
    """Añade `sesion` = AAAAMMDD * 10 + orden dentro del día. items: [(fecha, clave_orden, dict)]."""
    por_dia = {}
    for fecha, clave, d in sorted(items, key=lambda t: (t[0], t[1])):
        k = por_dia.get(fecha, 0)
        por_dia[fecha] = k + 1
        d["sesion"] = int(fecha.replace("-", "")) * 10 + k
    return [d for _f, _c, d in items]


def _recorrer(ctx, cuerpo, docs):
    """De lo más reciente a lo más antiguo, hasta `ctx.desde(cuerpo)` y `ctx.limite`."""
    desde = ctx.desde(cuerpo)
    n = 0
    for d in sorted(docs, key=lambda d: (d.fecha, d.sesion), reverse=True):
        if desde and d.fecha < desde:
            break
        yield d
        n += 1
        if ctx.limite and n >= ctx.limite:
            break


def _seguro(ctx, cuerpo, funcion):
    """Lista de documentos de una fuente; si su web falla, se avisa y se sigue con las demás."""
    try:
        return list(funcion(ctx))
    except (ErrorDescarga, urllib.error.URLError, ValueError) as e:
        ctx.log(f"! {cuerpo}: no se pudo leer la lista de actas: {e}")
        return []


def documentos(ctx):
    # Por turnos entre instituciones, para que una prueba con límite vea todas.
    fuentes = [_recorrer(ctx, c, _seguro(ctx, c, f)) for c, f in
               (("cabildo-lanzarote", _lanzarote), ("consell-mallorca", _mallorca))]
    while fuentes:
        for g in list(fuentes):
            d = next(g, None)
            if d is None:
                fuentes.remove(g)
            else:
                yield d


def texto(ctx, doc):
    """Como actas_llm.texto_documento, pero los TXT de Lanzarote vienen en Windows-1252, no en UTF-8."""
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/docs/{Contexto.clave(doc.url)}.{doc.formato}")
    if doc.formato == "pdf" or raw[:5] == b"%PDF-":
        return Contexto.pdf_texto(raw, layout=False)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


# ---------------------------------------------------------------------------- Lanzarote

def _valor(v):
    if isinstance(v, dict):
        v = v.get("es") or next(iter(v.values()), None)
    return (str(v).strip() if v is not None else "") or None


def _fecha_en_nombre(nombre):
    """Fecha de la sesión escrita en el nombre de un fichero del portal, si la hay."""
    nombre = urllib.parse.unquote(nombre or "")
    nombre = re.split(r"(?i)aprobada", nombre)[0]  # «…aprobada definitivamente el 25 de abril»
    m = re.search(r"(?<!\d)(\d{2})-(\d{2})-(20\d{2})(?!\d)", nombre)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(?i)(?<!\d)(\d{1,2})_de_([a-z]+)_de_(20\d{2})", nombre)
        if not m or m.group(2).lower() not in MESES:
            return None
        dia, mes, ano = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3))
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _fichero(x, clave):
    f = x.get(clave)
    return f.get("image") if isinstance(f, dict) and f.get("image") else None


def _lanzarote(ctx):
    datos = json.loads(ctx.texto(LANZAROTE_API, headers={"Accept": "application/json"}))
    cuerpo = _POR_CODIGO["cabildo-lanzarote"]
    items, vistas = [], set()
    for reg in datos.get("data") or []:
        x = reg.get("data") or {}
        fecha = x.get("inputDateComponent") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
            continue
        acta, formato = None, None
        for clave in ("documentUploadComponent2", "documentUploadComponent3"):
            ruta = _fichero(x, clave)
            ext = (ruta or "").rsplit(".", 1)[-1].lower()
            if ext in ("pdf", "txt"):
                acta, formato = ruta, ext
                break
        if not acta:
            continue  # sin acta publicada, o solo en ODT/DOCX
        url = LANZAROTE_WEB + urllib.parse.quote(acta, safe="/%()._-~,")
        if url in vistas:
            continue
        vistas.add(url)
        convocatoria = _fichero(x, "documentUploadComponent") or _fichero(x, "documentUploadComponent1")
        extra = {"id_portal": reg.get("id"), "convocatoria": LANZAROTE_WEB + urllib.parse.quote(convocatoria, safe="/%()._-~,") if convocatoria else None,
                 "video": x.get("builderLinkInputComponent") or None}
        otra = _fecha_en_nombre(acta) or _fecha_en_nombre(convocatoria)
        if otra and abs((date.fromisoformat(otra) - date.fromisoformat(fecha)).days) > 3:
            # El portal tiene la fecha mal o el acta colgada en otro registro: manda la del fichero,
            # y la convocatoria y el vídeo del registro solo se guardan si cuadran con ella.
            extra["fecha_portal"] = fecha
            fecha = otra
            extra["video"] = None
            if _fecha_en_nombre(convocatoria) != fecha:
                extra["convocatoria"] = None
        # «tipo» y «año» vienen a veces intercambiados.
        tipo = next((v for v in (_valor(x.get("builderLanguageInputComponent")), _valor(x.get("builderInputComponent1")))
                     if v and not re.fullmatch(r"\d{4}", v)), None)
        extra["tipo"] = tipo
        titulo = f"Acta de la sesión {tipo.lower() if tipo else ''} del Pleno del Cabildo de Lanzarote de {fecha}".replace("  ", " ")
        items.append((fecha, reg.get("id") or 0, dict(fecha=fecha, url=url, formato=formato, titulo=titulo, extra=extra)))
    return [Documento(cuerpo=cuerpo.codigo, fecha=d["fecha"], url=d["url"], sesion=d["sesion"], formato=d["formato"],
                      idioma="es", titulo=d["titulo"], legislatura=cuerpo.legislatura_de(d["fecha"]), extra=d["extra"])
            for d in _sesiones(items)]


# ---------------------------------------------------------------------------- Mallorca

TIPOS_MALLORCA = {"ordinaria": "ordinària", "extraordinaria": "extraordinària",
                  "extraordinaria_i_urgent": "extraordinària i urgent", "extraordinaria_urgent": "extraordinària urgent",
                  "constitutiva": "constitutiva"}


def _mallorca(ctx):
    cuerpo = _POR_CODIGO["consell-mallorca"]
    portada = ctx.texto(MALLORCA_ARXIU, cache="consell-mallorca/llistes/arxiu.html", caduca_dias=30)
    carpetas = []  # (año, url de la carpeta)
    for m in re.finditer(r'href="([^"]*_fldid=(\d+)[^"]*)"[^>]*>\s*(\d{4})\s*</a>', portada):
        url = m.group(1).replace("&amp;", "&").split("#")[0]
        carpetas.append((int(m.group(3)), url, m.group(2)))
    if not carpetas:
        raise ValueError("no se encontraron las carpetas por año del archivo de plenos")
    items = []
    for ano, url, fld in sorted(set(carpetas), reverse=True):
        pagina = ctx.texto(url, cache=f"consell-mallorca/llistes/{fld}.html", caduca_dias=30)
        for m in re.finditer(r'href="(/documents/\d+/\d+/([^"/?]+\.pdf))"', pagina):
            ruta, nombre = m.group(1), m.group(2)
            p = re.match(r"(\d{4})(\d{2})(\d{2})(?:_(\d+))?_sessio_(.+?)(?:_ple)?\.pdf$", nombre)
            if not p:
                ctx.log(f"  consell-mallorca: fichero sin el patrón de acta, se salta: {nombre}")
                continue
            fecha = f"{p.group(1)}-{p.group(2)}-{p.group(3)}"
            tipo = TIPOS_MALLORCA.get(p.group(5), p.group(5).replace("_", " "))
            titulo = f"Acta de la sessió {tipo} del Ple del Consell de Mallorca de {fecha}"
            items.append((fecha, nombre, dict(fecha=fecha, url=MALLORCA_WEB + ruta, titulo=titulo,
                                               extra={"tipo": tipo, "carpeta": fld, "any": ano})))
    vistas, docs = set(), []
    for d in _sesiones(items):
        if d["url"] in vistas:
            continue
        vistas.add(d["url"])
        docs.append(Documento(cuerpo=cuerpo.codigo, fecha=d["fecha"], url=d["url"], sesion=d["sesion"], formato="pdf",
                              idioma="ca", titulo=d["titulo"], legislatura=cuerpo.legislatura_de(d["fecha"]),
                              extra=d["extra"]))
    return docs
