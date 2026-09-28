"""Ayuntamiento de Gijón/Xixón: votaciones del Pleno (proposiciones en JSON y actas con reglas).

Fuentes (datos abiertos municipales, opendata.gijon.es, los mismos que usa proposiciones.gijon.es):
- Proposiciones de Pleno (descargar.php?id=546&tipo=JSON&comprimiretiquetas&sinvacios): cada
  proposición de los grupos con el pleno (p3 = idpleno, p4 = nombre), título (p5), resultado (p6:
  «Unanimidad», «Mayoría Absoluta», «Mayoría Simple», «Rechazada»), grupos proponentes (pgs), y dos
  bloques de voto: el nominal de cada concejal (pvs[0]: id, nombre, «A favor», «En contra»,
  «Abstención», «Ausente») y el de cada grupo (pvs[1]: id del grupo, siglas y sentido). Va del
  01/08/2015 al 08/10/2025 (962 proposiciones): la fuente dejó de actualizarse ahí.
- Autoridades (id=543), grupos (id=544) y órganos (id=542): nombre del grupo de cada concejal en
  cada fecha (los que pasan a no adscritos cambian), para poner el grupo en el voto nominal.
- Plenos (id=545): cada sesión con su fecha, tipo y documentos (orden del día, «Relación y
  acuerdos», acta en PDF, vídeo).
- Actas desde octubre de 2020: cada punto del orden del día («12.- PROPOSICIÓN PRESENTADA POR …», en
  mayúsculas) acaba con una frase muy regular que se lee con reglas: «el Ayuntamiento Pleno con
  doce votos a favor (9 del PSOE, 2 de IU-MP-IAS y 1 de Podemos Xixón) y quince votos en contra
  (8 de FORO, 5 del PP, 1 de VOX y 1 del Concejal no adscrito) no aprueba la proposición». De ahí
  salen los dictámenes, ordenanzas, presupuestos… y las proposiciones posteriores al 08/10/2025,
  con recuento por grupo («pdf-reglas»). Las proposiciones de los plenos que ya están en el JSON
  se toman del JSON (más completo: voto nominal).
- Actas de 2015 a septiembre de 2020: son transcripciones literales («Votos a favor: Foro (8),
  PP (3)…») con formatos que cambian; van como documentos para el extractor LLM (`documentos`),
  igual que las posteriores en las que las reglas no leen ninguna votación.

Cobertura: mandatos X (desde el 13/06/2015), XI y XII.
Limitaciones: los puntos de las actas de octubre de 2020 en adelante cuya votación no sigue la frase tipo
(p. ej. «por unanimidad» sin recuento sí se lee; votaciones separadas por apartados sin «el
Ayuntamiento Pleno con…» no) se pierden. Las proposiciones del JSON con el bloque nominal
incoherente (dos votaciones mezcladas, o 28 votos en febrero y marzo de 2019 porque figura también un
concejal ya sustituido) salen sin voto nominal ni totales, solo con el voto por grupo publicado. Los
grupos se nombran con el nombre oficial del conjunto de grupos (id=544) también en las actas.
sesion = idpleno de la fuente; numero = 10000 + orden para las proposiciones del JSON y
N*100 + M*10 + k para el punto N (subpunto M, k-ésima votación del punto) de las actas.
"""

import json
import re
import unicodedata
import urllib.parse

from ... import territorio
from ..modelo import Documento, Votacion, VotoGrupo, VotoNominal

CODIGO = "ayto-gijon"
OPENDATA = "https://opendata.gijon.es/descargar.php?id={}&tipo=JSON"
URL_PROPOSICIONES = OPENDATA.format(546) + "&comprimiretiquetas&sinvacios"
WEB = "https://proposiciones.gijon.es"
INICIO = "2015-06-13"
FECHA_REGLAS = "2020-10-01"  # desde aquí las actas usan la frase tipo; antes, documentos para LLM

