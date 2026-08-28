# Descargador de Música Accesible 1.8.0

**Desarrollado por Nicolás Alfaro**

La versión 1.8.0 es una actualización importante centrada en accesibilidad, estabilidad, formatos de descarga, reproducción, internacionalización y distribución portable.

## Nuevas funciones

- Nuevos formatos de audio: MP3, M4A, AAC, OPUS, OGG, WAV y FLAC.
- Selección de video MP4 por resolución: mejor disponible, 2160p/4K, 1440p, 1080p, 720p, 480p, 360p, 240p y 144p.
- Cantidad predeterminada de resultados configurable: 20, 50, 75, 100, 150, 200 o 300.
- Opción para decidir si el programa pregunta la cantidad de resultados antes de cada búsqueda.
- Selector de dispositivo de salida de audio mediante MPV.
- Nueva opción para limpiar el historial sin eliminar los archivos descargados.
- El historial se limita automáticamente a los 1.000 registros más recientes.

## Accesibilidad y reproductor

- Mejoras orientadas al uso con NVDA y JAWS.
- El volumen seleccionado se conserva al reproducir nuevas canciones.
- Se eliminó del reproductor el cuadro redundante de atajos; la ayuda completa sigue disponible desde el menú Ayuda.
- Si el dispositivo de audio guardado deja de estar disponible, el reproductor vuelve automáticamente al dispositivo predeterminado.
- Al iniciar se anuncia el nombre del programa, la versión y «Desarrollado por Nicolás Alfaro».
- Al cerrar se anuncia un agradecimiento al usuario y la autoría del programa.

## Motor de descarga y estabilidad

- yt-dlp continúa como motor principal.
- Soporte de Deno portable para los desafíos JavaScript actuales de YouTube.
- pytubefix funciona como motor alternativo automático cuando el fallo es compatible con un reintento.
- Node portable disponible para el motor alternativo.
- El respaldo no se activa innecesariamente ante videos privados o eliminados, falta de Internet, errores DNS, timeout, autenticación o HTTP 429.
- Se mejoró el tratamiento de temporales fallidos para no tocar archivos anteriores del usuario.
- Se registra información técnica de los intentos en `logs/descargador.log` para facilitar el diagnóstico.
- Se reforzó la actualización de yt-dlp con verificación y restauración del motor anterior si una actualización falla.
- Se corrigió la acumulación de archivos obsoletos que podían quedar después de actualizaciones antiguas.

## Idiomas

La interfaz dispone de seis idiomas:

- Español
- Inglés
- Francés
- Italiano
- Portugués
- Ruso

Todos los idiomas utilizan un catálogo sincronizado y existen verificaciones automáticas para detectar claves faltantes o variables incompatibles.

## Distribución

- Preparación para una distribución portable en Windows.
- El objetivo del paquete público es que el usuario no tenga que instalar Python, yt-dlp, Deno, Node ni FFmpeg manualmente.
- FFmpeg, MPV y los motores necesarios se integran en la construcción distribuible.
- UPX está desactivado en la compilación para mantener un empaquetado más transparente y reducir posibles conflictos con antivirus.
- El código fuente y los binarios grandes de terceros se separan: el repositorio contiene el código; el ZIP portable se publica en GitHub Releases.

## GitHub y actualizaciones

- Repositorio oficial: `nicoalfaro2026/descargador-musica-accesible`.
- El actualizador automático consulta las Releases del repositorio oficial.
- Licencia del proyecto: GNU General Public License v3.0 (GPL-3.0).

## Nota de uso

El programa debe utilizarse respetando los derechos de autor, las condiciones de los servicios y la legislación aplicable. El usuario es responsable del contenido que descarga y del uso que hace de él.
