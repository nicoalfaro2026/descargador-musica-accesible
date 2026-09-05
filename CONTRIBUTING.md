# Contribuir

Gracias por ayudar a mejorar Descargador de Música Accesible.

## Antes de enviar un cambio

- Mantenga la navegación por teclado y la compatibilidad con lectores de pantalla.
- No añada pasos que obliguen al usuario final a instalar dependencias manualmente.
- No recomiende desactivar antivirus o protecciones de Windows.
- No incluya claves, tokens, cookies ni datos personales en commits, capturas o logs.
- Ejecute `python tools/verificar_traducciones.py` si modifica textos o idiomas.
- Ejecute `python -m compileall -q .` antes de proponer cambios de Python.

## Traducciones

Consulte `docs/TRADUCCIONES.md`. Para una corrección de idioma normalmente basta con modificar el JSON correspondiente; no es necesario tocar el código.

## Accesibilidad

Al informar o corregir un problema de accesibilidad, indique lector de pantalla (NVDA, JAWS u otro), idioma, versión de Windows, control afectado, teclas utilizadas, texto anunciado y comportamiento esperado.

## Binarios

No añada al repositorio fuente binarios grandes de terceros. Los componentes portables se incorporan al construir la Release y el paquete final se publica como archivo adjunto de la Release.
