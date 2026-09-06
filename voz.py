import ctypes
import os
import platform
import queue
import sys
import threading
import time
from pathlib import Path

_cola_voz = queue.Queue()
_worker_iniciado = False
_lock = threading.Lock()
_ultimo_texto = ""
_ultimo_tiempo = 0.0
_metodo_activo = "sin iniciar"
_ultimo_error = ""
_nvda = None
_nvda_probado = False
_nvda_ultimo_intento = 0.0
_jaws = None
_jaws_probado = False
_jaws_ultimo_intento = 0.0
_NVDA_REINTENTO_SEGUNDOS = 3.0


def _windows():
    return platform.system().lower() == "windows"


def _posibles_dll_nvda():
    bits = "64" if sys.maxsize > 2**32 else "32"
    nombres = [
        f"nvdaControllerClient{bits}.dll",
        "nvdaControllerClient.dll",
        "nvdaControllerClient64.dll",
        "nvdaControllerClient32.dll",
    ]

    carpetas = []
    bases = []
    try:
        bases.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    bases.append(Path.cwd())

    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, "_MEIPASS"):
            bases.append(Path(sys._MEIPASS))

    for base in bases:
        carpetas.append(base)
        # Soporte para la estructura oficial del ZIP de NVDA Controller Client.
        carpetas.append(base / "x64")
        carpetas.append(base / "x86")
        carpetas.append(base / "nvda_controller_client")
        carpetas.append(base / "nvda_controller_client" / "x64")
        carpetas.append(base / "nvda_controller_client" / "x86")

    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        valor = os.environ.get(variable)
        if valor:
            carpetas.append(Path(valor) / "NVDA")
            carpetas.append(Path(valor) / "NVDA" / "lib")

    nvda_home = os.environ.get("NVDA_HOME")
    if nvda_home:
        carpetas.append(Path(nvda_home))

    vistos = set()
    for carpeta in carpetas:
        for nombre in nombres:
            ruta = carpeta / nombre
            clave = str(ruta).lower()
            if clave not in vistos:
                vistos.add(clave)
                yield ruta


def _cargar_nvda():
    global _nvda, _nvda_probado, _ultimo_error, _nvda_ultimo_intento

    if _nvda is not None:
        return _nvda

    # Si ya se intentó antes y falló, no lo dejamos cacheado para siempre:
    # NVDA puede tardar unos segundos más en arrancar que el programa, o el
    # usuario puede iniciarlo después. Se reintenta pasado un breve
    # enfriamiento en vez de resignarse a usar otra voz durante toda la
    # sesión.
    ahora = time.time()
    if _nvda_probado and (ahora - _nvda_ultimo_intento) < _NVDA_REINTENTO_SEGUNDOS:
        return None

    _nvda_probado = True
    _nvda_ultimo_intento = ahora

    if not _windows():
        _ultimo_error = "NVDA directo solo está disponible en Windows."
        return None

    for ruta in _posibles_dll_nvda():
        if not ruta.exists():
            continue
        try:
            dll = ctypes.WinDLL(str(ruta))
            dll.nvdaController_testIfRunning.restype = ctypes.c_int
            dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            dll.nvdaController_speakText.restype = ctypes.c_int
            try:
                dll.nvdaController_cancelSpeech.restype = ctypes.c_int
            except Exception:
                pass

            if dll.nvdaController_testIfRunning() == 0:
                _nvda = dll
                _ultimo_error = f"NVDA detectado con {ruta.name}."
                return _nvda
            _ultimo_error = "La DLL de NVDA existe, pero NVDA no parece estar ejecutándose."
        except Exception as e:
            _ultimo_error = f"No se pudo usar la DLL de NVDA: {e}"
            continue

    if not _ultimo_error:
        _ultimo_error = "No se encontró nvdaControllerClient64.dll o nvdaControllerClient32.dll junto al programa."
    return None


def _hablar_nvda(texto, limpiar=False):
    dll = _cargar_nvda()
    if dll is None:
        return False
    try:
        if limpiar and hasattr(dll, "nvdaController_cancelSpeech"):
            try:
                dll.nvdaController_cancelSpeech()
            except Exception:
                pass
        resultado = dll.nvdaController_speakText(str(texto))
        return resultado == 0
    except Exception as e:
        global _ultimo_error
        _ultimo_error = f"Error hablando con NVDA: {e}"
        return False


def _jaws_esta_ejecutandose():
    """Detecta la ventana principal de JAWS sin iniciarlo ni hablar con él."""
    if not _windows():
        return False
    try:
        return bool(ctypes.windll.user32.FindWindowW("JFWUI2", None))
    except Exception:
        return False


def _cargar_jaws():
    global _jaws, _jaws_probado, _ultimo_error, _jaws_ultimo_intento

    if _jaws is not None:
        return _jaws

    # Mismo criterio que con NVDA: si falló, se reintenta pasado un breve
    # enfriamiento en vez de resignarse a no volver a probar en la sesión.
    ahora = time.time()
    if _jaws_probado and (ahora - _jaws_ultimo_intento) < _NVDA_REINTENTO_SEGUNDOS:
        return None

    _jaws_probado = True
    _jaws_ultimo_intento = ahora

    if not _windows():
        return None

    if not _jaws_esta_ejecutandose():
        _ultimo_error = "JAWS no parece estar en ejecución."
        return None

    try:
        import comtypes.client
        objeto = comtypes.client.CreateObject("FreedomSci.JawsApi")
        _jaws = objeto
        _ultimo_error = "JAWS detectado."
        return _jaws
    except Exception as e:
        _ultimo_error = f"JAWS está en ejecución, pero no se pudo conectar con su API: {e}"
        return None


