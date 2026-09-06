@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Crear Descargador de Musica Accesible Portable

set "LOG=%~dp0construccion_portable.log"
>"%LOG%" echo ==========================================================
>>"%LOG%" echo CONSTRUCCION PORTABLE - %DATE% %TIME%
>>"%LOG%" echo Carpeta fuente: %CD%
>>"%LOG%" echo ==========================================================

echo ==========================================================
echo DESCARGADOR DE MUSICA ACCESIBLE
echo CONSTRUCTOR PORTABLE
echo ==========================================================
echo.
echo El usuario final no necesita ejecutar archivos adicionales.
echo El diagnostico de construccion se guardara en:
echo %LOG%
echo.

where python >>"%LOG%" 2>&1
python --version >>"%LOG%" 2>&1
if errorlevel 1 goto :error_python

for /f "delims=" %%V in ('python -c "import config; print(config.VERSION)"') do set "APPVER=%%V"
if not defined APPVER goto :error_version
set "VERFILE=%APPVER:.=_%"

if not exist "%~dp0copiar_build_portable.py" goto :error_helper

set "WORK=%USERPROFILE%\DMA_B"
set "SRC=%WORK%\s"
set "VENV=%WORK%\v"
set "OUT=%~dp0PAQUETE_PARA_DISTRIBUIR"
set "ZIP=%~dp0DescargadorMusicaAccesible_!VERFILE!_PORTABLE.zip"

echo Version detectada: !APPVER!
>>"%LOG%" echo Version detectada: !APPVER!

echo [1/9] Preparando carpeta temporal corta...
if exist "%WORK%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%WORK%' -Recurse -Force -ErrorAction Stop" >>"%LOG%" 2>&1
    if errorlevel 1 goto :error_cleanup
)
mkdir "%SRC%" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_mkdir

echo [2/9] Copiando proyecto...
python "%~dp0copiar_build_portable.py" fuente "%~dp0." "%SRC%" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_copy

for %%F in (main.py DescargadorAccesible_FINAL.spec requirements_build.txt ffmpeg.exe ffprobe.exe mpv-1.dll nvdaControllerClient64.dll) do (
    if not exist "%SRC%\%%F" (
        >>"%LOG%" echo FALTA ARCHIVO CRITICO: %%F
        echo ERROR: Falta el archivo critico %%F despues de copiar.
        goto :error
    )
)

echo [3/9] Creando entorno Python aislado...
python -m venv "%VENV%" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_venv
set "PY=%VENV%\Scripts\python.exe"
set "PYTHONNOUSERSITE=1"
if not exist "%PY%" goto :error_venv

echo [4/9] Instalando dependencias de construccion...
"%PY%" -m pip install --upgrade pip >>"%LOG%" 2>&1
if errorlevel 1 goto :error_pip
"%PY%" -m pip install --upgrade -r "%SRC%\requirements_build.txt" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_deps
"%PY%" -m pip install --upgrade --no-deps pytubefix==10.11.0 >>"%LOG%" 2>&1
if errorlevel 1 goto :error_pytubefix

echo [5/9] Preparando componentes portables...
pushd "%SRC%"
"%PY%" preparar_motor_robusto.py >>"%LOG%" 2>&1
if errorlevel 1 goto :error_deno_pop
"%PY%" preparar_node_portable.py >>"%LOG%" 2>&1
if errorlevel 1 goto :error_node_pop
"%PY%" -c "from motor_ytdlp import actualizar_motor_descarga; r=actualizar_motor_descarga(); print('yt-dlp:', r.get('version'), r.get('ruta'))" >>"%LOG%" 2>&1
if errorlevel 1 >>"%LOG%" echo AVISO: se conservara el yt-dlp.exe incluido.

echo [6/9] Compilando ejecutable con PyInstaller...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%PY%" -m PyInstaller --clean --noconfirm DescargadorAccesible_FINAL.spec >>"%LOG%" 2>&1
if errorlevel 1 goto :error_pyinstaller_pop

set "BUILT=%SRC%\dist\DMA"
if not exist "%BUILT%\DescargadorMusicaAccesible.exe" goto :error_exe_pop

