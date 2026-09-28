"""Ayuntamiento de València: resultado de las mociones del Pleno (CSV) y actas del Pleno (para LLM).

Fuentes (web municipal, www.valencia.es):
- «Pleno: seguimiento de mociones y declaraciones institucionales» (trazabilidad), una página por
  año desde 2018 con un CSV por sesión (y su PDF). Cada CSV empieza con «SESIÓN PLENARIA
  [EXTRAORDINARIA] DE 28 DE OCTUBRE DE 2025» y trae por moción o declaración institucional: TIPO,
  ASUNTO, ENLACE A INICIATIVA (código «I-ENERO2025-3»), GRUPO/S y PROPONENTE/S que la presentan,
  RESULTADOS («Aprobada», «Aprobada propuesta alternativa», «Rechazada», «Rechazada la urgencia»,
  «Retirada»…), servicio competente y actuaciones. No trae recuento ni voto por grupo: de aquí
  sale una votación por moción con el resultado oficial, el autor y el código («csv»).
- «Plenos del Ayuntamiento por años»: una página por año con las sesiones y, en cada sesión, el
  orden del día y el acta firmada (A_00001_AAAAMMDD_HHMM_0_firmadoweb.pdf). El acta es bilingüe
  (valenciano y castellano, a dos columnas) y es donde está el voto por grupo: va como documento
  para el extractor LLM (`documentos`).

Cobertura: mandatos X (desde el 13/06/2015), XI y XII. Mociones del CSV desde 2018 (antes solo hay
declaraciones institucionales de 2015 a 2018 en otra página, sin resultado); actas desde 2015.

Limitaciones: el CSV solo recoge mociones y declaraciones institucionales, no los dictámenes; las
retiradas no se dan como votación. «Aprobada propuesta alternativa» significa que se votó y aprobó
un texto alternativo (normalmente del gobierno) en lugar del de la moción: se da como aprobada con
subtítulo «Propuesta alternativa» y el texto original del resultado en extra. «Rechazada la
urgencia» es la votación de la urgencia (subtítulo «Urgencia»). Las mociones del CSV también
estarán en el acta: el extractor LLM debe cruzarlas por fecha y título (extra["mociones_csv"]).
sesion = AAAAMMDD * 10 + tipo (0 ordinaria, 1 extraordinaria, 2 urgente; +3 si hay otra del
mismo tipo ese día); numero = el del código de la iniciativa («I-ENERO2025-3» -> 3).
"""

import csv
import html
import io
import re
import unicodedata
from datetime import date

from ... import territorio
from ..modelo import Documento, Votacion

CODIGO = "ayto-valencia"
BASE = "https://www.valencia.es"
SEGUIMIENTO = (BASE + "/cas/ayuntamiento/actividad-politica-del-pleno-y-las-comisiones/-/content/"
               "pleno-actividad-pol%C3%8Dtica-del-pleno-y-las-comisiones?uid=72C8FD8A3A00A55DC12583E50038A172")
PLENOS = BASE + "/cas/ayuntamiento/plenodelayuntamiento/-/categories/36871053"
INICIO = "2015-06-13"

CUERPOS = [
    territorio.Cuerpo(CODIGO, territorio.num_municipio("46250"), "Ayuntamiento de València", "València",
                      "municipal", "VC", 33, {n: territorio.MANDATOS_LOCALES[n] for n in (10, 11, 12)},
                      web=BASE + "/cas/ayuntamiento/actividad-politica-del-pleno-y-las-comisiones"),
]

# Las actas traen el voto de cada grupo y los asuntos que el CSV no recoge: van al LLM aunque ese día ya
# tenga las mociones del CSV (la fusión de actas_llm evita repetirlas).
DOCUMENTOS_COMPLETAN = True

