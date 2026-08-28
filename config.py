import sys
from pathlib import Path

APP_NOMBRE = "Descargador de Música Accesible"
VERSION = "1.8.0"

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "datos"
LOGS_DIR = BASE_DIR / "logs"

CONFIG_ARCHIVO = DATA_DIR / "configuracion.json"
HISTORIAL_ARCHIVO = DATA_DIR / "historial.jsonl"
LOG_ARCHIVO = LOGS_DIR / "descargador.log"

from utils import obtener_carpeta_descargas_app

CARPETA_DEFECTO = obtener_carpeta_descargas_app()
FORMATO_DEFECTO = "MP3"
CALIDAD_DEFECTO = "320 kbps"
MAX_RESULTADOS_BUSQUEDA = 300
MAX_REGISTROS_HISTORIAL = 1000

FORMATOS_DISPONIBLES = ["MP3", "M4A", "AAC", "OPUS", "OGG", "WAV", "FLAC", "MP4"]
CALIDADES_AUDIO_CON_PERDIDA = ["128 kbps", "192 kbps", "256 kbps", "320 kbps"]
CALIDADES_AUDIO_SIN_PERDIDA = ["Mejor calidad disponible"]
RESOLUCIONES_VIDEO_DISPONIBLES = [
    "Mejor disponible",
    "Hasta 2160p (4K)",
    "Hasta 1440p",
    "Hasta 1080p",
    "Hasta 720p",
    "Hasta 480p",
    "Hasta 360p",
    "Hasta 240p",
    "Hasta 144p",
]
# Compatibilidad con código antiguo que todavía importe este nombre.
CALIDADES_DISPONIBLES = CALIDADES_AUDIO_CON_PERDIDA
RESULTADOS_BUSQUEDA_DISPONIBLES = ["20", "50", "75", "100", "150", "200", "300"]

FORMATOS_AUDIO_CON_PERDIDA = {"MP3", "M4A", "AAC", "OPUS", "OGG"}
FORMATOS_AUDIO_SIN_PERDIDA = {"WAV", "FLAC"}


def opciones_calidad_para_formato(formato):
    formato = str(formato or FORMATO_DEFECTO).upper()
    if formato == "MP4":
        return list(RESOLUCIONES_VIDEO_DISPONIBLES)
    if formato in FORMATOS_AUDIO_SIN_PERDIDA:
        return list(CALIDADES_AUDIO_SIN_PERDIDA)
    return list(CALIDADES_AUDIO_CON_PERDIDA)
