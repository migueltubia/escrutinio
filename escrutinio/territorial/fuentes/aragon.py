"""Cortes de Aragón: Diario de Sesiones del Pleno (PDF) para extraer las votaciones con un LLM.

Fuente: la base Lotus Domino bases.cortesaragon.es/bases/original.nsf. Su vista por defecto se lee en
XML (?ReadViewEntries) y está agrupada por «Legislatura XII» > «DSCA PLENOS» > un documento por número
del Diario («Num:6 (28/05/2026)»); la ficha de cada documento (?OpenDocument) enlaza el PDF. No hay
datos estructurados de votaciones: la página «Votaciones» de la web es solo la guía del Reglamento, y
el Diario da los totales en texto libre («Presentes, sesenta y uno; … votos a favor, veinticuatro…»),
con correcciones de voto telemático que no se prestan a reglas.

Cobertura: legislaturas X (2019), XI (2023) y XII (2026). El Diario oficial sale con unos 4 meses de
retraso. La base tiene errores que se sortean así:
- fichas cuyo PDF es de otro número («Num:54» con el DSCA_2 de la XII, 42 y 45 de la XI): se descartan;
- fechas mal tecleadas en la vista (X 38 y 59): se toma la del nombre del fichero si la de la vista
  rompe el orden con los números vecinos;
- el DSCA 46 de la X es de la Diputación Permanente: fuera, no es el Pleno.
Los huecos que dejan esos descartes y el final de la XI (16-10 a 12-12-2025, sin Diario oficial) se
cubren con las transcripciones provisionales (tprovisional.nsf, un PDF por media jornada, agrupadas
por el identificador de sesión del nombre del fichero). Solo en legislaturas cerradas o para fechas
anteriores al último Diario oficial: la cola de la legislatura en curso espera al Diario, para no
duplicar sesiones. `sesion` es el número del Diario (oficial) o el identificador interno de la sesión
(provisional, extra["provisional"] = True).
"""

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from ...territorio import Cuerpo, num_parlamento, romano
from ..modelo import Documento

CODIGO = "parl-AR"
CUERPOS = [
    Cuerpo(CODIGO, num_parlamento("AR"), "Cortes de Aragón", "Cortes (Aragón)", "autonomico", "AR", 67,
           {10: (romano(10), "2019-06-20", "2023-06-23"),
            11: (romano(11), "2023-06-23", "2026-03-03"),
            12: (romano(12), "2026-03-03", None)},
           web="https://www.cortesaragon.es"),
]
NOTAS = ("Diario de Sesiones del Pleno en PDF (base Domino original.nsf, vista XML) para LLM; X-XII legislatura. "
         "Se descartan fichas con el PDF de otro número y la Diputación Permanente; los huecos y el final de la XI "
         "se cubren con transcripciones provisionales (extra.provisional). El Diario sale con ~4 meses de retraso.")

BASES = "https://bases.cortesaragon.es"
VISTA = BASES + "/bases/original.nsf/$defaultview?ReadViewEntries"
PROVISIONALES = "https://www.cortesaragon.es/Transcripciones-provisionales.2245.0.html?&no_cache=1"

NUM_RE = re.compile(r"Num:\s*(\d+)\D*?\((\d{2})/(\d{2})/(\d{4})\)")
PDF_RE = re.compile(r'href="(/bases/original\.nsf/0/[0-9a-fA-F]{32}/\$FILE/[^"]+)"')
NUM_FICHERO_RE = re.compile(r"(?:^|/)DSCA[\s_-]*(?:PLENO[\s_-]*)?(\d+)", re.I)
FECHA_FICHERO_RE = re.compile(r"(20\d\d)[-_](\d{1,2})[-_](\d{1,2})")
PROV_RE = re.compile(r'href="(https://bases\.cortesaragon\.es/bases/tprovisional\.nsf/[^"]+/\$File/([^"]+))"[^>]*>'
                     r"\s*(\d{2})\.(\d{2})\.(\d{4})([^<]*)<")
COMISION_RE = re.compile(r"^(?:[AB]-?\d+|R)$", re.I)  # códigos de sesión de comisión mal clasificados


def _fecha(a, m, d):
    try:
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _entradas(texto):
    return [(ve.get("position"), ve.get("unid"), [t.text or "" for t in ve.iter("text")])
            for ve in ET.fromstring(texto.encode("utf-8"))]


