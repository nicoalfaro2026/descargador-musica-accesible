# Dependencias binarias para construir la versión Windows

El repositorio fuente no debe almacenar los binarios portables grandes de terceros. La carpeta local usada para construir una Release puede contener estos componentes:

- `ffmpeg.exe`
- `ffprobe.exe`
- `mpv-1.dll`
- `nvdaControllerClient64.dll`
- `yt-dlp.exe`
- `deno.exe`
- `node.exe`

Los scripts del proyecto pueden preparar o actualizar yt-dlp, Deno y Node. FFmpeg, FFprobe, libmpv y el cliente de NVDA deben provenir de distribuciones confiables y compatibles con Windows x64 antes de construir la Release.

`DescargadorAccesible_FINAL.spec` incluye automáticamente los binarios presentes en la carpeta de construcción. `CREAR_VERSION_DISTRIBUIBLE.bat` comprueba que los componentes esenciales hayan quedado en el paquete final.

## Reglas para el repositorio

- No subir estos binarios al historial normal de Git.
- No copiar ejecutables desde fuentes desconocidas.
- Mantener registro de la procedencia y versión utilizada para cada Release.
- Publicar el ZIP portable en GitHub Releases, acompañado de su SHA-256.
- Revisar las licencias y avisos de terceros aplicables antes de la distribución pública.
