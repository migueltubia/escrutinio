"""Votaciones sacadas con un LLM de diarios de sesiones y actas en texto libre.

La mayoría de parlamentos autonómicos y ayuntamientos no publican sus votaciones como datos: las
cuentan en el diario de sesiones o en el acta («queda aprobada por 25 votos a favor (GP, GS y GV),
1 en contra y 2 abstenciones»). Sus conectores generan modelo.Documento y aquí:

1. Se obtiene el texto (PDF o HTML) y se condensa: solo los encabezados de cada asunto (donde va el
   título y el expediente) y los párrafos de las votaciones, con su contexto.
2. Un LLM devuelve cada votación con su asunto, expediente, totales, voto por grupo y resultado,
   sin inventar nada que no esté escrito. Se valida (tipos, sentidos, totales que no superen los
   escaños) y se convierte en modelo.Votacion con fuente «pdf-llm» o «html-llm».
3. Lo extraído se guarda en data/llm/actas/<cuerpo>.jsonl, una línea por documento: es la fuente de
   verdad de esta parte (como las fichas IA), así que reconstruir la base no vuelve a llamar al LLM y
   un documento ya procesado no se repite.

Sin clave de DeepSeek, `actas-exportar` deja los textos condensados y unas instrucciones para que
otro LLM o agente los procese, y `actas-importar` carga sus respuestas.
"""

import html
import json
import re
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

from ..config import LLM_DIR
from ..texto import tokens
from . import estado
from .contexto import Contexto
from .modelo import SENTIDOS_GRUPO, TIPOS_INICIATIVA, Votacion, VotoGrupo

VERSION = "actas-v1"
ACTAS_DIR = LLM_DIR / "actas"
PENDIENTES_DIR = ACTAS_DIR / "pendientes"
MAX_TROZO = 45_000  # caracteres de texto condensado por llamada
MIN_PARTIR = 2_000  # un trozo cuya respuesta no cabe se parte en dos mientras tenga al menos esto
# El modelo razona antes de responder y ese razonamiento cuenta dentro de max_tokens: con 8.000 se lo comía
# entero y no llegaba a escribir nada. La API admite hasta 384K; sin fijarlo, el defecto en modo thinking es 64K.
MAX_TOKENS = 32_000

SISTEMA = """Eres un analista parlamentario. Recibes el texto (condensado) de un diario de sesiones o de un acta de
pleno de una institución española: un parlamento autonómico, unas juntas generales, un cabildo o consell
insular o un ayuntamiento. Puede estar en castellano, catalán, valenciano, gallego o euskera. Extrae TODAS
las votaciones del pleno que aparecen, en el orden en que se celebran, sin inventar nada.

Para cada votación devuelve:
- titulo: el asunto votado (título de la iniciativa o del punto del orden del día), en castellano si puedes
  traducirlo con fidelidad; si no, tal cual. Sin el nombre del grupo que lo presenta.
- subtitulo: qué se vota dentro del asunto si es una votación parcial (una enmienda, un punto, una votación
  separada, la toma en consideración…), o null.
- expediente: el número o código del expediente si aparece en el texto para ese asunto (p. ej. «11L/PNLP-0343»,
  «PNL/000735», «250-00521/15», «10/2023/PLE»), o null. No lo construyas tú.
- tipo_iniciativa: una de pl (proyecto de ley o de norma foral), ppl (proposición de ley o de norma foral),
  ilp, dl (convalidación de decreto-ley), presupuesto, ordenanza, pnl (proposición no de ley), mocion, acuerdo
  (propuesta de acuerdo o dictamen municipal), control, organizacion (elecciones, nombramientos, reglamento),
  investidura, otro.
- autor: grupo, gobierno o institución que presenta el asunto, si se dice; si no, null.
- a_favor, en_contra, abstenciones: números solo si el texto los da (o si da la lista de quién votó qué con
  el número de miembros de cada grupo escrito en el texto); si no, null.
- unanimidad: true si se aprueba por unanimidad o por asentimiento.
- resultado: aprobada | rechazada | null si el texto no lo dice ni se deduce de los totales escritos.
- grupos: lista de {"grupo": nombre tal como aparece, "sentido": si | no | abstencion | dividido} solo si el
  texto dice qué votó cada grupo; si no, lista vacía.

Reglas: no deduzcas totales ni sentidos que no estén escritos; no incluyas votaciones de comisiones ni de otras
sesiones que se mencionen; si una votación se repite (por ejemplo por empate), inclúyelas todas; si el texto no
tiene ninguna votación, devuelve una lista vacía.
Responde SOLO con un objeto json: {"votaciones": [{"titulo": "...", "subtitulo": null, "expediente": null,
"tipo_iniciativa": "mocion", "autor": null, "a_favor": 14, "en_contra": 13, "abstenciones": 0,
"unanimidad": false, "resultado": "aprobada", "grupos": [{"grupo": "PSOE", "sentido": "si"}]}]}"""

