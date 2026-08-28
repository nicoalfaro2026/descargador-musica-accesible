import ctypes
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

_cola_voz = queue.Queue()
_worker_iniciado = False
_lock = threading.Lock()
_ultimo_texto = ""
_ultimo_tiempo = 0.0
_metodo_activo = "sin iniciar"
_ultimo_error = ""
_nvda = None
_nvda_probado = False

NOMBRES_VOZ_PREFERIDOS = ["Elena", "Helena", "Spanish", "Español", "Espanol"]


def _windows():
    return platform.system().lower() == "windows"


def _startupinfo_oculto():
    if not _windows():
        return None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return startupinfo
    except Exception:
        return None


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
    global _nvda, _nvda_probado, _ultimo_error

    if _nvda_probado:
        return _nvda

    _nvda_probado = True

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


def _vbs_literal(texto):
    # Literal VBScript: "texto" con comillas duplicadas.
    return '"' + str(texto).replace('"', '""') + '"'


def _hablar_vbs_sapi(texto):
    """Usa SAPI de Windows mediante Windows Script Host. Suele ser más estable que PowerShell."""
    global _ultimo_error

    if not _windows():
        return False

    wscript = shutil.which("wscript.exe") or shutil.which("cscript.exe")
    if not wscript:
        _ultimo_error = "No se encontró wscript.exe ni cscript.exe para voz SAPI."
        return False

    texto_lit = _vbs_literal(texto)
    script = f'''
On Error Resume Next
Set sapi = CreateObject("SAPI.SpVoice")
If Err.Number <> 0 Then WScript.Quit 2
For Each voz In sapi.GetVoices
    nombre = LCase(voz.GetDescription)
    If InStr(nombre, "elena") > 0 Or InStr(nombre, "helena") > 0 Then
        Set sapi.Voice = voz
        Exit For
    End If
Next
If sapi.Voice Is Nothing Then
    For Each voz In sapi.GetVoices
        nombre = LCase(voz.GetDescription)
        If InStr(nombre, "spanish") > 0 Or InStr(nombre, "español") > 0 Or InStr(nombre, "espanol") > 0 Then
            Set sapi.Voice = voz
            Exit For
        End If
    Next
End If
sapi.Rate = 0
sapi.Volume = 100
sapi.Speak {texto_lit}, 0
Set sapi = Nothing
'''

    ruta = None
    try:
        fd, ruta = tempfile.mkstemp(prefix="descargador_voz_", suffix=".vbs", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        subprocess.run(
            [wscript, "//B", ruta],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=_startupinfo_oculto(),
            timeout=45,
            check=False,
        )
        return True
    except Exception as e:
        _ultimo_error = f"Error usando SAPI por VBScript: {e}"
        return False
    finally:
        if ruta:
            try:
                os.remove(ruta)
            except Exception:
                pass


def _ps_literal(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _hablar_powershell(texto):
    global _ultimo_error

    if not _windows():
        return False

    exe = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        _ultimo_error = "No se encontró PowerShell para voz SAPI."
        return False

    texto_lit = _ps_literal(texto)
    script = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voz = $s.GetInstalledVoices() | Where-Object {{ $_.Enabled -and ($_.VoiceInfo.Name -match 'Elena|Helena') }} | Select-Object -First 1
if (-not $voz) {{ $voz = $s.GetInstalledVoices() | Where-Object {{ $_.Enabled -and ($_.VoiceInfo.Culture.Name -like 'es-*') }} | Select-Object -First 1 }}
if (-not $voz) {{ $voz = $s.GetInstalledVoices() | Where-Object {{ $_.Enabled -and ($_.VoiceInfo.Name -match 'Spanish|Español|Espanol') }} | Select-Object -First 1 }}
if ($voz) {{ $s.SelectVoice($voz.VoiceInfo.Name) }}
$s.Rate = 0
$s.Volume = 100
$s.Speak({texto_lit})
$s.Dispose()
"""

    try:
        import base64
        encoded = script.encode("utf-16le")
        cmd = [exe, "-STA", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", base64.b64encode(encoded).decode("ascii")]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=_startupinfo_oculto(),
            timeout=45,
            check=False,
        )
        return True
    except Exception as e:
        _ultimo_error = f"Error usando SAPI por PowerShell: {e}"
        return False


def _seleccionar_voz_pyttsx3(motor):
    try:
        voces = motor.getProperty("voices") or []
    except Exception:
        return "predeterminada"

    for preferida in NOMBRES_VOZ_PREFERIDOS:
        for voz in voces:
            texto = f"{getattr(voz, 'name', '')} {getattr(voz, 'id', '')}".lower()
            if preferida.lower() in texto:
                try:
                    motor.setProperty("voice", voz.id)
                    return getattr(voz, "name", preferida) or preferida
                except Exception:
                    pass

    for voz in voces:
        texto = f"{getattr(voz, 'name', '')} {getattr(voz, 'id', '')}".lower()
        if any(palabra in texto for palabra in ("spanish", "español", "espanol", "es-")):
            try:
                motor.setProperty("voice", voz.id)
                return getattr(voz, "name", "voz en español") or "voz en español"
            except Exception:
                pass

    return "predeterminada"


def _hablar_pyttsx3(texto):
    global _ultimo_error

    if pyttsx3 is None:
        _ultimo_error = "pyttsx3 no está instalado."
        return False

    try:
        motor = pyttsx3.init("sapi5" if _windows() else None)
        _seleccionar_voz_pyttsx3(motor)
        motor.setProperty("rate", 175)
        motor.setProperty("volume", 1.0)
        motor.say(str(texto))
        motor.runAndWait()
        try:
            motor.stop()
        except Exception:
            pass
        return True
    except Exception as e:
        _ultimo_error = f"Error usando pyttsx3: {e}"
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

        # 2) Voz de Windows por VBScript/SAPI. Más estable que PowerShell en varios equipos.
        if _hablar_vbs_sapi(texto):
            _metodo_activo = "voz de Windows SAPI"
            continue

        # 3) Voz de Windows por PowerShell.
        if _hablar_powershell(texto):
            _metodo_activo = "voz de Windows PowerShell"
            continue

        # 4) pyttsx3 como último respaldo.
        if _hablar_pyttsx3(texto):
            _metodo_activo = "pyttsx3"
            continue

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

    Con NVDA se entrega el texto directamente al lector de pantalla. Si NVDA
    no está disponible, usa una voz local síncrona para evitar que el mensaje
    se pierda al cerrar la aplicación.
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

    # Los respaldos son síncronos a propósito: el programa no termina hasta
    # haber entregado la despedida al motor de voz local.
    if _hablar_vbs_sapi(texto):
        _metodo_activo = "voz de Windows SAPI"
        return True
    if _hablar_powershell(texto):
        _metodo_activo = "voz de Windows PowerShell"
        return True
    if _hablar_pyttsx3(texto):
        _metodo_activo = "pyttsx3"
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
    powershell = shutil.which('powershell.exe') or shutil.which('powershell') or shutil.which('pwsh') or traducir("No encontrado")
    wsh = shutil.which('wscript.exe') or shutil.which('cscript.exe') or traducir("No encontrado")
    pyttsx3_estado = traducir("Sí") if pyttsx3 is not None else traducir("No")

    return "\n".join([
        traducir_formato("Método activo: {metodo}", metodo=metodo),
        traducir_formato("Último detalle/error: {detalle}", detalle=detalle),
        traducir_formato("Windows: {valor}", valor=_windows()),
        traducir_formato("PowerShell: {valor}", valor=powershell),
        traducir_formato("Windows Script Host: {valor}", valor=wsh),
        traducir_formato("pyttsx3 instalado: {valor}", valor=pyttsx3_estado),
        traducir("DLL NVDA detectadas:") + "\n- " + "\n- ".join(dlls),
    ])
