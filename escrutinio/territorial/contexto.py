"""Lo que reciben los conectores: descarga con caché en disco, texto de PDF, fechas y registro.

La caché (data/raw/territorial/<cuerpo>/, fuera de git) hace que repetir una descarga completa
no vuelva a pedir lo que ya se tiene. En GitHub Actions se empieza sin caché, así que los
conectores deben ser incrementales: pedir solo desde `ctx.desde(cuerpo)`.
"""

import gzip
import hashlib
import http.cookiejar
import os
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from ..config import RAW_DIR

CACHE_DIR = RAW_DIR / "territorial"
CERTIFICADOS = Path(__file__).with_name("certificados.pem")
UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36 escrutinio/0.2 (datos abiertos parlamentarios)")


class ErrorDescarga(RuntimeError):
    pass


# Webs que en esta ejecución no han respondido nunca y dos veces seguidas no han dejado ni conectar (se agota el
# tiempo, cortan o rechazan la conexión): suelen ser las que no aceptan conexiones desde fuera de España. Las
# peticiones siguientes a esas webs fallan en el acto, también las de otros Contexto (el listado de documentos).
_CAIDAS = {}    # host -> error
_VIVAS = set()  # hosts que han contestado algo en esta ejecución


def _sin_conexion(e):
    """¿Falló antes de que la web contestara nada? (no un certificado, ni un tiempo agotado leyendo la respuesta)"""
    if isinstance(e, urllib.error.URLError):
        e = e.reason  # urllib envuelve así los errores al conectar
    elif not isinstance(e, ConnectionError):  # «Remote end closed connection without response» llega sin envolver
        return False
    return isinstance(e, (TimeoutError, ConnectionError, socket.gaierror))


