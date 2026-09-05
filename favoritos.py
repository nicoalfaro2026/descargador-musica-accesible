import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import FAVORITOS_ARCHIVO


def _clave_url(url):
    """Genera una clave estable para evitar favoritos duplicados."""
    texto = str(url or "").strip()
    if not texto:
        return ""

    try:
        parsed = urlparse(texto)
        host = (parsed.netloc or "").lower().split(":", 1)[0]
        path = parsed.path or ""

        # Normalizar las formas más habituales de una URL de YouTube.
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            consulta = parse_qs(parsed.query)
            if path == "/watch":
                video_id = (consulta.get("v") or [""])[0].strip()
                if video_id:
                    return f"youtube:{video_id}"
            playlist_id = (consulta.get("list") or [""])[0].strip()
            if playlist_id and path.rstrip("/") == "/playlist":
                return f"youtube-playlist:{playlist_id}"
            partes = [p for p in path.split("/") if p]
            if len(partes) >= 2 and partes[0] in {"shorts", "embed", "live"}:
                return f"youtube:{partes[1]}"
        if host in {"youtu.be", "www.youtu.be"}:
            video_id = path.strip("/").split("/", 1)[0]
            if video_id:
                return f"youtube:{video_id}"

        # Para otros sitios conservamos una forma simple y estable.
        base = f"{host}{path}".rstrip("/")
        if parsed.query:
            base += f"?{parsed.query}"
        return base or texto
    except Exception:
        return texto


def _leer_sin_error():
    if not FAVORITOS_ARCHIVO.exists():
        return []
    try:
        datos = json.loads(FAVORITOS_ARCHIVO.read_text(encoding="utf-8"))
        if not isinstance(datos, list):
            return []
        salida = []
        vistos = set()
        for item in datos:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            clave = str(item.get("clave") or _clave_url(url)).strip()
            if not url or not clave or clave in vistos:
                continue
            copia = dict(item)
            copia["url"] = url
            copia["clave"] = clave
            salida.append(copia)
            vistos.add(clave)
        return salida
    except Exception:
        return []


def _guardar_atomicamente(items):
    FAVORITOS_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    temporal = FAVORITOS_ARCHIVO.with_suffix(FAVORITOS_ARCHIVO.suffix + ".tmp")
    texto = json.dumps(items, ensure_ascii=False, indent=2)
    temporal.write_text(texto, encoding="utf-8")
    temporal.replace(FAVORITOS_ARCHIVO)


def leer_favoritos():
    """Devuelve los favoritos guardados, del más reciente al más antiguo."""
    items = _leer_sin_error()
    items.reverse()
    return items


def esta_en_favoritos(url):
    clave = _clave_url(url)
    if not clave:
        return False
    return any(item.get("clave") == clave for item in _leer_sin_error())


def agregar_favorito(item):
    """Agrega un elemento. Devuelve True si se agregó y False si ya existía."""
    if not isinstance(item, dict):
        return False
    url = str(item.get("url") or "").strip()
    clave = _clave_url(url)
    if not url or not clave:
        return False

    items = _leer_sin_error()
    if any(existente.get("clave") == clave for existente in items):
        return False

    nuevo = {
        "clave": clave,
        "url": url,
        "titulo": str(item.get("titulo") or item.get("title") or "Sin título"),
        "canal": str(item.get("canal") or item.get("uploader") or item.get("autor") or "No disponible"),
        "tipo": str(item.get("tipo_favorito") or "Video"),
        "duracion_texto": str(item.get("duracion_texto") or ""),
        "fecha_publicacion_texto": str(item.get("fecha_publicacion_texto") or item.get("fecha_texto") or ""),
        "visualizaciones_texto": str(item.get("visualizaciones_texto") or ""),
        "fecha_agregado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Conservar identificadores útiles sin guardar información sensible.
    for clave_extra in ("id", "webpage_url", "extractor_key"):
        if item.get(clave_extra):
            nuevo[clave_extra] = item.get(clave_extra)

    items.append(nuevo)
    _guardar_atomicamente(items)
    return True


def quitar_favorito(url):
    """Quita un elemento. Devuelve True si existía."""
    clave = _clave_url(url)
    if not clave:
        return False
    items = _leer_sin_error()
    nuevos = [item for item in items if item.get("clave") != clave]
    if len(nuevos) == len(items):
        return False
    _guardar_atomicamente(nuevos)
    return True


def alternar_favorito(item):
    """Alterna un favorito y devuelve 'agregado', 'quitado' o 'error'."""
    if not isinstance(item, dict):
        return "error"
    url = str(item.get("url") or "").strip()
    if not url:
        return "error"
    if esta_en_favoritos(url):
        return "quitado" if quitar_favorito(url) else "error"
    return "agregado" if agregar_favorito(item) else "error"
