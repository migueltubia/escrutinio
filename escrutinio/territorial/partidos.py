"""Partido, siglas y color de un grupo a partir del nombre que publica cada fuente.

Las fuentes escriben el mismo grupo de mil maneras («Grupo Parlamentario Socialista», «G.P.S.»,
«PSOE», «Socialistas de Gijón»). Aquí se reconoce el partido para que las siglas sean las mismas en
todas las instituciones (así la web puede sumar «el PSOE» del Congreso, de un parlamento y de un
ayuntamiento) y el color, el habitual del partido.
"""

import hashlib
import re

from ..texto import normalizar

# (patrón sobre el nombre normalizado, siglas, color). Se prueban en orden: primero lo específico.
PARTIDOS = [
    (r"\bno adscrit|\bsin adscripcion|\bno inscrit|\bdiputad[oa]s? no adscrit|\bconcejal(es)? no adscrit", "No adscritos", "#b4b4b4"),
    (r"\bmixto\b|\bmixt\b|\btalde mistoa\b", "Mixto", "#8a8f98"),
    (r"\bvox\b", "VOX", "#63be21"),
    (r"navarra suma|\bna\+", "NA+", "#1d4f9c"),
    (r"\bupn\b|union del pueblo navarro", "UPN", "#1d4f9c"),
    (r"\bcup\b|unitat popular|unidad popular", "CUP", "#ffed00"),
    (r"agrupacion socialista gomera|\basg\b", "ASG", "#2f8f3a"),
    (r"\bpartido popular\b|\bpopular(es)?\b|\bpp\b|\bgpp\b", "PP", "#1d84ce"),
    (r"\bpsc\b|socialistes de catalunya", "PSOE", "#e30613"),
    (r"socialista|\bpsoe\b|\bpsd?e\b|\bpse ee\b|\bfsa\b|\bpsib\b|\bpspv\b|\bpsdeg\b|\bpsn\b|\bgps\b|\bsocialistas?\b", "PSOE", "#e30613"),
    (r"ciudadanos|\bciutadans\b|\bcs\b|\bc s\b", "Cs", "#eb6109"),
    (r"eh bildu|\bbildu\b", "Bildu", "#00a19a"),
    (r"eaj pnv|\bpnv\b|\beaj\b|nacionalistas vascos|euzko abertzaleak", "PNV", "#008000"),
    (r"geroa bai", "Geroa Bai", "#e0301e"),
    (r"compromis", "Compromís", "#f18a00"),
    (r"mas madrid|mas pais|\bmes madrid", "Más Madrid", "#00c19d"),
    (r"\bsumar\b|movimiento sumar", "Sumar", "#e5007d"),
    (r"adelante andalucia", "Adelante Andalucía", "#00a650"),
    (r"elkarrekin|unidas podemos|unidos podemos|unidas por|unides podem|\bpodemos\b|\bpodem\b|\bpodemos\b|en comu podem", "Podemos", "#6c3483"),
    (r"\bcomuns\b|en comu|catalunya en comu|comuns sumar", "Comuns", "#c3113b"),
    (r"extremadura unida|juntos por extremadura", "EU-Ext", "#2e7d32"),
    (r"izquierda unida|\biu\b|esquerra unida|\beu\b|ezker batua|\bgeup\b", "IU", "#a31c2c"),
    (r"por andalucia", "Por Andalucía", "#6c3483"),
    (r"esquerra republicana|\berc\b|republicano", "ERC", "#ffb232"),
    (r"junts|junts per catalunya|\bjxcat\b|\bjxc\b|convergencia", "Junts", "#20c0b2"),
    (r"alianca catalana", "Aliança Catalana", "#0a2a5e"),
    (r"\bbng\b|bloque nacionalista galego", "BNG", "#76b3dd"),
    (r"coalicion canaria|\bcc\b|\bcc pnc\b|\bcc an\b", "CC", "#f7c600"),
    (r"nueva canarias|\bnc\b|\bnc bc\b", "NC", "#8fbe00"),
    (r"foro asturias|\bforo\b|\bfac\b", "Foro", "#0071bc"),
    (r"partido regionalista de cantabria|\bprc\b|regionalista", "PRC", "#a2c73b"),
    (r"chunta aragonesista|\bcha\b", "CHA", "#9e1a2c"),
    (r"partido aragones|\bpar\b", "PAR", "#f7b500"),
    (r"teruel existe", "Teruel Existe", "#00833e"),
    (r"soria ya", "Soria Ya", "#2e8b57"),
    (r"union del pueblo leones|\bupl\b", "UPL", "#b5163c"),
    (r"por avila|\bxav\b", "Por Ávila", "#1f5ea8"),
    (r"mes per mallorca|\bmes per menorca\b|\bmes\b", "Més", "#c5d300"),
    (r"\bel pi\b|proposta per les illes", "El Pi", "#7a4d9c"),
    (r"coalicion por melilla|\bcpm\b", "CpM", "#1b8a3a"),
    (r"movimiento por la dignidad|\bmdyc\b", "MDyC", "#7cb342"),
    (r"caballas", "Caballas", "#3a7d44"),
]

