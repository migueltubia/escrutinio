"""Catálogo territorial: instituciones con votaciones y árbol de ámbitos para filtrar.

Cada institución («cuerpo») tiene un número estable y sus legislaturas (o mandatos) se guardan en
la tabla legislatura con id = num * 100 + número de legislatura. El Congreso es el num 0, así que
sus ids (10 a 15) son los de siempre y todo lo que ya filtraba por legislatura sigue valiendo.

Números reservados, para que no choquen nunca:
- 0: Congreso (1: Senado, cuando se añada, usaría 1000 + comunidad para no pisar a los parlamentos).
- 1 a 19: parlamentos autonómicos, con el código INE de la comunidad (01 Andalucía … 19 Melilla).
- 20 a 22: Juntas Generales de Álava, Bizkaia y Gipuzkoa.
- 23 a 29: cabildos canarios. 30 a 33: consells insulars de Baleares.
- 200 + código INE de provincia: diputaciones provinciales.
- Código INE del municipio (5 cifras, de 1001 en adelante): ayuntamientos.

Las legislaturas de cada institución las declara su conector (escrutinio/territorial/fuentes).
"""

from dataclasses import dataclass, field

NIVELES = {
    "nacional": "Nacional",
    "autonomico": "Parlamentos autonómicos",
    "provincial": "Provincial e insular",
    "municipal": "Ayuntamientos",
}

# (código ISO 3166-2 sin «ES-», nombre, código INE de la comunidad)
CCAA = [
    ("AN", "Andalucía", 1), ("AR", "Aragón", 2), ("AS", "Asturias", 3), ("IB", "Illes Balears", 4),
    ("CN", "Canarias", 5), ("CB", "Cantabria", 6), ("CL", "Castilla y León", 7), ("CM", "Castilla-La Mancha", 8),
    ("CT", "Cataluña", 9), ("VC", "Comunitat Valenciana", 10), ("EX", "Extremadura", 11), ("GA", "Galicia", 12),
    ("MD", "Comunidad de Madrid", 13), ("MC", "Región de Murcia", 14), ("NC", "Navarra", 15), ("PV", "País Vasco", 16),
    ("RI", "La Rioja", 17), ("CE", "Ceuta", 18), ("ML", "Melilla", 19),
]
NOMBRE_CCAA = {c: n for c, n, _ in CCAA}
INE_CCAA = {c: i for c, _, i in CCAA}

# Provincia (código INE) -> comunidad.
PROVINCIA_CCAA = {
    4: "AN", 11: "AN", 14: "AN", 18: "AN", 21: "AN", 23: "AN", 29: "AN", 41: "AN",
    22: "AR", 44: "AR", 50: "AR", 33: "AS", 7: "IB", 35: "CN", 38: "CN", 39: "CB",
    5: "CL", 9: "CL", 24: "CL", 34: "CL", 37: "CL", 40: "CL", 42: "CL", 47: "CL", 49: "CL",
    2: "CM", 13: "CM", 16: "CM", 19: "CM", 45: "CM", 8: "CT", 17: "CT", 25: "CT", 43: "CT",
    3: "VC", 12: "VC", 46: "VC", 6: "EX", 10: "EX", 15: "GA", 27: "GA", 32: "GA", 36: "GA",
    28: "MD", 30: "MC", 31: "NC", 1: "PV", 20: "PV", 48: "PV", 26: "RI", 51: "CE", 52: "ML",
}

NUM_JUNTAS = {"alava": 20, "bizkaia": 21, "gipuzkoa": 22}
NUM_CABILDOS = {"gran-canaria": 23, "tenerife": 24, "lanzarote": 25, "fuerteventura": 26, "la-palma": 27,
                "la-gomera": 28, "el-hierro": 29}
NUM_CONSELLS = {"mallorca": 30, "menorca": 31, "eivissa": 32, "formentera": 33}

# Mandatos municipales (y de cabildos, consells y diputaciones): numerados desde 1979.
MANDATOS_LOCALES = {
    9: ("IX", "2011-06-11", "2015-06-13"),
    10: ("X", "2015-06-13", "2019-06-15"),
    11: ("XI", "2019-06-15", "2023-06-17"),
    12: ("XII", "2023-06-17", None),
}


def num_parlamento(ccaa):
    return INE_CCAA[ccaa]


def num_diputacion(provincia_ine):
    return 200 + int(provincia_ine)


def num_municipio(ine):
    """Código INE de 5 cifras del municipio (p. ej. «33024», Gijón)."""
    return int(ine)


def id_legislatura(num, numero):
    return int(num) * 100 + int(numero)


