"""Ayuntamiento de Zaragoza: votaciones del Pleno desde el «Extracto de los acuerdos» (HTML, reglas).

Fuentes (sede electrónica, www.zaragoza.es):
- «Sesiones plenarias» (/sede/portal/organizacion/plenos/sesiones-plenarias): una tabla por año
  (2007-2026) con cada sesión, su fecha y tipo, y enlaces al orden del día, las mociones, el
  «Extracto de los acuerdos» (página de publicación fehaciente, /servicio/fehaciente/N, o en 2016
  /servicio/agenda-institucional/attachment/N) y el acta en PDF.
- El extracto de acuerdos es HTML con cada punto en un <li> («8. Expediente número 9.243/2026.-
  Aprobar …. VOTACIÓN: 19 votos a favor (PP/VOX/Concejal no adscrita) y 12 abstenciones
  (PSOE/ZEC). Queda aprobado el dictamen …») y las secciones en <h3> (dictámenes por comisión,
  mociones…); en los plenos extraordinarios y en el debate sobre el estado de la ciudad los puntos
  van en <p> numerados («1.- Expediente …», «3. Propuesta de resolución formulada por …»). Las
  frases son muy regulares desde 2015 y se leen con reglas: totales, grupos por sentido, resultado
  y expediente (o número de registro de la moción, «(17.149)») («html-reglas»). Las mociones con
  votación por puntos o con enmiendas dan una votación por cada recuento; las propuestas de
  resolución del debate del estado de la ciudad van como control.
- La API REST municipal (/sede/servicio/agenda-institucional/mocion.json) solo trae las mociones
  del próximo pleno (texto, grupo y expediente, sin resultado ni votos), y /sesion-plenaria.json
  solo la lista de sesiones: no sirven para el voto.

Cobertura: mandatos X (desde el 13/06/2015), XI y XII; las sesiones que tienen extracto.
Limitaciones: el extracto nombra los grupos de cada sentido pero no cuántos votos pone cada uno;
el recuento por grupo solo se da cuando un sentido lo vota un único grupo. «Unanimidad» sin
recuento sale como asentimiento (con los votos a favor si el extracto dice «el voto favorable de
los 31 miembros»). Los puntos cuyo voto no sigue estas frases se pierden. Las erratas del extracto
en los grupos («PODEMOZ», «ZECPSOE», «PP-PSOE»: unas decenas de 26.000 votos de grupo) se corrigen con
reglas y lo que no es un grupo conocido («el Alcalde», trozos de la frase siguiente) se descarta.
Un recuento que suma más de 31 se da sin totales. El servidor responde 404 al azar: se reintenta.
Resultado: se toma de la primera frase de resultado entre un recuento y el siguiente (o el siguiente
«VOTACIÓN» o etiqueta «…:»), sin contar los resúmenes («Se aprueba por tanto la moción…»); las
votaciones de retirada o de enmiendas sin frase propia quedan sin resultado. Los empates resueltos con
voto de calidad llevan extra["voto_calidad"], y las votaciones en que el propio extracto contradice su
recuento (erratas de la fuente: 4 en 2015-2026) llevan extra["aviso_resultado"].
Las sesiones de varios días (debate del estado de la ciudad) y alguna fila repetida publican el mismo
extracto en cada fila: cada votación se da una vez (la de la fila más reciente).
sesion = número de la publicación fehaciente del extracto (1.000.000 + número en los adjuntos de
2016); numero = N*10000 + M*100 + k para el punto N (subpunto M) y su k-ésima votación.
"""

import difflib
import html
import re
import time
import unicodedata
import urllib.error
from datetime import date
from pathlib import Path

from ... import territorio
from ..contexto import CACHE_DIR
from ..modelo import Votacion, VotoGrupo

CODIGO = "ayto-zaragoza"
BASE = "https://www.zaragoza.es"
SESIONES = BASE + "/sede/portal/organizacion/plenos/sesiones-plenarias"
INICIO = "2015-06-13"

CUERPOS = [
    territorio.Cuerpo(CODIGO, territorio.num_municipio("50297"), "Ayuntamiento de Zaragoza", "Zaragoza",
                      "municipal", "AR", 31, {n: territorio.MANDATOS_LOCALES[n] for n in (10, 11, 12)},
                      web=SESIONES),
]

