"""Compromisos de cada programa electoral, leídos una sola vez con DeepSeek.

El texto se trocea por páginas (unos 40.000 caracteres por trozo) y de cada trozo DeepSeek devuelve los
compromisos con su cita literal, el tema (los 23 de las fichas), el tipo de acción, quién tendría que
llevarlo a cabo y si es verificable. Las mismas reglas que en las actas:

- La cita tiene que aparecer tal cual en el texto (salvo espacios, comillas, mayúsculas y tildes; sin
  las cabeceras y pies de página repetidos, que cortan las frases entre páginas). Si no, el
  compromiso se descarta. Lo que se guarda es el fragmento del propio programa, no lo que devuelve el
  modelo, y la página sale de dónde está, no de lo que diga.
- Nada que no esté escrito; las frases vagas («impulsaremos», «apostaremos por») quedan como no
  verificables en vez de convertirse en compromisos.

El resultado va a data/llm/programas/<id>.jsonl, una línea por compromiso, y el registro lo marca como
leído. Cada trozo ya respondido se guarda en la caché local (data/raw/programas/trozos/), así que si
la lectura se corta a medias, al reintentar no se paga dos veces lo que ya estaba hecho.
"""

import hashlib
import json
import re
import threading
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ..catalogos import CODIGOS_TEMA, TEMAS
from ..llm import deepseek
from . import registro

# v2: la cita, en la lengua del programa (catalán, euskera, gallego…), sin traducir. En castellano da lo mismo que v1.
VERSION_PROMPT = "compromisos-v2"
MODELO = "deepseek-v4-pro"
MAX_TROZO = 40_000
HILOS = 4  # trozos de un programa que se piden a la vez
PROGRAMAS_A_LA_VEZ = 4
TIPOS_ACCION = {
    "legislar": "aprobar o reformar una ley",
    "derogar": "derogar una norma o parte de ella",
    "financiar": "dotar de dinero, una ayuda o una prestación",
    "crear_organismo": "crear un organismo, una agencia o un plan con nombre propio",
    "bajar_impuesto": "bajar, suprimir o bonificar un impuesto o una cotización",
    "subir_impuesto": "crear o subir un impuesto o una cotización",
    "declaracion": "declaración general o de principios",
    "otra": "otra medida concreta (gestión, acuerdos, reorganización…)",
}
RESPONSABLES = {
    "parlamento": "requiere una ley o un acuerdo de las Cortes",
    "gobierno": "lo puede hacer el Gobierno por su cuenta (real decreto, presupuestos, gestión)",
    "otra_administracion": "depende de las comunidades autónomas, los ayuntamientos o la Unión Europea",
}

_TEMAS_TXT = "\n".join(f"- {c}: {n} (p. ej. {s})" for c, n, s in TEMAS)
SISTEMA = f"""Eres un analista político neutral. Recibes un fragmento del programa electoral de un partido español para unas
elecciones generales. Extrae, en el orden en que aparecen, los compromisos que el partido dice que llevará a cabo.

Para cada compromiso devuelve:
- texto: el compromiso en una sola frase, en infinitivo y sin sujeto ni nombre de partido («Derogar la Ley X»,
  «Bajar el IVA de los alimentos básicos al 0 %», «Crear una agencia estatal de salud pública»). Sin valoraciones.
- cita: el fragmento del programa que contiene el compromiso, COPIADO LITERALMENTE carácter a carácter (una o dos
  frases, como mucho 300 caracteres). No corrijas erratas, no resumas, no cambies el orden ni las mayúsculas. Si el
  programa está en catalán, euskera, gallego u otra lengua, la cita va en esa lengua, SIN TRADUCIR; el texto, las
  etiquetas y todo lo demás, en castellano.
- tema: código de la lista cerrada de temas.
- etiquetas: de 0 a 3 términos concretos en minúsculas («alquiler de temporada», «ley de amnistía»).
- tipo_accion: una de {json.dumps(TIPOS_ACCION, ensure_ascii=False)}
- responsable: una de {json.dumps(RESPONSABLES, ensure_ascii=False)}
- verificable: true si promete una acción concreta cuyo cumplimiento se puede comprobar (una ley, una derogación,
  una cifra, un organismo, un impuesto, una prestación); false si es una intención general sin medida concreta
  («impulsaremos», «apostaremos por», «defenderemos», «fomentaremos» sin decir cómo).

Reglas:
1. Nada que no esté escrito en el fragmento. No completes cifras ni fechas.
2. Si un párrafo tiene varias medidas concretas distintas, un compromiso por medida, cada uno con su cita.
3. No son compromisos los diagnósticos, las críticas a otros partidos, los logros pasados ni los títulos, índices
   y portadas. Si el fragmento no tiene compromisos, devuelve una lista vacía.
4. Las frases vagas no se convierten en compromisos concretos: se devuelven con verificable false.

Temas (lista cerrada):
{_TEMAS_TXT}

Responde SOLO con un objeto json: {{"compromisos": [{{"texto": "Derogar la Ley X", "cita": "Derogaremos la Ley X…",
"tema": "JUS", "etiquetas": ["ley x"], "tipo_accion": "derogar", "responsable": "parlamento", "verificable": true}}]}}"""

