import os
import sys
import threading
from pathlib import Path

import wx

from voz import hablar_async as _hablar_async_original
from i18n import formatear_duracion, traducir, traducir_clave, traducir_dinamico, traducir_formato


def hablar_async(texto, *args, **kwargs):
    return _hablar_async_original(traducir_dinamico(texto), *args, **kwargs)
from descargador import ErrorYoutubeBloqueo
from configuracion import guardar_configuracion_completa


class ErrorReproductor(Exception):
    """Error controlado del reproductor interno."""


def _base_programa():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _carpetas_posibles_mpv():
    """Rutas donde podría estar mpv-1.dll en desarrollo o en PyInstaller."""
    rutas = []

    def agregar(ruta):
        if not ruta:
            return
        ruta = Path(ruta)
        texto = str(ruta)
        if texto not in rutas:
            rutas.append(texto)

    base = _base_programa()

    agregar(base)
    agregar(base / "mpv")
    agregar(base / "bin")
    agregar(base / "_internal")
    agregar(base / "_internal" / "mpv")
    agregar(base / "_internal" / "bin")

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass = Path(meipass)
        agregar(meipass)
        agregar(meipass / "mpv")
        agregar(meipass / "bin")

    # Por si el usuario tiene MPV instalado o copiado manualmente.
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        raiz = os.environ.get(variable)
        if raiz:
            agregar(Path(raiz) / "mpv")
            agregar(Path(raiz) / "Programs" / "mpv")

    return rutas


def _preparar_entorno_mpv():
    """Agrega al PATH las carpetas con mpv-1.dll para que python-mpv pueda cargarla."""
    encontradas = []

    for carpeta in _carpetas_posibles_mpv():
        try:
            ruta = Path(carpeta)
            dll = ruta / "mpv-1.dll"
            if dll.exists():
                encontradas.append(str(ruta))
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(str(ruta))
                    except Exception:
                        pass
                os.environ["PATH"] = str(ruta) + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass

    return encontradas



def listar_dispositivos_audio():
    """Devuelve dispositivos de salida de MPV como pares (id, descripción).

    El identificador es el valor estable que MPV espera en ``audio-device``.
    La descripción es solo para mostrarla al usuario. Siempre se incluye
    ``auto`` para respetar el dispositivo predeterminado de Windows.
    """
    dispositivos = [("auto", traducir("Predeterminado de Windows"))]
    _preparar_entorno_mpv()
    try:
        import mpv  # type: ignore
        prueba = mpv.MPV(
            ytdl=False,
            video=False,
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            terminal=False,
            msg_level="all=no",
        )
        try:
            lista = getattr(prueba, "audio_device_list", None) or []
            vistos = {"auto"}
            for item in lista:
                if not isinstance(item, dict):
                    continue
                nombre = str(item.get("name") or "").strip()
                descripcion = str(item.get("description") or nombre).strip()
                if not nombre or nombre in vistos:
                    continue
                vistos.add(nombre)
                dispositivos.append((nombre, descripcion or nombre))
        finally:
            try:
                prueba.terminate()
            except Exception:
                pass
    except Exception:
        pass
    return dispositivos


def diagnostico_reproductor():
    """Devuelve un diagnóstico legible y localizado del reproductor interno MPV."""
    lineas = []
    lineas.append(traducir("Diagnóstico del reproductor interno"))
    lineas.append("")
    lineas.append(traducir("Motor configurado: MPV portable"))
    lineas.append("")

    rutas_mpv = _preparar_entorno_mpv()

    try:
        import mpv  # type: ignore
        lineas.append(traducir("python-mpv instalado: Sí"))
        version_modulo = getattr(mpv, "__version__", traducir("No disponible"))
        lineas.append(traducir_formato("Versión del módulo python-mpv: {version}", version=version_modulo))

        try:
            prueba = mpv.MPV(
                ytdl=False,
                video=False,
                osc=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                terminal=False,
                msg_level="all=no",
            )
            try:
                prueba.terminate()
            except Exception:
                pass
            lineas.append(traducir("MPV / mpv-1.dll disponible: Sí"))
        except Exception as exc:
            lineas.append(traducir("MPV / mpv-1.dll disponible: No"))
            lineas.append(traducir_formato("Detalle: {detalle}", detalle=exc))
    except ModuleNotFoundError:
        lineas.append(traducir("python-mpv instalado: No"))
        lineas.append(traducir("Solución en modo Python: ejecute python -m pip install python-mpv"))
    except Exception as exc:
        lineas.append(traducir("python-mpv instalado: Error al importar"))
        lineas.append(traducir_formato("Detalle: {detalle}", detalle=exc))

    lineas.append("")
    lineas.append(traducir("Rutas MPV detectadas con mpv-1.dll:"))
    if rutas_mpv:
        for ruta in rutas_mpv:
            lineas.append(f"- {ruta}")
    else:
        lineas.append(traducir("- No se encontró mpv-1.dll en rutas comunes."))

    lineas.append("")
    lineas.append(traducir("Rutas revisadas:"))
    for ruta in _carpetas_posibles_mpv():
        p = Path(ruta)
        existe = traducir("existe") if p.exists() else traducir("no existe")
        tiene = traducir("con mpv-1.dll") if (p / "mpv-1.dll").exists() else traducir("sin mpv-1.dll")
        lineas.append(f"- {ruta} ({existe}, {tiene})")

    return "\n".join(lineas)


