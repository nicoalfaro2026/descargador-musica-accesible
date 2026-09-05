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


class ErrorVideoNoDisponible(Exception):
    """Error amigable cuando el video es privado, fue eliminado o está restringido.

    Se distingue de ErrorYoutubeBloqueo porque aquí no sirve reintentar con
    cookies ni sesión del navegador: el contenido no está disponible para
    nadie, no solo para el programa.
    """


def validar_archivo_cookies_netscape(ruta):
    """Valida sin copiar ni registrar el contenido sensible del archivo."""
    try:
        ruta = Path(str(ruta or "")).expanduser()
        if not ruta.is_file():
            return False, "El archivo cookies.txt seleccionado no existe."
        with open(ruta, "r", encoding="utf-8-sig", errors="replace") as archivo:
            primera = archivo.readline().strip()
        if primera not in {"# Netscape HTTP Cookie File", "# HTTP Cookie File"}:
            return False, "El archivo cookies.txt seleccionado no tiene formato Netscape compatible."
        return True, ""
    except Exception:
        return False, "No se pudo leer el archivo cookies.txt seleccionado."


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
        self._idioma_preferido = "es"
        self._preferir_idioma_programa = True
        self._usar_cookies_respaldo = False
        self._navegador_cookies = "auto"
        self._metodo_autenticacion = "ninguno"
        self._archivo_cookies = ""

    def configurar_preferencias(
        self, idioma="es", preferir_idioma=True, usar_cookies_respaldo=False,
        navegador_cookies="auto", metodo_autenticacion="ninguno", archivo_cookies=""
    ):
        idioma = str(idioma or "es").lower().strip()
        if idioma not in {"es", "en", "pt", "fr", "it", "ru"}:
            idioma = "es"
        navegador = str(navegador_cookies or "auto").lower().strip()
        if navegador not in {"auto", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"}:
            navegador = "auto"
        metodo = str(metodo_autenticacion or "ninguno").lower().strip()
        if metodo not in {"ninguno", "cookies_txt", "navegador"}:
            metodo = "navegador" if usar_cookies_respaldo else "ninguno"
        self._idioma_preferido = idioma
        self._preferir_idioma_programa = bool(preferir_idioma)
        self._metodo_autenticacion = metodo
        self._archivo_cookies = str(archivo_cookies or "").strip()
        self._usar_cookies_respaldo = metodo == "navegador"
        self._navegador_cookies = navegador

    def _resolver_navegador_cookies(self):
        if self._metodo_autenticacion != "navegador":
            return None
        if self._navegador_cookies != "auto":
            return self._navegador_cookies

        local = Path(os.environ.get("LOCALAPPDATA", ""))
        roaming = Path(os.environ.get("APPDATA", ""))
        candidatos = [
            ("chrome", local / "Google" / "Chrome" / "User Data"),
            ("edge", local / "Microsoft" / "Edge" / "User Data"),
            ("brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
            ("vivaldi", local / "Vivaldi" / "User Data"),
            ("firefox", roaming / "Mozilla" / "Firefox" / "Profiles"),
            ("opera", roaming / "Opera Software" / "Opera Stable"),
            ("chromium", local / "Chromium" / "User Data"),
        ]
        for nombre, ruta in candidatos:
            try:
                if str(ruta) and ruta.exists():
                    return nombre
            except Exception:
                continue
        return None

    def _args_idioma_cli(self):
        if not self._preferir_idioma_programa:
            return []
        return ["--extractor-args", f"youtube:lang={self._idioma_preferido}"]

    def _resolver_fuente_autenticacion(self):
        if self._metodo_autenticacion == "cookies_txt":
            return ("cookies_txt", self._archivo_cookies) if self._archivo_cookies else None
        navegador = self._resolver_navegador_cookies()
        return ("navegador", navegador) if navegador else None

    def _descripcion_fuente_autenticacion(self):
        fuente = self._resolver_fuente_autenticacion()
        if not fuente:
            return ""
        if fuente[0] == "cookies_txt":
            return "archivo cookies.txt"
        return f"sesión del navegador {fuente[1]}"

    def _args_cookies_cli(self):
        fuente = self._resolver_fuente_autenticacion()
        if not fuente:
            return []
        tipo, valor = fuente
        if tipo == "cookies_txt":
            valido, mensaje = validar_archivo_cookies_netscape(valor)
            if not valido:
                raise ErrorYoutubeBloqueo(mensaje)
            return ["--cookies", str(Path(valor).expanduser())]
        return ["--cookies-from-browser", valor]

    def _opciones_idioma_python(self):
        if not self._preferir_idioma_programa:
            return {}
        return {"extractor_args": {"youtube": {"lang": [self._idioma_preferido]}}}

    def _opciones_cookies_python(self):
        fuente = self._resolver_fuente_autenticacion()
        if not fuente:
            return {}
        tipo, valor = fuente
        if tipo == "cookies_txt":
            valido, mensaje = validar_archivo_cookies_netscape(valor)
            if not valido:
                raise ErrorYoutubeBloqueo(mensaje)
            return {"cookiefile": str(Path(valor).expanduser())}
        return {"cookiesfrombrowser": (valor, None, None, None)}

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
        if isinstance(error, (DescargaCancelada, ErrorYoutubeBloqueo, ErrorVideoNoDisponible, MotorAlternativoCancelado)):
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
            "failed to decrypt with dpapi", "cookies.txt",
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

    def listar_videos_coleccion(self, url, limite=50, tipo="canal", inicio=1):
        """Lista videos de un canal o una lista de reproducción sin descargarlos.

        ``inicio`` es 1-based. Si ``limite`` es None se solicitan todos los
        elementos disponibles desde ``inicio``. Para listas grandes se usa
        extracción plana para evitar resolver cada video individualmente.
        """
        url = str(url or "").strip()
        if not url:
            return []

        try:
            inicio = max(1, int(inicio or 1))
        except (TypeError, ValueError):
            inicio = 1

        sin_limite = limite is None
        if not sin_limite:
            try:
                limite = int(limite)
            except (TypeError, ValueError):
                limite = 50
            limite = max(1, limite)

        tipo = "playlist" if str(tipo).lower() in {"playlist", "lista", "lista de reproducción"} else "canal"
        # Para canales mantenemos el límite general para proteger búsquedas accidentales.
        if tipo == "canal" and not sin_limite:
            limite = min(MAX_RESULTADOS_BUSQUEDA, limite)
        url_listado = self._preparar_url_coleccion_para_listar(url, tipo)

        motor = self._buscar_motor_externo()
        if motor:
            return self._listar_videos_coleccion_cli(motor, url_listado, limite, inicio=inicio)

        opciones = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "ignoreerrors": True,
            "playliststart": inicio,
        }
        if not sin_limite:
            opciones["playlistend"] = inicio + limite - 1

        info = self._extraer_con_reintentos(url_listado, download=False, opciones_extra=opciones)
        entradas = info.get("entries", []) if isinstance(info, dict) else []
        return self._normalizar_entradas_video(entradas, limite)

    def listar_videos_coleccion_rango(self, url, desde, hasta, tipo="playlist"):
        try:
            desde = max(1, int(desde))
            hasta = max(desde, int(hasta))
        except (TypeError, ValueError) as exc:
            raise ValueError("El rango de la playlist no es válido.") from exc
        return self.listar_videos_coleccion(url, limite=hasta - desde + 1, tipo=tipo, inicio=desde)

    def obtener_informacion_coleccion(self, url, tipo="playlist"):
        """Obtiene título, autor y cantidad aproximada de una colección."""
        url = str(url or "").strip()
        if not url:
            return {}
        tipo = "playlist" if str(tipo).lower() in {"playlist", "lista", "lista de reproducción"} else "canal"
        url_listado = self._preparar_url_coleccion_para_listar(url, tipo)
        motor = self._buscar_motor_externo()
        if motor:
            info = self._ejecutar_cli_json(
                motor,
                ["--quiet", "--dump-single-json", "--flat-playlist", "--ignore-errors", "--playlist-end", "1", url_listado],
            )
        else:
            opciones = {
                "quiet": True,
                "extract_flat": True,
                "skip_download": True,
                "ignoreerrors": True,
                "playlistend": 1,
            }
            info = self._extraer_con_reintentos(url_listado, download=False, opciones_extra=opciones)
        if not isinstance(info, dict):
            return {}
        titulo = info.get("title") or info.get("playlist_title") or ("Lista de reproducción" if tipo == "playlist" else "Canal")
        autor = info.get("uploader") or info.get("channel") or info.get("creator") or "No disponible"
        total = info.get("playlist_count") or info.get("n_entries")
        try:
            total = int(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        return {
            "tipo": "Lista de reproducción" if tipo == "playlist" else "Canal",
            "tipo_clave": tipo,
            "titulo": str(titulo),
            "canal": str(autor),
            "autor": str(autor),
            "url": url,
            "id": info.get("id") or "",
            "descripcion": info.get("description") or "No disponible",
            "total_elementos": total,
        }

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
            "total_elementos": entrada.get("playlist_count") or entrada.get("n_entries"),
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
            if limite is not None and len(videos) >= limite:
                break

        return videos


    def completar_metadatos_resultado(self, resultado):
        """Completa canal, fecha, visualizaciones y duración solo cuando el usuario enfoca un resultado.

        La búsqueda inicial sigue siendo rápida. Esta consulta adicional se hace de forma
        diferida para no multiplicar por cientos las solicitudes a YouTube.
        """
        resultado = dict(resultado or {})
        url = resultado.get("url") or ""
        if not url:
            return resultado
        info = self.obtener_informacion(url)
        for clave in ("titulo", "canal", "duracion", "duracion_texto", "fecha", "fecha_texto", "visualizaciones", "visualizaciones_texto", "url"):
            valor = info.get(clave)
            if valor not in (None, "", "No disponible"):
                resultado[clave] = valor
        return resultado


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

    def _args_cli_base(self, incluir_cookies=False):
        # No fijamos un User-Agent antiguo: yt-dlp mantiene sus propios perfiles
        # actualizados y puede elegir el más apropiado.
        idiomas_accept = {
            "es": "es-ES,es;q=0.9,en;q=0.8",
            "en": "en-US,en;q=0.9",
            "pt": "pt-BR,pt;q=0.9,en;q=0.8",
            "fr": "fr-FR,fr;q=0.9,en;q=0.8",
            "it": "it-IT,it;q=0.9,en;q=0.8",
            "ru": "ru-RU,ru;q=0.9,en;q=0.8",
        }
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
            f"Accept-Language: {idiomas_accept.get(self._idioma_preferido, idiomas_accept['es'])}",
        ]
        args.extend(self._args_idioma_cli())
        args.extend(argumentos_runtime_javascript_cli())
        if incluir_cookies:
            args.extend(self._args_cookies_cli())
        return args

    def _ejecutar_cli_json(self, motor, args):
        def ejecutar(incluir_cookies=False):
            comando = [motor] + self._args_cli_base(incluir_cookies=incluir_cookies) + args
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
            return resultado

        resultado = ejecutar(False)
        salida = (resultado.stdout or "").strip()
        error = limpiar_texto_consola((resultado.stderr or "").strip())

        if resultado.returncode != 0:
            mensaje = error or salida or "El motor de descarga devolvió un error."
            mensaje_minusculas = mensaje.lower()
            if self._es_bloqueo_youtube(mensaje_minusculas) and self._resolver_fuente_autenticacion():
                descripcion = self._descripcion_fuente_autenticacion()
                self._registrar_motor(f"YouTube pidió verificación; reintentando con {descripcion}")
                resultado = ejecutar(True)
                salida = (resultado.stdout or "").strip()
                error = limpiar_texto_consola((resultado.stderr or "").strip())
                if resultado.returncode == 0:
                    self._registrar_motor(f"Operación resuelta utilizando {descripcion}")
                else:
                    mensaje = error or salida or "El motor de descarga devolvió un error."
                    mensaje_minusculas = mensaje.lower()

            if resultado.returncode != 0:
                if self._es_error_runtime_javascript(mensaje_minusculas):
                    raise RuntimeError(
                        "YouTube necesita un motor JavaScript compatible para este contenido. "
                        "Utilice la versión portable oficial o vuelva a preparar el programa."
                    )
                if self._es_error_dpapi(mensaje_minusculas):
                    raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(mensaje_minusculas))
                if self._es_bloqueo_youtube(mensaje_minusculas):
                    raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(mensaje_minusculas))
                if self._es_video_no_disponible(mensaje_minusculas):
                    raise ErrorVideoNoDisponible(self._mensaje_video_no_disponible(mensaje))
                raise RuntimeError(mensaje)

        if not salida:
            raise RuntimeError("El motor de descarga no devolvió información.")

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

    def _listar_videos_coleccion_cli(self, motor, url, limite, inicio=1):
        argumentos = [
            "--quiet",
            "--dump-single-json",
            "--flat-playlist",
            "--ignore-errors",
        ]
        if int(inicio or 1) > 1:
            argumentos.extend(["--playlist-start", str(int(inicio))])
        if limite is not None:
            argumentos.extend(["--playlist-end", str(int(inicio or 1) + int(limite) - 1)])
        argumentos.append(url)
        info = self._ejecutar_cli_json(motor, argumentos)
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
        ffmpeg_location = self._buscar_ffmpeg()
        formato = str(formato or "MP3").upper()

        def construir_args(incluir_cookies=False):
            args = self._args_cli_base(incluir_cookies=incluir_cookies) + [
                "--newline",
                "--no-playlist",
                "--windows-filenames",
                "--continue",
                "--part",
                "--progress-template",
                "download:%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
                "-o",
                outtmpl,
            ]
            if formato in _AUDIO_CODEC_YTDLP:
                if not ffmpeg_location:
                    raise RuntimeError(
                        "No se encontró el componente de conversión necesario. Utilice la versión portable oficial del programa."
                    )
                args += ["-f", "bestaudio/best", "-x", "--audio-format", _AUDIO_CODEC_YTDLP[formato]]
                if formato not in _FORMATOS_AUDIO_SIN_PERDIDA:
                    args += ["--audio-quality", f"{calidad_numero or '320'}K"]
                args += ["--ffmpeg-location", ffmpeg_location]
            else:
                args += ["-f", _selector_video(calidad), "--merge-output-format", "mp4"]
                if ffmpeg_location:
                    args += ["--ffmpeg-location", ffmpeg_location]
            args.append(url)
            return args

        def ejecutar(incluir_cookies=False):
            comando = [motor] + construir_args(incluir_cookies=incluir_cookies)
            if callback_progreso:
                callback_progreso({
                    "porcentaje": 0,
                    "mensaje": traducir_formato("Preparando descarga con motor externo en formato {formato}", formato=formato),
                    "estado": traducir("Preparando"),
                })
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
            return codigo, "\n".join(salida)

        codigo, texto_salida = ejecutar(False)
        if codigo != 0 and self._es_bloqueo_youtube(texto_salida.lower()) and self._resolver_fuente_autenticacion():
            descripcion = self._descripcion_fuente_autenticacion()
            self._registrar_motor(f"Descarga bloqueada por YouTube; reintentando con {descripcion}")
            if callback_progreso:
                callback_progreso({"porcentaje": 0, "mensaje": "Reintentando con la autenticación configurada", "estado": "Verificando acceso"})
            codigo, texto_salida = ejecutar(True)
            if codigo == 0:
                self._registrar_motor(f"Descarga resuelta utilizando {descripcion}")

        if codigo != 0:
            salida_minusculas = texto_salida.lower()
            if self._es_error_runtime_javascript(salida_minusculas):
                raise RuntimeError(
                    "YouTube necesita un motor JavaScript compatible para este contenido. Utilice la versión portable oficial o vuelva a preparar el programa."
                )
            if self._es_error_dpapi(salida_minusculas):
                raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(salida_minusculas))
            if self._es_bloqueo_youtube(salida_minusculas):
                raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(salida_minusculas))
            if self._es_video_no_disponible(salida_minusculas):
                raise ErrorVideoNoDisponible(self._mensaje_video_no_disponible(texto_salida))
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

                if self._es_video_no_disponible(mensaje):
                    raise ErrorVideoNoDisponible(self._mensaje_video_no_disponible(str(error))) from error

                # En errores de red, formatos o extracción, prueba la siguiente estrategia.
                if self._es_error_reintentable(mensaje):
                    continue

                raise error

        if hubo_bloqueo_youtube and self._resolver_fuente_autenticacion():
            descripcion = self._descripcion_fuente_autenticacion()
            self._registrar_motor(f"YouTube pidió verificación; reintentando con {descripcion} mediante yt-dlp Python")
            opciones = self._opciones_base()
            opciones.update(self._opciones_cookies_python())
            opciones.update(opciones_extra)
            try:
                with yt_dlp.YoutubeDL(opciones) as ydl:
                    resultado = ydl.extract_info(url, download=download)
                self._registrar_motor(f"Operación resuelta utilizando {descripcion}")
                return resultado
            except DescargaCancelada:
                raise
            except Exception as error_cookies:
                ultimo_error = error_cookies
                if self._es_error_dpapi(str(error_cookies)):
                    raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(str(error_cookies))) from error_cookies

        if hubo_bloqueo_youtube:
            raise ErrorYoutubeBloqueo(self._mensaje_autenticacion_fallida(str(ultimo_error or ""))) from ultimo_error

        if ultimo_error:
            raise ultimo_error

        raise RuntimeError("No se pudo completar la operación.")

    def _opciones_base(self):
        idiomas_accept = {
            "es": "es-ES,es;q=0.9,en;q=0.8",
            "en": "en-US,en;q=0.9",
            "pt": "pt-BR,pt;q=0.9,en;q=0.8",
            "fr": "fr-FR,fr;q=0.9,en;q=0.8",
            "it": "it-IT,it;q=0.9,en;q=0.8",
            "ru": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        opciones = {
            "retries": 5,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "socket_timeout": 30,
            "no_color": True,
            "no_warnings": True,
            "logger": _LoggerSilencioso(),
            "http_headers": {
                "Accept-Language": idiomas_accept.get(self._idioma_preferido, idiomas_accept["es"]),
            },
        }
        opciones.update(self._opciones_idioma_python())
        return opciones

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
        """Detecta solicitudes de autenticación/verificación de YouTube.

        YouTube puede devolver el mismo error traducido al idioma solicitado por
        el programa. Por eso no debemos depender únicamente del texto inglés.
        """
        import unicodedata

        bruto = str(mensaje or "").lower().replace("’", "'").replace("�", "")
        normal = unicodedata.normalize("NFKD", bruto)
        normal = "".join(c for c in normal if not unicodedata.combining(c))

        patrones = [
            # Inglés
            "sign in to confirm",
            "not a bot",
            "confirm you're not a bot",
            "login required",
            "cookies for the authentication",
            "cookies-from-browser",

            # Español
            "inicia sesion para confirmar",
            "iniciar sesion para confirmar",
            "no eres un bot",

            # Portugués
            "faca login para confirmar",
            "inicie sessao para confirmar",
            "nao e um robo",
            "nao e um bot",

            # Francés
            "connectez-vous pour confirmer",
            "vous n'etes pas un robot",
            "vous n'etes pas un bot",

            # Italiano
            "accedi per confermare",
            "non sei un bot",
            "non sei un robot",

            # Ruso (formas frecuentes de los mensajes de verificación)
            "vojdite, chtoby podtverdit",
            "ne robot",
            "не робот",
        ]

        if any(patron in normal for patron in patrones):
            return True

        # Respaldo deliberadamente conservador: algunos mensajes localizados
        # conservan la palabra "bot" aunque el resto cambie.
        indicadores_login = (
            "sign in", "login", "sesion", "sessao", "connectez", "accedi",
            "confirm", "verific", "autentic",
        )
        return "bot" in normal and any(indicador in normal for indicador in indicadores_login)

    def _es_error_dpapi(self, mensaje):
        texto = str(mensaje or "").lower()
        return "failed to decrypt with dpapi" in texto or ("dpapi" in texto and "decrypt" in texto)

    def _es_video_no_disponible(self, mensaje):
        """Detecta videos que no están disponibles para nadie, no solo para el programa.

        A diferencia de _es_bloqueo_youtube, aquí reintentar con cookies o
        sesión del navegador no cambia el resultado: el contenido no existe,
        es privado, fue eliminado o está restringido por copyright/edad/país.
        """
        texto = str(mensaje or "").lower()
        patrones = [
            "private video", "video is private", "video privado",
            "video unavailable", "video no disponible", "vídeo no disponible",
            "has been removed", "eliminado por el usuario", "ha sido eliminado",
            "copyright", "members-only", "members only", "solo para miembros",
            "no longer available", "ya no está disponible", "ya no esta disponible",
            "this video is unavailable",
            "not available in your country", "no disponible en tu país", "no disponible en su país",
            "no disponible en tu pais", "no disponible en su pais",
            "age-restricted", "restringido por edad",
            "video does not exist", "el video no existe",
        ]
        return any(patron in texto for patron in patrones)

    def _mensaje_video_no_disponible(self, detalle=""):
        detalle = limpiar_texto_consola(str(detalle or "")).strip()
        mensaje = traducir(
            "Este video no está disponible. Puede ser privado, haber sido eliminado por su autor, "
            "o estar restringido por copyright, edad o país. No es un problema del programa ni de "
            "la autenticación configurada."
        )
        if detalle:
            mensaje += "\n\n" + traducir_formato("Detalle técnico: {detalle}", detalle=detalle)
        return mensaje

    def _mensaje_autenticacion_fallida(self, salida=""):
        if self._es_error_dpapi(salida):
            return traducir(
                "Windows no permitió descifrar las cookies del navegador. Seleccione Archivo cookies.txt en Herramientas, Opciones, Autenticación de YouTube y vuelva a intentarlo."
            )
        if self._metodo_autenticacion == "cookies_txt":
            return traducir(
                "YouTube no aceptó el archivo cookies.txt configurado. Exporte un archivo nuevo en formato Netscape desde una sesión iniciada de YouTube y vuelva a intentarlo."
            )
        if self._metodo_autenticacion == "navegador":
            return traducir(
                "YouTube no pudo utilizar la sesión del navegador configurado. Puede seleccionar Archivo cookies.txt, recomendado en Windows, desde Herramientas, Opciones."
            )
        return traducir(
            "YouTube solicitó verificación o inicio de sesión. Configure un archivo cookies.txt desde Herramientas, Opciones, Autenticación de YouTube y vuelva a intentarlo."
        )

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