_COMILLAS = str.maketrans({"“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "´": "'", "–": "-", "—": "-",
                           "­": None, "​": None})


def normalizar(s):
    s = unicodedata.normalize("NFKC", s or "").translate(_COMILLAS)
    return re.sub(r"\s+", " ", s).strip()


# Para buscar la cita sin tener en cuenta mayúsculas ni tildes. Cambia cada letra por una sola, así que las
# posiciones coinciden y lo que se guarda es el texto del propio programa.
_PLANO = str.maketrans("áéíóúàèìòùäëïöüâêîôû", "aeiouaeiouaeiouaeiou")


def _plano(s):
    return s.lower().translate(_PLANO)


def _sin_cabeceras(paginas):
    """Quita las cabeceras y los pies repetidos («/22 Madrid 7 de julio 2023 Bloque I», el número de página),
    que cortan las frases que siguen en la página siguiente: el modelo los salta y la cita no coincidiría."""
    def clave(linea):
        return re.sub(r"\d+", "#", linea.strip().lower())

    def bordes(p):  # las tres primeras y las tres últimas líneas con texto: donde van cabeceras y pies
        lineas = [l for l in p.splitlines() if l.strip()]
        return {clave(l) for l in lineas[:3] + lineas[-3:] if len(l.strip()) <= 80}

    cuenta = Counter(k for p in paginas for k in bordes(p))
    repetidas = {k for k, n in cuenta.items() if n >= (3 if "#" in k else 5)}
    salida = []
    for p in paginas:
        quitar = bordes(p) & repetidas
        salida.append("\n".join(l for l in p.splitlines() if clave(l) not in quitar))
    return salida


def trozos(txt):
    """[(primera página, páginas)] con páginas enteras hasta MAX_TROZO caracteres (las páginas empiezan en 1)."""
    paginas = _sin_cabeceras(txt.rstrip("\f").split("\f"))  # pdftotext acaba con un salto de página
    out, actual, desde = [], [], 1
    for n, pag in enumerate(paginas, 1):
        if actual and sum(len(p) for p in actual) + len(pag) > MAX_TROZO:
            out.append((desde, actual))
            actual, desde = [], n
        actual.append(pag)
    if any(p.strip() for p in actual):
        out.append((desde, actual))
    return out


