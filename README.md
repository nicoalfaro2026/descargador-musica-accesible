# Descargador de Música Accesible

[English README](README_EN.md)

Aplicación de escritorio para Windows desarrollada con accesibilidad como requisito principal. Está pensada para utilizarse completamente con teclado y lectores de pantalla como NVDA y JAWS.

> **Uso responsable:** utilice la aplicación únicamente con contenido que tenga derecho o permiso para descargar y respete las condiciones aplicables de los servicios utilizados.

## Estado del proyecto

Versión pública estable: **1.8.0**.

Rama de trabajo actual: **1.8.1 en prueba**, centrada en mantenimiento, búsquedas, autenticación opcional mediante navegador y documentación accesible.

Idiomas incluidos: Español, English, Français, Italiano, Português y Русский. `idiomas/es.json` es el catálogo maestro y los seis catálogos deben mantener las mismas claves.

## Cambios en prueba para 1.8.1

- Resultados de YouTube más simples: índice, título, canal, publicación, visualizaciones y duración; la URL se conserva internamente pero no se muestra en la lista.
- Enriquecimiento diferido de metadatos para mantener rápidas las búsquedas grandes.
- Preferencia opcional por los metadatos de YouTube en el idioma de la aplicación.
- Respaldo voluntario con una sesión ya iniciada en un navegador cuando YouTube solicite verificación.
- La actualización manual de la librería de descarga ya no vuelve a descargar la misma versión si no existe una más nueva.
- Mejoras para evitar que los mensajes de bienvenida y despedida sean interrumpidos.
- Manual profesional en PDF accesible y TXT para los seis idiomas.
- Favoritos persistentes: Alt+F agrega o quita el video enfocado y Herramientas > Favoritos permite reproducirlo, descargarlo, consultar información o retirarlo de la lista.
- Cola de descargas persistente: Alt+Q agrega el video enfocado, Ctrl+Shift+Q agrega videos marcados y Herramientas > Cola de descargas permite iniciar, revisar, detener o administrar la cola.

Consulte [RELEASE_NOTES_1_8_1_PRUEBA.md](RELEASE_NOTES_1_8_1_PRUEBA.md) para el detalle de esta versión de prueba.

## Accesibilidad

El proyecto prioriza navegación por teclado, orden de tabulación comprensible, etiquetas compatibles con lectores de pantalla, mensajes breves y ausencia de configuraciones técnicas obligatorias para el usuario final.

## Ejecutar desde código fuente en Windows

En la carpeta completa de construcción ejecute `PREPARAR_MODO_ROBUSTO.bat` y después `ABRIR_PROGRAMA.bat`.

Los binarios portables de terceros no se almacenan en el repositorio fuente. Consulte [docs/DEPENDENCIAS_BINARIAS.md](docs/DEPENDENCIAS_BINARIAS.md) y [docs/DOCUMENTACION_TECNICA.md](docs/DOCUMENTACION_TECNICA.md).

## Crear una versión portable

Ejecute `CREAR_VERSION_DISTRIBUIBLE.bat` desde la carpeta completa de construcción. Los paquetes portables destinados a personas usuarias se publican en **GitHub Releases**.

## Traducciones

Antes de publicar ejecute:

```text
python tools/verificar_traducciones.py
python tools/verificar_textos_interfaz.py
```

Consulte [docs/TRADUCCIONES.md](docs/TRADUCCIONES.md).

## Seguridad y antivirus

No se recomienda desactivar Windows Defender ni otro antivirus. Las Releases deberían publicarse con SHA-256 y, cuando sea posible, con firma digital.

## Contacto

Desarrollado por Nicolás Alfaro.

Correo: alfaronico8@gmail.com

Proyecto oficial: https://github.com/nicoalfaro2026/descargador-musica-accesible

## Licencia

Este proyecto se distribuye bajo la **GNU General Public License v3.0 (GPL-3.0)**. Consulte [LICENSE](LICENSE).

- Playlists mejoradas integradas con Favoritos y Cola: contenido, playlist completa y selección por rango.