NOTAS = ("Mociones y declaraciones institucionales del Pleno desde 2018 con resultado oficial, grupo "
         "proponente y código, del CSV municipal de trazabilidad (sin recuento ni voto por grupo). Actas "
         "bilingües del Pleno desde el 13/06/2015 como documentos para el extractor LLM (voto por grupo). "
         "Las retiradas no se dan; «Aprobada propuesta alternativa» sale como aprobada con subtítulo. "
         "sesion = AAAAMMDD*10 + tipo de sesión.")

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
TIPO_SESION = {"ordinaria": 0, "extraordinaria": 1, "urgente": 2}


def _plano(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _limpio(s):
    s = html.unescape(s or "").replace("\xa0", " ").replace("•", " ")
    return re.sub(r"\s+", " ", s).strip(" ;")


def _html_texto(s):
    return _limpio(re.sub(r"<[^>]+>", " ", s))


def _pagina(ctx, url, cache, caduca_dias=None):
    return ctx.fetch(url, cache=cache, caduca_dias=caduca_dias).decode("utf-8", "replace")


def _absoluta(href):
    href = html.unescape(href)
    return href if href.startswith("http") else BASE + href


def _sesiones_por_codigo(items):
    """[(fecha, tipo, orden)] -> sesion: AAAAMMDD*10 + tipo, +3 por cada repetición del mismo tipo y día."""
    vistos, salida = {}, []
    for fecha, tipo, orden in items:
        base = TIPO_SESION.get(tipo, 1)
        n = vistos.get((fecha, base), 0)
        vistos[(fecha, base)] = n + 1
        salida.append(int(fecha.replace("-", "")) * 10 + base + 3 * n)
    return salida


# ---------------------------------------------------------------------------- mociones (CSV)

def _paginas_anuales(ctx):
    """[(año, url)] de las páginas de trazabilidad por año, de la más reciente a la más antigua."""
    h = _pagina(ctx, SEGUIMIENTO, "ayto-valencia/seguimiento.html", caduca_dias=1)
    anos = {}
    for href, ano in re.findall(r'href="([^"]*general-por-a[^"]*uid=[^"]+)".{0,400}?A[ñn]o (\d{4})', h, re.S):
        anos.setdefault(int(ano), _absoluta(href))
    return sorted(anos.items(), reverse=True)


def _csvs_de_ano(ctx, ano, url):
    """[(texto del enlace, url)] de los CSV de un año, en el orden de la página (más reciente primero)."""
    actual = ano >= date.today().year - 1
    h = _pagina(ctx, url, f"ayto-valencia/seguimiento-{ano}.html", caduca_dias=1 if actual else 60)
    salida = []
    for href, txt in re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', h, re.S):
        t = _html_texto(txt)
        if "/documents/" in href and re.search(r"(?i)\(csv\b|\.csv", t + " " + href):
            salida.append((t, _absoluta(href)))
    return salida


def _decodificar(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _fecha_texto(t, ano=None):
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-z]+)\s*(?:de\s+)?(\d{4})", _plano(t))
    if m and m.group(2) in MESES:
        return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1))).isoformat()
    m = re.search(r"(\d{1,2})\s*de\s*([a-z]+)", _plano(t))
    if m and ano and m.group(2) in MESES:
        return date(ano, MESES[m.group(2)], int(m.group(1))).isoformat()
    return None


def _tipo_sesion(t):
    p = _plano(t)
    if "urgente" in p or "urgent" in p:
        return "urgente"
    if "extraordinari" in p or "extra" in p.split("-"):
        return "extraordinaria"
    return "ordinaria"


def _leer_csv(raw):
    """(cabecera de la sesión, [dict por fila]) de un CSV de trazabilidad."""
    t = _decodificar(raw)
    filas = list(csv.reader(io.StringIO(t, newline=""), delimiter=";"))
    titulo, cab, datos = "", None, []
    for f in filas:
        celdas = [c.strip() for c in f]
        if cab is None:
            if celdas and _plano(celdas[0]) == "tipo":
                cab = [_plano(c).replace("*", "").strip() for c in celdas]
            elif any(celdas) and not titulo:
                titulo = _limpio(" ".join(celdas))
            continue
        if not celdas or not _limpio(celdas[0]):
            continue
        datos.append({cab[i]: c for i, c in enumerate(celdas) if i < len(cab)})
    return titulo, datos


