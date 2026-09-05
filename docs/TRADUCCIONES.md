# Guía de traducciones

## Catálogo maestro

`idiomas/es.json` es la referencia del proyecto. Cada uno de estos archivos debe contener exactamente las mismas claves:

- `es.json`
- `en.json`
- `fr.json`
- `it.json`
- `pt.json`
- `ru.json`

No es necesario modificar archivos `.py` para corregir una traducción normal.

## Claves especiales

Algunas claves empiezan y terminan con doble guion bajo, por ejemplo `__help.shortcuts__`. Son identificadores estables para textos largos o dinámicos. No cambie el nombre de la clave; traduzca únicamente su valor.

## Variables

Los textos pueden contener variables como `{total}`, `{formato}`, `{ruta}`, `{detalle}` o `{porcentaje}`. Deben conservarse exactamente con las llaves y el mismo nombre. Es posible cambiar su posición dentro de la frase si la gramática del idioma lo requiere.

Ejemplo:

```json
"Buscando {cantidad} resultados": "Searching for {cantidad} results"
```

## Atajos y nombres técnicos

No traduzca comandos, rutas, nombres de archivos o nombres técnicos cuando eso altere su significado. Por ejemplo: `yt-dlp`, `FFmpeg`, `MPV`, `NVDA`, `JAWS`, `python-mpv`, `Ctrl`, `Alt`, `Enter`, nombres de archivos y extensiones.

## Verificación

Ejecute desde la raíz del proyecto:

```text
python tools/verificar_traducciones.py
```

El verificador comprueba:

1. JSON válido;
2. mismas claves en todos los idiomas;
3. valores no vacíos;
4. que las variables `{...}` coincidan con el catálogo español;
5. que no falten los textos estables utilizados por el programa.

Una traducción automática o asistida por IA debe revisarse, cuando sea posible, por una persona nativa que utilice el programa con lector de pantalla. La revisión debe comprobar tanto el idioma como la comprensión de etiquetas, diálogos, anuncios y atajos.

## Revisión externa

Para pedir a una persona que revise italiano, por ejemplo, basta con entregarle `idiomas/it.json`. No necesita recibir el código fuente. Al devolver el archivo se ejecuta el verificador y después se prueba el programa con el idioma correspondiente.
