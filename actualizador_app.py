import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class ActualizadorNoConfigurado(Exception):
    pass


class ActualizadorError(Exception):
    pass


@dataclass
class InfoActualizacion:
    version: str
    tag: str
    nombre: str
    notas: str
    pagina: str
    descarga_url: str
    archivo: str


def _base_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _rutas_recurso(nombre):
    rutas = []
    base = _base_dir()
    rutas.append(base / nombre)
    rutas.append(base / "_internal" / nombre)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        rutas.append(Path(meipass) / nombre)
    rutas.append(Path(__file__).resolve().parent / nombre)

    vistas = set()
    unicas = []
    for ruta in rutas:
        try:
            clave = str(ruta.resolve())
        except Exception:
            clave = str(ruta)
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(ruta)
    return unicas


def cargar_configuracion_actualizador():
    datos = {}
    for ruta in _rutas_recurso("actualizacion.json"):
        if ruta.exists():
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                if isinstance(datos, dict):
                    break
            except Exception:
                datos = {}

    if not isinstance(datos, dict):
        datos = {}

    return {
        "github_repo": str(datos.get("github_repo", "")).strip(),
        "api_url": str(datos.get("api_url", "")).strip(),
        "manifest_url": str(datos.get("manifest_url", "")).strip(),
        "asset_contains": str(datos.get("asset_contains", "")).strip(),
        "asset_extension": str(datos.get("asset_extension", ".zip") or ".zip").strip(),
        "pagina_descargas": str(datos.get("pagina_descargas", "")).strip(),
    }


def normalizar_version(version):
    texto = str(version or "").strip()
    texto = texto.lower().replace("version", "").replace("versión", "").strip()
    texto = texto.lstrip("v")
    partes = []
    for parte in re.split(r"[^0-9]+", texto):
        if parte != "":
            try:
                partes.append(int(parte))
            except Exception:
                partes.append(0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:4])


def es_version_mayor(disponible, actual):
    return normalizar_version(disponible) > normalizar_version(actual)


def _abrir_json_url(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DescargadorMusicaAccesible-Actualizador",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", errors="replace"))


def _version_desde_tag(tag):
    return str(tag or "").strip().lstrip("v")


def _seleccionar_asset(assets, extension=".zip", contiene=""):
    extension = extension or ".zip"
    contiene = (contiene or "").lower().strip()
    candidatos = []
    for asset in assets or []:
        nombre = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if not nombre or not url:
            continue
        if extension and not nombre.lower().endswith(extension.lower()):
            continue
        if contiene and contiene not in nombre.lower():
            continue
        candidatos.append((nombre, url))
    if candidatos:
        return candidatos[0]

    # Respaldo: primer ZIP disponible, aunque no coincida con asset_contains.
    for asset in assets or []:
        nombre = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if nombre.lower().endswith(".zip") and url:
            return nombre, url
    return None, None


def consultar_actualizacion(version_actual, timeout=20):
    cfg = cargar_configuracion_actualizador()
    manifest_url = cfg.get("manifest_url")
    api_url = cfg.get("api_url")
    repo = cfg.get("github_repo")

    if manifest_url:
        datos = _abrir_json_url(manifest_url, timeout=timeout)
        version = str(datos.get("version", "")).strip().lstrip("v")
        url = str(datos.get("download_url", "")).strip()
        archivo = str(datos.get("archivo", "")).strip() or Path(url).name or "actualizacion.zip"
        if not version or not url:
            raise ActualizadorError("El manifiesto de actualización no contiene versión o enlace de descarga.")
        if not es_version_mayor(version, version_actual):
            return None
        return InfoActualizacion(
            version=version,
            tag=datos.get("tag", f"v{version}"),
            nombre=datos.get("nombre", f"Versión {version}"),
            notas=datos.get("notas", ""),
            pagina=datos.get("pagina", cfg.get("pagina_descargas", "")),
            descarga_url=url,
            archivo=archivo,
        )

    if not api_url and repo:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    if not api_url:
        raise ActualizadorNoConfigurado(
            "El actualizador todavía no tiene configurado el repositorio de GitHub ni el enlace de actualización."
        )

    datos = _abrir_json_url(api_url, timeout=timeout)
    tag = str(datos.get("tag_name", "")).strip()
    version = _version_desde_tag(tag)
    if not version:
        raise ActualizadorError("No se pudo leer la versión publicada.")
    if not es_version_mayor(version, version_actual):
        return None

    archivo, descarga_url = _seleccionar_asset(
        datos.get("assets", []),
        extension=cfg.get("asset_extension", ".zip"),
        contiene=cfg.get("asset_contains", ""),
    )
    if not descarga_url:
        raise ActualizadorError("La versión publicada no tiene un archivo ZIP descargable.")

    return InfoActualizacion(
        version=version,
        tag=tag or f"v{version}",
        nombre=str(datos.get("name", "")).strip() or f"Versión {version}",
        notas=str(datos.get("body", "")).strip(),
        pagina=str(datos.get("html_url", "")).strip() or cfg.get("pagina_descargas", ""),
        descarga_url=descarga_url,
        archivo=archivo,
    )