# Lo que delata el resultado de una votación (varias lenguas): recuentos y fórmulas de resultado. No basta
# con «votación», que sale en cada punto del orden del día («Debate y votación de…»).
_VOTO = re.compile(
    r"(?i)votos? a favor|votos? en contra|en contra[:,?]|a favor[:,?]|abstenci[oó]n(es)?[:,?]|\babstenci[oó]ns\b|"
    r"votos emitidos|votos? afirmativos|votos? negativos|vots? a favor|vots? en contra|abstencions|vots emesos|"
    r"queda(n)? (aprobad|rechazad|aprovad|rebutjad|desestimad)|ha(n)? (quedado|resultado|sido) (aprobad|rechazad)|"
    r"(se|es) (aprueba|rechaza|desestima)|resulta(n)? (aprobad|rechazad)|ha(n)? quedat (aprovad|rebutjad)|"
    r"ha(n)? estat (aprovad|rebutjad)|s'aprova|es rebutja|unanimidad|unanimitat|unanimidade|asentimiento|"
    r"rexeitad|aprobad[oa]s? (por|con)|aldeko|kontrako|abstentzio|onartu(a|ta|rik)|ez da onartu|"
    r"queda(n)? investid|investid[oa] (president|lehendakari)|voto favorable|votos? favorables|mayor[ií]a absoluta|"
    r"majoria absoluta|votaci[oó]n (p[uú]blica )?por llamamiento|votaci[oó] nominal|resultado de la votaci|"
    r"\d+\s+votos|\d+\s+vots|votos? (en blanco|nulos?)|vots? (en blanc|nuls?)|ha obtenido|resulta(n)? elegid|queda(n)? elegid|"
    r"elegid[oa]s? (president|vicepresident|secretari)|"
    # Recuentos leídos sin «votos a favor»: «Finaliza la votación. Emitidos, sesenta y seis; sí, treinta y cuatro; no…»
    r"finaliza(da)? la votaci|\bemitidos\b|\bs[ií], (un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|"
    r"catorce|quince|dieci|veint|treint|cuarent|cincuent|sesent|setent|ochent|novent|cien|\d)|ningun[ao] abstenci")
_ASUNTO = re.compile(
    r"(?i)(proposici[oó]n no de ley|proposici[oó] no de llei|proposici[oó]n de ley|proposici[oó] de llei|"
    r"proyecto de ley|projecte de llei|moci[oó]n|moci[oó]|decreto[- ]ley|decret llei|dictamen|propuesta de|"
    r"proposta de|punto\s+\d|punt\s+\d|asunto\s+n|expediente|\b\d{1,2}L/|/\d{4,6}\b|^\s*\d{1,3}[.\-–)]\s+\S)")


def html_a_texto(h):
    h = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t\xa0]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def texto_documento(modulo, ctx, doc):
    """Texto de un documento: el que dé el propio conector o el de su URL (PDF o HTML)."""
    if hasattr(modulo, "texto"):
        return modulo.texto(ctx, doc)
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/docs/{Contexto.clave(doc.url)}.{doc.formato}",
                    inseguro=getattr(modulo, "INSEGURO", False))
    if doc.formato == "pdf" or raw[:5] == b"%PDF-":
        return Contexto.pdf_texto(raw, layout=False)
    for enc in ("utf-8", "cp1252"):
        try:
            texto = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = raw.decode("utf-8", "replace")
    return html_a_texto(texto) if doc.formato == "html" else texto


