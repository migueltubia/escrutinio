"""Plataforma «Audio Vídeo Actas» (AVA) de eCityclic, que usan varios ayuntamientos andaluces.

No es un conector (empieza por «_»): lo usan malaga.py (videoactas.malaga.eu) y cordoba.py
(oficinavirtual.cordoba.es/actas). La plataforma no tiene API pública; todo sale del HTML:

- Buscador de sesiones: <base>/session/fragmentCustom?sessionTypeId=<órgano>&max=&offset=&sort=
  sessionDate&order=desc. El id del órgano («Pleno Municipal») está en el desplegable del propio
  formulario. Cada sesión es una caja con título, tipo (ordinaria, extraordinaria…), fecha y hora, y
  un enlace a su ficha (sessionDetail/<id de 32 hex>).
- Ficha de la sesión: documentos (downloadItem/<id>: orden del día, extracto, acta…) y, si hay
  vídeo, el índice de puntos del orden del día («topicTitle»), que trae los títulos bien escritos.
"""

import html
import re
import urllib.error
from datetime import date

from ..contexto import ErrorDescarga

POR_PAGINA = 50

CAJA_RE = re.compile(
    r'<div class="title" title="([^"]*)".*?<div class="type">(.*?)</div>.*?'
    r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})h.*?sessionDetail/([0-9a-f]{32})', re.S)
DOC_RE = re.compile(
    r'href="[^"]*/session/downloadItem/([0-9a-f]{32})"\s+title="([^"]*)".*?class="doc-link-name">([^<]*)<', re.S)
PUNTO_VIDEO_RE = re.compile(r'<span class="topicTitle"\s*>(.*?)</span>', re.S)


def _texto_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def organo(ctx, base, nombre, defecto):
    """Id del órgano `nombre` en el desplegable del buscador (o `defecto` si no se encuentra)."""
    try:
        h = ctx.texto(f"{base}/session/portadaPublica")
    except (ErrorDescarga, urllib.error.URLError) as e:
        ctx.log(f"  ! {base}: portada sin cargar ({e}); se usa el órgano conocido")
        return defecto
    for valor, texto in re.findall(r'<option value="([0-9a-f]{32})"[^>]*>(.*?)</option>', h, re.S):
        if _texto_html(texto).lower() == nombre.lower():
            return valor
    return defecto


def sesiones(ctx, base, id_organo, desde=None):
    """Sesiones del órgano, de la más reciente a la más antigua, hasta la fecha `desde` (ISO).

    Devuelve dicts con id, titulo, tipo, fecha (AAAA-MM-DD), hora (HH:MM) y url de la ficha. El
    buscador no se guarda en caché: cambia con cada sesión nueva.
    """
    offset, vistas = 0, set()
    while True:
        url = (f"{base}/session/fragmentCustom?searchText=&sessionTypeId={id_organo}&startDate=&endDate="
               f"&search=yes&max={POR_PAGINA}&offset={offset}&sort=sessionDate&order=desc")
        h = ctx.texto(url)
        cajas = CAJA_RE.findall(h)
        nuevas = 0
        for titulo, tipo, d, m, a, hora, sid in cajas:
            if sid in vistas:
                continue
            vistas.add(sid)
            nuevas += 1
            fecha = f"{a}-{m}-{d}"
            if desde and fecha < desde:
                return
            yield {"id": sid, "titulo": _texto_html(titulo), "tipo": _texto_html(tipo), "fecha": fecha,
                   "hora": hora, "url": f"{base}/session/sessionDetail/{sid}"}
        if not nuevas or len(cajas) < POR_PAGINA:
            return
        offset += POR_PAGINA


def ficha(ctx, base, sesion, cache, falta=None):
    """Documentos y puntos (índice del vídeo) de la ficha de una sesión.

    - documentos: [(id, fichero, nombre, url)] en el orden de la página.
    - puntos: títulos del índice del vídeo, tal cual («PUNTO Nº 02.- Dictamen relativo a…»).
    La ficha se guarda en caché (un día si la sesión tiene menos de 14 meses; si no, medio año). Si
    a la copia guardada le falta el documento que se busca (`falta(documentos)` es verdadero), se
    vuelve a pedir: el acta se publica meses después de la sesión.
    """
    reciente = (date.today() - date.fromisoformat(sesion["fecha"])).days < 430
    raw = ctx.fetch(sesion["url"], cache=cache, caduca_dias=1 if reciente else 180)
    docs, puntos = _leer_ficha(raw, base)
    if falta and falta(docs):
        raw = ctx.fetch(sesion["url"], cache=cache, caduca_dias=0)
        docs, puntos = _leer_ficha(raw, base)
    return docs, puntos


def _leer_ficha(raw, base):
    h = raw.decode("utf-8", "replace")
    docs = [(i, html.unescape(f).strip(), _texto_html(n), f"{base}/session/downloadItem/{i}")
            for i, f, n in DOC_RE.findall(h)]
    puntos = [_texto_html(p) for p in PUNTO_VIDEO_RE.findall(h)]
    return docs, puntos
