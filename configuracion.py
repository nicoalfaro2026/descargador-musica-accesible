import json
from datetime import datetime

from config import (
    CALIDAD_DEFECTO,
    CARPETA_DEFECTO,
    CONFIG_ARCHIVO,
    FORMATO_DEFECTO,
    FORMATOS_DISPONIBLES,
    RESULTADOS_BUSQUEDA_DISPONIBLES,
    opciones_calidad_para_formato,
)
from utils import carpeta_guardada_usable, normalizar_ruta_usuario

FRECUENCIAS_ACTUALIZACION = [
    "Nunca",
    "Al iniciar",
    "Cada día",
    "Cada semana",
    "Cada mes",
]

def _como_bool(valor, predeterminado=False):
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return bool(predeterminado)
    if isinstance(valor, (int, float)):
        return valor != 0
    texto = str(valor).strip().lower()
    if texto in {"1", "true", "sí", "si", "yes", "on", "activado"}:
        return True
    if texto in {"0", "false", "no", "off", "desactivado", ""}:
        return False
    return bool(predeterminado)


CONFIG_DEFECTO = {
    "carpeta": CARPETA_DEFECTO,
    "formato": FORMATO_DEFECTO,
    "calidad": CALIDAD_DEFECTO,
    "frecuencia_actualizaciones": "Cada semana",
    "ultima_revision_actualizaciones": "",
    "primera_revision_actualizaciones_realizada": False,
    "frecuencia_actualizaciones_motor": "Cada semana",
    "actualizar_motor_silenciosamente": False,
    "canal_actualizaciones_motor": "stable",
    "canal_motor_instalado": "stable",
    "ultima_revision_actualizaciones_motor": "",
    "primera_revision_actualizaciones_motor_realizada": False,
    "sonidos_activados": True,
    "sonido_inicio": True,
    "sonido_cierre": True,
    "sonido_descarga": True,
    "sonido_error": True,
    "reproductor_volumen_inicial": "50%",
    "reproductor_salto_segundos": "10 segundos",
    "reproductor_velocidad_inicial": "1.00",
    "reproductor_anunciar_posicion_al_pausar": False,
    "reproductor_dispositivo_salida": "auto",
    "busqueda_resultados_predeterminados": "100",
    "busqueda_preguntar_cantidad": False,
    "youtube_preferir_idioma_programa": True,
    "youtube_metodo_autenticacion": "ninguno",
    "youtube_archivo_cookies": "",
    # Compatibilidad con configuraciones 1.8.1 de prueba anteriores.
    "youtube_usar_cookies_respaldo": False,
    "youtube_navegador_cookies": "auto",
    "idioma": "es",
    "idioma_configurado": False,
}


