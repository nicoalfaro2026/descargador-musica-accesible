# Descargador de Música Accesible 1.8.1

Esta versión está centrada en mantenimiento, accesibilidad y robustez.

## Búsquedas en YouTube

- La lista de resultados ya no muestra la URL como columna visible.
- Cada fila presenta índice, título, canal, fecha de publicación, visualizaciones y duración cuando YouTube proporciona esos datos.
- Los datos que falten se completan de forma diferida al permanecer sobre un resultado, evitando realizar cientos de consultas de una sola vez.
- Puede preferirse la información de YouTube en el idioma seleccionado en la aplicación. Si YouTube no ofrece una traducción, se conserva el título disponible.

## Respaldo con sesión del navegador

- Se añadió una opción voluntaria para utilizar como segundo intento una sesión ya iniciada en un navegador compatible cuando YouTube solicite verificación o inicio de sesión.
- El primer intento continúa realizándose sin cookies del navegador.
- La función está desactivada por defecto.
- Puede elegirse detección automática, Chrome, Edge, Firefox, Brave, Opera, Vivaldi o Chromium.
- El programa no guarda las cookies en el historial, los registros ni la configuración.

## Actualización de la librería de descarga

- La actualización manual compara primero la versión instalada con la última disponible.
- Si ya se dispone de la versión más reciente, el programa informa que no hay una actualización y evita descargar nuevamente la misma versión.
- Se añadió una opción para actualizar automáticamente este componente solo cuando se detecte una versión realmente más nueva.

## Inicio y cierre

- La revisión automática de actualizaciones se retrasa para no interrumpir el mensaje de bienvenida.
- El cierre mantiene el proceso activo brevemente para dar tiempo al lector de pantalla a terminar el mensaje de despedida.
- La ventana de "Actualización completada" que se muestra tras actualizar el programa ahora incluye, cuando existen, las novedades visibles de la nueva versión antes del botón Aceptar.

## Soporte de JAWS y eliminación de voces de Windows

- El programa ahora habla directamente con JAWS cuando está en ejecución, además de con NVDA.
- Se eliminaron por completo las voces de respaldo de Windows (SAPI, PowerShell y pyttsx3), que antes podían activarse y anunciar con una voz distinta a la del lector de pantalla de la persona usuaria (por ejemplo, la voz "Elena").
- Si ni NVDA ni JAWS están en ejecución, el programa ya no habla con ninguna voz propia: solo emite un sonido breve.

## Manual

- Nuevo manual de usuario profesional en PDF accesible y TXT.
- Disponible en español, inglés, francés, italiano, portugués y ruso.
- El manual describe únicamente funciones visibles para la persona usuaria y evita detalles técnicos innecesarios.
- Incluye autenticación mediante navegador, funcionamiento portable, tamaño del programa, solución de problemas y contacto con el desarrollador.

## Contacto

Desarrollado por Nicolás Alfaro.

Correo: alfaronico8@gmail.com

Proyecto: https://github.com/nicoalfaro2026/descargador-musica-accesible

## Ajustes posteriores a pruebas con NVDA

- La bienvenida se anuncia después de que la ventana ya es visible y el foco de trabajo se entrega después del mensaje, evitando que el cuadro URL interrumpa el saludo.
- La despedida mantiene la aplicación activa más tiempo para permitir que NVDA finalice el anuncio.
- Las URL dejan de mostrarse como columnas en Canales y listas y en los videos de una colección. Se conservan internamente para las acciones del programa.
- Corregido el foco inicial y un anuncio incorrecto de NVDA al abrir Herramientas > Opciones con un archivo cookies.txt ya guardado (NVDA leía de más la etiqueta "Archivo cookies.txt:" en vez de anunciar solo el primer control). La causa era el orden real de las ventanas internas del diálogo, no el foco en sí; se corrigió reordenando la creación de esos controles.

## Canal del motor de descarga

- En Herramientas, Opciones puede elegirse el canal de actualización del motor: Estable, Nightly o Master / Desarrollo.
- Estable continúa como valor predeterminado para priorizar compatibilidad.
- Nightly permite recibir correcciones recientes con mayor rapidez cuando sea necesario.
- Master / Desarrollo queda disponible para pruebas y casos donde una corrección todavía no haya llegado a los otros canales.
- El cambio de canal se aplica al actualizar el motor y queda guardado en la configuración.

## Anuncios de descarga

- Se eliminó el aviso duplicado "Proceso completado" al finalizar una descarga.
- El lector de pantalla recibe un único anuncio final claro: "Descarga completada", seguido del título.
- El campo de progreso termina en 100 % sin repetir el mensaje final.
- El aviso de conversión ya no menciona MP3 cuando se está utilizando otro formato.

## Favoritos

- Se añadió Herramientas > Favoritos para conservar videos y volver a ellos más adelante.
- Alt+F agrega o quita el video enfocado sin abrir menús adicionales.
- Enter sobre un video mantiene el menú de acciones habitual e incorpora Agregar a favoritos o Quitar de favoritos según corresponda.
- El programa anuncia de forma breve "Se agregó a tus favoritos" o "Se quitó de tus favoritos".
- La lista de Favoritos muestra índice, título, canal y tipo, sin mostrar la URL.
- Desde Favoritos se puede reproducir, descargar, consultar información, copiar la URL o quitar el elemento.
- Los favoritos se guardan en la carpeta de datos del programa, se mantienen al cerrar y no se duplican aunque una misma URL de YouTube tenga parámetros diferentes.
- Se evitó un conflicto de Alt+F con el menú File/Fichier en los idiomas donde la letra F era un mnemónico de menú.
- Se corrigió además el texto del atajo de cancelación para evitar el aviso interno de wxPython causado por "Ctrl+K / Esc"; Escape continúa funcionando como atajo real.