CUERPOS = [
    territorio.Cuerpo(CODIGO, territorio.num_municipio("33024"), "Ayuntamiento de Gijón/Xixón", "Gijón",
                      "municipal", "AS", 27, {n: territorio.MANDATOS_LOCALES[n] for n in (10, 11, 12)}, web=WEB),
]

NOTAS = ("Proposiciones de los grupos (01/08/2015-08/10/2025) del JSON municipal con voto nominal, voto por "
         "grupo, resultado y proponentes. Desde octubre de 2020, el resto de puntos votados (y las proposiciones "
         "posteriores a octubre de 2025) salen de las actas con reglas, con recuento por grupo. Actas de "
         "2015 a septiembre de 2020 (transcripciones literales) y las que las reglas no leen, como "
         "documentos para el extractor LLM. sesion = idpleno.")

SENTIDO_JSON = {"a favor": "si", "en contra": "no", "abstencion": "abstencion", "ausente": "no_vota"}
MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
NUMEROS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
           "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
           "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
           "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
           "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "ninguno": 0, "ninguna": 0, "cero": 0}
# Siglas de las actas -> id del grupo en el conjunto de grupos (id=544). «IU» y «Podemos» dependen del
# mandato: Izquierda Unida (17) hasta 2023 e IU-MP-IAS (74) después; Xixón Sí Puede (20) en 2015-2019,
# Podemos Equo Xixón (30) en 2019-2023 y Podemos Xixón (73) desde 2023.
ALIAS_GRUPO = {"psoe": 18, "socialista": 18, "foro": 16, "foro asturias": 16, "pp": 21, "partido popular": 21,
               "popular": 21, "vox": 29, "iu mp ias": 74, "xixon iu mas pais ias": 74, "c's": 19,
               "ciudadanos": 19, "xsp": 20, "xixon si puede": 20, "podemos equo xixon": 30, "pex": 30,
               "podemos xixon": 73, "concejal no adscrito": 56, "concejala no adscrita": 56,
               "concejales no adscritos": 56, "no adscrito": 56, "no adscritos": 56, "cna": 56,
               "ciudadano": 19, "del concejal no adscrito": 56, "de la concejala no adscrita": 56}
EQUIVALENTES = ({17, 74}, {20, 30, 73})
MANDATO_2019, MANDATO_2023 = "2019-06-15", "2023-06-17"


def _alias(clave, fecha):
    if clave in ("iu", "izquierda unida"):
        return 17 if fecha < MANDATO_2023 else 74
    if clave == "podemos":
        return 20 if fecha < MANDATO_2019 else 30 if fecha < MANDATO_2023 else 73
    return ALIAS_GRUPO.get(clave)


def _clave(s):
    return re.sub(r"[\s-]+", " ", _plano((s or "").replace("’", "'"))).strip(" .")


