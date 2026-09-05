@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo =====================================================
echo Preparando Descargador de Musica Accesible - robusto
echo =====================================================
python --version
if errorlevel 1 (
    echo No se encontro Python. Python solo es necesario para desarrollo.
    pause
    exit /b 1
)

echo.
echo 1 de 4 - Instalando y actualizando librerias...
call INSTALAR_DEPENDENCIAS.bat --sin-pausa
if errorlevel 1 (
    echo ERROR: No se pudieron preparar las dependencias.
    pause
    exit /b 1
)

echo.
echo 2 de 4 - Preparando Deno portable para yt-dlp...
python preparar_motor_robusto.py
if errorlevel 1 echo AVISO: Deno no pudo prepararse. Puede volver a intentarlo mas tarde.

echo.
echo 3 de 4 - Preparando Node portable para pytubefix...
python preparar_node_portable.py
if errorlevel 1 echo AVISO: Node no pudo prepararse. yt-dlp seguira funcionando; el respaldo puede quedar limitado.

echo.
echo 4 de 4 - Actualizando yt-dlp.exe...
python -c "from motor_ytdlp import actualizar_motor_descarga; r=actualizar_motor_descarga(); print('yt-dlp listo:', r.get('version'), r.get('ruta'))"
if errorlevel 1 echo AVISO: yt-dlp no pudo actualizarse ahora. Se conservara el existente.

echo.
echo Diagnostico de motores:
python -c "from motor_ytdlp import diagnostico_motor_descarga; print(diagnostico_motor_descarga())"
echo.
echo Preparacion terminada. Ahora puede abrir ABRIR_PROGRAMA.bat.
pause