def _normalizar_configuracion(datos):
    configuracion = dict(CONFIG_DEFECTO)

    if not isinstance(datos, dict):
        return configuracion

    carpeta_guardada = normalizar_ruta_usuario(datos.get("carpeta") or "")
    if not carpeta_guardada_usable(carpeta_guardada):
        carpeta_guardada = CARPETA_DEFECTO

    for clave in CONFIG_DEFECTO:
        if clave in datos:
            configuracion[clave] = datos[clave]

    configuracion["carpeta"] = carpeta_guardada

    # Booleanos explícitos para evitar que cadenas como "false" sean True.
    for clave in (
        "primera_revision_actualizaciones_realizada",
        "primera_revision_actualizaciones_motor_realizada",
        "actualizar_motor_silenciosamente",
        "sonidos_activados",
        "sonido_inicio",
        "sonido_cierre",
        "sonido_descarga",
        "sonido_error",
        "reproductor_anunciar_posicion_al_pausar",
        "busqueda_preguntar_cantidad",
        "youtube_preferir_idioma_programa",
        "youtube_usar_cookies_respaldo",
        "idioma_configurado",
    ):
        configuracion[clave] = _como_bool(datos.get(clave, configuracion[clave]), configuracion[clave])

    if configuracion["frecuencia_actualizaciones"] not in FRECUENCIAS_ACTUALIZACION:
        configuracion["frecuencia_actualizaciones"] = CONFIG_DEFECTO["frecuencia_actualizaciones"]

    if configuracion["frecuencia_actualizaciones_motor"] not in FRECUENCIAS_ACTUALIZACION:
        configuracion["frecuencia_actualizaciones_motor"] = CONFIG_DEFECTO["frecuencia_actualizaciones_motor"]

    canales_motor = {"stable", "nightly", "master"}
    canal_deseado = str(configuracion.get("canal_actualizaciones_motor", "stable") or "stable").strip().lower()
    if canal_deseado not in canales_motor:
        canal_deseado = "stable"
    configuracion["canal_actualizaciones_motor"] = canal_deseado

    canal_instalado = str(configuracion.get("canal_motor_instalado", "stable") or "stable").strip().lower()
    if canal_instalado not in canales_motor:
        canal_instalado = "stable"
    configuracion["canal_motor_instalado"] = canal_instalado

    if configuracion["formato"] not in FORMATOS_DISPONIBLES:
        configuracion["formato"] = FORMATO_DEFECTO

    calidades_validas = opciones_calidad_para_formato(configuracion["formato"])
    if configuracion["calidad"] not in calidades_validas:
        configuracion["calidad"] = calidades_validas[-1] if calidades_validas else CALIDAD_DEFECTO

    volumenes = [f"{n}%" for n in range(0, 101, 10)]
    # También permitimos valores intermedios guardados por los atajos del reproductor.
    try:
        volumen_num = int(str(configuracion["reproductor_volumen_inicial"]).replace("%", "").strip())
        if 0 <= volumen_num <= 100:
            configuracion["reproductor_volumen_inicial"] = f"{volumen_num}%"
        else:
            raise ValueError
    except Exception:
        configuracion["reproductor_volumen_inicial"] = CONFIG_DEFECTO["reproductor_volumen_inicial"]

    if configuracion["reproductor_salto_segundos"] not in ["5 segundos", "10 segundos", "15 segundos", "30 segundos"]:
        configuracion["reproductor_salto_segundos"] = CONFIG_DEFECTO["reproductor_salto_segundos"]

    if configuracion["reproductor_velocidad_inicial"] not in ["0.75", "1.00", "1.25", "1.50"]:
        configuracion["reproductor_velocidad_inicial"] = CONFIG_DEFECTO["reproductor_velocidad_inicial"]

    dispositivo = str(configuracion.get("reproductor_dispositivo_salida") or "auto").strip()
    configuracion["reproductor_dispositivo_salida"] = dispositivo or "auto"

    cantidad = str(configuracion.get("busqueda_resultados_predeterminados", "100"))
    if cantidad not in RESULTADOS_BUSQUEDA_DISPONIBLES:
        cantidad = CONFIG_DEFECTO["busqueda_resultados_predeterminados"]
    configuracion["busqueda_resultados_predeterminados"] = cantidad

    navegadores = {"auto", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"}
    navegador = str(configuracion.get("youtube_navegador_cookies", "auto") or "auto").strip().lower()
    if navegador not in navegadores:
        navegador = "auto"
    configuracion["youtube_navegador_cookies"] = navegador

    # Migración transparente desde la opción de respaldo por navegador usada en
    # compilaciones de prueba anteriores.
    metodo = str(configuracion.get("youtube_metodo_autenticacion", "ninguno") or "ninguno").strip().lower()
    if "youtube_metodo_autenticacion" not in datos and _como_bool(datos.get("youtube_usar_cookies_respaldo", False), False):
        metodo = "navegador"
    if metodo not in {"ninguno", "cookies_txt", "navegador"}:
        metodo = "ninguno"
    configuracion["youtube_metodo_autenticacion"] = metodo
    configuracion["youtube_archivo_cookies"] = str(configuracion.get("youtube_archivo_cookies", "") or "").strip()
    configuracion["youtube_usar_cookies_respaldo"] = metodo == "navegador"

    if configuracion.get("idioma") not in ["es", "en", "pt", "fr", "it", "ru"]:
        configuracion["idioma"] = CONFIG_DEFECTO["idioma"]

    return configuracion


def cargar_configuracion():
    if not CONFIG_ARCHIVO.exists():
        return dict(CONFIG_DEFECTO)

    try:
        with open(CONFIG_ARCHIVO, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
        return _normalizar_configuracion(datos)
    except Exception:
        return dict(CONFIG_DEFECTO)


def guardar_configuracion_completa(configuracion):
    try:
        CONFIG_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        datos = _normalizar_configuracion(configuracion)
        with open(CONFIG_ARCHIVO, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False, indent=4)
    except Exception:
        pass


def guardar_configuracion(carpeta, formato, calidad, opciones=None):
    datos = dict(CONFIG_DEFECTO)
    if isinstance(opciones, dict):
        datos.update(opciones)

    carpeta = normalizar_ruta_usuario(carpeta or "")
    if not carpeta_guardada_usable(carpeta):
        carpeta = CARPETA_DEFECTO

    datos.update({"carpeta": carpeta, "formato": formato, "calidad": calidad})
    guardar_configuracion_completa(datos)


def fecha_iso_hoy():
    return datetime.now().strftime("%Y-%m-%d")
