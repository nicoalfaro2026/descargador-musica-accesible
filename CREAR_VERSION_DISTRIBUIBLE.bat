@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================================
echo CREAR VERSION PORTABLE PARA DISTRIBUIR - SIN INSTALADOR
echo ==========================================================
echo.
echo El usuario final NO necesitara Python, pip, Deno ni Node instalados.
echo Este proceso usa una carpeta corta temporal para evitar errores de rutas largas.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: En esta PC de desarrollo no se encontro Python.
    pause
    exit /b 1
)

set "WORK=%USERPROFILE%\DMA_B"
set "SRC=%WORK%\s"
set "VENV=%WORK%\v"
set "OUT=%~dp0PAQUETE_PARA_DISTRIBUIR"
set "ZIP=%~dp0DescargadorMusicaAccesible_1_8_0_PORTABLE.zip"

if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%SRC%" || goto :error

rem Copiar el proyecto a una ruta corta. Se excluyen residuos de desarrollo.
robocopy "%~dp0" "%SRC%" /E /R:1 /W:1 /XD build dist logs __pycache__ PAQUETE_PARA_DISTRIBUIR /XF *.zip *.pyc diagnostico_dependencias.txt HABILITAR_RUTAS_LARGAS_WINDOWS.bat >nul
if errorlevel 8 goto :error

python -m venv "%VENV%"
if errorlevel 1 goto :error
set "PY=%VENV%\Scripts\python.exe"
set "PYTHONNOUSERSITE=1"

"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%PY%" -m pip install --upgrade -r "%SRC%\requirements_build.txt"
if errorlevel 1 goto :error
rem Instalar pytubefix sin nodejs-wheel-binaries. El proyecto aporta Node portable.
"%PY%" -m pip install --upgrade --no-deps pytubefix==10.11.0
if errorlevel 1 goto :error

echo.
echo Preparando runtimes portables...
pushd "%SRC%"
"%PY%" preparar_motor_robusto.py
if errorlevel 1 (
    echo ERROR: No se pudo preparar Deno portable.
    popd
    goto :error
)
"%PY%" preparar_node_portable.py
if errorlevel 1 (
    echo ERROR: No se pudo preparar Node portable.
    popd
    goto :error
)

"%PY%" -c "from motor_ytdlp import actualizar_motor_descarga; r=actualizar_motor_descarga(); print('yt-dlp:', r.get('version'), r.get('ruta'))"
if errorlevel 1 echo AVISO: se conservara el yt-dlp.exe incluido.

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
"%PY%" -m PyInstaller --clean --noconfirm DescargadorAccesible_FINAL.spec
if errorlevel 1 (
    popd
    goto :error
)

set "BUILT=%SRC%\dist\DMA"
if not exist "%BUILT%\DescargadorMusicaAccesible.exe" (
    echo ERROR: PyInstaller no genero el ejecutable final.
    popd
    goto :error
)

rem Verificaciones basicas del paquete final.
if not exist "%BUILT%\_internal\yt-dlp.exe" goto :faltan
if not exist "%BUILT%\_internal\deno.exe" goto :faltan
if not exist "%BUILT%\_internal\node.exe" goto :faltan
if not exist "%BUILT%\_internal\ffmpeg.exe" goto :faltan
if not exist "%BUILT%\_internal\ffprobe.exe" goto :faltan
if not exist "%BUILT%\_internal\mpv-1.dll" goto :faltan
if not exist "%BUILT%\_internal\nvdaControllerClient64.dll" goto :faltan

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%" || goto :error_pop
robocopy "%BUILT%" "%OUT%" /E /R:1 /W:1 >nul
if errorlevel 8 goto :error_pop

if exist "MANUAL_DE_USUARIO_DESCARGADOR_MUSICA_ACCESIBLE.txt" copy /Y "MANUAL_DE_USUARIO_DESCARGADOR_MUSICA_ACCESIBLE.txt" "%OUT%\MANUAL_DE_USUARIO.txt" >nul
if exist "LEEME_USUARIO_FINAL.txt" copy /Y "LEEME_USUARIO_FINAL.txt" "%OUT%\LEEME.txt" >nul
if exist "manuales" robocopy "manuales" "%OUT%\Manuales" /E /R:1 /W:1 >nul

popd

if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath '%ZIP%' -CompressionLevel Optimal -Force"
if errorlevel 1 goto :error

certutil -hashfile "%ZIP%" SHA256 > "%ZIP%.sha256.txt"

echo.
echo ==========================================================
echo LISTO.
echo Carpeta para probar:
echo %OUT%
echo.
echo ZIP para distribuir:
echo %ZIP%
echo.
echo Los usuarios solo deben descomprimir y abrir:
echo DescargadorMusicaAccesible.exe
echo No necesitan ejecutar ningun BAT ni instalar dependencias.
echo ==========================================================
pause
exit /b 0

:faltan
echo ERROR: Al paquete final le falta uno o mas motores portables.
:error_pop
popd
:error
echo.
echo ERROR: No se pudo crear la version distribuible.
echo Revise los mensajes anteriores.
pause
exit /b 1
