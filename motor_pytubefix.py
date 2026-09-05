"""Motor alternativo basado en pytubefix.

Este módulo NO reemplaza yt-dlp. Solo se usa como respaldo automático cuando
el motor principal falla por un problema de extracción/formato compatible con
un segundo intento. Mantenerlo separado permite actualizar o quitar el motor
alternativo sin tocar la interfaz accesible.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

from i18n import traducir, traducir_formato

try:
    from importlib.metadata import version as version_paquete
except Exception:  # pragma: no cover
    version_paquete = None

try:
    from pytubefix import YouTube
    try:
        from pytubefix.contrib.search import Search
    except Exception:
        Search = None
    _ERROR_IMPORTACION = None
except Exception as exc:  # pytubefix es deliberadamente opcional al arrancar.
    YouTube = None
    Search = None
    _ERROR_IMPORTACION = exc


class MotorAlternativoCancelado(Exception):
    """Señal interna para detener una descarga del motor alternativo."""


def disponible():
    return YouTube is not None


def version_instalada():
    if not disponible():
        return None
    if version_paquete is None:
        return "Detectada"
    try:
        return version_paquete("pytubefix")
    except Exception:
        return "Detectada"


def _node_portable():
    """Devuelve (ruta, versión) del Node que pytubefix usará, si está disponible."""
    try:
        import nodejs_wheel.executable as node_exec
        nombre = "node.exe" if os.name == "nt" else "node"
        ruta = Path(node_exec.ROOT_DIR) / nombre
        if not ruta.exists():
            return None, None
        p = subprocess.run(
            [str(ruta), "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        version = (p.stdout or p.stderr or "").strip() if p.returncode == 0 else None
        return str(ruta), version
    except Exception:
        return None, None


def detalle_disponibilidad():
    if disponible():
        ruta_node, version_node = _node_portable()
        base = f"pytubefix {version_instalada() or 'detectada'}"
        if ruta_node:
            return f"{base} (Node portable {version_node or 'detectado'})"
        return f"{base} (Node portable no encontrado; respaldo limitado)"
    if _ERROR_IMPORTACION:
        return f"No disponible: {_ERROR_IMPORTACION}"
    return "No disponible"


def _valor(objeto, nombre, predeterminado=None):
    try:
        valor = getattr(objeto, nombre, predeterminado)
        if callable(valor):
            return valor()
        return valor
    except Exception:
        return predeterminado


def _fecha_yyyymmdd(valor):
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y%m%d")
    texto = str(valor or "").strip()
    if not texto:
        return None
    solo_digitos = re.sub(r"\D", "", texto)
    if len(solo_digitos) >= 8:
        return solo_digitos[:8]
    return texto


def _info(yt, url=""):
    titulo = _valor(yt, "title", "Sin título") or "Sin título"
    canal = _valor(yt, "author", None) or _valor(yt, "channel_id", None) or "No disponible"
    duracion = _valor(yt, "length", None)
    visualizaciones = _valor(yt, "views", None)
    fecha = _fecha_yyyymmdd(_valor(yt, "publish_date", None))
    watch_url = _valor(yt, "watch_url", None) or url

    try:
        duracion_num = int(duracion) if duracion is not None else None
    except Exception:
        duracion_num = None

    return {
        "title": titulo,
        "channel": canal,
        "uploader": canal,
        "duration": duracion_num,
        "view_count": visualizaciones,
        "upload_date": fecha,
        "webpage_url": watch_url,
        "url": watch_url,
        "_motor": "pytubefix",
    }


def obtener_informacion(url):
    if not disponible():
        raise RuntimeError("El motor alternativo pytubefix no está instalado.")
    yt = YouTube(str(url))
    return _info(yt, str(url))


def buscar(texto, limite=20):
    if Search is None:
        raise RuntimeError("La búsqueda del motor alternativo pytubefix no está disponible.")

    limite = max(1, int(limite or 20))
    resultados = []
    busqueda = Search(str(texto))

    for video in list(_valor(busqueda, "videos", []) or []):
        try:
            resultados.append(_info(video, _valor(video, "watch_url", "") or ""))
        except Exception:
            continue
        if len(resultados) >= limite:
            break

    return resultados


def obtener_url_reproduccion(url):
    if not disponible():
        raise RuntimeError("El motor alternativo pytubefix no está instalado.")

    yt = YouTube(str(url))
    streams = _valor(yt, "streams", None)
    if streams is None:
        raise RuntimeError("pytubefix no devolvió formatos reproducibles.")

    stream = streams.get_audio_only()
    if not stream:
        try:
            stream = streams.filter(only_audio=True).order_by("abr").desc().first()
        except Exception:
            stream = None

    stream_url = _valor(stream, "url", None) if stream else None
    if not stream_url:
        raise RuntimeError("pytubefix no pudo obtener una URL temporal de audio.")

    info = _info(yt, str(url))
    info["stream_url"] = stream_url
    return info


def _nombre_seguro(texto, predeterminado="Descarga"):
    texto = str(texto or predeterminado).strip()
    texto = re.sub(r'[\\/:*?"<>|]+', ' ', texto)
    texto = re.sub(r"\s+", " ", texto).strip().strip(".")
    if not texto:
        texto = predeterminado
    return texto[:180].strip() or predeterminado


def _ruta_unica(carpeta, nombre_base, extension):
    carpeta = Path(carpeta)
    ruta = carpeta / f"{nombre_base}{extension}"
    contador = 2
    while ruta.exists():
        ruta = carpeta / f"{nombre_base} ({contador}){extension}"
        contador += 1
    return ruta


def _tamano_stream(stream):
    for nombre in ("filesize", "filesize_approx"):
        try:
            valor = getattr(stream, nombre, None)
            if valor:
                return int(valor)
        except Exception:
            pass
    return 0


def _callback_progreso(callback, cancelado_fn):
    def progreso(stream, chunk, bytes_remaining):
        if cancelado_fn and cancelado_fn():
            raise MotorAlternativoCancelado()

        total = _tamano_stream(stream)
        try:
            restantes = int(bytes_remaining or 0)
        except Exception:
            restantes = 0

        porcentaje = int(((total - restantes) / total) * 100) if total else 0
        porcentaje = max(0, min(100, porcentaje))
        if callback:
            callback({
                "porcentaje": porcentaje,
                "mensaje": traducir_formato("{porcentaje}% - descarga en curso", porcentaje=porcentaje),
                "estado": traducir("Descargando"),
            })

    return progreso


def _startupinfo_sin_ventana():
    if os.name != "nt":
        return None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return startupinfo
    except Exception:
        return None


def _ffmpeg_ejecutable(ffmpeg_location):
    if not ffmpeg_location:
        return None
    base = Path(ffmpeg_location)
    if base.is_file():
        return str(base)
    for nombre in ("ffmpeg.exe", "ffmpeg"):
        ruta = base / nombre
        if ruta.exists():
            return str(ruta)
    return None


def _ejecutar_ffmpeg(args, ffmpeg_location):
    ffmpeg = _ffmpeg_ejecutable(ffmpeg_location)
    if not ffmpeg:
        raise RuntimeError("No se encontró FFmpeg para procesar la descarga alternativa.")

    resultado = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=_startupinfo_sin_ventana(),
        timeout=900,
    )
    if resultado.returncode != 0:
        detalle = (resultado.stderr or resultado.stdout or "").strip()
        raise RuntimeError(detalle or "FFmpeg no pudo procesar la descarga alternativa.")


def _altura_objetivo(calidad):
    coincidencia = re.search(r"(2160|1440|1080|720|480|360|240|144)\s*p", str(calidad or ""), re.I)
    return int(coincidencia.group(1)) if coincidencia else None


def _altura_stream(stream):
    texto = str(_valor(stream, "resolution", "") or "")
    coincidencia = re.search(r"(\d+)\s*p", texto, re.I)
    return int(coincidencia.group(1)) if coincidencia else 0


def _mejor_stream_hasta(query, altura=None):
    try:
        candidatos = list(query)
    except Exception:
        candidatos = []
    if altura:
        candidatos = [s for s in candidatos if 0 < _altura_stream(s) <= altura]
    candidatos.sort(key=_altura_stream, reverse=True)
    return candidatos[0] if candidatos else None


def descargar(url, carpeta_destino, formato, calidad, ffmpeg_location=None,
              callback_progreso=None, cancelado_fn=None):
    """Descarga con pytubefix como último recurso.

    Los formatos de audio se obtienen desde el mejor stream disponible y se
    convierten con FFmpeg. Para MP4 se respeta, cuando es posible, la resolución
    máxima elegida por el usuario.
    """
    if not disponible():
        raise RuntimeError("El motor alternativo pytubefix no está instalado.")

    carpeta = Path(carpeta_destino)
    carpeta.mkdir(parents=True, exist_ok=True)

    if callback_progreso:
        callback_progreso({
            "porcentaje": 0,
            "mensaje": traducir("Preparando descarga"),
            "estado": traducir("Preparando"),
        })

    progreso = _callback_progreso(callback_progreso, cancelado_fn)
    yt = YouTube(str(url), on_progress_callback=progreso)
    titulo = _nombre_seguro(_valor(yt, "title", "Descarga"))
    streams = _valor(yt, "streams", None)
    if streams is None:
        raise RuntimeError("pytubefix no devolvió formatos descargables.")

    formato = str(formato or "MP3").upper()
    formatos_audio = {"MP3", "M4A", "AAC", "OPUS", "OGG", "WAV", "FLAC"}

    if formato in formatos_audio:
        try:
            stream = streams.get_audio_only()
        except Exception:
            stream = None
        if not stream:
            try:
                stream = streams.filter(only_audio=True).order_by("abr").desc().first()
            except Exception:
                stream = None
        if not stream:
            raise RuntimeError("pytubefix no encontró un stream de audio.")
        if not _ffmpeg_ejecutable(ffmpeg_location):
            raise RuntimeError("No se encontró FFmpeg para convertir el audio alternativo.")

        calidad_numero = re.sub(r"\D", "", str(calidad or "320")) or "320"
        mapa = {
            "MP3": (".mp3", ["-vn", "-codec:a", "libmp3lame", "-b:a", f"{calidad_numero}k"]),
            "M4A": (".m4a", ["-vn", "-c:a", "aac", "-b:a", f"{calidad_numero}k", "-movflags", "+faststart"]),
            "AAC": (".aac", ["-vn", "-c:a", "aac", "-b:a", f"{calidad_numero}k", "-f", "adts"]),
            "OPUS": (".opus", ["-vn", "-c:a", "libopus", "-b:a", f"{calidad_numero}k"]),
            "OGG": (".ogg", ["-vn", "-c:a", "libvorbis", "-b:a", f"{calidad_numero}k"]),
            "WAV": (".wav", ["-vn", "-c:a", "pcm_s16le"]),
            "FLAC": (".flac", ["-vn", "-c:a", "flac"]),
        }
        extension, args_codec = mapa[formato]

        with tempfile.TemporaryDirectory(prefix="dma_pytubefix_") as tmpdir:
            if cancelado_fn and cancelado_fn():
                raise MotorAlternativoCancelado()
            archivo_origen = stream.download(output_path=tmpdir)
            if cancelado_fn and cancelado_fn():
                raise MotorAlternativoCancelado()
            destino = _ruta_unica(carpeta, titulo, extension)
            if callback_progreso:
                callback_progreso({
                    "porcentaje": 100,
                    "mensaje": traducir_formato("Convirtiendo archivo a {formato}", formato=formato),
                    "estado": traducir("Convirtiendo"),
                })
            _ejecutar_ffmpeg(["-i", str(archivo_origen)] + args_codec + [str(destino)], ffmpeg_location)

    else:
        altura = _altura_objetivo(calidad)
        video = None
        audio = None
        try:
            videos = streams.filter(adaptive=True, only_video=True, file_extension="mp4")
            video = _mejor_stream_hasta(videos, altura)
            audio = streams.filter(only_audio=True).order_by("abr").desc().first()
        except Exception:
            video = None
            audio = None

        if video and audio and _ffmpeg_ejecutable(ffmpeg_location):
            with tempfile.TemporaryDirectory(prefix="dma_pytubefix_") as tmpdir:
                archivo_video = video.download(output_path=tmpdir, filename="video_temp.mp4")
                if cancelado_fn and cancelado_fn():
                    raise MotorAlternativoCancelado()
                extension_audio = "." + str(_valor(audio, "subtype", "m4a") or "m4a").lstrip(".")
                archivo_audio = audio.download(output_path=tmpdir, filename="audio_temp" + extension_audio)
                if cancelado_fn and cancelado_fn():
                    raise MotorAlternativoCancelado()
                destino = _ruta_unica(carpeta, titulo, ".mp4")
                if callback_progreso:
                    callback_progreso({
                        "porcentaje": 100,
                        "mensaje": traducir("Combinando video y audio"),
                        "estado": traducir("Procesando"),
                    })
                _ejecutar_ffmpeg([
                    "-i", str(archivo_video), "-i", str(archivo_audio),
                    "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart",
                    str(destino),
                ], ffmpeg_location)
        else:
            try:
                progresivos = streams.filter(progressive=True, file_extension="mp4")
                progresivo = _mejor_stream_hasta(progresivos, altura)
            except Exception:
                progresivo = None
            if not progresivo:
                raise RuntimeError("pytubefix no encontró una combinación de video y audio compatible con la resolución elegida.")
            destino = _ruta_unica(carpeta, titulo, ".mp4")
            progresivo.download(output_path=str(carpeta), filename=destino.name)

    if cancelado_fn and cancelado_fn():
        raise MotorAlternativoCancelado()

    if callback_progreso:
        callback_progreso({
            "porcentaje": 100,
            "mensaje": traducir("Descarga completada"),
            "estado": traducir("Completado"),
        })

    return _info(yt, str(url))

