"""Prepara un Node.js portable para el motor alternativo pytubefix.

Descarga únicamente la distribución oficial de Node.js, verifica SHA-256 y
extrae solo node.exe. No instala Node en Windows ni modifica PATH/Registro.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
DESTINO = BASE / ("node.exe" if os.name == "nt" else "node")
INDEX_URL = "https://nodejs.org/dist/index.json"
MIN_MAJOR = 22
UA = "DescargadorMusicaAccesible/1.8.0"


def _version_ejecutable(ruta: Path) -> str | None:
    if not ruta.exists():
        return None
    try:
        p = subprocess.run(
            [str(ruta), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        texto = (p.stdout or p.stderr or "").strip()
        if p.returncode == 0 and re.match(r"^v?\d+\.\d+\.\d+", texto):
            return texto
    except Exception:
        return None
    return None


def _major(version: str | None) -> int:
    m = re.search(r"(\d+)", version or "")
    return int(m.group(1)) if m else 0


def _abrir(url: str, timeout: int = 45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def _copiar_node_del_sistema() -> str | None:
    candidato = shutil.which("node") or shutil.which("node.exe")
    if not candidato:
        return None
    ruta = Path(candidato)
    ver = _version_ejecutable(ruta)
    if _major(ver) < MIN_MAJOR:
        return None
    if ruta.resolve() != DESTINO.resolve():
        shutil.copy2(ruta, DESTINO)
    return ver


def _seleccionar_release() -> dict:
    with _abrir(INDEX_URL) as resp:
        datos = json.load(resp)
    candidatos = []
    for rel in datos:
        version = str(rel.get("version", ""))
        files = rel.get("files") or []
        if "win-x64-zip" not in files:
            continue
        if _major(version) < MIN_MAJOR:
            continue
        if rel.get("lts"):
            candidatos.append(rel)
    if not candidatos:
        for rel in datos:
            version = str(rel.get("version", ""))
            files = rel.get("files") or []
            if "win-x64-zip" in files and _major(version) >= MIN_MAJOR:
                candidatos.append(rel)
    if not candidatos:
        raise RuntimeError("No se encontró una versión compatible de Node.js para Windows x64.")
    return candidatos[0]


def preparar() -> dict:
    actual = _version_ejecutable(DESTINO)
    if _major(actual) >= MIN_MAJOR:
        return {"ok": True, "version": actual, "ruta": str(DESTINO), "origen": "existente"}

    copiada = _copiar_node_del_sistema()
    if _major(copiada) >= MIN_MAJOR:
        return {"ok": True, "version": copiada, "ruta": str(DESTINO), "origen": "sistema"}

    rel = _seleccionar_release()
    version = str(rel["version"])
    nombre = f"node-{version}-win-x64.zip"
    base_url = f"https://nodejs.org/dist/{version}"

    with _abrir(f"{base_url}/SHASUMS256.txt") as resp:
        checksums = resp.read().decode("utf-8", "replace")
    esperado = None
    for linea in checksums.splitlines():
        partes = linea.strip().split()
        if len(partes) >= 2 and partes[-1].lstrip("*") == nombre:
            esperado = partes[0].lower()
            break
    if not esperado or not re.fullmatch(r"[0-9a-f]{64}", esperado):
        raise RuntimeError("No se pudo obtener el SHA-256 oficial de Node.js.")

    with tempfile.TemporaryDirectory(prefix="dma_node_") as tmp:
        zip_path = Path(tmp) / nombre
        h = hashlib.sha256()
        with _abrir(f"{base_url}/{nombre}", timeout=120) as resp, zip_path.open("wb") as out:
            while True:
                bloque = resp.read(1024 * 1024)
                if not bloque:
                    break
                out.write(bloque)
                h.update(bloque)
        real = h.hexdigest().lower()
        if real != esperado:
            raise RuntimeError(f"SHA-256 de Node.js no coincide: {real} != {esperado}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            miembro = next((n for n in zf.namelist() if n.lower().endswith("/node.exe")), None)
            if not miembro:
                raise RuntimeError("La distribución oficial de Node.js no contiene node.exe.")
            with zf.open(miembro) as src, DESTINO.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    ver = _version_ejecutable(DESTINO)
    if _major(ver) < MIN_MAJOR:
        try:
            DESTINO.unlink()
        except Exception:
            pass
        raise RuntimeError("node.exe se preparó, pero no pudo ejecutarse correctamente.")

    return {"ok": True, "version": ver, "ruta": str(DESTINO), "origen": "oficial"}


if __name__ == "__main__":
    try:
        r = preparar()
        print(f"Node portable listo: {r['version']} - {r['ruta']}")
    except Exception as exc:
        print(f"ERROR preparando Node portable: {exc}")
        raise SystemExit(1)
