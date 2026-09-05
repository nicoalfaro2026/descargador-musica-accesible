from pathlib import Path
import os
import platform
import re
import subprocess
from datetime import datetime
import sys


def formato_duracion(segundos):
    try:
        segundos = int(segundos or 0)
    except (TypeError, ValueError):
        return "No disponible"

    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    seg = segundos % 60

    if horas:
        return f"{horas:02d}:{minutos:02d}:{seg:02d}"

    return f"{minutos:02d}:{seg:02d}"


def formato_fecha_yt(fecha):
    if not fecha:
        return "No disponible"

    try:
        return datetime.strptime(str(fecha), "%Y%m%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(fecha)


def formato_numero(valor):
    if valor is None:
        return "No disponible"

    try:
        return f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


def formato_tamano(bytes_valor):
    if not bytes_valor:
        return "desconocido"

    try:
        bytes_valor = float(bytes_valor)
    except (TypeError, ValueError):
        return "desconocido"

    unidades = ["B", "KB", "MB", "GB", "TB"]
    indice = 0

    while bytes_valor >= 1024 and indice < len(unidades) - 1:
        bytes_valor /= 1024
        indice += 1

    return f"{bytes_valor:.1f} {unidades[indice]}"


def formato_velocidad(bytes_por_segundo):
    if not bytes_por_segundo:
        return "velocidad desconocida"

    return f"{formato_tamano(bytes_por_segundo)}/s"


def formato_eta(segundos):
    if segundos is None:
        return "ETA desconocido"

    try:
        segundos = int(segundos)
    except (TypeError, ValueError):
        return "ETA desconocido"

    minutos = segundos // 60
    seg = segundos % 60

    if minutos:
        return f"{minutos} min {seg} s"

    return f"{seg} s"


def abrir_carpeta(ruta):
    sistema = platform.system().lower()

    if sistema == "windows":
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sistema == "darwin":
        subprocess.Popen(["open", ruta])
    else:
        subprocess.Popen(["xdg-open", ruta])


def limpiar_texto_consola(texto):
    """Quita colores/códigos ANSI de errores de consola para mostrar mensajes limpios."""
    texto = str(texto or "")
    texto = re.sub(r"\x1b\[[0-9;]*m", "", texto)
    texto = re.sub(r"\[0;31m|\[0m", "", texto)
    return texto.strip()



def normalizar_ruta_usuario(ruta):
    """Expande variables de entorno y devuelve una ruta absoluta legible."""
    if not ruta:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(ruta))))


def carpeta_guardada_usable(carpeta):
    """
    Evita que el programa conserve una carpeta de otra computadora o de otro usuario.

    Esto es importante cuando se comparte el programa ya probado: si por accidente viaja
    un archivo de configuración, la carpeta de descargas se recalcula para el usuario
    actual en vez de usar una ruta vieja como C:/Users/otro_usuario/...
    """
    carpeta = normalizar_ruta_usuario(carpeta)

    if not carpeta:
        return False

    sistema = platform.system().lower()

    if sistema == "windows":
        try:
            home_actual = normalizar_ruta_usuario(os.path.expanduser("~"))
            raiz_usuarios = os.path.dirname(home_actual)
            carpeta_lower = carpeta.lower()
            home_lower = home_actual.lower()
            raiz_lower = raiz_usuarios.lower().rstrip("\\/") + os.sep.lower()

            if carpeta_lower.startswith(raiz_lower) and not (
                carpeta_lower == home_lower or carpeta_lower.startswith(home_lower.rstrip("\\/") + os.sep.lower())
            ):
                return False
        except Exception:
            pass

    # Si la ruta no existe, intentamos crearla. Si no se puede crear, no sirve.
    try:
        os.makedirs(carpeta, exist_ok=True)
        return os.path.isdir(carpeta)
    except Exception:
        return False

def obtener_carpeta_musica():
    """Devuelve la carpeta Música real del usuario en Windows; si falla, usa ~/Music."""
    sistema = platform.system().lower()

    if sistema == "windows":
        try:
            import ctypes
            from ctypes import wintypes

            # FOLDERID_Music = 4BD8D571-6D19-48D3-BE97-422220080E43
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            folderid_music = GUID(
                0x4BD8D571,
                0x6D19,
                0x48D3,
                (wintypes.BYTE * 8)(0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43),
            )

            path_ptr = ctypes.c_wchar_p()
            hr = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folderid_music),
                0,
                None,
                ctypes.byref(path_ptr),
            )
            if hr == 0 and path_ptr.value:
                ruta = path_ptr.value
                try:
                    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                except Exception:
                    pass
                return ruta
        except Exception:
            pass

    return os.path.join(os.path.expanduser("~"), "Music")


def obtener_carpeta_descargas_app():
    ruta = os.path.join(obtener_carpeta_musica(), "Descargador de Música Accesible")
    try:
        os.makedirs(ruta, exist_ok=True)
    except Exception:
        pass
    return ruta


def sanitizar_nombre_carpeta(nombre, predeterminado="Descarga"):
    """Devuelve un nombre seguro para crear carpetas en Windows y otros sistemas."""
    nombre = str(nombre or "").strip()
    if not nombre:
        nombre = predeterminado

    # Caracteres prohibidos por Windows: \ / : * ? " < > |
    nombre = re.sub(r'[\\/:*?"<>|]+', ' ', nombre)
    nombre = re.sub(r'\s+', ' ', nombre).strip().strip('.')

    # Evita nombres demasiado largos y nombres vacíos después de limpiar.
    if not nombre:
        nombre = predeterminado

    return nombre[:120].strip() or predeterminado


def limpiar_archivos_obsoletos_instalacion():
    """Elimina restos conocidos de versiones/pruebas antiguas en modo empaquetado.

    Nunca toca datos, logs, descargas ni archivos del usuario. En desarrollo no
    hace nada, para no borrar herramientas del proyecto fuente.
    """
    if not getattr(sys, "frozen", False):
        return []

    base = Path(sys.executable).resolve().parent
    eliminados = []
    patrones = [
        "NOTAS_VERSION_*.txt",
        "NOTAS_PRUEBA_ACTUALIZADOR_*.txt",
    ]
    nombres = [
        "LEEME_PRUEBA_Y_EMPAQUETADO.txt",
        "ABRIR_EXE_PRUEBA.bat",
        "EMPAQUETAR_MODO_PRUEBA.bat",
        "DescargadorAccesible_PRUEBA.spec",
        "INSTALAR_REPRODUCTOR_INTERNO.bat",
        "nvdaControllerClient.dll",
        "nvdaControllerClient32.dll",
    ]

    objetivos = []
    for carpeta in (base, base / "_internal"):
        for patron in patrones:
            objetivos.extend(carpeta.glob(patron))
        objetivos.extend(carpeta / nombre for nombre in nombres)

    for ruta in objetivos:
        try:
            if ruta.is_file():
                ruta.unlink()
                eliminados.append(ruta.name)
        except Exception:
            pass

    cache = base / "__pycache__"
    if cache.exists() and cache.is_dir():
        try:
            import shutil
            shutil.rmtree(cache, ignore_errors=True)
            eliminados.append("__pycache__/")
        except Exception:
            pass

    return eliminados