def _hablar_jaws(texto, limpiar=False):
    objeto = _cargar_jaws()
    if objeto is None:
        return False
    try:
        resultado = objeto.SayString(str(texto), 1 if limpiar else 0)
        return bool(resultado)
    except Exception as e:
        global _ultimo_error
        _ultimo_error = f"Error hablando con JAWS: {e}"
        return False


def _beep_respaldo():
    if not _windows():
        return
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def _vaciar_cola():
    try:
        while True:
            _cola_voz.get_nowait()
    except queue.Empty:
        pass


def _trabajador_voz():
    global _metodo_activo

    while True:
        item = _cola_voz.get()
        if item is None:
            break

        texto, limpiar = item
        texto = str(texto or "").strip()
        if not texto:
            continue

        # 1) NVDA directo, solo si está disponible. Así no se mezcla con otra voz.
        if _hablar_nvda(texto, limpiar=limpiar):
            _metodo_activo = "NVDA"
            continue

        # 2) JAWS directo, solo si está disponible.
        if _hablar_jaws(texto, limpiar=limpiar):
            _metodo_activo = "JAWS"
            continue

        # El programa depende únicamente de lectores de pantalla (NVDA o
        # JAWS): si ninguno está en ejecución, no se usa ninguna voz propia
        # de Windows como respaldo.
        _metodo_activo = "beep/consola"
        _beep_respaldo()
        print(texto)


def _asegurar_worker():
    global _worker_iniciado

    with _lock:
        if _worker_iniciado:
            return
        hilo = threading.Thread(target=_trabajador_voz, daemon=True)
        hilo.start()
        _worker_iniciado = True


def hablar_async(texto, limpiar=False, preferir_nvda=True):
    """Anuncia un mensaje de forma accesible sin bloquear la interfaz."""
    global _ultimo_texto, _ultimo_tiempo

    try:
        from i18n import traducir_dinamico
        texto = traducir_dinamico(texto)
    except Exception:
        pass

    texto = str(texto or "").strip()
    if not texto:
        return

    ahora = time.time()
    if texto == _ultimo_texto and (ahora - _ultimo_tiempo) < 0.8:
        return

    _ultimo_texto = texto
    _ultimo_tiempo = ahora

    _asegurar_worker()
    if limpiar:
        _vaciar_cola()
    _cola_voz.put((texto, limpiar))


def hablar_cierre(texto, limpiar=True):
    """Anuncia la despedida de forma fiable antes de terminar el proceso.

    Se entrega el texto directamente al lector de pantalla activo (NVDA o
    JAWS). Si ninguno está en ejecución, no se anuncia con ninguna voz
    propia de Windows: el programa depende únicamente del lector de
    pantalla de la persona usuaria.
    """
    global _ultimo_texto, _ultimo_tiempo, _metodo_activo

    try:
        from i18n import traducir_dinamico
        texto = traducir_dinamico(texto)
    except Exception:
        pass

    texto = str(texto or "").strip()
    if not texto:
        return False

    _ultimo_texto = texto
    _ultimo_tiempo = time.time()

    # NVDA conserva el anuncio aunque la ventana se destruya inmediatamente.
    if _hablar_nvda(texto, limpiar=limpiar):
        _metodo_activo = "NVDA"
        return True

    # JAWS también conserva el anuncio aunque la ventana se destruya.
    if _hablar_jaws(texto, limpiar=limpiar):
        _metodo_activo = "JAWS"
        return True

    _metodo_activo = "beep/consola"
    _beep_respaldo()
    print(texto)
    return False


def metodo_activo_voz():
    return _metodo_activo


def diagnostico_voz():
    """Devuelve un resumen localizado para mostrar al usuario en caso de fallos de voz."""
    try:
        from i18n import traducir, traducir_dinamico, traducir_formato
    except Exception:
        traducir = lambda x: x
        traducir_dinamico = lambda x: x
        traducir_formato = lambda x, **kw: str(x).format(**kw)

    dlls = []
    for ruta in _posibles_dll_nvda():
        if ruta.exists():
            dlls.append(str(ruta))
    if not dlls:
        dlls.append(traducir("No se encontró DLL de NVDA junto al programa."))

    metodo = traducir_dinamico(_metodo_activo)
    detalle = traducir_dinamico(_ultimo_error or traducir("Sin errores registrados"))
    jaws_estado = traducir("Sí") if _jaws_esta_ejecutandose() else traducir("No")

    return "\n".join([
        traducir_formato("Método activo: {metodo}", metodo=metodo),
        traducir_formato("Último detalle/error: {detalle}", detalle=detalle),
        traducir_formato("Windows: {valor}", valor=_windows()),
        traducir_formato("JAWS en ejecución: {valor}", valor=jaws_estado),
        traducir("DLL NVDA detectadas:") + "\n- " + "\n- ".join(dlls),
    ])