class ReproductorMPV:
    """Pequeño envoltorio sobre MPV para reproducir audio/video por URL."""

    def __init__(self, volumen_inicial=50, velocidad_inicial=1.0, dispositivo_salida="auto"):
        rutas_mpv = _preparar_entorno_mpv()

        try:
            import mpv  # type: ignore
        except ModuleNotFoundError as exc:
            raise ErrorReproductor(
                "Falta la librería de Python llamada python-mpv. "
                "Abra una consola en la carpeta del programa y ejecute: python -m pip install python-mpv"
            ) from exc
        except Exception as exc:
            raise ErrorReproductor(traducir_formato("No se pudo importar python-mpv. Detalle: {detalle}", detalle=exc)) from exc

        self.mpv = mpv
        try:
            volumen_inicial = int(volumen_inicial)
        except Exception:
            volumen_inicial = 50
        try:
            velocidad_inicial = float(velocidad_inicial)
        except Exception:
            velocidad_inicial = 1.0

        self.volumen = max(0, min(100, volumen_inicial))
        self.velocidad = round(max(0.5, min(2.0, velocidad_inicial)), 2)
        self.dispositivo_salida = str(dispositivo_salida or "auto").strip() or "auto"
        self.cargado = False
        self.url = None
        self.pausado = False

        try:
            opciones_player = dict(
                ytdl=False,
                video=False,
                osc=False,
                input_default_bindings=False,
                input_vo_keyboard=False,
                terminal=False,
                msg_level="all=no",
                audio_display="no",
                audio_device=self.dispositivo_salida,
            )
            try:
                self.player = mpv.MPV(**opciones_player)
            except Exception:
                # Si un auricular o HDMI guardado ya no existe, no dejamos al
                # usuario sin reproductor: volvemos al dispositivo de Windows.
                if self.dispositivo_salida == "auto":
                    raise
                self.dispositivo_salida = "auto"
                opciones_player["audio_device"] = "auto"
                self.player = mpv.MPV(**opciones_player)
            self.player.volume = self.volumen
            self.player.speed = self.velocidad
        except Exception as exc:
            detalle_rutas = ""
            if rutas_mpv:
                detalle_rutas = traducir_formato(" Rutas MPV detectadas: {rutas}", rutas="; ".join(rutas_mpv))
            raise ErrorReproductor(
                traducir_formato(
                    "No se pudo iniciar MPV desde Python. Verifique que mpv-1.dll esté junto al programa o dentro de la carpeta _internal. Detalle técnico: {detalle}.{rutas}",
                    detalle=exc,
                    rutas=detalle_rutas,
                )
            ) from exc

    def cargar(self, url):
        if not url:
            raise ErrorReproductor("No hay URL de reproducción para cargar.")
        self.url = url
        self.cargado = True

    def reproducir(self):
        if not self.cargado or not self.url:
            raise ErrorReproductor("No hay contenido cargado para reproducir.")
        self.player.play(self.url)
        self.pausado = False
        try:
            self.player.pause = False
        except Exception:
            pass

    def pausar_o_continuar(self):
        if not self.cargado:
            raise ErrorReproductor("No hay contenido cargado para reproducir.")
        self.pausado = not bool(getattr(self.player, "pause", False))
        self.player.pause = self.pausado
        return "Pausado" if self.pausado else "Reproduciendo"

    def detener(self):
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.terminate()
        except Exception:
            pass

    def adelantar(self, segundos=10):
        try:
            self.player.command("seek", float(segundos), "relative")
        except Exception:
            # Respaldo usando time_pos.
            actual = self.posicion() or 0
            self._set_posicion(actual + int(segundos))

    def retroceder(self, segundos=10):
        try:
            self.player.command("seek", -float(segundos), "relative")
        except Exception:
            actual = self.posicion() or 0
            self._set_posicion(max(0, actual - int(segundos)))

    def _set_posicion(self, segundos):
        try:
            self.player.time_pos = max(0, int(segundos))
        except Exception:
            pass

    def cambiar_volumen(self, delta):
        self.volumen = max(0, min(100, self.volumen + int(delta)))
        self.player.volume = self.volumen
        return self.volumen

    def cambiar_velocidad(self, delta):
        self.velocidad = round(max(0.5, min(2.0, self.velocidad + float(delta))), 2)
        try:
            self.player.speed = self.velocidad
        except Exception:
            pass
        return self.velocidad

    def duracion(self):
        try:
            valor = self.player.duration
        except Exception:
            valor = None
        if valor is None or valor <= 0:
            return None
        return int(valor)

    def posicion(self):
        try:
            valor = self.player.time_pos
        except Exception:
            valor = None
        if valor is None or valor < 0:
            return 0
        return int(valor)


