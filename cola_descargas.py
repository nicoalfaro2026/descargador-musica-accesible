import json
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from config import COLA_DESCARGAS_ARCHIVO


ESTADO_PENDIENTE = "Pendiente"
ESTADO_DESCARGANDO = "Descargando"
ESTADO_ERROR = "Error"

_LOCK = threading.RLock()


def _clave_url(url):
    """Devuelve una clave estable para evitar elementos duplicados en la cola."""
    texto = str(url or "").strip()
    if not texto:
        return ""
    try:
        parsed = urlparse(texto)
        host = (parsed.netloc or "").lower().split(":", 1)[0]
        path = parsed.path or ""
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if path == "/watch":
                video_id = (parse_qs(parsed.query).get("v") or [""])[0].strip()
                if video_id:
                    return f"youtube:{video_id}"
            partes = [p for p in path.split("/") if p]
            if len(partes) >= 2 and partes[0] in {"shorts", "embed", "live"}:
                return f"youtube:{partes[1]}"
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = path.strip("/").split("/", 1)[0]
            if video_id:
                return f"youtube:{video_id}"
        base = f"{host}{path}".rstrip("/")
        if parsed.query:
            base += f"?{parsed.query}"
        return base or texto
    except Exception:
        return texto


def _guardar_atomicamente(items):
    COLA_DESCARGAS_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    temporal = COLA_DESCARGAS_ARCHIVO.with_suffix(COLA_DESCARGAS_ARCHIVO.suffix + ".tmp")
    temporal.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(COLA_DESCARGAS_ARCHIVO)


def _leer_sin_error():
    if not COLA_DESCARGAS_ARCHIVO.exists():
        return []
    try:
        datos = json.loads(COLA_DESCARGAS_ARCHIVO.read_text(encoding="utf-8"))
        if not isinstance(datos, list):
            return []
        salida = []
        vistos = set()
        cambio = False
        for item in datos:
            if not isinstance(item, dict):
                cambio = True
                continue
            url = str(item.get("url") or "").strip()
            clave = str(item.get("clave") or _clave_url(url)).strip()
            if not url or not clave or clave in vistos:
                cambio = True
                continue
            copia = dict(item)
            copia["url"] = url
            copia["clave"] = clave
            if copia.get("estado") not in {ESTADO_PENDIENTE, ESTADO_DESCARGANDO, ESTADO_ERROR}:
                copia["estado"] = ESTADO_PENDIENTE
                cambio = True
            salida.append(copia)
            vistos.add(clave)
        if cambio:
            _guardar_atomicamente(salida)
        return salida
    except Exception:
        return []



def restablecer_descargas_interrumpidas():
    """Al iniciar el programa, devuelve a Pendiente cualquier entrada que quedó Descargando."""
    with _LOCK:
        items = _leer_sin_error()
        cambio = False
        for item in items:
            if item.get("estado") == ESTADO_DESCARGANDO:
                item["estado"] = ESTADO_PENDIENTE
                item["error"] = ""
                cambio = True
        if cambio:
            _guardar_atomicamente(items)
        return items


def leer_cola():
    """Devuelve la cola en el mismo orden en que se agregaron los elementos."""
    with _LOCK:
        return _leer_sin_error()


def esta_en_cola(url):
    clave = _clave_url(url)
    with _LOCK:
        return bool(clave) and any(item.get("clave") == clave for item in _leer_sin_error())


def agregar_a_cola(item):
    """Agrega un video. Devuelve 'agregado', 'duplicado' o 'error'."""
    if not isinstance(item, dict):
        return "error"
    url = str(item.get("url") or "").strip()
    clave = _clave_url(url)
    if not url or not clave:
        return "error"
    with _LOCK:
        items = _leer_sin_error()
        if any(existente.get("clave") == clave for existente in items):
            return "duplicado"
        nuevo = {
            "clave": clave,
            "url": url,
            "titulo": str(item.get("titulo") or item.get("title") or "Sin título"),
            "canal": str(item.get("canal") or item.get("uploader") or item.get("autor") or "No disponible"),
            "duracion_texto": str(item.get("duracion_texto") or ""),
            "estado": ESTADO_PENDIENTE,
            "error": "",
            "fecha_agregado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        for clave_extra in ("id", "webpage_url", "extractor_key"):
            if item.get(clave_extra):
                nuevo[clave_extra] = item.get(clave_extra)
        items.append(nuevo)
        _guardar_atomicamente(items)
        return "agregado"


def agregar_varios_a_cola(items):
    """Agrega varios videos con un único guardado.

    Devuelve un diccionario con agregados, duplicados y errores.
    """
    if not isinstance(items, (list, tuple)):
        return {"agregados": 0, "duplicados": 0, "errores": 1}

    with _LOCK:
        actuales = _leer_sin_error()
        claves = {item.get("clave") for item in actuales if item.get("clave")}
        agregados = 0
        duplicados = 0
        errores = 0

        for item in items:
            if not isinstance(item, dict):
                errores += 1
                continue
            url = str(item.get("url") or "").strip()
            clave = _clave_url(url)
            if not url or not clave:
                errores += 1
                continue
            if clave in claves:
                duplicados += 1
                continue

            nuevo = {
                "clave": clave,
                "url": url,
                "titulo": str(item.get("titulo") or item.get("title") or "Sin título"),
                "canal": str(item.get("canal") or item.get("uploader") or item.get("autor") or "No disponible"),
                "duracion_texto": str(item.get("duracion_texto") or ""),
                "estado": ESTADO_PENDIENTE,
                "error": "",
                "fecha_agregado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            for clave_extra in ("id", "webpage_url", "extractor_key"):
                if item.get(clave_extra):
                    nuevo[clave_extra] = item.get(clave_extra)
            actuales.append(nuevo)
            claves.add(clave)
            agregados += 1

        if agregados:
            _guardar_atomicamente(actuales)
        return {"agregados": agregados, "duplicados": duplicados, "errores": errores}


def quitar_de_cola(url):
    clave = _clave_url(url)
    if not clave:
        return False
    with _LOCK:
        items = _leer_sin_error()
        nuevos = [item for item in items if item.get("clave") != clave]
        if len(nuevos) == len(items):
            return False
        _guardar_atomicamente(nuevos)
        return True


def vaciar_cola():
    with _LOCK:
        _guardar_atomicamente([])
        return True


def actualizar_estado(url, estado, error=""):
    clave = _clave_url(url)
    if not clave:
        return False
    with _LOCK:
        items = _leer_sin_error()
        encontrado = False
        for item in items:
            if item.get("clave") == clave:
                item["estado"] = estado if estado in {ESTADO_PENDIENTE, ESTADO_DESCARGANDO, ESTADO_ERROR} else ESTADO_PENDIENTE
                item["error"] = str(error or "")
                encontrado = True
                break
        if encontrado:
            _guardar_atomicamente(items)
        return encontrado


def preparar_reintento_errores():
    with _LOCK:
        items = _leer_sin_error()
        cambio = False
        for item in items:
            if item.get("estado") == ESTADO_ERROR:
                item["estado"] = ESTADO_PENDIENTE
                item["error"] = ""
                cambio = True
        if cambio:
            _guardar_atomicamente(items)
        return items
