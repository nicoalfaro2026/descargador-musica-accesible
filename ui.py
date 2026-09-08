import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import wx

from i18n import (
    LANGUAGES,
    activar_wx,
    establecer_idioma,
    idioma_actual,
    traducir,
    traducir_clave,
    traducir_dinamico,
    traducir_formato,
)

from config import (
    APP_NOMBRE,
    CALIDADES_DISPONIBLES,
    FORMATOS_DISPONIBLES,
    HISTORIAL_ARCHIVO,
    LOG_ARCHIVO,
    LOGS_DIR,
    RESULTADOS_BUSQUEDA_DISPONIBLES,
    VERSION,
    opciones_calidad_para_formato,
)
from configuracion import (
    FRECUENCIAS_ACTUALIZACION,
    cargar_configuracion,
    fecha_iso_hoy,
    guardar_configuracion,
)
from descargador import DescargaCancelada, Descargador, ErrorAutenticacionYoutube, validar_archivo_cookies_netscape
from historial import agregar_descarga, leer_historial, limpiar_historial
from favoritos import alternar_favorito, esta_en_favoritos, leer_favoritos, quitar_favorito
from cola_descargas import (
    ESTADO_DESCARGANDO,
    ESTADO_ERROR,
    ESTADO_PENDIENTE,
    agregar_a_cola,
    agregar_varios_a_cola,
    actualizar_estado as actualizar_estado_cola,
    esta_en_cola,
    leer_cola,
    preparar_reintento_errores,
    restablecer_descargas_interrumpidas,
    quitar_de_cola,
    vaciar_cola,
)
from utils import abrir_carpeta, sanitizar_nombre_carpeta
from sonidos import reproducir_sonido
from voz import hablar_async, hablar_cierre, metodo_activo_voz, diagnostico_voz
from reproductor import DialogoReproductor, diagnostico_reproductor, listar_dispositivos_audio
import integracion_windows
from actualizador_app import (
    ActualizadorNoConfigurado,
    consultar_actualizacion,
    descargar_actualizacion,
    crear_script_aplicacion,
    ejecutar_script_y_salir,
    carpeta_temporal_actualizador,
    limpiar_carpeta_temporal_actualizador,
    es_version_mayor,
)

# Traduce también los mensajes hablados que se envían a NVDA/voz accesible.
_hablar_async_original = hablar_async
def hablar_async(texto, *args, **kwargs):
    return _hablar_async_original(traducir_dinamico(texto), *args, **kwargs)

activar_wx(wx)

from motor_ytdlp import (
    actualizar_motor_descarga,
    diagnostico_motor_descarga,
    version_instalada_actual,
    version_mas_reciente_disponible,
    normalizar_canal_motor,
)


# Texto de "novedades" mostrado una vez, en la ventana de actualización completada.
# Para publicar una nueva versión: agregar aquí la versión y la clave del catálogo
# con la lista de cambios visibles para la persona usuaria (ver __whatsnew.*.body__
# en idiomas/es.json), sin detalles técnicos innecesarios.
NOVEDADES_VERSION = {
    "1.8.1": "__whatsnew.1_8_1__body__",
    "1.8.2": "__whatsnew.1_8_2__body__",
    "1.8.3": "__whatsnew.1_8_3__body__",
}


def _etiqueta_canal_motor(canal):
    canal = normalizar_canal_motor(canal)
    etiquetas = {
        "stable": "Estable",
        "nightly": "Nightly",
        "master": "Master / Desarrollo",
    }
    return traducir(etiquetas.get(canal, "Estable"))


def seleccionar_carpeta(cuadro_destino):
    dialogo = wx.DirDialog(None, "Seleccione una carpeta de destino")

    if dialogo.ShowModal() == wx.ID_OK:
        cuadro_destino.SetValue(dialogo.GetPath())

    dialogo.Destroy()