def _columna(fila, *nombres, bruto=False):
    for k, v in fila.items():
        if any(k.startswith(n) for n in nombres):
            return v if bruto else _limpio(v)
    return ""


def _resultado(r):
    p = _plano(r)
    if p.startswith("aprobad"):
        return "aprobada"
    if p.startswith("rechazad") or p.startswith("desestimad") or p.startswith("no aprobad"):
        return "rechazada"
    return None


def _tipo_iniciativa(tipo):
    p = _plano(tipo)
    if "mocion" in p:
        return "mocion"
    if "declaracion" in p:
        return "otro"
    return "otro"


def _grupos(g):
    """«• Compromís \\n• Socialista» -> «Compromís, Socialista»."""
    partes = [_limpio(x).strip(" ,.") for x in re.split(r"\s{2,}|•|\n", (g or "").replace("\xa0", " "))]
    return ", ".join(dict.fromkeys(x for x in partes if x)) or None


def _mociones(ctx, desde):
    for ano, url in _paginas_anuales(ctx):
        if desde and ano < int(desde[:4]):
            break
        enlaces = _csvs_de_ano(ctx, ano, url)
        sesiones = []
        for txt, csv_url in enlaces:
            raw = ctx.fetch(csv_url, cache=f"ayto-valencia/csv/{ctx.clave(csv_url)}.csv")
            titulo, filas = _leer_csv(raw)
            fecha = _fecha_texto(titulo) or _fecha_texto(txt, ano)
            if not fecha:
                ctx.log(f"  València: CSV sin fecha de sesión: {csv_url}")
                continue
            sesiones.append({"fecha": fecha, "tipo": _tipo_sesion(titulo + " " + csv_url), "url": csv_url,
                             "titulo": titulo, "filas": filas,
                             "hora": re.search(r"(\d{1,2})-horas", csv_url).group(1).zfill(2)
                             if re.search(r"(\d{1,2})-horas", csv_url) else ""})
        # Si hay dos sesiones del mismo tipo el mismo día, la de hora más temprana va primero.
        sesiones.sort(key=lambda s: (s["fecha"], TIPO_SESION[s["tipo"]], s["hora"], s["url"]))
        for s, ses in zip(sesiones, _sesiones_por_codigo([(s["fecha"], s["tipo"], 0) for s in sesiones])):
            s["sesion"] = ses
        for s in sorted(sesiones, key=lambda s: s["sesion"], reverse=True):
            if s["fecha"] < INICIO or (desde and s["fecha"] < desde):
                continue
            yield s


def _votaciones_csv(s):
    usados = set()
    for i, f in enumerate(s["filas"], 1):
        tipo = _columna(f, "tipo")
        asunto = _columna(f, "asunto")
        res_txt = _columna(f, "resultado")
        codigo = _columna(f, "enlace a iniciativa", "enlace iniciativa") or None
        resultado = _resultado(res_txt)
        if not asunto or resultado is None:
            continue  # retiradas, pendientes o filas sin resultado
        m = re.search(r"-(\d+)\s*$", codigo or "")
        numero = int(m.group(1)) if m else 900 + i
        while numero in usados:
            numero += 1000
        usados.add(numero)
        p = _plano(res_txt)
        subtitulo = None
        if "urgencia" in p:
            subtitulo = "Urgencia"
        elif "alternativa" in p:
            subtitulo = "Propuesta alternativa"
        elif "enmienda" in p:
            subtitulo = "Con enmienda"
        proponentes = _columna(f, "proponente", bruto=True)
        yield Votacion(CODIGO, s["fecha"], asunto.rstrip("."), sesion=s["sesion"], numero=numero,
                       subtitulo=subtitulo, expediente=codigo, tipo_iniciativa=_tipo_iniciativa(tipo),
                       tipo_votacion="mocion" if "mocion" in _plano(tipo) else None,
                       autor=_grupos(_columna(f, "grupo", bruto=True)), resultado=resultado, url=s["url"], fuente="csv",
                       extra={"tipo": tipo, "resultado_fuente": res_txt,
                              "proponentes": _grupos(proponentes),
                              "acuerdo": _columna(f, "enlace acuerdo", "enlace al acuerdo") or None,
                              "sesion_csv": s["titulo"]})