# Palabras de relleno del nombre de un grupo, para quedarse con lo que lo identifica.
_GENERICO = re.compile(
    r"(?i)^\s*(el\s+|la\s+)?(grupos?|g\.?\s*p\.?|g\.?\s*m\.?|talde|grup)\s+((parlamentari[oa]?|municipal|pol[ií]tico|"
    r"de\s+junteros|de\s+procuradores|juntero|mixto(?=\s+-))\s*)?(de\s+|del\s+|d')?")
_MINUSCULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "i", "por", "para", "en", "a", "per", "da", "do"}


def _limpio(nombre):
    return normalizar(nombre).replace("-", " ")


def reconocer(nombre):
    """(siglas, color) del partido de un grupo, o (None, None) si no se reconoce.

    Un grupo mixto con un solo partido en el nombre («G.P. Mixto-Adelante Andalucía») es ese partido.
    """
    n = _limpio(nombre)
    if re.search(PARTIDOS[1][0], n):
        resto = re.sub(PARTIDOS[1][0], " ", n)
        for patron, siglas, color in PARTIDOS[2:]:
            if re.search(patron, resto):
                return siglas, color
        return PARTIDOS[1][1], PARTIDOS[1][2]
    for patron, siglas, color in PARTIDOS:
        if re.search(patron, n):
            return siglas, color
    return None, None


def color_neutro(texto):
    """Color estable (gris azulado variado) para grupos locales sin partido conocido."""
    tonos = ["#6b7b8c", "#7a8f6a", "#8c7b6b", "#6b8c86", "#86738c", "#8c8a6b", "#5f7f9e", "#9e7f5f"]
    return tonos[int(hashlib.md5(texto.encode()).hexdigest(), 16) % len(tonos)]


def _nombre_propio(texto):
    """«VECINOS POR GIJÓN» -> «Vecinos por Gijón»; respeta siglas cortas y lo que ya viene con mayúsculas."""
    palabras = texto.split()
    if texto.upper() != texto:
        return " ".join(palabras)
    out = []
    for i, w in enumerate(palabras):
        if i and w.lower() in _MINUSCULAS:
            out.append(w.lower())
        elif len(w) <= 3 and w.isalpha():
            out.append(w)  # probablemente unas siglas
        else:
            out.append(w.capitalize())
    return " ".join(out)


def codigo_grupo(nombre):
    """(código, siglas, color) de un grupo. El código es único por legislatura y estable."""
    nombre = re.sub(r"\s+", " ", (nombre or "").strip())
    if not nombre:
        return "?", "?", "#9aa0a6"
    siglas, color = reconocer(nombre)
    if siglas:
        return siglas, siglas, color
    # Grupo local o sin partido reconocido: el propio nombre, sin «Grupo Municipal» y demás.
    corto = _nombre_propio(_GENERICO.sub("", nombre).strip(" .-–:()")) or nombre
    corto = corto[:40]
    return corto, corto, color_neutro(normalizar(corto))
