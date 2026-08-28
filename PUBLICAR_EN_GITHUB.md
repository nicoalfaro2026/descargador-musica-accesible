# Lista de comprobación para publicar en GitHub

1. Ejecutar `python tools/verificar_traducciones.py`.
2. Ejecutar `python -m compileall -q .`.
3. Probar búsqueda, reproducción y descarga con Español, English, Français, Italiano, Português y Русский.
4. Probar navegación con NVDA; cuando sea posible, realizar una segunda prueba con JAWS.
5. Confirmar que no existan `datos/`, `logs/`, cachés, ZIP de pruebas o credenciales dentro del repositorio.
6. Verificar que `actualizacion.json` apunte exactamente al nombre definitivo del repositorio de GitHub.
7. Elegir una licencia para el código antes de solicitar contribuciones externas.
8. Subir al repositorio únicamente el código fuente y documentación; no los binarios portables grandes de terceros.
9. Construir el ZIP final desde la carpeta de construcción completa con `CREAR_VERSION_DISTRIBUIBLE.bat`.
10. Probar ese ZIP en otra PC o en un usuario de Windows sin Python/Deno/Node instalados.
11. Calcular y publicar el SHA-256 del ZIP.
12. Crear una Release de GitHub y adjuntar el ZIP portable y su SHA-256.
13. No indicar a los usuarios que desactiven Windows Defender. Investigar cualquier falso positivo.
