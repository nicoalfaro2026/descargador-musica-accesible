"""Prepara dependencias portables del motor de descarga en Windows.

Descarga Deno desde la release oficial más reciente de GitHub, verifica el
SHA-256 publicado por la API cuando está disponible y deja deno.exe junto al
proyecto. No instala Deno en Windows ni modifica PATH.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
API_DENO = "https://api.github.com/repos/denoland/deno/releases/latest"
ASSET_DENO = "deno-x86_64-pc-windows-msvc.zip"


def _request(url):
    return urllib.request.Request(url, headers={
        "User-Agent": "DescargadorMusicaAccesible/1.8.0-robusto",
        "Accept": "application/vnd.github+json",
    })


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _checksum_esperado(release, asset):
    digest = str(asset.get("digest") or "").strip().lower()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1].strip()

    nombre_checksum = ASSET_DENO + ".sha256sum"
    asset_checksum = next(
        (a for a in release.get("assets", []) if a.get("name") == nombre_checksum),
        None,
    )
    if not asset_checksum or not asset_checksum.get("browser_download_url"):
        return None

    with urllib.request.urlopen(_request(asset_checksum["browser_download_url"]), timeout=30) as respuesta:
        texto = respuesta.read().decode("utf-8", errors="replace")
    match = __import__("re").search(r"\b([0-9a-fA-F]{64})\b", texto)
    return match.group(1).lower() if match else None


def _version_compatible(texto):
    match = re.search(r"(?:^|\s)(\d+)\.(\d+)(?:\.(\d+))?", str(texto or ""))
    if not match:
        return False
    version = tuple(int(x or 0) for x in match.groups())
    return version >= (2, 3, 0)


def _version_deno(ruta):
    try:
        r = subprocess.run([str(ruta), "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        if r.returncode == 0:
            return (r.stdout or "").splitlines()[0].strip()
    except Exception:
        pass
    return None


def preparar_deno():
    destino = BASE / "deno.exe"
    actual = _version_deno(destino) if destino.exists() else None

    print("Consultando la versión estable más reciente de Deno...")
    try:
        with urllib.request.urlopen(_request(API_DENO), timeout=30) as respuesta:
            release = json.loads(respuesta.read().decode("utf-8"))
    except Exception:
        if actual and _version_compatible(actual):
            print(f"No se pudo consultar GitHub. Se conserva Deno portable compatible: {actual}")
            return destino
        if actual:
            raise RuntimeError(f"La copia local de Deno no es compatible con yt-dlp: {actual}")
        raise

    tag = str(release.get("tag_name") or "").strip().lstrip("v")
    if actual and tag and tag in actual:
        print(f"Deno portable ya está actualizado: {actual}")
        return destino

    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_DENO), None)
    if not asset:
        raise RuntimeError(f"No se encontró el archivo oficial {ASSET_DENO} en la última versión de Deno.")

    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("GitHub no devolvió la URL del Deno portable.")

    with tempfile.TemporaryDirectory(prefix="dma_deno_") as tmpdir:
        zip_tmp = Path(tmpdir) / ASSET_DENO
        print(f"Descargando Deno {release.get('tag_name', '')} portable...")
        with urllib.request.urlopen(_request(url), timeout=120) as entrada, open(zip_tmp, "wb") as salida:
            shutil.copyfileobj(entrada, salida, length=1024 * 1024)

        if zip_tmp.stat().st_size < 5 * 1024 * 1024:
            raise RuntimeError("La descarga de Deno parece incompleta.")

        esperado = _checksum_esperado(release, asset)
        if not esperado:
            raise RuntimeError("No se pudo obtener el SHA-256 oficial de Deno. Por seguridad no se instalará el archivo.")
        obtenido = _sha256(zip_tmp)
        if obtenido.lower() != esperado.lower():
            raise RuntimeError("La verificación SHA-256 de Deno no coincide. No se instalará el archivo.")
        print("SHA-256 de Deno verificado correctamente.")

        with zipfile.ZipFile(zip_tmp) as zf:
            nombres = {Path(n).name.lower(): n for n in zf.namelist()}
            miembro = nombres.get("deno.exe")
            if not miembro:
                raise RuntimeError("El ZIP oficial de Deno no contiene deno.exe.")
            extraido = Path(tmpdir) / "deno.exe"
            with zf.open(miembro) as entrada, open(extraido, "wb") as salida:
                shutil.copyfileobj(entrada, salida)
            shutil.copy2(extraido, destino)

    version = _version_deno(destino)
    if not version:
        try:
            destino.unlink()
        except Exception:
            pass
        raise RuntimeError("deno.exe se descargó, pero Windows no pudo ejecutarlo correctamente.")

    print(f"Deno portable listo: {version}")
    print(f"Ruta: {destino}")
    return destino


if __name__ == "__main__":
    if os.name != "nt":
        print("Este preparador descarga el Deno portable de Windows. Ejecútelo en la PC Windows del programa.")
        sys.exit(0)
    try:
        preparar_deno()
    except Exception as exc:
        print(f"ERROR preparando Deno: {exc}")
        sys.exit(1)