def descargar(ctx):
    desde = ctx.desde(CODIGO)
    n = 0
    for s in _mociones(ctx, desde):
        for v in _votaciones_csv(s):
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


# ---------------------------------------------------------------------------- actas (LLM)

def _anos_plenos(ctx):
    h = _pagina(ctx, PLENOS, "ayto-valencia/plenos.html", caduca_dias=1)
    anos = {}
    for cat, ano in re.findall(r'categories/(\d+)"[^>]*>\s*<span>(\d{4})</span>', h):
        anos.setdefault(int(ano), f"{BASE}/cas/ayuntamiento/plenodelayuntamiento/-/categories/{cat}")
    return sorted(anos.items(), reverse=True)


def _sesiones_de_ano(ctx, ano, url):
    actual = ano >= date.today().year - 1
    h = _pagina(ctx, url, f"ayto-valencia/plenos-{ano}.html", caduca_dias=1 if actual else 60)
    patron = (r"href='(/cas/ayuntamiento/plenodelayuntamiento/-/asset_publisher/[^']+/content/([0-9-]+))'"
              r"[^>]*>\s*<div[^>]*>\s*<img[^>]*>\s*<h3[^>]*>([^<]+)</h3>")
    salida = []
    for href, slug, titulo in re.findall(patron, h):
        fecha = slug[:10]
        tipo = re.search(r"\(([^)]+)\)", titulo)
        salida.append({"url": BASE + href, "slug": slug, "fecha": fecha, "titulo": _limpio(titulo),
                       "tipo": _plano(tipo.group(1)) if tipo else "ordinaria"})
    return salida


def _acta(ctx, s):
    reciente = s["fecha"] >= date.fromordinal(date.today().toordinal() - 120).isoformat()
    h = _pagina(ctx, s["url"], f"ayto-valencia/sesion/{s['slug']}.html", caduca_dias=2 if reciente else None)
    for href in re.findall(r'href="([^"]*/documents/[^"]*/A_[^"/]+\.pdf[^"]*)"', h):
        return _absoluta(href)
    return None


def documentos(ctx):
    desde = ctx.desde(CODIGO)
    n = 0
    for ano, url in _anos_plenos(ctx):
        if ano < int(INICIO[:4]) or (desde and ano < int(desde[:4])):
            break
        sesiones = sorted(_sesiones_de_ano(ctx, ano, url), key=lambda s: (s["fecha"], TIPO_SESION.get(s["tipo"], 1), s["slug"]))
        for s, ses in zip(sesiones, _sesiones_por_codigo([(s["fecha"], s["tipo"], 0) for s in sesiones])):
            s["sesion"] = ses
        for s in sorted(sesiones, key=lambda s: s["sesion"], reverse=True):
            if s["fecha"] < INICIO or (desde and s["fecha"] < desde) or s["fecha"] > date.today().isoformat():
                continue
            acta = _acta(ctx, s)
            if not acta:
                continue  # sesión sin acta publicada todavía
            yield Documento(CODIGO, s["fecha"], acta, sesion=s["sesion"], formato="pdf", idioma="es",
                            titulo=f"Acta del Pleno del Ayuntamiento de València, sesión {s['titulo']}",
                            legislatura=CUERPOS[0].legislatura_de(s["fecha"]),
                            extra={"bilingue": "va/es", "pagina": s["url"], "tipo_sesion": s["tipo"],
                                   "mociones_csv": "las mociones con resultado ya vienen del CSV (descargar)"})
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