def formato_tiempo(segundos):
    return formatear_duracion(segundos)


class DialogoReproductor(wx.Dialog):
    """Diálogo accesible para escuchar un resultado antes de descargar."""

    def __init__(self, padre, descargador, url, resultado, configuracion=None):
        super().__init__(padre, title=traducir("Reproductor interno"), size=(720, 300))
        self.padre = padre
        self.descargador = descargador
        self.url = url
        self.resultado = resultado or {}
        self.configuracion = configuracion or {}
        self.titulo_video = self.resultado.get("titulo", "resultado seleccionado")
        self.salto_segundos = self._leer_salto_segundos()
        self.volumen_inicial = self._leer_volumen_inicial()
        self.velocidad_inicial = self._leer_velocidad_inicial()
        self.dispositivo_salida = str(self.configuracion.get("reproductor_dispositivo_salida", "auto") or "auto")
        self.anunciar_posicion_al_pausar = bool(self.configuracion.get("reproductor_anunciar_posicion_al_pausar", False))
        self.reproductor = None
        self.preparando = True
        self.cerrando = False

        self._crear_interfaz()
        self._crear_eventos()

        self.temporizador = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._actualizar_posicion_visual, self.temporizador)

        hablar_async(f"Preparando reproducción de {self.titulo_video}", limpiar=True)
        wx.CallLater(250, self._iniciar_preparacion)

    def _iniciar_preparacion(self):
        if self.cerrando:
            return
        hilo = threading.Thread(target=self._preparar_hilo, daemon=True)
        hilo.start()

    def _leer_volumen_inicial(self):
        valor = str(self.configuracion.get("reproductor_volumen_inicial", "50%"))
        try:
            return int(valor.replace("%", "").strip())
        except Exception:
            return 50

    def _leer_salto_segundos(self):
        valor = str(self.configuracion.get("reproductor_salto_segundos", "10 segundos"))
        try:
            return int(valor.split()[0])
        except Exception:
            return 10

    def _leer_velocidad_inicial(self):
        valor = str(self.configuracion.get("reproductor_velocidad_inicial", "1.00"))
        try:
            return float(valor)
        except Exception:
            return 1.0

    def _crear_interfaz(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.texto_titulo = wx.StaticText(self, label=f"Reproductor: {self.titulo_video}")
        sizer.Add(self.texto_titulo, 0, wx.EXPAND | wx.ALL, 10)

        self.estado = wx.TextCtrl(
            self,
            value="Preparando reproducción...",
            style=wx.TE_READONLY,
        )
        self.estado.SetName("Estado del reproductor")
        sizer.Add(self.estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila_botones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_pausa = wx.Button(self, label="Pausar o continuar")
        self.btn_detener = wx.Button(self, label="Detener y volver")
        self.btn_pausa.SetName("Pausar o continuar reproducción")
        self.btn_detener.SetName("Detener reproducción y volver a resultados")
        fila_botones.Add(self.btn_pausa, 0, wx.ALL, 5)
        fila_botones.Add(self.btn_detener, 0, wx.ALL, 5)
        sizer.Add(fila_botones, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        self.SetSizer(sizer)

    def _crear_eventos(self):
        self.Bind(wx.EVT_CHAR_HOOK, self._tecla)
        self.Bind(wx.EVT_CLOSE, self._cerrar)
        self.btn_pausa.Bind(wx.EVT_BUTTON, lambda evento: self._pausar_o_continuar())
        self.btn_detener.Bind(wx.EVT_BUTTON, lambda evento: self._detener_y_cerrar())

    def _preparar_hilo(self):
        try:
            info = self.descargador.obtener_url_reproduccion(self.url)
            wx.CallAfter(self._iniciar_reproduccion, info)
        except ErrorYoutubeBloqueo as exc:
            wx.CallAfter(self._error_youtube_bloqueo, str(exc))
        except Exception as exc:
            wx.CallAfter(self._error_preparando, str(exc))

    def _iniciar_reproduccion(self, info):
        if self.cerrando:
            return

        try:
            self.reproductor = ReproductorMPV(
                volumen_inicial=self.volumen_inicial,
                velocidad_inicial=self.velocidad_inicial,
                dispositivo_salida=self.dispositivo_salida,
            )
            self.reproductor.cargar(info["stream_url"])
            self.reproductor.reproducir()
            self.preparando = False
            self.estado.SetValue(traducir_dinamico(
                traducir_formato("Reproduciendo. Volumen {volumen} por ciento. Velocidad {velocidad}", volumen=self.volumen_inicial, velocidad=f"{self.velocidad_inicial:.2f}")
            ))
            hablar_async(
                traducir_formato("Reproduciendo. Volumen {volumen} por ciento. Velocidad {velocidad}", volumen=self.volumen_inicial, velocidad=f"{self.velocidad_inicial:.2f}"),
                limpiar=True,
            )
            self.temporizador.Start(2000)
            self.SetFocus()
        except Exception as exc:
            self._error_preparando(str(exc))

    def _error_youtube_bloqueo(self, mensaje):
        self.preparando = False
        self.estado.SetValue(traducir_dinamico("YouTube bloqueó la reproducción automática."))
        hablar_async("YouTube bloqueó la reproducción automática", limpiar=True)
        wx.MessageBox(
            traducir_clave("__player.youtube_blocked.body__").format(detalle=mensaje),
            "Reproductor interno",
            wx.OK | wx.ICON_INFORMATION,
        )
        self._detener_y_cerrar(anunciar=False)

    def _error_preparando(self, mensaje):
        self.preparando = False
        self.estado.SetValue(traducir_dinamico("No se pudo iniciar el reproductor interno."))
        hablar_async("No se pudo iniciar el reproductor interno", limpiar=True)
        wx.MessageBox(
            traducir_clave("__player.start_error.body__").format(detalle=mensaje),
            "Reproductor interno",
            wx.OK | wx.ICON_ERROR,
        )
        self._detener_y_cerrar(anunciar=False)

    def _tecla(self, evento):
        codigo = evento.GetKeyCode()

        mapa = {
            ord("1"): "retroceder",
            ord("2"): "pausa",
            ord("3"): "adelantar",
            ord("4"): "detener",
            ord("5"): "velocidad_menos",
            ord("6"): "velocidad_mas",
            ord("7"): "volumen_menos",
            ord("8"): "volumen_mas",
            ord("0"): "duracion",
            ord("9"): "posicion",
            wx.WXK_NUMPAD1: "retroceder",
            wx.WXK_NUMPAD2: "pausa",
            wx.WXK_NUMPAD3: "adelantar",
            wx.WXK_NUMPAD4: "detener",
            wx.WXK_NUMPAD5: "velocidad_menos",
            wx.WXK_NUMPAD6: "velocidad_mas",
            wx.WXK_NUMPAD7: "volumen_menos",
            wx.WXK_NUMPAD8: "volumen_mas",
            wx.WXK_NUMPAD0: "duracion",
            wx.WXK_NUMPAD9: "posicion",
        }

        if codigo in (wx.WXK_ESCAPE,):
            self._detener_y_cerrar()
            return

        accion = mapa.get(codigo)

        if accion:
            self._ejecutar_accion(accion)
            return

        evento.Skip()

    def _guardar_volumen_actual(self):
        """Guarda el último volumen elegido para que la próxima reproducción lo respete."""
        try:
            if not self.reproductor:
                return
            volumen = int(getattr(self.reproductor, "volumen", self.volumen_inicial))
            volumen = max(0, min(100, volumen))
            self.volumen_inicial = volumen
            self.configuracion["reproductor_volumen_inicial"] = f"{volumen}%"
            guardar_configuracion_completa(self.configuracion)
        except Exception:
            pass

    def _ejecutar_accion(self, accion):
        if self.preparando or not self.reproductor:
            hablar_async("El reproductor todavía se está preparando", limpiar=True)
            return

        try:
            if accion == "retroceder":
                self.reproductor.retroceder(self.salto_segundos)
                self._decir_estado(traducir_formato("Retrocediendo {segundos} segundos", segundos=self.salto_segundos))
            elif accion == "pausa":
                estado = self.reproductor.pausar_o_continuar()
                if estado == "Pausado" and self.anunciar_posicion_al_pausar:
                    self._decir_estado(traducir_formato("Pausado. Posición actual {posicion}", posicion=formato_tiempo(self.reproductor.posicion())))
                else:
                    self._decir_estado(estado)
            elif accion == "adelantar":
                self.reproductor.adelantar(self.salto_segundos)
                self._decir_estado(traducir_formato("Adelantando {segundos} segundos", segundos=self.salto_segundos))
            elif accion == "detener":
                self._detener_y_cerrar()
            elif accion == "velocidad_menos":
                velocidad = self.reproductor.cambiar_velocidad(-0.25)
                self._decir_estado(f"Velocidad {velocidad}")
            elif accion == "velocidad_mas":
                velocidad = self.reproductor.cambiar_velocidad(0.25)
                self._decir_estado(f"Velocidad {velocidad}")
            elif accion == "volumen_menos":
                volumen = self.reproductor.cambiar_volumen(-10)
                self._guardar_volumen_actual()
                self._decir_estado(traducir_formato("Volumen {volumen} por ciento", volumen=volumen))
            elif accion == "volumen_mas":
                volumen = self.reproductor.cambiar_volumen(10)
                self._guardar_volumen_actual()
                self._decir_estado(traducir_formato("Volumen {volumen} por ciento", volumen=volumen))
            elif accion == "duracion":
                self._decir_estado(traducir_formato("Duración total {duracion}", duracion=formato_tiempo(self.reproductor.duracion())))
            elif accion == "posicion":
                self._decir_estado(traducir_formato("Posición actual {posicion}", posicion=formato_tiempo(self.reproductor.posicion())))
        except Exception as exc:
            self._decir_estado(f"No se pudo ejecutar la acción. {exc}")

    def _decir_estado(self, texto):
        texto = traducir_dinamico(texto)
        try:
            self.estado.SetValue(texto)
        except Exception:
            pass
        _hablar_async_original(texto, limpiar=True)

    def _actualizar_posicion_visual(self, evento=None):
        if not self.reproductor or self.preparando:
            return

        try:
            posicion = formato_tiempo(self.reproductor.posicion())
            duracion = formato_tiempo(self.reproductor.duracion())
            self.estado.SetValue(traducir_dinamico(traducir_formato("Reproduciendo. Posición {posicion}. Duración {duracion}.", posicion=posicion, duracion=duracion)))
        except Exception:
            pass

    def _detener_y_cerrar(self, anunciar=True):
        if self.cerrando:
            return

        self.cerrando = True
        try:
            self.temporizador.Stop()
        except Exception:
            pass

        if self.reproductor:
            self._guardar_volumen_actual()
            self.reproductor.detener()

        if anunciar:
            hablar_async("Reproducción detenida. Volviendo a la lista", limpiar=True)

        try:
            if self.IsModal():
                self.EndModal(wx.ID_OK)
            else:
                self.Close()
        except Exception:
            try:
                self.Destroy()
            except Exception:
                pass

    def _pausar_o_continuar(self):
        self._ejecutar_accion("pausa")

    def _cerrar(self, evento):
        self._detener_y_cerrar()