class Ventana(wx.Frame):
    def __init__(self):
        super().__init__(None, title=f"{APP_NOMBRE} v{VERSION}", size=(980, 760))
        self.CreateStatusBar()
        self.SetStatusText("Listo")

        self.descargador = Descargador()
        self.descarga_activa = False
        self.busqueda_activa = False
        self.hilo_descarga = None
        self.tipo_descarga_activa = None
        self._cancelar_item_cola = False
        self._detener_cola_solicitada = False
        self._pausa_autenticacion_cola = False
        self.ultimo_anuncio = -1
        self.ultimo_estado_anunciado = None
        self.info_actual = None
        self.resultados_busqueda = []
        self.resultados_colecciones = []
        self.videos_coleccion = []
        self.videos_marcados = set()
        self.coleccion_actual = None
        self.configuracion = cargar_configuracion()
        self._revision_motor_arranque_pendiente = False
        if not self.configuracion.get("idioma_configurado", False):
            self._seleccionar_idioma_inicial()
        establecer_idioma(self.configuracion.get("idioma", "es"))
        self._aplicar_preferencias_descargador()
        self.SetTitle(f"{traducir(APP_NOMBRE)} v{VERSION} - {traducir('Desarrollado por Nicolás Alfaro')}")
        self._ultima_pestana_anunciada = None
        self._ultima_pestana_anunciada_tiempo = 0
        self._metadatos_enriquecidos = set()
        self._metadatos_en_proceso = set()
        self._enriquecimiento_pendiente = None
        self._cerrando = False
        # Si una cola quedó interrumpida por cierre de Windows o del programa,
        # sus elementos vuelven a Pendiente sin comenzar automáticamente.
        restablecer_descargas_interrumpidas()

        self._crear_ids()
        self._crear_menu()
        self._crear_interfaz()
        self._crear_atajos()
        self._cargar_configuracion_en_ui()
        self._actualizar_botones_descarga(False)
        self._actualizar_botones_busqueda(False)
        self.Bind(wx.EVT_CLOSE, self.cerrar_programa)
        self.Bind(wx.EVT_CHAR_HOOK, self._atajos_resultados_busqueda)

        # La bienvenida se anuncia DESPUÉS de que la ventana sea visible.
        # Si se establece el foco o se habla desde __init__, NVDA puede recibir
        # inmediatamente el evento del primer control y cortar el mensaje.
        self._bienvenida_anunciada = False

    def iniciar_experiencia_accesible(self):
        """Anuncia la identidad del programa antes de entregar el foco de trabajo."""
        if self._cerrando or self._bienvenida_anunciada:
            return
        self._bienvenida_anunciada = True
        mensaje = traducir_formato(
            "{app}. Versión {version}. Desarrollado por Nicolás Alfaro. Bienvenido.",
            app=APP_NOMBRE,
            version=VERSION,
        )
        try:
            self.SetStatusText(mensaje)
            self.SetFocus()
        except Exception:
            pass
        self._sonido("inicio", esperar=True)
        hablar_async(mensaje, limpiar=True)

        # No mover el foco mientras NVDA está pronunciando la presentación.
        wx.CallLater(5200, self._finalizar_inicio_accesible)

    def _finalizar_inicio_accesible(self):
        if self._cerrando:
            return
        try:
            self.SetStatusText(traducir("Listo"))
            self.campo_url.SetFocus()
        except Exception:
            pass

        # Los avisos posteriores comienzan cuando la bienvenida ya terminó.
        wx.CallLater(1000, self._notificar_resultado_actualizacion_arranque)
        wx.CallLater(3000, self._programar_revision_actualizaciones)

    def _notificar_resultado_actualizacion_arranque(self):
        try:
            argumentos = list(sys.argv or [])
            if "--actualizado" in argumentos:
                indice = argumentos.index("--actualizado")
                version = VERSION
                if indice + 1 < len(argumentos):
                    version = argumentos[indice + 1]
                # Seguridad: si se abrió una versión anterior a la que se intentó instalar,
                # la actualización no se aplicó realmente. No mostrar éxito falso.
                if es_version_mayor(version, VERSION):
                    self._mostrar_error_detallado(
                        "No se pudo aplicar la actualización",
                        traducir_formato(
                            "La actualización se descargó, pero el programa volvió a abrir una versión anterior. Esto significa que no se pudieron reemplazar todos los archivos automáticamente.\n\nVersión esperada: {esperada}.\nVersión abierta: {abierta}.",
                            esperada=version,
                            abierta=VERSION,
                        ),
                        "Error aplicando actualización",
                    )
                else:
                    mensaje = traducir_formato(
                        "Descargador de Música Accesible se actualizó correctamente.\n\nAhora está usando la versión {version}.",
                        version=VERSION,
                    )
                    clave_novedades = NOVEDADES_VERSION.get(VERSION)
                    if clave_novedades:
                        texto_novedades = traducir_clave(clave_novedades, default="")
                        if texto_novedades:
                            mensaje += "\n\n" + traducir("Novedades de esta versión:") + "\n" + texto_novedades
                    self._mostrar_mensaje_accesible(
                        "Actualización completada",
                        mensaje,
                        wx.ICON_INFORMATION,
                        "Actualización completada",
                        False,
                    )
            elif "--actualizacion-error" in argumentos:
                self._mostrar_error_detallado(
                    "No se pudo aplicar la actualización",
                    "No se pudo aplicar la actualización automáticamente. Puede descargar la nueva versión manualmente desde la página oficial.",
                    "Error aplicando actualización",
                )
        except Exception:
            pass

    def _aplicar_preferencias_descargador(self):
        try:
            self.descargador.configurar_preferencias(
                idioma=self.configuracion.get("idioma", "es"),
                preferir_idioma=self.configuracion.get("youtube_preferir_idioma_programa", True),
                usar_cookies_respaldo=self.configuracion.get("youtube_usar_cookies_respaldo", False),
                navegador_cookies=self.configuracion.get("youtube_navegador_cookies", "auto"),
                metodo_autenticacion=self.configuracion.get("youtube_metodo_autenticacion", "ninguno"),
                archivo_cookies=self.configuracion.get("youtube_archivo_cookies", ""),
            )
        except Exception as exc:
            self.agregar_log(f"No se pudieron aplicar preferencias del motor: {exc}") if hasattr(self, "agregar_log") else None

    def _seleccionar_idioma_inicial(self):
        """Muestra selector de idioma en el primer inicio o tras actualizar desde versiones anteriores."""
        try:
            dialogo = wx.Dialog(None, title="Seleccione idioma / Select language / Choisissez la langue / Seleziona lingua / Escolha o idioma / Выберите язык", size=(520, 300))
            panel = wx.Panel(dialogo)
            sizer = wx.BoxSizer(wx.VERTICAL)
            texto = wx.StaticText(
                panel,
                label=(
                    "Seleccione el idioma del programa.\n"
                    "Select the program language.\n"
                    "Choisissez la langue du programme.\n"
                    "Seleziona la lingua del programma.\n"
                    "Escolha o idioma do programa.\n"
                    "Выберите язык программы."
                ),
            )
            sizer.Add(texto, 0, wx.EXPAND | wx.ALL, 10)
            codigos = list(LANGUAGES.keys())
            nombres = [LANGUAGES[c] for c in codigos]
            combo = wx.Choice(panel, choices=nombres)
            idioma_actual_config = self.configuracion.get("idioma", "es")
            seleccion = codigos.index(idioma_actual_config) if idioma_actual_config in codigos else 0
            combo.SetSelection(seleccion)
            combo.SetName("Seleccione idioma")
            sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            fila = wx.BoxSizer(wx.HORIZONTAL)
            btn_aceptar = wx.Button(panel, wx.ID_OK, label="Aceptar")
            btn_cancelar = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
            fila.Add(btn_aceptar, 0, wx.ALL, 5)
            fila.Add(btn_cancelar, 0, wx.ALL, 5)
            sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
            panel.SetSizer(sizer)
            dialogo.SetAffirmativeId(wx.ID_OK)
            dialogo.SetEscapeId(wx.ID_CANCEL)
            combo.SetFocus()
            if dialogo.ShowModal() == wx.ID_OK:
                sel = combo.GetSelection()
                if 0 <= sel < len(codigos):
                    self.configuracion["idioma"] = codigos[sel]
            self.configuracion["idioma_configurado"] = True
            guardar_configuracion(
                self.configuracion.get("carpeta", ""),
                self.configuracion.get("formato", "MP3"),
                self.configuracion.get("calidad", "320 kbps"),
                opciones=self.configuracion,
            )
            dialogo.Destroy()
        except Exception:
            self.configuracion["idioma"] = self.configuracion.get("idioma", "es") or "es"
            self.configuracion["idioma_configurado"] = True

    def _crear_ids(self):
        self.id_foco_url = wx.NewIdRef()
        self.id_seleccionar_carpeta = wx.NewIdRef()
        self.id_obtener_info = wx.NewIdRef()
        self.id_descargar = wx.NewIdRef()
        self.id_cancelar = wx.NewIdRef()
        self.id_historial = wx.NewIdRef()
        self.id_abrir_historial = wx.NewIdRef()
        self.id_limpiar_historial = wx.NewIdRef()
        self.id_salir = wx.NewIdRef()
        self.id_foco_busqueda = wx.NewIdRef()
        self.id_buscar = wx.NewIdRef()
        self.id_accion_resultado = wx.NewIdRef()
        self.id_reproducir = wx.NewIdRef()
        self.id_descargar_enfocado = wx.NewIdRef()
        self.id_descargar_marcados = wx.NewIdRef()
        self.id_info_enfocado = wx.NewIdRef()
        self.id_copiar_url_enfocado = wx.NewIdRef()
        self.id_limpiar_busqueda_actual = wx.NewIdRef()
        self.id_favorito_enfocado = wx.NewIdRef()
        self.id_cola_enfocado = wx.NewIdRef()
        self.id_cola_marcados = wx.NewIdRef()
        self.id_favoritos = wx.NewIdRef()
        self.id_cola_descargas = wx.NewIdRef()
        self.id_pestana_1 = wx.NewIdRef()
        self.id_pestana_2 = wx.NewIdRef()
        self.id_pestana_3 = wx.NewIdRef()
        self.id_atajos_teclado = wx.NewIdRef()
        self.id_manual_usuario = wx.NewIdRef()
        self.id_novedades_version = wx.NewIdRef()
        self.id_opciones = wx.NewIdRef()
        self.id_buscar_actualizaciones_app = wx.NewIdRef()
        self.id_abrir_con = wx.NewIdRef()
        self.ids_idioma = {codigo: wx.NewIdRef() for codigo in LANGUAGES}

    def _crear_menu(self):
        barra_menu = wx.MenuBar()

        menu_archivo = wx.Menu()
        self.menu_abrir_carpeta = menu_archivo.Append(wx.ID_ANY, "Abrir carpeta de descargas")
        self.menu_abrir_logs = menu_archivo.Append(wx.ID_ANY, "Abrir carpeta de logs")
        self.menu_historial = menu_archivo.Append(self.id_historial, "Ver historial\tCtrl+H")
        self.menu_abrir_historial = menu_archivo.Append(self.id_abrir_historial, "Abrir carpeta de historial")
        self.menu_limpiar_historial = menu_archivo.Append(self.id_limpiar_historial, "Limpiar historial")
        menu_archivo.AppendSeparator()
        self.menu_salir = menu_archivo.Append(self.id_salir, "Salir\tCtrl+Q")

        menu_acciones = wx.Menu()
        self.menu_foco_url = menu_acciones.Append(self.id_foco_url, "Ir al campo URL\tCtrl+L")
        self.menu_seleccionar_carpeta = menu_acciones.Append(
            self.id_seleccionar_carpeta,
            "Seleccionar carpeta\tCtrl+O",
        )
        self.menu_obtener_info = menu_acciones.Append(self.id_obtener_info, "Información\tCtrl+I")
        self.menu_descargar = menu_acciones.Append(self.id_descargar, "Descargar elemento enfocado\tAlt+D")
        self.menu_info_enfocado = menu_acciones.Append(self.id_info_enfocado, "Información del elemento enfocado\tAlt+I")
        self.menu_copiar_url_enfocado = menu_acciones.Append(self.id_copiar_url_enfocado, "Copiar URL del elemento enfocado\tAlt+C")
        self.menu_favorito_enfocado = menu_acciones.Append(self.id_favorito_enfocado, "Agregar o quitar de favoritos\tAlt+F")
        self.menu_cola_enfocado = menu_acciones.Append(self.id_cola_enfocado, "Agregar a la cola de descargas\tAlt+Q")
        self.menu_limpiar_busqueda_actual = menu_acciones.Append(self.id_limpiar_busqueda_actual, "Limpiar cuadro de búsqueda\tAlt+L")
        self.menu_descargar_marcados = menu_acciones.Append(self.id_descargar_marcados, "Descargar videos marcados\tCtrl+Shift+D")
        self.menu_cola_marcados = menu_acciones.Append(self.id_cola_marcados, "Agregar videos marcados a la cola\tCtrl+Shift+Q")
        self.menu_cancelar = menu_acciones.Append(self.id_cancelar, "Cancelar descarga\tCtrl+K")

        menu_buscar = wx.Menu()
        self.menu_foco_busqueda = menu_buscar.Append(self.id_foco_busqueda, "Ir a búsqueda\tCtrl+B")
        self.menu_buscar = menu_buscar.Append(self.id_buscar, "Buscar en YouTube\tCtrl+Enter")
        self.menu_accion_resultado = menu_buscar.Append(
            self.id_accion_resultado,
            "Acción del resultado seleccionado\tEnter",
        )
        self.menu_reproducir = menu_buscar.Append(self.id_reproducir, "Reproducir elemento enfocado\tAlt+R")

        self.menu_herramientas = menu_herramientas = wx.Menu()
        self.menu_favoritos = menu_herramientas.Append(self.id_favoritos, "Favoritos")
        self.menu_cola_descargas = menu_herramientas.Append(self.id_cola_descargas, "Cola de descargas")
        menu_herramientas.AppendSeparator()
        self.menu_buscar_actualizaciones_app = menu_herramientas.Append(
            self.id_buscar_actualizaciones_app,
            "Buscar actualizaciones del programa",
        )
        menu_herramientas.AppendSeparator()
        self.menu_actualizar_ytdlp = menu_herramientas.Append(wx.ID_ANY, "Actualizar librería de descarga")
        self.menu_version_ytdlp = menu_herramientas.Append(wx.ID_ANY, "Ver versión de la librería de descarga")
        menu_herramientas.AppendSeparator()
        self.menu_idioma = wx.Menu()
        self.items_idioma = {}
        idioma_guardado = self.configuracion.get("idioma", idioma_actual())
        for codigo, nombre in LANGUAGES.items():
            item = self.menu_idioma.AppendRadioItem(self.ids_idioma[codigo], nombre)
            self.items_idioma[codigo] = item
            if codigo == idioma_guardado:
                item.Check(True)
        menu_herramientas.AppendSubMenu(self.menu_idioma, "Idioma")
        self.menu_opciones = menu_herramientas.Append(self.id_opciones, "Opciones")
        menu_herramientas.AppendSeparator()
        self.menu_abrir_con = menu_herramientas.Append(
            self.id_abrir_con,
            self._texto_menu_abrir_con(),
        )

        menu_ayuda = wx.Menu()
        self.menu_manual_usuario = menu_ayuda.Append(self.id_manual_usuario, "Manual de usuario")
        self.menu_atajos_teclado = menu_ayuda.Append(self.id_atajos_teclado, "Atajos de teclado")
        self.menu_novedades_version = menu_ayuda.Append(self.id_novedades_version, "Novedades de esta versión")
        menu_ayuda.AppendSeparator()
        self.menu_acerca = menu_ayuda.Append(wx.ID_ANY, "Acerca de...")
        self.menu_contacto = menu_ayuda.Append(wx.ID_ANY, "Contacto")

        barra_menu.Append(menu_archivo, "&Archivo")
        barra_menu.Append(menu_acciones, "&Acciones")
        barra_menu.Append(menu_buscar, "&Buscar")
        barra_menu.Append(menu_herramientas, "&Herramientas")
        barra_menu.Append(menu_ayuda, "A&yuda")

        self.SetMenuBar(barra_menu)

        self.Bind(wx.EVT_MENU, self.abrir_carpeta_descargas, self.menu_abrir_carpeta)
        self.Bind(wx.EVT_MENU, self.abrir_carpeta_logs, self.menu_abrir_logs)
        self.Bind(wx.EVT_MENU, self.mostrar_historial, self.menu_historial)
        self.Bind(wx.EVT_MENU, self._abrir_archivo_historial, self.menu_abrir_historial)
        self.Bind(wx.EVT_MENU, self._limpiar_historial, self.menu_limpiar_historial)
        self.Bind(wx.EVT_MENU, self.salir_programa, self.menu_salir)

        self.Bind(wx.EVT_MENU, self.enfocar_url, self.menu_foco_url)
        self.Bind(wx.EVT_MENU, self.examinar_carpeta, self.menu_seleccionar_carpeta)
        self.Bind(wx.EVT_MENU, self.obtener_informacion, self.menu_obtener_info)
        self.Bind(wx.EVT_MENU, self.descargar_enfocado_actual, self.menu_descargar)
        self.Bind(wx.EVT_MENU, self.informacion_enfocada_actual, self.menu_info_enfocado)
        self.Bind(wx.EVT_MENU, self.copiar_url_enfocada_actual, self.menu_copiar_url_enfocado)
        self.Bind(wx.EVT_MENU, self.alternar_favorito_enfocado, self.menu_favorito_enfocado)
        self.Bind(wx.EVT_MENU, self.agregar_cola_enfocado, self.menu_cola_enfocado)
        self.Bind(wx.EVT_MENU, self.limpiar_busqueda_actual, self.menu_limpiar_busqueda_actual)
        self.Bind(wx.EVT_MENU, self.descargar_marcados_actual, self.menu_descargar_marcados)
        self.Bind(wx.EVT_MENU, self.agregar_marcados_cola, self.menu_cola_marcados)
        self.Bind(wx.EVT_MENU, self.cancelar_descarga, self.menu_cancelar)

        self.Bind(wx.EVT_MENU, self.enfocar_busqueda, self.menu_foco_busqueda)
        self.Bind(wx.EVT_MENU, self.iniciar_busqueda, self.menu_buscar)
        self.Bind(wx.EVT_MENU, self.acciones_resultado_enter, self.menu_accion_resultado)
        self.Bind(wx.EVT_MENU, self.reproducir_actual, self.menu_reproducir)
        self.Bind(wx.EVT_MENU, self.ir_pestana_1, id=self.id_pestana_1)
        self.Bind(wx.EVT_MENU, self.ir_pestana_2, id=self.id_pestana_2)
        self.Bind(wx.EVT_MENU, self.ir_pestana_3, id=self.id_pestana_3)

        self.Bind(wx.EVT_MENU, self.mostrar_favoritos, self.menu_favoritos)
        self.Bind(wx.EVT_MENU, self.mostrar_cola_descargas, self.menu_cola_descargas)
        self.Bind(wx.EVT_MENU, self.buscar_actualizaciones_programa, self.menu_buscar_actualizaciones_app)
        self.Bind(wx.EVT_MENU, self.actualizar_ytdlp, self.menu_actualizar_ytdlp)
        self.Bind(wx.EVT_MENU, self.ver_version_ytdlp, self.menu_version_ytdlp)
        self.Bind(wx.EVT_MENU, self.mostrar_opciones, self.menu_opciones)
        self.Bind(wx.EVT_MENU, self.alternar_abrir_con_windows, self.menu_abrir_con)
        self.Bind(wx.EVT_MENU_OPEN, self._al_abrir_menu)
        for codigo, ident in self.ids_idioma.items():
            self.Bind(wx.EVT_MENU, lambda evento, c=codigo: self.cambiar_idioma(c), id=ident)

        self.Bind(wx.EVT_MENU, self.abrir_manual_usuario, self.menu_manual_usuario)
        self.Bind(wx.EVT_MENU, self.mostrar_atajos_teclado, self.menu_atajos_teclado)
        self.Bind(wx.EVT_MENU, self.mostrar_novedades_version, self.menu_novedades_version)
        self.Bind(wx.EVT_MENU, self.mostrar_acerca, self.menu_acerca)
        self.Bind(wx.EVT_MENU, self.mostrar_contacto, self.menu_contacto)

    def _crear_interfaz(self):
        self.notebook = wx.Notebook(self)
        self.panel_descarga = wx.Panel(self.notebook)
        self.panel_busqueda = wx.Panel(self.notebook)
        self.panel_colecciones = wx.Panel(self.notebook)

        self.notebook.AddPage(self.panel_descarga, "Descargar por URL")
        self.notebook.AddPage(self.panel_busqueda, "Buscar en YouTube")
        self.notebook.AddPage(self.panel_colecciones, "Canales y listas")

        self._crear_pestana_descarga(self.panel_descarga)
        self._crear_pestana_busqueda(self.panel_busqueda)
        self._crear_pestana_colecciones(self.panel_colecciones)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._al_cambiar_pestana)

    def _crear_pestana_descarga(self, panel):
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label="Pegue aquí la URL a descargar:"), 0, wx.ALL, 5)
        self.campo_url = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.campo_url.SetName("Pegue aquí la URL a descargar. URL. Pestaña Alt más 1")
        self.campo_url.Bind(wx.EVT_TEXT_ENTER, self._accion_url_enter)
        self.campo_url.Bind(wx.EVT_KEY_DOWN, self._tecla_campo_url)
        self.campo_url.Bind(wx.EVT_CHAR_HOOK, self._tecla_campo_url_hook)
        sizer.Add(self.campo_url, 0, wx.EXPAND | wx.ALL, 5)

        fila_opciones = wx.BoxSizer(wx.HORIZONTAL)

        fila_formato = wx.BoxSizer(wx.VERTICAL)
        fila_formato.Add(wx.StaticText(panel, label="Formato:"), 0, wx.ALL, 5)
        self.formato = wx.Choice(panel, choices=FORMATOS_DISPONIBLES)
        self.formato.SetName("Formato de descarga")
        fila_formato.Add(self.formato, 0, wx.EXPAND | wx.ALL, 5)

        fila_calidad = wx.BoxSizer(wx.VERTICAL)
        self.etiqueta_calidad = wx.StaticText(panel, label="Calidad:")
        fila_calidad.Add(self.etiqueta_calidad, 0, wx.ALL, 5)
        self.calidad = wx.Choice(panel, choices=CALIDADES_DISPONIBLES)
        self.calidad.SetName("Calidad de audio")
        fila_calidad.Add(self.calidad, 0, wx.EXPAND | wx.ALL, 5)
        self.formato.Bind(wx.EVT_CHOICE, self._al_cambiar_formato)

        fila_opciones.Add(fila_formato, 1, wx.EXPAND)
        fila_opciones.Add(fila_calidad, 1, wx.EXPAND)
        sizer.Add(fila_opciones, 0, wx.EXPAND)

        sizer.Add(wx.StaticText(panel, label="Carpeta destino:"), 0, wx.ALL, 5)
        fila_carpeta = wx.BoxSizer(wx.HORIZONTAL)
        self.carpeta = wx.TextCtrl(panel)
        self.carpeta.SetName("Carpeta destino")
        fila_carpeta.Add(self.carpeta, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_examinar = wx.Button(panel, label="Examinar")
        self.btn_examinar.SetName("Examinar carpeta destino")
        self.btn_examinar.Bind(wx.EVT_BUTTON, self.examinar_carpeta)
        fila_carpeta.Add(self.btn_examinar, 0, wx.ALL, 5)
        sizer.Add(fila_carpeta, 0, wx.EXPAND)

        fila_botones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_info = wx.Button(panel, label="Información")
        self.btn_info.SetName("Obtener información del video")
        self.btn_info.Bind(wx.EVT_BUTTON, self.obtener_informacion)
        fila_botones.Add(self.btn_info, 0, wx.ALL, 5)

        self.btn_descargar = wx.Button(panel, label="Descargar")
        self.btn_descargar.SetName("Descargar video o audio")
        self.btn_descargar.Bind(wx.EVT_BUTTON, self.iniciar_descarga)
        fila_botones.Add(self.btn_descargar, 0, wx.ALL, 5)

        self.btn_cancelar = wx.Button(panel, label="Cancelar")
        self.btn_cancelar.SetName("Cancelar descarga")
        self.btn_cancelar.Bind(wx.EVT_BUTTON, self.cancelar_descarga)
        fila_botones.Add(self.btn_cancelar, 0, wx.ALL, 5)

        sizer.Add(fila_botones, 0, wx.ALL, 0)

        sizer.Add(wx.StaticText(panel, label="Barra de progreso:"), 0, wx.ALL, 5)
        self.gauge = wx.Gauge(panel, range=100)
        sizer.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 5)

        sizer.Add(wx.StaticText(panel, label="Progreso detallado:"), 0, wx.ALL, 5)
        self.progreso = wx.TextCtrl(panel, value="0%", style=wx.TE_READONLY)
        self.progreso.SetName("Progreso detallado de la descarga")
        sizer.Add(self.progreso, 0, wx.EXPAND | wx.ALL, 5)

        sizer.Add(wx.StaticText(panel, label="Estado:"), 0, wx.ALL, 5)
        self.estado = wx.TextCtrl(panel, value="Listo", style=wx.TE_READONLY)
        self.estado.SetName("Estado del programa")
        sizer.Add(self.estado, 0, wx.EXPAND | wx.ALL, 5)

        # La interfaz queda limpia: los mensajes se guardan en archivo de log y
        # se anuncian por NVDA/voz accesible cuando corresponda.
        self.log = None

        panel.SetSizer(sizer)

    def _crear_pestana_busqueda(self, panel):
        self.sizer_busqueda = wx.BoxSizer(wx.VERTICAL)

        self.sizer_busqueda.Add(wx.StaticText(panel, label="Buscar en YouTube:"), 0, wx.ALL, 5)

        self.campo_busqueda = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER | wx.WANTS_CHARS)
        self.campo_busqueda.SetName("Buscar en YouTube. Pestaña Alt más 2. Alt más L limpia el cuadro de búsqueda")
        self.campo_busqueda.Bind(wx.EVT_TEXT_ENTER, self.iniciar_busqueda)
        self.campo_busqueda.Bind(wx.EVT_KEY_DOWN, self._tecla_campo_busqueda)
        self.campo_busqueda.Bind(wx.EVT_CHAR, self._tecla_campo_busqueda)
        self.campo_busqueda.Bind(wx.EVT_CHAR_HOOK, self._tecla_campo_busqueda_hook)
        self.sizer_busqueda.Add(self.campo_busqueda, 0, wx.EXPAND | wx.ALL, 5)

        ayuda = wx.StaticText(
            panel,
            label="Escriba una búsqueda y presione Enter. La cantidad de resultados se configura en Herramientas, Opciones. Alt+L limpia el cuadro de búsqueda. En resultados: Alt+D descarga, Alt+R reproduce, Alt+I información, Alt+C copia URL.",
        )
        self.sizer_busqueda.Add(ayuda, 0, wx.EXPAND | wx.ALL, 5)

        self.estado_busqueda = wx.StaticText(panel, label="Estado: Listo")
        self.sizer_busqueda.Add(self.estado_busqueda, 0, wx.EXPAND | wx.ALL, 5)

        self.panel_resultados_busqueda = wx.Panel(panel)
        sizer_resultados = wx.BoxSizer(wx.VERTICAL)

        self.lista_resultados = wx.ListCtrl(
            self.panel_resultados_busqueda,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
        )
        self.lista_resultados.SetName("Resultados de búsqueda de YouTube. Enter abre acciones. Alt más D descarga. Alt más R reproduce. Alt más F agrega o quita de favoritos. Alt más Q agrega a la cola")
        self.lista_resultados.InsertColumn(0, "", width=45)
        self.lista_resultados.InsertColumn(1, "Título", width=380)
        self.lista_resultados.InsertColumn(2, "Canal", width=190)
        self.lista_resultados.InsertColumn(3, "Publicado", width=120)
        self.lista_resultados.InsertColumn(4, "Visualizaciones", width=125)
        self.lista_resultados.InsertColumn(5, "Duración", width=95)
        self.lista_resultados.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.acciones_resultado_enter)
        self.lista_resultados.Bind(wx.EVT_LIST_ITEM_FOCUSED, self._resultado_busqueda_enfocado)
        sizer_resultados.Add(self.lista_resultados, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_limpiar_busqueda = wx.Button(self.panel_resultados_busqueda, label="Limpiar búsqueda Alt+L")
        self.btn_limpiar_busqueda.SetName("Limpiar búsqueda Alt más L botón")
        self.btn_limpiar_busqueda.Bind(wx.EVT_BUTTON, self.limpiar_busqueda)
        sizer_resultados.Add(self.btn_limpiar_busqueda, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.panel_resultados_busqueda.SetSizer(sizer_resultados)
        self.sizer_busqueda.Add(self.panel_resultados_busqueda, 1, wx.EXPAND | wx.ALL, 0)
        self.lista_resultados.Disable()
        self.btn_limpiar_busqueda.Disable()
        self.panel_resultados_busqueda.Hide()

        panel.SetSizer(self.sizer_busqueda)

    def _crear_pestana_colecciones(self, panel):
        self.sizer_colecciones = wx.BoxSizer(wx.VERTICAL)

        self.sizer_colecciones.Add(wx.StaticText(panel, label="Buscar canal o lista de reproducción:"), 0, wx.ALL, 5)

        self.campo_busqueda_coleccion = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER | wx.WANTS_CHARS)
        self.campo_busqueda_coleccion.SetName("Buscar canal o lista de reproducción. Pestaña Alt más 3. Alt más L limpia el cuadro de búsqueda")
        self.campo_busqueda_coleccion.Bind(wx.EVT_TEXT_ENTER, self.iniciar_busqueda_coleccion)
        self.campo_busqueda_coleccion.Bind(wx.EVT_KEY_DOWN, self._tecla_campo_busqueda_coleccion)
        self.campo_busqueda_coleccion.Bind(wx.EVT_CHAR_HOOK, self._tecla_campo_busqueda_coleccion)
        self.sizer_colecciones.Add(self.campo_busqueda_coleccion, 0, wx.EXPAND | wx.ALL, 5)

        ayuda = wx.StaticText(
            panel,
            label=(
                "Escriba la búsqueda y presione Enter. Luego elija si desea buscar canales o listas. "
                "En la lista de videos, Espacio marca o desmarca. Alt+Q agrega los marcados a la cola; si no hay marcados, agrega el video enfocado. Alt+D descarga el video enfocado; Alt+R lo reproduce."
            ),
        )
        self.sizer_colecciones.Add(ayuda, 0, wx.EXPAND | wx.ALL, 5)

        self.estado_colecciones = wx.StaticText(panel, label="Estado: Listo")
        self.sizer_colecciones.Add(self.estado_colecciones, 0, wx.EXPAND | wx.ALL, 5)

        self.panel_resultados_colecciones = wx.Panel(panel)
        sizer_resultados = wx.BoxSizer(wx.VERTICAL)

        self.lista_colecciones = wx.ListCtrl(
            self.panel_resultados_colecciones,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
        )
        self.lista_colecciones.SetName("Resultados de canales o listas de reproducción. Enter abre acciones")
        self.lista_colecciones.InsertColumn(0, "#", width=45)
        self.lista_colecciones.InsertColumn(1, "Tipo", width=150)
        self.lista_colecciones.InsertColumn(2, "Nombre", width=350)
        self.lista_colecciones.InsertColumn(3, "Autor", width=220)
        self.lista_colecciones.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.acciones_coleccion_enter)
        sizer_resultados.Add(self.lista_colecciones, 1, wx.EXPAND | wx.ALL, 5)

        self.btn_limpiar_colecciones = wx.Button(self.panel_resultados_colecciones, label="Limpiar búsqueda Alt+L")
        self.btn_limpiar_colecciones.SetName("Limpiar búsqueda Alt más L botón")
        self.btn_limpiar_colecciones.Bind(wx.EVT_BUTTON, self.limpiar_busqueda_coleccion)
        sizer_resultados.Add(self.btn_limpiar_colecciones, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

        self.panel_resultados_colecciones.SetSizer(sizer_resultados)
        self.sizer_colecciones.Add(self.panel_resultados_colecciones, 1, wx.EXPAND | wx.ALL, 0)
        self.lista_colecciones.Disable()
        self.btn_limpiar_colecciones.Disable()
        self.panel_resultados_colecciones.Hide()

        self.panel_videos_coleccion = wx.Panel(panel)
        sizer_videos = wx.BoxSizer(wx.VERTICAL)
        self.texto_videos_coleccion = wx.StaticText(self.panel_videos_coleccion, label="Videos de la colección:")
        sizer_videos.Add(self.texto_videos_coleccion, 0, wx.EXPAND | wx.ALL, 5)

        self.lista_videos_coleccion = wx.ListCtrl(
            self.panel_videos_coleccion,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
        )
        self.lista_videos_coleccion.SetName("Videos de la colección. Espacio marca o desmarca. Enter abre acciones del video enfocado. Alt más Q agrega los marcados a la cola; si no hay marcados, agrega el enfocado. Alt más D descarga. Alt más R reproduce. Alt más F agrega o quita de favoritos")
        self.lista_videos_coleccion.InsertColumn(0, "Marcado", width=85)
        self.lista_videos_coleccion.InsertColumn(1, "#", width=45)
        self.lista_videos_coleccion.InsertColumn(2, "Título", width=410)
        self.lista_videos_coleccion.InsertColumn(3, "Canal", width=210)
        self.lista_videos_coleccion.InsertColumn(4, "Duración", width=90)
        self.lista_videos_coleccion.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.acciones_video_coleccion_enter)
        sizer_videos.Add(self.lista_videos_coleccion, 1, wx.EXPAND | wx.ALL, 5)

        fila_videos = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_descargar_marcados = wx.Button(self.panel_videos_coleccion, label="Agregar videos marcados a la cola")
        self.btn_descargar_marcados.SetName("Agregar videos marcados a la cola de descargas")
        self.btn_descargar_marcados.Bind(wx.EVT_BUTTON, self.agregar_marcados_cola)
        fila_videos.Add(self.btn_descargar_marcados, 0, wx.ALL, 5)

        self.btn_volver_colecciones = wx.Button(self.panel_videos_coleccion, label="Volver a resultados")
        self.btn_volver_colecciones.SetName("Volver a resultados de canales o listas")
        self.btn_volver_colecciones.Bind(wx.EVT_BUTTON, self.volver_resultados_colecciones)
        fila_videos.Add(self.btn_volver_colecciones, 0, wx.ALL, 5)
        sizer_videos.Add(fila_videos, 0, wx.ALIGN_RIGHT | wx.ALL, 0)

        self.panel_videos_coleccion.SetSizer(sizer_videos)
        self.sizer_colecciones.Add(self.panel_videos_coleccion, 1, wx.EXPAND | wx.ALL, 0)
        self.lista_videos_coleccion.Disable()
        self.btn_descargar_marcados.Disable()
        self.panel_videos_coleccion.Hide()

        panel.SetSizer(self.sizer_colecciones)

    def _crear_atajos(self):
        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [
                    (wx.ACCEL_CTRL, ord("L"), self.id_foco_url),
                    (wx.ACCEL_CTRL, ord("O"), self.id_seleccionar_carpeta),
                    (wx.ACCEL_CTRL, ord("I"), self.id_obtener_info),
                    (wx.ACCEL_CTRL, ord("K"), self.id_cancelar),
                    (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.id_cancelar),
                    (wx.ACCEL_CTRL, ord("H"), self.id_historial),
                    (wx.ACCEL_CTRL, ord("Q"), self.id_salir),
                    (wx.ACCEL_CTRL, ord("B"), self.id_foco_busqueda),
                    (wx.ACCEL_CTRL, wx.WXK_RETURN, self.id_buscar),
                    (wx.ACCEL_ALT, ord("R"), self.id_reproducir),
                    (wx.ACCEL_ALT, ord("D"), self.id_descargar),
                    (wx.ACCEL_ALT, ord("I"), self.id_info_enfocado),
                    (wx.ACCEL_ALT, ord("C"), self.id_copiar_url_enfocado),
                    (wx.ACCEL_ALT, ord("F"), self.id_favorito_enfocado),
                    (wx.ACCEL_ALT, ord("Q"), self.id_cola_enfocado),
                    (wx.ACCEL_ALT, ord("L"), self.id_limpiar_busqueda_actual),
                    (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("D"), self.id_descargar_marcados),
                    (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("Q"), self.id_cola_marcados),
                    (wx.ACCEL_ALT, ord("1"), self.id_pestana_1),
                    (wx.ACCEL_ALT, ord("2"), self.id_pestana_2),
                    (wx.ACCEL_ALT, ord("3"), self.id_pestana_3),
                ]
            )
        )

    def _calidad_seleccionada(self):
        opciones = getattr(self, "_opciones_calidad_actuales", []) or []
        indice = self.calidad.GetSelection()
        if 0 <= indice < len(opciones):
            return opciones[indice]
        return opciones[-1] if opciones else "320 kbps"

    def _actualizar_opciones_calidad(self, formato=None, valor_preferido=None):
        formato = formato or self.formato.GetStringSelection() or "MP3"
        opciones = opciones_calidad_para_formato(formato)
        self._opciones_calidad_actuales = list(opciones)
        self.calidad.Clear()
        self.calidad.AppendItems([traducir(opcion) for opcion in opciones])

        if formato == "MP4":
            self.etiqueta_calidad.SetLabel(traducir("Resolución de video:"))
            self.calidad.SetName(traducir("Resolución de video"))
        else:
            self.etiqueta_calidad.SetLabel(traducir("Calidad:"))
            self.calidad.SetName(traducir("Calidad de audio"))

        if valor_preferido in opciones:
            seleccion = opciones.index(valor_preferido)
        elif formato in ("WAV", "FLAC", "MP4"):
            seleccion = 0
        else:
            seleccion = len(opciones) - 1
        self.calidad.SetSelection(max(0, seleccion))

    def _al_cambiar_formato(self, evento=None):
        formato = self.formato.GetStringSelection() or "MP3"
        anterior = self._calidad_seleccionada()
        self._actualizar_opciones_calidad(formato, anterior)
        try:
            self.configuracion["formato"] = formato
            self.configuracion["calidad"] = self._calidad_seleccionada()
        except Exception:
            pass
        if evento is not None:
            evento.Skip()

    def _cargar_configuracion_en_ui(self):
        self.carpeta.SetValue(self.configuracion.get("carpeta", ""))

        formato = self.configuracion.get("formato", "MP3")
        calidad = self.configuracion.get("calidad", "320 kbps")

        self.formato.SetSelection(FORMATOS_DISPONIBLES.index(formato) if formato in FORMATOS_DISPONIBLES else 0)
        self._actualizar_opciones_calidad(self.formato.GetStringSelection(), calidad)


    def _datos_pestana(self, indice):
        datos = {
            0: ("URL", "Alt más 1"),
            1: ("Buscar en YouTube", "Alt más 2"),
            2: ("Canales y listas", "Alt más 3"),
        }
        return datos.get(indice, ("Pestaña", ""))

    def _anunciar_pestana(self, indice, limpiar=True):
        nombre, atajo = self._datos_pestana(indice)
        ahora = time.time()
        if self._ultima_pestana_anunciada == indice and ahora - self._ultima_pestana_anunciada_tiempo < 0.6:
            return
        self._ultima_pestana_anunciada = indice
        self._ultima_pestana_anunciada_tiempo = ahora
        mensaje = f"{nombre}. Pestaña {atajo}" if atajo else f"Pestaña {nombre}"
        self.SetStatusText(mensaje)
        hablar_async(mensaje, limpiar=limpiar)

    def _al_cambiar_pestana(self, evento):
        try:
            self._anunciar_pestana(self.notebook.GetSelection(), limpiar=True)
        except Exception:
            pass
        evento.Skip()

    def _ir_a_pestana(self, indice, nombre=None, control=None):
        try:
            self.notebook.SetSelection(indice)
            if control is not None:
                control.SetFocus()
            self._anunciar_pestana(indice, limpiar=True)
        except Exception:
            pass

    def ir_pestana_1(self, evento=None):
        self._ir_a_pestana(0, control=self.campo_url)

    def ir_pestana_2(self, evento=None):
        control = self.lista_resultados if self.lista_resultados.IsEnabled() and self.resultados_busqueda else self.campo_busqueda
        self._ir_a_pestana(1, control=control)

    def ir_pestana_3(self, evento=None):
        if self.lista_videos_coleccion.IsEnabled() and self.videos_coleccion:
            control = self.lista_videos_coleccion
        elif self.lista_colecciones.IsEnabled() and self.resultados_colecciones:
            control = self.lista_colecciones
        else:
            control = self.campo_busqueda_coleccion
        self._ir_a_pestana(2, control=control)

    def _sonido(self, nombre, esperar=False):
        if not self.configuracion.get("sonidos_activados", True):
            return False

        mapa = {
            "inicio": "sonido_inicio",
            "cierre": "sonido_cierre",
            "descarga_completada": "sonido_descarga",
            "error": "sonido_error",
        }

        clave = mapa.get(nombre)
        if clave and not self.configuracion.get(clave, True):
            return False

        return reproducir_sonido(nombre, esperar=esperar)

    def _programar_revision_actualizaciones(self):
        try:
            # Orden de revisión al iniciar:
            # 1) Primero actualizaciones del programa.
            # 2) Luego actualizaciones de la librería de descarga.
            # Así evitamos diálogos simultáneos y el usuario recibe los avisos
            # de forma clara y accesible.
            revisar_programa = (
                not self.configuracion.get("primera_revision_actualizaciones_realizada", False)
                or self._debe_revisar_actualizaciones(
                    "frecuencia_actualizaciones",
                    "ultima_revision_actualizaciones",
                )
            )

            revisar_motor = (
                not self.configuracion.get("primera_revision_actualizaciones_motor_realizada", False)
                or self._debe_revisar_actualizaciones(
                    "frecuencia_actualizaciones_motor",
                    "ultima_revision_actualizaciones_motor",
                )
            )
            self._revision_motor_arranque_pendiente = bool(revisar_motor)

            if revisar_programa:
                hilo = threading.Thread(target=self._revisar_actualizaciones_inicio_hilo, daemon=True)
                hilo.start()
            elif revisar_motor:
                wx.CallLater(1500, self._continuar_revision_motor_post_programa)
        except Exception:
            pass

    def _continuar_revision_motor_post_programa(self):
        try:
            if not getattr(self, "_revision_motor_arranque_pendiente", False):
                return
            self._revision_motor_arranque_pendiente = False
            wx.CallLater(1200, self._iniciar_revision_motor_arranque)
        except Exception:
            pass

    def _iniciar_revision_motor_arranque(self):
        try:
            hilo_motor = threading.Thread(target=self._revisar_motor_inicio_hilo, daemon=True)
            hilo_motor.start()
        except Exception:
            pass

    def _debe_revisar_actualizaciones(self, clave_frecuencia="frecuencia_actualizaciones", clave_ultima="ultima_revision_actualizaciones"):
        frecuencia = self.configuracion.get(clave_frecuencia, "Cada semana")
        if frecuencia == "Nunca":
            return False
        if frecuencia == "Al iniciar":
            return True

        ultima = self.configuracion.get(clave_ultima, "")
        if not ultima:
            return True

        try:
            from datetime import datetime
            fecha_ultima = datetime.strptime(ultima, "%Y-%m-%d")
            dias = (datetime.now() - fecha_ultima).days
        except Exception:
            return True

        if frecuencia == "Cada día":
            return dias >= 1
        if frecuencia == "Cada semana":
            return dias >= 7
        if frecuencia == "Cada mes":
            return dias >= 30

        return False

    def _revisar_actualizaciones_inicio_hilo(self):
        """Revisa actualizaciones del programa principal según la frecuencia elegida."""
        try:
            info = consultar_actualizacion(VERSION)
            self.configuracion["ultima_revision_actualizaciones"] = fecha_iso_hoy()
            self.configuracion["primera_revision_actualizaciones_realizada"] = True
            wx.CallAfter(self.guardar_configuracion)

            if info is None:
                wx.CallAfter(self._continuar_revision_motor_post_programa)
                return

            wx.CallAfter(self._preguntar_descargar_actualizacion_programa, info, True)
        except ActualizadorNoConfigurado:
            wx.CallAfter(self.agregar_log, "Actualizador del programa no configurado para revisión automática.")
            wx.CallAfter(self._continuar_revision_motor_post_programa)
        except Exception as exc:
            wx.CallAfter(self.agregar_log, f"No se pudo revisar actualizaciones del programa al iniciar: {exc}")
            wx.CallAfter(self._continuar_revision_motor_post_programa)

    def _revisar_motor_inicio_hilo(self):
        """Revisa actualizaciones del motor de descarga según la frecuencia elegida."""
        try:
            canal_deseado = normalizar_canal_motor(self.configuracion.get("canal_actualizaciones_motor", "stable"))
            canal_instalado = normalizar_canal_motor(self.configuracion.get("canal_motor_instalado", "stable"))
            version_instalada = version_instalada_actual()
            version_nueva = version_mas_reciente_disponible(canal_deseado)
            if not version_nueva or not version_instalada:
                return

            self.configuracion["ultima_revision_actualizaciones_motor"] = fecha_iso_hoy()
            self.configuracion["primera_revision_actualizaciones_motor_realizada"] = True
            wx.CallAfter(self.guardar_configuracion)

            requiere_cambio_canal = canal_deseado != canal_instalado
            if requiere_cambio_canal or es_version_mayor(version_nueva, version_instalada):
                if self.configuracion.get("actualizar_motor_silenciosamente", False):
                    wx.CallAfter(self.actualizar_ytdlp, None, True)
                else:
                    wx.CallAfter(
                        self._preguntar_actualizar_motor_descarga,
                        version_instalada,
                        version_nueva,
                        canal_instalado,
                        canal_deseado,
                    )
        except Exception as exc:
            wx.CallAfter(self.agregar_log, f"No se pudo revisar actualizaciones de la librería de descarga al iniciar: {exc}")

    def _preguntar_actualizar_motor_descarga(self, version_instalada, version_nueva, canal_instalado="stable", canal_deseado="stable"):
        canal_instalado = normalizar_canal_motor(canal_instalado)
        canal_deseado = normalizar_canal_motor(canal_deseado)
        if canal_instalado != canal_deseado:
            encabezado_canal = traducir_formato(
                "Canal actual: {actual}. Canal seleccionado: {nuevo}.",
                actual=_etiqueta_canal_motor(canal_instalado),
                nuevo=_etiqueta_canal_motor(canal_deseado),
            )
        else:
            encabezado_canal = traducir_formato("Canal: {canal}.", canal=_etiqueta_canal_motor(canal_deseado))
        mensaje = (
            traducir("Se ha encontrado una actualización de la librería de descarga yt-dlp.") + "\n\n"
            + traducir_formato("Versión actual: {version}", version=version_instalada) + "\n"
            + traducir_formato("Nueva versión: {version}", version=version_nueva) + "\n"
            + encabezado_canal + "\n\n"
            + traducir("Se recomienda actualizar el motor para mejorar la búsqueda, reproducción y descarga.") + "\n\n"
            + traducir("¿Desea actualizar la librería de descarga ahora?")
        )
        hablar_async("Actualización de la librería de descarga yt-dlp disponible", limpiar=True)
        respuesta = wx.MessageBox(
            mensaje,
            "Actualización de la librería de descarga disponible",
            wx.YES_NO | wx.ICON_INFORMATION,
            self,
        )
        if respuesta == wx.YES:
            self.actualizar_ytdlp()

    def cambiar_idioma(self, codigo):
        if codigo not in LANGUAGES:
            return
        self.configuracion["idioma"] = codigo
        self.configuracion["idioma_configurado"] = True
        establecer_idioma(codigo)
        self._aplicar_preferencias_descargador()
        self.guardar_configuracion()
        nombre = LANGUAGES.get(codigo, codigo)
        mensaje = traducir("Idioma cambiado. Para aplicar todos los textos completamente, cierre y abra el programa nuevamente.")
        try:
            for c, item in self.items_idioma.items():
                item.Check(c == codigo)
        except Exception:
            pass
        self._mostrar_mensaje_accesible(
            traducir("Idioma cambiado"),
            f"{mensaje}\n\n{nombre}",
            wx.ICON_INFORMATION,
            registrar=False,
        )

    def mostrar_opciones(self, evento=None):
        dialogo = wx.Dialog(self, title="Opciones", size=(680, 720))
        panel = wx.ScrolledWindow(dialogo, style=wx.VSCROLL)
        panel.SetScrollRate(0, 12)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label="Buscar actualizaciones del programa:"), 0, wx.ALL, 8)
        combo_frecuencia = wx.Choice(panel, choices=FRECUENCIAS_ACTUALIZACION)
        frecuencia_actual = self.configuracion.get("frecuencia_actualizaciones", "Cada semana")
        if frecuencia_actual not in FRECUENCIAS_ACTUALIZACION:
            frecuencia_actual = "Cada semana"
        combo_frecuencia.SetSelection(FRECUENCIAS_ACTUALIZACION.index(frecuencia_actual))
        combo_frecuencia.SetName("Frecuencia para buscar actualizaciones del programa")
        sizer.Add(combo_frecuencia, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        sizer.Add(wx.StaticText(panel, label="Buscar actualizaciones de la librería de descarga:"), 0, wx.ALL, 8)
        combo_frecuencia_motor = wx.Choice(panel, choices=FRECUENCIAS_ACTUALIZACION)
        frecuencia_motor_actual = self.configuracion.get("frecuencia_actualizaciones_motor", "Cada semana")
        if frecuencia_motor_actual not in FRECUENCIAS_ACTUALIZACION:
            frecuencia_motor_actual = "Cada semana"
        combo_frecuencia_motor.SetSelection(FRECUENCIAS_ACTUALIZACION.index(frecuencia_motor_actual))
        combo_frecuencia_motor.SetName("Frecuencia para buscar actualizaciones de la librería de descarga")
        sizer.Add(combo_frecuencia_motor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        chk_actualizar_motor_auto = wx.CheckBox(panel, label="Actualizar automáticamente la librería cuando exista una versión nueva")
        chk_actualizar_motor_auto.SetValue(bool(self.configuracion.get("actualizar_motor_silenciosamente", False)))
        chk_actualizar_motor_auto.SetName("Actualizar automáticamente la librería de descarga cuando exista una versión nueva")
        sizer.Add(chk_actualizar_motor_auto, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        sizer.Add(wx.StaticText(panel, label="Canal de actualización del motor de descarga:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        canales_motor_ids = ["stable", "nightly", "master"]
        canales_motor_etiquetas = ["Estable", "Nightly", "Master / Desarrollo"]
        combo_canal_motor = wx.Choice(panel, choices=canales_motor_etiquetas)
        canal_motor_actual = normalizar_canal_motor(self.configuracion.get("canal_actualizaciones_motor", "stable"))
        combo_canal_motor.SetSelection(canales_motor_ids.index(canal_motor_actual))
        combo_canal_motor.SetName("Canal de actualización de la librería de descarga")
        sizer.Add(combo_canal_motor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        caja_busqueda = wx.StaticBox(panel, label="Opciones de búsqueda")
        sizer_busqueda = wx.StaticBoxSizer(caja_busqueda, wx.VERTICAL)
        sizer_busqueda.Add(wx.StaticText(caja_busqueda, label="Cantidad predeterminada de resultados:"), 0, wx.ALL, 4)
        combo_resultados = wx.Choice(caja_busqueda, choices=RESULTADOS_BUSQUEDA_DISPONIBLES)
        resultados_actual = str(self.configuracion.get("busqueda_resultados_predeterminados", "100"))
        if resultados_actual not in RESULTADOS_BUSQUEDA_DISPONIBLES:
            resultados_actual = "100"
        combo_resultados.SetSelection(RESULTADOS_BUSQUEDA_DISPONIBLES.index(resultados_actual))
        combo_resultados.SetName("Cantidad predeterminada de resultados de búsqueda")
        sizer_busqueda.Add(combo_resultados, 0, wx.EXPAND | wx.ALL, 4)
        chk_preguntar_resultados = wx.CheckBox(caja_busqueda, label="Preguntar la cantidad antes de cada búsqueda")
        chk_preguntar_resultados.SetValue(bool(self.configuracion.get("busqueda_preguntar_cantidad", False)))
        chk_preguntar_resultados.SetName("Preguntar cantidad de resultados antes de cada búsqueda")
        sizer_busqueda.Add(chk_preguntar_resultados, 0, wx.ALL, 4)
        sizer.Add(sizer_busqueda, 0, wx.EXPAND | wx.ALL, 8)

        caja_youtube = wx.StaticBox(panel, label="YouTube y autenticación")
        sizer_youtube = wx.StaticBoxSizer(caja_youtube, wx.VERTICAL)
        chk_idioma_youtube = wx.CheckBox(caja_youtube, label="Preferir información de YouTube en el idioma del programa")
        chk_idioma_youtube.SetValue(bool(self.configuracion.get("youtube_preferir_idioma_programa", True)))
        chk_idioma_youtube.SetName("Preferir metadatos de YouTube en el idioma del programa")
        sizer_youtube.Add(chk_idioma_youtube, 0, wx.ALL, 4)

        lbl_metodo_auth = wx.StaticText(caja_youtube, label=traducir("Método de autenticación de YouTube:"))
        sizer_youtube.Add(lbl_metodo_auth, 0, wx.ALL, 4)
        metodos_auth_ids = ["ninguno", "cookies_txt", "navegador"]
        metodos_auth_etiquetas = [
            traducir("Sin autenticación"),
            traducir("Archivo cookies.txt (recomendado)"),
            traducir("Sesión del navegador (alternativo)"),
        ]
        combo_metodo_auth = wx.Choice(caja_youtube, choices=metodos_auth_etiquetas)
        metodo_actual = str(self.configuracion.get("youtube_metodo_autenticacion", "ninguno") or "ninguno").lower()
        if metodo_actual not in metodos_auth_ids:
            metodo_actual = "navegador" if self.configuracion.get("youtube_usar_cookies_respaldo", False) else "ninguno"
        combo_metodo_auth.SetSelection(metodos_auth_ids.index(metodo_actual))
        combo_metodo_auth.SetName(traducir("Método de autenticación de YouTube"))
        sizer_youtube.Add(combo_metodo_auth, 0, wx.EXPAND | wx.ALL, 4)

        # Controles del archivo cookies.txt.
        #
        # Se confirmó con el registro de depuración de NVDA (evento MSAA
        # EVENT_SYSTEM_FOREGROUND sobre el propio diálogo, distinto del foco real
        # del control) que NVDA anuncia una "descripción" del diálogo tomada de
        # una etiqueta de texto suelta, y que eso depende del orden REAL de
        # ventanas de Windows (Z-order), no del orden visual ni del orden lógico
        # de Tab de wx. lbl_metodo_auth antecede a un combo y nunca causa esto;
        # lbl_archivo_cookies antecedía a un botón y sí lo causaba.
        # wx.Window.MoveBeforeInTabOrder()/MoveAfterInTabOrder() NO sirven para
        # esto: solo reordenan la lista lógica de Tab de wx, no las ventanas
        # nativas reales que usa NVDA aquí (ya se probó y no tuvo efecto).
        # La única forma de cambiar el orden real es el orden de CREACIÓN: por
        # eso el botón se crea antes que la etiqueta, dejándola junto al cuadro
        # de texto de la ruta en el orden real de ventanas. El orden visual
        # (de arriba a abajo) se controla aparte, más abajo, con sizer.Add(), y
        # el orden de Tab se sigue fijando con MoveAfterInTabOrder como antes.
        btn_archivo_cookies = wx.Button(caja_youtube, label=traducir("Seleccionar archivo cookies.txt..."))
        btn_archivo_cookies.SetName(traducir("Seleccionar archivo cookies.txt..."))
        lbl_archivo_cookies = wx.StaticText(caja_youtube, label=traducir("Archivo cookies.txt:"))
        sizer_youtube.Add(lbl_archivo_cookies, 0, wx.ALL, 4)
        sizer_youtube.Add(btn_archivo_cookies, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        ruta_cookies_inicial = str(self.configuracion.get("youtube_archivo_cookies", "") or "")

        # Control enfocable para que la ruta forme parte real del recorrido con Tab.
        # Se mantiene protegido contra edición desde la propia aplicación.
        txt_archivo_cookies = wx.TextCtrl(
            caja_youtube,
            value=ruta_cookies_inicial,
            style=wx.BORDER_SIMPLE,
        )
        txt_archivo_cookies.SetName(traducir("Ruta del archivo cookies.txt"))

        estado_ruta_cookies = {"valor": ruta_cookies_inicial, "actualizando": False}

        def establecer_ruta_cookies_en_control(ruta):
            ruta = str(ruta or "")
            estado_ruta_cookies["actualizando"] = True
            estado_ruta_cookies["valor"] = ruta
            try:
                txt_archivo_cookies.ChangeValue(ruta)
                txt_archivo_cookies.SetInsertionPointEnd()
                txt_archivo_cookies.SetToolTip(
                    ruta if ruta else traducir("No hay un archivo cookies.txt seleccionado.")
                )
            finally:
                estado_ruta_cookies["actualizando"] = False

        def bloquear_edicion_ruta_cookies(evento):
            codigo = evento.GetKeyCode()

            # Tab y Shift+Tab: navegación normal del diálogo.
            if codigo == wx.WXK_TAB:
                evento.Skip()
                return

            # Navegación dentro del texto.
            if codigo in {
                wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END,
                wx.WXK_PAGEUP, wx.WXK_PAGEDOWN,
            }:
                evento.Skip()
                return

            # Permitir seleccionar y copiar.
            if evento.ControlDown() and codigo in (ord("C"), ord("A")):
                evento.Skip()
                return

            # El resto se consume: la ruta no se puede modificar.
            return

        def restaurar_ruta_si_se_modifica(evento):
            if not estado_ruta_cookies["actualizando"]:
                valor_correcto = estado_ruta_cookies["valor"]
                if txt_archivo_cookies.GetValue() != valor_correcto:
                    wx.CallAfter(establecer_ruta_cookies_en_control, valor_correcto)
            evento.Skip()

        txt_archivo_cookies.Bind(wx.EVT_CHAR, bloquear_edicion_ruta_cookies)
        txt_archivo_cookies.Bind(wx.EVT_TEXT, restaurar_ruta_si_se_modifica)
        establecer_ruta_cookies_en_control(ruta_cookies_inicial)

        sizer_youtube.Add(txt_archivo_cookies, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        btn_ayuda_cookies = wx.Button(caja_youtube, label=traducir("Cómo obtener cookies.txt"))
        btn_ayuda_cookies.SetName(traducir("Cómo obtener cookies.txt"))
        sizer_youtube.Add(btn_ayuda_cookies, 0, wx.ALL, 4)

        try:
            # Esto fija el orden de Tab (navegación con teclado): botón, ruta,
            # ayuda. Es independiente del orden real de ventanas que se resolvió
            # arriba con el orden de creación.
            txt_archivo_cookies.MoveAfterInTabOrder(btn_archivo_cookies)
            btn_ayuda_cookies.MoveAfterInTabOrder(txt_archivo_cookies)
        except Exception:
            pass

        lbl_navegador = wx.StaticText(caja_youtube, label=traducir("Navegador para la sesión de YouTube:"))
        sizer_youtube.Add(lbl_navegador, 0, wx.ALL, 4)
        navegadores_ids = ["auto", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"]
        navegadores_etiquetas = ["Automático", "Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Brave", "Opera", "Vivaldi", "Chromium"]
        combo_navegador = wx.Choice(caja_youtube, choices=navegadores_etiquetas)
        navegador_actual = str(self.configuracion.get("youtube_navegador_cookies", "auto") or "auto").lower()
        seleccion_navegador = navegadores_ids.index(navegador_actual) if navegador_actual in navegadores_ids else 0
        combo_navegador.SetSelection(seleccion_navegador)
        combo_navegador.SetName(traducir("Navegador con sesión iniciada de Google o YouTube"))
        sizer_youtube.Add(combo_navegador, 0, wx.EXPAND | wx.ALL, 4)

        def actualizar_controles_autenticacion(evento=None):
            indice = combo_metodo_auth.GetSelection()
            metodo = metodos_auth_ids[indice] if 0 <= indice < len(metodos_auth_ids) else "ninguno"
            mostrar_archivo = metodo == "cookies_txt"
            mostrar_navegador = metodo == "navegador"

            for control in (lbl_archivo_cookies, btn_archivo_cookies, txt_archivo_cookies, btn_ayuda_cookies):
                control.Show(mostrar_archivo)
            # No hace falta volver a llamar aquí a establecer_ruta_cookies_en_control():
            # es la única función que modifica estado_ruta_cookies["valor"], así que el
            # texto y el tooltip del control ya reflejan ese valor desde que se creó o
            # desde la última vez que se eligió un archivo. Repetirlo aquí no cambiaba
            # nada realmente, pero sí manipulaba el control de texto (ChangeValue,
            # SetInsertionPointEnd, SetToolTip) justo cuando el diálogo de Opciones se
            # está mostrando por primera vez con Archivo cookies.txt ya guardado, y eso
            # coincidía exactamente con el anuncio incorrecto de NVDA ("Archivo
            # cookies.txt:") reportado al abrir Opciones con un archivo ya cargado,
            # aunque el foco real ya estuviera bien puesto en el primer control.
            for control in (lbl_navegador, combo_navegador):
                control.Show(mostrar_navegador)

            sizer_youtube.Layout()
            panel.Layout()
            panel.FitInside()
            dialogo.Layout()

        def seleccionar_archivo_cookies(evento=None):
            dialogo_archivo = wx.FileDialog(
                dialogo,
                message=traducir("Seleccione el archivo cookies.txt exportado en formato Netscape"),
                wildcard="cookies.txt (*.txt)|*.txt|Todos los archivos (*.*)|*.*",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            )
            ruta_valida = ""
            mensaje_error = ""
            if dialogo_archivo.ShowModal() == wx.ID_OK:
                ruta = dialogo_archivo.GetPath()
                valido, mensaje_validacion = validar_archivo_cookies_netscape(ruta)
                if valido:
                    ruta_valida = ruta
                else:
                    mensaje_error = mensaje_validacion
            dialogo_archivo.Destroy()

            if ruta_valida:
                establecer_ruta_cookies_en_control(ruta_valida)
                combo_metodo_auth.SetSelection(metodos_auth_ids.index("cookies_txt"))
                actualizar_controles_autenticacion()

                # Regresamos el foco al botón de selección. Así, el siguiente Tab
                # lleva de forma predecible al campo que contiene la ruta.
                wx.CallLater(120, btn_archivo_cookies.SetFocus)

                # Indicamos tanto que el archivo es válido como la ruta cargada.
                mensaje_ok = (
                    f"{traducir('Archivo de cookies configurado correctamente.')} "
                    f"{traducir('Ruta del archivo cookies.txt')}: {ruta_valida}"
                )
                wx.CallLater(350, hablar_async, mensaje_ok, limpiar=True)
            elif mensaje_error:
                self._mostrar_mensaje_accesible(
                    traducir("Archivo cookies.txt no válido"), mensaje_error, wx.ICON_INFORMATION, registrar=False
                )

        def mostrar_ayuda_cookies(evento=None):
            ayudas = {
                "es": (
                    "GOOGLE CHROME\n\n"
                    "1. Abra Google Chrome y pulse Ctrl+L.\n"
                    "2. Pegue esta dirección y pulse Enter:\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Busque Añadir a Chrome, actívelo y confirme con Añadir extensión.\n"
                    "4. Abra youtube.com e inicie sesión con la cuenta que utiliza en YouTube.\n"
                    "5. Abra el botón Extensiones de Chrome. Con lector de pantalla puede recorrer la barra de herramientas con Tab hasta encontrar Extensiones.\n"
                    "6. Elija Get cookies.txt LOCALLY.\n"
                    "7. Seleccione Netscape. No utilice JSON.\n"
                    "8. Exporte las cookies y guarde el archivo cookies.txt en una carpeta que recuerde.\n"
                    "9. Vuelva a Descargador de Música Accesible, Herramientas, Opciones, Autenticación de YouTube.\n"
                    "10. Elija Archivo cookies.txt (recomendado).\n"
                    "11. Active Seleccionar archivo cookies.txt y abra el archivo que exportó.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Abra Firefox y pulse Ctrl+L.\n"
                    "2. Pegue esta dirección y pulse Enter:\n"
                    "https://addons.mozilla.org/es-ES/firefox/addon/cookies-txt/\n"
                    "3. Active Añadir a Firefox y confirme la instalación.\n"
                    "4. Abra youtube.com e inicie sesión.\n"
                    "5. Abra Extensiones, elija cookies.txt y exporte el archivo.\n"
                    "6. En el programa seleccione Archivo cookies.txt y abra el archivo exportado.\n\n"
                    "Importante: cookies.txt contiene información de su sesión. No lo comparta, no lo envíe por correo y no lo publique. El programa guarda solamente la ruta del archivo; no copia sus cookies al historial, al registro ni a los informes de diagnóstico."
                ),
                "en": (
                    "GOOGLE CHROME\n\n"
                    "1. Open Google Chrome and press Ctrl+L.\n"
                    "2. Paste this address and press Enter:\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Find Add to Chrome, activate it, and confirm with Add extension.\n"
                    "4. Open youtube.com and sign in with the account you use on YouTube.\n"
                    "5. Open Chrome's Extensions button. With a screen reader, use Tab through the toolbar until you find Extensions.\n"
                    "6. Choose Get cookies.txt LOCALLY.\n"
                    "7. Select Netscape. Do not use JSON.\n"
                    "8. Export the cookies and save cookies.txt in a folder you can find easily.\n"
                    "9. Return to Accessible Music Downloader, Tools, Options, YouTube authentication.\n"
                    "10. Choose cookies.txt file (recommended).\n"
                    "11. Activate Select cookies.txt file and open the file you exported.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Open Firefox and press Ctrl+L.\n"
                    "2. Paste this address and press Enter:\n"
                    "https://addons.mozilla.org/firefox/addon/cookies-txt/\n"
                    "3. Activate Add to Firefox and confirm the installation.\n"
                    "4. Open youtube.com and sign in.\n"
                    "5. Open Extensions, choose cookies.txt, and export the file.\n"
                    "6. In the program, select cookies.txt file and open the exported file.\n\n"
                    "Important: cookies.txt contains session information. Do not share, email, or publish it. The program stores only the file path; it never copies your cookies into history, logs, or diagnostic reports."
                ),
                "fr": (
                    "GOOGLE CHROME\n\n"
                    "1. Ouvrez Google Chrome et appuyez sur Ctrl+L.\n"
                    "2. Collez cette adresse et appuyez sur Entrée :\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Recherchez Ajouter à Chrome, activez-le puis confirmez avec Ajouter l'extension.\n"
                    "4. Ouvrez youtube.com et connectez-vous avec votre compte YouTube.\n"
                    "5. Ouvrez le bouton Extensions de Chrome. Avec un lecteur d'écran, parcourez la barre d'outils avec Tab jusqu'à Extensions.\n"
                    "6. Choisissez Get cookies.txt LOCALLY.\n"
                    "7. Sélectionnez Netscape. N'utilisez pas JSON.\n"
                    "8. Exportez les cookies et enregistrez cookies.txt dans un dossier facile à retrouver.\n"
                    "9. Revenez dans le programme, Outils, Options, Authentification YouTube.\n"
                    "10. Choisissez Fichier cookies.txt (recommandé).\n"
                    "11. Activez Sélectionner le fichier cookies.txt et ouvrez le fichier exporté.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Ouvrez Firefox et appuyez sur Ctrl+L.\n"
                    "2. Ouvrez : https://addons.mozilla.org/fr/firefox/addon/cookies-txt/\n"
                    "3. Activez Ajouter à Firefox et confirmez.\n"
                    "4. Ouvrez youtube.com et connectez-vous.\n"
                    "5. Ouvrez Extensions, choisissez cookies.txt et exportez le fichier.\n"
                    "6. Dans le programme, sélectionnez le fichier cookies.txt exporté.\n\n"
                    "Important : cookies.txt contient des informations de session. Ne le partagez pas, ne l'envoyez pas par courriel et ne le publiez pas. Le programme enregistre uniquement le chemin du fichier."
                ),
                "it": (
                    "GOOGLE CHROME\n\n"
                    "1. Apri Google Chrome e premi Ctrl+L.\n"
                    "2. Incolla questo indirizzo e premi Invio:\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Cerca Aggiungi, attivalo e conferma l'installazione dell'estensione.\n"
                    "4. Apri youtube.com e accedi con il tuo account YouTube.\n"
                    "5. Apri il pulsante Estensioni di Chrome. Con uno screen reader, usa Tab nella barra degli strumenti fino a Estensioni.\n"
                    "6. Scegli Get cookies.txt LOCALLY.\n"
                    "7. Seleziona Netscape. Non usare JSON.\n"
                    "8. Esporta i cookie e salva cookies.txt in una cartella facile da trovare.\n"
                    "9. Torna nel programma, Strumenti, Opzioni, Autenticazione YouTube.\n"
                    "10. Scegli File cookies.txt (consigliato).\n"
                    "11. Attiva Seleziona file cookies.txt e apri il file esportato.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Apri Firefox e premi Ctrl+L.\n"
                    "2. Apri: https://addons.mozilla.org/it/firefox/addon/cookies-txt/\n"
                    "3. Attiva Aggiungi a Firefox e conferma.\n"
                    "4. Apri youtube.com e accedi.\n"
                    "5. Apri Estensioni, scegli cookies.txt ed esporta il file.\n"
                    "6. Nel programma seleziona il file cookies.txt esportato.\n\n"
                    "Importante: cookies.txt contiene informazioni di sessione. Non condividerlo, non inviarlo via e-mail e non pubblicarlo. Il programma memorizza soltanto il percorso del file."
                ),
                "pt": (
                    "GOOGLE CHROME\n\n"
                    "1. Abra o Google Chrome e pressione Ctrl+L.\n"
                    "2. Cole este endereço e pressione Enter:\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Procure Adicionar ao Chrome, ative e confirme com Adicionar extensão.\n"
                    "4. Abra youtube.com e entre com a conta que usa no YouTube.\n"
                    "5. Abra o botão Extensões do Chrome. Com leitor de tela, use Tab na barra de ferramentas até Extensões.\n"
                    "6. Escolha Get cookies.txt LOCALLY.\n"
                    "7. Selecione Netscape. Não use JSON.\n"
                    "8. Exporte os cookies e salve cookies.txt em uma pasta fácil de localizar.\n"
                    "9. Volte ao programa, Ferramentas, Opções, Autenticação do YouTube.\n"
                    "10. Escolha Arquivo cookies.txt (recomendado).\n"
                    "11. Ative Selecionar arquivo cookies.txt e abra o arquivo exportado.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Abra o Firefox e pressione Ctrl+L.\n"
                    "2. Abra: https://addons.mozilla.org/pt-BR/firefox/addon/cookies-txt/\n"
                    "3. Ative Adicionar ao Firefox e confirme.\n"
                    "4. Abra youtube.com e entre na sua conta.\n"
                    "5. Abra Extensões, escolha cookies.txt e exporte o arquivo.\n"
                    "6. No programa selecione o arquivo cookies.txt exportado.\n\n"
                    "Importante: cookies.txt contém informações da sessão. Não compartilhe, não envie por e-mail e não publique. O programa armazena somente o caminho do arquivo."
                ),
                "ru": (
                    "GOOGLE CHROME\n\n"
                    "1. Откройте Google Chrome и нажмите Ctrl+L.\n"
                    "2. Вставьте этот адрес и нажмите Enter:\n"
                    "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc\n"
                    "3. Найдите кнопку добавления в Chrome, активируйте ее и подтвердите установку расширения.\n"
                    "4. Откройте youtube.com и войдите в свою учетную запись YouTube.\n"
                    "5. Откройте кнопку Расширения Chrome. Со скринридером переходите по панели инструментов клавишей Tab до Расширения.\n"
                    "6. Выберите Get cookies.txt LOCALLY.\n"
                    "7. Выберите формат Netscape. Не используйте JSON.\n"
                    "8. Экспортируйте cookies и сохраните cookies.txt в удобной папке.\n"
                    "9. Вернитесь в программу: Инструменты, Параметры, Аутентификация YouTube.\n"
                    "10. Выберите Файл cookies.txt (рекомендуется).\n"
                    "11. Активируйте выбор файла cookies.txt и откройте экспортированный файл.\n\n"
                    "MOZILLA FIREFOX\n\n"
                    "1. Откройте Firefox и нажмите Ctrl+L.\n"
                    "2. Откройте: https://addons.mozilla.org/firefox/addon/cookies-txt/\n"
                    "3. Добавьте расширение в Firefox и подтвердите установку.\n"
                    "4. Откройте youtube.com и войдите в учетную запись.\n"
                    "5. Откройте Расширения, выберите cookies.txt и экспортируйте файл.\n"
                    "6. В программе выберите экспортированный cookies.txt.\n\n"
                    "Важно: cookies.txt содержит данные сеанса. Не передавайте его другим людям, не отправляйте по почте и не публикуйте. Программа сохраняет только путь к файлу."
                ),
            }
            mensaje_ayuda = ayudas.get(idioma_actual(), ayudas["es"])
            self._mostrar_mensaje_accesible(
                traducir("Cómo obtener cookies.txt"), mensaje_ayuda, wx.ICON_INFORMATION, registrar=False
            )

        btn_archivo_cookies.Bind(wx.EVT_BUTTON, seleccionar_archivo_cookies)
        btn_ayuda_cookies.Bind(wx.EVT_BUTTON, mostrar_ayuda_cookies)
        combo_metodo_auth.Bind(wx.EVT_CHOICE, actualizar_controles_autenticacion)
        sizer.Add(sizer_youtube, 0, wx.EXPAND | wx.ALL, 8)

        chk_sonidos = wx.CheckBox(panel, label="Activar sonidos")
        chk_sonidos.SetValue(bool(self.configuracion.get("sonidos_activados", True)))
        chk_sonidos.SetName("Activar o desactivar sonidos")
        sizer.Add(chk_sonidos, 0, wx.ALL, 8)

        caja_sonidos = wx.StaticBox(panel, label="Sonidos individuales")
        sizer_sonidos = wx.StaticBoxSizer(caja_sonidos, wx.VERTICAL)
        chk_inicio = wx.CheckBox(caja_sonidos, label="Sonido de inicio")
        chk_cierre = wx.CheckBox(caja_sonidos, label="Sonido de cierre")
        chk_descarga = wx.CheckBox(caja_sonidos, label="Sonido de descarga finalizada")
        chk_error = wx.CheckBox(caja_sonidos, label="Sonido de error")
        chk_inicio.SetValue(bool(self.configuracion.get("sonido_inicio", True)))
        chk_cierre.SetValue(bool(self.configuracion.get("sonido_cierre", True)))
        chk_descarga.SetValue(bool(self.configuracion.get("sonido_descarga", True)))
        chk_error.SetValue(bool(self.configuracion.get("sonido_error", True)))
        for chk in (chk_inicio, chk_cierre, chk_descarga, chk_error):
            sizer_sonidos.Add(chk, 0, wx.ALL, 4)
        sizer.Add(sizer_sonidos, 0, wx.EXPAND | wx.ALL, 8)

        caja_reproductor = wx.StaticBox(panel, label="Opciones del reproductor")
        sizer_reproductor = wx.StaticBoxSizer(caja_reproductor, wx.VERTICAL)

        sizer_reproductor.Add(wx.StaticText(caja_reproductor, label="Volumen inicial:"), 0, wx.ALL, 4)
        opciones_volumen = [f"{n}%" for n in range(0, 101, 10)]
        combo_volumen = wx.Choice(caja_reproductor)
        volumen_actual = str(self.configuracion.get("reproductor_volumen_inicial", "50%") or "50%")
        # Si el usuario dejó, por ejemplo, 57 % mediante los atajos del reproductor,
        # no lo convertimos silenciosamente a 50 % al abrir y aceptar Opciones.
        if volumen_actual not in opciones_volumen:
            try:
                numero_actual = int(volumen_actual.replace("%", "").strip())
                if 0 <= numero_actual <= 100:
                    opciones_volumen.append(f"{numero_actual}%")
                    opciones_volumen.sort(key=lambda valor: int(valor.replace("%", "")))
                else:
                    volumen_actual = "50%"
            except Exception:
                volumen_actual = "50%"
        combo_volumen.AppendItems(opciones_volumen)
        combo_volumen.SetSelection(opciones_volumen.index(volumen_actual))
        combo_volumen.SetName("Volumen inicial del reproductor")
        sizer_reproductor.Add(combo_volumen, 0, wx.EXPAND | wx.ALL, 4)

        sizer_reproductor.Add(wx.StaticText(caja_reproductor, label="Dispositivo de salida:"), 0, wx.ALL, 4)
        dispositivos = listar_dispositivos_audio()
        ids_dispositivos = [identificador for identificador, descripcion in dispositivos]
        etiquetas_dispositivos = [descripcion for identificador, descripcion in dispositivos]
        combo_dispositivo = wx.Choice(caja_reproductor, choices=etiquetas_dispositivos)
        dispositivo_actual = str(self.configuracion.get("reproductor_dispositivo_salida", "auto") or "auto")
        seleccion_dispositivo = ids_dispositivos.index(dispositivo_actual) if dispositivo_actual in ids_dispositivos else 0
        combo_dispositivo.SetSelection(seleccion_dispositivo)
        combo_dispositivo.SetName("Dispositivo de salida del reproductor")
        sizer_reproductor.Add(combo_dispositivo, 0, wx.EXPAND | wx.ALL, 4)

        sizer_reproductor.Add(wx.StaticText(caja_reproductor, label="Segundos para adelantar o retroceder:"), 0, wx.ALL, 4)
        opciones_salto = ["5 segundos", "10 segundos", "15 segundos", "30 segundos"]
        combo_salto = wx.Choice(caja_reproductor, choices=opciones_salto)
        salto_actual = self.configuracion.get("reproductor_salto_segundos", "10 segundos")
        if salto_actual not in opciones_salto:
            salto_actual = "10 segundos"
        combo_salto.SetSelection(opciones_salto.index(salto_actual))
        combo_salto.SetName("Segundos para adelantar o retroceder")
        sizer_reproductor.Add(combo_salto, 0, wx.EXPAND | wx.ALL, 4)

        sizer_reproductor.Add(wx.StaticText(caja_reproductor, label="Velocidad inicial:"), 0, wx.ALL, 4)
        opciones_velocidad = ["0.75", "1.00", "1.25", "1.50"]
        combo_velocidad = wx.Choice(caja_reproductor, choices=opciones_velocidad)
        velocidad_actual = self.configuracion.get("reproductor_velocidad_inicial", "1.00")
        if velocidad_actual not in opciones_velocidad:
            velocidad_actual = "1.00"
        combo_velocidad.SetSelection(opciones_velocidad.index(velocidad_actual))
        combo_velocidad.SetName("Velocidad inicial del reproductor")
        sizer_reproductor.Add(combo_velocidad, 0, wx.EXPAND | wx.ALL, 4)

        chk_posicion_pausa = wx.CheckBox(caja_reproductor, label="Anunciar posición al pausar")
        chk_posicion_pausa.SetValue(bool(self.configuracion.get("reproductor_anunciar_posicion_al_pausar", False)))
        chk_posicion_pausa.SetName("Anunciar posición actual al pausar")
        sizer_reproductor.Add(chk_posicion_pausa, 0, wx.ALL, 4)
        sizer.Add(sizer_reproductor, 0, wx.EXPAND | wx.ALL, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_aceptar = wx.Button(panel, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
        btn_aceptar.SetName("Aceptar opciones")
        btn_cancelar.SetName("Cancelar opciones")
        fila.Add(btn_aceptar, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sizer)
        actualizar_controles_autenticacion()
        panel.FitInside()
        contenedor = wx.BoxSizer(wx.VERTICAL)
        contenedor.Add(panel, 1, wx.EXPAND)
        dialogo.SetSizer(contenedor)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        # actualizar_controles_autenticacion() ya hizo Show/Hide y Layout de varios
        # controles justo antes (según el método de autenticación guardado). Cuando
        # el método guardado es Archivo cookies.txt, esos controles quedan visibles
        # y el diálogo crece.
        #
        # Se comprobó con NVDA real (comando "reportar foco actual") que el foco
        # final SÍ termina en combo_frecuencia; el problema es un anuncio de más
        # que ocurre antes de eso. Tanto wx.CallAfter como wx.CallLater piden el
        # foco recién cuando el bucle de eventos ya está procesando mensajes CON
        # la ventana visible, es decir, después de que Windows ya asignó su propio
        # foco inicial por defecto. Solo cuando los controles de Archivo
        # cookies.txt están visibles, ese foco por defecto de Windows parece caer
        # en el botón "Seleccionar archivo cookies.txt...", y NVDA anuncia su
        # etiqueta ("Archivo cookies.txt:") antes de que nuestro pedido de foco,
        # con una pequeña demora, lo corrija al combo real.
        #
        # Para no depender de ganarle a Windows por unos milisegundos, se pide el
        # foco en cuanto el diálogo se activa (EVT_ACTIVATE), que ocurre como
        # parte del mismo evento nativo de mostrar la ventana, en vez de esperar a
        # que el bucle de eventos quede libre. Se mantiene además el CallLater
        # como respaldo, por si EVT_ACTIVATE no llegara a dispararse en algún caso.
        def _pedir_foco_inicial_opciones(evento_activar):
            if evento_activar.GetActive():
                combo_frecuencia.SetFocus()
            evento_activar.Skip()

        dialogo.Bind(wx.EVT_ACTIVATE, _pedir_foco_inicial_opciones)
        wx.CallLater(120, combo_frecuencia.SetFocus)

        if dialogo.ShowModal() == wx.ID_OK:
            self.configuracion["frecuencia_actualizaciones"] = combo_frecuencia.GetStringSelection()
            self.configuracion["frecuencia_actualizaciones_motor"] = combo_frecuencia_motor.GetStringSelection()
            self.configuracion["actualizar_motor_silenciosamente"] = chk_actualizar_motor_auto.GetValue()
            indice_canal_motor = combo_canal_motor.GetSelection()
            self.configuracion["canal_actualizaciones_motor"] = canales_motor_ids[indice_canal_motor] if 0 <= indice_canal_motor < len(canales_motor_ids) else "stable"
            self.configuracion["busqueda_resultados_predeterminados"] = combo_resultados.GetStringSelection()
            self.configuracion["busqueda_preguntar_cantidad"] = chk_preguntar_resultados.GetValue()
            self.configuracion["youtube_preferir_idioma_programa"] = chk_idioma_youtube.GetValue()
            indice_metodo = combo_metodo_auth.GetSelection()
            metodo_auth = metodos_auth_ids[indice_metodo] if 0 <= indice_metodo < len(metodos_auth_ids) else "ninguno"
            if metodo_auth == "cookies_txt":
                valido, mensaje_validacion = validar_archivo_cookies_netscape(txt_archivo_cookies.GetValue())
                if not valido:
                    self._mostrar_mensaje_accesible(
                        "Archivo cookies.txt no válido", mensaje_validacion, wx.ICON_INFORMATION, registrar=False
                    )
                    dialogo.Destroy()
                    return
            self.configuracion["youtube_metodo_autenticacion"] = metodo_auth
            self.configuracion["youtube_archivo_cookies"] = txt_archivo_cookies.GetValue().strip()
            self.configuracion["youtube_usar_cookies_respaldo"] = metodo_auth == "navegador"
            indice_nav = combo_navegador.GetSelection()
            self.configuracion["youtube_navegador_cookies"] = navegadores_ids[indice_nav] if 0 <= indice_nav < len(navegadores_ids) else "auto"
            self.configuracion["sonidos_activados"] = chk_sonidos.GetValue()
            self.configuracion["sonido_inicio"] = chk_inicio.GetValue()
            self.configuracion["sonido_cierre"] = chk_cierre.GetValue()
            self.configuracion["sonido_descarga"] = chk_descarga.GetValue()
            self.configuracion["sonido_error"] = chk_error.GetValue()
            self.configuracion["reproductor_volumen_inicial"] = combo_volumen.GetStringSelection()
            indice_disp = combo_dispositivo.GetSelection()
            self.configuracion["reproductor_dispositivo_salida"] = ids_dispositivos[indice_disp] if 0 <= indice_disp < len(ids_dispositivos) else "auto"
            self.configuracion["reproductor_salto_segundos"] = combo_salto.GetStringSelection()
            self.configuracion["reproductor_velocidad_inicial"] = combo_velocidad.GetStringSelection()
            self.configuracion["reproductor_anunciar_posicion_al_pausar"] = chk_posicion_pausa.GetValue()
            self.guardar_configuracion()
            self._aplicar_preferencias_descargador()
            hablar_async(traducir("Opciones guardadas"), limpiar=True)
            self.SetStatusText("Opciones guardadas")

        dialogo.Destroy()

    def _tecla_campo_url(self, evento):
        codigo = evento.GetKeyCode()
        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._accion_url_enter()
            return
        evento.Skip()

    def _tecla_campo_url_hook(self, evento):
        codigo = evento.GetKeyCode()
        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._accion_url_enter()
            return
        evento.Skip()

    def _es_url_playlist_youtube(self, url):
        texto = str(url or "").strip()
        if not texto:
            return False
        try:
            parsed = urlparse(texto)
            host = (parsed.netloc or "").lower().split(":", 1)[0]
            if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
                return False
            consulta = parse_qs(parsed.query)
            lista_id = (consulta.get("list") or [""])[0].strip()
            if not lista_id:
                return False
            # Una URL /playlist es inequívoca. También aceptamos URLs con list
            # pero sin video individual, que es la forma habitual de compartir una lista.
            return parsed.path.rstrip("/") == "/playlist" or not (consulta.get("v") or [""])[0].strip()
        except Exception:
            return False

    def _coleccion_playlist_desde_url(self, url, titulo=None):
        return {
            "tipo": "Lista de reproducción",
            "tipo_clave": "playlist",
            "titulo": titulo or "Lista de reproducción",
            "canal": "No disponible",
            "autor": "No disponible",
            "url": str(url or "").strip(),
            "descripcion": "No disponible",
            "origen_url_directa": True,
        }

    def _accion_url_enter(self, evento=None):
        if self.notebook.GetSelection() != 0:
            return
        url = self.campo_url.GetValue().strip()
        if not url:
            self._mostrar_mensaje_accesible(
                "Falta URL",
                "Debe pegar una URL para continuar.",
                wx.ICON_INFORMATION,
                enfocar_control=self.campo_url,
            )
            return
        if self._es_url_playlist_youtube(url):
            self._mostrar_acciones_playlist_url(url)
        else:
            self._mostrar_acciones_url()

    def _mostrar_acciones_url(self):
        opciones = [(traducir("Descargar (Alt+D)"), "Descargar"), (traducir("Información (Alt+I)"), "Información")]
        dialogo = wx.Dialog(self, title="Acción para URL", size=(430, 185))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label="Seleccione una acción. Alt+D descarga. Alt+I información."), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=[etiqueta for etiqueta, accion in opciones])
        combo.SetSelection(0)
        combo.SetName("Acción para la URL pegada. Alt más D descarga. Alt más I información")
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(dialogo, wx.ID_CANCEL, label="Cancelar")
        fila.Add(btn_ok, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        accion_directa = {"valor": None}

        def aceptar_con_enter(evento):
            codigo = evento.GetKeyCode()
            if evento.AltDown() and codigo in (ord("D"), ord("d")):
                accion_directa["valor"] = "Descargar"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("I"), ord("i")):
                accion_directa["valor"] = "Información"
                dialogo.EndModal(wx.ID_OK)
                return
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK)
                return
            evento.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, aceptar_con_enter)
        combo.Bind(wx.EVT_KEY_DOWN, aceptar_con_enter)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo.SetFocus()
        hablar_async("Elija una acción. Descargar, Alt más D. Información, Alt más I", limpiar=True)

        accion = None
        if dialogo.ShowModal() == wx.ID_OK:
            if accion_directa["valor"]:
                accion = accion_directa["valor"]
            else:
                seleccion = combo.GetSelection()
                accion = opciones[seleccion][1] if 0 <= seleccion < len(opciones) else None
        dialogo.Destroy()
        self.notebook.SetSelection(0)
        self.campo_url.SetFocus()

        if accion == "Descargar":
            self.iniciar_descarga()
        elif accion == "Información":
            self.obtener_informacion()

    def _mostrar_acciones_playlist_url(self, url):
        coleccion = self._coleccion_playlist_desde_url(url)
        opciones = [
            (traducir("Ver contenido de la playlist"), "Ver contenido"),
            (traducir("Agregar toda la playlist a la cola de descargas"), "Agregar toda"),
            (traducir("Seleccionar un rango de la playlist"), "Rango"),
            (traducir("Agregar o quitar la playlist de favoritos"), "Favorito"),
            (traducir("Información"), "Información"),
        ]
        dialogo = wx.Dialog(self, title=traducir("Playlist detectada"), size=(520, 230))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label=traducir("Se detectó una lista de reproducción. Elija qué desea hacer.")), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=[x[0] for x in opciones])
        combo.SetSelection(0)
        combo.SetName(traducir("Acciones para la playlist pegada"))
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(wx.Button(dialogo, wx.ID_OK, label=traducir("Aceptar")), 0, wx.ALL, 5)
        fila.Add(wx.Button(dialogo, wx.ID_CANCEL, label=traducir("Cancelar")), 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo.SetFocus()
        hablar_async("Se detectó una lista de reproducción. Elija ver su contenido, agregarla completa a la cola o seleccionar un rango.", limpiar=True)
        accion = None
        if dialogo.ShowModal() == wx.ID_OK:
            indice = combo.GetSelection()
            accion = opciones[indice][1] if 0 <= indice < len(opciones) else None
        dialogo.Destroy()
        self.notebook.SetSelection(0)
        self.campo_url.SetFocus()
        if accion == "Ver contenido":
            self._preparar_playlist_directa(coleccion, "ver")
        elif accion == "Agregar toda":
            self._preparar_playlist_directa(coleccion, "toda")
        elif accion == "Rango":
            self._preparar_playlist_directa(coleccion, "rango")
        elif accion == "Favorito":
            self._preparar_playlist_directa(coleccion, "favorito")
        elif accion == "Información":
            self._preparar_playlist_directa(coleccion, "info")

    def _preparar_playlist_directa(self, coleccion, accion):
        hablar_async("Obteniendo información de la playlist", limpiar=True)
        def trabajo():
            actualizada = dict(coleccion)
            try:
                info = self.descargador.obtener_informacion_coleccion(actualizada.get("url", ""), tipo="playlist")
                if info:
                    actualizada.update({k: v for k, v in info.items() if v not in (None, "")})
            except Exception:
                pass
            wx.CallAfter(self._ejecutar_accion_playlist, actualizada, accion, True)
        threading.Thread(target=trabajo, daemon=True).start()

    def _ejecutar_accion_playlist(self, coleccion, accion, desde_url=False):
        if desde_url:
            self.notebook.SetSelection(2)
        if accion == "ver":
            self.cargar_videos_coleccion_para_elegir(coleccion)
        elif accion == "toda":
            self.agregar_playlist_completa_cola(coleccion)
        elif accion == "rango":
            self.agregar_rango_playlist_cola(coleccion)
        elif accion == "favorito":
            self._alternar_favorito_coleccion(coleccion)
        elif accion == "info":
            self.informacion_coleccion(coleccion)

    def _actualizar_botones_descarga(self, descargando):
        self.btn_descargar.Enable(not descargando)
        self.btn_info.Enable(not descargando)
        self.btn_examinar.Enable(not descargando)
        self.btn_cancelar.Enable(descargando)
        self.menu_descargar.Enable(not descargando)
        self.menu_obtener_info.Enable(not descargando)
        self.menu_seleccionar_carpeta.Enable(not descargando)
        self.menu_cancelar.Enable(descargando)

    def _actualizar_botones_busqueda(self, buscando):
        self.campo_busqueda.Enable(not buscando)
        try:
            self.campo_busqueda_coleccion.Enable(not buscando)
        except Exception:
            pass
        self.menu_buscar.Enable(not buscando)

    def enfocar_url(self, evento=None):
        self.notebook.SetSelection(0)
        self.campo_url.SetFocus()
        self.campo_url.SetInsertionPointEnd()

    def enfocar_busqueda(self, evento=None):
        self.notebook.SetSelection(1)
        self.campo_busqueda.SetFocus()
        self.campo_busqueda.SetInsertionPointEnd()

    def _tecla_campo_busqueda(self, evento):
        codigo = evento.GetKeyCode()

        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.iniciar_busqueda()
            return

        evento.Skip()

    def _tecla_campo_busqueda_hook(self, evento):
        codigo = evento.GetKeyCode()

        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.iniciar_busqueda()
            return

        evento.Skip()

    def examinar_carpeta(self, evento=None):
        seleccionar_carpeta(self.carpeta)

    def mostrar_atajos_teclado(self, evento=None):
        texto = traducir_clave("__help.shortcuts__")
        self._mostrar_texto_dialogo(
            traducir("Atajos de teclado"),
            texto,
            traducir("Lista de atajos de teclado"),
        )

    def mostrar_novedades_version(self, evento=None):
        clave_novedades = NOVEDADES_VERSION.get(VERSION)
        if clave_novedades:
            texto = traducir_clave(clave_novedades)
        else:
            texto = traducir("No hay novedades registradas para esta versión.")
        self._mostrar_texto_dialogo(
            traducir_formato("Novedades de la versión {version}", version=VERSION),
            texto,
            traducir("Novedades de esta versión"),
        )

    def abrir_manual_usuario(self, evento=None):
        codigo = self.configuracion.get("idioma", idioma_actual())
        nombres = [f"MANUAL_{str(codigo).upper()}.pdf", f"MANUAL_{str(codigo).upper()}.txt", "MANUAL_ES.pdf", "MANUAL_ES.txt"]
        bases = []
        if getattr(sys, "frozen", False):
            bases.extend([Path(sys.executable).resolve().parent, Path(sys.executable).resolve().parent / "_internal"])
        bases.extend([Path(__file__).resolve().parent, Path(__file__).resolve().parent / "manuales"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bases.extend([Path(meipass), Path(meipass) / "manuales"])
        for base in bases:
            for nombre in nombres:
                candidatos = [base / nombre, base / "manuales" / nombre]
                for ruta in candidatos:
                    if ruta.exists():
                        try:
                            if os.name == "nt":
                                os.startfile(str(ruta))
                            else:
                                webbrowser.open(ruta.resolve().as_uri())
                            hablar_async("Manual de usuario abierto", limpiar=True)
                            return
                        except Exception:
                            continue
        self._mostrar_error_detallado("Manual no disponible", "No se encontró el manual de usuario en esta instalación.")

    def mostrar_acerca(self, evento=None):
        wx.MessageBox(
            traducir_clave("__about.body__").format(app=APP_NOMBRE, version=VERSION),
            "Acerca de",
            wx.OK | wx.ICON_INFORMATION,
        )

    def mostrar_contacto(self, evento=None):
        wx.MessageBox(
            traducir_clave("__contact.body__").format(app=APP_NOMBRE),
            "Contacto",
            wx.OK | wx.ICON_INFORMATION,
        )

    def salir_programa(self, evento=None):
        self.Close()

    def abrir_carpeta_descargas(self, evento=None):
        carpeta = self.carpeta.GetValue().strip()

        if not carpeta:
            self._mostrar_mensaje_accesible("Información", "No hay carpeta seleccionada.", wx.ICON_INFORMATION)
            return

        try:
            abrir_carpeta(carpeta)
        except Exception:
            self._mostrar_error_detallado("Error", "No fue posible abrir la carpeta.")

    def abrir_carpeta_logs(self, evento=None):
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            abrir_carpeta(str(LOGS_DIR))
        except Exception:
            self._mostrar_error_detallado("Error", "No fue posible abrir la carpeta de logs.")

    def _texto_menu_abrir_con(self):
        """Un solo texto de menú que cambia según el estado: si ya está
        agregado, ofrece quitarlo; si no, ofrece agregarlo."""
        try:
            ya_agregado = integracion_windows.registrado()
        except Exception:
            ya_agregado = False
        if ya_agregado:
            return "Quitar \"Reproducir con Descargador de Música Accesible\" del menú de Windows"
        return "Agregar \"Reproducir con Descargador de Música Accesible\" al menú de Windows"

    def _actualizar_texto_abrir_con(self):
        try:
            self.menu_abrir_con.SetItemLabel(self._texto_menu_abrir_con())
        except Exception:
            pass

    def _al_abrir_menu(self, evento):
        try:
            if evento.GetMenu() is self.menu_herramientas:
                self._actualizar_texto_abrir_con()
        except Exception:
            pass
        evento.Skip()

    def alternar_abrir_con_windows(self, evento=None):
        """Agrega o quita del menú de Windows según corresponda: si ya
        estaba agregado, lo quita; si no, lo agrega."""
        try:
            ya_agregado = integracion_windows.registrado()
        except Exception:
            ya_agregado = False
        if ya_agregado:
            self.quitar_abrir_con_windows()
        else:
            self.agregar_abrir_con_windows()
        self._actualizar_texto_abrir_con()

    def agregar_abrir_con_windows(self):
        """Agrega el programa al menú Abrir con de Windows para archivos de
        audio, sin cambiar el reproductor predeterminado del sistema."""
        try:
            self.SetStatusText("Agregando \"Reproducir con Descargador de Música Accesible\" al menú de Windows")
            self.estado.SetValue(traducir_dinamico("Agregando \"Reproducir con Descargador de Música Accesible\" al menú de Windows"))
        except Exception:
            pass
        hablar_async("Agregando \"Reproducir con Descargador de Música Accesible\" al menú de Windows", limpiar=True)
        try:
            integracion_windows.registrar()
            self._mostrar_mensaje_accesible(
                "Menú de Windows",
                "Descargador de Música Accesible se agregó al menú de Windows. Ahora puede elegir \"Reproducir con Descargador de Música Accesible\" al hacer clic derecho o presionar la tecla Aplicaciones sobre una canción, en Abrir con.",
                wx.ICON_INFORMATION,
                "Agregado al menú de Windows",
                False,
            )
        except Exception as exc:
            self._mostrar_error_detallado(
                "No se pudo agregar al menú de Windows",
                traducir_formato(
                    "No se pudo agregar Descargador de Música Accesible al menú de Windows. Detalle: {detalle}",
                    detalle=exc,
                ),
                "Error",
            )

    def quitar_abrir_con_windows(self):
        """Quita al programa del menú Abrir con de Windows, si se había
        agregado antes."""
        try:
            self.SetStatusText("Quitando \"Reproducir con Descargador de Música Accesible\" del menú de Windows")
            self.estado.SetValue(traducir_dinamico("Quitando \"Reproducir con Descargador de Música Accesible\" del menú de Windows"))
        except Exception:
            pass
        hablar_async("Quitando \"Reproducir con Descargador de Música Accesible\" del menú de Windows", limpiar=True)
        try:
            integracion_windows.quitar_registro()
            self._mostrar_mensaje_accesible(
                "Menú de Windows",
                "Descargador de Música Accesible se quitó del menú de Windows.",
                wx.ICON_INFORMATION,
                "Quitado del menú de Windows",
                False,
            )
        except Exception as exc:
            self._mostrar_error_detallado(
                "No se pudo quitar del menú de Windows",
                traducir_formato(
                    "No se pudo quitar Descargador de Música Accesible del menú de Windows. Detalle: {detalle}",
                    detalle=exc,
                ),
                "Error",
            )

    def buscar_actualizaciones_programa(self, evento=None):
        """Revisa si existe una nueva versión del programa principal."""
        try:
            self.SetStatusText("Buscando actualizaciones del programa")
            self.estado.SetValue(traducir_dinamico("Buscando actualizaciones del programa"))
        except Exception:
            pass
        hablar_async("Buscando actualizaciones del programa", limpiar=True)
        hilo = threading.Thread(target=self._buscar_actualizaciones_programa_hilo, daemon=True)
        hilo.start()

    def _buscar_actualizaciones_programa_hilo(self):
        try:
            info = consultar_actualizacion(VERSION)
            if info is None:
                wx.CallAfter(
                    self._mostrar_mensaje_accesible,
                    "No hay actualizaciones disponibles",
                    "Ya tiene la versión más reciente de Descargador de Música Accesible.",
                    wx.ICON_INFORMATION,
                    "Actualización del programa",
                    False,
                )
                return
            wx.CallAfter(self._preguntar_descargar_actualizacion_programa, info)
        except ActualizadorNoConfigurado:
            mensaje = (
                "El actualizador está preparado, pero todavía no tiene configurado el enlace de actualización.\n\n"
                "Cuando suba el programa a GitHub, configure el archivo actualizacion.json con el repositorio o el enlace de actualización."
            )
            wx.CallAfter(
                self._mostrar_mensaje_accesible,
                "Actualizador no configurado",
                mensaje,
                wx.ICON_INFORMATION,
                "Actualizador no configurado",
                True,
            )
        except Exception as exc:
            wx.CallAfter(
                self._mostrar_error_detallado,
                "No se pudo comprobar actualizaciones",
                "No se pudo comprobar si hay una actualización disponible. Verifique su conexión a Internet e inténtelo nuevamente.\n\n" + str(exc),
                "Error comprobando actualizaciones",
            )

    @staticmethod
    def _limpiar_notas_actualizacion(texto):
        """Quita el marcado Markdown más común de las notas de la versión para que
        se escuchen de forma natural con el lector de pantalla (sin símbolos
        sueltos de #, * o `)."""
        texto = str(texto or "").strip()
        if not texto:
            return texto
        texto = re.sub(r"^#{1,6}\s*", "", texto, flags=re.MULTILINE)
        texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
        texto = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", texto)
        texto = re.sub(r"`([^`]+)`", r"\1", texto)
        texto = re.sub(r"^[-*]\s+", "- ", texto, flags=re.MULTILINE)
        return texto.strip()

    def _preguntar_descargar_actualizacion_programa(self, info, continuar_motor_despues=False):
        notas = self._limpiar_notas_actualizacion(getattr(info, "notas", ""))
        if not notas:
            notas = traducir("Esta versión no incluye una descripción detallada de novedades.")

        contenido = (
            traducir_formato("Versión actual: {version}", version=VERSION) + "\n"
            + traducir_formato("Nueva versión: {version}", version=info.version) + "\n\n"
            + traducir("Novedades de esta versión:") + "\n\n"
            + notas
        )

        hablar_async(traducir("Nueva actualización disponible"), limpiar=True)

        dialogo = wx.Dialog(
            self,
            title=traducir("Nueva actualización disponible"),
            size=(640, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        panel = wx.Panel(dialogo)
        sizer = wx.BoxSizer(wx.VERTICAL)

        etiqueta = wx.StaticText(
            panel,
            label=traducir(
                "Se recomienda actualizar para recibir mejoras, correcciones y mayor estabilidad.\n"
                "Use las flechas arriba y abajo para leer las novedades de esta versión."
            ),
        )
        sizer.Add(etiqueta, 0, wx.EXPAND | wx.ALL, 10)

        cuadro = wx.TextCtrl(panel, value=contenido, style=wx.TE_MULTILINE | wx.TE_READONLY)
        cuadro.SetName(traducir("Novedades de la nueva versión"))
        sizer.Add(cuadro, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        botones = wx.BoxSizer(wx.HORIZONTAL)
        btn_aceptar = wx.Button(panel, wx.ID_YES, label=traducir("Aceptar"))
        btn_aceptar.SetName(traducir("Aceptar y descargar la actualización"))
        btn_mas_tarde = wx.Button(panel, wx.ID_NO, label=traducir("Más tarde"))
        btn_mas_tarde.SetName(traducir("Actualizar más tarde"))
        botones.Add(btn_aceptar, 0, wx.ALL, 10)
        botones.Add(btn_mas_tarde, 0, wx.TOP | wx.BOTTOM | wx.RIGHT, 10)
        sizer.Add(botones, 0, wx.ALIGN_RIGHT)

        panel.SetSizer(sizer)
        dialogo.SetEscapeId(wx.ID_NO)
        dialogo.SetAffirmativeId(wx.ID_YES)

        # El foco inicial va al cuadro de novedades (no al botón) para que la
        # persona usuaria pueda leerlas de inmediato con las flechas arriba y
        # abajo; al presionar Tab pasa a Aceptar y luego a Más tarde.
        cuadro.SetFocus()
        respuesta = dialogo.ShowModal()
        dialogo.Destroy()

        if respuesta == wx.ID_YES:
            self._revision_motor_arranque_pendiente = False
            self._descargar_actualizacion_programa(info)
        elif continuar_motor_despues:
            self._continuar_revision_motor_post_programa()

    def _descargar_actualizacion_programa(self, info):
        try:
            self.SetStatusText("Descargando actualización del programa")
            self.estado.SetValue(traducir_dinamico("Descargando actualización del programa"))
        except Exception:
            pass
        hablar_async("Descargando actualización del programa", limpiar=True)
        hilo = threading.Thread(target=self._descargar_actualizacion_programa_hilo, args=(info,), daemon=True)
        hilo.start()

    def _descargar_actualizacion_programa_hilo(self, info):
        limpiar_carpeta_temporal_actualizador()
        destino = carpeta_temporal_actualizador() / "descarga"

        def progreso(porcentaje):
            mensaje = traducir_formato("Descargando actualización {porcentaje} por ciento", porcentaje=porcentaje)
            wx.CallAfter(self.SetStatusText, mensaje)
            wx.CallAfter(self.estado.SetValue, traducir_dinamico(mensaje))
            if porcentaje in (25, 50, 75, 100):
                wx.CallAfter(hablar_async, mensaje, False)

        try:
            ruta = descargar_actualizacion(info, destino, callback=progreso)
            wx.CallAfter(self._preguntar_aplicar_actualizacion_programa, info, ruta)
        except Exception as exc:
            wx.CallAfter(
                self._mostrar_error_detallado,
                "No se pudo descargar la actualización",
                "No se pudo descargar la actualización. Verifique su conexión a Internet e inténtelo nuevamente.\n\n" + str(exc),
                "Error descargando actualización",
            )

    def _preguntar_aplicar_actualizacion_programa(self, info, ruta):
        mensaje = (
            "La actualización está lista para instalarse.\n\n"
            "El programa se cerrará por unos momentos para aplicar los cambios y se abrirá nuevamente de forma automática.\n\n"
            "Por favor, no cierre ni apague el equipo durante este proceso."
        )
        hablar_async("Actualización descargada correctamente", limpiar=True)
        respuesta = wx.MessageBox(
            mensaje,
            "Actualización descargada correctamente",
            wx.OK | wx.CANCEL | wx.ICON_INFORMATION,
        )
        if respuesta != wx.OK:
            self._mostrar_mensaje_accesible(
                "Actualización pendiente",
                traducir_formato("La actualización quedó descargada en:\n{ruta}", ruta=ruta),
                wx.ICON_INFORMATION,
                "Actualización pendiente",
                False,
            )
            return

        try:
            script = crear_script_aplicacion(ruta, info.version)
        except Exception as exc:
            self._mostrar_mensaje_accesible(
                "Actualización descargada correctamente",
                traducir_formato(
                    "La actualización se descargó correctamente, pero no se pudo iniciar la instalación automática.\n\nArchivo descargado:\n{ruta}\n\nDetalle:\n{detalle}",
                    ruta=ruta,
                    detalle=exc,
                ),
                wx.ICON_WARNING,
                "Actualización descargada",
                True,
            )
            return

        self._mostrar_mensaje_accesible(
            "Aplicando actualización",
            "El programa se va a cerrar para aplicar los cambios. Se abrirá nuevamente cuando termine la actualización.",
            wx.ICON_INFORMATION,
            "Aplicando actualización",
            False,
        )
        try:
            ejecutar_script_y_salir(script)
            self.Close()
        except Exception as exc:
            self._mostrar_error_detallado(
                "No se pudo aplicar la actualización",
                "No se pudo iniciar el instalador de la actualización.\n\n" + str(exc),
                "Error aplicando actualización",
            )

    def actualizar_ytdlp(self, evento=None, silencioso=False):
        self.agregar_log("Actualizando librería de descarga...")
        self.estado.SetValue("Actualizando librería de descarga")
        self.SetStatusText("Actualizando librería de descarga")
        if not silencioso:
            hablar_async("Comprobando actualización de la librería de descarga", limpiar=True)

        hilo = threading.Thread(target=self._actualizar_ytdlp_hilo, args=(silencioso,), daemon=True)
        hilo.start()

    def _actualizar_ytdlp_hilo(self, silencioso=False):
        def callback(mensaje):
            wx.CallAfter(self.estado.SetValue, mensaje)
            wx.CallAfter(self.SetStatusText, mensaje)
            wx.CallAfter(self.agregar_log, mensaje)
            if not silencioso:
                wx.CallAfter(hablar_async, mensaje, True)

        try:
            canal_deseado = normalizar_canal_motor(self.configuracion.get("canal_actualizaciones_motor", "stable"))
            canal_instalado = normalizar_canal_motor(self.configuracion.get("canal_motor_instalado", "stable"))
            version_instalada = version_instalada_actual()
            version_nueva = version_mas_reciente_disponible(canal_deseado)
            cambio_canal = canal_deseado != canal_instalado

            if version_instalada and version_nueva and not cambio_canal and not es_version_mayor(version_nueva, version_instalada):
                mensaje = traducir_formato(
                    "Ya tiene instalada la última versión disponible de la librería de descarga. Versión instalada: {version}. Canal: {canal}.",
                    version=version_instalada,
                    canal=_etiqueta_canal_motor(canal_deseado),
                )
                wx.CallAfter(self.estado.SetValue, "Librería de descarga actualizada")
                wx.CallAfter(self.SetStatusText, "No hay actualizaciones de la librería de descarga")
                wx.CallAfter(self.agregar_log, mensaje)
                if not silencioso:
                    wx.CallAfter(hablar_async, mensaje, True)
                    wx.CallAfter(wx.MessageBox, mensaje, "Sin actualizaciones", wx.OK | wx.ICON_INFORMATION)
                return
            if not version_nueva:
                raise RuntimeError("No se pudo comprobar la versión más reciente de la librería de descarga. Revise su conexión a Internet y vuelva a intentarlo.")

            if cambio_canal:
                callback(
                    traducir_formato(
                        "Cambiando canal del motor de {actual} a {nuevo}.",
                        actual=_etiqueta_canal_motor(canal_instalado),
                        nuevo=_etiqueta_canal_motor(canal_deseado),
                    )
                )

            resultado = actualizar_motor_descarga(callback=callback, canal=canal_deseado)
            ruta = resultado.get("ruta", "")
            version = resultado.get("version", "")
            canal_resultado = normalizar_canal_motor(resultado.get("canal", canal_deseado))
            self.configuracion["canal_motor_instalado"] = canal_resultado
            wx.CallAfter(self.guardar_configuracion)
            mensaje = traducir_formato(
                "Motor de descarga actualizado correctamente. Versión instalada: {version}. Canal: {canal}.",
                version=version,
                canal=_etiqueta_canal_motor(canal_resultado),
            )
            wx.CallAfter(self.estado.SetValue, "Motor actualizado")
            wx.CallAfter(self.SetStatusText, "Motor de descarga actualizado")
            wx.CallAfter(self.agregar_log, f"Motor de descarga actualizado correctamente: {version} - canal {canal_resultado} - {ruta}")
            if not silencioso:
                wx.CallAfter(hablar_async, mensaje, True)
                wx.CallAfter(
                    wx.MessageBox,
                    mensaje,
                    "Actualización completada",
                    wx.OK | wx.ICON_INFORMATION,
                )
        except Exception as e:
            detalle = str(e)
            wx.CallAfter(self.estado.SetValue, traducir_dinamico("Error"))
            wx.CallAfter(self.SetStatusText, "Error actualizando librería de descarga")
            wx.CallAfter(self.agregar_log, f"Error actualizando librería de descarga: {detalle}")
            wx.CallAfter(self._mostrar_error_detallado, "Error actualizando librería de descarga", detalle)

    def ver_version_ytdlp(self, evento=None):
        try:
            texto = diagnostico_motor_descarga()
            self.agregar_log("Versión de la librería de descarga consultada")
            dialogo = wx.Dialog(self, title="Versión de la librería de descarga", size=(620, 360))
            panel = wx.Panel(dialogo)
            sizer = wx.BoxSizer(wx.VERTICAL)

            cuadro = wx.TextCtrl(panel, value=texto, style=wx.TE_MULTILINE | wx.TE_READONLY)
            cuadro.SetName("Versión de la librería de descarga")
            sizer.Add(cuadro, 1, wx.EXPAND | wx.ALL, 10)

            btn = wx.Button(panel, wx.ID_OK, label="Aceptar")
            btn.SetName("Aceptar versión del motor")
            sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

            panel.SetSizer(sizer)
            btn.SetFocus()
            dialogo.ShowModal()
            dialogo.Destroy()
        except Exception as e:
            self._mostrar_error_detallado("Error", f"No fue posible obtener la versión del motor de descarga.\n\n{e}")

    def agregar_log(self, texto):
        try:
            if getattr(self, "log", None) is not None:
                self.log.AppendText("\n" + str(texto))
        except Exception:
            pass

        try:
            LOG_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)

            with open(LOG_ARCHIVO, "a", encoding="utf-8") as archivo:
                archivo.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {texto}\n")
        except Exception:
            pass

    def _anunciar(self, texto, limpiar=False, actualizar_estado=True):
        texto = traducir_dinamico(str(texto or "").strip())

        if not texto:
            return

        try:
            self.SetStatusText(texto)
        except Exception:
            pass

        if actualizar_estado:
            try:
                self.estado.SetValue(texto)
            except Exception:
                pass

        _hablar_async_original(texto, limpiar=limpiar)

    def _mostrar_mensaje_accesible(
        self,
        titulo,
        mensaje,
        icono=wx.ICON_INFORMATION,
        estado=None,
        registrar=True,
        enfocar_control=None,
    ):
        """Muestra un aviso con botón Aceptar y lo anuncia primero por NVDA/voz accesible."""
        titulo = traducir_dinamico(str(titulo or "Aviso").strip())
        mensaje = traducir_dinamico(str(mensaje or "").strip())

        if not mensaje:
            mensaje = traducir_dinamico("Ocurrió una situación que requiere atención.")

        estado_traducido = traducir_dinamico(estado) if estado else None

        try:
            if estado_traducido:
                self.estado.SetValue(str(estado_traducido))
                self.SetStatusText(str(estado_traducido))
            else:
                self.SetStatusText(mensaje)
        except Exception:
            pass

        if registrar:
            self.agregar_log(mensaje)

        # Se anuncia antes de abrir el cuadro para que NVDA no pierda el mensaje.
        if icono == wx.ICON_ERROR:
            self._sonido("error", esperar=False)
        self._anunciar(f"{titulo}. {mensaje}", limpiar=True, actualizar_estado=False)

        wx.MessageBox(mensaje, titulo, wx.OK | icono)

        if enfocar_control is not None:
            try:
                enfocar_control.SetFocus()
            except Exception:
                pass

    def _mostrar_error_detallado(self, titulo, error, estado="Error"):
        detalle = str(error or "").strip()
        if not detalle:
            detalle = "No se pudo completar la operación."

        self._mostrar_mensaje_accesible(
            titulo,
            detalle,
            icono=wx.ICON_ERROR,
            estado=estado,
            registrar=True,
        )

    def _set_estado_busqueda(self, texto):
        try:
            texto = traducir_dinamico(texto)
            self.estado_busqueda.SetLabel(f"{traducir('Estado')}: {texto}")
            self.panel_busqueda.Layout()
        except Exception:
            pass

    def _ocultar_resultados_busqueda(self):
        self.resultados_busqueda = []
        self.lista_resultados.DeleteAllItems()
        self.lista_resultados.Disable()
        self.btn_limpiar_busqueda.Disable()
        self.panel_resultados_busqueda.Hide()
        self.panel_busqueda.Layout()

    def validar_campos(self):
        url = self.campo_url.GetValue().strip()
        carpeta = self.carpeta.GetValue().strip()

        if not url:
            self._mostrar_mensaje_accesible("Falta URL", "Debe ingresar una URL.", wx.ICON_INFORMATION, enfocar_control=self.campo_url)
            self.enfocar_url()
            return None

        if not carpeta:
            self._mostrar_mensaje_accesible("Falta carpeta", "Debe seleccionar una carpeta de destino.", wx.ICON_INFORMATION, enfocar_control=self.carpeta)
            self.notebook.SetSelection(0)
            self.carpeta.SetFocus()
            return None

        return url, carpeta

    def validar_carpeta_descarga(self):
        carpeta = self.carpeta.GetValue().strip()

        if not carpeta:
            self._mostrar_mensaje_accesible("Falta carpeta", "Debe seleccionar una carpeta de destino.", wx.ICON_INFORMATION, enfocar_control=self.carpeta)
            self.notebook.SetSelection(0)
            self.carpeta.SetFocus()
            return None

        return carpeta

    def _mostrar_error_autenticacion_youtube(self, error):
        mensaje = str(error)
        metodo_auth = str(self.configuracion.get("youtube_metodo_autenticacion", "ninguno") or "ninguno")
        if metodo_auth == "ninguno":
            mensaje += (
                "\n\nPuede configurar un archivo cookies.txt desde Herramientas, Opciones, "
                "Autenticación de YouTube. Es el método recomendado en Windows."
            )
        elif metodo_auth == "navegador" and "DPAPI" in mensaje.upper():
            mensaje += (
                "\n\nLa lectura directa de cookies del navegador fue bloqueada por Windows. "
                "Seleccione Archivo cookies.txt en Herramientas, Opciones y vuelva a intentarlo."
            )
        self.estado.SetValue("Bloqueado por YouTube")
        self._set_estado_busqueda("Bloqueado por YouTube")
        try:
            self._set_estado_colecciones("Bloqueado por YouTube")
        except Exception:
            pass
        self._mostrar_mensaje_accesible(
            "YouTube bloqueó la solicitud",
            mensaje,
            icono=wx.ICON_INFORMATION,
            estado="YouTube bloqueó la solicitud automática",
            registrar=True,
        )

    def obtener_informacion(self, evento=None):
        url = self.campo_url.GetValue().strip()
        if not url:
            self._mostrar_mensaje_accesible("Falta URL", "Debe ingresar una URL.", wx.ICON_INFORMATION, enfocar_control=self.campo_url)
            self.enfocar_url()
            return
        if self._es_url_playlist_youtube(url):
            self._preparar_playlist_directa(self._coleccion_playlist_desde_url(url), "info")
            return
        self._solicitar_informacion_url(url, volver_busqueda=False)

    def _solicitar_informacion_url(self, url, volver_busqueda=False, info_respaldo=None):
        self.estado.SetValue("Obteniendo información")
        self.agregar_log("Obteniendo información del video...")

        if volver_busqueda:
            self._set_estado_busqueda("Obteniendo información del resultado seleccionado")

        hablar_async("Obteniendo información del video")
        self.btn_info.Enable(False)

        hilo = threading.Thread(
            target=self._obtener_informacion_hilo,
            args=(url, volver_busqueda, info_respaldo),
            daemon=True,
        )
        hilo.start()

    def _obtener_informacion_hilo(self, url, volver_busqueda=False, info_respaldo=None):
        try:
            info = self.descargador.obtener_informacion(url)
            wx.CallAfter(self._mostrar_info_dialogo_y_actualizar, info, volver_busqueda, False)
            hablar_async(f"Título {info['titulo']}")
        except ErrorAutenticacionYoutube as e:
            if info_respaldo:
                info_respaldo = dict(info_respaldo)
                info_respaldo["nota"] = "Información parcial tomada del resultado de búsqueda. YouTube no permitió recuperar todos los datos en este momento."
                wx.CallAfter(self._mostrar_info_dialogo_y_actualizar, info_respaldo, volver_busqueda, True)
            else:
                wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
        except Exception as e:
            if info_respaldo:
                info_respaldo = dict(info_respaldo)
                info_respaldo["nota"] = "Información parcial tomada del resultado de búsqueda. No se pudo ampliar la información en este momento."
                wx.CallAfter(self._mostrar_info_dialogo_y_actualizar, info_respaldo, volver_busqueda, True)
            else:
                wx.CallAfter(self.estado.SetValue, traducir_dinamico("Error"))
                wx.CallAfter(self.agregar_log, str(e))
                wx.CallAfter(self._mostrar_error_detallado, "Error", "No se pudo obtener la información.")
        finally:
            wx.CallAfter(self.btn_info.Enable, not self.descarga_activa)

    def _texto_info_video(self, info):
        texto = (
            f"{traducir('Título:')} {info.get('titulo', traducir('Sin título'))}\n"
            f"{traducir('Canal:')} {info.get('canal', traducir('No disponible'))}\n"
            f"{traducir('Duración:')} {info.get('duracion_texto', traducir('No disponible'))}\n"
            f"{traducir('Fecha:')} {info.get('fecha_texto', traducir('No disponible'))}\n"
            f"{traducir('Visualizaciones:')} {info.get('visualizaciones_texto', traducir('No disponible'))}\n"
            f"{traducir('URL:')} {info.get('url', '')}"
        )

        if info.get("nota"):
            texto += f"\n\n{traducir('Nota:')} {traducir_dinamico(info.get('nota'))}"

        return texto

    def _registrar_info_video(self, info, estado="Información obtenida"):
        self.info_actual = info
        self.estado.SetValue(estado)
        self.agregar_log(f"Título: {info.get('titulo', 'Sin título')}")

    def _mostrar_info_dialogo_y_actualizar(self, info, volver_busqueda=False, parcial=False):
        estado = "Información parcial" if parcial else "Información obtenida"
        self._registrar_info_video(info, estado=estado)

        if volver_busqueda:
            self._set_estado_busqueda(estado)

        self._mostrar_dialogo_info(info, volver_busqueda=volver_busqueda, parcial=parcial)

    def _mostrar_dialogo_info(self, info, volver_busqueda=False, parcial=False):
        titulo = "Información parcial del video" if parcial else "Información del video"
        dialogo = wx.Dialog(self, title=titulo, size=(680, 420))
        dialogo.SetName(titulo)
        sizer = wx.BoxSizer(wx.VERTICAL)

        texto = wx.TextCtrl(
            dialogo,
            value=self._texto_info_video(info),
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        texto.SetName("Texto con información del video")
        sizer.Add(texto, 1, wx.EXPAND | wx.ALL, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_aceptar = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_aceptar.SetName("Aceptar y volver")
        fila.Add(btn_aceptar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        texto.SetFocus()
        hablar_async("Información abierta. Use Tab para ir al botón Aceptar", limpiar=True)
        dialogo.ShowModal()
        dialogo.Destroy()

        if volver_busqueda:
            self.notebook.SetSelection(1)
            if self.resultados_busqueda:
                indice = self._indice_resultado_seleccionado()
                if indice is not None:
                    self.lista_resultados.Select(indice)
                    self.lista_resultados.Focus(indice)
            self.lista_resultados.SetFocus()

    def iniciar_descarga(self, evento=None):
        url_directa = self.campo_url.GetValue().strip()
        if url_directa and self._es_url_playlist_youtube(url_directa):
            self._mostrar_acciones_playlist_url(url_directa)
            return
        datos = self.validar_campos()
        if not datos:
            return
        url, carpeta = datos
        self._comenzar_descarga(url, carpeta)

    def _comenzar_descarga(self, url, carpeta):
        if self.descarga_activa:
            hablar_async("Ya hay una descarga en curso")
            return

        formato = self.formato.GetStringSelection()
        calidad = self._calidad_seleccionada()

        self.descarga_activa = True
        self.tipo_descarga_activa = "individual"
        self.ultimo_anuncio = -1
        self.ultimo_estado_anunciado = None
        self.ultimo_aviso_descarga_tiempo = 0
        self.gauge.SetValue(0)
        self.progreso.SetValue("0%")
        mensaje_inicio = traducir_formato("Preparando descarga en formato {formato}, calidad {calidad}", formato=formato, calidad=calidad)
        self.estado.SetValue(traducir_dinamico("Preparando descarga"))
        self.SetStatusText(mensaje_inicio)
        self.agregar_log("Iniciando descarga")
        self._actualizar_botones_descarga(True)
        self._anunciar(mensaje_inicio, limpiar=True)

        self.hilo_descarga = threading.Thread(
            target=self._descargar_hilo,
            args=(url, carpeta, formato, calidad),
            daemon=True,
        )
        self.hilo_descarga.start()

    def _descargar_hilo(self, url, carpeta, formato, calidad):
        try:
            info = self.descargador.descargar(
                url,
                carpeta,
                formato,
                calidad,
                callback_progreso=lambda datos: wx.CallAfter(self._actualizar_progreso, datos),
            )

            registro = {
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "titulo": info["titulo"],
                "canal": info["canal"],
                "duracion": info["duracion_texto"],
                "url": url,
                "formato": formato,
                "calidad": calidad,
                "carpeta": carpeta,
            }
            agregar_descarga(registro)

            wx.CallAfter(self._descarga_completada, info)
        except DescargaCancelada:
            wx.CallAfter(self.estado.SetValue, traducir_dinamico("Cancelado"))
            wx.CallAfter(self.SetStatusText, "Descarga cancelada")
            wx.CallAfter(self.agregar_log, "Descarga cancelada por el usuario")
            hablar_async("Descarga cancelada por el usuario", limpiar=True)
        except ErrorAutenticacionYoutube as e:
            wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
        except Exception as e:
            wx.CallAfter(self._mostrar_error_detallado, "Error en la descarga", e)
        finally:
            wx.CallAfter(self._finalizar_descarga_ui)

    def _actualizar_progreso(self, datos):
        porcentaje = int(datos.get("porcentaje", 0))
        mensaje = datos.get("mensaje", f"{porcentaje}%")
        estado = datos.get("estado", "Descargando")
        mensaje_traducido = traducir_dinamico(mensaje)
        estado_traducido = traducir_dinamico(estado)

        self.gauge.SetValue(max(0, min(100, porcentaje)))
        self.progreso.SetValue(mensaje_traducido)
        self.estado.SetValue(estado_traducido)
        self.SetStatusText(mensaje_traducido)

        if estado != self.ultimo_estado_anunciado:
            self.ultimo_estado_anunciado = estado
            if estado == "Preparando":
                self._anunciar("Preparando descarga", limpiar=True, actualizar_estado=False)
            elif estado == "Descargando":
                self._anunciar("Descarga iniciada", limpiar=True, actualizar_estado=False)
            elif estado == "Procesando":
                self._anunciar("Archivo descargado. Procesando conversión", limpiar=True, actualizar_estado=False)
            elif estado == "Convirtiendo":
                self._anunciar("Convirtiendo archivo...", limpiar=True, actualizar_estado=False)
            elif estado == "Completado":
                # El aviso final se emite una sola vez en _descarga_completada.
                # Evita que NVDA diga "Proceso completado" y luego "Descarga completada".
                pass

        bloque = porcentaje // 10

        if porcentaje > 0 and porcentaje < 100 and bloque > self.ultimo_anuncio:
            self.ultimo_anuncio = bloque
            self.ultimo_aviso_descarga_tiempo = time.time()
            self._anunciar(traducir_formato("Descargando {porcentaje} por ciento", porcentaje=bloque * 10), limpiar=False, actualizar_estado=False)
        elif estado == "Descargando" and porcentaje == 0:
            # Algunos videos no entregan tamaño total, por eso no hay porcentaje real.
            # En ese caso se anuncia periódicamente que la descarga sigue activa.
            ahora = time.time()
            if ahora - getattr(self, "ultimo_aviso_descarga_tiempo", 0) >= 15:
                self.ultimo_aviso_descarga_tiempo = ahora
                self._anunciar("Descarga en curso", limpiar=False, actualizar_estado=False)

    def _descarga_completada(self, info):
        titulo = info.get("titulo", "archivo")
        self._registrar_info_video(info, estado="Completado")
        self.gauge.SetValue(100)
        self.progreso.SetValue("100%")
        self.estado.SetValue(traducir_dinamico("Completado"))
        self.SetStatusText(traducir_dinamico("Descarga completada"))
        self._set_estado_busqueda("Puede seguir buscando o limpiar la búsqueda.")
        self.agregar_log(f"Descarga completada: {titulo}")
        self._sonido("descarga_completada", esperar=True)
        mensaje_final = traducir_formato("Descarga completada. {titulo}", titulo=titulo)
        self._anunciar(mensaje_final, limpiar=True, actualizar_estado=False)

    def _finalizar_descarga_ui(self):
        self.descarga_activa = False
        self.tipo_descarga_activa = None
        self._actualizar_botones_descarga(False)

    def cancelar_descarga(self, evento=None):
        if not self.descarga_activa:
            return

        if self.tipo_descarga_activa == "cola":
            self._detener_cola_solicitada = True
        self.descargador.cancelar()
        if self.tipo_descarga_activa == "cola":
            self.estado.SetValue(traducir_dinamico("Deteniendo cola"))
            self.SetStatusText(traducir_dinamico("Deteniendo cola de descargas"))
            self.progreso.SetValue(traducir_dinamico("Deteniendo cola de descargas..."))
            self.agregar_log("Solicitud para detener cola de descargas enviada")
            hablar_async("Deteniendo cola de descargas", limpiar=True)
        else:
            self.estado.SetValue(traducir_dinamico("Cancelando"))
            self.SetStatusText(traducir_dinamico("Cancelando descarga"))
            self.progreso.SetValue(traducir_dinamico("Cancelando descarga..."))
            self.agregar_log("Solicitud de cancelación enviada")
            hablar_async("Cancelando descarga", limpiar=True)

    def iniciar_busqueda(self, evento=None):
        if self.busqueda_activa:
            hablar_async("La búsqueda ya está en curso")
            return

        consulta = self.campo_busqueda.GetValue().strip()

        if not consulta:
            self._mostrar_mensaje_accesible("Falta búsqueda", "Debe escribir algo para buscar.", wx.ICON_INFORMATION, enfocar_control=self.campo_busqueda)
            self.enfocar_busqueda()
            return

        limite = self._pedir_cantidad_resultados()

        if limite is None:
            self.enfocar_busqueda()
            return

        self.busqueda_activa = True
        self._ocultar_resultados_busqueda()
        self._set_estado_busqueda("Buscando")
        self._actualizar_botones_busqueda(True)
        self.SetStatusText(traducir_formato("Buscando {cantidad} resultados en YouTube", cantidad=limite))
        hablar_async(traducir_formato("Buscando {cantidad} resultados en YouTube", cantidad=limite), limpiar=True)

        hilo = threading.Thread(
            target=self._buscar_hilo,
            args=(consulta, limite),
            daemon=True,
        )
        hilo.start()

    def _pedir_cantidad_resultados(self, titulo="Cantidad de resultados", etiqueta="Cantidad de resultados a mostrar:", forzar_pregunta=False):
        if not forzar_pregunta and not bool(self.configuracion.get("busqueda_preguntar_cantidad", False)):
            try:
                return int(self.configuracion.get("busqueda_resultados_predeterminados", "100"))
            except Exception:
                return 100

        dialogo = wx.Dialog(self, title=titulo, size=(380, 190))
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(dialogo, label=etiqueta), 0, wx.ALL, 10)

        combo_cantidad = wx.Choice(dialogo, choices=RESULTADOS_BUSQUEDA_DISPONIBLES)
        predeterminada = str(self.configuracion.get("busqueda_resultados_predeterminados", "100"))
        combo_cantidad.SetSelection(RESULTADOS_BUSQUEDA_DISPONIBLES.index(predeterminada) if predeterminada in RESULTADOS_BUSQUEDA_DISPONIBLES else 0)
        combo_cantidad.SetName(etiqueta.rstrip(":") or "Cantidad de resultados")
        sizer.Add(combo_cantidad, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_aceptar = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(dialogo, wx.ID_CANCEL, label="Cancelar")
        fila.Add(btn_aceptar, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        def aceptar_con_enter(evento):
            codigo = evento.GetKeyCode()
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK)
                return
            evento.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, aceptar_con_enter)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo_cantidad.SetFocus()

        limite = None
        if dialogo.ShowModal() == wx.ID_OK:
            try:
                limite = int(combo_cantidad.GetStringSelection())
            except Exception:
                limite = 100

        dialogo.Destroy()
        return limite

    def _buscar_hilo(self, consulta, limite):
        try:
            resultados = self.descargador.buscar_youtube(
                consulta,
                limite,
            )
            wx.CallAfter(self._mostrar_resultados_busqueda, resultados)
        except ErrorAutenticacionYoutube as e:
            wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
        except Exception as e:
            wx.CallAfter(self._set_estado_busqueda, "Error")
            wx.CallAfter(self._mostrar_error_detallado, "Error buscando en YouTube", e)
        finally:
            wx.CallAfter(self._finalizar_busqueda_ui)

    def _texto_resultado_busqueda(self, valor, tipo="dato"):
        if tipo == "titulo" and valor in (None, "", "Sin título"):
            return traducir("Sin título")
        if valor in (None, "", "No disponible"):
            return traducir("No disponible")
        return str(valor)

    def _mostrar_resultados_busqueda(self, resultados):
        self.resultados_busqueda = resultados or []
        self._metadatos_enriquecidos.clear()
        self._metadatos_en_proceso.clear()
        self.lista_resultados.DeleteAllItems()

        for indice, resultado in enumerate(self.resultados_busqueda):
            item = self.lista_resultados.InsertItem(indice, str(indice + 1))
            self.lista_resultados.SetItem(item, 1, self._texto_resultado_busqueda(resultado.get("titulo"), "titulo"))
            self.lista_resultados.SetItem(item, 2, self._texto_resultado_busqueda(resultado.get("canal")))
            self.lista_resultados.SetItem(item, 3, self._texto_resultado_busqueda(resultado.get("fecha_texto")))
            self.lista_resultados.SetItem(item, 4, self._texto_resultado_busqueda(resultado.get("visualizaciones_texto")))
            self.lista_resultados.SetItem(item, 5, self._texto_resultado_busqueda(resultado.get("duracion_texto")))

        total = len(self.resultados_busqueda)

        if total:
            self.lista_resultados.Enable()
            self.btn_limpiar_busqueda.Enable()
            self.panel_resultados_busqueda.Show()
            self.panel_busqueda.Layout()
            self._set_estado_busqueda(traducir_formato("{total} resultados encontrados. Use flechas y Enter para elegir acción.", total=total))
            self.agregar_log(f"Búsqueda finalizada: {total} resultados encontrados")
            self.lista_resultados.Select(0)
            self.lista_resultados.Focus(0)
            self.lista_resultados.SetFocus()
            hablar_async(traducir_formato("{total} resultados encontrados. Lista lista. Use flechas y Enter para elegir acción. Alt más D descarga. Alt más R reproduce. Alt más I información. Alt más C copia URL. Alt más F agrega o quita de favoritos. Alt más Q agrega a la cola. Alt más L limpia el cuadro de búsqueda", total=total), limpiar=True)
        else:
            self.panel_resultados_busqueda.Hide()
            self.panel_busqueda.Layout()
            self._set_estado_busqueda("Sin resultados")
            self.agregar_log("Búsqueda finalizada: 0 resultados encontrados")
            self.campo_busqueda.SetFocus()
            hablar_async("No se encontraron resultados")

    def _resultado_busqueda_enfocado(self, evento):
        indice = evento.GetIndex() if evento is not None else self.lista_resultados.GetFocusedItem()
        if indice < 0 or indice >= len(self.resultados_busqueda):
            return
        try:
            if self._enriquecimiento_pendiente is not None:
                self._enriquecimiento_pendiente.Stop()
        except Exception:
            pass
        # Esperamos un instante para no consultar cada fila cuando el usuario se desplaza rápidamente.
        self._enriquecimiento_pendiente = wx.CallLater(700, self._iniciar_enriquecimiento_resultado, indice)

    def _iniciar_enriquecimiento_resultado(self, indice):
        if indice < 0 or indice >= len(self.resultados_busqueda):
            return
        if indice in self._metadatos_enriquecidos or indice in self._metadatos_en_proceso:
            return
        if self.lista_resultados.GetFocusedItem() != indice:
            return
        resultado = self.resultados_busqueda[indice]
        faltan = (
            resultado.get("canal") in (None, "", "No disponible", traducir("No disponible"))
            or resultado.get("fecha_texto") in (None, "", "No disponible", traducir("No disponible"))
            or resultado.get("visualizaciones_texto") in (None, "", "No disponible", traducir("No disponible"))
        )
        if not faltan:
            self._metadatos_enriquecidos.add(indice)
            return
        self._metadatos_en_proceso.add(indice)
        threading.Thread(target=self._enriquecer_resultado_hilo, args=(indice,), daemon=True).start()

    def _enriquecer_resultado_hilo(self, indice):
        exito = False
        try:
            base = dict(self.resultados_busqueda[indice])
            completo = self.descargador.completar_metadatos_resultado(base)
            wx.CallAfter(self._aplicar_metadatos_resultado, indice, completo)
            exito = True
        except Exception as exc:
            wx.CallAfter(self.agregar_log, f"No se pudieron completar metadatos del resultado {indice + 1}: {exc}")
        finally:
            wx.CallAfter(self._finalizar_enriquecimiento_resultado, indice, exito)

    def _finalizar_enriquecimiento_resultado(self, indice, exito=False):
        self._metadatos_en_proceso.discard(indice)
        # Si hubo un fallo temporal, permitimos que un futuro enfoque vuelva a intentarlo.
        if exito:
            self._metadatos_enriquecidos.add(indice)

    def _aplicar_metadatos_resultado(self, indice, resultado):
        if indice < 0 or indice >= len(self.resultados_busqueda):
            return
        self.resultados_busqueda[indice] = resultado
        self.lista_resultados.SetItem(indice, 1, self._texto_resultado_busqueda(resultado.get("titulo"), "titulo"))
        self.lista_resultados.SetItem(indice, 2, self._texto_resultado_busqueda(resultado.get("canal")))
        self.lista_resultados.SetItem(indice, 3, self._texto_resultado_busqueda(resultado.get("fecha_texto")))
        self.lista_resultados.SetItem(indice, 4, self._texto_resultado_busqueda(resultado.get("visualizaciones_texto")))
        self.lista_resultados.SetItem(indice, 5, self._texto_resultado_busqueda(resultado.get("duracion_texto")))

    def _finalizar_busqueda_ui(self):
        self.busqueda_activa = False
        self._actualizar_botones_busqueda(False)

    def limpiar_busqueda(self, evento=None):
        self.campo_busqueda.SetValue("")
        self._ocultar_resultados_busqueda()
        self._set_estado_busqueda("Listo para una nueva búsqueda")
        self.campo_busqueda.SetFocus()
        hablar_async("Búsqueda limpiada")

    def _indice_resultado_seleccionado(self):
        indice = self.lista_resultados.GetFirstSelected()

        if indice == -1:
            if self.resultados_busqueda:
                indice = 0
                self.lista_resultados.Select(0)
            else:
                return None

        if indice < 0 or indice >= len(self.resultados_busqueda):
            return None

        return indice

    def _resultado_seleccionado(self):
        indice = self._indice_resultado_seleccionado()

        if indice is None:
            hablar_async("No hay resultado seleccionado")
            return None

        return self.resultados_busqueda[indice]

    def acciones_resultado_enter(self, evento=None):
        if self.notebook.GetSelection() != 1:
            if evento:
                try:
                    evento.Skip()
                except Exception:
                    pass
            return

        resultado = self._resultado_seleccionado()

        if not resultado:
            return

        es_favorito = esta_en_favoritos(resultado.get("url", ""))
        etiqueta_favorito = "Quitar de favoritos (Alt+F)" if es_favorito else "Agregar a favoritos (Alt+F)"
        opciones = [
            (traducir("Descargar (Alt+D)"), "Descargar"),
            (traducir("Información (Alt+I)"), "Información"),
            (traducir("Reproducir (Alt+R)"), "Reproducir"),
            (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
            (traducir(etiqueta_favorito), "Favorito"),
            (traducir("Agregar a la cola de descargas (Alt+Q)"), "Cola"),
        ]
        dialogo = wx.Dialog(self, title="Acción del resultado", size=(470, 205))
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(dialogo, label="Seleccione una acción. Alt+D descarga. Alt+R reproduce. Alt+I información. Alt+C copia URL. Alt+F agrega o quita de favoritos. Alt+Q agrega a la cola."), 0, wx.ALL, 10)
        combo_acciones = wx.Choice(dialogo, choices=[etiqueta for etiqueta, accion in opciones])
        combo_acciones.SetSelection(0)
        sizer.Add(combo_acciones, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_aceptar = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(dialogo, wx.ID_CANCEL, label="Cancelar")
        fila.Add(btn_aceptar, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        accion_directa = {"valor": None}

        def aceptar_accion_con_enter(evento):
            codigo = evento.GetKeyCode()
            if evento.AltDown() and codigo in (ord("D"), ord("d")):
                accion_directa["valor"] = "Descargar"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("R"), ord("r")):
                accion_directa["valor"] = "Reproducir"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("I"), ord("i")):
                accion_directa["valor"] = "Información"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("C"), ord("c")):
                accion_directa["valor"] = "Copiar URL"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("F"), ord("f")):
                accion_directa["valor"] = "Favorito"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("Q"), ord("q")):
                accion_directa["valor"] = "Cola"
                dialogo.EndModal(wx.ID_OK)
                return
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK)
                return
            evento.Skip()

        combo_acciones.SetName("Acción para el resultado seleccionado. Alt más D descarga. Alt más R reproduce. Alt más I información. Alt más C copia URL. Alt más F agrega o quita de favoritos. Alt más Q agrega a la cola")
        btn_aceptar.SetName("Aceptar acción")
        btn_cancelar.SetName("Cancelar acción")
        dialogo.Bind(wx.EVT_CHAR_HOOK, aceptar_accion_con_enter)
        combo_acciones.Bind(wx.EVT_KEY_DOWN, aceptar_accion_con_enter)

        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo_acciones.SetFocus()
        hablar_async("Elija una acción. Descargar, Alt más D. Reproducir, Alt más R. Información, Alt más I. Copiar URL, Alt más C. Favoritos, Alt más F. Cola, Alt más Q", limpiar=True)

        accion = None
        if dialogo.ShowModal() == wx.ID_OK:
            if accion_directa["valor"]:
                accion = accion_directa["valor"]
            else:
                seleccion = combo_acciones.GetSelection()
                accion = opciones[seleccion][1] if 0 <= seleccion < len(opciones) else None

        dialogo.Destroy()
        self.notebook.SetSelection(1)
        self.lista_resultados.SetFocus()

        if accion and accion not in {"Favorito", "Cola"}:
            hablar_async(f"Acción seleccionada: {accion}")

        if accion == "Descargar":
            self.descargar_resultado()
        elif accion == "Información":
            self.informacion_resultado()
        elif accion == "Reproducir":
            self.reproducir_resultado()
        elif accion == "Copiar URL":
            self.copiar_url_resultado()
        elif accion == "Favorito":
            self._alternar_favorito_item(resultado)
        elif accion == "Cola":
            self._agregar_cola_item(resultado)

    def _atajos_resultados_busqueda(self, evento):
        codigo = evento.GetKeyCode()
        foco = wx.Window.FindFocus()
        pagina = self.notebook.GetSelection()

        if evento.AltDown() and codigo in (ord("1"), wx.WXK_NUMPAD1):
            self.ir_pestana_1()
            return
        if evento.AltDown() and codigo in (ord("2"), wx.WXK_NUMPAD2):
            self.ir_pestana_2()
            return
        if evento.AltDown() and codigo in (ord("3"), wx.WXK_NUMPAD3):
            self.ir_pestana_3()
            return
        if evento.AltDown() and codigo in (ord("D"), ord("d")):
            self.descargar_enfocado_actual()
            return
        if evento.AltDown() and codigo in (ord("R"), ord("r")):
            self.reproducir_actual()
            return
        if evento.AltDown() and codigo in (ord("I"), ord("i")):
            self.informacion_enfocada_actual()
            return
        if evento.AltDown() and codigo in (ord("C"), ord("c")):
            self.copiar_url_enfocada_actual()
            return
        if evento.AltDown() and codigo in (ord("F"), ord("f")):
            self.alternar_favorito_enfocado()
            return
        if evento.AltDown() and codigo in (ord("Q"), ord("q")):
            self.agregar_cola_enfocado()
            return
        if evento.AltDown() and codigo in (ord("L"), ord("l")):
            self.limpiar_busqueda_actual()
            return
        if evento.ControlDown() and evento.ShiftDown() and codigo in (ord("D"), ord("d")):
            self.descargar_marcados_actual()
            return

        if pagina == 0:
            if foco == self.campo_url and codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._accion_url_enter()
                return
            evento.Skip()
            return

        if pagina == 1:
            if foco == self.campo_busqueda:
                if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                    self.iniciar_busqueda()
                    return
                evento.Skip()
                return

            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self.acciones_resultado_enter()
                return

            evento.Skip()
            return

        if pagina == 2:
            if foco == self.campo_busqueda_coleccion:
                if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                    self.iniciar_busqueda_coleccion()
                    return
                evento.Skip()
                return

            if foco == self.lista_colecciones:
                if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                    self.acciones_coleccion_enter()
                    return
                evento.Skip()
                return

            if foco == self.lista_videos_coleccion:
                if codigo in (ord(" "),):
                    self.alternar_marca_video_coleccion()
                    return
                if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                    self.acciones_video_coleccion_enter()
                    return
                evento.Skip()
                return

            evento.Skip()
            return

        evento.Skip()

    def descargar_actual(self, evento=None):
        # Compatibilidad interna: descargar ahora siempre significa descargar el elemento enfocado.
        self.descargar_enfocado_actual(evento)

    def descargar_enfocado_actual(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 1:
            self.descargar_resultado()
        elif pagina == 2:
            self.descargar_video_coleccion()
        else:
            self.iniciar_descarga()

    def informacion_enfocada_actual(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 0:
            self.obtener_informacion()
        elif pagina == 1:
            self.informacion_resultado()
        elif pagina == 2:
            foco = wx.Window.FindFocus()
            if foco == self.lista_colecciones or (self.panel_resultados_colecciones.IsShown() and not self.panel_videos_coleccion.IsShown()):
                self.informacion_coleccion()
            elif foco == self.lista_videos_coleccion or self.panel_videos_coleccion.IsShown():
                self.informacion_video_coleccion()
            else:
                hablar_async("Seleccione un canal, lista o video primero")

    def copiar_url_enfocada_actual(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 0:
            url = self.campo_url.GetValue().strip()
            if not url:
                hablar_async("No hay URL para copiar")
                self.campo_url.SetFocus()
                return
            try:
                if wx.TheClipboard.Open():
                    wx.TheClipboard.SetData(wx.TextDataObject(url))
                    wx.TheClipboard.Close()
                    self.SetStatusText("URL copiada al portapapeles")
                    hablar_async("URL copiada")
            except Exception:
                try:
                    wx.TheClipboard.Close()
                except Exception:
                    pass
                self._mostrar_error_detallado("Error", "No se pudo copiar la URL.")
        elif pagina == 1:
            self.copiar_url_resultado()
        elif pagina == 2:
            foco = wx.Window.FindFocus()
            if foco == self.lista_colecciones or (self.panel_resultados_colecciones.IsShown() and not self.panel_videos_coleccion.IsShown()):
                self.copiar_url_coleccion()
            elif foco == self.lista_videos_coleccion or self.panel_videos_coleccion.IsShown():
                self.copiar_url_video_coleccion()
            else:
                hablar_async("Seleccione un canal, lista o video primero")

    def _alternar_favorito_item(self, item):
        if not isinstance(item, dict):
            hablar_async("No hay un elemento seleccionado para favoritos", limpiar=True)
            return
        url = str(item.get("url") or "").strip()
        if not url:
            self._mostrar_mensaje_accesible(
                "Favoritos",
                "El elemento seleccionado no tiene una dirección disponible y no puede guardarse en favoritos.",
                wx.ICON_INFORMATION,
            )
            return

        datos = dict(item)
        if not datos.get("tipo_favorito"):
            tipo_clave = str(datos.get("tipo_clave") or "").lower()
            datos["tipo_favorito"] = "Playlist" if tipo_clave == "playlist" else ("Canal" if tipo_clave == "canal" else "Video")
        resultado = alternar_favorito(datos)
        if resultado == "agregado":
            self.SetStatusText(traducir("Se agregó a tus favoritos."))
            hablar_async("Se agregó a tus favoritos.", limpiar=True)
        elif resultado == "quitado":
            self.SetStatusText(traducir("Se quitó de tus favoritos."))
            hablar_async("Se quitó de tus favoritos.", limpiar=True)
        else:
            self._mostrar_error_detallado("Favoritos", "No se pudo actualizar la lista de favoritos.")

    def alternar_favorito_enfocado(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 1:
            item = self._resultado_seleccionado()
            if item:
                self._alternar_favorito_item(item)
            return

        if pagina == 2:
            foco = wx.Window.FindFocus()
            if foco == self.lista_videos_coleccion or self.panel_videos_coleccion.IsShown():
                item = self._video_enfocado_coleccion()
                if item:
                    self._alternar_favorito_item(item)
                return
            if foco == self.lista_colecciones or self.panel_resultados_colecciones.IsShown():
                coleccion = self._coleccion_seleccionada()
                if coleccion and str(coleccion.get("tipo_clave") or "").lower() == "playlist":
                    self._alternar_favorito_coleccion(coleccion)
                    return
            hablar_async("Seleccione primero un video o una playlist para agregarlo a favoritos", limpiar=True)
            return

        hablar_async("Para usar favoritos, seleccione primero un video en Buscar en YouTube o en Canales y listas", limpiar=True)

    def _agregar_cola_item(self, item):
        if not isinstance(item, dict):
            hablar_async("No hay un video seleccionado para agregar a la cola", limpiar=True)
            return
        url = str(item.get("url") or "").strip()
        if not url:
            self._mostrar_mensaje_accesible(
                "Cola de descargas",
                "El video seleccionado no tiene una dirección disponible y no puede agregarse a la cola.",
                wx.ICON_INFORMATION,
            )
            return
        resultado = agregar_a_cola(dict(item))
        if resultado == "agregado":
            self.SetStatusText(traducir("Se agregó a la cola de descargas."))
            hablar_async("Se agregó a la cola de descargas.", limpiar=True)
        elif resultado == "duplicado":
            self.SetStatusText(traducir("Este elemento ya está en la cola de descargas."))
            hablar_async("Este elemento ya está en la cola de descargas.", limpiar=True)
        else:
            self._mostrar_error_detallado("Cola de descargas", "No se pudo agregar el elemento a la cola de descargas.")

    def agregar_cola_enfocado(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 1:
            item = self._resultado_seleccionado()
            if item:
                self._agregar_cola_item(item)
            return
        if pagina == 2:
            foco = wx.Window.FindFocus()
            if foco == self.lista_videos_coleccion or self.panel_videos_coleccion.IsShown():
                if self.videos_marcados:
                    self.agregar_marcados_cola()
                else:
                    item = self._video_enfocado_coleccion()
                    if item:
                        self._agregar_cola_item(item)
                return
            if foco == self.lista_colecciones or self.panel_resultados_colecciones.IsShown():
                coleccion = self._coleccion_seleccionada()
                if coleccion and str(coleccion.get("tipo_clave") or "").lower() == "playlist":
                    self.agregar_playlist_completa_cola(coleccion)
                    return
            hablar_async("Seleccione primero un video o una playlist para agregarlo a la cola", limpiar=True)
            return
        hablar_async("Para agregar a la cola, seleccione primero un video en Buscar en YouTube o en Canales y listas", limpiar=True)

    def agregar_marcados_cola(self, evento=None):
        if self.notebook.GetSelection() != 2 or not self.panel_videos_coleccion.IsShown():
            hablar_async("Esta opción está disponible en la lista de videos de Canales y listas.", limpiar=True)
            return
        if not self.videos_marcados:
            hablar_async("No hay videos marcados para agregar a la cola.", limpiar=True)
            return
        videos = [self.videos_coleccion[i] for i in sorted(self.videos_marcados) if 0 <= i < len(self.videos_coleccion)]
        self._agregar_varios_cola_y_anunciar(videos)

    def _copiar_url_favorito(self, favorito):
        url = str((favorito or {}).get("url") or "").strip()
        if not url:
            hablar_async("El favorito no tiene URL disponible", limpiar=True)
            return
        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Close()
                hablar_async("URL copiada", limpiar=True)
        except Exception:
            try:
                wx.TheClipboard.Close()
            except Exception:
                pass
            self._mostrar_error_detallado("Error", "No se pudo copiar la URL.")

    def _informacion_favorito(self, favorito):
        favorito = favorito or {}
        partes = [
            f"{traducir('Título:')} {favorito.get('titulo') or traducir('Sin título')}",
            f"{traducir('Canal:')} {favorito.get('canal') or traducir('No disponible')}",
            f"{traducir('Tipo:')} {traducir(favorito.get('tipo') or 'Video')}",
        ]
        if favorito.get("fecha_publicacion_texto"):
            partes.append(f"{traducir('Publicado:')} {favorito.get('fecha_publicacion_texto')}")
        if favorito.get("visualizaciones_texto"):
            partes.append(f"{traducir('Visualizaciones:')} {favorito.get('visualizaciones_texto')}")
        if favorito.get("duracion_texto"):
            partes.append(f"{traducir('Duración:')} {favorito.get('duracion_texto')}")
        if favorito.get("fecha_agregado"):
            partes.append(f"{traducir('Agregado a favoritos:')} {favorito.get('fecha_agregado')}")
        self._mostrar_texto_dialogo(
            traducir("Información del favorito"),
            "\n".join(partes),
            traducir("Información del favorito"),
        )

    def _reproducir_favorito(self, favorito):
        favorito = favorito or {}
        url = str(favorito.get("url") or "").strip()
        if not url:
            self._mostrar_mensaje_accesible("Sin URL", "El favorito seleccionado no tiene URL.", wx.ICON_INFORMATION)
            return
        try:
            dialogo = DialogoReproductor(self, self.descargador, url, favorito, self.configuracion)
            dialogo.ShowModal()
            dialogo.Destroy()
        except Exception as exc:
            self._mostrar_error_detallado("Error en reproductor", exc)

    def _descargar_favorito(self, favorito):
        favorito = favorito or {}
        url = str(favorito.get("url") or "").strip()
        if not url:
            self._mostrar_mensaje_accesible("Sin URL", "El favorito seleccionado no tiene URL.", wx.ICON_INFORMATION)
            return
        carpeta = self.validar_carpeta_descarga()
        if not carpeta:
            return
        hablar_async("Descarga enviada desde favoritos. Se anunciará el progreso y la finalización", limpiar=True)
        self._comenzar_descarga(url, carpeta)

    def mostrar_favoritos(self, evento=None):
        favoritos = leer_favoritos()
        if not favoritos:
            self._mostrar_mensaje_accesible(
                "Favoritos",
                "Aún no tienes favoritos. Selecciona un video y pulsa Alt+F para agregarlo.",
                wx.ICON_INFORMATION,
            )
            return

        dialogo = wx.Dialog(self, title=traducir("Favoritos"), size=(850, 500))
        sizer = wx.BoxSizer(wx.VERTICAL)
        instrucciones = wx.StaticText(
            dialogo,
            label="Tus favoritos. Enter abre las acciones disponibles para cada elemento. En videos, Alt+D descarga, Alt+R reproduce y Alt+Q agrega a la cola. Alt+I muestra información, Alt+C copia la URL y Alt+F o Suprimir quita el favorito.",
        )
        sizer.Add(instrucciones, 0, wx.EXPAND | wx.ALL, 10)

        lista = wx.ListCtrl(dialogo, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        lista.SetName("Lista de favoritos. Enter abre las acciones disponibles. Alt más F quita de favoritos")
        lista.InsertColumn(0, "", width=45)
        lista.InsertColumn(1, "Título", width=440)
        lista.InsertColumn(2, "Canal", width=220)
        lista.InsertColumn(3, "Tipo", width=100)
        sizer.Add(lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        estado = wx.StaticText(dialogo, label="")
        sizer.Add(estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_acciones = wx.Button(dialogo, label="Abrir acciones")
        btn_quitar = wx.Button(dialogo, label="Quitar de favoritos")
        btn_cerrar = wx.Button(dialogo, wx.ID_CANCEL, label="Cerrar")
        fila.Add(btn_acciones, 0, wx.ALL, 5)
        fila.Add(btn_quitar, 0, wx.ALL, 5)
        fila.Add(btn_cerrar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetEscapeId(wx.ID_CANCEL)

        datos = {"items": list(favoritos)}
        accion_playlist_pendiente = {"accion": None, "coleccion": None}

        def recargar_lista(seleccion=0):
            lista.DeleteAllItems()
            items = datos["items"]
            for indice, fav in enumerate(items):
                fila_idx = lista.InsertItem(indice, str(indice + 1))
                lista.SetItem(fila_idx, 1, str(fav.get("titulo") or traducir("Sin título")))
                lista.SetItem(fila_idx, 2, str(fav.get("canal") or traducir("No disponible")))
                lista.SetItem(fila_idx, 3, traducir(str(fav.get("tipo") or "Video")))
            estado.SetLabel(traducir_formato("{total} favoritos guardados.", total=len(items)))
            if items:
                seleccion = min(max(0, seleccion), len(items) - 1)
                lista.Select(seleccion)
                lista.Focus(seleccion)
                lista.Enable()
                lista.SetFocus()
            else:
                lista.Disable()
                estado.SetLabel(traducir("No hay favoritos guardados."))

        def favorito_actual():
            items = datos["items"]
            if not items:
                return None, None
            indice = lista.GetFirstSelected()
            if indice < 0:
                indice = 0
            if indice < 0 or indice >= len(items):
                return None, None
            return indice, items[indice]

        def quitar_actual(evento=None):
            indice, fav = favorito_actual()
            if fav is None:
                hablar_async("No hay favoritos guardados.", limpiar=True)
                return
            if quitar_favorito(fav.get("url", "")):
                datos["items"].pop(indice)
                hablar_async("Se quitó de tus favoritos.", limpiar=True)
                recargar_lista(max(0, indice - 1 if indice >= len(datos["items"]) else indice))
            else:
                self._mostrar_error_detallado("Favoritos", "No se pudo quitar el favorito.")

        def ejecutar_accion(accion, fav):
            if accion == "Reproducir":
                self._reproducir_favorito(fav)
            elif accion == "Descargar":
                self._descargar_favorito(fav)
            elif accion == "Información":
                self._informacion_favorito(fav)
            elif accion == "Copiar URL":
                self._copiar_url_favorito(fav)
            elif accion == "Quitar de favoritos":
                quitar_actual()
            elif accion == "Agregar a cola":
                self._agregar_cola_item(fav)
            elif accion in {"Ver playlist", "Playlist completa", "Rango playlist"}:
                coleccion = {
                    "tipo": "Lista de reproducción", "tipo_clave": "playlist",
                    "titulo": fav.get("titulo") or "Lista de reproducción",
                    "canal": fav.get("canal") or "No disponible",
                    "autor": fav.get("canal") or "No disponible",
                    "url": fav.get("url") or "",
                    "descripcion": "No disponible",
                }
                mapa_accion = {"Ver playlist": "ver", "Playlist completa": "toda", "Rango playlist": "rango"}
                accion_playlist_pendiente["accion"] = mapa_accion[accion]
                accion_playlist_pendiente["coleccion"] = coleccion
                if dialogo.IsModal():
                    dialogo.EndModal(wx.ID_OK)
            try:
                if datos["items"]:
                    lista.SetFocus()
            except Exception:
                pass

        def abrir_acciones(evento=None):
            _, fav = favorito_actual()
            if fav is None:
                hablar_async("No hay favoritos guardados.", limpiar=True)
                return
            es_playlist = str(fav.get("tipo") or "").lower() == "playlist"
            if es_playlist:
                opciones = [
                    (traducir("Ver contenido de la playlist"), "Ver playlist"),
                    (traducir("Agregar toda la playlist a la cola de descargas"), "Playlist completa"),
                    (traducir("Seleccionar un rango de la playlist"), "Rango playlist"),
                    (traducir("Información (Alt+I)"), "Información"),
                    (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
                    (traducir("Quitar de favoritos (Alt+F)"), "Quitar de favoritos"),
                ]
            else:
                opciones = [
                    (traducir("Reproducir (Alt+R)"), "Reproducir"),
                    (traducir("Descargar (Alt+D)"), "Descargar"),
                    (traducir("Información (Alt+I)"), "Información"),
                    (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
                    (traducir("Quitar de favoritos (Alt+F)"), "Quitar de favoritos"),
                    (traducir("Agregar a la cola de descargas (Alt+Q)"), "Agregar a cola"),
                ]
            dlg_accion = wx.Dialog(dialogo, title=traducir("Acción del favorito"), size=(500, 225))
            sz = wx.BoxSizer(wx.VERTICAL)
            sz.Add(wx.StaticText(dlg_accion, label="Seleccione una acción para el favorito."), 0, wx.ALL, 10)
            combo = wx.Choice(dlg_accion, choices=[x[0] for x in opciones])
            combo.SetSelection(0)
            if es_playlist:
                combo.SetName(traducir("Acción de playlist favorita. Enter confirma. Alt más I información. Alt más C copia URL. Alt más F quita de favoritos"))
            else:
                combo.SetName("Acción del favorito. Alt más R reproduce. Alt más D descarga. Alt más I información. Alt más C copia URL. Alt más F quita de favoritos. Alt más Q agrega a la cola")
            sz.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            botones = wx.BoxSizer(wx.HORIZONTAL)
            botones.Add(wx.Button(dlg_accion, wx.ID_OK, label="Aceptar"), 0, wx.ALL, 5)
            botones.Add(wx.Button(dlg_accion, wx.ID_CANCEL, label="Cancelar"), 0, wx.ALL, 5)
            sz.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
            dlg_accion.SetSizer(sz)
            dlg_accion.SetAffirmativeId(wx.ID_OK)
            dlg_accion.SetEscapeId(wx.ID_CANCEL)
            directo = {"accion": None}

            def tecla_accion(ev):
                codigo = ev.GetKeyCode()
                if ev.AltDown():
                    es_playlist = str(fav.get("tipo") or "").lower() == "playlist"
                    mapa = {
                        ord("I"): "Información", ord("i"): "Información",
                        ord("C"): "Copiar URL", ord("c"): "Copiar URL",
                        ord("F"): "Quitar de favoritos", ord("f"): "Quitar de favoritos",
                    }
                    if not es_playlist:
                        mapa.update({
                            ord("R"): "Reproducir", ord("r"): "Reproducir",
                            ord("D"): "Descargar", ord("d"): "Descargar",
                            ord("Q"): "Agregar a cola", ord("q"): "Agregar a cola",
                        })
                    if codigo in mapa:
                        directo["accion"] = mapa[codigo]
                        dlg_accion.EndModal(wx.ID_OK)
                        return
                if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                    dlg_accion.EndModal(wx.ID_OK)
                    return
                ev.Skip()

            dlg_accion.Bind(wx.EVT_CHAR_HOOK, tecla_accion)
            combo.Bind(wx.EVT_KEY_DOWN, tecla_accion)
            combo.SetFocus()
            if es_playlist:
                hablar_async("Elija una acción para la playlist favorita. Puede ver su contenido, agregarla completa a la cola, seleccionar un rango, consultar información, copiar la URL o quitarla de favoritos.", limpiar=True)
            else:
                hablar_async("Elija una acción para el favorito. Reproducir, descargar, información, copiar URL, quitar de favoritos o agregar a la cola", limpiar=True)
            accion = None
            if dlg_accion.ShowModal() == wx.ID_OK:
                accion = directo["accion"]
                if not accion:
                    sel = combo.GetSelection()
                    accion = opciones[sel][1] if 0 <= sel < len(opciones) else None
            dlg_accion.Destroy()
            if accion:
                ejecutar_accion(accion, fav)

        def tecla_dialogo(ev):
            codigo = ev.GetKeyCode()
            if ev.AltDown():
                _, fav = favorito_actual()
                if fav is not None:
                    es_playlist = str(fav.get("tipo") or "").lower() == "playlist"
                    if not es_playlist and codigo in (ord("D"), ord("d")):
                        ejecutar_accion("Descargar", fav); return
                    if not es_playlist and codigo in (ord("R"), ord("r")):
                        ejecutar_accion("Reproducir", fav); return
                    if codigo in (ord("I"), ord("i")):
                        ejecutar_accion("Información", fav); return
                    if codigo in (ord("C"), ord("c")):
                        ejecutar_accion("Copiar URL", fav); return
                    if codigo in (ord("F"), ord("f")):
                        quitar_actual(); return
                    if not es_playlist and codigo in (ord("Q"), ord("q")):
                        ejecutar_accion("Agregar a cola", fav); return
            if codigo == wx.WXK_DELETE:
                quitar_actual(); return
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and wx.Window.FindFocus() == lista:
                abrir_acciones(); return
            ev.Skip()

        lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, abrir_acciones)
        dialogo.Bind(wx.EVT_CHAR_HOOK, tecla_dialogo)
        lista.Bind(wx.EVT_KEY_DOWN, tecla_dialogo)
        btn_acciones.Bind(wx.EVT_BUTTON, abrir_acciones)
        btn_quitar.Bind(wx.EVT_BUTTON, quitar_actual)
        recargar_lista(0)
        hablar_async(traducir_formato("Favoritos abiertos. {total} elementos guardados.", total=len(datos["items"])), limpiar=True)
        dialogo.ShowModal()
        dialogo.Destroy()
        if accion_playlist_pendiente["accion"] and accion_playlist_pendiente["coleccion"]:
            wx.CallAfter(
                self._ejecutar_accion_playlist,
                accion_playlist_pendiente["coleccion"],
                accion_playlist_pendiente["accion"],
                False,
            )

    def mostrar_cola_descargas(self, evento=None):
        items = leer_cola()
        if not items:
            self._mostrar_mensaje_accesible(
                "Cola de descargas",
                "La cola de descargas está vacía. Seleccione un video y pulse Alt+Q para agregarlo.",
                wx.ICON_INFORMATION,
            )
            return

        dialogo = wx.Dialog(self, title=traducir("Cola de descargas"), size=(900, 520))
        sizer = wx.BoxSizer(wx.VERTICAL)
        instrucciones = wx.StaticText(
            dialogo,
            label="Elementos pendientes de descarga. Iniciar cola descarga los elementos uno por uno usando el formato, la calidad y la carpeta seleccionados actualmente. Suprimir quita el elemento enfocado.",
        )
        sizer.Add(instrucciones, 0, wx.EXPAND | wx.ALL, 10)

        lista = wx.ListCtrl(dialogo, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        lista.SetName("Cola de descargas. Use flechas para recorrer. Suprimir quita el elemento enfocado.")
        lista.InsertColumn(0, "", width=45)
        lista.InsertColumn(1, "Título", width=445)
        lista.InsertColumn(2, "Canal", width=230)
        lista.InsertColumn(3, "Estado", width=130)
        sizer.Add(lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        estado = wx.StaticText(dialogo, label="")
        sizer.Add(estado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_iniciar = wx.Button(dialogo, label="Iniciar cola")
        btn_cancelar_actual = wx.Button(dialogo, label="Cancelar descarga actual")
        btn_detener = wx.Button(dialogo, label="Detener cola")
        btn_quitar = wx.Button(dialogo, label="Quitar de la cola")
        btn_vaciar = wx.Button(dialogo, label="Vaciar cola")
        btn_cerrar = wx.Button(dialogo, wx.ID_CANCEL, label="Cerrar")
        for boton in (btn_iniciar, btn_cancelar_actual, btn_detener, btn_quitar, btn_vaciar, btn_cerrar):
            fila.Add(boton, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetEscapeId(wx.ID_CANCEL)

        datos = {"items": list(items)}

        def cola_activa():
            return bool(self.descarga_activa and self.tipo_descarga_activa == "cola")

        def recargar_lista(seleccion=0):
            datos["items"] = leer_cola()
            lista.DeleteAllItems()
            for indice, item in enumerate(datos["items"]):
                fila_idx = lista.InsertItem(indice, str(indice + 1))
                lista.SetItem(fila_idx, 1, str(item.get("titulo") or traducir("Sin título")))
                lista.SetItem(fila_idx, 2, str(item.get("canal") or traducir("No disponible")))
                lista.SetItem(fila_idx, 3, traducir(str(item.get("estado") or ESTADO_PENDIENTE)))
            total = len(datos["items"])
            estado.SetLabel(traducir_formato("{total} elementos en la cola de descargas.", total=total))
            activa = cola_activa()
            btn_iniciar.Enable(bool(total) and not self.descarga_activa)
            btn_cancelar_actual.Enable(activa)
            btn_detener.Enable(activa)
            btn_quitar.Enable(bool(total) and not activa)
            btn_vaciar.Enable(bool(total) and not activa)
            if total:
                seleccion = min(max(0, seleccion), total - 1)
                lista.Select(seleccion)
                lista.Focus(seleccion)
                lista.Enable()
                lista.SetFocus()
            else:
                lista.Disable()
                estado.SetLabel(traducir("La cola de descargas está vacía."))

        def item_actual():
            if not datos["items"]:
                return None, None
            indice = lista.GetFirstSelected()
            if indice < 0:
                indice = 0
            if indice >= len(datos["items"]):
                return None, None
            return indice, datos["items"][indice]

        def quitar_actual(evento=None):
            if cola_activa():
                hablar_async("No se puede quitar un elemento mientras la cola está en ejecución.", limpiar=True)
                return
            indice, item = item_actual()
            if item is None:
                hablar_async("La cola de descargas está vacía.", limpiar=True)
                return
            if quitar_de_cola(item.get("url", "")):
                hablar_async("Se quitó de la cola de descargas.", limpiar=True)
                recargar_lista(max(0, indice - 1 if indice >= len(datos["items"]) - 1 else indice))
            else:
                self._mostrar_error_detallado("Cola de descargas", "No se pudo quitar el elemento de la cola.")

        def vaciar(evento=None):
            if cola_activa():
                hablar_async("No se puede vaciar la cola mientras está en ejecución.", limpiar=True)
                return
            respuesta = wx.MessageBox(
                traducir("¿Desea eliminar todos los elementos de la cola de descargas?"),
                traducir("Vaciar cola"),
                wx.YES_NO | wx.ICON_QUESTION,
            )
            if respuesta == wx.YES:
                vaciar_cola()
                hablar_async("Cola de descargas vaciada.", limpiar=True)
                recargar_lista(0)

        def iniciar(evento=None):
            if self.descarga_activa:
                hablar_async("Ya hay una descarga en curso.", limpiar=True)
                return
            if not leer_cola():
                hablar_async("La cola de descargas está vacía.", limpiar=True)
                return
            dialogo.EndModal(wx.ID_OK)
            wx.CallAfter(self._comenzar_cola_descargas)

        def cancelar_actual(evento=None):
            if not cola_activa():
                hablar_async("No hay una cola de descargas en ejecución.", limpiar=True)
                return
            self._cancelar_descarga_actual_cola()

        def detener(evento=None):
            if not cola_activa():
                hablar_async("No hay una cola de descargas en ejecución.", limpiar=True)
                return
            self.cancelar_descarga()

        def tecla_dialogo(ev):
            if ev.GetKeyCode() == wx.WXK_DELETE and wx.Window.FindFocus() == lista:
                quitar_actual()
                return
            ev.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, tecla_dialogo)
        lista.Bind(wx.EVT_KEY_DOWN, tecla_dialogo)
        btn_iniciar.Bind(wx.EVT_BUTTON, iniciar)
        btn_cancelar_actual.Bind(wx.EVT_BUTTON, cancelar_actual)
        btn_detener.Bind(wx.EVT_BUTTON, detener)
        btn_quitar.Bind(wx.EVT_BUTTON, quitar_actual)
        btn_vaciar.Bind(wx.EVT_BUTTON, vaciar)
        recargar_lista(0)
        hablar_async(traducir_formato("Cola de descargas abierta. {total} elementos.", total=len(datos["items"])), limpiar=True)
        dialogo.ShowModal()
        dialogo.Destroy()

    def _comenzar_cola_descargas(self):
        if self.descarga_activa:
            hablar_async("Ya hay una descarga en curso.", limpiar=True)
            return
        items = preparar_reintento_errores()
        if not items:
            hablar_async("La cola de descargas está vacía.", limpiar=True)
            return
        carpeta = self.validar_carpeta_descarga()
        if not carpeta:
            return
        formato = self.formato.GetStringSelection()
        calidad = self._calidad_seleccionada()
        total = len(items)
        mensaje = traducir_formato(
            "Se descargarán {total} elementos de la cola en formato {formato}, calidad {calidad}.\n\nCarpeta destino:\n{carpeta}\n\n¿Desea continuar?",
            total=total,
            formato=formato,
            calidad=calidad,
            carpeta=carpeta,
        )
        if wx.MessageBox(mensaje, traducir("Iniciar cola de descargas"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            hablar_async("Inicio de la cola cancelado.", limpiar=True)
            return

        self.descarga_activa = True
        self.tipo_descarga_activa = "cola"
        self._cancelar_item_cola = False
        self._detener_cola_solicitada = False
        self._pausa_autenticacion_cola = False
        self.ultimo_anuncio = -1
        self.ultimo_estado_anunciado = None
        self.gauge.SetValue(0)
        self.progreso.SetValue("0%")
        self.estado.SetValue(traducir("Preparando cola de descargas"))
        self.SetStatusText(traducir_formato("Preparando cola de {total} elementos", total=total))
        self._actualizar_botones_descarga(True)
        hablar_async(traducir_formato("Iniciando cola de descargas. {total} elementos.", total=total), limpiar=True)
        self.hilo_descarga = threading.Thread(
            target=self._descargar_cola_hilo,
            args=(items, carpeta, formato, calidad),
            daemon=True,
        )
        self.hilo_descarga.start()

    def _cancelar_descarga_actual_cola(self):
        if not (self.descarga_activa and self.tipo_descarga_activa == "cola"):
            hablar_async("No hay una descarga de la cola en curso.", limpiar=True)
            return
        self._cancelar_item_cola = True
        self.descargador.cancelar()
        self.SetStatusText(traducir("Cancelando descarga actual de la cola"))
        hablar_async("Cancelando descarga actual. La cola continuará con el siguiente elemento.", limpiar=True)

    def _descargar_cola_hilo(self, items, carpeta, formato, calidad):
        total = len(items)
        completados = 0
        cancelados = 0
        errores = []
        actual = None
        try:
            self.descargador.limpiar_cancelacion()
            for indice, item in enumerate(items, start=1):
                actual = item
                if self.descargador.fue_cancelado():
                    raise DescargaCancelada()
                url = str(item.get("url") or "")
                titulo = str(item.get("titulo") or f"Video {indice}")
                actualizar_estado_cola(url, ESTADO_DESCARGANDO)
                wx.CallAfter(self._inicio_item_cola, indice, total, titulo)

                def callback(datos, indice=indice, total=total):
                    wx.CallAfter(self._actualizar_progreso_cola, indice, total, datos)

                try:
                    info = self.descargador.descargar(url, carpeta, formato, calidad, callback_progreso=callback)
                    completados += 1
                    registro = {
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "titulo": info.get("titulo", titulo),
                        "canal": info.get("canal", item.get("canal", "No disponible")),
                        "duracion": info.get("duracion_texto", item.get("duracion_texto", "No disponible")),
                        "url": url,
                        "formato": formato,
                        "calidad": calidad,
                        "carpeta": carpeta,
                    }
                    agregar_descarga(registro)
                    quitar_de_cola(url)
                    wx.CallAfter(self._item_cola_completado, indice, total)
                    if indice < total:
                        wx.CallAfter(self.SetStatusText, traducir("Pausa breve antes de la siguiente descarga"))
                        for _ in range(30):
                            if self._detener_cola_solicitada or self.descargador.fue_cancelado():
                                break
                            time.sleep(0.1)
                except DescargaCancelada:
                    if self._detener_cola_solicitada:
                        actualizar_estado_cola(url, ESTADO_PENDIENTE)
                        raise
                    if self._cancelar_item_cola:
                        self._cancelar_item_cola = False
                        cancelados += 1
                        quitar_de_cola(url)
                        self.descargador.limpiar_cancelacion()
                        wx.CallAfter(self._item_cola_cancelado, indice, total, titulo)
                        continue
                    actualizar_estado_cola(url, ESTADO_PENDIENTE)
                    raise
                except ErrorAutenticacionYoutube as exc:
                    actualizar_estado_cola(url, ESTADO_PENDIENTE, str(exc))
                    self._pausa_autenticacion_cola = True
                    wx.CallAfter(self._mostrar_pausa_autenticacion_cola, str(exc))
                    raise DescargaCancelada()
                except Exception as exc:
                    actualizar_estado_cola(url, ESTADO_ERROR, str(exc))
                    errores.append(f"{titulo}: {exc}")
                    wx.CallAfter(self._item_cola_error, indice, total, titulo)

            wx.CallAfter(self._cola_descargas_completada, completados, cancelados, total, errores, carpeta)
        except DescargaCancelada:
            if actual:
                actualizar_estado_cola(actual.get("url", ""), ESTADO_PENDIENTE)
            self._cancelar_item_cola = False
            self._detener_cola_solicitada = False
            pendientes = len(leer_cola())
            if self._pausa_autenticacion_cola:
                wx.CallAfter(self.estado.SetValue, traducir("Cola pausada por autenticación de YouTube"))
                wx.CallAfter(self.SetStatusText, traducir("Cola pausada por autenticación de YouTube"))
                wx.CallAfter(self.agregar_log, f"Cola pausada por autenticación. Pendientes: {pendientes}")
            else:
                wx.CallAfter(self.estado.SetValue, traducir("Cola detenida"))
                wx.CallAfter(self.SetStatusText, traducir("Cola de descargas detenida"))
                wx.CallAfter(self.agregar_log, f"Cola de descargas detenida. Pendientes: {pendientes}")
                hablar_async(traducir_formato("Cola de descargas detenida. {total} elementos pendientes.", total=pendientes), limpiar=True)
        finally:
            self._cancelar_item_cola = False
            self._detener_cola_solicitada = False
            self._pausa_autenticacion_cola = False
            wx.CallAfter(self._finalizar_descarga_ui)

    def _mostrar_pausa_autenticacion_cola(self, detalle):
        pendientes = len(leer_cola())
        mensaje = traducir_formato(
            "YouTube requiere verificar la sesión para continuar. La cola se ha pausado y conserva {total} elementos pendientes.\n\n{detalle}\n\nRevise Herramientas, Opciones, Autenticación de YouTube y luego vuelva a iniciar la cola.",
            total=pendientes,
            detalle=str(detalle or ""),
        )
        self._mostrar_mensaje_accesible(
            "Cola pausada por autenticación de YouTube",
            mensaje,
            wx.ICON_INFORMATION,
            estado="Cola pausada por autenticación de YouTube",
            registrar=True,
        )

    def _inicio_item_cola(self, indice, total, titulo):
        self.estado.SetValue(traducir("Descargando"))
        texto = traducir_formato("Descargando {indice} de {total}. {titulo}", indice=indice, total=total, titulo=titulo)
        self.progreso.SetValue(texto)
        self.SetStatusText(texto)
        hablar_async(texto, limpiar=True)

    def _actualizar_progreso_cola(self, indice, total, datos):
        porcentaje = max(0, min(100, int(datos.get("porcentaje", 0) or 0)))
        try:
            total = max(1, int(total))
            indice = max(1, int(indice))
            porcentaje_total = int((((indice - 1) + porcentaje / 100.0) / total) * 100)
        except Exception:
            porcentaje_total = 0
        self.gauge.SetValue(max(0, min(100, porcentaje_total)))
        mensaje = traducir_formato(
            "Descarga {indice} de {total}: {porcentaje} por ciento",
            indice=indice,
            total=total,
            porcentaje=porcentaje,
        )
        self.progreso.SetValue(mensaje)
        self.SetStatusText(mensaje)

    def _item_cola_completado(self, indice, total):
        hablar_async(traducir_formato("Descarga {indice} de {total} completada.", indice=indice, total=total), limpiar=True)

    def _item_cola_cancelado(self, indice, total, titulo):
        hablar_async(
            traducir_formato("Descarga {indice} de {total} cancelada. {titulo}. La cola continuará.", indice=indice, total=total, titulo=titulo),
            limpiar=True,
        )

    def _item_cola_error(self, indice, total, titulo):
        hablar_async(
            traducir_formato("No se pudo completar la descarga {indice} de {total}. {titulo}. La cola continuará.", indice=indice, total=total, titulo=titulo),
            limpiar=True,
        )

    def _cola_descargas_completada(self, completados, cancelados, total, errores, carpeta):
        self.gauge.SetValue(100)
        self.estado.SetValue(traducir("Completado"))
        self.SetStatusText(traducir("Cola de descargas finalizada"))
        self.agregar_log(f"Cola de descargas finalizada: {completados}/{total}. Carpeta: {carpeta}")
        self._sonido("descarga_completada", esperar=True)
        pendientes = len(leer_cola())
        if errores or cancelados:
            hablar_async(
                traducir_formato("Cola finalizada. {completados} completadas, {cancelados} canceladas y {pendientes} pendientes o con error.", completados=completados, cancelados=cancelados, pendientes=pendientes),
                limpiar=True,
            )
        else:
            hablar_async("Todas las descargas de la cola se completaron.", limpiar=True)

    def limpiar_busqueda_actual(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 1:
            self.limpiar_busqueda()
        elif pagina == 2:
            self.limpiar_busqueda_coleccion()
        else:
            self._mostrar_mensaje_accesible(
                "Limpiar cuadro de búsqueda",
                "Alt más L limpia el cuadro de búsqueda en Buscar en YouTube o en Canales y listas.",
                wx.ICON_INFORMATION,
            )

    def descargar_marcados_actual(self, evento=None):
        if self.notebook.GetSelection() == 2:
            self.descargar_videos_marcados()
        else:
            self._mostrar_mensaje_accesible(
                "Descarga múltiple",
                "Para descargar videos marcados, entre a la pestaña Canales y listas, cargue videos y márquelos con Espacio.",
                wx.ICON_INFORMATION,
            )

    def reproducir_actual(self, evento=None):
        pagina = self.notebook.GetSelection()
        if pagina == 1:
            self.reproducir_resultado()
        elif pagina == 2:
            self.reproducir_video_coleccion()
        else:
            self._mostrar_mensaje_accesible(
                "Reproductor",
                "Para reproducir, primero seleccione un resultado de búsqueda o un video dentro de una lista.",
                wx.ICON_INFORMATION,
            )

    def _usar_url_resultado(self, resultado):
        url = resultado.get("url", "").strip()

        if not url:
            hablar_async("El resultado no tiene URL")
            self._mostrar_mensaje_accesible("Sin URL", "El resultado seleccionado no tiene URL.", wx.ICON_INFORMATION)
            return None

        self.campo_url.SetValue(url)
        return url

    def descargar_resultado(self, evento=None):
        resultado = self._resultado_seleccionado()

        if not resultado:
            return

        url = self._usar_url_resultado(resultado)

        if not url:
            return

        carpeta = self.validar_carpeta_descarga()

        if not carpeta:
            return

        self._set_estado_busqueda("Descarga enviada. El progreso está en la pestaña Descargar.")
        hablar_async("Descarga enviada. Se anunciará el progreso y la finalización", limpiar=True)
        self._comenzar_descarga(url, carpeta)
        self.notebook.SetSelection(1)
        self.lista_resultados.SetFocus()

    def informacion_resultado(self, evento=None):
        resultado = self._resultado_seleccionado()

        if not resultado:
            return

        url = resultado.get("url", "").strip()

        if not url:
            hablar_async("El resultado no tiene URL")
            self._mostrar_mensaje_accesible("Sin URL", "El resultado seleccionado no tiene URL.", wx.ICON_INFORMATION)
            return

        # Para accesibilidad y rapidez, la información del resultado se abre de inmediato
        # con los datos ya recuperados por la búsqueda. Así no queda en silencio si
        # YouTube bloquea una consulta ampliada.
        info = dict(resultado)
        info["url"] = url
        if not info.get("nota"):
            info["nota"] = "Información tomada del resultado de búsqueda."

        self._set_estado_busqueda("Mostrando información del resultado seleccionado")
        self.agregar_log(f"Mostrando información: {info.get('titulo', 'Sin título')}")
        hablar_async("Mostrando información del resultado seleccionado")
        self._mostrar_info_dialogo_y_actualizar(info, volver_busqueda=True, parcial=False)

    def reproducir_resultado(self, evento=None):
        resultado = self._resultado_seleccionado()

        if not resultado:
            return

        url = resultado.get("url", "").strip()

        if not url:
            hablar_async("El resultado no tiene URL")
            self._mostrar_mensaje_accesible("Sin URL", "El resultado seleccionado no tiene URL.", wx.ICON_INFORMATION)
            return

        self._set_estado_busqueda("Preparando reproductor interno")
        self.agregar_log(f"Preparando reproducción interna: {resultado.get('titulo', 'Sin título')}")

        try:
            dialogo = DialogoReproductor(self, self.descargador, url, resultado, self.configuracion)
            dialogo.ShowModal()
            dialogo.Destroy()
            self.notebook.SetSelection(1)
            if self.resultados_busqueda:
                indice = self._indice_resultado_seleccionado()
                if indice is not None:
                    self.lista_resultados.Select(indice)
                    self.lista_resultados.Focus(indice)
            self.lista_resultados.SetFocus()
            self._set_estado_busqueda("Reproductor cerrado. Lista lista.")
        except Exception as exc:
            self._mostrar_error_detallado("Error en reproductor", exc)

    def copiar_url_resultado(self, evento=None):
        resultado = self._resultado_seleccionado()

        if not resultado:
            return

        url = resultado.get("url", "").strip()

        if not url:
            hablar_async("El resultado no tiene URL")
            return

        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Close()
                hablar_async("URL copiada")
                self._set_estado_busqueda("URL copiada al portapapeles")
        except Exception:
            try:
                wx.TheClipboard.Close()
            except Exception:
                pass
            self._mostrar_error_detallado("Error", "No se pudo copiar la URL.")

    def _tecla_campo_busqueda_coleccion(self, evento):
        codigo = evento.GetKeyCode()
        if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.iniciar_busqueda_coleccion()
            return
        evento.Skip()

    def _set_estado_colecciones(self, texto):
        try:
            texto = traducir_dinamico(texto)
            self.estado_colecciones.SetLabel(f"{traducir('Estado')}: {texto}")
            self.panel_colecciones.Layout()
        except Exception:
            pass

    def _ocultar_resultados_colecciones(self):
        self.resultados_colecciones = []
        self.videos_coleccion = []
        self.videos_marcados = set()
        self.coleccion_actual = None
        try:
            self.lista_colecciones.DeleteAllItems()
            self.lista_colecciones.Disable()
            self.btn_limpiar_colecciones.Disable()
            self.panel_resultados_colecciones.Hide()
            self.lista_videos_coleccion.DeleteAllItems()
            self.lista_videos_coleccion.Disable()
            self.btn_descargar_marcados.Disable()
            self.panel_videos_coleccion.Hide()
            self.panel_colecciones.Layout()
        except Exception:
            pass

    def limpiar_busqueda_coleccion(self, evento=None):
        self.campo_busqueda_coleccion.SetValue("")
        self._ocultar_resultados_colecciones()
        self._set_estado_colecciones("Listo para una nueva búsqueda")
        self.campo_busqueda_coleccion.SetFocus()
        hablar_async("Búsqueda de canales y listas limpiada")

    def _pedir_tipo_busqueda_coleccion(self):
        opciones = [(traducir("Buscar canal"), "canal"), (traducir("Buscar lista de reproducción"), "playlist")]
        dialogo = wx.Dialog(self, title="Tipo de búsqueda", size=(430, 190))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label="¿Qué desea buscar?"), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=[etiqueta for etiqueta, valor in opciones])
        combo.SetSelection(0)
        combo.SetName("Elegir si desea buscar canal o lista de reproducción")
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(dialogo, wx.ID_CANCEL, label="Cancelar")
        fila.Add(btn_ok, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        def aceptar_con_enter(evento):
            codigo = evento.GetKeyCode()
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK)
                return
            evento.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, aceptar_con_enter)
        combo.Bind(wx.EVT_KEY_DOWN, aceptar_con_enter)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo.SetFocus()
        hablar_async("Elija si desea buscar canal o lista de reproducción", limpiar=True)

        tipo = None
        if dialogo.ShowModal() == wx.ID_OK:
            seleccion = combo.GetSelection()
            tipo = opciones[seleccion][1] if 0 <= seleccion < len(opciones) else "canal"
        dialogo.Destroy()
        return tipo

    def iniciar_busqueda_coleccion(self, evento=None):
        if self.busqueda_activa:
            hablar_async("La búsqueda ya está en curso")
            return

        consulta = self.campo_busqueda_coleccion.GetValue().strip()
        if not consulta:
            self._mostrar_mensaje_accesible(
                "Falta búsqueda",
                "Debe escribir el nombre de un canal o una lista de reproducción.",
                wx.ICON_INFORMATION,
                enfocar_control=self.campo_busqueda_coleccion,
            )
            self.notebook.SetSelection(2)
            self.campo_busqueda_coleccion.SetFocus()
            return

        tipo = self._pedir_tipo_busqueda_coleccion()
        if tipo is None:
            self.campo_busqueda_coleccion.SetFocus()
            return

        limite = self._pedir_cantidad_resultados(
            titulo="Cantidad de resultados",
            etiqueta="Cantidad de canales o listas a buscar:",
        )
        if limite is None:
            self.campo_busqueda_coleccion.SetFocus()
            return

        self.busqueda_activa = True
        self._ocultar_resultados_colecciones()
        etiqueta = "listas de reproducción" if tipo == "playlist" else "canales"
        self._set_estado_colecciones(f"Buscando {etiqueta}")
        self._actualizar_botones_busqueda(True)
        self.SetStatusText(traducir_formato("Buscando {cantidad} {tipo}", cantidad=limite, tipo=traducir_dinamico(etiqueta)))
        hablar_async(traducir_formato("Buscando {cantidad} {tipo}", cantidad=limite, tipo=traducir_dinamico(etiqueta)), limpiar=True)

        hilo = threading.Thread(
            target=self._buscar_coleccion_hilo,
            args=(consulta, tipo, limite),
            daemon=True,
        )
        hilo.start()

    def _buscar_coleccion_hilo(self, consulta, tipo, limite):
        try:
            resultados = self.descargador.buscar_colecciones_youtube(consulta, tipo=tipo, limite=limite)
            wx.CallAfter(self._mostrar_resultados_colecciones, resultados, tipo)
        except ErrorAutenticacionYoutube as e:
            wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
        except Exception as e:
            wx.CallAfter(self._set_estado_colecciones, "Error")
            wx.CallAfter(self._mostrar_error_detallado, "Error buscando canales o listas", e)
        finally:
            wx.CallAfter(self._finalizar_busqueda_ui)

    def _mostrar_resultados_colecciones(self, resultados, tipo):
        self.resultados_colecciones = resultados or []
        self.videos_coleccion = []
        self.videos_marcados = set()
        self.coleccion_actual = None
        self.lista_colecciones.DeleteAllItems()
        self.lista_videos_coleccion.DeleteAllItems()
        self.panel_videos_coleccion.Hide()

        for indice, resultado in enumerate(self.resultados_colecciones):
            item = self.lista_colecciones.InsertItem(indice, str(indice + 1))
            self.lista_colecciones.SetItem(item, 1, resultado.get("tipo", "Canal"))
            self.lista_colecciones.SetItem(item, 2, resultado.get("titulo", "Sin título"))
            self.lista_colecciones.SetItem(item, 3, resultado.get("autor", resultado.get("canal", "No disponible")))

        total = len(self.resultados_colecciones)
        etiqueta = "listas" if tipo == "playlist" else "canales"

        if total:
            self.lista_colecciones.Enable()
            self.btn_limpiar_colecciones.Enable()
            self.panel_resultados_colecciones.Show()
            self.panel_colecciones.Layout()
            self._set_estado_colecciones(traducir_formato("{total} {tipo} encontrados. Use flechas y Enter para elegir acción. Pestaña Canales y listas, Alt+3.", total=total, tipo=traducir_dinamico(etiqueta)))
            self.agregar_log(f"Búsqueda de {etiqueta} finalizada: {total} resultados")
            self.lista_colecciones.Select(0)
            self.lista_colecciones.Focus(0)
            self.lista_colecciones.SetFocus()
            hablar_async(traducir_formato("{total} {tipo} encontrados. Use flechas y Enter para elegir acción. Esta es la pestaña Canales y listas, Alt más 3", total=total, tipo=traducir_dinamico(etiqueta)), limpiar=True)
        else:
            self.panel_resultados_colecciones.Hide()
            self.panel_colecciones.Layout()
            self._set_estado_colecciones("Sin resultados")
            self.campo_busqueda_coleccion.SetFocus()
            hablar_async("No se encontraron resultados")

    def _indice_coleccion_seleccionada(self):
        indice = self.lista_colecciones.GetFirstSelected()
        if indice == -1:
            if self.resultados_colecciones:
                indice = 0
                self.lista_colecciones.Select(0)
            else:
                return None
        if indice < 0 or indice >= len(self.resultados_colecciones):
            return None
        return indice

    def _coleccion_seleccionada(self):
        indice = self._indice_coleccion_seleccionada()
        if indice is None:
            hablar_async("No hay canal o lista seleccionada")
            return None
        return self.resultados_colecciones[indice]

    def _alternar_favorito_coleccion(self, coleccion):
        if not coleccion:
            return
        datos = dict(coleccion)
        datos["tipo_favorito"] = "Playlist" if str(datos.get("tipo_clave") or "").lower() == "playlist" else "Canal"
        self._alternar_favorito_item(datos)

    def _pedir_cantidad_playlist_mostrar(self):
        opciones = list(RESULTADOS_BUSQUEDA_DISPONIBLES) + [traducir("Todos")]
        dialogo = wx.Dialog(self, title=traducir("Cantidad de elementos"), size=(440, 195))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label=traducir("Cantidad de elementos de la playlist a mostrar:")), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=opciones)
        pred = str(self.configuracion.get("resultados_busqueda", "100"))
        combo.SetSelection(RESULTADOS_BUSQUEDA_DISPONIBLES.index(pred) if pred in RESULTADOS_BUSQUEDA_DISPONIBLES else 3)
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(wx.Button(dialogo, wx.ID_OK, label=traducir("Aceptar")), 0, wx.ALL, 5)
        fila.Add(wx.Button(dialogo, wx.ID_CANCEL, label=traducir("Cancelar")), 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo.SetFocus()
        valor = None
        if dialogo.ShowModal() == wx.ID_OK:
            seleccion = combo.GetSelection()
            if seleccion == len(opciones) - 1:
                valor = 0  # 0 representa todos, None representa cancelar.
            elif 0 <= seleccion < len(RESULTADOS_BUSQUEDA_DISPONIBLES):
                valor = int(RESULTADOS_BUSQUEDA_DISPONIBLES[seleccion])
        dialogo.Destroy()
        return valor

    def _pedir_rango_playlist(self):
        dialogo = wx.Dialog(self, title=traducir("Seleccionar rango de la playlist"), size=(470, 265))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label=traducir("Indique las posiciones que desea agregar a la cola de descargas.")), 0, wx.ALL, 10)
        fila_desde = wx.BoxSizer(wx.HORIZONTAL)
        fila_desde.Add(wx.StaticText(dialogo, label=traducir("Desde:")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        desde = wx.TextCtrl(dialogo, value="1", style=wx.TE_PROCESS_ENTER)
        desde.SetName(traducir("Primera posición del rango"))
        fila_desde.Add(desde, 1, wx.ALL, 5)
        sizer.Add(fila_desde, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        fila_hasta = wx.BoxSizer(wx.HORIZONTAL)
        fila_hasta.Add(wx.StaticText(dialogo, label=traducir("Hasta:")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        hasta = wx.TextCtrl(dialogo, value="20", style=wx.TE_PROCESS_ENTER)
        hasta.SetName(traducir("Última posición del rango"))
        fila_hasta.Add(hasta, 1, wx.ALL, 5)
        sizer.Add(fila_hasta, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        botones = wx.BoxSizer(wx.HORIZONTAL)
        botones.Add(wx.Button(dialogo, wx.ID_OK, label=traducir("Aceptar")), 0, wx.ALL, 5)
        botones.Add(wx.Button(dialogo, wx.ID_CANCEL, label=traducir("Cancelar")), 0, wx.ALL, 5)
        sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        desde.SetFocus()
        resultado = None
        if dialogo.ShowModal() == wx.ID_OK:
            try:
                inicio = int(desde.GetValue().strip())
                fin = int(hasta.GetValue().strip())
                if inicio < 1 or fin < inicio:
                    raise ValueError
                resultado = (inicio, fin)
            except ValueError:
                self._mostrar_mensaje_accesible(
                    "Rango no válido",
                    "El valor Desde debe ser 1 o mayor y Hasta debe ser igual o mayor que Desde.",
                    wx.ICON_INFORMATION,
                )
        dialogo.Destroy()
        return resultado

    def _agregar_varios_cola_y_anunciar(self, videos):
        resultado = agregar_varios_a_cola([dict(v) for v in (videos or []) if isinstance(v, dict)])
        agregados = int(resultado.get("agregados", 0))
        duplicados = int(resultado.get("duplicados", 0))
        errores = int(resultado.get("errores", 0))
        if duplicados or errores:
            mensaje = traducir_formato(
                "{agregados} elementos agregados a la cola. {duplicados} ya estaban en la cola. {errores} no pudieron agregarse.",
                agregados=agregados, duplicados=duplicados, errores=errores,
            )
        else:
            mensaje = traducir_formato("Se agregaron {agregados} elementos a la cola de descargas.", agregados=agregados)
        self.SetStatusText(mensaje)
        hablar_async(mensaje, limpiar=True)
        return resultado

    def agregar_playlist_completa_cola(self, coleccion=None):
        if self.busqueda_activa:
            hablar_async("Espere a que termine la operación actual antes de cargar otra playlist.", limpiar=True)
            return
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        if str(coleccion.get("tipo_clave") or "").lower() != "playlist":
            hablar_async("Esta acción está disponible únicamente para listas de reproducción.", limpiar=True)
            return
        nombre = coleccion.get("titulo") or traducir("la playlist")
        total = coleccion.get("total_elementos")
        try:
            total = int(total) if total not in (None, "") else None
        except (TypeError, ValueError):
            total = None
        if total:
            mensaje = traducir_formato(
                "La playlist {nombre} contiene {total} elementos. Se agregarán todos a la cola de descargas. Si son muchos, el proceso puede tardar. ¿Desea continuar?",
                nombre=nombre, total=total,
            )
        else:
            mensaje = traducir_formato(
                "Se cargará la playlist completa {nombre} y se agregarán sus elementos a la cola de descargas. Si contiene muchos elementos, el proceso puede tardar. ¿Desea continuar?",
                nombre=nombre,
            )
        if wx.MessageBox(mensaje, traducir("Agregar playlist completa"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return
        self.busqueda_activa = True
        self._actualizar_botones_busqueda(True)
        hablar_async("Cargando la playlist completa. Espere, por favor.", limpiar=True)
        def trabajo():
            try:
                videos = self.descargador.listar_videos_coleccion(coleccion.get("url", ""), limite=None, tipo="playlist")
                wx.CallAfter(self._playlist_completa_cargada, videos, coleccion)
            except ErrorAutenticacionYoutube as e:
                wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
            except Exception as e:
                wx.CallAfter(self._mostrar_error_detallado, "Error cargando playlist", e)
            finally:
                wx.CallAfter(self._finalizar_busqueda_ui)
        threading.Thread(target=trabajo, daemon=True).start()

    def _playlist_completa_cargada(self, videos, coleccion):
        videos = videos or []
        if not videos:
            self._mostrar_mensaje_accesible("Playlist vacía", "No se encontraron elementos en la playlist.", wx.ICON_INFORMATION)
            return
        self._agregar_varios_cola_y_anunciar(videos)

    def agregar_rango_playlist_cola(self, coleccion=None):
        if self.busqueda_activa:
            hablar_async("Espere a que termine la operación actual antes de cargar otra playlist.", limpiar=True)
            return
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        if str(coleccion.get("tipo_clave") or "").lower() != "playlist":
            hablar_async("Esta acción está disponible únicamente para listas de reproducción.", limpiar=True)
            return
        rango = self._pedir_rango_playlist()
        if not rango:
            return
        desde, hasta = rango
        cantidad = hasta - desde + 1
        mensaje = traducir_formato(
            "Se agregarán a la cola los elementos desde {desde} hasta {hasta}, hasta {cantidad} elementos. ¿Desea continuar?",
            desde=desde, hasta=hasta, cantidad=cantidad,
        )
        if wx.MessageBox(mensaje, traducir("Confirmar rango"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return
        self.busqueda_activa = True
        self._actualizar_botones_busqueda(True)
        hablar_async(traducir_formato("Cargando elementos desde {desde} hasta {hasta}", desde=desde, hasta=hasta), limpiar=True)
        def trabajo():
            try:
                videos = self.descargador.listar_videos_coleccion_rango(coleccion.get("url", ""), desde, hasta, tipo="playlist")
                wx.CallAfter(self._rango_playlist_cargado, videos, desde, hasta)
            except ErrorAutenticacionYoutube as e:
                wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
            except Exception as e:
                wx.CallAfter(self._mostrar_error_detallado, "Error cargando rango de playlist", e)
            finally:
                wx.CallAfter(self._finalizar_busqueda_ui)
        threading.Thread(target=trabajo, daemon=True).start()

    def _rango_playlist_cargado(self, videos, desde, hasta):
        videos = videos or []
        if not videos:
            self._mostrar_mensaje_accesible("Sin elementos", "No se encontraron elementos dentro del rango indicado.", wx.ICON_INFORMATION)
            return
        self._agregar_varios_cola_y_anunciar(videos)

    def acciones_coleccion_enter(self, evento=None):
        if self.notebook.GetSelection() != 2:
            if evento:
                evento.Skip()
            return
        coleccion = self._coleccion_seleccionada()
        if not coleccion:
            return

        es_playlist = str(coleccion.get("tipo_clave") or "").lower() == "playlist"
        if es_playlist:
            es_favorito = esta_en_favoritos(coleccion.get("url", ""))
            etiqueta_favorito = "Quitar de favoritos (Alt+F)" if es_favorito else "Agregar a favoritos (Alt+F)"
            opciones = [
                (traducir("Ver contenido de la playlist"), "Ver contenido"),
                (traducir("Agregar toda la playlist a la cola de descargas"), "Agregar toda"),
                (traducir("Seleccionar un rango de la playlist"), "Rango"),
                (traducir(etiqueta_favorito), "Favorito"),
                (traducir("Información (Alt+I)"), "Información"),
                (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
            ]
            ayuda = "Seleccione una acción para la playlist. Alt+F agrega o quita de favoritos. Alt+I información. Alt+C copia URL."
            seleccion_inicial = 0
        else:
            opciones = [
                (traducir("Información (Alt+I)"), "Información"),
                (traducir("Elegir videos para descargar"), "Elegir videos para descargar"),
                (traducir("Descargar primeros videos (Alt+D)"), "Descargar primeros videos"),
                (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
            ]
            ayuda = "Seleccione una acción. Alt+I información. Alt+D descarga primeros videos. Alt+C copia URL."
            seleccion_inicial = 1

        dialogo = wx.Dialog(self, title=traducir("Acción del canal o lista"), size=(550, 260 if es_playlist else 220))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label=traducir(ayuda)), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=[etiqueta for etiqueta, accion in opciones])
        combo.SetSelection(seleccion_inicial)
        combo.SetName(traducir("Acción para el canal o lista seleccionada"))
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        fila.Add(wx.Button(dialogo, wx.ID_OK, label=traducir("Aceptar")), 0, wx.ALL, 5)
        fila.Add(wx.Button(dialogo, wx.ID_CANCEL, label=traducir("Cancelar")), 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        directo = {"valor": None}

        def tecla(ev):
            codigo = ev.GetKeyCode()
            if ev.AltDown() and codigo in (ord("I"), ord("i")):
                directo["valor"] = "Información"; dialogo.EndModal(wx.ID_OK); return
            if ev.AltDown() and codigo in (ord("C"), ord("c")):
                directo["valor"] = "Copiar URL"; dialogo.EndModal(wx.ID_OK); return
            if es_playlist and ev.AltDown() and codigo in (ord("F"), ord("f")):
                directo["valor"] = "Favorito"; dialogo.EndModal(wx.ID_OK); return
            if not es_playlist and ev.AltDown() and codigo in (ord("D"), ord("d")):
                directo["valor"] = "Descargar primeros videos"; dialogo.EndModal(wx.ID_OK); return
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK); return
            ev.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, tecla)
        combo.Bind(wx.EVT_KEY_DOWN, tecla)
        combo.SetFocus()
        hablar_async(ayuda, limpiar=True)
        accion = None
        if dialogo.ShowModal() == wx.ID_OK:
            accion = directo["valor"]
            if not accion:
                sel = combo.GetSelection()
                accion = opciones[sel][1] if 0 <= sel < len(opciones) else None
        dialogo.Destroy()
        self.notebook.SetSelection(2)
        self.lista_colecciones.SetFocus()

        if accion == "Información":
            self.informacion_coleccion(coleccion)
        elif accion == "Elegir videos para descargar":
            self.cargar_videos_coleccion_para_elegir(coleccion)
        elif accion == "Descargar primeros videos":
            self.descargar_primeros_videos_coleccion(coleccion)
        elif accion == "Copiar URL":
            self.copiar_url_coleccion(coleccion)
        elif accion == "Ver contenido":
            self.cargar_videos_coleccion_para_elegir(coleccion)
        elif accion == "Agregar toda":
            self.agregar_playlist_completa_cola(coleccion)
        elif accion == "Rango":
            self.agregar_rango_playlist_cola(coleccion)
        elif accion == "Favorito":
            self._alternar_favorito_coleccion(coleccion)

    def informacion_coleccion(self, coleccion=None):
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        partes = [
            f"Tipo: {coleccion.get('tipo', 'No disponible')}",
            f"Nombre: {coleccion.get('titulo', 'Sin título')}",
            f"Autor: {coleccion.get('autor', coleccion.get('canal', 'No disponible'))}",
        ]
        if coleccion.get("total_elementos") not in (None, ""):
            partes.append(f"Elementos: {coleccion.get('total_elementos')}")
        partes.extend([
            f"URL: {coleccion.get('url', '')}",
            "",
            f"Descripción: {coleccion.get('descripcion', 'No disponible')}",
        ])
        texto = "\n".join(partes)
        self._mostrar_texto_dialogo("Información del canal o lista", texto, "Información del canal o lista")
        self.lista_colecciones.SetFocus()

    def copiar_url_coleccion(self, coleccion=None):
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        url = coleccion.get("url", "").strip()
        if not url:
            hablar_async("No hay URL para copiar")
            return
        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Close()
                self._set_estado_colecciones("URL copiada al portapapeles")
                hablar_async("URL copiada")
        except Exception:
            try:
                wx.TheClipboard.Close()
            except Exception:
                pass
            self._mostrar_error_detallado("Error", "No se pudo copiar la URL.")

    def _pedir_cantidad_videos_coleccion(self, accion="cargar"):
        return self._pedir_cantidad_resultados(
            titulo="Cantidad de videos",
            etiqueta="Cantidad de videos a cargar:" if accion == "cargar" else "Cantidad de videos a descargar:",
        )

    def cargar_videos_coleccion_para_elegir(self, coleccion=None):
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        if str(coleccion.get("tipo_clave") or "").lower() == "playlist":
            limite = self._pedir_cantidad_playlist_mostrar()
            if limite is None:
                self.lista_colecciones.SetFocus()
                return
            limite = None if limite == 0 else limite
        else:
            limite = self._pedir_cantidad_videos_coleccion("cargar")
            if limite is None:
                self.lista_colecciones.SetFocus()
                return
        self._listar_videos_coleccion(coleccion, limite, accion="mostrar")

    def descargar_primeros_videos_coleccion(self, coleccion=None):
        coleccion = coleccion or self._coleccion_seleccionada()
        if not coleccion:
            return
        limite = self._pedir_cantidad_videos_coleccion("descargar")
        if limite is None:
            self.lista_colecciones.SetFocus()
            return
        self._listar_videos_coleccion(coleccion, limite, accion="descargar")

    def _listar_videos_coleccion(self, coleccion, limite, accion="mostrar"):
        if self.busqueda_activa:
            hablar_async("La búsqueda ya está en curso")
            return
        url = coleccion.get("url", "").strip()
        if not url:
            self._mostrar_mensaje_accesible("Sin URL", "El canal o lista seleccionada no tiene URL.", wx.ICON_INFORMATION)
            return

        self.busqueda_activa = True
        self._actualizar_botones_busqueda(True)
        self.coleccion_actual = coleccion
        self.videos_coleccion = []
        self.videos_marcados = set()
        self.lista_videos_coleccion.DeleteAllItems()
        self.lista_videos_coleccion.Disable()
        self.btn_descargar_marcados.Disable()
        self.panel_videos_coleccion.Hide()
        if limite is None:
            self._set_estado_colecciones(traducir_formato("Cargando todos los elementos de {nombre}", nombre=coleccion.get("titulo", traducir_dinamico("la colección"))))
            hablar_async("Cargando todos los elementos de la playlist", limpiar=True)
        else:
            self._set_estado_colecciones(traducir_formato("Cargando {cantidad} videos de {nombre}", cantidad=limite, nombre=coleccion.get("titulo", traducir_dinamico("la colección"))))
            hablar_async(traducir_formato("Cargando {cantidad} videos", cantidad=limite), limpiar=True)

        hilo = threading.Thread(
            target=self._listar_videos_coleccion_hilo,
            args=(coleccion, limite, accion),
            daemon=True,
        )
        hilo.start()

    def _listar_videos_coleccion_hilo(self, coleccion, limite, accion):
        try:
            videos = self.descargador.listar_videos_coleccion(
                coleccion.get("url", ""),
                limite=limite,
                tipo=coleccion.get("tipo_clave", "canal"),
            )
            if accion == "descargar":
                wx.CallAfter(self._descargar_videos_obtenidos, videos, coleccion)
            else:
                wx.CallAfter(self._mostrar_videos_coleccion, videos, coleccion)
        except ErrorAutenticacionYoutube as e:
            wx.CallAfter(self._mostrar_error_autenticacion_youtube, e)
        except Exception as e:
            wx.CallAfter(self._set_estado_colecciones, "Error cargando videos")
            wx.CallAfter(self._mostrar_error_detallado, "Error cargando videos", e)
        finally:
            wx.CallAfter(self._finalizar_busqueda_ui)

    def _mostrar_videos_coleccion(self, videos, coleccion):
        self.videos_coleccion = videos or []
        self.videos_marcados = set()
        self.coleccion_actual = coleccion
        self.lista_videos_coleccion.DeleteAllItems()
        nombre = coleccion.get("titulo", "colección")
        self.texto_videos_coleccion.SetLabel(f"Videos de: {nombre}")

        for indice, video in enumerate(self.videos_coleccion):
            item = self.lista_videos_coleccion.InsertItem(indice, "No")
            self.lista_videos_coleccion.SetItem(item, 1, str(indice + 1))
            self.lista_videos_coleccion.SetItem(item, 2, video.get("titulo", "Sin título"))
            self.lista_videos_coleccion.SetItem(item, 3, video.get("canal", "No disponible"))
            self.lista_videos_coleccion.SetItem(item, 4, video.get("duracion_texto", "No disponible"))

        total = len(self.videos_coleccion)
        if total:
            self.panel_resultados_colecciones.Show()
            self.panel_videos_coleccion.Show()
            self.lista_videos_coleccion.Enable()
            self.btn_descargar_marcados.Enable()
            self.panel_colecciones.Layout()
            self._set_estado_colecciones(traducir_formato("{total} videos cargados. Espacio marca; Enter actúa sobre el video enfocado. Alt+D descarga. Alt+R reproduce. Alt+I información. Alt+C copia URL. Alt+F agrega o quita de favoritos. Alt+Q agrega a la cola. Alt+L limpia la búsqueda.", total=total))
            self.lista_videos_coleccion.Select(0)
            self.lista_videos_coleccion.Focus(0)
            self.lista_videos_coleccion.SetFocus()
            hablar_async(traducir_formato("{total} videos cargados. Use Espacio para marcar. Enter abre acciones del video enfocado. Alt más D descarga el enfocado. Alt más R reproduce el enfocado. Alt más I información. Alt más C copia URL. Alt más F agrega o quita de favoritos. Alt más Q agrega a la cola. Alt más L limpia el cuadro de búsqueda", total=total), limpiar=True)
        else:
            self.panel_videos_coleccion.Hide()
            self.panel_colecciones.Layout()
            self._set_estado_colecciones("No se encontraron videos")
            self.lista_colecciones.SetFocus()
            hablar_async("No se encontraron videos")

    def _descargar_videos_obtenidos(self, videos, coleccion):
        videos = videos or []
        if not videos:
            self._set_estado_colecciones("No se encontraron videos para descargar")
            hablar_async("No se encontraron videos para descargar")
            return
        self.coleccion_actual = coleccion
        self._mostrar_videos_coleccion(videos, coleccion)
        self._descargar_lista_videos(videos, coleccion, origen="primeros")

    def volver_resultados_colecciones(self, evento=None):
        self.panel_videos_coleccion.Hide()
        self.panel_colecciones.Layout()
        if isinstance(self.coleccion_actual, dict) and self.coleccion_actual.get("origen_url_directa"):
            self.notebook.SetSelection(0)
            self.campo_url.SetFocus()
            hablar_async("Volviendo a Descargar por URL", limpiar=True)
            return
        self.lista_colecciones.SetFocus()
        hablar_async("Volviendo a resultados de canales o listas")

    def _indice_video_coleccion(self):
        indice = self.lista_videos_coleccion.GetFirstSelected()
        if indice == -1:
            if self.videos_coleccion:
                indice = 0
                self.lista_videos_coleccion.Select(0)
            else:
                return None
        if indice < 0 or indice >= len(self.videos_coleccion):
            return None
        return indice

    def _video_enfocado_coleccion(self):
        indice = self._indice_video_coleccion()
        if indice is None:
            hablar_async("No hay video seleccionado")
            return None
        return self.videos_coleccion[indice]

    def alternar_marca_video_coleccion(self, evento=None):
        indice = self._indice_video_coleccion()
        if indice is None:
            return
        if indice in self.videos_marcados:
            self.videos_marcados.remove(indice)
            marcado = False
        else:
            self.videos_marcados.add(indice)
            marcado = True
        self._actualizar_marca_video(indice)
        total = len(self.videos_marcados)
        titulo = self.videos_coleccion[indice].get("titulo", "video")
        if marcado:
            hablar_async(traducir_formato("Marcado. {titulo}. Total marcados {total}", titulo=titulo, total=total), limpiar=True)
        else:
            hablar_async(traducir_formato("Desmarcado. {titulo}. Total marcados {total}", titulo=titulo, total=total), limpiar=True)
        self._set_estado_colecciones(f"{total} videos marcados")
        self.lista_videos_coleccion.Select(indice)
        self.lista_videos_coleccion.Focus(indice)
        self.lista_videos_coleccion.SetFocus()

    def _actualizar_marca_video(self, indice):
        try:
            texto = "Sí" if indice in self.videos_marcados else "No"
            self.lista_videos_coleccion.SetItem(indice, 0, texto)
        except Exception:
            pass

    def acciones_video_coleccion_enter(self, evento=None):
        if self.notebook.GetSelection() != 2:
            if evento:
                evento.Skip()
            return
        video = self._video_enfocado_coleccion()
        if not video:
            return

        es_favorito = esta_en_favoritos(video.get("url", ""))
        etiqueta_favorito = "Quitar de favoritos (Alt+F)" if es_favorito else "Agregar a favoritos (Alt+F)"
        opciones = [
            (traducir("Reproducir este video (Alt+R)"), "Reproducir este video"),
            (traducir("Descargar este video (Alt+D)"), "Descargar este video"),
            (traducir("Información de este video (Alt+I)"), "Información de este video"),
            (traducir("Copiar URL (Alt+C)"), "Copiar URL"),
            (traducir(etiqueta_favorito), "Favorito"),
            (traducir("Agregar a la cola de descargas (Alt+Q)"), "Cola"),
        ]
        dialogo = wx.Dialog(self, title="Acción del video", size=(510, 230))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(dialogo, label="Seleccione una acción para el video enfocado. Alt+D descarga. Alt+R reproduce. Alt+I información. Alt+C copia URL. Alt+F agrega o quita de favoritos. Alt+Q agrega a la cola."), 0, wx.ALL, 10)
        combo = wx.Choice(dialogo, choices=[etiqueta for etiqueta, accion in opciones])
        combo.SetSelection(0)
        combo.SetName("Acción para el video enfocado. Alt más D descarga. Alt más R reproduce. Alt más I información. Alt más C copia URL. Alt más F agrega o quita de favoritos. Alt más Q agrega a la cola")
        sizer.Add(combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn_cancelar = wx.Button(dialogo, wx.ID_CANCEL, label="Cancelar")
        fila.Add(btn_ok, 0, wx.ALL, 5)
        fila.Add(btn_cancelar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        accion_directa = {"valor": None}

        def aceptar_con_enter(evento):
            codigo = evento.GetKeyCode()
            if evento.AltDown() and codigo in (ord("R"), ord("r")):
                accion_directa["valor"] = "Reproducir este video"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("D"), ord("d")):
                accion_directa["valor"] = "Descargar este video"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("I"), ord("i")):
                accion_directa["valor"] = "Información de este video"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("C"), ord("c")):
                accion_directa["valor"] = "Copiar URL"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("F"), ord("f")):
                accion_directa["valor"] = "Favorito"
                dialogo.EndModal(wx.ID_OK)
                return
            if evento.AltDown() and codigo in (ord("Q"), ord("q")):
                accion_directa["valor"] = "Cola"
                dialogo.EndModal(wx.ID_OK)
                return
            if codigo in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                dialogo.EndModal(wx.ID_OK)
                return
            evento.Skip()

        dialogo.Bind(wx.EVT_CHAR_HOOK, aceptar_con_enter)
        combo.Bind(wx.EVT_KEY_DOWN, aceptar_con_enter)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        dialogo.SetEscapeId(wx.ID_CANCEL)
        combo.SetFocus()
        hablar_async("Elija acción para este video. Descargar, Alt más D. Reproducir, Alt más R. Información, Alt más I. Copiar URL, Alt más C. Favoritos, Alt más F. Cola, Alt más Q", limpiar=True)

        accion = None
        if dialogo.ShowModal() == wx.ID_OK:
            if accion_directa["valor"]:
                accion = accion_directa["valor"]
            else:
                seleccion = combo.GetSelection()
                accion = opciones[seleccion][1] if 0 <= seleccion < len(opciones) else None
        dialogo.Destroy()
        self.notebook.SetSelection(2)
        self.lista_videos_coleccion.SetFocus()

        if accion == "Reproducir este video":
            self.reproducir_video_coleccion(video)
        elif accion == "Descargar este video":
            self.descargar_video_coleccion(video)
        elif accion == "Información de este video":
            self.informacion_video_coleccion(video)
        elif accion == "Copiar URL":
            self.copiar_url_video_coleccion(video)
        elif accion == "Favorito":
            self._alternar_favorito_item(video)
        elif accion == "Cola":
            self._agregar_cola_item(video)

    def descargar_video_coleccion(self, video=None):
        video = video or self._video_enfocado_coleccion()
        if not video:
            return
        self._descargar_lista_videos([video], self.coleccion_actual, origen="video enfocado")

    def descargar_videos_marcados(self, evento=None):
        if not self.videos_marcados:
            self._mostrar_mensaje_accesible(
                "Sin videos marcados",
                "Marque uno o más videos con Espacio antes de descargar varios.",
                wx.ICON_INFORMATION,
                enfocar_control=self.lista_videos_coleccion,
            )
            return
        indices = sorted(self.videos_marcados)
        videos = [self.videos_coleccion[i] for i in indices if 0 <= i < len(self.videos_coleccion)]
        self._descargar_lista_videos(videos, self.coleccion_actual, origen="marcados")

    def descargar_videos_marcados_o_enfocado(self, evento=None):
        if self.notebook.GetSelection() == 2 and self.videos_marcados:
            self.descargar_videos_marcados()
        elif self.notebook.GetSelection() == 2:
            self.descargar_video_coleccion()
        else:
            self.descargar_resultado()

    def _preparar_carpeta_coleccion(self, coleccion):
        carpeta_base = self.validar_carpeta_descarga()
        if not carpeta_base:
            return None
        if not coleccion:
            return carpeta_base
        titulo = coleccion.get("titulo", "Descarga")
        tipo = coleccion.get("tipo_clave", "canal")
        if tipo == "playlist":
            nombre = "Lista - " + titulo
        else:
            nombre = titulo
        carpeta = os.path.join(carpeta_base, sanitizar_nombre_carpeta(nombre, "Colección"))
        try:
            os.makedirs(carpeta, exist_ok=True)
        except Exception as exc:
            self._mostrar_error_detallado("Error", f"No se pudo crear la carpeta de la colección.\n\n{exc}")
            return None
        return carpeta

    def _descargar_lista_videos(self, videos, coleccion=None, origen="selección"):
        videos = [v for v in (videos or []) if v and v.get("url")]
        if not videos:
            self._mostrar_mensaje_accesible("Sin videos", "No hay videos válidos para descargar.", wx.ICON_INFORMATION)
            return
        carpeta = self._preparar_carpeta_coleccion(coleccion)
        if not carpeta:
            return
        if not self._confirmar_descarga_multiple(videos, carpeta, coleccion, origen):
            self.lista_videos_coleccion.SetFocus()
            return
        self._comenzar_descarga_lote(videos, carpeta, coleccion)

    def _confirmar_descarga_multiple(self, videos, carpeta, coleccion=None, origen="selección"):
        cantidad = len(videos)
        nombre = coleccion.get("titulo", "la colección") if coleccion else "la selección"
        if cantidad == 1:
            return True
        mensaje = traducir_formato(
            "Se descargarán {cantidad} videos de {nombre}.\n\nCarpeta destino:\n{carpeta}\n\n¿Desea continuar?",
            cantidad=cantidad,
            nombre=nombre,
            carpeta=carpeta,
        )
        hablar_async(traducir_formato("Confirmar descarga de {cantidad} videos", cantidad=cantidad), limpiar=True)
        respuesta = wx.MessageBox(mensaje, "Confirmar descarga múltiple", wx.YES_NO | wx.ICON_QUESTION)
        return respuesta == wx.YES

    def _comenzar_descarga_lote(self, videos, carpeta, coleccion=None):
        if self.descarga_activa:
            hablar_async("Ya hay una descarga en curso")
            return
        formato = self.formato.GetStringSelection()
        calidad = self._calidad_seleccionada()
        self.descarga_activa = True
        self.tipo_descarga_activa = "lote"
        self.ultimo_anuncio = -1
        self.ultimo_estado_anunciado = None
        self.ultimo_aviso_descarga_tiempo = 0
        self.gauge.SetValue(0)
        self.progreso.SetValue("0%")
        cantidad = len(videos)
        nombre = coleccion.get("titulo", "selección") if coleccion else "selección"
        self.estado.SetValue(traducir_dinamico("Preparando descarga múltiple"))
        self.SetStatusText(traducir_formato("Preparando descarga de {cantidad} videos", cantidad=cantidad))
        self._actualizar_botones_descarga(True)
        self._anunciar(traducir_formato("Preparando descarga de {cantidad} videos de {nombre}", cantidad=cantidad, nombre=nombre), limpiar=True)

        self.hilo_descarga = threading.Thread(
            target=self._descargar_lote_hilo,
            args=(videos, carpeta, formato, calidad),
            daemon=True,
        )
        self.hilo_descarga.start()

    def _descargar_lote_hilo(self, videos, carpeta, formato, calidad):
        completados = 0
        errores = []
        total = len(videos)
        try:
            self.descargador.limpiar_cancelacion()
            for indice, video in enumerate(videos, start=1):
                if self.descargador.fue_cancelado():
                    raise DescargaCancelada()
                url = video.get("url", "")
                titulo = video.get("titulo", f"Video {indice}")
                wx.CallAfter(self._actualizar_progreso_lote, indice, total, 0, f"Preparando {indice} de {total}: {titulo}", "Preparando")

                def callback(datos, indice=indice, total=total):
                    porcentaje_video = int(datos.get("porcentaje", 0) or 0)
                    mensaje = datos.get("mensaje", "")
                    estado = datos.get("estado", "Descargando")
                    wx.CallAfter(self._actualizar_progreso_lote, indice, total, porcentaje_video, mensaje, estado)

                try:
                    info = self.descargador.descargar(
                        url,
                        carpeta,
                        formato,
                        calidad,
                        callback_progreso=callback,
                    )
                    completados += 1
                    registro = {
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "titulo": info.get("titulo", titulo),
                        "canal": info.get("canal", video.get("canal", "No disponible")),
                        "duracion": info.get("duracion_texto", video.get("duracion_texto", "No disponible")),
                        "url": url,
                        "formato": formato,
                        "calidad": calidad,
                        "carpeta": carpeta,
                    }
                    agregar_descarga(registro)
                except DescargaCancelada:
                    raise
                except ErrorAutenticacionYoutube as exc:
                    errores.append(f"{titulo}: {exc}")
                except Exception as exc:
                    errores.append(f"{titulo}: {exc}")

            wx.CallAfter(self._descarga_lote_completada, completados, total, errores, carpeta)
        except DescargaCancelada:
            wx.CallAfter(self.estado.SetValue, traducir_dinamico("Cancelado"))
            wx.CallAfter(self.SetStatusText, "Descarga múltiple cancelada")
            wx.CallAfter(self.agregar_log, "Descarga múltiple cancelada por el usuario")
            hablar_async("Descarga múltiple cancelada por el usuario", limpiar=True)
        finally:
            wx.CallAfter(self._finalizar_descarga_ui)

    def _actualizar_progreso_lote(self, indice, total, porcentaje_video, mensaje, estado):
        try:
            total = max(1, int(total))
            indice = max(1, int(indice))
            porcentaje_video = max(0, min(100, int(porcentaje_video)))
            porcentaje_total = int((((indice - 1) + (porcentaje_video / 100.0)) / total) * 100)
        except Exception:
            porcentaje_total = 0
        mensaje_traducido = traducir_dinamico(mensaje)
        texto = traducir_clave("__multi.progress__").format(
            indice=indice,
            total=total,
            mensaje=mensaje_traducido,
        )
        estado_traducido = traducir_dinamico(estado)
        self.gauge.SetValue(max(0, min(100, porcentaje_total)))
        self.progreso.SetValue(texto)
        self.estado.SetValue(estado_traducido)
        self.SetStatusText(texto)
        if porcentaje_total > 0:
            bloque = porcentaje_total // 10
            if bloque > self.ultimo_anuncio and porcentaje_total < 100:
                self.ultimo_anuncio = bloque
                self._anunciar(traducir_formato("Descarga múltiple {porcentaje} por ciento", porcentaje=bloque * 10), limpiar=False, actualizar_estado=False)

    def _descarga_lote_completada(self, completados, total, errores, carpeta):
        self.gauge.SetValue(100)
        texto_final = traducir_clave("__multi.finished__").format(
            completados=completados,
            total=total,
        )
        self.progreso.SetValue(texto_final)
        self.estado.SetValue(traducir_dinamico("Completado"))
        self.SetStatusText(traducir_dinamico("Descarga múltiple finalizada"))
        self._set_estado_colecciones("Descarga múltiple finalizada")
        self.agregar_log(f"Descarga múltiple finalizada: {completados}/{total}. Carpeta: {carpeta}")
        self._sonido("descarga_completada", esperar=True)
        if errores:
            resumen = "\n".join(errores[:8])
            if len(errores) > 8:
                resumen += "\n" + traducir_formato("Y {cantidad} errores más. Revise la carpeta de logs.", cantidad=len(errores) - 8)
            self._mostrar_mensaje_accesible(
                "Descarga múltiple finalizada con avisos",
                traducir_formato("Se completaron {completados} de {total} videos.\n\nErrores:\n{resumen}", completados=completados, total=total, resumen=resumen),
                wx.ICON_INFORMATION,
                estado="Descarga múltiple finalizada con avisos",
            )
        else:
            self._anunciar(traducir_formato("Descarga múltiple finalizada. {completados} videos descargados", completados=completados), limpiar=True, actualizar_estado=False)

    def informacion_video_coleccion(self, video=None):
        video = video or self._video_enfocado_coleccion()
        if not video:
            return
        info = dict(video)
        if not info.get("nota"):
            info["nota"] = "Información tomada de la lista de videos."
        self._mostrar_info_dialogo_y_actualizar(info, volver_busqueda=False, parcial=False)
        self.notebook.SetSelection(2)
        self.lista_videos_coleccion.SetFocus()

    def reproducir_video_coleccion(self, video=None):
        video = video or self._video_enfocado_coleccion()
        if not video:
            return
        url = video.get("url", "").strip()
        if not url:
            self._mostrar_mensaje_accesible("Sin URL", "El video enfocado no tiene URL.", wx.ICON_INFORMATION)
            return
        self._set_estado_colecciones("Preparando reproductor interno")
        self.agregar_log(f"Preparando reproducción interna desde colección: {video.get('titulo', 'Sin título')}")
        try:
            dialogo = DialogoReproductor(self, self.descargador, url, video, self.configuracion)
            dialogo.ShowModal()
            dialogo.Destroy()
            self.notebook.SetSelection(2)
            indice = self._indice_video_coleccion()
            if indice is not None:
                self.lista_videos_coleccion.Select(indice)
                self.lista_videos_coleccion.Focus(indice)
            self.lista_videos_coleccion.SetFocus()
            self._set_estado_colecciones("Reproductor cerrado. Lista de videos lista.")
        except Exception as exc:
            self._mostrar_error_detallado("Error en reproductor", exc)

    def copiar_url_video_coleccion(self, video=None):
        video = video or self._video_enfocado_coleccion()
        if not video:
            return
        url = video.get("url", "").strip()
        if not url:
            hablar_async("El video no tiene URL")
            return
        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Close()
                self._set_estado_colecciones("URL del video copiada al portapapeles")
                hablar_async("URL copiada")
        except Exception:
            try:
                wx.TheClipboard.Close()
            except Exception:
                pass
            self._mostrar_error_detallado("Error", "No se pudo copiar la URL.")

    def _mostrar_texto_dialogo(self, titulo, texto, nombre_control="Texto"):
        dialogo = wx.Dialog(self, title=titulo, size=(720, 460))
        sizer = wx.BoxSizer(wx.VERTICAL)
        cuadro = wx.TextCtrl(dialogo, value=texto, style=wx.TE_MULTILINE | wx.TE_READONLY)
        cuadro.SetName(nombre_control)
        sizer.Add(cuadro, 1, wx.EXPAND | wx.ALL, 10)
        btn = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn.SetName("Aceptar")
        sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        cuadro.SetFocus()
        hablar_async(titulo, limpiar=True)
        dialogo.ShowModal()
        dialogo.Destroy()

    def probar_voz_accesible(self, evento=None):
        mensaje = "Prueba de voz accesible. Si escucha este mensaje, la voz funciona correctamente."

        try:
            self.SetStatusText("Probando voz accesible")
        except Exception:
            pass

        try:
            self.estado.SetValue("Probando voz accesible")
        except Exception:
            pass

        hablar_async(mensaje, limpiar=True)

        wx.MessageBox(
            traducir_clave("__voice.test.body__").format(metodo=metodo_activo_voz()),
            "Probar voz accesible",
            wx.OK | wx.ICON_INFORMATION,
        )

    def mostrar_diagnostico_voz(self, evento=None):
        texto = diagnostico_voz()
        dialogo = wx.Dialog(self, title="Diagnóstico de voz accesible", size=(760, 500))
        sizer = wx.BoxSizer(wx.VERTICAL)
        cuadro = wx.TextCtrl(
            dialogo,
            value=texto,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        cuadro.SetName("Texto de diagnóstico de voz accesible")
        sizer.Add(cuadro, 1, wx.EXPAND | wx.ALL, 10)
        btn = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn.SetName("Aceptar diagnóstico")
        sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        cuadro.SetFocus()
        dialogo.ShowModal()
        dialogo.Destroy()

    def mostrar_diagnostico_reproductor(self, evento=None):
        texto = diagnostico_reproductor()
        self.agregar_log("Diagnóstico de reproductor interno consultado")
        dialogo = wx.Dialog(self, title="Diagnóstico de reproductor interno", size=(820, 540))
        sizer = wx.BoxSizer(wx.VERTICAL)
        cuadro = wx.TextCtrl(
            dialogo,
            value=texto,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        cuadro.SetName("Texto de diagnóstico de reproductor interno")
        sizer.Add(cuadro, 1, wx.EXPAND | wx.ALL, 10)
        btn = wx.Button(dialogo, wx.ID_OK, label="Aceptar")
        btn.SetName("Aceptar diagnóstico de reproductor")
        sizer.Add(btn, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialogo.SetSizer(sizer)
        dialogo.SetAffirmativeId(wx.ID_OK)
        cuadro.SetFocus()
        dialogo.ShowModal()
        dialogo.Destroy()

    def mostrar_historial(self, evento=None):
        registros = leer_historial()

        if not registros:
            self._mostrar_mensaje_accesible("Historial", "Todavía no hay historial de descargas.", wx.ICON_INFORMATION)
            return

        lineas = []

        for indice, registro in enumerate(registros, start=1):
            lineas.append(
                f"{indice}. {registro.get('titulo', traducir('Sin título'))}\n"
                f"   {traducir('Canal:')} {registro.get('canal', traducir('No disponible'))}\n"
                f"   {traducir('Fecha:')} {registro.get('fecha', traducir('No disponible'))}\n"
                f"   {traducir('Formato:')} {registro.get('formato', '')} {registro.get('calidad', '')}\n"
                f"   {traducir('Carpeta:')} {registro.get('carpeta', '')}\n"
                f"   {traducir('URL:')} {registro.get('url', '')}\n"
            )

        dialogo = wx.Dialog(self, title="Historial de descargas", size=(760, 520))
        sizer = wx.BoxSizer(wx.VERTICAL)

        texto = wx.TextCtrl(
            dialogo,
            value="\n".join(lineas),
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        sizer.Add(texto, 1, wx.EXPAND | wx.ALL, 10)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        btn_abrir_archivo = wx.Button(dialogo, label="Abrir carpeta de historial")
        btn_limpiar = wx.Button(dialogo, label="Limpiar historial")
        btn_cerrar = wx.Button(dialogo, label="Cerrar")

        btn_abrir_archivo.Bind(wx.EVT_BUTTON, lambda evento: self._abrir_archivo_historial())
        btn_limpiar.Bind(wx.EVT_BUTTON, lambda evento: (dialogo.EndModal(wx.ID_OK), self._limpiar_historial()))
        btn_cerrar.Bind(wx.EVT_BUTTON, lambda evento: dialogo.Close())

        fila.Add(btn_abrir_archivo, 0, wx.ALL, 5)
        fila.Add(btn_limpiar, 0, wx.ALL, 5)
        fila.Add(btn_cerrar, 0, wx.ALL, 5)
        sizer.Add(fila, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        dialogo.SetSizer(sizer)
        dialogo.ShowModal()
        dialogo.Destroy()

    def _limpiar_historial(self, evento=None):
        respuesta = wx.MessageBox(
            traducir("¿Está seguro de que desea eliminar todo el historial de descargas? Esta acción no eliminará las canciones descargadas."),
            traducir("Confirmar limpieza del historial"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if respuesta != wx.YES:
            hablar_async("Limpieza de historial cancelada", limpiar=True)
            return
        if limpiar_historial():
            self._mostrar_mensaje_accesible(
                "Historial",
                "El historial de descargas se limpió correctamente. Las canciones descargadas no fueron eliminadas.",
                wx.ICON_INFORMATION,
            )
        else:
            self._mostrar_error_detallado("Error", "No fue posible limpiar el historial de descargas.")

    def _abrir_archivo_historial(self, evento=None):
        try:
            HISTORIAL_ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
            if not HISTORIAL_ARCHIVO.exists():
                HISTORIAL_ARCHIVO.write_text("", encoding="utf-8")
            abrir_carpeta(str(HISTORIAL_ARCHIVO.parent))
        except Exception:
            self._mostrar_error_detallado("Error", "No fue posible abrir el historial.")

    def guardar_configuracion(self):
        guardar_configuracion(
            self.carpeta.GetValue().strip(),
            self.formato.GetStringSelection(),
            self._calidad_seleccionada(),
            opciones=self.configuracion,
        )

    def cerrar_programa(self, evento):
        if self._cerrando:
            try:
                if evento.CanVeto():
                    evento.Veto()
            except Exception:
                pass
            return

        if self.descarga_activa:
            respuesta = wx.MessageBox(
                "Hay una descarga en curso. ¿Desea cancelar y salir?",
                "Confirmar salida",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            if respuesta != wx.YES:
                if evento.CanVeto():
                    evento.Veto()
                return
            self.descargador.cancelar()

        self._cerrando = True
        self.guardar_configuracion()
        try:
            if evento.CanVeto():
                evento.Veto()
        except Exception:
            pass
        try:
            self.Enable(False)
        except Exception:
            pass
        self._sonido("cierre", esperar=True)
        hablar_cierre(
            traducir_formato(
                "Gracias por utilizar {app}. Desarrollado por Nicolás Alfaro.",
                app=APP_NOMBRE,
            ),
            limpiar=True,
        )
        # Mantener el proceso vivo mientras el lector termina la despedida.
        # 1,8 segundos resultaron insuficientes en pruebas reales con NVDA.
        try:
            self.SetStatusText(
                traducir_formato(
                    "Gracias por utilizar {app}. Desarrollado por Nicolás Alfaro.",
                    app=APP_NOMBRE,
                )
            )
        except Exception:
            pass
        wx.CallLater(5500, self.Destroy)


def iniciar():
    app = wx.App(False)
    ventana = Ventana()
    ventana.Show()
    # Esperar a que Windows y el lector de pantalla terminen de presentar
    # la ventana antes de anunciar la bienvenida personalizada.
    wx.CallLater(650, ventana.iniciar_experiencia_accesible)
    app.MainLoop()
