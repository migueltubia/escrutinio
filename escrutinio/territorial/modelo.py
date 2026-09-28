"""Modelo común de las fuentes autonómicas y locales.

Cada conector (escrutinio/territorial/fuentes/*.py) descarga lo que publica una institución y lo
devuelve con estas clases, ya normalizado. El resto (guardarlo en la base, calcular resultados y
grupos decisivos, afinidades, fichas IA, web) es común y no depende de la fuente.

Reglas para los conectores:
- Nada de inventar: si la fuente no da un dato (totales, voto por grupo, expediente), va a None.
- `sesion` y `numero` identifican la votación junto con la fecha y deben ser estables entre
  ejecuciones (el número de orden en el documento de la sesión vale).
- `expediente` es el código de la iniciativa en la propia fuente, tal cual («11/0177/0001/01562»,
  «11L/PNLP-0343»). Es la llave que une votaciones e iniciativa. Si no hay, se deduce del título.
- Los grupos van con el nombre que publica la fuente; al cargar se reconocen el partido, las
  siglas y el color (territorial/partidos.py).
"""

from dataclasses import asdict, dataclass, field

SENTIDOS = ("si", "no", "abstencion", "no_vota")
SENTIDOS_GRUPO = ("si", "no", "abstencion", "dividido")

# Tipo de iniciativa -> (nombre, familia). Se guarda como «prefijo» en iniciativa y votacion, igual
# que los prefijos numéricos del Congreso (121, 162…), y la familia agrupa en la web.
TIPOS_INICIATIVA = {
    "pl": ("Proyecto de ley o de norma foral", "ley"),
    "ppl": ("Proposición de ley o de norma foral", "ley"),
    "ilp": ("Iniciativa legislativa popular o municipal", "ley"),
    "dl": ("Decreto-ley (convalidación)", "decreto_ley"),
    "presupuesto": ("Presupuestos", "ley"),
    "ordenanza": ("Ordenanza o reglamento", "ley"),
    "pnl": ("Proposición no de ley", "pnl"),
    "mocion": ("Moción", "mocion"),
    "acuerdo": ("Propuesta de acuerdo o dictamen", "otro"),
    "control": ("Control al gobierno, planes e informes", "control"),
    "organizacion": ("Organización, elecciones y nombramientos", "organizacion"),
    "investidura": ("Investidura, confianza o censura", "organizacion"),
    "otro": ("Otros asuntos", "otro"),
}


@dataclass
class VotoGrupo:
    grupo: str                      # nombre tal como lo publica la fuente
    si: int | None = None
    no: int | None = None
    abstencion: int | None = None
    no_vota: int | None = None
    sentido: str | None = None      # si solo se conoce el sentido: si | no | abstencion | dividido


@dataclass
class VotoNominal:
    nombre: str
    grupo: str
    sentido: str                    # si | no | abstencion | no_vota


@dataclass
class Votacion:
    cuerpo: str                     # código de la institución (territorio.Cuerpo.codigo)
    fecha: str                      # AAAA-MM-DD
    titulo: str                     # asunto votado (título de la iniciativa o del punto del orden del día)
    sesion: int = 0                 # número de sesión; 0 si no se conoce
    numero: int = 0                 # orden de la votación en la sesión (único junto con fecha y sesión)
    legislatura: int | None = None  # número propio de la legislatura o mandato; si falta, por la fecha
    subtitulo: str | None = None    # qué se vota dentro del asunto (enmienda, punto, votación separada…)
    expediente: str | None = None   # código de la iniciativa en la fuente
    tipo_iniciativa: str | None = None  # clave de TIPOS_INICIATIVA
    tipo_votacion: str | None = None    # clave de catalogos.TIPOS_VOTACION, si la fuente lo deja claro
    autor: str | None = None        # quién presenta la iniciativa (grupo, Gobierno, alcaldía…)
    a_favor: int | None = None
    en_contra: int | None = None
    abstenciones: int | None = None
    no_votan: int | None = None
    presentes: int | None = None
    asentimiento: bool = False      # aprobada sin votación (asentimiento o unanimidad sin recuento)
    resultado: str | None = None    # «aprobada» o «rechazada» si la fuente lo dice
    mayoria: str | None = None      # «simple» o «absoluta» si se sabe
    grupos: list = field(default_factory=list)   # [VotoGrupo]
    nominal: list = field(default_factory=list)  # [VotoNominal]
    url: str | None = None          # documento de origen
    fuente: str = ""                # cómo se obtuvo: xml, csv, json, html, pdf-reglas, pdf-llm…
    extra: dict = field(default_factory=dict)

    def a_dict(self):
        return asdict(self)

    @staticmethod
    def de_dict(d):
        d = dict(d)
        d["grupos"] = [VotoGrupo(**g) for g in d.get("grupos") or []]
        d["nominal"] = [VotoNominal(**n) for n in d.get("nominal") or []]
        return Votacion(**d)


@dataclass
class Documento:
    """Diario de sesiones o acta en texto libre, del que un LLM saca las votaciones.

    Lo generan los conectores de fuentes sin datos estructurados (función `documentos(ctx)`); el
    extractor (territorial/actas_llm.py) lo lee, lo pasa al LLM y devuelve Votacion.
    """

    cuerpo: str
    fecha: str                      # AAAA-MM-DD de la sesión
    url: str                        # PDF o página del diario/acta
    sesion: int = 0                 # número de sesión si se conoce (si no, 0)
    formato: str = "pdf"            # pdf | html | txt
    idioma: str = "es"              # es | ca | gl | eu | va
    titulo: str | None = None
    legislatura: int | None = None
    extra: dict = field(default_factory=dict)

    def a_dict(self):
        return asdict(self)


@dataclass
class Iniciativa:
    """Ficha de una iniciativa (opcional: la mayoría de conectores solo dan votaciones)."""

    cuerpo: str
    expediente: str
    titulo: str
    legislatura: int | None = None
    tipo_iniciativa: str | None = None
    autor: str | None = None
    fecha_presentacion: str | None = None
    resultado: str | None = None    # resultado oficial de tramitación si se publica, en texto
    url: str | None = None
    extra: dict = field(default_factory=dict)

    def a_dict(self):
        return asdict(self)
