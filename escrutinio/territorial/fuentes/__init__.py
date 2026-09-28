"""Registro de conectores territoriales.

Cada módulo de esta carpeta es un conector y declara:

- `CUERPOS`: lista de territorio.Cuerpo (instituciones que cubre, con sus legislaturas).
- `descargar(ctx)`: generador de modelo.Votacion (y, si quiere, de modelo.Iniciativa) para esas
  instituciones, a partir de datos estructurados (XML, CSV, JSON, HTML o PDF de formato fijo).
  Debe respetar `ctx.desde(cuerpo)` (recogida incremental: None = todo el histórico) y
  `ctx.limite` (probar con pocas votaciones sin descargarlo todo: mejor recorrer de lo más
  reciente a lo más antiguo).
- `documentos(ctx)` (en vez de, o además de, `descargar`): generador de modelo.Documento para las
  fuentes que solo publican el diario de sesiones o el acta en texto libre. De ahí saca las
  votaciones un LLM (territorial/actas_llm.py). Si el texto no se obtiene descargando la URL tal
  cual (HTML con mucho ruido, varios ficheros por sesión…), el módulo puede definir además
  `texto(ctx, documento) -> str`.
- Opcionales: `ACTIVO = False` para dejarlo fuera de la recogida automática (web que bloquea,
  conector a medias), `NOTAS` con la cobertura y las limitaciones, `INSEGURO = True` si la web tiene
  el certificado mal (para descargar sus documentos) y `DOCUMENTOS_COMPLETAN = True` si sus actas
  añaden detalle a días que ya tienen votaciones de `descargar` (si no, esos días no van al LLM).

Los módulos que empiezan por «_» no son conectores.
"""

import importlib
import pkgutil
import sys

MODULOS = {}
CUERPOS = []
ERRORES = {}  # conectores que no se pudieron importar: no deben tumbar a los demás

for _info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if _info.name.startswith("_"):
        continue
    try:
        _m = importlib.import_module(f"{__name__}.{_info.name}")
    except Exception as _e:  # noqa: BLE001
        ERRORES[_info.name] = f"{type(_e).__name__}: {_e}"
        print(f"! Conector territorial «{_info.name}» sin cargar: {ERRORES[_info.name]}", file=sys.stderr)
        continue
    MODULOS[_info.name] = _m
    CUERPOS.extend(getattr(_m, "CUERPOS", []))


def modulo_de(cuerpo):
    for nombre, m in MODULOS.items():
        if any(c.codigo == cuerpo for c in getattr(m, "CUERPOS", [])):
            return nombre, m
    return None, None
