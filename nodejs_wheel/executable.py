"""Localizador de Node portable compatible con pytubefix."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bases() -> list[Path]:
    bases: list[Path] = []

    def agregar(p: Path | None) -> None:
        if not p:
            return
        try:
            p = p.resolve()
        except Exception:
            pass
        if p not in bases:
            bases.append(p)

    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        agregar(exe)
        agregar(exe / "_internal")
        try:
            agregar(Path(sys._MEIPASS))
        except Exception:
            pass
    else:
        proyecto = Path(__file__).resolve().parent.parent
        agregar(proyecto)
        agregar(proyecto / "_internal")

    return bases


def _root_dir() -> str:
    nombre = "node.exe" if os.name == "nt" else "node"
    for base in _bases():
        if (base / nombre).exists():
            return str(base)
    # Pytubefix concatena ROOT_DIR + node.exe. Devolver la primera ruta permite
    # que el error sea claro si el portable todavía no fue preparado.
    bases = _bases()
    return str(bases[0] if bases else Path.cwd())


ROOT_DIR = _root_dir()
