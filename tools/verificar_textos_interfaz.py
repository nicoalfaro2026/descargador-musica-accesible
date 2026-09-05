from __future__ import annotations

import ast
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = json.loads((RAIZ / "idiomas" / "es.json").read_text(encoding="utf-8"))

FUNCIONES_TRADUCCION = {"traducir", "traducir_dinamico", "traducir_formato", "traducir_clave"}
CONTROLES_WX = {
    "MessageBox", "StaticText", "Button", "CheckBox", "Choice", "StaticBox",
    "Dialog", "DirDialog", "Append", "AppendSubMenu", "AddPage", "InsertColumn",
    "SetName", "SetLabel", "SetStatusText", "TextCtrl", "ListBox",
}
EXCEPCIONES_VISIBLES = {
    "RuntimeError", "ValueError", "ErrorReproductor", "ErrorYoutubeBloqueo",
    "ActualizadorError", "ActualizadorNoConfigurado",
}
ARCHIVOS_RUNTIME = {
    "ui.py", "reproductor.py", "descargador.py", "motor_ytdlp.py",
    "motor_pytubefix.py", "actualizador_app.py", "voz.py", "configuracion.py",
}


def nombre_llamada(nodo):
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        return nodo.attr
    return ""


def constantes_de_llamada(nodo):
    for arg in nodo.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield arg.lineno, arg.value
    for kw in nodo.keywords:
        if kw.arg in {"label", "title", "message", "caption", "value", "heading", "text"}:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                yield kw.value.lineno, kw.value.value


def main():
    errores = []
    for ruta in sorted(RAIZ.glob("*.py")):
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        except Exception as exc:
            errores.append(f"{ruta.name}: no se pudo analizar: {exc}")
            continue

        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call):
                nombre = nombre_llamada(nodo.func)
                if nombre in FUNCIONES_TRADUCCION and nodo.args:
                    arg = nodo.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value not in CATALOGO:
                            errores.append(
                                f"{ruta.name}:{arg.lineno}: texto usado por {nombre} no está en es.json: {arg.value!r}"
                            )
                if nombre in CONTROLES_WX:
                    for linea, texto in constantes_de_llamada(nodo):
                        if texto.strip() and texto not in CATALOGO and not texto.startswith(("http://", "https://")):
                            errores.append(
                                f"{ruta.name}:{linea}: texto directo de interfaz no está en es.json: {texto!r}"
                            )

            if ruta.name in ARCHIVOS_RUNTIME and isinstance(nodo, ast.Raise) and isinstance(nodo.exc, ast.Call):
                nombre = nombre_llamada(nodo.exc.func)
                if nombre in EXCEPCIONES_VISIBLES and nodo.exc.args:
                    arg = nodo.exc.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value not in CATALOGO:
                        errores.append(
                            f"{ruta.name}:{arg.lineno}: mensaje de error visible no está en es.json: {arg.value!r}"
                        )

    if errores:
        print("VERIFICACIÓN DE INTERFAZ FALLIDA")
        for e in errores:
            print("-", e)
        return 1

    print("VERIFICACIÓN DE INTERFAZ CORRECTA: no se detectaron textos estáticos visibles fuera del catálogo maestro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
