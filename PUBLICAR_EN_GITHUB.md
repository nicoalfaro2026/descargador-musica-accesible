# Lista de comprobación para publicar en GitHub

1. Ejecutar `python tools/verificar_traducciones.py`.
2. Ejecutar `python tools/verificar_textos_interfaz.py`.
3. Ejecutar la comprobación de sintaxis de los archivos Python.
4. Probar búsqueda, reproducción y descarga con Español, English, Français, Italiano, Português y Русский.
5. Probar navegación con NVDA y, cuando sea posible, realizar una segunda prueba con JAWS.
6. Confirmar que no existan `datos/`, `logs/`, cachés, ZIP de pruebas o credenciales dentro del repositorio.
7. Verificar que `actualizacion.json` apunte al repositorio oficial.
8. Mantener la licencia GPL-3.0 y el archivo LICENSE.
9. Subir al repositorio únicamente el código fuente y documentación; los binarios grandes se distribuyen mediante Releases.
10. Construir el ZIP final desde la carpeta completa con `CREAR_VERSION_DISTRIBUIBLE.bat`.
11. Probar el EXE generado y volver a probar el ZIP descomprimido en una carpeta nueva.
12. Cuando sea posible, probar en otro equipo o perfil de Windows sin el entorno de desarrollo instalado.
13. Calcular y publicar el SHA-256 del ZIP.
14. Crear una Release de GitHub y adjuntar el ZIP portable y su SHA-256.
15. Probar el actualizador automático desde una versión anterior antes de considerar finalizada la publicación.
16. No indicar a las personas usuarias que desactiven Windows Defender. Investigar cualquier falso positivo.