NOTAS = ("Votaciones del Pleno desde el 13/06/2015 leídas con reglas del «Extracto de los acuerdos» de cada "
         "sesión (HTML de la sede): totales, grupos por sentido (recuento por grupo solo si un sentido lo "
         "vota un único grupo), resultado y expediente. Una votación por recuento (votaciones por puntos y "
         "enmiendas); propuestas de resolución del debate del estado de la ciudad como control. La API REST "
         "municipal no trae resultados. sesion = número del extracto.")

GRUPOS_CANON = {"zec": "ZeC", "c's": "C's", "c s": "C's", "cs": "C's", "cis": "C's", "ciudadanos": "C's",
                "vox": "VOX", "pp": "PP", "psoe": "PSOE", "cha": "CHA", "podemos": "Podemos-Equo",
                "podemos equo": "Podemos-Equo", "iu": "IU", "cna": "Concejales no adscritos"}
# Los grupos de los mandatos X a XII: un nombre que no es ninguno de estos se corrige o se descarta (_erratas).
CANONICOS = set(GRUPOS_CANON.values()) | {"Concejal no adscrito", "Concejal no adscrita"}


def _plano(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _texto(h):
    h = re.sub(r"(?i)<br\s*/?>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).replace("\xa0", " ").strip()


def _pedir(ctx, url, cache=None, caduca_dias=None, valida=None, intentos=8):
    """ctx.fetch con reintentos: el servidor de la sede devuelve 404 al azar."""
    ruta = (CACHE_DIR / cache).with_name(Path(cache).name + ".gz") if cache else None
    ultimo = None
    for i in range(intentos):
        try:
            raw = ctx.fetch(url, cache=cache, caduca_dias=caduca_dias)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            ultimo = e
            time.sleep(0.8 + 0.4 * i)
            continue
        t = raw.decode("utf-8", "replace")
        if valida is None or valida(t):
            return t
        if ruta and ruta.exists():
            ruta.unlink()  # página de error guardada: se pide otra vez
        time.sleep(0.8 + 0.4 * i)
    raise ultimo or RuntimeError(f"Zaragoza: respuesta no válida de {url}")


# ---------------------------------------------------------------------------- sesiones

def _sesiones(ctx):
    """[{fecha, nombre, acuerdo, acta}] de la tabla de sesiones, de la más reciente a la más antigua."""
    h = _pedir(ctx, SESIONES, "ayto-zaragoza/sesiones.html", caduca_dias=1, valida=lambda t: 'id="2016"' in t)
    salida = []
    for fila in re.findall(r"(?s)<tr>(.*?)</tr>", h):
        celdas = re.findall(r'(?s)<td([^>]*)>(.*?)</td>', fila)
        if len(celdas) < 4:
            continue
        por_cab = {}
        for attrs, contenido in celdas:
            m = re.search(r'headers="(\w+)"', attrs)
            por_cab.setdefault(m.group(1) if m else f"col{len(por_cab)}", contenido)
        fecha_txt = _texto(por_cab.get("fecha", ""))
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", fecha_txt)
        acuerdo = re.search(r'href="([^"]*(?:fehaciente|attachment)/(\d+))"', por_cab.get("acuerdo", ""))
        if not acuerdo:
            continue
        href = acuerdo.group(1)
        salida.append({"fecha": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None,
                       "nombre": _texto(por_cab.get("nombre", "")),
                       "acuerdo": href if href.startswith("http") else BASE + href,
                       "sesion": int(acuerdo.group(2)) + (1_000_000 if "attachment" in href else 0)})
    return salida


def _extracto(ctx, s):
    h = _pedir(ctx, s["acuerdo"], f"ayto-zaragoza/extractos/{s['sesion']}.html",
               valida=lambda t: 'id="rscont"' in t)
    i = h.find('id="rscont"')
    j = h.find("ZONA DE DESCARGA", i)
    return h[i:j if j > 0 else None]


# ---------------------------------------------------------------------------- votos

N_VOTO = (r"(?P<n>\d+)\s*(?P<tipo>(?i:(?:votos?\s+)?a\s*favor|votos?\s+favor(?:ables?)?|(?:votos?\s+)?(?:en|a)\s*contra|"
          r"abstenci[oó]n(?:es)?))")
# Grupos entre paréntesis (a veces tras «:» o sin cerrar: «9 votos en contra (ZeC y 2 abstenciones (CHA)»),
# o siglas sueltas sin paréntesis («15 votos a favor PP y 4 abstenciones VOX»). Distingue mayúsculas.
_SIGLA = r"(?:[A-ZÁÉÍÓÚ]{2,}|Ze[Cc]|C[´'’,]s)"
GRUPOS_PAR = (r"(?:\s*:?\s*[(/]+\s*(?P<g>[^()]*?)\s*(?:\)|(?=\s+\d+\s+(?i:votos?|abstenci|en\s+contra|a\s+favor))|$)"
              r"|\s+(?P<g2>" + _SIGLA + r"(?:\s*[/,]\s*" + _SIGLA + r")*)/?(?=\s*(?:\by\b|,|\.|;|\)|$)))?")
RECUENTO = re.compile(N_VOTO + GRUPOS_PAR)
UNANIMIDAD = re.compile(r"\bunanimidad\b", re.I)
EXPEDIENTE = re.compile(r"[Ee]xpediente(?:\s+electr[oó]nico)?\s+n[úu]mero\s+([\d.]+\s*/\s*\d{4})|"
                        r"\((P-\d[\d.]*/\d{4})\)|\((\d[\d.]*/\d{2,4})\.?\)|\((\d{1,3}\.\d{3})\)")
PREFIJO_EXP = re.compile(r"^[Ee]xpediente(?:\s+electr[oó]nico)?\s+n[úu]mero\s+[\d.\s]+/\s*\d{4}\s*\.?-?\s*")
CORTE_TITULO = re.compile(r"\.-\s|VOTACI[ÓO]N|[Ss]ometid[oa]s?\s+a\s+votaci|se\s+somete[n]?\s+a\s+votaci|"
                          r"[Cc]oncluido\s+el\s+debate|[Rr]ETIRAD[AO]|\bUnanimidad\b")


def _grupo(g):
    g = re.sub(r"\s+", " ", g.replace("´", "'").replace("’", "'")).strip(" .,;:")
    g = re.split(r"\.-|\.\s", g)[0].strip(" .,;:")           # paréntesis sin cerrar: «CHA.- Queda aprobado»
    g = re.sub(r"(?i)^(?:y|e)\s+|\s+(?:y|e)$", "", g)          # «CHA y», «y VOX»
    g = re.sub(r"(?i)^(?:grupo\s+(?:municipal\s+)?|g\.?m\.?\s+)", "", g)
    g = re.sub(r"^\d+\s+", "", g)                             # «6 concejales no adscritos»
    fin = re.search(r"(?:[-–]\s*|(?<=[a-z]))([A-Z][A-Za-z']+)$", g)
    if len(g.split()) > 4 and fin:
        g = fin.group(1)                                      # «la señora Torres por una cuestión técnica- VOX»
    m = re.match(r"^conceja\w*?\s*no\s*adscrit([ao])s?$", _plano(g))  # también «Concejalno adscrita»
    if m:
        return f"Concejal no adscrit{m.group(1)}"
    if re.match(r"^concejal\w*\s+no\s+adscrit\w*s$", _plano(g)):
        return "Concejales no adscritos"
    clave = re.sub(r"[^a-z0-9']+", " ", _plano(g)).strip()
    return GRUPOS_CANON.get(clave, g)


def _erratas(g):
    """Grupos conocidos en lo que no es el nombre de un grupo: pegados («PSOE ZEC», «PP-PSOE», «C's.VOX»,
    «ZECPSOE»), con una letra o cifra de más («PSOEA», «VOX9», «PPP») o una cambiada («PODEMOZ»). Lo demás
    («el Alcalde», «HA», restos de la frase siguiente) no es un grupo y se descarta."""
    for separador in (r"\s+", r"[\s.\-]+"):
        trozos = [_grupo(t) for t in re.split(separador, g) if t]
        if len(trozos) > 1 and all(t in CANONICOS for t in trozos):
            return trozos
    junto = re.sub(r"[^a-z0-9']+", "", _plano(g))
    for clave, nombre in GRUPOS_CANON.items():
        resto = junto[len(clave):]
        if junto.startswith(clave) and (resto in GRUPOS_CANON or len(resto) <= 2):
            return [nombre] + ([GRUPOS_CANON[resto]] if resto in GRUPOS_CANON else [])
    parecido = difflib.get_close_matches(junto, [c for c in GRUPOS_CANON if len(c) > 3], n=1, cutoff=0.85)
    return [GRUPOS_CANON[parecido[0]]] if parecido else []


def _grupos(texto):
    if not texto:
        return []
    texto = re.sub(r"(?i)A[\^r]ox", "/Vox", texto)
    texto = re.sub(r"\bC\s*[,´'’`;.?¿]\s*[sSzZ](y\s)?(?![a-z])", lambda m: "C's y " if m.group(1) else "C's", texto)
    texto = re.split(r"\.-|\s(?:Entra|Sale)n?\s", texto)[0]  # paréntesis sin cerrar: sigue otra frase
    partes = re.split(r"\s*/\s*|\s*[,;]\s*|\.\s+|\s+[yYeE]\s+|^[yY]\s+", texto)
    salida = []
    for p in partes:
        g = _grupo(p)
        if not g or re.fullmatch(r"\d+", g):
            continue
        salida.extend([g] if g in CANONICOS else _erratas(g))
    return salida


RESULTADO = re.compile(r"(?P<no>no\s+(?:se\s+)?aprueba|no\s+(?:queda\s+)?aprobad|queda\s+rechazad|rechazad|se\s+rechaza|"
                       r"desestimad|se\s+desestima|decae|no\s+prospera|no\s+se\s+acepta|no\s+aceptad)|"
                       r"(?P<si>queda\s+aprobad|aprobad|se\s+aprueba|se\s+acepta|aceptad)")
MAYORIA = re.compile(r"mayoria\s+absoluta|(?:tres\s+quintos|dos\s+tercios)")
# «Se aprueba por unanimidad la enmienda…»: la frase de una unanimidad empieza antes de la palabra.
ANTES_UNANIMIDAD = re.compile(r"(?:(?:no\s+)?se\s+(?:aprueba|rechaza|desestima|acepta)n?|(?:queda\s+)?(?:aprobad|rechazad|"
                              r"desestimad|aceptad)[oa]s?|(?:es|son|fue|fueron)\s+\w+)\s+(?:\w+\s+){0,3}?por\s+$", re.I)
SEPARA_RECUENTO = re.compile(r"[\s,;y\-–)]*|\)?\s*\.\s*-\s*|\s+[a-z]\s+")  # «(Vox)).- 2 en contra», «(…) t 13»  # entre partes de un mismo recuento («… (Vox).- 2 en contra»)


def _resultado(ventana):
    """Resultado de la primera frase de resultado de la ventana (texto hasta la siguiente votación).

    No valen las frases de resumen («Se aprueba por tanto la moción…»), que hablan del conjunto y no de
    esta votación."""
    p = _plano(ventana)
    for m in RESULTADO.finditer(p):
        cola, cabeza = p[m.end():m.end() + 14], p[max(0, m.start() - 12):m.start()]
        if "por tanto" in cola or "por tanto" in cabeza:
            continue
        return "rechazada" if m.group("no") else "aprobada"
    return None


def _recorta_ventana(ventana):
    """Corta la ventana antes de la etiqueta de la votación siguiente («.- Dictamen con la enmienda
    aprobada de VOX: 29 votos…»), para que no se lea como resultado de esta."""
    dos_puntos = ventana.rfind(":")
    if dos_puntos < 0:
        return ventana
    corte = max(ventana.rfind(".-", 0, dos_puntos), ventana.rfind(". ", 0, dos_puntos), ventana.rfind("- ", 0, dos_puntos))
    return ventana[:corte] if corte >= 0 else ""


def _votos_item(texto):
    """[dict] de las votaciones de un punto, en orden: recuentos y unanimidades."""
    # Variantes de redacción: «Total 29 votos (PP/PSOE) a favor», «Votos a favor 17 (ZeC, PSOE y CHA)».
    while True:                                                            # «(PSOE(Podemos/ZeC(Concejal…)»
        nuevo = re.sub(r"\(([^()]{1,40})\(", r"(\1/", texto)
        if nuevo == texto:
            break
        texto = nuevo
    texto = re.sub(r"\)\s*/(?=[^()]{1,40}\))", "/", texto)                 # «(ZEC/PSOE/C's)/CHA)»
    texto = re.sub(r"(\d+)\s+(?:votos\s*)?(\([^()]*\))\s*(?:votos\s+)?(a\s+favor|en\s+contra)", r"\1 votos \3 \2", texto)
    texto = re.sub(r"(?i)\b(votos\s+a\s+favor|votos\s+en\s+contra|abstenciones)\s*:?\s+(\d+)\b", r"\2 \1", texto)
    eventos = []
    grupos_rec, ultimo = [], None

    def clase(m):
        t = _plano(m.group("tipo"))
        return "favor" if "favor" in t else "contra" if "contra" in t else "abst"

    for m in RECUENTO.finditer(texto):
        if int(m.group("n")) > CUERPOS[0].escanos:
            continue  # «factura nº 2022 a favor de…»: no es un recuento
        # Un sentido que ya está en el recuento en curso empieza otra votación («… 3 abstenciones. 31 a favor»).
        if ultimo is not None and SEPARA_RECUENTO.fullmatch(texto[ultimo.end():m.start()]) \
                and clase(m) not in {clase(x) for x in grupos_rec[-1]}:
            grupos_rec[-1].append(m)
        else:
            grupos_rec.append([m])
        ultimo = m
    for cluster in grupos_rec:
        d = {"ini": cluster[0].start(), "fin": cluster[-1].end(), "a_favor": None, "en_contra": None,
             "abstenciones": None, "sentidos": {}, "unanimidad": False}
        for m in cluster:
            tipo = _plano(m.group("tipo"))
            clave, sentido = (("a_favor", "si") if "favor" in tipo else ("en_contra", "no") if "contra" in tipo
                              else ("abstenciones", "abstencion"))
            d[clave] = (d[clave] or 0) + int(m.group("n"))
            d["sentidos"].setdefault(sentido, []).extend(_grupos(m.group("g") or m.group("g2")))
        eventos.append(d)
    for m in UNANIMIDAD.finditer(texto):
        # Dentro de un recuento, o justo detrás de uno en el que todos votan a favor, es el mismo voto.
        if any(e["ini"] <= m.start() < e["fin"] or (e["fin"] <= m.start() < e["fin"] + 25 and not e["en_contra"]
                                                      and not e["abstenciones"]) for e in eventos):
            continue
        previa = ANTES_UNANIMIDAD.search(texto[max(0, m.start() - 70):m.start()])
        ini = m.start() - (len(texto[max(0, m.start() - 70):m.start()]) - previa.start()) if previa else m.start()
        d = {"ini": ini, "fin": m.end(), "a_favor": None, "en_contra": None, "abstenciones": None,
             "sentidos": {}, "unanimidad": True, "frase_previa": previa.group(0) if previa else ""}
        fav = re.match(r".{0,120}?voto\s+favorable\s+de\s+(?:los\s+)?(\d+)\s+miembros", texto[m.end():], re.S)
        if fav:
            d.update(a_favor=int(fav.group(1)), en_contra=0, abstenciones=0)
        eventos.append(d)
    eventos.sort(key=lambda e: e["ini"])
    for i, e in enumerate(eventos):
        # El resultado y la mayoría exigida se buscan solo hasta la votación siguiente del punto (o el
        # siguiente «VOTACIÓN»): así el «No se aprueba el punto 5» no se aplica al punto 4, ni el
        # resultado del dictamen a la votación previa de su retirada o de una enmienda.
        fin = eventos[i + 1]["ini"] if i + 1 < len(eventos) else len(texto)
        otra = re.search(r"VOTACI[ÓO]N", texto[e["fin"]:fin])
        if otra:
            fin = e["fin"] + otra.start()
        ventana = _recorta_ventana(texto[e["fin"]:min(fin, e["fin"] + 400)])
        if e["unanimidad"]:
            rechazo = re.search(r"rechaza|desestima|no\s+se\s+aprueba|no\s+se\s+acepta", _plano(e["frase_previa"]))
            e["resultado"] = "rechazada" if rechazo or _resultado(ventana[:40]) == "rechazada" else "aprobada"
        else:
            e["resultado"] = _resultado(ventana)
        plano = _plano(ventana)
        e["mayoria"] = "absoluta" if MAYORIA.search(plano) else None
        e["voto_calidad"] = "voto de calidad" in plano
        antes = texto[max(eventos[i - 1]["fin"] if i else 0, e["ini"] - 90):e["ini"]]
        et = re.findall(r"(\d+)\s*º|(?i:punto)\s+(\d+|(?i:primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|"
                        r"s[eé]ptim[oa]|octav[oa]|noven[oa]|d[eé]cim[oa]|[uú]nic[oa]))|([Ee]nmienda[^.:;]{0,60})|([Uu]rgencia)|"
                        r"(retirada)", antes)
        e["etiqueta"] = None
        if et:
            a, b, c, d_, r = et[-1]
            e["etiqueta"] = (f"Punto {(a or b).lower()}" if (a or b) else c.strip() if c else
                             "Urgencia" if d_ else "Retirada del asunto")
    return eventos


def _contradice(e):
    """El resultado escrito no cuadra con el recuento por mayoría simple (sin mayoría cualificada ni voto de calidad)."""
    if not e.get("resultado") or (e["a_favor"] is None and e["en_contra"] is None) or e.get("mayoria") \
            or e.get("voto_calidad"):
        return False
    favor, contra = e["a_favor"] or 0, e["en_contra"] or 0
    return (favor <= contra) if e["resultado"] == "aprobada" else (favor > contra)


def _voto_grupos(sentidos, d):
    """VotoGrupo por grupo: sentido por el bloque en que se nombra; recuento si el bloque es de un solo grupo."""
    por_grupo = {}
    cuenta = {"si": d["a_favor"], "no": d["en_contra"], "abstencion": d["abstenciones"]}
    for sentido, grupos in sentidos.items():
        unicos = list(dict.fromkeys(grupos))
        for g in unicos:
            por_grupo.setdefault(g, {})[sentido] = cuenta[sentido] if len(unicos) == 1 else None
    salida = []
    for g, s in por_grupo.items():
        sentido = next(iter(s)) if len(s) == 1 else "dividido"
        n = {k: s.get(k) for k in ("si", "no", "abstencion")}
        salida.append(VotoGrupo(g, si=n["si"], no=n["no"], abstencion=n["abstencion"], sentido=sentido))
    return salida


def _tipo_iniciativa(seccion, titulo):
    p, sec = _plano(titulo), _plano(seccion)
    if p.startswith("propuesta de resolucion"):
        return "control"  # debate sobre el estado de la ciudad
    if "mocion" in sec or p.startswith(("presentada por", "mocion")) or "presentada por el grupo" in p[:80]:
        return "mocion"
    if "declaracion institucional" in p[:60]:
        return "otro"
    if "acta de la sesion" in p[:80] or p.startswith("aprobacion del acta"):
        return "organizacion"
    if "ordenanza" in p or "reglamento" in p:
        return "ordenanza"
    if "presupuesto" in p or "modificacion de creditos" in p or "credito" in p:
        return "presupuesto"
    if any(k in p[:80] for k in ("nombramiento", "designacion", "designar", "nombrar", "eleccion")):
        return "organizacion"
    if any(k in p[:60] for k in ("comparecencia", "interpelacion", "pregunta", "informacion del gobierno")):
        return "control"
    return "acuerdo"


def _autor(titulo):
    m = re.search(r"(?:[Pp]resentada|[Ff]ormulada)\s+(?:conjuntamente\s+)?por\s+(?:el|los)\s+[Gg]rupos?\s+[Mm]unicipal(?:es)?\s+"
                  r"(?:de\s+|del\s+)?(.+?)(?:,|\s+en\s+el\s+sentido|\s+relativa|\s+sobre|\s+para|\.)", titulo)
    return m.group(1).strip() if m else None


ETIQUETA = re.compile(r"<(/?)(ol|ul|li|p|h\d|div|table|tr|td)\b([^>]*)>", re.I)
NUM_PUNTO = re.compile(r"^(\d{1,3})(?:\.(\d{1,2}))?\s*(?:\.\s*-?|-|\s)\s*(?=[^\d\s.,%€])")


def _bloques(contenido):
    """[(tipo, texto, número implícito)] en orden: cada <li>, <p> o <h3> con su propio texto (sin el de
    las listas anidadas) y, para los <li> de una <ol>, el número que les da la lista («<ol start="5">»)."""
    bloques, pila, actual, tipo, implicito = [], [], [], None, None

    def cerrar():
        nonlocal actual
        t = _texto(" ".join(actual))
        if t and tipo:
            bloques.append((tipo, t, implicito))
        actual = []

    pos = 0
    for m in ETIQUETA.finditer(contenido):
        actual.append(contenido[pos:m.start()])
        pos = m.end()
        cierre, nombre, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if nombre in ("ol", "ul"):
            cerrar()
            if cierre:
                if pila:
                    pila.pop()
            else:
                ini = re.search(r'start="?(\d+)', attrs)
                pila.append({"tipo": nombre, "n": (int(ini.group(1)) - 1) if ini else 0, "prof": len(pila) + 1})
            tipo, implicito = None, None
        elif nombre in ("li", "p") or re.fullmatch(r"h\d", nombre):
            cerrar()
            if cierre:
                tipo, implicito = None, None
            else:
                tipo = "h3" if nombre.startswith("h") else nombre
                implicito = None
                if nombre == "li" and pila and pila[-1]["tipo"] == "ol":
                    pila[-1]["n"] += 1
                    implicito = (pila[-1]["n"], pila[-1]["prof"])
    actual.append(contenido[pos:])
    cerrar()
    return bloques


def _es_seccion(tipo, t):
    if tipo == "h3":
        return True
    letras = [c for c in t if c.isalpha()]
    return (tipo == "p" and len(t) < 160 and len(letras) > 5 and sum(c.isupper() for c in letras) / len(letras) > 0.9
            and not NUM_PUNTO.match(t))


def _puntos(contenido):
    """[(N, M, sección, texto)] de los puntos del orden del día del extracto.

    Los puntos van en <li> numerados («8. Expediente…», «4 Expediente…», «3.1 …»), en <li> de una
    <ol start="5"> sin número escrito, o en <p> numerados (plenos extraordinarios, debate del estado de
    la ciudad). Un número solo abre punto si sigue la secuencia (N igual o poco mayor que el anterior);
    los bloques sin número se unen al punto en curso."""
    puntos, seccion, ultimo = [], "", 0
    for tipo, t, implicito in _bloques(contenido):
        if _es_seccion(tipo, t):
            seccion = t
            continue
        m = NUM_PUNTO.match(t)
        n = sub = None
        if m:
            n, sub = int(m.group(1)), int(m.group(2) or 0)
            resto = t[m.end():]
            if not (ultimo < n <= ultimo + 4 and (sub == 0 or sub == 1 or not puntos)) and \
                    not (n == ultimo and puntos and sub > puntos[-1][1]):
                n = None  # número fuera de secuencia (importes, «19 votos…», puntos de la moción)
        elif implicito and tipo == "li":
            k, prof = implicito
            if prof == 1 and ultimo < k <= ultimo + 4:
                n, sub, resto = k, 0, t
            elif prof > 1 and puntos:
                n, sub, resto = puntos[-1][0], k, t
        if n is not None:
            puntos.append([n, sub, seccion, resto.strip()])
            ultimo = n
        elif puntos:
            puntos[-1][3] += " " + t
    return puntos


def _votaciones_extracto(s, contenido):
    h2 = re.search(r"(?s)<h2[^>]*>(.*?)</h2>", contenido)
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", _texto(h2.group(1))) if h2 else None
    fecha = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else s["fecha"]
    titulo_sesion = _texto(h2.group(1)) if h2 else s["nombre"]
    usados = set()
    for n, sub, seccion, texto in _puntos(contenido):
        exp = EXPEDIENTE.search(texto)
        expediente = next((g for g in exp.groups() if g), None).replace(" ", "") if exp else None
        cuerpo = PREFIJO_EXP.sub("", texto)
        cortes = [m.start() for m in [CORTE_TITULO.search(cuerpo)] if m]
        par = re.search(r"\((?:P-)?\d[\d.]*(?:/\d{2,4})?\.?\)", cuerpo)
        if par:
            cortes.append(par.end())
        titulo = cuerpo[:min(cortes)] if cortes else cuerpo[:400]
        titulo = titulo.strip(" .-")[:700]
        if not titulo:
            continue
        eventos = [e for e in _votos_item(texto) if e["unanimidad"] or e["resultado"] or e["a_favor"] is not None]
        tipo = _tipo_iniciativa(seccion, titulo)
        for e in eventos:
            if sum(e[x] or 0 for x in ("a_favor", "en_contra", "abstenciones")) > CUERPOS[0].escanos:
                e.update(a_favor=None, en_contra=None, abstenciones=None, sentidos={}, aviso=True)
        eventos = [e for e in eventos if e["resultado"] or e["a_favor"] is not None or e["unanimidad"]]
        for k, e in enumerate(eventos):
            numero = n * 10000 + sub * 100 + k
            if numero in usados or k >= 100:
                continue
            usados.add(numero)
            sin_recuento = e["a_favor"] is None and e["en_contra"] is None and e["abstenciones"] is None
            subtitulo = e["etiqueta"] or (f"Votación {k + 1} de {len(eventos)}" if len(eventos) > 1 else None)
            yield Votacion(
                CODIGO, fecha, titulo, sesion=s["sesion"], numero=numero, subtitulo=subtitulo,
                expediente=expediente, tipo_iniciativa=tipo, tipo_votacion={"mocion": "mocion", "control": "control"}.get(tipo),
                autor=_autor(titulo) if tipo in ("mocion", "control") else None, a_favor=e["a_favor"], en_contra=e["en_contra"],
                abstenciones=e["abstenciones"], asentimiento=sin_recuento and e["unanimidad"],
                resultado=e["resultado"], mayoria=e["mayoria"], grupos=_voto_grupos(e["sentidos"], e),
                url=s["acuerdo"], fuente="html-reglas",
                extra={"punto": f"{n}.{sub}" if sub else str(n), "seccion": seccion or None,
                       "sesion_nombre": titulo_sesion, **({"unanimidad": True} if e["unanimidad"] else {}),
                       **({"aviso": "el recuento leído supera los 31 concejales: sin totales"} if e.get("aviso") else {}),
                       **({"voto_calidad": True} if e.get("voto_calidad") else {}),
                       **({"aviso_resultado": "el extracto da un resultado que contradice su propio recuento"}
                          if _contradice(e) else {})})


# ---------------------------------------------------------------------------- conector

def descargar(ctx):
    desde = ctx.desde(CODIGO)
    vistos, emitidas, n = set(), {}, 0
    sesiones = [s for s in _sesiones(ctx) if s["fecha"]]
    for s in sorted(sesiones, key=lambda s: (s["fecha"], s["sesion"]), reverse=True):
        if s["fecha"] < INICIO or (desde and s["fecha"] < desde):
            break
        if s["sesion"] in vistos:
            continue  # dos sesiones del mismo día con un solo extracto
        vistos.add(s["sesion"])
        try:
            contenido = _extracto(ctx, s)
        except (urllib.error.HTTPError, RuntimeError) as e:
            ctx.log(f"  Zaragoza: no se pudo leer el extracto {s['acuerdo']} ({s['fecha']}): {e}")
            continue
        # Las sesiones de varios días (debate del estado de la ciudad) publican el mismo extracto en cada una.
        huella = ctx.clave(re.sub(r"(?s)FECHA DE PUBLICACI.*", "", _texto(contenido)))
        if huella in vistos:
            continue
        vistos.add(huella)
        for v in _votaciones_extracto(s, contenido):
            if v.fecha < INICIO:
                continue
            # La misma votación en el extracto de otra fila de la misma sesión (sesiones de varios días o
            # filas repetidas): se da una vez, la de la fila más reciente.
            clave = (v.titulo[:300], v.subtitulo, v.a_favor, v.en_contra, v.abstenciones, v.resultado)
            previa = emitidas.get(clave)
            if previa and previa[1] != v.sesion and \
                    abs(date.fromisoformat(previa[0]).toordinal() - date.fromisoformat(v.fecha).toordinal()) <= 3:
                continue
            emitidas.setdefault(clave, (v.fecha, v.sesion))
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
