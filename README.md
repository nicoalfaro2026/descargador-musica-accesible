# Descargador de Música Accesible

[English README](README_EN.md)

Aplicación de escritorio para Windows desarrollada con accesibilidad como requisito principal. Está pensada para utilizarse completamente con teclado y lectores de pantalla como NVDA y JAWS.

> **Uso responsable:** utilice la aplicación únicamente con contenido que tenga derecho o permiso para descargar y respete las condiciones aplicables de los servicios utilizados.

## Estado del proyecto

Versión del código de esta base: **1.8.0**.

Idiomas incluidos: Español, English, Français, Italiano, Português y Русский. Los seis catálogos comparten exactamente las mismas claves; `idiomas/es.json` es el catálogo maestro.

## Novedades principales de 1.8.0

- Historial limitado automáticamente a los 1.000 registros más recientes y opción para limpiarlo sin borrar archivos descargados.
- Cantidad predeterminada de búsqueda configurable: 20, 50, 75, 100, 150, 200 o 300 resultados.
- Opción para preguntar o no la cantidad antes de cada búsqueda.
- Selector de dispositivo de salida de audio mediante MPV, con retorno automático al dispositivo predeterminado si el elegido desaparece.
- Reproductor simplificado; la ayuda completa de teclado queda en **Ayuda > Atajos de teclado**.
- Audio: MP3, M4A, AAC, OPUS, OGG, WAV y FLAC.
- Video MP4 con calidad automática o límites de resolución desde 144p hasta 2160p/4K.

## Arquitectura de descarga

El programa utiliza **yt-dlp** como motor principal, **Deno** para soporte JavaScript y **pytubefix + Node portable** como respaldo automático ante fallos compatibles. **FFmpeg** procesa conversiones y **MPV** proporciona la reproducción interna.

El usuario final no debería necesitar instalar Python, Deno, Node, FFmpeg ni modificar Windows.

## Accesibilidad

El proyecto prioriza navegación por teclado, orden de tabulación comprensible, etiquetas compatibles con lectores de pantalla, anuncios breves y ausencia de pasos técnicos obligatorios para el usuario final.

## Ejecutar desde código fuente en Windows

En la carpeta completa de construcción ejecute `PREPARAR_MODO_ROBUSTO.bat` y después `ABRIR_PROGRAMA.bat`.

Los binarios portables de terceros no se almacenan en el repositorio fuente. Consulte [docs/DEPENDENCIAS_BINARIAS.md](docs/DEPENDENCIAS_BINARIAS.md).

## Crear una versión portable

Ejecute `CREAR_VERSION_DISTRIBUIBLE.bat`. El proceso crea `PAQUETE_PARA_DISTRIBUIR` y `DescargadorMusicaAccesible_1_8_0_PORTABLE.zip`, destinados a **GitHub Releases**.

## Traducciones

Ejecute `python tools/verificar_traducciones.py` y `python tools/verificar_textos_interfaz.py` antes de publicar. Consulte [docs/TRADUCCIONES.md](docs/TRADUCCIONES.md).

## Seguridad y antivirus

No se recomienda desactivar Windows Defender ni otro antivirus. Las Releases deberían publicarse con SHA-256 y, cuando sea posible, con firma digital.

## Licencia

Este proyecto se distribuye bajo la **GNU General Public License v3.0 (GPL-3.0)**. Consulte el archivo [LICENSE](LICENSE).
