# -*- coding: utf-8 -*-
"""Copias seguras usadas por el constructor portable.

Evita depender de Robocopy y mantiene fuera del build los residuos de desarrollo.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from pathlib import Path

EXCLUDED_DIRS = {
    "build",
    "dist",
    "logs",
    "datos",
    "__pycache__",
    "PAQUETE_PARA_DISTRIBUIR",
    ".git",
}

EXCLUDED_FILES = {
    "diagnostico_dependencias.txt",
    "construccion_portable.log",
    "construccion_1_8_0.log",
    "HABILITAR_RUTAS_LARGAS_WINDOWS.bat",
}

EXCLUDED_PATTERNS = (
    "*.zip",
    "*.pyc",
    "*.sha256.txt",
)


def _archivo_excluido(nombre: str) -> bool:
    if nombre in EXCLUDED_FILES:
        return True
    return any(fnmatch.fnmatch(nombre.lower(), patron.lower()) for patron in EXCLUDED_PATTERNS)


def copiar_fuente(src: Path, dst: Path) -> None:
    src = src.resolve()
    dst.mkdir(parents=True, exist_ok=True)
    copiados = 0
    omitidos = 0

    for raiz, directorios, archivos in os.walk(src):
        raiz_path = Path(raiz)
        conservados = []
        for nombre in directorios:
            if nombre in EXCLUDED_DIRS:
                omitidos += 1
            else:
                conservados.append(nombre)
        directorios[:] = conservados

        relativo = raiz_path.relative_to(src)
        destino_raiz = dst / relativo
        destino_raiz.mkdir(parents=True, exist_ok=True)

        for nombre in archivos:
            if _archivo_excluido(nombre):
                omitidos += 1
                continue
            origen = raiz_path / nombre
            destino = destino_raiz / nombre
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino)
            copiados += 1

    print(f"Copia de fuente terminada. Archivos copiados: {copiados}. Omitidos: {omitidos}.")


def copiar_final(src: Path, dst: Path) -> None:
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(f"No existe la carpeta compilada: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    total = sum(1 for p in dst.rglob("*") if p.is_file())
    print(f"Copia final terminada. Archivos copiados: {total}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("modo", choices=["fuente", "final"])
    parser.add_argument("origen")
    parser.add_argument("destino")
    args = parser.parse_args()

    src = Path(args.origen)
    dst = Path(args.destino)
    if not src.exists():
        raise FileNotFoundError(f"No existe la carpeta fuente: {src}")

    if args.modo == "fuente":
        copiar_fuente(src, dst)
    else:
        copiar_final(src, dst)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR DE COPIA: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
