from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
IDIOMAS = RAIZ / "idiomas"
CODIGOS = ("es", "en", "fr", "it", "pt", "ru")
RE_VARIABLE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


def cargar(codigo: str):
    ruta = IDIOMAS / f"{codigo}.json"
    with ruta.open("r", encoding="utf-8") as archivo:
        datos = json.load(archivo)
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta.name}: el contenido raíz debe ser un objeto JSON")
    return datos


def variables(texto):
    return sorted(RE_VARIABLE.findall(str(texto)))


def main() -> int:
    errores = []
    catalogos = {}
    for codigo in CODIGOS:
        try:
            catalogos[codigo] = cargar(codigo)
        except Exception as exc:
            errores.append(f"{codigo}: no se pudo cargar: {exc}")

    if errores:
        for error in errores:
            print("ERROR:", error)
        return 1

    maestro = catalogos["es"]
    claves_maestro = set(maestro)
    print(f"Catálogo maestro: es.json - {len(maestro)} entradas")

    for codigo in CODIGOS:
        datos = catalogos[codigo]
        claves = set(datos)
        faltan = sorted(claves_maestro - claves)
        sobran = sorted(claves - claves_maestro)
        vacias = sorted(k for k, v in datos.items() if not isinstance(v, str) or not v.strip())

        if faltan:
            errores.append(f"{codigo}: faltan {len(faltan)} claves: {faltan[:10]}")
        if sobran:
            errores.append(f"{codigo}: sobran {len(sobran)} claves: {sobran[:10]}")
        if vacias:
            errores.append(f"{codigo}: hay {len(vacias)} valores vacíos/no textuales: {vacias[:10]}")

        for clave in sorted(claves_maestro & claves):
            vars_es = variables(maestro[clave])
            vars_destino = variables(datos[clave])
            if vars_es != vars_destino:
                errores.append(
                    f"{codigo}: variables distintas en {clave!r}: es={vars_es}, destino={vars_destino}"
                )

        print(f"{codigo}.json: {len(datos)} entradas")

    if errores:
        print("\nVERIFICACIÓN FALLIDA")
        for error in errores:
            print("-", error)
        return 1

    print("\nVERIFICACIÓN CORRECTA: todos los idiomas tienen las mismas claves, valores y variables válidas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
