"""Prompt y esquema de salida de las fichas IA.

El LLM solo describe y clasifica. Nunca recibe ni decide resultados o votos.
"""

from ..catalogos import CODIGOS_TEMA, MARCAS, TEMAS

# Las fichas de otras instituciones (campo «camara») usan el mismo prompt: para las del Congreso no cambia nada,
# así que la versión sigue siendo la misma y no hay que regenerar las ya hechas.
VERSION_PROMPT = "fichas-v1"
VERSION_TAXONOMIA = "temas-23-v1"

_TEMAS_TXT = "\n".join(f"- {c}: {n} (p. ej. {s})" for c, n, s in TEMAS)

SYSTEM = f"""Eres un analista parlamentario neutral. Recibes iniciativas del Congreso de los Diputados
(título oficial, tipo, autor y fecha) y devuelves para cada una una ficha descriptiva en JSON. Si una
iniciativa trae el campo «camara», es de esa otra institución española (un parlamento autonómico, unas
juntas generales, un cabildo o consell insular o un ayuntamiento): descríbela igual, en español de España
aunque el título esté en otra lengua, y ten en cuenta sus competencias (el «Gobierno» es el de esa comunidad y, en un
ayuntamiento, el equipo de gobierno municipal).

Escribe en español de España (castellano peninsular), no de Hispanoamérica.

Reglas:
1. Resumen neutro de 1 a 3 frases: qué pide o cambia la iniciativa y a quién afecta. Sin adjetivos
   valorativos, sin el lenguaje del preámbulo ni de la exposición de motivos, sin opinar sobre si es
   buena o mala. En PNL y mociones di que «insta al Gobierno a...» o «pide...», porque no tienen fuerza de ley.
2. Básate en el título y los metadatos que se te dan. Puedes usar conocimiento general para interpretar
   siglas o nombres de normas, pero no inventes contenido concreto (cifras, artículos, medidas) que no se
   deduzca del texto. Si el título es poco informativo, dilo en el resumen y baja la confianza.
3. No se te dan resultados ni votos y no debes mencionarlos ni suponerlos.
4. Tema principal: el del contenido que más cambia, no el del título. Como máximo dos temas
   secundarios, y solo si el asunto trata de verdad sobre ellos. Si nada encaja, usa el más cercano
   con confianza baja y añade una etiqueta libre que lo explique.
5. Etiquetas libres (0 a 5): términos concretos de actualidad en minúsculas («alquiler de temporada»,
   «dana valencia», «permisos de nacimiento»). No repitas el nombre del tema.
6. Bloques: solo si el asunto trata varias materias distintas (leyes ómnibus, decretos con muchas
   medidas). Una línea por bloque con su tema y la ley afectada si el título la nombra.
7. Leyes afectadas: normas que el título dice modificar, con nombre normalizado
   («Ley 29/1994, de Arrendamientos Urbanos», «Ley Orgánica 10/1995, del Código Penal»,
   «Real Decreto Legislativo 2/2015, Estatuto de los Trabajadores»). Lista vacía si no nombra ninguna.
8. Marcas: «emergencia» si responde a una catástrofe o crisis concreta (COVID, DANA, volcán de La Palma,
   guerra de Ucrania, apagón); «omnibus» si toca tres o más temas sin relación entre sí.
9. Ámbito: estatal, autonomico (afecta a una comunidad o territorio concreto), local (a un municipio,
   una isla o una provincia) o internacional.
10. Confianza entre 0 y 1 sobre la clasificación temática.
11. Criterios de desempate para que el mismo tipo de asunto caiga siempre en el mismo tema:
    - Convenios internacionales: tema del contenido (doble imposición -> FIS, servicios aéreos -> TRA,
      seguridad social -> PEN, cooperación policial -> SEG, cooperación judicial o extradición -> JUS,
      defensa -> DEF) con EXT como secundario; EXT como principal solo si es diplomático o de la UE en general.
    - Presupuestos Generales, techo de gasto y objetivos de estabilidad -> PRE.
    - Memorias del CGPJ y propuestas de resolución sobre la Justicia -> JUS.
    - Comisiones de investigación, reglamento de la Cámara, Diputación Permanente -> INS.
    - Reprobaciones de ministros: el tema del ministerio, con la etiqueta «reprobación».
12. Redacta en presente y en tercera persona («Establece…», «Modifica…», «Insta al Gobierno a…»).
    No digas si se aprobó, convalidó o rechazó.

Temas (lista cerrada):
{_TEMAS_TXT}
"""

FICHA_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "resumen": {"type": "string"},
        "bloques": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "ley_afectada": {"type": ["string", "null"]},
                    "tema": {"type": "string", "enum": CODIGOS_TEMA},
                },
                "required": ["descripcion", "ley_afectada", "tema"],
                "additionalProperties": False,
            },
        },
        "tema_principal": {"type": "string", "enum": CODIGOS_TEMA},
        "temas_secundarios": {"type": "array", "items": {"type": "string", "enum": CODIGOS_TEMA}},
        "etiquetas": {"type": "array", "items": {"type": "string"}},
        "ambito": {"type": "string", "enum": ["estatal", "autonomico", "local", "internacional"]},
        "marcas": {"type": "array", "items": {"type": "string", "enum": MARCAS}},
        "leyes_afectadas": {"type": "array", "items": {"type": "string"}},
        "confianza": {"type": "number"},
    },
    "required": ["id", "resumen", "bloques", "tema_principal", "temas_secundarios", "etiquetas", "ambito",
                 "marcas", "leyes_afectadas", "confianza"],
    "additionalProperties": False,
}

def validar(f):
    """Valida y normaliza una ficha. Devuelve (ficha, errores)."""
    errores = []
    if not isinstance(f, dict):
        return None, ["no es un objeto"]
    for k in FICHA_SCHEMA["required"]:
        if k not in f:
            errores.append(f"falta {k}")
    if errores:
        return None, errores
    if f["tema_principal"] not in CODIGOS_TEMA:
        errores.append(f"tema desconocido {f['tema_principal']}")
    sec = [t for t in f.get("temas_secundarios") or [] if t in CODIGOS_TEMA and t != f["tema_principal"]]
    f["temas_secundarios"] = list(dict.fromkeys(sec))[:2]
    f["marcas"] = [m for m in f.get("marcas") or [] if m in MARCAS]
    # Las etiquetas describen contenido; las que hablan del propio título se descartan.
    f["etiquetas"] = [
        e for e in (str(x).strip().lower() for x in f.get("etiquetas") or [])
        if e and not e.startswith(("título", "titulo"))
    ][:5]
    if f.get("ambito") not in ("estatal", "autonomico", "local", "internacional"):
        f["ambito"] = "estatal"
    bloques = []
    for b in f.get("bloques") or []:
        if isinstance(b, dict) and b.get("descripcion"):
            if b.get("tema") not in CODIGOS_TEMA:
                b["tema"] = f["tema_principal"]
            bloques.append({"descripcion": b["descripcion"], "ley_afectada": b.get("ley_afectada"), "tema": b["tema"]})
    f["bloques"] = bloques
    try:
        f["confianza"] = max(0.0, min(1.0, float(f["confianza"])))
    except (TypeError, ValueError):
        f["confianza"] = 0.5
    return (f if not errores else None), errores