## Cola de descargas

- Se añadió Herramientas > Cola de descargas para reunir varios videos y descargarlos de forma secuencial.
- Alt+Q agrega el video enfocado a la cola sin abrir menús adicionales.
- Enter sobre un video incorpora la acción Agregar a la cola de descargas.
- En Canales y listas, Ctrl+Shift+Q agrega juntos los videos marcados con Espacio.
- La cola evita duplicados, conserva los elementos pendientes al cerrar y nunca se inicia automáticamente al volver a abrir el programa.
- La lista de la cola muestra índice, título, canal y estado, sin mostrar la URL.
- Al iniciar se utilizan el formato, la calidad o resolución y la carpeta de destino seleccionados en la ventana principal.
- El lector de pantalla anuncia la posición de cada elemento, por ejemplo "Descargando 2 de 8".
- Es posible cancelar únicamente la descarga actual y continuar con la siguiente, o detener toda la cola conservando los pendientes.
- Los elementos con error permanecen en la cola para poder reintentarlos.
- Suprimir quita el elemento enfocado y Vaciar cola elimina todos los pendientes cuando la cola no está en ejecución.
- Corregida la apertura de Herramientas > Cola de descargas cuando ya existen elementos guardados.

## Playlists mejoradas

- Las playlists continúan dentro de Canales y listas; no se añadió una pestaña nueva.
- Enter sobre una playlist permite ver su contenido, agregarla completa a la cola, seleccionar un rango, usar Favoritos, consultar información o copiar la URL.
- Una URL de playlist pegada directamente en Descargar por URL se detecta y abre las mismas acciones.
- Ver contenido permite cargar una cantidad determinada o todos los elementos disponibles.
- Espacio marca elementos y Alt+Q agrega los marcados a la Cola de descargas; si no hay marcados, agrega solo el enfocado.
- Se añadió selección por rango, por ejemplo desde el elemento 5 hasta el 20.
- Las playlists pueden guardarse en Favoritos y desde allí volver a abrirse, agregarse completas a la cola o procesarse por rango.
- La adición masiva a la cola se guarda en una sola operación para mejorar rendimiento y evitar escrituras innecesarias.
- Las URLs siguen siendo internas y no se muestran en las listas accesibles.
- Corregida la detección de solicitudes de autenticación de YouTube cuando el mensaje aparece traducido. El respaldo mediante sesión del navegador ahora también se activa durante la reproducción interna.
- Añadido Archivo cookies.txt como método recomendado de autenticación de YouTube en Windows, con validación Netscape y guía accesible para Chrome y Firefox.
- La lectura directa de sesión del navegador permanece como alternativa. Los errores DPAPI ya no se repiten elemento por elemento.
- La Cola de descargas se pausa ante un problema de autenticación y conserva los elementos pendientes.
- Añadida una pausa interna de 3 segundos entre elementos de la Cola para reducir solicitudes consecutivas sin ralentizar en exceso el proceso.
- Opciones: la autenticación de YouTube ahora muestra solo los controles correspondientes al método seleccionado. Con Archivo cookies.txt aparece primero el botón de selección y luego la ruta; con Sesión del navegador desaparecen los controles del archivo y aparece el selector del navegador.
- Opciones: el anuncio de cookies.txt se realiza después de cerrar el selector de archivos para que NVDA y JAWS confirmen claramente que el archivo fue cargado.
- Opciones: se retiraron textos explicativos extensos del diálogo para evitar lecturas innecesarias; la información detallada permanece en la ayuda y el manual.
- wxPython: corregida la jerarquía de controles dentro de StaticBoxSizer para eliminar los avisos internos mostrados al abrir Opciones.
- Accesibilidad: eliminada la entrada histórica con el acelerador inválido "Ctrl+K / Esc"; el menú utiliza Ctrl+K y Escape sigue funcionando mediante su manejo de teclado.

## Reproductor interno

- El reproductor interno distingue cuatro situaciones en lugar de una sola bolsa genérica: autenticación de YouTube requerida, video no disponible (privado, eliminado, con copyright, restringido por edad o país), falta el componente MPV, o error general.
- La detección y el mensaje amigable se comparten entre la ruta de yt-dlp externo y la ruta interna (librería Python), tanto para reproducción como para descarga.
- El mensaje de "falta MPV" ahora solo aparece cuando realmente falla la inicialización de python-mpv/mpv-1.dll, no ante cualquier error del reproductor.
- El reproductor interno usa el mismo archivo cookies.txt / sesión del navegador que las descargas, con el mismo mecanismo de reintento.

## Corrección de traducción

- Se corrigió una clave que solo existía en español ("No hay un archivo cookies.txt seleccionado.", usada en el tooltip de la ruta de cookies.txt en Herramientas, Opciones); ahora está sincronizada en los seis idiomas.
