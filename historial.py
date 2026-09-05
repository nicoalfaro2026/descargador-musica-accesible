import json
from collections import deque

from config import HISTORIAL_ARCHIVO, MAX_REGISTROS_HISTORIAL


def _registros_validos_desde_archivo(limite=None):
    if not HISTORIAL_ARCHIVO.exists():
        return []

    maxlen = None
    if limite is not None:
        try:
            maxlen = max(1, int(limite))
        except Exception:
            maxlen = 100

    registros = deque(maxlen=maxlen)
    try:
        with open(HISTORIAL_ARCHIVO, "r", encoding="utf-8") as archivo:
            for linea in archivo:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    registro = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                if isinstance(registro, dict):
                    registros.append(registro)
    except Exception:
        return []
    return list(registros)


def limitar_historial(maximo=MAX_REGISTROS_HISTORIAL):
    """Conserva solo los registros más recientes para que el historial no crezca sin límite."""
    try:
        maximo = max(1, int(maximo))
        registros = _registros_validos_desde_archivo(maximo)
        HISTORIAL_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORIAL_ARCHIVO, "w", encoding="utf-8") as archivo:
            for registro in registros:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return len(registros)
    except Exception:
        return 0


def agregar_descarga(registro):
    try:
        HISTORIAL_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORIAL_ARCHIVO, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        # 1000 líneas son pequeñas; recortar aquí mantiene el archivo acotado
        # incluso si el usuario nunca abre la ventana de historial.
        limitar_historial(MAX_REGISTROS_HISTORIAL)
    except Exception:
        pass


def leer_historial(limite=100):
    registros = _registros_validos_desde_archivo(limite)
    registros.reverse()
    return registros


def limpiar_historial():
    """Vacía únicamente el registro; nunca elimina archivos descargados."""
    try:
        HISTORIAL_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        HISTORIAL_ARCHIVO.write_text("", encoding="utf-8")
        return True
    except Exception:
        return False