def _en_orden(palabras, fuente):
    """Posición (en caracteres) donde empiezan las palabras de la cita dentro de la fuente, todas y en el mismo orden,
    con como mucho 3 palabras intercaladas entre dos seguidas y un 20 % en total; o None. Sirve para los PDF que
    repiten trozos de texto («situar-lo situar lo», «per per»): el modelo lee la frase limpia."""
    n = len(palabras)
    margen = max(3, n // 5)
    for i, (w, ini) in enumerate(fuente):
        if w != palabras[0]:
            continue
        k, sobran = i, 0
        for p in palabras[1:]:
            for salto in range(1, 5):
                if k + salto < len(fuente) and fuente[k + salto][0] == p:
                    k, sobran = k + salto, sobran + salto - 1
                    break
            else:
                break
            if sobran > margen:
                break
        else:
            return ini
    return None


def localizar(cita, paginas, desde):
    """(página, cita) si la cita está en el programa, o None.

    Primero se busca tal cual (salvo espacios, comillas, mayúsculas y tildes) y se guarda el fragmento del propio
    programa. Si no, se acepta cuando todas sus palabras están en el programa en el mismo orden y casi seguidas
    (_en_orden), y se guarda la cita del modelo: cada palabra suya está escrita en el programa, en ese orden.
    """
    normas = [normalizar(p) for p in paginas]
    inicios, pos = [], 0
    for n in normas:
        inicios.append(pos)
        pos += len(n) + 1
    completo = " ".join(normas)
    buscada = normalizar(cita)
    if len(buscada) < 20:
        return None
    i = _plano(completo).find(_plano(buscada))
    if i >= 0:
        return desde + max(k for k, ini in enumerate(inicios) if ini <= i), completo[i:i + len(buscada)]
    palabras = re.findall(r"\w+", _plano(buscada))
    if len(palabras) < 6:
        return None
    # Aquí se unen también las palabras partidas por guion al final de línea («propone- mos»), página a página.
    unidas = [_GUION.sub(r"\1\2", _plano(n)) for n in normas]
    inicios, pos = [], 0
    for n in unidas:
        inicios.append(pos)
        pos += len(n) + 1
    i = _en_orden(palabras, [(m.group(), m.start()) for m in re.finditer(r"\w+", " ".join(unidas))])
    if i is None:
        return None
    return desde + max(k for k, ini in enumerate(inicios) if ini <= i), buscada


_GUION = re.compile(r"(\w)- (\w)")


def validar(c):
    """Compromiso limpio o None. La cita se comprueba aparte (localizar)."""
    if not isinstance(c, dict):
        return None
    texto_ = normalizar(c.get("texto"))
    if not texto_ or not c.get("cita") or c.get("tema") not in CODIGOS_TEMA:
        return None
    etiquetas = [normalizar(e).lower() for e in (c.get("etiquetas") or []) if isinstance(e, str) and e.strip()][:3]
    return {
        "texto": texto_, "tema": c["tema"], "etiquetas": etiquetas,
        "tipo_accion": c.get("tipo_accion") if c.get("tipo_accion") in TIPOS_ACCION else "otra",
        "responsable": c.get("responsable") if c.get("responsable") in RESPONSABLES else "parlamento",
        "verificable": bool(c.get("verificable")),
    }


def ruta_compromisos(id_):
    return registro.PROGRAMAS_DIR / f"{id_}.jsonl"


def leer_compromisos(id_):
    ruta = ruta_compromisos(id_)
    if not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def _respuestas(desde, paginas, cache, modelo, solo_cache=False):
    """Respuestas de un trozo: [(primera página, páginas, respuesta, nueva)]. Cada respuesta sale de la caché (por el
    contenido del trozo) o de DeepSeek, y se guarda. Si la respuesta no cabe (muchos compromisos y mucho
    razonamiento), el trozo se parte en dos por las páginas y se pide cada mitad."""
    ruta = cache / f"{hashlib.sha1(chr(12).join(paginas).encode()).hexdigest()[:16]}.json"
    guardada = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
    if guardada and not guardada.get("partir"):
        return [(desde, paginas, guardada, False)]
    if not guardada and solo_cache:
        raise deepseek.ErrorIA(f"el trozo de las páginas {desde}–{desde + len(paginas) - 1} no está en la caché")
    if not guardada:
        try:
            datos, modelo_real, uso = deepseek.chat_json(SISTEMA, "Fragmento del programa (páginas "
                                                         f"{desde}–{desde + len(paginas) - 1}):\n\n" + "\n".join(paginas),
                                                         modelo, max_tokens=64_000)
        except deepseek.RespuestaTruncada:
            if len(paginas) < 2:
                raise
            ruta.write_text(json.dumps({"partir": True}), encoding="utf-8")  # al reintentar, directamente a las mitades
            guardada = {"partir": True}
    if guardada:
        mitad = len(paginas) // 2
        return (_respuestas(desde, paginas[:mitad], cache, modelo, solo_cache)
                + _respuestas(desde + mitad, paginas[mitad:], cache, modelo, solo_cache))
    respuesta = {"compromisos": datos.get("compromisos") or [], "modelo": f"deepseek:{modelo_real}",
                 "tokens_entrada": uso.get("prompt_tokens", 0), "tokens_salida": uso.get("completion_tokens", 0)}
    ruta.write_text(json.dumps(respuesta, ensure_ascii=False), encoding="utf-8")
    return [(desde, paginas, respuesta, True)]


def _leer_programa(e, modelo, log, version=VERSION_PROMPT, solo_cache=False):
    """Lee un programa trozo a trozo. Devuelve (compromisos, tokens de entrada, de salida, descartados)."""
    cache = registro.TEXTOS_DIR / "trozos" / e["id"] / version
    cache.mkdir(parents=True, exist_ok=True)
    partes = trozos(registro.texto(e["id"]))
    compromisos, t_in, t_out, brutos = [], 0, 0, 0
    usados = set()
    # Los trozos se piden a la vez (HILOS) y se procesan en orden. Si uno falla, los demás terminan y quedan en la caché.
    with ThreadPoolExecutor(HILOS) as hilos:
        futuros = [hilos.submit(_respuestas, desde, paginas, cache, modelo, solo_cache) for desde, paginas in partes]
        for k, ((desde, paginas), futuro) in enumerate(zip(partes, futuros), 1):
            for desde_p, paginas_p, respuesta, nueva in futuro.result():
                if nueva:
                    t_in += respuesta["tokens_entrada"]
                    t_out += respuesta["tokens_salida"]
                brutos += len(respuesta["compromisos"])
                _anadir(e, respuesta, paginas_p, desde_p, compromisos, usados)
            log(f"    trozo {k}/{len(partes)} (págs. {desde}–{desde + len(paginas) - 1}): {len(compromisos)} compromisos")
    return compromisos, t_in, t_out, brutos - len(compromisos)


def _anadir(e, respuesta, paginas, desde, compromisos, usados):
    """Añade los compromisos válidos de un trozo cuya cita está en el programa, con su página y su id."""
    for bruto in respuesta["compromisos"]:
        c = validar(bruto)
        sitio = localizar(bruto.get("cita", ""), paginas, desde) if c else None
        if not sitio:
            continue
        c["pagina"], c["cita"] = sitio
        # El id sale de la cita: si se relee y sale la misma cita, los emparejamientos y verificaciones siguen valiendo.
        base = f"{e['id']}:{hashlib.sha1(c['cita'].lower().encode()).hexdigest()[:8]}"
        c["id"], n = base, 2
        while c["id"] in usados:
            c["id"], n = f"{base}-{n}", n + 1
        usados.add(c["id"])
        compromisos.append({"id": c.pop("id"), **c, "modelo": respuesta["modelo"]})


def leer(ids=None, reintentar=False, limite=None, modelo=None, releer=False, log=print):
    """Lee los programas pendientes (y, con reintentar, los que fallaron). Lo ya leído no se vuelve a leer.

    Se leen varios programas a la vez (PROGRAMAS_A_LA_VEZ), cada uno con sus trozos en paralelo: en un programa
    corto, el trozo más lento marca el paso y el resto de hilos quedaría parado.
    """
    if not deepseek.disponible():
        raise SystemExit("Falta DEEPSEEK_API_KEY (en .env o como variable de entorno)")
    estados = ("pendiente", "error") if reintentar else ("pendiente",)
    cola = [e for e in registro.vigentes(registro.leer_registro())
            if (not ids or e["id"] in ids or e["base"] in ids) and (releer or e["estado"] in estados)
            and "escaneado" not in (e.get("motivo") or "")]
    if not cola:
        log("No hay programas pendientes de leer")
        return 0
    modelo = modelo or MODELO
    cerrojo = threading.Lock()  # el registro se reescribe entero: una actualización cada vez

    def uno(e):
        log(f"  {e['id']}: leyendo con {modelo} ({VERSION_PROMPT})")
        try:
            compromisos, t_in, t_out, descartados = _leer_programa(e, modelo, lambda m: log(f"  {e['id']}{m}"))
        except deepseek.ErrorIA as err:
            e.update(estado="error", motivo=f"{type(err).__name__}: {err}")
            with cerrojo:
                registro.actualizar_entrada(e)
            log(f"  ! {e['id']}: {err}")
            return
        if releer and ruta_compromisos(e["id"]).exists():  # la lectura anterior se conserva con su versión
            anterior = e.get("version_prompt") or "sin-version"
            ruta_compromisos(e["id"]).replace(registro.PROGRAMAS_DIR / f"{e['id']}.{anterior}.jsonl")
            e.setdefault("relecturas", []).append({"version_anterior": anterior, "fecha": date.today().isoformat(),
                                                   "compromisos": e.get("compromisos")})
        ruta_compromisos(e["id"]).write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in compromisos),
                                             encoding="utf-8")
        e.update(estado="leido", motivo=None, leido=date.today().isoformat(), modelo=compromisos[0]["modelo"] if compromisos else modelo,
                 version_prompt=VERSION_PROMPT, compromisos=len(compromisos),
                 verificables=sum(c["verificable"] for c in compromisos), descartados=descartados,
                 tokens_entrada=e.get("tokens_entrada", 0) + t_in, tokens_salida=e.get("tokens_salida", 0) + t_out)
        with cerrojo:
            registro.actualizar_entrada(e)
        log(f"  {e['id']}: {len(compromisos)} compromisos ({e['verificables']} verificables); "
            f"{descartados} descartados (la cita no está tal cual en el texto o falta algún campo)")

    with ThreadPoolExecutor(PROGRAMAS_A_LA_VEZ) as programas:
        list(programas.map(uno, cola[: limite or None]))
    return len(cola)