def romano(n):
    valores = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
               (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in valores:
        while n >= v:
            out += s
            n -= v
    return out


@dataclass
class Cuerpo:
    """Institución cuyas votaciones se recogen."""

    codigo: str                 # único y estable: «congreso», «parl-AS», «ayto-gijon», «jjgg-alava»…
    num: int                    # ver la tabla de números reservados arriba
    nombre: str                 # «Junta General del Principado de Asturias»
    corto: str                  # para etiquetas: «Junta General (Asturias)»
    nivel: str                  # clave de NIVELES
    ccaa: str | None            # comunidad a la que pertenece (None para las nacionales)
    escanos: int                # escaños o concejales (por defecto para todas sus legislaturas)
    # número -> (romano, inicio, fin[, escaños si cambian])
    legislaturas: dict = field(default_factory=dict)
    web: str | None = None      # página de la fuente
    grupo_nivel: str | None = None  # agrupación dentro de la comunidad («Juntas Generales», «Cabildos»…)

    def escanos_de(self, numero):
        t = self.legislaturas.get(numero) or ()
        return t[3] if len(t) > 3 and t[3] else self.escanos

    def legislatura_de(self, fecha):
        """Número de la legislatura vigente en una fecha (AAAA-MM-DD)."""
        for n, (_rom, ini, fin, *_) in sorted(self.legislaturas.items()):
            if ini <= fecha and (fin is None or fecha < fin):
                return n
        return None

    def id_leg(self, numero):
        return id_legislatura(self.num, numero)


def congreso():
    from .config import LEGISLATURAS

    return Cuerpo("congreso", 0, "Congreso de los Diputados", "Congreso", "nacional", None, 350,
                  {n: v for n, v in LEGISLATURAS.items()}, "https://www.congreso.es")


def cuerpos():
    """Todas las instituciones: el Congreso y las que declaran los conectores territoriales."""
    from .territorial.fuentes import CUERPOS

    todos = [congreso(), *CUERPOS]
    vistos = {}
    for c in todos:
        otro = vistos.get(c.num)
        if otro and otro.codigo != c.codigo:
            raise ValueError(f"Número {c.num} repetido: {otro.codigo} y {c.codigo}")
        vistos[c.num] = c
    return todos


def por_codigo():
    return {c.codigo: c for c in cuerpos()}


def arbol(con_datos=None):
    """Nodos del árbol de ámbitos: [(codigo, padre, nombre, nivel, cuerpo, orden)].

    España > Nacional (Congreso…) y Comunidades autónomas > cada comunidad > su parlamento, las
    instituciones provinciales o insulares y los ayuntamientos. Con `con_datos` (conjunto de
    códigos de cuerpo), solo se incluyen las ramas que tienen alguna institución con datos.
    """
    todos = [c for c in cuerpos() if con_datos is None or c.codigo in con_datos]
    nodos = [("es", None, "Toda España", None, None, 0)]
    nacionales = [c for c in todos if c.nivel == "nacional"]
    if nacionales:
        nodos.append(("nacional", "es", "Nacional", "nacional", None, 1))
        for i, c in enumerate(nacionales):
            nodos.append((c.codigo, "nacional", c.nombre, c.nivel, c.codigo, i))
    ccaa_con = [cc for cc, _n, _i in CCAA if any(c.ccaa == cc for c in todos)]
    if ccaa_con:
        nodos.append(("ccaa", "es", "Comunidades autónomas", None, None, 2))
    orden_nivel = {"autonomico": 0, "provincial": 1, "municipal": 2}
    for i, cc in enumerate(sorted(ccaa_con, key=lambda x: NOMBRE_CCAA[x])):
        nodos.append((cc, "ccaa", NOMBRE_CCAA[cc], None, None, i))
        propios = sorted((c for c in todos if c.ccaa == cc), key=lambda c: (orden_nivel.get(c.nivel, 9), c.nombre))
        grupos = set()
        for c in propios:
            if c.nivel == "autonomico":
                nodos.append((c.codigo, cc, c.nombre, c.nivel, c.codigo, 0))
                continue
            # Código estable («AS.municipal»): puede ir en enlaces compartidos.
            clave = f"{cc}.{c.nivel}"
            if clave not in grupos:
                grupos.add(clave)
                nodos.append((clave, cc, c.grupo_nivel or NIVELES[c.nivel], c.nivel, None, 1 + orden_nivel.get(c.nivel, 9)))
            nodos.append((c.codigo, clave, c.nombre, c.nivel, c.codigo, 0))
    return nodos
