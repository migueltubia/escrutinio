import gzip
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import USER_AGENT


def fetch(url, data=None, retries=5, timeout=60):
    """GET (o POST si hay `data`) con reintentos y soporte gzip. Devuelve bytes."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
        "Accept": "*/*",
    }
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
    last = None
    for intento in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # red, timeouts, gzip truncado
            last = e
        time.sleep(1.5 * (intento + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {last}")
