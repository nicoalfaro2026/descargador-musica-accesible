import os
import platform
import sys
from pathlib import Path


def _base_candidates():
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(sys.executable).resolve().parent)
    try:
        candidatos.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidatos.append(Path(meipass))
    return candidatos


def ruta_sonido(nombre):
    if not nombre:
        return None
    nombre = str(nombre)
    if not nombre.lower().endswith(".wav"):
        nombre += ".wav"
    for base in _base_candidates():
        for carpeta in (
            base,
            base / "sonidos",
            base / "_internal",
            base / "_internal" / "sonidos",
        ):
            ruta = carpeta / nombre
            if ruta.exists():
                return str(ruta)
    return None


def reproducir_sonido(nombre, esperar=False):
    """Reproduce un sonido WAV corto si está disponible.

    No lanza errores si el sistema no tiene soporte o si falta el archivo.
    En Windows usa winsound, que no requiere dependencias externas.
    """
    ruta = ruta_sonido(nombre)
    if not ruta:
        return False

    if platform.system().lower() == "windows":
        try:
            import winsound
            flags = winsound.SND_FILENAME
            if not esperar:
                flags |= winsound.SND_ASYNC
            winsound.PlaySound(ruta, flags)
            return True
        except Exception:
            return False

    # Fallback simple para otros sistemas. El programa está pensado para Windows,
    # pero dejamos esto sin romper compatibilidad.
    try:
        if sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["afplay", ruta], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        else:
            import subprocess
            subprocess.Popen(["aplay", ruta], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        return False