def rehacer_citas(ids=None, log=print):
    """Vuelve a comprobar las citas de los programas leídos con lo que DeepSeek ya respondió (la caché local de
    trozos), sin llamar a nada: sirve cuando mejora la comprobación. Los compromisos que ya estaban conservan su id
    (sale de la cita), así que sus emparejamientos siguen valiendo; los recuperados se emparejan como nuevos."""
    cambiados = 0
    for e in registro.vigentes(registro.leer_registro()):
        if e["estado"] != "leido" or (ids and e["id"] not in ids and e["base"] not in ids):
            continue
        try:
            compromisos, _t_in, _t_out, descartados = _leer_programa(e, None, lambda m: None, version=e.get("version_prompt") or VERSION_PROMPT,
                                                                   solo_cache=True)
        except deepseek.ErrorIA as err:
            log(f"  {e['id']}: {err}; se queda como estaba")
            continue
        if len(compromisos) <= (e.get("compromisos") or 0):
            continue
        ruta_compromisos(e["id"]).write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in compromisos),
                                             encoding="utf-8")
        antes = e.get("compromisos")
        e = next(x for x in registro.leer_registro() if x["id"] == e["id"])  # el registro puede haber cambiado
        e.update(compromisos=len(compromisos), verificables=sum(c["verificable"] for c in compromisos), descartados=descartados)
        registro.actualizar_entrada(e)
        cambiados += 1
        log(f"  {e['id']}: {antes} -> {len(compromisos)} compromisos; {descartados} siguen fuera")
    return cambiados


