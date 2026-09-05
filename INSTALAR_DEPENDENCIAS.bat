@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo Instalando dependencias de desarrollo
echo ================================================
python --version
if errorlevel 1 (
    echo ERROR: No se encontro Python.
    pause
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto :error

rem Pytubefix declara nodejs-wheel-binaries como dependencia. No lo instalamos:
rem la aplicacion usa un node.exe portable y un adaptador local nodejs_wheel.
python -m pip install --upgrade --no-deps pytubefix==10.11.0
if errorlevel 1 goto :error

echo.
echo Dependencias instaladas correctamente.
echo No se instalo nodejs-wheel-binaries: no es necesario en este proyecto.
if /I "%~1"=="--sin-pausa" exit /b 0
pause
exit /b 0

:error
echo.
echo ERROR: No se pudieron instalar las dependencias.
if /I "%~1"=="--sin-pausa" exit /b 1
pause
exit /b 1
