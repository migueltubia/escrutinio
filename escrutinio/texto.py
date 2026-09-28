import re
import unicodedata

STOP = {
    "de", "del", "la", "las", "el", "los", "y", "e", "o", "u", "a", "en", "por", "para", "con", "sobre",
    "al", "que", "se", "su", "sus", "un", "una", "lo", "relativa", "relativo", "relativas", "relativos",
}


def sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar(texto):
    t = sin_tildes((texto or "").lower())
    t = re.sub(r"[^a-z0-9ñ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(texto):
    return [w for w in normalizar(texto).split() if w not in STOP and len(w) > 1]


# Debates de política general (estado de la nación, de la comunidad o de la región, orientación política
# del Gobierno…): cada grupo presenta propuestas de resolución sobre cualquier asunto, así que lo que se
# vota no tiene el tema del debate. No lo son los debates y mociones sobre «la política general seguida
# en…» o «en materia de…» un asunto concreto, ni las propuestas cuyo título ya dice qué piden.
_DEBATE_GENERAL = re.compile(
    r"\b(?:debat|debate|debates|pleno|plenos|declaracio|declaracion)(?: anual)? (?:de|sobre) politica (?:general|xeral)\b"
    r"|\borientacion? politica\b"
    r"|\bestado (?:de la|da|del) (?:nacion|nacionalidad|comunidad|region|autonomia|ciudad|municipio|villa)\b"
    r"|\baccio politica i de govern\b"
    r"|\bactuacion politica del consejo de gobierno\b"
)
_NO_DEBATE_GENERAL = ("mocio", "interpel", "proposicio", "pregunta", "consecuencia", "presentada", "propuesta de impulso")


def es_debate_general(titulo):
    n = normalizar(titulo)
    if n.startswith(_NO_DEBATE_GENERAL) or "en materia" in n or "monografic" in n:
        return False
    return bool(_DEBATE_GENERAL.search(n))


# Grupos parlamentarios: (código en los ficheros de votación, legislaturas, patrón del autor, nombre, siglas, color)
GRUPOS = [
    ("GS", range(10, 16), r"socialista", "Grupo Socialista", "PSOE", "#e30613"),
    ("GP", range(10, 16), r"grupo parlamentario popular", "Grupo Popular", "PP", "#1d84ce"),
    ("GVOX", range(13, 16), r"\bvox\b", "Grupo VOX", "VOX", "#63be21"),
    ("GSUMAR", range(15, 16), r"sumar", "Grupo Plurinacional SUMAR", "Sumar", "#e5007d"),
    ("GP-EC-EM", range(11, 12), r"podemos|en comu|en marea", "Grupo Podemos-En Comú Podem-En Marea", "Podemos", "#6c3483"),
    ("GCUP-EC-EM", range(12, 13), r"podemos|en comu|en marea|confederal", "Grupo Confederal Unidos Podemos-En Comú Podem-En Marea", "UP", "#6c3483"),
    ("GCUP-EC-GC", range(13, 15), r"podemos|en comu|galicia en comun|confederal", "Grupo Confederal Unidas Podemos-En Comú Podem-Galicia en Común", "UP", "#6c3483"),
    ("GCs", range(11, 15), r"ciudadanos", "Grupo Ciudadanos", "Cs", "#eb6109"),
    ("GER", range(11, 13), r"esquerra republicana|republicano", "Grupo de Esquerra Republicana", "ERC", "#ffb232"),
    ("GR", range(13, 16), r"republicano|esquerra republicana", "Grupo Republicano", "ERC", "#ffb232"),
    ("GJxCAT", range(15, 16), r"junts", "Grupo Junts per Catalunya", "Junts", "#20c0b2"),
    ("GPlu", range(13, 15), r"plural", "Grupo Plural", "Plural", "#20c0b2"),
    ("GEH Bildu", range(14, 16), r"bildu", "Grupo Euskal Herria Bildu", "Bildu", "#00a19a"),
    ("GV (EAJ-PNV)", range(10, 16), r"vasco|eaj pnv|pnv", "Grupo Vasco (EAJ-PNV)", "PNV", "#008000"),
    ("GC-CiU", range(10, 11), r"catalan|convergencia", "Grupo Catalán (CiU)", "CiU", "#18307b"),
    ("GC-DL", range(11, 12), r"catalan|democracia i llibertat|democracia y libertad", "Grupo Catalán (Democràcia i Llibertat)", "DL", "#18307b"),
    ("GIP", range(10, 11), r"izquierda plural", "Grupo La Izquierda Plural", "IU-ICV", "#a31c2c"),
    ("GUPyD", range(10, 11), r"union progreso y democracia", "Grupo Unión Progreso y Democracia", "UPyD", "#e5007e"),
    ("GMx", range(10, 16), r"mixto", "Grupo Mixto", "Mixto", "#8a8f98"),
]

COLOR_DESCONOCIDO = "#9aa0a6"


def grupo_de_autor(autor, leg, codigos=None):
    """Código de grupo (el de los ficheros de votación) a partir del autor de una iniciativa."""
    a = normalizar(autor)
    if not a:
        return None
    if a.startswith("gobierno"):
        return "Gobierno"
    if "grupo" not in a:
        if "senado" in a:
            return "Senado"
        if "comunidad" in a or "parlamento" in a or "asamblea" in a or "cortes de" in a or "junta general" in a:
            return "CCAA"
        if "iniciativa legislativa popular" in a or "comision promotora" in a:
            return "ILP"
    if "izquierda plural" in a and leg == 10:
        return "GIP"
    encontrados = []
    for codigo, legs, patron, *_ in GRUPOS:
        if leg in legs and re.search(patron, a) and (codigos is None or codigo in codigos):
            encontrados.append(codigo)
    if encontrados:
        return encontrados[0]
    if "grupo" in a or "diputad" in a:
        return "Otros"
    return None


def info_grupo(codigo, leg):
    for c, legs, _p, nombre, siglas, color in GRUPOS:
        if c == codigo and leg in legs:
            return nombre, siglas, color
    for c, _legs, _p, nombre, siglas, color in GRUPOS:
        if c == codigo:
            return nombre, siglas, color
    return codigo, codigo, COLOR_DESCONOCIDO