def condensar(texto, antes=4, despues=4, entero=15_000):
    """Encabezados de asunto (título y expediente) y párrafos con el resultado de cada votación, con unas
    líneas alrededor (antes: lo que se vota; después: el recuento que sigue). Si ya es corto, entero."""
    if len(texto) <= entero:
        return texto
    lineas = [l.rstrip() for l in texto.splitlines()]
    quedan = set()
    for i, l in enumerate(lineas):
        if _VOTO.search(l):
            quedan.update(range(max(0, i - antes), min(len(lineas), i + despues + 1)))
        elif _ASUNTO.search(l) and len(l) < 400:
            # El título del asunto suele seguir en 2-5 líneas; las vacías y los restos de paginación no cuentan.
            j, llenas = i, 0
            while j < len(lineas) and llenas < 6:
                quedan.add(j)
                llenas += len(lineas[j].strip()) > 6
                j += 1
    out, previo = [], -2
    for i in sorted(quedan):
        if i != previo + 1:
            out.append("[…]")
        if lineas[i].strip():
            out.append(lineas[i])
        previo = i
    return "\n".join(out)


def trozos(texto):
    partes, actual = [], []
    n = 0
    for l in texto.splitlines():
        if n + len(l) > MAX_TROZO and actual:
            partes.append("\n".join(actual))
            actual, n = [], 0
        actual.append(l)
        n += len(l) + 1
    if actual:
        partes.append("\n".join(actual))
    return partes


def partir(texto):
    """Dos mitades de un trozo cuya respuesta no cabe en max_tokens (plenos con muchas votaciones). Se corta
    por el «[…]» más cercano al centro, para no separar un asunto de su votación; si no hay ninguno cerca, por
    la línea más cercana. Un trozo de una sola línea no se parte."""
    lineas = texto.splitlines()
    inicio, pos = [], 0
    for l in lineas:
        inicio.append(pos)
        pos += len(l) + 1
    centro = pos / 2
    candidatos = [i for i in range(1, len(lineas)) if lineas[i] == "[…]" and pos / 4 <= inicio[i] <= 3 * pos / 4]
    candidatos = candidatos or list(range(1, len(lineas)))
    if not candidatos:
        return [texto]
    corte = min(candidatos, key=lambda i: abs(inicio[i] - centro))
    return ["\n".join(lineas[:corte]), "\n".join(lineas[corte:])]


# ------------------------------------------------------------------ validación y conversión

def _entero(x):
    try:
        n = int(x)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def limpiar_votaciones(bruto, escanos):
    """Valida lo que devuelve el LLM. Descarta lo que no tiene ni resultado ni totales."""
    out = []
    for v in bruto or []:
        if not isinstance(v, dict) or not str(v.get("titulo") or "").strip():
            continue
        tot = {k: _entero(v.get(k)) for k in ("a_favor", "en_contra", "abstenciones")}
        if sum(x or 0 for x in tot.values()) > escanos:
            tot = dict.fromkeys(tot)  # imposible: más votos que escaños
        resultado = v.get("resultado") if v.get("resultado") in ("aprobada", "rechazada") else None
        unanimidad = bool(v.get("unanimidad"))
        if unanimidad and not resultado:
            resultado = "aprobada"
        if resultado is None and tot["a_favor"] is None:
            continue
        grupos = [{"grupo": str(g["grupo"]).strip()[:120], "sentido": g["sentido"]} for g in v.get("grupos") or []
                  if isinstance(g, dict) and g.get("grupo") and g.get("sentido") in SENTIDOS_GRUPO]
        out.append({
            "titulo": str(v["titulo"]).strip()[:1000],
            "subtitulo": (str(v.get("subtitulo")).strip()[:500] or None) if v.get("subtitulo") else None,
            "expediente": (str(v.get("expediente")).strip()[:60] or None) if v.get("expediente") else None,
            "tipo_iniciativa": v.get("tipo_iniciativa") if v.get("tipo_iniciativa") in TIPOS_INICIATIVA else None,
            "autor": (str(v.get("autor")).strip()[:200] or None) if v.get("autor") else None,
            **tot, "unanimidad": unanimidad, "resultado": resultado, "grupos": grupos,
        })
    return out


