import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

try:
    import yt_dlp
except Exception:
    yt_dlp = None

from config import LOG_ARCHIVO, MAX_RESULTADOS_BUSQUEDA
from i18n import traducir, traducir_formato
from motor_ytdlp import argumentos_runtime_javascript_cli, buscar_motor_descarga
from motor_pytubefix import (
    MotorAlternativoCancelado,
    buscar as pytubefix_buscar,
    descargar as pytubefix_descargar,
    disponible as pytubefix_disponible,
    obtener_informacion as pytubefix_obtener_informacion,
    obtener_url_reproduccion as pytubefix_obtener_url_reproduccion,
    version_instalada as pytubefix_version,
)
from utils import (
    formato_duracion,
    formato_eta,
    formato_fecha_yt,
    formato_numero,
    formato_tamano,
    formato_velocidad,
    limpiar_texto_consola,
)


class DescargaCancelada(Exception):
    """Excepción interna para detener una descarga solicitada por el usuario."""


class ErrorYoutubeBloqueo(Exception):
    """Error amigable cuando YouTube bloquea la extracción automática."""


# Mantengo este alias para que ui.py siga siendo compatible si alguna parte antigua lo importa.
ErrorAutenticacionYoutube = ErrorYoutubeBloqueo


_AUDIO_CODEC_YTDLP = {
    "MP3": "mp3",
    "M4A": "m4a",
    "AAC": "aac",
    "OPUS": "opus",
    "OGG": "vorbis",
    "WAV": "wav",
    "FLAC": "flac",
}
_FORMATOS_AUDIO_SIN_PERDIDA = {"WAV", "FLAC"}


def _altura_desde_calidad(calidad):
    texto = str(calidad or "")
    coincidencia = re.search(r"(2160|1440|1080|720|480|360|240|144)\s*p", texto, re.I)
    return int(coincidencia.group(1)) if coincidencia else None


def _selector_video(calidad):
    altura = _altura_desde_calidad(calidad)
    if not altura:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
    return (
        f"bestvideo[height<={altura}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={altura}]+bestaudio/best[height<={altura}]"
    )


class _LoggerSilencioso:
    """Evita que yt-dlp imprima mensajes rojos crudos en consola/interfaz."""

    def debug(self, mensaje):
        pass

    def warning(self, mensaje):
        pass

    def error(self, mensaje):
        pass