def contexto_tls():
    """TLS con los intermedios que algunas webs no envían (certificados.pem): Windows los completa por su
    cuenta, pero en Linux (GitHub Actions) sin ellos la verificación falla. El mismo fichero trae alguna
    raíz reciente que los almacenes de confianza aún no incluyen."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=CERTIFICADOS)
    ctx.verify_flags |= getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    return ctx


_PDFTOTEXT = []


def _pdftotext():
    """El pdftotext de poppler si hay varios en el PATH (Git para Windows trae uno de xpdf que
    desordena las columnas con -layout); si no, el primero que haya."""
    if not _PDFTOTEXT:
        candidatos = []
        for carpeta in os.environ.get("PATH", "").split(os.pathsep):
            for nombre in ("pdftotext", "pdftotext.exe"):
                p = Path(carpeta) / nombre
                if p.is_file() and str(p) not in candidatos:
                    candidatos.append(str(p))
        elegido = candidatos[0] if candidatos else None
        for c in candidatos:
            try:
                r = subprocess.run([c, "-v"], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                continue
            if b"poppler" in (r.stdout + r.stderr).lower():
                elegido = c
                break
        _PDFTOTEXT.append(elegido)
    return _PDFTOTEXT[0]


class Contexto:
    def __init__(self, desde=None, completo=False, limite=None, log=print, pausa=0.3):
        self._desde = desde or {}       # cuerpo -> fecha ISO de la última votación guardada
        self.completo = completo        # ignora `desde` y lo recorre todo
        self.limite = limite            # máximo de votaciones (para probar un conector)
        self.log = log
        self.pausa = pausa              # segundos entre peticiones que no salen de la caché
        self.avisos = {}                # cuerpo -> (motivo, detalle): la fuente respondió a medias
        self._abridores = {}

    def aviso(self, cuerpo, motivo, detalle):
        """Anota que la fuente no se pudo usar del todo (ver territorial/estado.py); la web lo avisa."""
        self.avisos[cuerpo] = (motivo, detalle)

    # ------------------------------------------------------------------ fechas

    def desde(self, cuerpo, margen_dias=21):
        """Fecha desde la que hay que pedir (con margen, por si se publicó tarde o incompleto).

        None si no hay nada guardado o se pidió una recogida completa.
        """
        if self.completo or not self._desde.get(cuerpo):
            return None
        return (date.fromisoformat(self._desde[cuerpo]) - timedelta(days=margen_dias)).isoformat()

    # ------------------------------------------------------------------ caché

    def carpeta(self, cuerpo):
        p = CACHE_DIR / cuerpo
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------ descarga

    def _abridor(self, inseguro):
        if inseguro not in self._abridores:
            manejadores = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
            if inseguro:  # webs con el certificado caducado o mal encadenado
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            else:
                ctx = contexto_tls()
            manejadores.append(urllib.request.HTTPSHandler(context=ctx))
            self._abridores[inseguro] = urllib.request.build_opener(*manejadores)
        return self._abridores[inseguro]

    def fetch(self, url, cache=None, data=None, headers=None, reintentos=4, timeout=60, inseguro=False,
              caduca_dias=None, reintentar_404=False):
        """Descarga una URL y devuelve bytes.

        - `cache`: ruta (Path o relativa a CACHE_DIR) donde guardar la respuesta comprimida. Si ya
          existe, se devuelve sin pedirla (salvo que tenga más de `caduca_dias`).
        - `data`: dict para POST de formulario, o bytes para un cuerpo ya codificado.
        - `inseguro`: no verificar el certificado TLS.
        - `reintentar_404`: para servidores que dan 404 al azar; si no, un 404 lanza HTTPError en el acto.
        El resto de errores se reintenta, salvo en una web que no ha contestado nada en esta ejecución y dos
        veces seguidas no deja conectar: se da por caída (ver _CAIDAS).
        """
        ruta = None
        if cache is not None:
            ruta = Path(cache) if Path(cache).is_absolute() else CACHE_DIR / cache
            if ruta.suffix != ".gz":
                ruta = ruta.with_name(ruta.name + ".gz")
            if ruta.exists() and not (caduca_dias is not None and time.time() - ruta.stat().st_mtime > caduca_dias * 86400):
                return gzip.decompress(ruta.read_bytes())
        cuerpo = None
        if isinstance(data, dict):
            cuerpo = urllib.parse.urlencode(data).encode()
        elif data is not None:
            cuerpo = data
        cab = {"User-Agent": UA_NAVEGADOR, "Accept-Encoding": "gzip", "Accept": "*/*",
               "Accept-Language": "es-ES,es;q=0.9"}
        if isinstance(data, dict):
            cab["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        cab.update(headers or {})
        host = urllib.parse.urlsplit(url).hostname
        if host in _CAIDAS:
            raise ErrorDescarga(f"No se pudo descargar {url}: {host} no ha respondido en esta ejecución "
                                f"({_CAIDAS[host]})") from _CAIDAS[host]
        ultimo, raw, sin_conexion = None, None, 0
        for intento in range(reintentos):
            try:
                req = urllib.request.Request(url, data=cuerpo, headers=cab)
                with self._abridor(inseguro).open(req, timeout=timeout) as r:
                    _VIVAS.add(host)
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                break
            except urllib.error.HTTPError as e:
                _VIVAS.add(host)
                if e.code in (401, 403, 410) or (e.code == 404 and (not reintentar_404 or intento == reintentos - 1)):
                    raise
                ultimo = e
            except Exception as e:  # red, timeouts, gzip truncado
                raw, ultimo = None, e
                if host not in _VIVAS and _sin_conexion(e):
                    sin_conexion += 1
                    if sin_conexion >= 2:  # no se insiste: cada intento puede ser un minuto de espera
                        _CAIDAS[host] = e
                        break
            time.sleep(1.5 * (intento + 1))
        if raw is None:
            raise ErrorDescarga(f"No se pudo descargar {url}: {ultimo}") from ultimo
        if ruta is not None:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(gzip.compress(raw))
        if self.pausa:
            time.sleep(self.pausa)
        return raw

    def texto(self, url, cache=None, encoding="utf-8", **kw):
        return self.fetch(url, cache=cache, **kw).decode(encoding, "replace")

    @staticmethod
    def clave(texto):
        """Nombre de fichero corto y estable para una URL o texto largo."""
        return hashlib.sha1(texto.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------ PDF

    @staticmethod
    def pdf_texto(pdf, layout=True, raw=False):
        """Texto de un PDF (bytes). Usa pdftotext (mejor el de poppler) si está instalado; si no, pypdf.

        `layout` conserva la disposición en columnas; `raw`, el orden del flujo de contenido (lo mejor
        para tablas que pdftotext -layout mezcla).
        """
        exe = _pdftotext()
        if exe:
            with tempfile.TemporaryDirectory() as tmp:
                entrada = Path(tmp) / "doc.pdf"
                entrada.write_bytes(pdf)
                modo = ["-raw"] if raw else ["-layout"] if layout else []
                args = [exe, "-enc", "UTF-8"] + modo + [str(entrada), "-"]
                r = subprocess.run(args, capture_output=True, timeout=300)
                if r.returncode == 0:
                    return r.stdout.decode("utf-8", "replace")
        try:
            import io

            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("Para leer PDF hace falta pdftotext (poppler-utils) o pypdf (pip install pypdf)") from e
        lector = PdfReader(io.BytesIO(pdf))
        modo = {"extraction_mode": "layout"} if layout else {}
        return "\n".join((p.extract_text(**modo) or "") for p in lector.pages)
