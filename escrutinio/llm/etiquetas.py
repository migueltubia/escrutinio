"""Normalización de etiquetas libres (segundo nivel de la taxonomía).

Las fichas guardan las etiquetas tal como las escribió el modelo; esta tabla, revisada por la IA
sobre la lista completa, agrupa variantes del mismo concepto y se aplica al exportar y al calcular
estadísticas. También neutraliza denominaciones coloquiales o peyorativas.
"""

import re

VERSION = "etiquetas-v1"

_GRUPOS = {
    "abono de transporte": ["abonos de transporte"],
    "accidente de santiago": ["accidente de angrois", "alvia"],
    "spanair": ["accidente de spanair"],
    "accidente ferroviario": ["accidentes ferroviarios"],
    "apagón": ["apagón eléctrico"],
    "atentados de barcelona y cambrils": ["atentados de barcelona", "cambrils"],
    "autoconsumo": ["autoconsumo eléctrico"],
    "avocación": ["avocación al pleno"],
    "bono social": ["bono social eléctrico"],
    "brecha salarial": ["brecha salarial de género"],
    "comunidad valenciana": ["comunitat valenciana", "país valenciano"],
    "conciliación": ["conciliación familiar", "conciliación laboral"],
    "industria electrointensiva": ["consumidor electrointensivo", "consumidores electrointensivos"],
    "contratación pública": ["contratos públicos"],
    "alcoholemia": ["controles de alcoholemia"],
    "cooperación judicial": ["cooperación judicial civil", "cooperación judicial penal", "cooperación judicial internacional",
                             "asistencia judicial", "asistencia judicial penal"],
    "copago": ["copago farmacéutico", "copago sanitario"],
    "créditos extraordinarios": ["crédito extraordinario"],
    "debate sobre el estado de la nación": ["debate del estado de la nación", "debate estado de la nación"],
    "cliente financiero": ["defensa del cliente financiero"],
    "consumidores": ["defensa de los consumidores", "protección al consumidor", "protección de consumidores"],
    "discursos de odio": ["discurso de odio"],
    "derecho de voto": ["derecho al voto"],
    "derechos de la infancia": ["derechos de los niños", "derechos del niño"],
    "empleo juvenil": ["desempleo juvenil", "empleo joven"],
    "deslocalización": ["deslocalización empresarial"],
    "evau": ["ebau"],
    "entorno digital": ["entornos digitales"],
    "ela": ["esclerosis lateral amiotrófica"],
    "estatuto de autonomía": ["estatutos de autonomía"],
    "precio de la luz": ["factura de la luz", "factura eléctrica", "tarifa eléctrica"],
    "factura electrónica": ["facturación electrónica"],
    "financiación de partidos": ["financiación de partidos políticos"],
    "fmi": ["fondo monetario internacional"],
    "fp dual": ["formación dual", "formación profesional dual"],
    "fronteras": ["frontera"],
    "fuerzas de seguridad": ["fuerzas de seguridad del estado"],
    "impuesto sobre sociedades": ["impuesto de sociedades"],
    "impuesto sobre sucesiones y donaciones": ["impuesto de sucesiones y donaciones"],
    "impuesto a las grandes fortunas": ["grandes fortunas"],
    "indultos": ["indulto"],
    "indemnizaciones": ["indemnización"],
    "infraestructuras ferroviarias": ["infraestructura ferroviaria"],
    "renta mínima": ["ingreso mínimo", "ingresos mínimos"],
    "aborto": ["interrupción del embarazo"],
    "iva cultural": ["iva cultura"],
    "castellano": ["lengua castellana", "lengua española"],
    "grupos de interés": ["lobbies"],
    "lobo": ["lobo ibérico"],
    "mede": ["mecanismo europeo de estabilidad", "mecanismo de estabilidad"],
    "medicamentos falsificados": ["falsificación de medicamentos"],
    "menores no acompañados": ["menas", "menores extranjeros"],
    "mercado de valores": ["mercados de valores"],
    "morosidad": ["morosidad comercial"],
    "estabilidad presupuestaria": ["objetivo de estabilidad presupuestaria", "objetivos de estabilidad presupuestaria"],
    "okupación": ["ocupación de viviendas"],
    "violencia de género": ["pacto de estado contra la violencia de género"],
    "pensión de orfandad": ["pensiones de orfandad", "orfandad"],
    "pensiones no contributivas": ["pensión no contributiva"],
    "permisos de nacimiento": ["permiso de nacimiento", "permiso de paternidad", "permiso parental", "permisos parentales",
                               "permisos de maternidad y paternidad", "permisos de paternidad y maternidad"],
    "permiso de conducir": ["permisos de conducción"],
    "refugiados": ["personas refugiadas"],
    "pac": ["política agrícola común"],
    "política del agua": ["política de aguas"],
    "participaciones preferentes": ["preferentes"],
    "rescate de grecia": ["rescate a grecia"],
    "reestructuración bancaria": ["saneamiento bancario"],
    "regadío": ["regadíos"],
    "salario mínimo": ["salario mínimo interprofesional"],
    "salud sexual y reproductiva": ["salud reproductiva"],
    "sanidad universal": ["acceso universal a la sanidad"],
    "subastas de medicamentos": ["subasta de medicamentos"],
    "subcomisión": ["subcomisión parlamentaria"],
    "sustracción de menores": ["sustracción internacional de menores"],
    "transferencia de competencias": ["transferencias de competencias"],
    "transposición de directivas": ["transposición de directivas ue", "transposición directivas ue"],
    "trata de personas": ["trata de seres humanos", "tráfico de personas"],
    "tedh": ["tribunal europeo de derechos humanos"],
    "corte penal internacional": ["tribunal penal internacional"],
    "ucrania": ["guerra de ucrania"],
    "unión postal universal": ["unión postal"],
    "la palma": ["volcán", "volcán de la palma", "erupción volcánica"],
    "voto exterior": ["voto en el exterior"],
    "vehículo eléctrico": ["movilidad eléctrica"],
    "temporales": ["temporal", "daños por temporales", "borrasca"],
    "despoblación": ["españa vaciada", "reto demográfico"],
    "vivienda pública": ["vivienda social", "parque público de vivienda"],
    "justicia universal": ["jurisdicción universal"],
    "justicia gratuita": ["asistencia jurídica gratuita"],
    "secretos oficiales": ["información clasificada", "desclasificación"],
    "empleo doméstico": ["empleadas de hogar", "trabajo doméstico"],
    "trabajadores agrarios": ["trabajadores del campo", "trabajadores eventuales agrarios", "trabajo agrario", "temporeros"],
    "seguridad laboral": ["seguridad y salud laboral"],
    "prestación por desempleo": ["prestaciones por desempleo", "subsidio de desempleo"],
    "hidrógeno": ["hidrógeno renovable"],
    "i+d+i": ["i+d"],
    "historia clínica": ["historia clínica digital"],
    "inmigración": ["migración"],
    "familia": ["familias"],
    "fraude fiscal": ["lucha contra el fraude fiscal"],
    "multirreincidencia": ["reincidencia"],
    "atención al ciudadano": ["atención ciudadana"],
    "comunidades de propietarios": ["comunidades de vecinos"],
    "seguridad ciudadana": ["ley mordaza"],
}

CANONICAS = {variante: canonica for canonica, variantes in _GRUPOS.items() for variante in variantes}


def canonicas(etiquetas):
    """Lista de etiquetas normalizadas, sin repetidos y en el orden original."""
    return list(dict.fromkeys(CANONICAS.get(e, e) for e in etiquetas))


_FECHA = re.compile(r",?\s+de\s+\d{1,2}\s+de\s+[a-záéíóúñ]+(?:\s+de\s+\d{4})?\s*,?", re.I)


def ley_canonica(nombre):
    """«Ley Orgánica 10/1995, de 23 de noviembre, del Código Penal» -> «Ley Orgánica 10/1995, del Código Penal»."""
    n = re.sub(r"\s+", " ", _FECHA.sub(",", nombre.strip())).strip(" ,.")
    n = re.sub(r",\s*,", ",", n)
    return re.sub(r"(?i)^real decreto-ley", "Real Decreto-ley", n)


def leyes_canonicas(leyes):
    return list(dict.fromkeys(ley_canonica(l) for l in leyes if l and l.strip()))