def _plano(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _lista(v):
    if v is None or v == {} or v == "":
        return []
    return v if isinstance(v, list) else [v]


def _url(u):
    """Las rutas de la fuente llevan espacios y paréntesis sin codificar."""
    return urllib.parse.quote(u.strip(), safe=":/?&=%()#+,;@") if u else None


def _tildes(s):
    """Une las tildes partidas por el PDF: «DECLARACIÓ N» -> «DECLARACIÓN»."""
    return re.sub(r"([ÁÉÍÓÚáéíóú]) (N|NES|S|NS|n|nes|s|ns)\b", r"\1\2", s)


def _json(ctx, url, cache):
    return json.loads(ctx.fetch(url, cache=cache, caduca_dias=1).decode("utf-8-sig"))


# ---------------------------------------------------------------------------- catálogos

class Catalogo:
    """Plenos, grupos y el grupo de cada concejal en cada fecha."""

    def __init__(self, ctx):
        grupos = _json(ctx, OPENDATA.format(544), "ayto-gijon/grupos.json")["grupos"]["grupo"]
        self.grupos = {int(g["id"]): g["nombregrupo"].strip() for g in grupos}
        self.por_nombre = {_clave(g["nombregrupo"]): int(g["id"]) for g in grupos}
        self.por_nombre.update({_clave(g["siglasgrupo"]): int(g["id"]) for g in grupos})
        organos = _json(ctx, OPENDATA.format(542), "ayto-gijon/organos.json")["organos"]["organo"]
        partidos = {_plano(o["nombreorgano"]): int(o["idorgano"]) for o in organos
                    if o.get("nombretipoorgano") == "Partido"}
        self.concejales = {}
        for a in _lista(_json(ctx, OPENDATA.format(543), "ayto-gijon/autoridades.json").get("autoridad")):
            periodos = []
            for o in _lista((a.get("organos") or {}).get("organo")):
                if o.get("nombretipoorgano") != "Partido":
                    continue
                gid = partidos.get(_plano(o["nombreorgano"])) or self.por_nombre.get(_clave(o["nombreorgano"]))
                ini = o.get("fechainicioorgano") if isinstance(o.get("fechainicioorgano"), str) else "0000"
                fin = o.get("fechafinorgano") if isinstance(o.get("fechafinorgano"), str) else "9999"
                if gid is not None:
                    periodos.append((ini, fin, gid))
            actual = a.get("nombrepartido") if isinstance(a.get("nombrepartido"), str) else ""
            self.concejales[str(a["idautoridad"])] = (sorted(periodos), self.por_nombre.get(_clave(actual)), actual)
        self.plenos = {}
        for p in _lista(_json(ctx, OPENDATA.format(545), "ayto-gijon/plenos.json").get("pleno")):
            docs = {}
            for r in _lista((p.get("agrupacion_recursos") or {}).get("recursos")):
                docs.setdefault(r.get("nombretiporecursopleno"), r.get("recursopleno"))
            self.plenos[int(p["idpleno"])] = {"id": int(p["idpleno"]), "nombre": p.get("nombrepleno") or "",
                                              "tipo": p.get("nombretiposesionpleno") or "",
                                              "fecha": _fecha_pleno(p.get("nombrepleno"), p.get("fechapleno")),
                                              "acta": _url(docs.get("Acta")),
                                              "relacion": _url(docs.get("Relación y acuerdos"))}

    def grupo_concejal(self, id_autoridad, fecha, ids_votacion=()):
        """Grupo de un concejal en una fecha; si la votación publica los grupos, el equivalente de entre ellos."""
        periodos, actual, nombre = self.concejales.get(str(id_autoridad), ([], None, ""))
        gid = next((g for ini, fin, g in periodos if ini <= fecha <= fin), actual)
        if gid is None:
            return nombre or None
        if ids_votacion and gid not in ids_votacion:
            for eq in EQUIVALENTES:
                if gid in eq and eq & set(ids_votacion):
                    gid = sorted(eq & set(ids_votacion))[0]
        return self.grupos.get(gid, nombre or None)

    def grupo_acta(self, siglas, fecha):
        """Nombre oficial del grupo para las siglas de un acta («9 del PSOE» -> Partido Socialista…)."""
        clave = _clave(siglas)
        gid = _alias(clave, fecha) or self.por_nombre.get(clave)
        return self.grupos.get(gid, siglas.strip()) if gid is not None else siglas.strip()


def _fecha_pleno(nombre, fecha):
    m = re.search(r"(\d{1,2}) de ([a-z]+) de (\d{4})", _plano(nombre))
    if m and m.group(2) in MESES:
        return f"{m.group(3)}-{MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return (fecha or "")[:10]


# ---------------------------------------------------------------------------- proposiciones (JSON)

def _resultado_json(r):
    p = _plano(r)
    if p.startswith("rechazad"):
        return "rechazada", None
    if "absoluta" in p:
        return "aprobada", "absoluta"
    if "simple" in p:
        return "aprobada", "simple"
    if "unanimidad" in p or p.startswith("aprobad"):
        return "aprobada", None
    return None, None


def _votacion_json(cat, x, pleno, orden):
    fecha = pleno["fecha"] if pleno else _fecha_pleno(x.get("p4"), x.get("p12"))
    resultado, mayoria = _resultado_json(x.get("p6"))
    bloques = _lista(x.get("pvs"))
    nominal_bruto = _lista((bloques[0] or {}).get("pv")) if bloques else []
    grupos_bruto = _lista((bloques[1] or {}).get("pv")) if len(bloques) > 1 else []
    # Voto por grupo publicado (sentido); el recuento por grupo sale del nominal si se puede.
    sentido_grupo, ids_grupos = {}, set()
    for g in grupos_bruto:
        try:
            gid = int(g.get("pv1"))
        except (TypeError, ValueError):
            continue
        ids_grupos.add(gid)
        nombre = cat.grupos.get(gid) or (g.get("pv2") or "").strip()
        sentido_grupo[nombre] = SENTIDO_JSON.get(_plano(g.get("pv3")))
    ids = [str(v.get("pv1")) for v in nominal_bruto]
    nominal, cuenta = [], {}
    if nominal_bruto and len(set(ids)) == len(ids):
        for v in nominal_bruto:
            sentido = SENTIDO_JSON.get(_plano(v.get("pv4") or v.get("pv3")))
            if not sentido:
                continue
            grupo = cat.grupo_concejal(v.get("pv1"), fecha, ids_grupos) or "Sin grupo"
            nominal.append(VotoNominal((v.get("pv2") or "").strip(), grupo, sentido))
            cuenta.setdefault(grupo, {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0})[sentido] += 1
    motivo = "el bloque nominal repite concejales (varias votaciones mezcladas)" if nominal_bruto and not nominal else None
    if sum(1 for x in nominal if x.sentido != "no_vota") > CUERPOS[0].escanos:
        motivo = f"el bloque nominal trae {sum(1 for x in nominal if x.sentido != 'no_vota')} votos para 27 concejales"
        nominal, cuenta = [], {}
    grupos = []
    for nombre in dict.fromkeys(list(sentido_grupo) + list(cuenta)):
        c = cuenta.get(nombre)
        s = sentido_grupo.get(nombre)
        if c:
            votan = [k for k in ("si", "no", "abstencion") if c[k]]
            sentido = votan[0] if len(votan) == 1 else ("dividido" if votan else None)
            grupos.append(VotoGrupo(nombre, si=c["si"], no=c["no"], abstencion=c["abstencion"],
                                    no_vota=c["no_vota"], sentido=sentido))
        elif s in ("si", "no", "abstencion"):
            grupos.append(VotoGrupo(nombre, sentido=s))
    tot = {k: sum(1 for n in nominal if n.sentido == k) for k in ("si", "no", "abstencion", "no_vota")}
    autores = [(g.get("pg2") or "").strip() for g in _lista((x.get("pgs") or {}).get("pg"))]
    docs = [d.get("pd1") for d in _lista((x.get("pdes") or {}).get("pd")) if d.get("pd1")]
    extra = {"id": x.get("p1"), "concejalia": x.get("p8"), "resultado_fuente": x.get("p6"),
             "pleno": x.get("p4"), "video": x.get("p9")}
    if docs:
        extra["documentos"] = [_url(WEB + "/" + d.lstrip("/")) for d in docs]
    if motivo:
        extra["nominal_descartado"] = motivo
    return Votacion(
        CODIGO, fecha, (x.get("p5") or "").strip(), sesion=int(x["p3"]), numero=10000 + orden,
        expediente=str(x["p2"]).strip() if x.get("p2") else None, tipo_iniciativa="mocion", tipo_votacion="mocion",
        autor=", ".join(a for a in autores if a) or None,
        a_favor=tot["si"] if nominal else None, en_contra=tot["no"] if nominal else None,
        abstenciones=tot["abstencion"] if nominal else None, no_votan=tot["no_vota"] if nominal else None,
        presentes=(len(nominal) - tot["no_vota"]) if nominal else None,
        resultado=resultado, mayoria=mayoria, grupos=grupos, nominal=nominal,
        url=f"{WEB}/?detalle={x.get('p1')}", fuente="json", extra=extra)


def _proposiciones(ctx):
    d = _json(ctx, URL_PROPOSICIONES, "ayto-gijon/proposiciones.json")
    por_pleno = {}
    for x in _lista(d.get("p")):
        if x.get("p3"):
            por_pleno.setdefault(int(x["p3"]), []).append(x)
    for lista in por_pleno.values():
        lista.sort(key=lambda x: int(x.get("p1") or 0))
    return por_pleno


# ---------------------------------------------------------------------------- actas (reglas)

def _texto_pdf(ctx, raw):
    """pdftotext -raw (sin él, las tildes salen partidas: «aprobació n»), el mismo que el resto (el de poppler,
    que es el de GitHub Actions); si no hay, pypdf."""
    return ctx.pdf_texto(raw, raw=True)


def _mayusculas(s):
    letras = [c for c in s[:80] if c.isalpha()]
    return len(letras) >= 6 and sum(c.isupper() for c in letras) / len(letras) >= 0.85


# Cabecera y pie de página que pdftotext mete en medio del texto (a veces en mitad de una frase).
RUIDO = re.compile(r"^\s*(?:Ayuntamiento(?:\s+de\s+Gij[oó]n)?|de\s+Gij[oó]n|\d{2}/\d{2}/\d{4}|PA\d+|"
                   r"Ayuntamiento de Gij[oó]n/Xix[oó]n\s+P[aá]g\.?\s*\d+/\d+|\d{3} \d{2} \d{2} \d{2}.*gijon\.es)\s*$")
CABECERA = re.compile(r"^\s*(?:N[º°o]\.?\s*)?(\d{1,2})(?:\.(\d{1,2}))?\s*\.?-\s*(\S.*)$")


def _puntos(texto):
    """[(N, M, título, cuerpo)] de los puntos del orden del día de un acta."""
    lineas = texto.splitlines()
    puntos, actual, ultimo = [], None, 0
    i = 0
    while i < len(lineas):
        m = CABECERA.match(lineas[i])
        if m and _mayusculas(m.group(3)):
            n, sub = int(m.group(1)), int(m.group(2) or 0)
            if (sub == 0 and n == ultimo + 1) or (sub and n == ultimo):
                titulo = [m.group(3).strip()]
                j = i + 1
                while j < len(lineas) and j <= i + 4 and _mayusculas(lineas[j]) and not CABECERA.match(lineas[j]) \
                        and not titulo[-1].rstrip().endswith("."):
                    titulo.append(lineas[j].strip())
                    j += 1
                actual = [n, sub, " ".join(titulo), []]
                puntos.append(actual)
                ultimo = n
                i = j
                continue
        if actual is not None and not RUIDO.match(lineas[i]):
            actual[3].append(lineas[i])
        i += 1
    return [(n, sub, _tildes(re.sub(r"\s+", " ", t)).strip(" ."), " ".join(c)) for n, sub, t, c in puntos]


def _numero(s):
    s = _plano(s)
    return int(s) if s.isdigit() else NUMEROS.get(s)


_ACLARACION = r"(?:[-–][^()\-–]{0,80}[-–]\s*)?"  # «una abstención -de conformidad con el art. 65.3 del ROP- (1 de VOX)»
_BLOQUES = (r"(?:[\wáéíóú]+\s+(?:votos?\s+a\s+favor|votos?\s+en\s+contra|abstenci[oó]n(?:es)?)\s*" + _ACLARACION +
            r"(?:\([^)]*\))?\s*(?:,|\by\b|\be\b)?\s*)+")
FRASE = re.compile(r"(?:Ayuntamiento\s+Pleno,?\s+por\s+(?P<unan>unanimidad)\s*,?\s+|\bcon\s+(?P<votos>" + _BLOQUES + r"))"
                   r".{0,60}?(?P<verbo>no\s+aprueba|acuerda|aprueba|rechaza|desestima|estima|queda)", re.I | re.S)
BLOQUE = re.compile(r"(?P<n>[\wáéíóú]+)\s+(?P<tipo>votos?\s+a\s+favor|votos?\s+en\s+contra|abstenci[oó]n(?:es)?)"
                    r"\s*" + _ACLARACION + r"(?:\((?P<grupos>[^)]*)\))?", re.I)
PARTE = re.compile(r"^(?P<n>\d+)\s+(?:(?:del|de\s+la|de\s+los|de\s+las|de)\s+)?(?P<g>.+)$", re.I)


def _limpia_grupo(g):
    """«FORO -doña Carmen Moriyón-» -> «FORO»; «Conce- jal» -> «Concejal»; ruido de página fuera."""
    g = re.sub(r"\bPA\d+\b|\d{2}/\d{2}/\d{4}|Ayuntamiento\s+de\s+Gij[oó]n", " ", g)
    g = re.sub(r"(\w)-\s+([a-záéíóúñ])", r"\1\2", g)
    g = re.sub(r"(\w)-\s+([A-ZÁÉÍÓÚÑ])", r"\1-\2", g)
    g = re.split(r"\s[-–]|[-–]\s", g)[0]
    return re.sub(r"\s+", " ", g).strip(" ,.;:")


def _partes(cat, s, fecha, total=None):
    """«9 del PSOE, 8 de FORO y 1 del Concejal no adscrito» -> [(grupo, 9), …]. Un grupo sin número
    («(de VOX)») cuenta todo el bloque."""
    salida = []
    trozos = [t.strip() for t in re.split(r",\s*|\s+[yYeE]\s+|\s+(?=\d+\s+(?:del?|de\s+la|de\s+los)\s)", s or "")
              if t.strip()]
    for trozo in trozos:
        m = PARTE.match(trozo)
        if m:
            salida.append((cat.grupo_acta(_limpia_grupo(m.group("g")), fecha), int(m.group("n"))))
    if not salida and len(trozos) == 1 and total and not re.search(r"\d", trozos[0]):
        g = re.sub(r"(?i)^(?:del?|de\s+la|de\s+los)\s+", "", trozos[0])
        salida.append((cat.grupo_acta(_limpia_grupo(g), fecha), total))
    return salida


def _votaciones_frase(cat, cuerpo, fecha):
    """[dict] con totales, grupos y resultado de cada frase «el Ayuntamiento Pleno con …» del punto."""
    salida = []
    for m in FRASE.finditer(cuerpo):
        verbo = _plano(m.group("verbo"))
        if verbo == "queda":
            continue
        cola = _plano(cuerpo[m.end():m.end() + 60])
        resultado = "rechazada" if verbo in ("no aprueba", "rechaza", "desestima") else "aprobada"
        d = {"a_favor": None, "en_contra": None, "abstenciones": None, "grupos": {}, "resultado": resultado,
             "mayoria": "absoluta" if "mayoria absoluta" in cola else None,
             "unanimidad": bool(m.group("unan")) or "unanimidad" in cola,
             "urgencia": cola.startswith("la urgencia") or cola.startswith("urgencia"),
             "frase": re.sub(r"\s+", " ", cuerpo[m.start():m.end() + 40]).strip(), "aviso": None}
        if m.group("votos"):
            vistos = set()
            for b in BLOQUE.finditer(m.group("votos")):
                tipo = _plano(b.group("tipo"))
                clave, sentido = (("a_favor", "si") if "favor" in tipo else ("en_contra", "no") if "contra" in tipo
                                  else ("abstenciones", "abstencion"))
                if clave in vistos:
                    d["aviso"] = "incoherente"  # «doce votos en contra (…) y catorce votos en contra (…)»
                vistos.add(clave)
                n = _numero(b.group("n"))
                partes = _partes(cat, b.group("grupos"), fecha, n)
                d[clave] = n if n is not None else (sum(k for _, k in partes) if partes else None)
                if partes and n is not None and sum(k for _, k in partes) != n and not d["aviso"]:
                    d["aviso"] = "descuadre"
                for g, k in partes:
                    d["grupos"].setdefault(g, {"si": 0, "no": 0, "abstencion": 0})[sentido] += k
            if d["a_favor"] is None and d["en_contra"] is None and d["abstenciones"] is None:
                continue
            if d["aviso"] == "incoherente":
                d.update(a_favor=None, en_contra=None, abstenciones=None, grupos={})
        salida.append(d)
    return salida


def _tipo_punto(titulo):
    p = _plano(titulo)
    if p.startswith(("proposicion", "mocion")):
        return "mocion"
    if "ordenanza" in p or "reglamento" in p:
        return "ordenanza"
    if "presupuesto" in p or "credito" in p:
        return "presupuesto"
    if p.startswith(("dacion de cuenta", "informe", "comparecencia")):
        return "control"
    if p.startswith("declaracion"):
        return "otro"
    if any(k in p for k in ("nombramiento", "designacion", "eleccion", "composicion", "concejal")):
        return "organizacion"
    return "acuerdo"


def _autor_punto(titulo):
    """«… PRESENTADA POR EL GRUPO MUNICIPAL IU-MP-IAS SOBRE …» -> «Grupo Municipal IU-MP-IAS»."""
    m = re.search(r"PRESENTADA\s+(?:CONJUNTAMENTE\s+)?POR\s+(?:EL|LOS)\s+(GRUPOS?\s+MUNICIPAL(?:ES)?\s+.+?)"
                  r"\s+(?:SOBRE|PARA|POR|RELATIV|EN\s+RELACI|DE\s+|CON\s+|RESPECTO|ACERCA|INSTANDO|EN\s+)", titulo)
    if not m:
        return None
    palabras = []
    for w in m.group(1).split():
        if w in ("Y", "E", "DE", "DEL", "LA", "LOS"):
            palabras.append(w.lower())
        elif len(w) <= 4 or "-" in w:
            palabras.append(w)  # siglas: PSOE, FORO, VOX, IU-MP-IAS
        else:
            palabras.append(w.capitalize())
    return " ".join(palabras)


def _votaciones_acta(ctx, cat, pleno, con_json):
    raw = ctx.fetch(pleno["acta"], cache=f"{CODIGO}/actas/{ctx.clave(pleno['acta'])}.pdf")
    texto = _texto_pdf(ctx, raw)
    n_vot = 0
    for n, sub, titulo, cuerpo in _puntos(texto):
        plano = _plano(titulo)
        es_proposicion = plano.startswith("proposicion")
        if es_proposicion and con_json:
            continue  # la da el JSON, con voto nominal
        votos = _votaciones_frase(cat, cuerpo, pleno["fecha"])
        if votos and plano.startswith(("ruegos", "preguntas")):
            # Suele ser la urgencia de una moción presentada en ese turno, sin título propio: no se da.
            ctx.log(f"  Gijón: {len(votos)} votación(es) sin asunto claro en «{titulo}» del pleno {pleno['id']}")
            continue
        for k, d in enumerate(votos):
            grupos = []
            for g, c in d["grupos"].items():
                votan = [s for s in ("si", "no", "abstencion") if c[s]]
                grupos.append(VotoGrupo(g, si=c["si"], no=c["no"], abstencion=c["abstencion"],
                                        sentido=votan[0] if len(votan) == 1 else "dividido"))
            sin_recuento = d["a_favor"] is None and d["en_contra"] is None and d["abstenciones"] is None
            subtitulo = "Urgencia" if d["urgencia"] else None
            if len(votos) > 1:
                subtitulo = f"Votación {k + 1} de {len(votos)}" + (" (urgencia)" if d["urgencia"] else "")
            extra = {"punto": f"{n}.{sub}" if sub else str(n), "pleno": pleno["nombre"]}
            if d["unanimidad"]:
                extra["unanimidad"] = True
            if d["aviso"]:
                extra["aviso"] = ("la frase del acta repite un sentido de voto: sin totales ni grupos"
                                  if d["aviso"] == "incoherente" else "los votos por grupo no suman el total del acta")
                extra["frase"] = d["frase"][:600]
            yield Votacion(
                CODIGO, pleno["fecha"], titulo, sesion=pleno["id"], numero=n * 100 + sub * 10 + k,
                subtitulo=subtitulo, tipo_iniciativa=_tipo_punto(titulo),
                tipo_votacion="mocion" if es_proposicion else None, autor=_autor_punto(titulo),
                a_favor=d["a_favor"], en_contra=d["en_contra"], abstenciones=d["abstenciones"],
                asentimiento=sin_recuento and d["unanimidad"], resultado=d["resultado"], mayoria=d["mayoria"],
                grupos=grupos, url=pleno["acta"], fuente="pdf-reglas", extra=extra)
            n_vot += 1
    if not n_vot:
        ctx.log(f"  Gijón: el acta del pleno {pleno['id']} ({pleno['fecha']}) no tiene votaciones legibles con reglas")


# ---------------------------------------------------------------------------- conector

def _plenos_ordenados(cat, desde):
    for p in sorted(cat.plenos.values(), key=lambda p: (p["fecha"], p["id"]), reverse=True):
        if not p["fecha"] or p["fecha"] < INICIO:
            break
        if desde and p["fecha"] < desde:
            break
        yield p


def descargar(ctx):
    desde = ctx.desde(CODIGO)
    cat = Catalogo(ctx)
    props = _proposiciones(ctx)
    n = 0
    vistos = set()
    for p in _plenos_ordenados(cat, desde):
        vistos.add(p["id"])
        lista = props.get(p["id"], [])
        salida = [_votacion_json(cat, x, p, i) for i, x in enumerate(lista, 1)]
        if p["fecha"] >= FECHA_REGLAS and p["acta"]:
            salida.extend(_votaciones_acta(ctx, cat, p, con_json=bool(lista)))
        for v in salida:
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    # Proposiciones de plenos que no están en la lista de plenos (no debería haber).
    for pid, lista in sorted(props.items(), reverse=True):
        if pid in vistos:
            continue
        for i, x in enumerate(lista, 1):
            v = _votacion_json(cat, x, None, i)
            if v.fecha < INICIO or (desde and v.fecha < desde):
                continue
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


def _sin_reglas(ctx, cat, pleno):
    """True si el acta (de FECHA_REGLAS en adelante) habla de votos pero las reglas no leen ninguno."""
    texto = _texto_pdf(ctx, ctx.fetch(pleno["acta"], cache=f"{CODIGO}/actas/{ctx.clave(pleno['acta'])}.pdf"))
    if any(_votaciones_frase(cat, c, pleno["fecha"]) for _, _, _, c in _puntos(texto)):
        return False
    return bool(re.search(r"(?i)votos a favor|unanimidad", texto))


def documentos(ctx):
    """Actas para el extractor LLM: las de 2015 a septiembre de 2020 (transcripciones literales, sin
    frase tipo) y las posteriores en las que las reglas no encuentran ninguna votación."""
    desde = ctx.desde(CODIGO)
    cat = Catalogo(ctx)
    props = _proposiciones(ctx)
    n = 0
    for p in _plenos_ordenados(cat, desde):
        if not p["acta"] or (p["fecha"] >= FECHA_REGLAS and not _sin_reglas(ctx, cat, p)):
            continue
        cubiertas = props.get(p["id"], [])
        yield Documento(CODIGO, p["fecha"], p["acta"], sesion=p["id"], formato="pdf", idioma="es",
                        titulo=f"Acta del Pleno del Ayuntamiento de Gijón/Xixón: {p['nombre']}",
                        legislatura=CUERPOS[0].legislatura_de(p["fecha"]),
                        extra={"tipo_sesion": p["tipo"],
                               "proposiciones_json": [x.get("p5") for x in cubiertas],
                               "nota": "las proposiciones listadas ya vienen del JSON con voto nominal"})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/actas/{ctx.clave(doc.url)}.pdf")
    return _texto_pdf(ctx, raw)
