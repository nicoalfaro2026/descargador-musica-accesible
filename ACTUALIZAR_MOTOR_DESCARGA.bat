@echo off
cd /d "%~dp0"
echo Actualizando motor de descarga yt-dlp.exe...
python -c "from motor_ytdlp import actualizar_motor_descarga; print(actualizar_motor_descarga(callback=print))"
echo.
pause