def a_votaciones(registro):
    """Líneas guardadas (un documento) -> modelo.Votacion."""
    doc = registro["documento"]
    sesion = doc.get("sesion") or int(doc["fecha"].replace("-", ""))
    fuente = ("html" if doc.get("formato") == "html" else "pdf") + "-llm"
    # Numeración aparte (de 500000 en adelante) para no pisar nunca una votación estructurada del mismo día y
    # sesión, y distinta por documento (hay días con dos plenos que comparten número de sesión).
    base = 500000 + (zlib.crc32(doc["url"].encode()) % 499) * 1000
    for i, v in enumerate(registro["votaciones"], 1):
        yield Votacion(
            cuerpo=doc["cuerpo"], fecha=doc["fecha"], titulo=v["titulo"], sesion=int(sesion), numero=base + i,
            legislatura=doc.get("legislatura"), subtitulo=v.get("subtitulo"), expediente=v.get("expediente"),
            tipo_iniciativa=v.get("tipo_iniciativa"), autor=v.get("autor"), a_favor=v.get("a_favor"),
            en_contra=v.get("en_contra"), abstenciones=v.get("abstenciones"),
            asentimiento=bool(v.get("unanimidad")) and v.get("a_favor") is None,
            resultado=v.get("resultado"), grupos=[VotoGrupo(g["grupo"], sentido=g["sentido"]) for g in v.get("grupos") or []],
            url=doc["url"], fuente=fuente, extra={"modelo": registro.get("modelo")})


# ------------------------------------------------------------------ fusión con los datos estructurados

class Fusion:
    """Guarda votaciones leídas de actas sin duplicar las que ya vienen de datos estructurados.

    Hay instituciones con las dos cosas (Valencia: un CSV con el resultado de las mociones y las actas
    con el voto de cada grupo; Gijón: un JSON hasta 2025 y las actas; los parlamentos cuyos diarios se
    leen con reglas y además se leyeron enteros). Una votación del acta es la misma que una ya guardada
    del mismo día si trata del mismo asunto o, si no, si tiene exactamente los mismos totales; entonces
    no se añade y, si a la guardada le falta el voto por grupo, se completa con el del acta. Si ese día
    ya tiene al menos tantas votaciones como el documento, las que no emparejan también se dan por
    recogidas (suelen ser las mismas con otro título); si tiene menos, se añaden.
    """

    def __init__(self, con, cargador):
        self.con, self.cargador, self.cache = con, cargador, {}
        self.n = {"nuevas": 0, "ya estaban": 0, "completadas": 0}

    def _estructuradas(self, cuerpo, fecha):
        clave = (cuerpo, fecha)
        if clave not in self.cache:
            self.cache[clave] = [
                (r[0], set(tokens(f"{r[1] or ''} {r[2] or ''}")), r[3], tuple(r[4:7]))
                for r in self.con.execute(
                    """SELECT v.id, v.texto_expediente, v.titulo_subgrupo,
                              EXISTS (SELECT 1 FROM voto_grupo g WHERE g.votacion_id=v.id),
                              v.a_favor, v.en_contra, v.abstenciones
                       FROM votacion v WHERE v.camara=? AND v.fecha=? AND COALESCE(v.fuente, '') NOT LIKE '%llm'""", clave)]
        return self.cache[clave]

    def guardar_todas(self, votaciones, log=None):
        """Las votaciones de un documento, emparejando cada una con una ya guardada como mucho una vez."""
        por_dia = {}
        for v in votaciones:
            por_dia.setdefault((v.cuerpo, v.fecha), []).append(v)
        for (cuerpo, fecha), lista in por_dia.items():
            cubierto = len(self._estructuradas(cuerpo, fecha)) >= len(lista)
            usadas = set()
            for v in lista:
                try:
                    self.guardar(v, usadas, cubierto)
                except ValueError as e:
                    if log is None:
                        raise
                    log(f"  ! {cuerpo}: {e}")

    def guardar(self, v, usadas=None, cubierto=False):
        usadas = set() if usadas is None else usadas
        candidatas = [c for c in self._estructuradas(v.cuerpo, v.fecha) if c[0] not in usadas]
        if candidatas:
            t = set(tokens(f"{v.titulo} {v.subtitulo or ''}"))
            mejor, puntos = None, 0.0
            for vid, ct, con_grupos, _ in candidatas:
                if t and ct:
                    p = len(t & ct) / min(len(t), len(ct))
                    if p > puntos:
                        mejor, puntos = (vid, con_grupos), p
            if not (mejor and puntos >= 0.6):
                mejor = None
                totales = (v.a_favor, v.en_contra, v.abstenciones)
                if None not in totales:
                    mejor = next(((vid, cg) for vid, _, cg, tot in candidatas if tot == totales), None)
            if mejor:
                vid, con_grupos = mejor
                usadas.add(vid)
                if not con_grupos and v.grupos:
                    leg = self.con.execute("SELECT legislatura FROM votacion WHERE id=?", (vid,)).fetchone()[0]
                    self.con.executemany(
                        "INSERT OR IGNORE INTO voto_grupo(votacion_id, grupo, si, no, abstencion, no_vota, sentido) VALUES (?,?,0,0,0,0,?)",
                        [(vid, self.cargador.grupo(leg, g.grupo), g.sentido) for g in v.grupos])
                    self.n["completadas"] += 1
                else:
                    self.n["ya estaban"] += 1
                return None
            if cubierto:
                self.n["ya estaban"] += 1
                return None
        self.n["nuevas"] += 1
        return self.cargador.guardar(v)