def rehacer_texto(ids, log=print):
    """Vuelve a extraer el texto de programas ya leídos (p. ej. separando las columnas, que en algunos PDF salían
    mezcladas) y comprueba contra el texto nuevo, entero, todas las respuestas guardadas en la caché local, sin
    llamar a DeepSeek. El texto versionado se sustituye: la página de cada cita sale del nuevo."""
    for e in registro.vigentes(registro.leer_registro()):
        if e["estado"] != "leido" or (e["id"] not in ids and e["base"] not in ids):
            continue
        pdf = registro.PDF_DIR / f"{e['base']}.pdf"
        if not pdf.exists():
            log(f"  {e['id']}: no está el PDF en la caché local (data/raw/programas/pdf/); se queda como estaba")
            continue
        nuevo = registro._pdf_a_texto(pdf.read_bytes())
        if nuevo == registro.texto(e["id"]):
            log(f"  {e['id']}: el texto no cambia")
            continue
        cache = registro.TEXTOS_DIR / "trozos" / e["id"] / (e.get("version_prompt") or VERSION_PROMPT)
        respuestas = [r for r in (json.loads(f.read_text(encoding="utf-8")) for f in sorted(cache.glob("*.json"))) if "compromisos" in r]
        paginas = _sin_cabeceras(nuevo.rstrip("\f").split("\f"))
        compromisos, usados = [], set()
        for r in respuestas:
            _anadir(e, r, paginas, 1, compromisos, usados)
        compromisos.sort(key=lambda c: c["pagina"])
        brutos = sum(len(r["compromisos"]) for r in respuestas)
        registro.ruta_texto(e["id"]).write_text(nuevo, encoding="utf-8")
        ruta_compromisos(e["id"]).write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in compromisos),
                                             encoding="utf-8")
        antes = e.get("compromisos")
        e = next(x for x in registro.leer_registro() if x["id"] == e["id"])  # el registro puede haber cambiado
        e.update(compromisos=len(compromisos), verificables=sum(c["verificable"] for c in compromisos),
                 descartados=brutos - len(compromisos), texto="columnas", caracteres=len(nuevo))
        registro.actualizar_entrada(e)
        log(f"  {e['id']}: texto rehecho; {antes} -> {len(compromisos)} compromisos; {brutos - len(compromisos)} siguen fuera")


def releer(id_, version, modelo=None, log=print):
    """Releer un programa ya leído: solo con la versión actual del prompt y dicha explícitamente."""
    if version != VERSION_PROMPT:
        raise SystemExit(f"La versión actual del prompt es {VERSION_PROMPT}: para releer con otra hay que cambiarla en el código")
    e = next((e for e in registro.vigentes(registro.leer_registro()) if id_ in (e["id"], e["base"])), None)
    if not e:
        raise SystemExit(f"{id_} no está en el registro")
    if e.get("version_prompt") == version and e["estado"] == "leido":
        raise SystemExit(f"{e['id']} ya está leído con {version}")
    return leer(ids=[e["id"]], modelo=modelo, releer=True, log=log)