class Descargador:
    def __init__(self):
        self._cancelar = threading.Event()

    def cancelar(self):
        self._cancelar.set()

    def limpiar_cancelacion(self):
        self._cancelar.clear()

    def fue_cancelado(self):
        return self._cancelar.is_set()

    def _registrar_motor(self, mensaje):
        """Guarda detalles técnicos sin ensuciar la interfaz accesible."""
        try:
            LOG_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_ARCHIVO, "a", encoding="utf-8") as archivo:
                marca = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                archivo.write(f"{marca} - [motores] {mensaje}\n")
        except Exception:
            pass

    def _debe_intentar_motor_alternativo(self, error):
        if isinstance(error, (DescargaCancelada, ErrorYoutubeBloqueo, MotorAlternativoCancelado)):
            return False
        if not pytubefix_disponible():
            self._registrar_motor("pytubefix no está disponible; no se puede usar respaldo")
            return False

        mensaje = limpiar_texto_consola(str(error)).lower()

        # Casos donde cambiar de extractor normalmente no resuelve el problema.
        no_reintentar = [
            "private video", "video is private", "video privado",
            "video unavailable", "video no disponible", "has been removed", "eliminado",
            "copyright", "members-only", "members only",
            "login required", "sign in to confirm", "not a bot",
            "confirm you're not a bot", "confirm you’re not a bot",
            "no internet", "name resolution", "dns", "network is unreachable",
            "connection refused", "connection reset", "timed out", "timeout",
            "http error 429", "too many requests",
        ]
        if any(patron in mensaje for patron in no_reintentar):
            return False

        # Si el error es de extracción/formato/JS o es desconocido, un motor
        # realmente independiente sí puede aportar valor como último recurso.
        return True

    def _es_url_youtube(self, url):
        texto = str(url or "").lower()
        return any(dominio in texto for dominio in (
            "youtube.com/", "youtu.be/", "youtube-nocookie.com/"
        ))

    def _temporales_descarga(self, carpeta):
        encontrados = set()
        try:
            for ruta in Path(carpeta).iterdir():
                if not ruta.is_file():
                    continue
                nombre = ruta.name.lower()
                if nombre.endswith((".part", ".ytdl")) or re.search(r"\.f\d+\.(?:webm|m4a|mp4)$", nombre):
                    encontrados.add(str(ruta.resolve()))
        except Exception:
            pass
        return encontrados

    def _limpiar_temporales_nuevos(self, carpeta, existentes):
        actuales = self._temporales_descarga(carpeta)
        for ruta_txt in actuales - set(existentes or set()):
            try:
                Path(ruta_txt).unlink()
                self._registrar_motor(f"Se limpió temporal incompleto: {Path(ruta_txt).name}")
            except Exception:
                pass

    def _alternativo_info(self, url, error_principal):
        if not self._es_url_youtube(url):
            raise error_principal
        if not self._debe_intentar_motor_alternativo(error_principal):
            raise error_principal
        self._registrar_motor(f"yt-dlp falló obteniendo información: {error_principal}")
        try:
            info = pytubefix_obtener_informacion(url)
            self._registrar_motor(f"pytubefix {pytubefix_version() or ''} resolvió información correctamente")
            return normalizar_info_video(info)
        except Exception as error_alt:
            self._registrar_motor(f"pytubefix también falló obteniendo información: {error_alt}")
            raise error_principal

    def _alternativo_busqueda(self, texto, limite, error_principal):
        if not self._debe_intentar_motor_alternativo(error_principal):
            raise error_principal
        self._registrar_motor(f"yt-dlp falló en búsqueda: {error_principal}")
        try:
            entradas = pytubefix_buscar(texto, limite)
            resultados = []
            for entrada in entradas:
                resultado = normalizar_info_video(entrada)
                resultado["url"] = entrada.get("webpage_url") or entrada.get("url") or resultado.get("url", "")
                resultados.append(resultado)
            if not resultados:
                raise RuntimeError("pytubefix no devolvió resultados")
            self._registrar_motor(f"pytubefix {pytubefix_version() or ''} resolvió búsqueda correctamente")
            return resultados
        except Exception as error_alt:
            self._registrar_motor(f"pytubefix también falló en búsqueda: {error_alt}")
            raise error_principal

    def _alternativo_reproduccion(self, url, error_principal):
        if not self._es_url_youtube(url):
            raise error_principal
        if not self._debe_intentar_motor_alternativo(error_principal):
            raise error_principal
        self._registrar_motor(f"yt-dlp falló obteniendo reproducción: {error_principal}")
        try:
            info = pytubefix_obtener_url_reproduccion(url)
            normalizada = normalizar_info_video(info)
            normalizada["stream_url"] = info.get("stream_url")
            self._registrar_motor(f"pytubefix {pytubefix_version() or ''} resolvió reproducción correctamente")
            return normalizada
        except Exception as error_alt:
            self._registrar_motor(f"pytubefix también falló obteniendo reproducción: {error_alt}")
            raise error_principal

    def _alternativo_descarga(self, url, carpeta_destino, formato, calidad, callback_progreso, error_principal):
        if not self._es_url_youtube(url):
            raise error_principal
        if not self._debe_intentar_motor_alternativo(error_principal):
            raise error_principal
        self._registrar_motor(f"yt-dlp falló descargando: {error_principal}")
        try:
            info = pytubefix_descargar(
                url, carpeta_destino, formato, calidad,
                ffmpeg_location=self._buscar_ffmpeg(),
                callback_progreso=callback_progreso,
                cancelado_fn=self.fue_cancelado,
            )
            self._registrar_motor(f"pytubefix {pytubefix_version() or ''} completó la descarga correctamente")
            return normalizar_info_video(info)
        except MotorAlternativoCancelado as exc:
            raise DescargaCancelada() from exc
        except Exception as error_alt:
            self._registrar_motor(f"pytubefix también falló descargando: {error_alt}")
            raise error_principal

    def obtener_informacion(self, url):
        motor = self._buscar_motor_externo()
        if motor:
            try:
                info = self._obtener_informacion_cli(motor, url)
                self._registrar_motor("Información resuelta con yt-dlp externo")
                return info
            except Exception as error:
                return self._alternativo_info(url, error)

        opciones = {
            "quiet": True,
            "noplaylist": True,
            "skip_download": True,
        }

        try:
            info = self._extraer_con_reintentos(url, download=False, opciones_extra=opciones)
            self._registrar_motor("Información resuelta con yt-dlp Python")
            return normalizar_info_video(info)
        except Exception as error:
            return self._alternativo_info(url, error)

    def _normalizar_url_youtube(self, url, tipo="video"):
        url = str(url or "").strip()
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("/"):
            return "https://www.youtube.com" + url
        if tipo == "playlist":
            return "https://www.youtube.com/playlist?list=" + url
        if tipo == "canal":
            if url.startswith("@"):
                return "https://www.youtube.com/" + url
            if url.startswith("UC"):
                return "https://www.youtube.com/channel/" + url
            return "https://www.youtube.com/" + url.lstrip("/")
        return "https://www.youtube.com/watch?v=" + url

    def buscar_youtube(self, texto_busqueda, limite=50):
        texto_busqueda = str(texto_busqueda or "").strip()

        if not texto_busqueda:
            return []

        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = MAX_RESULTADOS_BUSQUEDA

        limite = max(1, min(MAX_RESULTADOS_BUSQUEDA, limite))

        motor = self._buscar_motor_externo()
        if motor:
            try:
                resultados = self._buscar_youtube_cli(motor, texto_busqueda, limite)
                self._registrar_motor("Búsqueda resuelta con yt-dlp externo")
                return resultados
            except Exception as error:
                return self._alternativo_busqueda(texto_busqueda, limite, error)

        opciones = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "ignoreerrors": True,
            "noplaylist": True,
        }

        consulta = f"ytsearch{limite}:{texto_busqueda}"
        try:
            info = self._extraer_con_reintentos(consulta, download=False, opciones_extra=opciones)
            self._registrar_motor("Búsqueda resuelta con yt-dlp Python")
        except Exception as error:
            return self._alternativo_busqueda(texto_busqueda, limite, error)

        entradas = info.get("entries", []) if isinstance(info, dict) else []
        resultados = []

        for entrada in entradas:
            if not entrada:
                continue

            resultado = normalizar_info_video(entrada)
            resultado["url"] = (
                entrada.get("webpage_url")
                or entrada.get("url")
                or resultado.get("url")
                or ""
            )

            if resultado["url"] and not str(resultado["url"]).startswith("http"):
                resultado["url"] = self._normalizar_url_youtube(resultado["url"], "video")

            resultados.append(resultado)

        return resultados

    def buscar_colecciones_youtube(self, texto_busqueda, tipo="canal", limite=50):
        """Busca canales o listas de reproducción de YouTube.

        tipo puede ser "canal" o "playlist". Se usa la página de resultados de
        YouTube con filtro para que el usuario no reciba videos sueltos cuando
        pidió canales o listas.
        """
        texto_busqueda = str(texto_busqueda or "").strip()

        if not texto_busqueda:
            return []

        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = MAX_RESULTADOS_BUSQUEDA

        limite = max(1, min(MAX_RESULTADOS_BUSQUEDA, limite))
        tipo = "playlist" if str(tipo).lower() in {"playlist", "lista", "lista de reproducción"} else "canal"
        url_busqueda = self._url_busqueda_colecciones(texto_busqueda, tipo)

        motor = self._buscar_motor_externo()
        if motor:
            return self._buscar_colecciones_cli(motor, url_busqueda, tipo, limite)

        opciones = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "ignoreerrors": True,
            "playlistend": limite,
        }

        info = self._extraer_con_reintentos(url_busqueda, download=False, opciones_extra=opciones)
        entradas = info.get("entries", []) if isinstance(info, dict) else []
        return self._normalizar_resultados_colecciones(entradas, tipo, limite)

    def listar_videos_coleccion(self, url, limite=50, tipo="canal"):
        """Lista videos de un canal o una lista de reproducción sin descargarlos."""
        url = str(url or "").strip()
        if not url:
            return []

        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = 50
        limite = max(1, min(MAX_RESULTADOS_BUSQUEDA, limite))

        tipo = "playlist" if str(tipo).lower() in {"playlist", "lista", "lista de reproducción"} else "canal"
        url_listado = self._preparar_url_coleccion_para_listar(url, tipo)

        motor = self._buscar_motor_externo()
        if motor:
            return self._listar_videos_coleccion_cli(motor, url_listado, limite)

        opciones = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "ignoreerrors": True,
            "playlistend": limite,
        }

        info = self._extraer_con_reintentos(url_listado, download=False, opciones_extra=opciones)
        entradas = info.get("entries", []) if isinstance(info, dict) else []
        return self._normalizar_entradas_video(entradas, limite)

    def _url_busqueda_colecciones(self, texto_busqueda, tipo):
        # Filtros de búsqueda de YouTube:
        # canales: EgIQAg%3D%3D, listas: EgIQAw%3D%3D. Se deja doblemente codificado
        # como aparece en las URL públicas de YouTube.
        filtro = "EgIQAw%253D%253D" if tipo == "playlist" else "EgIQAg%253D%253D"
        return f"https://www.youtube.com/results?search_query={quote_plus(texto_busqueda)}&sp={filtro}"

    def _preparar_url_coleccion_para_listar(self, url, tipo):
        url = str(url or "").strip()
        if tipo != "canal":
            return url

        # En canales, la pestaña /videos suele devolver la lista de subidos de forma más directa.
        limpia = url.rstrip("/")
        if "/videos" in limpia or "/streams" in limpia or "playlist?list=" in limpia:
            return url
        if "youtube.com/" in limpia or "youtu.be/" in limpia:
            return limpia + "/videos"
        return url

    def _normalizar_resultados_colecciones(self, entradas, tipo, limite):
        resultados = []
        vistos = set()
        etiqueta = "Lista de reproducción" if tipo == "playlist" else "Canal"

        for entrada in entradas or []:
            if not entrada:
                continue
            resultado = self._normalizar_coleccion(entrada, tipo, etiqueta)
            url = resultado.get("url", "").strip()
            titulo = resultado.get("titulo", "").strip()
            clave = (url or titulo).lower()
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            resultados.append(resultado)
            if len(resultados) >= limite:
                break

        return resultados

    def _normalizar_coleccion(self, entrada, tipo, etiqueta):
        titulo = entrada.get("title") or entrada.get("channel") or entrada.get("uploader") or "Sin título"
        autor = entrada.get("uploader") or entrada.get("channel") or entrada.get("creator") or "No disponible"
        url = entrada.get("webpage_url") or entrada.get("url") or entrada.get("original_url") or ""

        if url and not str(url).startswith("http"):
            url = self._normalizar_url_youtube(url, tipo)

        return {
            "tipo": etiqueta,
            "tipo_clave": tipo,
            "titulo": titulo,
            "canal": autor,
            "autor": autor,
            "url": url,
            "id": entrada.get("id") or entrada.get("channel_id") or entrada.get("playlist_id") or "",
            "descripcion": entrada.get("description") or "No disponible",
        }

    def _normalizar_entradas_video(self, entradas, limite):
        videos = []
        vistos = set()

        for entrada in entradas or []:
            if not entrada:
                continue
            resultado = normalizar_info_video(entrada)
            url = entrada.get("webpage_url") or entrada.get("url") or resultado.get("url") or ""
            if url and not str(url).startswith("http"):
                url = self._normalizar_url_youtube(url, "video")
            resultado["url"] = url
            clave = (url or resultado.get("titulo", "")).lower()
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            videos.append(resultado)
            if len(videos) >= limite:
                break

        return videos


    def obtener_url_reproduccion(self, url):
        """Obtiene una URL temporal de audio/video para escuchar antes de descargar."""
        motor = self._buscar_motor_externo()
        if motor:
            try:
                info = self._obtener_url_reproduccion_cli(motor, url)
                self._registrar_motor("Reproducción resuelta con yt-dlp externo")
                return info
            except Exception as error:
                return self._alternativo_reproduccion(url, error)

        opciones = {
            "quiet": True,
            "noplaylist": True,
            "skip_download": True,
            # Preferimos audio para que la reproducción sea rápida y ligera.
            "format": "bestaudio/best",
        }

        try:
            info = self._extraer_con_reintentos(url, download=False, opciones_extra=opciones)
            self._registrar_motor("Reproducción resuelta con yt-dlp Python")
        except Exception as error:
            return self._alternativo_reproduccion(url, error)
        info_normalizada = normalizar_info_video(info)

        stream_url = info.get("url") if isinstance(info, dict) else None

        if not stream_url and isinstance(info, dict):
            formatos = info.get("formats") or []
            # Primero busca un formato de audio directo.
            for formato in formatos:
                if formato.get("url") and formato.get("acodec") != "none":
                    stream_url = formato.get("url")
                    break

        if not stream_url:
            error = RuntimeError("No se pudo obtener una URL de reproducción para este resultado.")
            return self._alternativo_reproduccion(url, error)

        info_normalizada["stream_url"] = stream_url
        return info_normalizada

    def descargar(
        self,
        url,
        carpeta_destino,
        formato,
        calidad,
        callback_progreso=None,
    ):
        self.limpiar_cancelacion()
        os.makedirs(carpeta_destino, exist_ok=True)
        temporales_antes = self._temporales_descarga(carpeta_destino)

        motor = self._buscar_motor_externo()
        if motor:
            try:
                resultado = self._descargar_cli(
                    motor,
                    url,
                    carpeta_destino,
                    formato,
                    calidad,
                    callback_progreso=callback_progreso,
                )
                self._registrar_motor("Descarga completada con yt-dlp externo")
                return resultado
            except Exception as error:
                self._limpiar_temporales_nuevos(carpeta_destino, temporales_antes)
                return self._alternativo_descarga(
                    url, carpeta_destino, formato, calidad, callback_progreso, error
                )

        calidad_numero = str(calidad).replace("kbps", "").strip()

        opciones = {
            "quiet": True,
            "noplaylist": True,
            "windowsfilenames": True,
            "outtmpl": os.path.join(carpeta_destino, "%(title).200B.%(ext)s"),
            "progress_hooks": [self._crear_hook_progreso(callback_progreso)],
            "postprocessor_hooks": [self._crear_hook_postproceso(callback_progreso)],
        }

        formato = str(formato or "MP3").upper()
        if formato in _AUDIO_CODEC_YTDLP:
            ffmpeg_location = self._buscar_ffmpeg()
            if not ffmpeg_location:
                raise RuntimeError(
                    "No se encontró FFmpeg. Coloque ffmpeg.exe y ffprobe.exe en la carpeta del programa "
                    "para poder convertir el audio al formato seleccionado."
                )
            postprocesador = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": _AUDIO_CODEC_YTDLP[formato],
            }
            if formato not in _FORMATOS_AUDIO_SIN_PERDIDA:
                postprocesador["preferredquality"] = calidad_numero or "320"
            opciones.update({
                "format": "bestaudio/best",
                "postprocessors": [postprocesador],
                "ffmpeg_location": ffmpeg_location,
            })
        else:
            opciones.update({
                "format": _selector_video(calidad),
                "merge_output_format": "mp4",
            })
            ffmpeg_location = self._buscar_ffmpeg()
            if ffmpeg_location:
                opciones["ffmpeg_location"] = ffmpeg_location

        if callback_progreso:
            callback_progreso(
                {
                    "porcentaje": 0,
                    "mensaje": traducir_formato("Preparando descarga en formato {formato}", formato=formato),
                    "estado": traducir("Preparando"),
                }
            )

        try:
            info = self._extraer_con_reintentos(url, download=True, opciones_extra=opciones)
            self._registrar_motor("Descarga completada con yt-dlp Python")
        except Exception as error:
            self._limpiar_temporales_nuevos(carpeta_destino, temporales_antes)
            return self._alternativo_descarga(
                url, carpeta_destino, formato, calidad, callback_progreso, error
            )

        if self.fue_cancelado():
            raise DescargaCancelada()

        return normalizar_info_video(info)


    def _buscar_motor_externo(self):
        """Busca yt-dlp.exe. Si existe, se usa como motor principal."""
        try:
            return buscar_motor_descarga()
        except Exception:
            return None

    def _startupinfo_sin_ventana(self):
        if os.name != "nt":
            return None
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        except Exception:
            return None

    def _args_cli_base(self):
        # No fijamos un User-Agent antiguo: yt-dlp mantiene sus propios perfiles
        # actualizados y puede elegir el más apropiado.
        args = [
            "--no-color",
            "--no-warnings",
            "--retries",
            "5",
            "--fragment-retries",
            "10",
            "--socket-timeout",
            "30",
            "--add-header",
            "Accept-Language: es-ES,es;q=0.9,en;q=0.8",
        ]
        args.extend(argumentos_runtime_javascript_cli())
        return args

    def _ejecutar_cli_json(self, motor, args):
        comando = [motor] + self._args_cli_base() + args
        try:
            resultado = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=self._startupinfo_sin_ventana(),
                timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("El motor de descarga tardó demasiado en responder.") from exc

        salida = (resultado.stdout or "").strip()
        error = limpiar_texto_consola((resultado.stderr or "").strip())

        if resultado.returncode != 0:
            mensaje = error or salida or "El motor de descarga devolvió un error."
            mensaje_minusculas = mensaje.lower()
            if self._es_error_runtime_javascript(mensaje_minusculas):
                raise RuntimeError(
                    "YouTube necesita un motor JavaScript compatible para este video. "
                    "Instale Deno, Node 22 o QuickJS, o coloque su ejecutable junto al programa."
                )
            if self._es_bloqueo_youtube(mensaje_minusculas):
                raise ErrorYoutubeBloqueo(
                    "YouTube bloqueó la solicitud automática. Actualice el motor de descarga desde Herramientas, pruebe otro resultado o vuelva a intentarlo más tarde."
                )
            raise RuntimeError(mensaje)

        if not salida:
            raise RuntimeError("El motor de descarga no devolvió información.")

        # yt-dlp puede escribir varias líneas; buscamos la última que parezca JSON.
        candidatos = [linea.strip() for linea in salida.splitlines() if linea.strip()]
        for linea in reversed(candidatos):
            if linea.startswith("{") or linea.startswith("["):
                try:
                    return json.loads(linea)
                except Exception:
                    pass

        try:
            return json.loads(salida)
        except Exception as exc:
            raise RuntimeError("No se pudo interpretar la respuesta del motor de descarga.") from exc

    def _obtener_informacion_cli(self, motor, url):
        info = self._ejecutar_cli_json(
            motor,
            [
                "--quiet",
                "--dump-single-json",
                "--no-playlist",
                url,
            ],
        )
        return normalizar_info_video(info)

    def _buscar_youtube_cli(self, motor, texto_busqueda, limite):
        info = self._ejecutar_cli_json(
            motor,
            [
                "--quiet",
                "--dump-single-json",
                "--flat-playlist",
                "--ignore-errors",
                f"ytsearch{limite}:{texto_busqueda}",
            ],
        )

        entradas = info.get("entries", []) if isinstance(info, dict) else []
        resultados = []

        for entrada in entradas:
            if not entrada:
                continue
            resultado = normalizar_info_video(entrada)
            resultado["url"] = entrada.get("webpage_url") or entrada.get("url") or resultado.get("url") or ""
            if resultado["url"] and not str(resultado["url"]).startswith("http"):
                resultado["url"] = self._normalizar_url_youtube(resultado["url"], "video")
            resultados.append(resultado)

        return resultados

    def _buscar_colecciones_cli(self, motor, url_busqueda, tipo, limite):
        info = self._ejecutar_cli_json(
            motor,
            [
                "--quiet",
                "--dump-single-json",
                "--flat-playlist",
                "--ignore-errors",
                "--playlist-end",
                str(limite),
                url_busqueda,
            ],
        )
        entradas = info.get("entries", []) if isinstance(info, dict) else []
        etiqueta = "Lista de reproducción" if tipo == "playlist" else "Canal"
        return self._normalizar_resultados_colecciones(entradas, tipo, limite)

    def _listar_videos_coleccion_cli(self, motor, url, limite):
        info = self._ejecutar_cli_json(
            motor,
            [
                "--quiet",
                "--dump-single-json",
                "--flat-playlist",
                "--ignore-errors",
                "--playlist-end",
                str(limite),
                url,
            ],
        )
        entradas = info.get("entries", []) if isinstance(info, dict) else []
        return self._normalizar_entradas_video(entradas, limite)

    def _obtener_url_reproduccion_cli(self, motor, url):
        info = self._ejecutar_cli_json(
            motor,
            [
                "--quiet",
                "--dump-single-json",
                "--no-playlist",
                "-f",
                "bestaudio/best",
                url,
            ],
        )
        info_normalizada = normalizar_info_video(info)
        stream_url = info.get("url") if isinstance(info, dict) else None

        if not stream_url and isinstance(info, dict):
            for formato in info.get("formats") or []:
                if formato.get("url") and formato.get("acodec") != "none":
                    stream_url = formato.get("url")
                    break

        if not stream_url:
            raise RuntimeError("No se pudo obtener una URL de reproducción para este resultado.")

        info_normalizada["stream_url"] = stream_url
        return info_normalizada

    def _parsear_progreso_cli(self, linea):
        linea = limpiar_texto_consola(linea)
        if not linea:
            return None

        if "|" in linea:
            partes = [p.strip() for p in linea.split("|")]
            porcentaje_txt = partes[0] if partes else ""
            porcentaje = self._porcentaje_desde_texto(porcentaje_txt)
            descargado = self._numero_float(partes[1]) if len(partes) > 1 else 0
            total = self._numero_float(partes[2]) if len(partes) > 2 else 0
            total_estimado = self._numero_float(partes[3]) if len(partes) > 3 else 0
            velocidad = self._numero_float(partes[4]) if len(partes) > 4 else None
            eta = self._numero_float(partes[5]) if len(partes) > 5 else None
            total_final = total or total_estimado
            mensaje = (
                f"{porcentaje}% - {formato_tamano(descargado)} de {formato_tamano(total_final)} - "
                f"{formato_velocidad(velocidad)} - {formato_eta(eta)}"
            )
            return {"porcentaje": porcentaje, "mensaje": mensaje, "estado": "Descargando"}

        match = re.search(r"(\d+(?:[\.,]\d+)?)%", linea)
        if match:
            porcentaje = int(float(match.group(1).replace(",", ".")))
            return {"porcentaje": porcentaje, "mensaje": linea, "estado": "Descargando"}

        if "destination" in linea.lower() or "destino" in linea.lower():
            return {"porcentaje": 0, "mensaje": "Preparando archivo de salida", "estado": "Preparando"}

        return None

    def _porcentaje_desde_texto(self, texto):
        texto = str(texto or "").replace("%", "").replace(",", ".").strip()
        try:
            return min(100, max(0, int(float(texto))))
        except Exception:
            return 0

    def _numero_float(self, texto):
        texto = str(texto or "").strip()
        if not texto or texto.lower() in {"none", "nan", "n/a"}:
            return 0
        try:
            return float(texto)
        except Exception:
            return 0

    def _descargar_cli(self, motor, url, carpeta_destino, formato, calidad, callback_progreso=None):
        calidad_numero = str(calidad).replace("kbps", "").strip()
        outtmpl = os.path.join(carpeta_destino, "%(title).200B.%(ext)s")

        args = self._args_cli_base() + [
            "--newline",
            "--no-playlist",
            "--windows-filenames",
            "--progress-template",
            "download:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "-o",
            outtmpl,
        ]

        ffmpeg_location = self._buscar_ffmpeg()

        formato = str(formato or "MP3").upper()
        if formato in _AUDIO_CODEC_YTDLP:
            if not ffmpeg_location:
                raise RuntimeError(
                    "No se encontró FFmpeg. Coloque ffmpeg.exe y ffprobe.exe en la carpeta del programa para poder convertir el audio al formato seleccionado."
                )
            args += [
                "-f", "bestaudio/best",
                "-x", "--audio-format", _AUDIO_CODEC_YTDLP[formato],
            ]
            if formato not in _FORMATOS_AUDIO_SIN_PERDIDA:
                args += ["--audio-quality", f"{calidad_numero or '320'}K"]
            args += ["--ffmpeg-location", ffmpeg_location]
        else:
            args += [
                "-f", _selector_video(calidad),
                "--merge-output-format", "mp4",
            ]
            if ffmpeg_location:
                args += ["--ffmpeg-location", ffmpeg_location]

        args.append(url)
        comando = [motor] + args

        if callback_progreso:
            callback_progreso({"porcentaje": 0, "mensaje": traducir_formato("Preparando descarga con motor externo en formato {formato}", formato=formato), "estado": traducir("Preparando")})

        proceso = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=self._startupinfo_sin_ventana(),
        )

        salida = []
        ultimo_aviso_generico = 0

        try:
            assert proceso.stdout is not None
            for linea in proceso.stdout:
                if self.fue_cancelado():
                    try:
                        proceso.terminate()
                    except Exception:
                        pass
                    raise DescargaCancelada()

                linea_limpia = limpiar_texto_consola(linea.strip())
                if linea_limpia:
                    salida.append(linea_limpia)

                progreso = self._parsear_progreso_cli(linea_limpia)
                if progreso and callback_progreso:
                    callback_progreso(progreso)
                elif callback_progreso and time.time() - ultimo_aviso_generico > 20:
                    ultimo_aviso_generico = time.time()
                    callback_progreso({"porcentaje": 0, "mensaje": "Descarga en curso", "estado": "Descargando"})

            codigo = proceso.wait()
        except DescargaCancelada:
            raise
        except Exception:
            try:
                proceso.kill()
            except Exception:
                pass
            raise

        texto_salida = "\n".join(salida)

        if codigo != 0:
            salida_minusculas = texto_salida.lower()
            if self._es_error_runtime_javascript(salida_minusculas):
                raise RuntimeError(
                    "YouTube necesita un motor JavaScript compatible para este video. "
                    "Instale Deno, Node 22 o QuickJS, o coloque su ejecutable junto al programa."
                )
            if self._es_bloqueo_youtube(salida_minusculas):
                raise ErrorYoutubeBloqueo(
                    "YouTube bloqueó la solicitud automática. Actualice el motor de descarga desde Herramientas, pruebe otro resultado o vuelva a intentarlo más tarde."
                )
            raise RuntimeError(texto_salida or "El motor externo no pudo completar la descarga.")

        if callback_progreso:
            callback_progreso({"porcentaje": 100, "mensaje": "Descarga finalizada. Preparando información final.", "estado": "Completado"})

        try:
            return self._obtener_informacion_cli(motor, url)
        except Exception:
            return {"titulo": "Descarga completada", "canal": "No disponible", "duracion_texto": "No disponible", "url": url}

    def _extraer_con_reintentos(self, url, download=False, opciones_extra=None):
        """
        Prueba varias configuraciones normales de yt-dlp antes de rendirse.
        No lee cookies del navegador en silencio porque eso sería invasivo para la privacidad.
        """
        opciones_extra = opciones_extra or {}
        if yt_dlp is None:
            raise RuntimeError(
                "No está disponible la librería interna yt-dlp y tampoco se encontró el motor externo yt-dlp.exe."
            )
        ultimo_error = None
        hubo_bloqueo_youtube = False

        for nombre_estrategia, opciones_estrategia in self._estrategias_ytdlp():
            if self.fue_cancelado():
                raise DescargaCancelada()

            opciones = self._opciones_base()
            opciones.update(opciones_estrategia)
            opciones.update(opciones_extra)

            try:
                with yt_dlp.YoutubeDL(opciones) as ydl:
                    return ydl.extract_info(url, download=download)
            except DescargaCancelada:
                raise
            except Exception as error:
                ultimo_error = error
                mensaje = limpiar_texto_consola(str(error)).lower()

                if self._es_bloqueo_youtube(mensaje):
                    hubo_bloqueo_youtube = True
                    continue

                # En errores de red, formatos o extracción, prueba la siguiente estrategia.
                if self._es_error_reintentable(mensaje):
                    continue

                raise error

        if hubo_bloqueo_youtube:
            raise ErrorYoutubeBloqueo(
                "YouTube bloqueó la solicitud automática. El programa probó varios métodos internos, "
                "pero esta vez YouTube pidió verificación. Actualiza yt-dlp desde Herramientas, prueba otro resultado "
                "o vuelve a intentarlo más tarde."
            ) from ultimo_error

        if ultimo_error:
            raise ultimo_error

        raise RuntimeError("No se pudo completar la operación.")

    def _opciones_base(self):
        return {
            "retries": 5,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "socket_timeout": 30,
            "no_color": True,
            "no_warnings": True,
            "logger": _LoggerSilencioso(),
            "http_headers": {
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            },
        }

    def _estrategias_ytdlp(self):
        # Dejamos que yt-dlp seleccione sus clientes de YouTube actuales.
        # Forzar clientes web/android/ios envejece rápido cuando YouTube cambia.
        return [
            ("principal", {}),
            ("ipv4", {"force_ipv4": True}),
        ]

    def _es_error_runtime_javascript(self, mensaje):
        patrones = [
            "no supported javascript runtime",
            "javascript runtime",
            "challenge solving failed",
            "n challenge",
            "signature solving failed",
            "ejs",
        ]
        return any(patron in mensaje for patron in patrones)

    def _es_bloqueo_youtube(self, mensaje):
        patrones = [
            "sign in to confirm",
            "not a bot",
            "confirm you’re not a bot",
            "confirm you're not a bot",
            "cookies-from-browser",
            "cookies for the authentication",
            "login required",
        ]
        return any(patron in mensaje for patron in patrones)

    def _es_error_reintentable(self, mensaje):
        patrones = [
            "timed out",
            "timeout",
            "temporarily unavailable",
            "unable to download",
            "http error",
            "requested format is not available",
            "fragment",
            "network",
            "connection",
        ]
        return any(patron in mensaje for patron in patrones)

    def _crear_hook_progreso(self, callback_progreso):
        def hook(datos):
            if self.fue_cancelado():
                raise DescargaCancelada()

            estado = datos.get("status")

            if estado == "downloading":
                descargado = datos.get("downloaded_bytes") or 0
                total = datos.get("total_bytes") or datos.get("total_bytes_estimate") or 0
                velocidad = datos.get("speed")
                eta = datos.get("eta")

                porcentaje = 0

                if total:
                    porcentaje = min(100, max(0, int((descargado / total) * 100)))

                mensaje = (
                    f"{porcentaje}% - "
                    f"{formato_tamano(descargado)} de {formato_tamano(total)} - "
                    f"{formato_velocidad(velocidad)} - "
                    f"{formato_eta(eta)}"
                )

                if callback_progreso:
                    callback_progreso(
                        {
                            "porcentaje": porcentaje,
                            "mensaje": mensaje,
                            "estado": traducir("Descargando"),
                        }
                    )

            elif estado == "finished":
                if callback_progreso:
                    callback_progreso(
                        {
                            "porcentaje": 100,
                            "mensaje": traducir("Archivo descargado. Procesando conversión si corresponde..."),
                            "estado": traducir("Procesando"),
                        }
                    )

        return hook

    def _crear_hook_postproceso(self, callback_progreso):
        def hook(datos):
            if self.fue_cancelado():
                raise DescargaCancelada()

            estado = datos.get("status")

            if callback_progreso and estado in {"started", "processing"}:
                callback_progreso(
                    {
                        "porcentaje": 100,
                        "mensaje": traducir("Convirtiendo archivo..."),
                        "estado": traducir("Convirtiendo"),
                    }
                )

            if callback_progreso and estado == "finished":
                callback_progreso(
                    {
                        "porcentaje": 100,
                        "mensaje": traducir("Conversión terminada."),
                        "estado": traducir("Completado"),
                    }
                )

        return hook

    def _buscar_ffmpeg(self):
        """
        Busca FFmpeg en desarrollo y en ejecutables creados con PyInstaller.

        En PyInstaller 6, los archivos binarios pueden quedar dentro de la carpeta
        _internal, aunque el .exe esté en la carpeta principal. Por eso se revisan
        varias ubicaciones posibles.
        """
        posibles_carpetas = []

        def agregar(carpeta):
            if not carpeta:
                return

            carpeta = os.path.abspath(str(carpeta))

            if carpeta not in posibles_carpetas:
                posibles_carpetas.append(carpeta)

        # Carpeta del .exe cuando está empaquetado.
        if getattr(sys, "frozen", False):
            agregar(os.path.dirname(sys.executable))
            agregar(getattr(sys, "_MEIPASS", ""))
        else:
            agregar(os.path.dirname(os.path.abspath(__file__)))

        # Carpeta actual por si el usuario abre el programa desde consola.
        agregar(os.getcwd())

        # Subcarpetas frecuentes en modo empaquetado.
        carpetas_base = list(posibles_carpetas)

        for base in carpetas_base:
            agregar(os.path.join(base, "bin"))
            agregar(os.path.join(base, "ffmpeg"))
            agregar(os.path.join(base, "_internal"))
            agregar(os.path.join(base, "_internal", "bin"))
            agregar(os.path.join(base, "_internal", "ffmpeg"))

        for carpeta in posibles_carpetas:
            ffmpeg_exe = os.path.join(carpeta, "ffmpeg.exe")
            ffprobe_exe = os.path.join(carpeta, "ffprobe.exe")
            ffmpeg_linux = os.path.join(carpeta, "ffmpeg")

            # En Windows pedimos ffmpeg y ffprobe para conversión y lectura segura.
            if os.path.exists(ffmpeg_exe):
                if os.name != "nt" or os.path.exists(ffprobe_exe):
                    return carpeta

            if os.path.exists(ffmpeg_linux):
                return carpeta

        return None


def normalizar_info_video(info):
    if not info:
        info = {}

    canal = (
        info.get("channel")
        or info.get("uploader")
        or info.get("creator")
        or info.get("channel_id")
        or "No disponible"
    )

    duracion = info.get("duration")
    fecha = info.get("upload_date") or info.get("release_date")
    visualizaciones = info.get("view_count")

    return {
        "titulo": info.get("title") or "Sin título",
        "canal": canal,
        "duracion": duracion,
        "duracion_texto": formato_duracion(duracion),
        "fecha": fecha,
        "fecha_texto": formato_fecha_yt(fecha),
        "visualizaciones": visualizaciones,
        "visualizaciones_texto": formato_numero(visualizaciones),
        "url": info.get("webpage_url") or info.get("original_url") or info.get("url") or "",
    }