def descargar_actualizacion(info, carpeta_destino, callback=None, timeout=30):
    carpeta = Path(carpeta_destino)
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = info.archivo or f"actualizacion_{info.version}.zip"
    destino = carpeta / nombre
    temporal = destino.with_suffix(destino.suffix + ".descargando")

    req = urllib.request.Request(
        info.descarga_url,
        headers={"User-Agent": "DescargadorMusicaAccesible-Actualizador"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(temporal, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            descargado = 0
            ultimo = -1
            while True:
                bloque = resp.read(1024 * 128)
                if not bloque:
                    break
                f.write(bloque)
                descargado += len(bloque)
                if total:
                    porcentaje = int(descargado * 100 / total)
                    if porcentaje != ultimo and (porcentaje % 5 == 0 or porcentaje >= 100):
                        ultimo = porcentaje
                        if callback:
                            callback(porcentaje)
                elif callback and ultimo < 0:
                    ultimo = 0
                    callback(0)
        if destino.exists():
            destino.unlink()
        temporal.rename(destino)
        if callback:
            callback(100)
        return destino
    except Exception:
        try:
            if temporal.exists():
                temporal.unlink()
        except Exception:
            pass
        raise



def carpeta_temporal_actualizador():
    """Devuelve una carpeta corta y estable para descargas temporales del actualizador.

    Se usa AppData\\Local para no depender de la ruta donde el usuario tenga instalado
    el programa. Esto evita errores por rutas largas o carpetas renombradas.
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    ruta = Path(base) / "DescargadorMusicaAccesible" / "Update"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def limpiar_carpeta_temporal_actualizador():
    try:
        ruta = carpeta_temporal_actualizador()
        for nombre in ("descarga", "extraida", "logs"):
            objetivo = ruta / nombre
            if objetivo.exists():
                shutil.rmtree(objetivo, ignore_errors=True)
    except Exception:
        pass

def crear_script_aplicacion(zip_actualizacion, version_nueva):
    """Crea un script externo para aplicar la actualización cuando el programa se cierre.

    El usuario no ve este detalle. Se usa porque Windows no permite reemplazar el EXE
    mientras está abierto. El trabajo pesado se realiza en AppData\\Local para evitar
    problemas de rutas largas aunque el usuario tenga el programa en Descargas,
    Escritorio, un pendrive o una carpeta renombrada.
    """
    if not getattr(sys, "frozen", False):
        raise ActualizadorError("La instalación automática solo está disponible en la versión empaquetada del programa.")

    app_dir = _base_dir()
    exe_path = Path(sys.executable).resolve()
    zip_path = Path(zip_actualizacion).resolve()

    trabajo = carpeta_temporal_actualizador()
    descarga_dir = trabajo / "descarga"
    extract_dir = trabajo / "extraida"
    logs_dir = trabajo / "logs"
    for carpeta in (descarga_dir, extract_dir, logs_dir):
        carpeta.mkdir(parents=True, exist_ok=True)

    script = trabajo / "aplicar_actualizacion.bat"
    log = logs_dir / "actualizador.log"
    exe_oficial = "DescargadorMusicaAccesible.exe"

    contenido = fr'''@echo off
setlocal EnableDelayedExpansion
set "APPDIR={app_dir}"
set "EXE={exe_path.name}"
set "EXE_OFICIAL={exe_oficial}"
set "ZIP={zip_path}"
set "WORK={trabajo}"
set "EXTRACT={extract_dir}"
set "LOG={log}"

echo ===== Actualizador Descargador de Musica Accesible ===== > "%LOG%"
echo Fecha: %DATE% %TIME% >> "%LOG%"
echo APPDIR=%APPDIR% >> "%LOG%"
echo ZIP=%ZIP% >> "%LOG%"
echo EXTRACT=%EXTRACT% >> "%LOG%"

timeout /t 3 /nobreak >nul

if not exist "%ZIP%" (
    echo ERROR: No existe el ZIP de actualizacion. >> "%LOG%"
    goto error
)

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >> "%LOG%" 2>&1
mkdir "%EXTRACT%" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: No se pudo crear la carpeta de extraccion. >> "%LOG%"
    goto error
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%EXTRACT%' -Force" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: Expand-Archive fallo. >> "%LOG%"
    goto error
)

set "SOURCE="
for /f "delims=" %%F in ('dir /s /b "%EXTRACT%\%EXE_OFICIAL%" 2^>nul') do (
    if not defined SOURCE set "SOURCE=%%~dpF"
)
if not defined SOURCE (
    for /f "delims=" %%F in ('dir /s /b "%EXTRACT%\%EXE%" 2^>nul') do (
        if not defined SOURCE set "SOURCE=%%~dpF"
    )
)
if not defined SOURCE (
    echo ERROR: No se encontro el ejecutable nuevo dentro del ZIP. >> "%LOG%"
    goto error
)

rem Quitar la barra final de SOURCE para que ROBocopy no mezcle los argumentos cuando la ruta va entre comillas.
if "!SOURCE:~-1!"=="\" set "SOURCE=!SOURCE:~0,-1!"
echo SOURCE=!SOURCE! >> "%LOG%"

if /I not "%EXE%"=="%EXE_OFICIAL%" (
    if exist "!SOURCE!\%EXE_OFICIAL%" (
        copy /y "!SOURCE!\%EXE_OFICIAL%" "!SOURCE!\%EXE%" >> "%LOG%" 2>&1
    )
)

robocopy "!SOURCE!" "%APPDIR%" /E /R:3 /W:2 /XD datos logs __pycache__ /XF aplicar_actualizacion.bat *.pyc >> "%LOG%" 2>&1
set "ROBO=%ERRORLEVEL%"
echo ROBOCOPY_ERRORLEVEL=%ROBO% >> "%LOG%"
if !ROBO! GEQ 8 goto error

rem Limpieza controlada de archivos de desarrollo y notas antiguas.
rem No se usa /MIR para no borrar datos ni archivos personales del usuario.
for %%D in ("%APPDIR%" "%APPDIR%\_internal") do (
    del /q "%%~D\NOTAS_VERSION_*.txt" >> "%LOG%" 2>&1
    del /q "%%~D\NOTAS_PRUEBA_ACTUALIZADOR_*.txt" >> "%LOG%" 2>&1
    del /q "%%~D\LEEME_PRUEBA_Y_EMPAQUETADO.txt" >> "%LOG%" 2>&1
    del /q "%%~D\ABRIR_EXE_PRUEBA.bat" >> "%LOG%" 2>&1
    del /q "%%~D\EMPAQUETAR_MODO_PRUEBA.bat" >> "%LOG%" 2>&1
    del /q "%%~D\DescargadorAccesible_PRUEBA.spec" >> "%LOG%" 2>&1
    del /q "%%~D\INSTALAR_REPRODUCTOR_INTERNO.bat" >> "%LOG%" 2>&1
    del /q "%%~D\nvdaControllerClient.dll" >> "%LOG%" 2>&1
    del /q "%%~D\nvdaControllerClient32.dll" >> "%LOG%" 2>&1
    if exist "%%~D\__pycache__" rmdir /s /q "%%~D\__pycache__" >> "%LOG%" 2>&1
)

if not exist "%APPDIR%\%EXE%" (
    echo ERROR: No existe el ejecutable actualizado para abrir. >> "%LOG%"
    goto error
)

echo OK: archivos copiados. >> "%LOG%"
start "" "%APPDIR%\%EXE%" --actualizado {version_nueva}

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >> "%LOG%" 2>&1
exit /b 0

:error
echo ERROR: No se pudo aplicar la actualizacion. >> "%LOG%"
if exist "%APPDIR%\%EXE%" start "" "%APPDIR%\%EXE%" --actualizacion-error
exit /b 1
'''
    with open(script, "w", encoding="mbcs", errors="replace") as f:
        f.write(contenido)
    return script

def ejecutar_script_y_salir(script):
    subprocess.Popen([str(script)], shell=False, cwd=str(Path(script).parent))