def _diarios(ctx, raiz, n, fin, desde):
    """Diarios oficiales del Pleno de la legislatura n, del más antiguo al más reciente (raiz: vista plegada)."""
    rom = romano(n)
    pos = None
    for p, _u, txt in _entradas(raiz):
        if txt and txt[0].strip() == f"Legislatura {rom}":
            pos = p
    if pos is None:
        return []
    m = re.search(rf'position="{re.escape(pos)}"[^>]*children="(\d+)" descendants="(\d+)"', raiz)
    cuenta = int(m.group(1)) + int(m.group(2)) + 1 if m else 2000
    vista = ctx.texto(f"{VISTA}&Start={pos}&Count={cuenta}",
                      cache=f"{CODIGO}/vista/{rom}.xml" if fin else None, caduca_dias=7 if fin else None)
    entradas = _entradas(vista)
    cat = next((p for p, u, t in entradas if not u and t and t[0].strip().upper() == "DSCA PLENOS"
                and p.count(".") == 1 and p.startswith(pos + ".")), None)
    if cat is None:
        return []
    por_num = {}
    for p, unid, txt in entradas:
        if not unid or not p.startswith(cat + ".") or p.count(".") != 2:
            continue
        m = NUM_RE.search(txt[0] if txt else "")
        if not m:
            continue
        num = int(m.group(1))
        por_num.setdefault(num, {"num": num, "unid": unid, "fecha": _fecha(m.group(4), m.group(3), m.group(2))})
    diarios = [d for d in sorted(por_num.values(), key=lambda d: d["num"]) if d["fecha"]]
    # Ficha de cada documento (nombre del PDF), solo para lo que interesa en esta recogida.
    limite_fecha = (date.fromisoformat(desde) - timedelta(days=7)).isoformat() if desde else None
    for d in diarios:
        if limite_fecha and d["fecha"] < limite_fecha:
            continue
        ficha = ctx.texto(f"{BASES}/bases/original.nsf/0/{d['unid']}?OpenDocument",
                          cache=f"{CODIGO}/fichas/{d['unid']}.html", caduca_dias=30)
        m = PDF_RE.search(ficha)
        if not m:
            continue
        href = html.unescape(m.group(1))
        fichero = urllib.parse.unquote(href.split("$FILE/", 1)[1])
        d["url"], d["fichero"] = BASES + href, fichero
        mf = FECHA_FICHERO_RE.search(fichero)
        d["fecha_fichero"] = _fecha(*mf.groups()) if mf else None
        mn = NUM_FICHERO_RE.search(fichero)
        if mn and int(mn.group(1)) != d["num"]:
            d["descarte"] = f"el PDF ({fichero}) es de otro número"
        elif "permanente" in fichero.lower():
            d["descarte"] = "Diputación Permanente"
    _corregir_fechas(diarios)
    return diarios


def _corregir_fechas(diarios):
    """Si la fecha de la vista y la del fichero no coinciden, se queda la que respete el orden de números."""
    dudosa = [bool(d.get("fecha_fichero")) and d["fecha_fichero"] != d["fecha"] for d in diarios]
    for i, d in enumerate(diarios):
        if not dudosa[i]:
            continue
        antes = next((diarios[j]["fecha"] for j in range(i - 1, -1, -1) if not dudosa[j]), None)
        despues = next((diarios[j]["fecha"] for j in range(i + 1, len(diarios)) if not dudosa[j]), None)

        def cabe(f):
            return (antes is None or antes <= f) and (despues is None or f <= despues)

        if not cabe(d["fecha"]) and cabe(d["fecha_fichero"]):
            d["fecha"] = d["fecha_fichero"]


