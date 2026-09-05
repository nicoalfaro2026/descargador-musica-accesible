# Documentación técnica

Este documento está dirigido a desarrolladores y colaboradores. La información técnica se mantiene separada del manual de usuario para conservar una experiencia sencilla y accesible.

## Estructura general

La interfaz de Windows se implementa principalmente con wxPython. `ui.py` coordina la ventana principal y delega tareas en módulos especializados:

- `descargador.py`: búsqueda, información, reproducción temporal y descargas.
- `motor_ytdlp.py`: localización y actualización del motor principal.
- `motor_pytubefix.py`: respaldo específico para YouTube cuando corresponde.
- `reproductor.py`: reproducción interna.
- `configuracion.py`: preferencias persistentes.
- `historial.py`: historial limitado de descargas.
- `favoritos.py`: persistencia, normalización de URL y eliminación de duplicados de Favoritos.
- `cola_descargas.py`: persistencia y estados de la cola, normalización de URL, reintentos y eliminación de duplicados.
- `i18n.py` e `idiomas/`: internacionalización.
- `actualizador_app.py`: actualizaciones de la aplicación desde GitHub Releases.

## Estrategia de descarga

El flujo intenta primero el motor principal sin utilizar una sesión del navegador. Cuando YouTube devuelve un error compatible con verificación o inicio de sesión, y la persona usuaria activó expresamente el respaldo con navegador, se puede realizar un segundo intento utilizando la sesión local del navegador seleccionado.

Las cookies de sesión no se escriben en los logs, el historial ni los archivos de configuración.

El motor alternativo se utiliza únicamente para fallos compatibles. Errores como falta de conexión, contenido privado o eliminado no deben provocar intentos innecesarios con múltiples motores.

## Búsqueda y enriquecimiento de metadatos

La búsqueda inicial utiliza un modo rápido para evitar que una consulta de 100 o 300 resultados genere centenares de solicitudes completas. Los datos ausentes, como canal, fecha o visualizaciones, se solicitan posteriormente solo para el resultado sobre el que la persona usuaria permanece enfocada.


## Favoritos

Los favoritos se guardan en `datos/favoritos.json`, carpeta que el actualizador preserva junto con el resto de datos personales de la aplicación. La URL se conserva internamente porque es necesaria para reproducir, descargar y copiar, pero no se muestra como columna en la interfaz.

Para YouTube se normalizan las formas habituales de enlace (`watch`, `youtu.be`, `shorts`, `embed` y `live`) a una clave estable por identificador de video. Esto evita guardar el mismo contenido varias veces por parámetros adicionales de una URL.


## Cola de descargas

La cola se guarda en `datos/cola_descargas.json`, que queda fuera del repositorio y se preserva durante las actualizaciones. Los estados persistentes son Pendiente, Descargando y Error. Al iniciar el programa, cualquier elemento que hubiera quedado como Descargando por un cierre inesperado vuelve a Pendiente y nunca se inicia automáticamente.

La interfaz utiliza Alt+Q para agregar el video enfocado y Ctrl+Shift+Q para agregar los videos marcados en Canales y listas. Al iniciar la cola se toman el formato, la calidad o resolución y la carpeta seleccionados en ese momento. Las descargas se procesan de forma secuencial. Los elementos completados salen de la cola y quedan registrados en el historial; los errores permanecen para reintento.

Cancelar únicamente la descarga actual elimina ese elemento y continúa con el siguiente. Detener la cola conserva el elemento actual y los pendientes para continuar posteriormente.

## Internacionalización

`idiomas/es.json` es el catálogo maestro. Todos los idiomas deben mantener las mismas claves y variables. Antes de publicar:

```text
python tools/verificar_traducciones.py
python tools/verificar_textos_interfaz.py
```

## Distribución

Los binarios grandes de terceros no forman parte del historial normal del repositorio fuente. La versión portable se construye mediante el proceso de empaquetado y se publica como archivo adjunto en GitHub Releases.

La compilación de PyInstaller mantiene UPX desactivado.

## Privacidad y diagnósticos

Nunca registrar contraseñas, cookies, tokens ni contenido de sesión. Los futuros informes de diagnóstico deben incluir únicamente información técnica necesaria para reproducir un problema.