# ------------------------------------------------------------------ almacén (data/llm/actas)

def _ruta(cuerpo):
    return ACTAS_DIR / f"{cuerpo}.jsonl"


def procesados(cuerpo):
    ruta = _ruta(cuerpo)
    if not ruta.exists():
        return set()
    return {json.loads(l)["documento"]["url"] for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()}


def guardar_registro(doc, votaciones, modelo):
    ACTAS_DIR.mkdir(parents=True, exist_ok=True)
    registro = {"documento": doc.a_dict() if hasattr(doc, "a_dict") else doc, "modelo": modelo, "version": VERSION,
                "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "votaciones": votaciones}
    with open(_ruta(registro["documento"]["cuerpo"]), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


def cargar_guardadas(con, log=print):
    """Carga en la base todas las votaciones extraídas y guardadas en el repositorio."""
    from .. import territorio
    from .cargar import Cargador

    if not ACTAS_DIR.exists():
        return 0
    cuerpos = {c.codigo: c for c in territorio.cuerpos()}
    n = 0
    for ruta in sorted(ACTAS_DIR.glob("*.jsonl")):
        if ruta.stem not in cuerpos:
            log(f"  ! actas de un cuerpo que ya no existe: {ruta.name}")
            continue
        fusion = Fusion(con, Cargador(con, cuerpos, "actas-llm"))
        ultimo = {}
        for l in ruta.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                ultimo[r["documento"]["url"]] = r  # si un documento se reprocesó, gana lo último
        for r in ultimo.values():
            vs = list(a_votaciones(r))
            fusion.guardar_todas(vs, log)
            n += len(vs)
        con.commit()
        log(f"  {ruta.stem}: {fusion.n}")
    log(f"Votaciones leídas de actas y diarios: {n}")
    return n


# ------------------------------------------------------------------ documentos pendientes

def documentos_pendientes(con, fuentes=None, limite=None, log=print):
    """[(modulo, ctx, Documento)] de los conectores con documentos() que aún no se han procesado."""
    from .fuentes import MODULOS

    # Sin «desde»: los conectores listan de lo más reciente a lo más antiguo y aquí se saltan los ya
    # procesados, así que cada ejecución sigue con el atraso donde lo dejó la anterior.
    ctx = Contexto(completo=True, log=log)
    modulos = [(n, m) for n, m in MODULOS.items()
               if hasattr(m, "documentos") and (n in fuentes if fuentes else getattr(m, "ACTIVO", True))]
    # Cupo por conector: así el atraso de uno (cientos de diarios antiguos) no deja sin turno a los demás.
    cupo = max(2, -(-limite // len(modulos))) if limite and modulos else None
    out = []
    for nombre, m in modulos:
        hechos = {c.codigo: procesados(c.codigo) for c in m.CUERPOS}
        # Días que ya tienen votaciones de datos estructurados o leídas con reglas: su diario no se manda al
        # LLM (saldrían repetidas), salvo que el conector diga que sus actas completan esos datos.
        completan = getattr(m, "DOCUMENTOS_COMPLETAN", False)
        con_votos = set() if completan else {(r[0], r[1]) for r in con.execute(
            f"""SELECT DISTINCT camara, fecha FROM votacion WHERE COALESCE(fuente, '') NOT LIKE '%llm'
                AND camara IN ({','.join('?' * len(m.CUERPOS))})""", [c.codigo for c in m.CUERPOS])}
        propios, vistos, inicio = 0, 0, time.time()
        # Las fuentes que solo tienen diarios (sin `descargar`) se anotan aquí para el aviso de la web.
        solo_diarios = [c.codigo for c in m.CUERPOS] if not hasattr(m, "descargar") else []
        try:
            for doc in m.documentos(ctx):
                vistos += 1
                if doc.url not in hechos.get(doc.cuerpo, ()) and (doc.cuerpo, doc.fecha) not in con_votos:
                    out.append((m, ctx, doc))
                    propios += 1
                    if cupo and propios >= cupo:
                        break
            estado.anotar(con, nombre, solo_diarios)
        except Exception as e:  # web caída: se sigue con los demás
            log(f"  ! {nombre}: no se pudieron listar los documentos: {type(e).__name__}: {e}")
            estado.anotar(con, nombre, solo_diarios, estado.motivo(e), str(e))
        # Sin caché (GitHub Actions) algún listado puede tardar mucho: así se ve cuál.
        log(f"  {nombre}: {propios} pendientes de {vistos} documentos vistos; {round(time.time() - inicio)} s")
    # Lo más reciente primero, sea de donde sea.
    out.sort(key=lambda t: t[2].fecha, reverse=True)
    return out[:limite] if limite else out


def _escanos(doc):
    from .. import territorio

    c = territorio.por_codigo()[doc.cuerpo]
    return c.escanos_de(doc.legislatura or c.legislatura_de(doc.fecha) or 0)


def procesar_deepseek(con, limite=40, fuentes=None, log=print):
    """Extrae con DeepSeek las votaciones de los documentos pendientes y las carga."""
    from .. import territorio
    from ..llm import deepseek
    from .cargar import Cargador

    if not deepseek.disponible():
        log("Actas y diarios: sin DEEPSEEK_API_KEY; se omite la extracción con IA")
        return 0
    pendientes = documentos_pendientes(con, fuentes=fuentes, limite=limite, log=log)
    log(f"Actas y diarios con DeepSeek: {len(pendientes)} documentos pendientes (límite {limite})")
    cuerpos = {c.codigo: c for c in territorio.cuerpos()}
    total = 0
    for m, ctx, doc in pendientes:
        try:
            texto = condensar(texto_documento(m, ctx, doc))
        except Exception as e:
            log(f"  ! {doc.cuerpo} {doc.fecha}: no se pudo leer {doc.url}: {e}")
            continue
        votaciones, modelo, fallo = [], None, False
        cola, leidas = trozos(texto), 0
        while cola:
            parte = cola.pop(0)
            usuario = (f"Institución: {cuerpos[doc.cuerpo].nombre}. Sesión plenaria del {doc.fecha}"
                       + (f" (parte {leidas + 1})" if leidas else "") + ".\n\nTexto:\n" + parte)
            try:
                datos, modelo_real, _uso = deepseek.chat_json(SISTEMA, usuario, max_tokens=MAX_TOKENS)
            except deepseek.ErrorIA as e:
                mitades = partir(parte) if isinstance(e, deepseek.RespuestaTruncada) else []
                if len(mitades) == 2 and len(parte) >= MIN_PARTIR:
                    # Si no, el mismo texto se truncaría igual en cada ejecución y ocuparía el cupo del conector.
                    log(f"  · {doc.cuerpo} {doc.fecha}: {e}; se parte el texto en dos")
                    cola[:0] = mitades
                    continue
                log(f"  ! {doc.cuerpo} {doc.fecha}: {e}")
                fallo = True
                break
            leidas += 1
            modelo = f"deepseek:{modelo_real}"
            votaciones += limpiar_votaciones(datos.get("votaciones"), _escanos(doc))
        if fallo:
            continue  # se reintentará en la próxima ejecución
        registro = guardar_registro(doc, votaciones, modelo)
        fusion = Fusion(con, Cargador(con, cuerpos, "actas-llm"))
        fusion.guardar_todas(a_votaciones(registro))
        con.commit()
        total += len(votaciones)
        log(f"  {doc.cuerpo} {doc.fecha}: {len(votaciones)} votaciones")
    log(f"Actas y diarios: {total} votaciones extraídas de {len(pendientes)} documentos")
    return total


# ------------------------------------------------------------------ intercambio con otro LLM o agente

def nombre_pendiente(doc):
    return f"{doc.cuerpo}__{doc.fecha}__{Contexto.clave(doc.url)}"


def exportar(con, fuentes=None, limite=20, limpiar=False, log=print):
    """Deja en data/llm/actas/pendientes/ el texto condensado de los documentos pendientes.

    Se puede ir por tandas: lo ya exportado se conserva (salvo `limpiar`) y no se vuelve a descargar.
    indice.tsv lista nombre, institución, fecha y caracteres de cada uno, para repartir el trabajo.
    """
    PENDIENTES_DIR.mkdir(parents=True, exist_ok=True)
    if limpiar:
        for f in PENDIENTES_DIR.glob("*"):
            f.unlink()
    pendientes = documentos_pendientes(con, fuentes=fuentes, limite=limite or None, log=log)
    n = 0
    for m, ctx, doc in pendientes:
        nombre = nombre_pendiente(doc)
        if (PENDIENTES_DIR / f"{nombre}.txt").exists():
            continue
        try:
            texto = condensar(texto_documento(m, ctx, doc))
        except Exception as e:
            log(f"  ! {doc.url}: {e}")
            continue
        meta = {**doc.a_dict(), "escanos": _escanos(doc)}
        (PENDIENTES_DIR / f"{nombre}.txt").write_text(json.dumps(meta, ensure_ascii=False) + "\n\n" + texto, encoding="utf-8")
        n += 1
        if n % 50 == 0:
            log(f"  {n} documentos exportados")
    filas = []
    for f in sorted(PENDIENTES_DIR.glob("*.txt")):
        cuerpo, fecha, _ = f.stem.split("__")
        filas.append(f"{f.stem}\t{cuerpo}\t{fecha}\t{f.stat().st_size}")
    (PENDIENTES_DIR / "indice.tsv").write_text("\n".join(filas) + "\n", encoding="utf-8")
    (PENDIENTES_DIR / "INSTRUCCIONES.md").write_text(
        f"# Extracción de votaciones de diarios y actas ({VERSION})\n\n{SISTEMA}\n\n## Entrada\n\n"
        "Cada `pendientes/<nombre>.txt` empieza con una línea JSON con los datos del documento (cuerpo, fecha, url,\n"
        "escaños…) y, tras una línea en blanco, el texto condensado ([…] marca lo omitido).\n\n## Salida\n\n"
        "Por cada entrada, `respuestas/<nombre>.json` con el objeto json pedido arriba: {\"votaciones\": [...]}.\n"
        "Después: `python -m escrutinio actas-importar \"data/llm/actas/respuestas/*.json\" --modelo <modelo>`.\n",
        encoding="utf-8")
    log(f"{n} documentos nuevos exportados; {len(filas)} pendientes en {PENDIENTES_DIR}")


def validar(ficheros, log=print):
    """Comprueba respuestas {"votaciones": [...]} antes de importarlas. Devuelve True si todo está bien."""
    bien = True
    for patron in ficheros:
        rutas = sorted(Path().glob(patron)) if any(c in patron for c in "*?") else [Path(patron)]
        for ruta in rutas:
            entrada = PENDIENTES_DIR / f"{ruta.stem}.txt"
            problemas = []
            if not entrada.exists():
                problemas.append("no corresponde a ningún pendiente exportado")
                escanos = 999
            else:
                escanos = json.loads(entrada.read_text(encoding="utf-8").split("\n", 1)[0]).get("escanos") or 999
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                log(f"{ruta.name}: no se puede leer como JSON: {e}")
                bien = False
                continue
            bruto = datos.get("votaciones") if isinstance(datos, dict) else None
            if not isinstance(bruto, list):
                problemas.append("falta la lista «votaciones»")
                bruto = []
            limpias = limpiar_votaciones(bruto, escanos)
            for i, v in enumerate(bruto, 1):
                if not isinstance(v, dict):
                    problemas.append(f"votación {i}: no es un objeto")
                    continue
                if not str(v.get("titulo") or "").strip():
                    problemas.append(f"votación {i}: sin título")
                if v.get("resultado") not in (None, "aprobada", "rechazada"):
                    problemas.append(f"votación {i}: resultado {v.get('resultado')!r}")
                if v.get("tipo_iniciativa") not in (None, *TIPOS_INICIATIVA):
                    problemas.append(f"votación {i}: tipo_iniciativa {v.get('tipo_iniciativa')!r}")
                for k in ("a_favor", "en_contra", "abstenciones"):
                    if v.get(k) is not None and _entero(v.get(k)) is None:
                        problemas.append(f"votación {i}: {k} no es un número")
                for g in v.get("grupos") or []:
                    if not isinstance(g, dict) or g.get("sentido") not in SENTIDOS_GRUPO or not g.get("grupo"):
                        problemas.append(f"votación {i}: grupo mal formado {g!r}")
                if v.get("resultado") is None and v.get("a_favor") is None and not v.get("unanimidad"):
                    problemas.append(f"votación {i}: ni resultado ni totales (se descartará)")
                tot = sum(_entero(v.get(k)) or 0 for k in ("a_favor", "en_contra", "abstenciones"))
                if tot > escanos:
                    problemas.append(f"votación {i}: {tot} votos con {escanos} escaños")
            log(f"{ruta.name}: {len(bruto)} votaciones, {len(limpias)} válidas"
                + ("".join(f"\n  - {p}" for p in problemas[:15]) if problemas else ""))
            bien = bien and not problemas
    return bien


def importar(con, ficheros, modelo, log=print):
    """Carga respuestas {"votaciones": [...]} de documentos exportados con `exportar`."""
    from .. import territorio
    from .cargar import Cargador
    from .modelo import Documento

    cuerpos = {c.codigo: c for c in territorio.cuerpos()}
    n = 0
    for patron in ficheros:
        rutas = sorted(Path().glob(patron)) if any(c in patron for c in "*?") else [Path(patron)]
        for ruta in rutas:
            entrada = PENDIENTES_DIR / f"{ruta.stem}.txt"
            if not entrada.exists():
                log(f"  ! {ruta.name}: no está entre los pendientes exportados")
                continue
            meta = json.loads(entrada.read_text(encoding="utf-8").split("\n", 1)[0])
            escanos = meta.pop("escanos")
            doc = Documento(**meta)
            if doc.url in procesados(doc.cuerpo):
                log(f"  {ruta.name}: ya estaba procesado")
                continue
            votaciones = limpiar_votaciones(json.loads(ruta.read_text(encoding="utf-8")).get("votaciones"), escanos)
            registro = guardar_registro(doc, votaciones, modelo)
            fusion = Fusion(con, Cargador(con, cuerpos, "actas-llm"))
            fusion.guardar_todas(a_votaciones(registro))
            con.commit()
            n += len(votaciones)
    log(f"Votaciones importadas de actas y diarios: {n}")