def _provisionales(ctx):
    """Transcripciones provisionales del Pleno agrupadas por sesión: [{fechas, partes, etiquetas, sesion}]."""
    pagina = ctx.texto(PROVISIONALES)
    grupos = {}
    for seccion in pagina.split('class="accordion-toggle"')[1:]:
        m = re.search(r'href="#collapse\d*">([^<]*)', seccion)
        if not m or m.group(1).strip().lower() != "pleno":
            continue
        for url, fichero, d, mes, a, resto in PROV_RE.findall(seccion):
            etiqueta = html.unescape(resto).replace("\xa0", " ").strip().strip("()").strip()
            fecha = _fecha(a, mes, d)
            if not fecha or COMISION_RE.match(etiqueta):
                continue
            mp = re.match(r"0*(\d+)[_-]", fichero)
            clave = int(mp.group(1)) if mp else fecha
            g = grupos.setdefault(clave, {"sesion": clave if mp else 0, "partes": {}})
            url = url.split("$File/")[0] + "$File/" + urllib.parse.quote(html.unescape(fichero))
            orden = 1 if "tarde" in etiqueta.lower() else 0
            g["partes"][url] = (fecha, orden, fichero, etiqueta)
    salida = []
    for g in grupos.values():
        partes = sorted(g["partes"].items(), key=lambda kv: kv[1][:3])
        salida.append({"sesion": g["sesion"], "partes": [u for u, _ in partes],
                       "fechas": sorted({p[0] for _, p in partes}),
                       "etiquetas": [p[3] for _, p in partes if p[3]]})
    return salida


def documentos(ctx):
    cuerpo = CUERPOS[0]
    desde = ctx.desde(CODIGO)
    n_doc = 0
    provisionales = raiz = None
    for n in sorted(cuerpo.legislaturas, reverse=True):
        rom, ini, fin = cuerpo.legislaturas[n][:3]
        if desde and fin and fin < desde:
            break
        raiz = raiz or ctx.texto(VISTA + "&CollapseView&Count=100")
        diarios = _diarios(ctx, raiz, n, fin, desde)
        docs = []
        for d in diarios:
            if not d.get("url"):
                continue
            if d.get("descarte"):
                ctx.log(f"  Aragón: descartado el DSCA {d['num']} ({rom}): {d['descarte']}")
                continue
            if cuerpo.legislatura_de(d["fecha"]) != n:
                ctx.log(f"  Aragón: DSCA {d['num']} ({rom}) con fecha {d['fecha']} fuera de la legislatura")
                continue
            docs.append(Documento(CODIGO, d["fecha"], d["url"], sesion=d["num"], formato="pdf", idioma="es",
                                  titulo=f"Diario de Sesiones de las Cortes de Aragón n.º {d['num']} ({rom} "
                                         f"legislatura), sesión plenaria",
                                  legislatura=n, extra={"fichero": d["fichero"]}))
        # Transcripciones provisionales de sesiones sin Diario oficial (huecos o legislatura cerrada).
        oficiales = sorted(doc.fecha for doc in docs)
        ultimo = oficiales[-1] if oficiales else None
        if provisionales is None:
            provisionales = _provisionales(ctx)
        for g in provisionales:
            f0, f1 = g["fechas"][0], g["fechas"][-1]
            if cuerpo.legislatura_de(f0) != n or (desde and f1 < desde):
                continue
            # Cubierta si un Diario empieza dentro de la sesión o el día antes (sesiones de jueves y viernes).
            previo = (date.fromisoformat(f0) - timedelta(days=1)).isoformat()
            if any(previo <= f <= f1 for f in oficiales) or not (fin or (ultimo and f1 < ultimo)):
                continue
            etiquetas = ", ".join(dict.fromkeys(g["etiquetas"]))
            docs.append(Documento(CODIGO, f0, g["partes"][0], sesion=g["sesion"], formato="pdf", idioma="es",
                                  titulo=f"Transcripción provisional de la sesión plenaria del {' y '.join(g['fechas'])}"
                                         + (f" ({etiquetas})" if etiquetas else ""),
                                  legislatura=n, extra={"provisional": True, "partes": g["partes"]}))
        for doc in sorted(docs, key=lambda x: (x.fecha, not x.extra.get("provisional"), x.sesion), reverse=True):
            if desde and doc.fecha < desde:
                break
            yield doc
            n_doc += 1
            if ctx.limite and n_doc >= ctx.limite:
                return


def texto(ctx, doc):
    """Texto del PDF; las transcripciones provisionales juntan sus partes (mañana, tarde, viernes…)."""
    trozos = []
    for url in doc.extra.get("partes") or [doc.url]:
        raw = ctx.fetch(url, cache=f"{doc.cuerpo}/docs/{ctx.clave(url)}.pdf")
        trozos.append(ctx.pdf_texto(raw, layout=False))
    return "\n\n".join(trozos)
