"""Prueba un conector sin tocar la base de datos: valida lo que devuelve y lo resume.

    python -m escrutinio territorial-probar asturias --limite 50 --salida muestra.jsonl
"""

import json
import re
from collections import Counter, defaultdict

from ..catalogos import TIPOS_VOTACION
from .contexto import Contexto
from .fuentes import MODULOS
from .modelo import SENTIDOS, SENTIDOS_GRUPO, TIPOS_INICIATIVA, Documento, Iniciativa, Votacion

FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def errores_votacion(v, cuerpos):
    """Lista de problemas de una votación normalizada (vacía si está bien)."""
    e = []
    c = cuerpos.get(v.cuerpo)
    if not c:
        return [f"cuerpo desconocido {v.cuerpo!r}"]
    if not FECHA_RE.match(v.fecha or ""):
        e.append(f"fecha {v.fecha!r}")
    elif (v.legislatura or c.legislatura_de(v.fecha)) not in c.legislaturas:
        e.append(f"legislatura {v.legislatura!r} de {v.fecha} no declarada en el cuerpo")
    if not (v.titulo or "").strip():
        e.append("sin título")
    if not isinstance(v.sesion, int) or not isinstance(v.numero, int):
        e.append("sesion y numero deben ser enteros")
    if v.tipo_iniciativa and v.tipo_iniciativa not in TIPOS_INICIATIVA:
        e.append(f"tipo_iniciativa {v.tipo_iniciativa!r}")
    if v.tipo_votacion and v.tipo_votacion not in TIPOS_VOTACION:
        e.append(f"tipo_votacion {v.tipo_votacion!r}")
    if v.resultado not in (None, "aprobada", "rechazada"):
        e.append(f"resultado {v.resultado!r}")
    for g in v.grupos:
        if g.sentido and g.sentido not in SENTIDOS_GRUPO:
            e.append(f"sentido de grupo {g.sentido!r}")
        if not g.grupo:
            e.append("grupo sin nombre")
    for n in v.nominal:
        if n.sentido not in SENTIDOS:
            e.append(f"sentido nominal {n.sentido!r}")
            break
    if v.nominal and v.a_favor is not None:
        si = sum(1 for n in v.nominal if n.sentido == "si")
        if si != v.a_favor:
            e.append(f"el voto nominal suma {si} síes y los totales dicen {v.a_favor}")
    esc = c.escanos_de(v.legislatura or c.legislatura_de(v.fecha) or 0)
    total = sum(x or 0 for x in (v.a_favor, v.en_contra, v.abstenciones))
    if total > esc:
        e.append(f"{total} votos con {esc} escaños")
    if v.resultado is None and v.a_favor is None and not v.asentimiento:
        e.append("ni resultado ni totales")
    return e


def probar(nombre, limite=50, desde=None, completo=False, salida=None, log=print):
    m = MODULOS.get(nombre)
    if not m:
        raise SystemExit(f"No hay conector «{nombre}». Disponibles: {', '.join(MODULOS)}")
    cuerpos = {c.codigo: c for c in m.CUERPOS}
    ctx = Contexto(desde={c: desde for c in cuerpos} if desde else None, completo=completo, limite=limite, log=log)
    fh = open(salida, "w", encoding="utf-8") if salida else None
    n, malos, claves = 0, 0, Counter()
    resumen = defaultdict(Counter)
    iniciativas = 0
    if hasattr(m, "documentos"):
        probar_documentos(m, ctx, cuerpos, limite, fh, log)
    for obj in (m.descargar(ctx) if hasattr(m, "descargar") else ()):
        if isinstance(obj, Iniciativa):
            iniciativas += 1
            if fh:
                fh.write(json.dumps({"_iniciativa": obj.a_dict()}, ensure_ascii=False) + "\n")
            continue
        if not isinstance(obj, Votacion):
            raise TypeError(f"El conector devolvió {type(obj).__name__}")
        n += 1
        errs = errores_votacion(obj, cuerpos)
        if errs:
            malos += 1
            if malos <= 15:
                log(f"  ! {obj.cuerpo} {obj.fecha} s{obj.sesion} n{obj.numero}: {'; '.join(errs)}")
        clave = (obj.cuerpo, obj.fecha, obj.sesion, obj.numero)
        claves[clave] += 1
        leg = obj.legislatura or cuerpos[obj.cuerpo].legislatura_de(obj.fecha)
        r = resumen[(obj.cuerpo, leg)]
        r["votaciones"] += 1
        r["con totales"] += obj.a_favor is not None
        r["con resultado oficial"] += obj.resultado is not None
        r["con voto por grupo"] += bool(obj.grupos)
        r["con voto nominal"] += bool(obj.nominal)
        r["con expediente"] += bool(obj.expediente)
        r["asentimiento"] += bool(obj.asentimiento)
        if fh:
            fh.write(json.dumps(obj.a_dict(), ensure_ascii=False) + "\n")
        if limite and n >= limite:
            break
    if fh:
        fh.close()
    repetidas = sum(1 for c in claves.values() if c > 1)
    log(f"{nombre}: {n} votaciones ({malos} con problemas, {repetidas} claves repetidas), {iniciativas} iniciativas")
    for (cuerpo, leg), r in sorted(resumen.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        partes = ", ".join(f"{k} {v}" for k, v in r.items())
        log(f"  {cuerpo} leg {leg}: {partes}")
    return n, malos, repetidas


def probar_documentos(m, ctx, cuerpos, limite, fh, log):
    """Lista los documentos (diarios, actas) de un conector para LLM y extrae el texto del primero."""
    docs = []
    for d in m.documentos(ctx):
        if not isinstance(d, Documento):
            raise TypeError(f"documentos() devolvió {type(d).__name__}")
        if d.cuerpo not in cuerpos:
            log(f"  ! documento de un cuerpo desconocido: {d.cuerpo}")
        elif not FECHA_RE.match(d.fecha or "") or (d.legislatura or cuerpos[d.cuerpo].legislatura_de(d.fecha)) not in cuerpos[d.cuerpo].legislaturas:
            log(f"  ! documento con fecha o legislatura no declarada: {d.fecha} {d.url}")
        docs.append(d)
        if fh:
            fh.write(json.dumps({"_documento": d.a_dict()}, ensure_ascii=False) + "\n")
        if limite and len(docs) >= limite:
            break
    log(f"Documentos para LLM: {len(docs)}" + (f", del {min(d.fecha for d in docs)} al {max(d.fecha for d in docs)}" if docs else ""))
    if docs:
        from .actas_llm import texto_documento

        t = texto_documento(m, ctx, docs[0])
        log(f"  texto del primero ({docs[0].url}): {len(t)} caracteres")
        log("  " + t[:600].replace("\n", "\n  "))