echo [7/9] Verificando y armando el paquete...
for %%F in (yt-dlp.exe deno.exe node.exe ffmpeg.exe ffprobe.exe mpv-1.dll nvdaControllerClient64.dll) do (
    if not exist "%BUILT%\_internal\%%F" (
        >>"%LOG%" echo FALTA EN _internal: %%F
        echo ERROR: Falta %%F en el paquete final.
        goto :error_pop
    ) else (
        >>"%LOG%" echo OK: %%F
    )
)

"%PY%" "%SRC%\copiar_build_portable.py" final "%BUILT%" "%OUT%" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_finalcopy_pop

if exist "LEEME_USUARIO_FINAL.txt" copy /Y "LEEME_USUARIO_FINAL.txt" "%OUT%\LEEME.txt" >>"%LOG%" 2>&1
if exist "manuales" powershell -NoProfile -ExecutionPolicy Bypass -Command "Copy-Item -LiteralPath 'manuales' -Destination '%OUT%\Manuales' -Recurse -Force" >>"%LOG%" 2>&1
popd

echo [8/9] Creando ZIP portable...
if exist "%ZIP%" del /q "%ZIP%" >>"%LOG%" 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath '%ZIP%' -CompressionLevel Optimal -Force" >>"%LOG%" 2>&1
if errorlevel 1 goto :error_zip
if not exist "%ZIP%" goto :error_zip

echo [9/9] Calculando SHA-256...
certutil -hashfile "%ZIP%" SHA256 > "%ZIP%.sha256.txt" 2>>"%LOG%"
if errorlevel 1 >>"%LOG%" echo AVISO: no se pudo generar SHA-256.

>>"%LOG%" echo CONSTRUCCION TERMINADA CORRECTAMENTE.
echo.
echo ==========================================================
echo LISTO. VERSION PORTABLE CREADA CORRECTAMENTE.
echo ==========================================================
echo Carpeta para probar:
echo %OUT%
echo.
echo ZIP para distribuir:
echo %ZIP%
echo.
echo Primero pruebe el EXE dentro de PAQUETE_PARA_DISTRIBUIR.
echo ==========================================================
pause
exit /b 0

:error_python
echo ERROR: Python no esta disponible en esta PC.
>>"%LOG%" echo ERROR: Python no esta disponible.
goto :error
:error_version
echo ERROR: No se pudo determinar la version del programa.
>>"%LOG%" echo ERROR: No se pudo determinar la version.
goto :error
:error_helper
echo ERROR: Falta copiar_build_portable.py.
>>"%LOG%" echo ERROR: Falta copiar_build_portable.py.
goto :error
:error_cleanup
echo ERROR: No se pudo limpiar la carpeta temporal %WORK%.
goto :error
:error_mkdir
echo ERROR: No se pudo crear %SRC%.
goto :error
:error_copy
echo ERROR: Fallo la copia inicial del proyecto.
goto :error
:error_venv
echo ERROR: No se pudo crear el entorno Python aislado.
goto :error
:error_pip
echo ERROR: No se pudo preparar pip.
goto :error
:error_deps
echo ERROR: Fallo la instalacion de requirements_build.txt.
goto :error
:error_pytubefix
echo ERROR: No se pudo preparar pytubefix para la compilacion.
goto :error
:error_deno_pop
echo ERROR: No se pudo preparar Deno portable.
popd
goto :error
:error_node_pop
echo ERROR: No se pudo preparar Node portable.
popd
goto :error
:error_pyinstaller_pop
echo ERROR: PyInstaller no pudo compilar el programa.
popd
goto :error
:error_exe_pop
echo ERROR: PyInstaller termino pero no genero el EXE esperado.
popd
goto :error
:error_finalcopy_pop
echo ERROR: Fallo la copia final del paquete.
popd
goto :error
:error_pop
echo ERROR: Faltan componentes o fallo el armado final.
popd
goto :error
:error_zip
echo ERROR: No se pudo crear el ZIP portable.
goto :error
:error
echo.
echo ==========================================================
echo NO SE PUDO CREAR LA VERSION DISTRIBUIBLE.
echo Revise el archivo:
echo %LOG%
echo ==========================================================
pause
exit /b 1
