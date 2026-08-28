# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

proyecto = Path(SPECPATH)

binaries = []
for nombre in (
    "ffmpeg.exe", "ffprobe.exe", "nvdaControllerClient64.dll", "mpv-1.dll",
    "yt-dlp.exe", "deno.exe", "node.exe", "qjs.exe"
):
    ruta = proyecto / nombre
    if ruta.exists():
        binaries.append((str(ruta), "."))

datas = []
for carpeta, destino in (
    ("nvda_controller_client", "nvda_controller_client"),
    ("sonidos", "sonidos"),
    ("idiomas", "idiomas"),
    ("manuales", "manuales"),
):
    ruta = proyecto / carpeta
    if ruta.exists():
        datas.append((str(ruta), destino))

archivo_actualizacion = proyecto / "actualizacion.json"
if archivo_actualizacion.exists():
    datas.append((str(archivo_actualizacion), "."))

for archivo_doc in (
    "MANUAL_DE_USUARIO_DESCARGADOR_MUSICA_ACCESIBLE.txt",
    "NOTAS_MOTOR_DESCARGA.txt", "NOTAS_DEPENDENCIAS.txt", "CAMBIOS.txt",
    "LEEME_USUARIO_FINAL.txt",
):
    ruta_doc = proyecto / archivo_doc
    if ruta_doc.exists():
        datas.append((str(ruta_doc), "."))

hiddenimports = [
    "wx",
    "yt_dlp",
    "mpv",
    "motor_ytdlp",
    "motor_pytubefix",
    "i18n",
    "actualizador_app",
    "pyttsx3",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "comtypes",
    "comtypes.client",
    "nodejs_wheel",
    "nodejs_wheel.executable",
]
hiddenimports += collect_submodules("yt_dlp_ejs")
hiddenimports += collect_submodules("pytubefix")
# Pytubefix lleva JS/protobuf y otros datos que no siempre son detectados por
# análisis de imports. Se incluyen explícitamente.
datas += collect_data_files("pytubefix")

a = Analysis(
    [str(proyecto / "main.py")],
    pathex=[str(proyecto)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["nodejs_wheel_binaries"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DescargadorMusicaAccesible",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DMA",
)
