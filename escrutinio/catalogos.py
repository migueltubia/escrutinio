"""Catálogos cerrados: tipos de expediente, temas y tipos de votación."""

# (prefijo, nombre, familia, fuerza_ley)
# familia: ley | decreto_ley | pnl | mocion | internacional | organizacion | control | otro
TIPOS_EXPEDIENTE = [
    ("110", "Autorización de convenio internacional", "internacional", 0),
    ("120", "Iniciativa legislativa popular", "ley", 1),
    ("121", "Proyecto de ley", "ley", 1),
    ("122", "Proposición de ley de grupos parlamentarios", "ley", 1),
    ("123", "Proposición de ley de diputados", "ley", 1),
    ("124", "Proposición de ley del Senado", "ley", 1),
    ("125", "Proposición de ley de comunidades autónomas", "ley", 1),
    ("127", "Propuesta de reforma de Estatuto de Autonomía", "ley", 1),
    ("130", "Real decreto-ley", "decreto_ley", 1),
    ("132", "Real decreto legislativo", "decreto_ley", 1),
    ("140", "Otras iniciativas legislativas", "ley", 1),
    ("152", "Comisión de investigación", "organizacion", 0),
    ("154", "Otras comisiones y subcomisiones", "organizacion", 0),
    ("155", "Creación de comisión permanente", "organizacion", 0),
    ("156", "Creación de comisión de investigación", "organizacion", 0),
    ("157", "Creación de otras comisiones no permanentes", "organizacion", 0),
    ("158", "Creación de subcomisiones y ponencias", "organizacion", 0),
    ("162", "Proposición no de ley ante el Pleno", "pnl", 0),
    ("173", "Moción consecuencia de interpelación urgente", "mocion", 0),
    ("200", "Comunicación del Gobierno (propuestas de resolución)", "control", 0),
    ("240", "Suplicatorio", "organizacion", 0),
    ("250", "Cuenta General del Estado", "control", 0),
    ("276", "Elección de miembros de órganos", "organizacion", 0),
    ("410", "Reforma del Reglamento del Congreso", "organizacion", 0),
    ("430", "Objetivo de estabilidad presupuestaria", "control", 0),
    ("180", "Investidura / confianza / censura", "organizacion", 0),
    ("SIN", "Asunto sin expediente identificado", "otro", 0),
]

# Prefijos que se descargan del buscador de iniciativas para enlazar votaciones.
PREFIJOS_BUSCADOR = [
    "110", "120", "121", "122", "123", "124", "125", "127", "130", "132",
    "152", "155", "156", "157", "158", "162", "173", "200", "240", "250", "276", "410", "430",
]

# Temas cerrados (código, nombre, subtemas de ejemplo).
TEMAS = [
    ("VIV", "Vivienda y urbanismo", "alquiler, vivienda pública, desahucios, okupación, pisos turísticos, suelo"),
    ("EMP", "Empleo y relaciones laborales", "salario mínimo, jornada, reforma laboral, desempleo, autónomos, conciliación"),
    ("PEN", "Pensiones y Seguridad Social", "revalorización, sostenibilidad, cotizaciones, ingreso mínimo vital"),
    ("FIS", "Fiscalidad", "IRPF, IVA, sociedades, impuestos a banca y energéticas, fraude fiscal"),
    ("PRE", "Presupuestos y finanzas públicas", "Presupuestos Generales, deuda, techo de gasto, fondos europeos"),
    ("ECO", "Economía, empresa y consumo", "banca, competencia, consumidores, industria, pymes, turismo"),
    ("SAN", "Sanidad", "sanidad pública, listas de espera, medicamentos, salud mental, tabaco"),
    ("EDU", "Educación y universidades", "leyes educativas, becas, FP, universidades, ciencia"),
    ("SOC", "Políticas sociales y familia", "dependencia, discapacidad, infancia, pobreza, mayores"),
    ("IGU", "Igualdad y derechos civiles", "violencia de género, LGTBI, paridad, memoria democrática, libertades"),
    ("MIG", "Inmigración y asilo", "regularización, fronteras, menores no acompañados, asilo"),
    ("JUS", "Justicia", "Código Penal, CGPJ, amnistía, organización judicial, indultos"),
    ("SEG", "Seguridad e interior", "policía, terrorismo, tráfico, prisiones, crimen organizado"),
    ("DEF", "Defensa", "gasto militar, misiones, Fuerzas Armadas, industria de defensa"),
    ("EXT", "Política exterior y UE", "tratados, Unión Europea, cooperación, conflictos internacionales"),
    ("TER", "Organización territorial", "estatutos, financiación autonómica, Cataluña, País Vasco, entes locales"),
    ("INS", "Instituciones y calidad democrática", "régimen electoral, transparencia, corrupción, Corona, reglamentos de las Cámaras"),
    ("ENE", "Energía", "precio de la luz, renovables, nuclear, gas"),
    ("MED", "Medio ambiente y clima", "cambio climático, agua, residuos, biodiversidad, bienestar animal"),
    ("AGR", "Agricultura, pesca y mundo rural", "PAC, sequía, despoblación, cadena alimentaria"),
    ("TRA", "Transporte e infraestructuras", "ferrocarril, abonos de transporte, carreteras, aeropuertos, puertos"),
    ("DIG", "Digital y tecnología", "inteligencia artificial, ciberseguridad, protección de datos, telecomunicaciones"),
    ("CUL", "Cultura, deporte y lenguas", "cultura, deporte, medios de comunicación, lenguas cooficiales"),
]
CODIGOS_TEMA = [t[0] for t in TEMAS]
MARCAS = ["emergencia", "omnibus"]

# Tipos de votación dentro de una iniciativa (lista cerrada).
TIPOS_VOTACION = {
    "pnl": "Proposición no de ley",
    "mocion": "Moción",
    "toma_consideracion": "Toma en consideración",
    "totalidad": "Enmienda a la totalidad",
    "enmiendas": "Enmiendas / votos particulares",
    "articulado": "Dictamen (articulado)",
    "conjunto": "Votación de conjunto",
    "enmiendas_senado": "Enmiendas del Senado",
    "veto_senado": "Veto del Senado",
    "convalidacion": "Convalidación de real decreto-ley",
    "tramitacion_ley": "Tramitación como proyecto de ley",
    "tratado": "Convenio internacional",
    "investidura": "Investidura, confianza o censura",
    "nombramiento": "Elección o nombramiento",
    "organizacion": "Organización de la Cámara",
    "control": "Control / propuestas de resolución",
    "otro": "Otro",
}
