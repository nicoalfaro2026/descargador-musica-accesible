import json
import sys
import types
from pathlib import Path

LANGUAGES = {
    "es": "Español",
    "en": "English",
    "pt": "Português",
    "fr": "Français",
    "it": "Italiano",
    "ru": "Ruso / Русский",
}

_current_language = None
_wx_patched = False
_cache = {}


def _base_dir():
    """Carpeta escribible del programa.

    En modo EXE debe apuntar a la carpeta donde está el ejecutable,
    porque allí se guarda la configuración del usuario en la carpeta datos.
    """
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _config_path():
    return _base_dir() / "datos" / "configuracion.json"


def _rutas_recurso(nombre):
    """Devuelve rutas posibles para recursos incluidos con PyInstaller.

    En modo Python los recursos están junto a los .py.
    En EXE modo carpeta, PyInstaller suele colocarlos dentro de _internal.
    En algunos modos también están disponibles mediante sys._MEIPASS.
    """
    rutas = []
    base = _base_dir()
    rutas.append(base / nombre)
    rutas.append(base / "_internal" / nombre)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        rutas.append(Path(meipass) / nombre)

    rutas.append(Path(__file__).resolve().parent / nombre)

    # Quitar duplicados manteniendo el orden.
    vistas = set()
    unicas = []
    for ruta in rutas:
        try:
            clave = str(ruta.resolve())
        except Exception:
            clave = str(ruta)
        if clave not in vistas:
            vistas.add(clave)
            unicas.append(ruta)
    return unicas


def _idiomas_dir():
    for ruta in _rutas_recurso("idiomas"):
        if ruta.exists():
            return ruta
    return _base_dir() / "idiomas"


def idioma_actual():
    global _current_language
    if _current_language:
        return _current_language
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            datos = json.load(f)
        idioma = datos.get("idioma", "es")
    except Exception:
        idioma = "es"
    if idioma not in LANGUAGES:
        idioma = "es"
    _current_language = idioma
    return idioma


def establecer_idioma(idioma):
    global _current_language
    if idioma not in LANGUAGES:
        idioma = "es"
    _current_language = idioma
    return idioma


def _cargar_diccionario(idioma):
    if idioma in _cache:
        return _cache[idioma]
    ruta = _idiomas_dir() / f"{idioma}.json"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, dict):
            datos = {}
    except Exception:
        datos = {}
    _cache[idioma] = datos
    return datos


def traducir(texto, idioma=None):
    if texto is None:
        return texto
    idioma = idioma or idioma_actual()
    texto = str(texto)
    if idioma == "es":
        return texto
    dic = _cargar_diccionario(idioma)
    if texto in dic:
        return dic[texto]
    # Reemplazo por fragmentos largos sobre el texto original, sin volver a
    # traducir dentro de lo ya reemplazado. Esto evita errores como duplicar
    # letras cuando una palabra traducida contiene otra clave del diccionario.
    claves = [k for k in sorted(dic.keys(), key=len, reverse=True) if k]
    resultado = []
    i = 0
    largo = len(texto)
    while i < largo:
        encontrada = None
        for origen in claves:
            if texto.startswith(origen, i):
                encontrada = origen
                break
        if encontrada:
            resultado.append(str(dic[encontrada]))
            i += len(encontrada)
        else:
            resultado.append(texto[i])
            i += 1
    return "".join(resultado)


def traducir_dinamico(texto, idioma=None):
    return traducir(texto, idioma=idioma)


def traducir_lista(valores, idioma=None):
    return [traducir(v, idioma=idioma) for v in valores]


def traducir_clave(clave, idioma=None, default=None):
    """Obtiene un texto por clave estable del catálogo de idiomas.

    Las claves estables comienzan normalmente con ``__`` y se usan para
    textos largos o mensajes con formato que no conviene buscar por
    fragmentos. Esto permite que una persona traductora edite los JSON sin
    tocar el código fuente.
    """
    idioma = idioma or idioma_actual()
    dic = _cargar_diccionario(idioma)
    if clave in dic:
        return str(dic[clave])

    # El español también tiene un catálogo explícito para servir de base
    # a traductores y a las comprobaciones automáticas del repositorio.
    if idioma != "es":
        dic_es = _cargar_diccionario("es")
        if clave in dic_es:
            return str(dic_es[clave])

    return str(default if default is not None else clave)


def traducir_formato(texto, idioma=None, **valores):
    """Traduce una plantilla completa y después sustituye sus valores.

    Es preferible a traducir un f-string ya construido porque mantiene
    intacto el orden de las palabras de cada idioma.
    """
    plantilla = traducir(texto, idioma=idioma)
    try:
        return plantilla.format(**valores)
    except Exception:
        try:
            return str(texto).format(**valores)
        except Exception:
            return plantilla


def _categoria_plural(valor, idioma):
    try:
        n = abs(int(valor))
    except Exception:
        n = 0
    if idioma == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    return "one" if n == 1 else "many"


def formatear_duracion(segundos, idioma=None):
    """Devuelve una duración legible y localizada para el lector de pantalla."""
    if segundos is None:
        return traducir("No disponible", idioma=idioma)

    idioma = idioma or idioma_actual()
    try:
        total = int(max(0, segundos))
    except Exception:
        total = 0

    horas = total // 3600
    minutos = (total % 3600) // 60
    seg = total % 60

    def unidad(valor, nombre):
        categoria = _categoria_plural(valor, idioma)
        clave = f"__time.{nombre}.{categoria}__"
        # Idiomas sin forma 'few' usan la forma plural normal.
        texto_unidad = traducir_clave(clave, idioma=idioma, default=None)
        if texto_unidad in (clave, "None", "") and categoria == "few":
            texto_unidad = traducir_clave(f"__time.{nombre}.many__", idioma=idioma, default=nombre)
        return f"{valor} {texto_unidad}"

    partes = []
    if horas:
        partes.append(unidad(horas, "hour"))
    if minutos or horas:
        partes.append(unidad(minutos, "minute"))
    partes.append(unidad(seg, "second"))

    if len(partes) == 1:
        return partes[0]
    if len(partes) == 2:
        conj = traducir_clave("__time.and__", idioma=idioma, default="y")
        return f"{partes[0]} {conj} {partes[1]}"
    conj = traducir_clave("__time.and__", idioma=idioma, default="y")
    return f"{', '.join(partes[:-1])} {conj} {partes[-1]}"


def activar_wx(wx):
    global _wx_patched
    if _wx_patched:
        return
    _wx_patched = True

    orig_message_box = wx.MessageBox
    def message_box(message, caption="Mensaje", style=wx.OK | wx.CENTRE, parent=None, x=wx.DefaultCoord, y=wx.DefaultCoord):
        return orig_message_box(traducir(message), traducir(caption), style, parent, x, y)
    wx.MessageBox = message_box

    orig_static_text = wx.StaticText
    def static_text(*args, **kwargs):
        if "label" in kwargs:
            kwargs["label"] = traducir(kwargs["label"])
        elif len(args) >= 3 and isinstance(args[2], str):
            args = list(args)
            args[2] = traducir(args[2])
        return orig_static_text(*args, **kwargs)
    wx.StaticText = static_text

    orig_button = wx.Button
    def button(*args, **kwargs):
        if "label" in kwargs:
            kwargs["label"] = traducir(kwargs["label"])
        elif len(args) >= 3 and isinstance(args[2], str):
            args = list(args)
            args[2] = traducir(args[2])
        return orig_button(*args, **kwargs)
    wx.Button = button

    orig_checkbox = wx.CheckBox
    def checkbox(*args, **kwargs):
        if "label" in kwargs:
            kwargs["label"] = traducir(kwargs["label"])
        elif len(args) >= 3 and isinstance(args[2], str):
            args = list(args)
            args[2] = traducir(args[2])
        return orig_checkbox(*args, **kwargs)
    wx.CheckBox = checkbox

    orig_choice = wx.Choice
    def choice(*args, **kwargs):
        original_choices = None
        if "choices" in kwargs and kwargs["choices"] is not None:
            original_choices = [str(x) for x in kwargs["choices"]]
            kwargs["choices"] = traducir_lista(original_choices)
        elif len(args) >= 3 and isinstance(args[2], (list, tuple)):
            args = list(args)
            original_choices = [str(x) for x in args[2]]
            args[2] = traducir_lista(original_choices)
        obj = orig_choice(*args, **kwargs)
        if original_choices is not None:
            translated_choices = traducir_lista(original_choices)
            obj._i18n_original_choices = original_choices
            obj._i18n_translated_choices = translated_choices
            orig_get = obj.GetStringSelection
            orig_set = obj.SetStringSelection
            def get_string_selection(self):
                try:
                    sel = self.GetSelection()
                    if 0 <= sel < len(self._i18n_original_choices):
                        return self._i18n_original_choices[sel]
                except Exception:
                    pass
                return orig_get()
            def set_string_selection(self, value):
                try:
                    value = str(value)
                    if value in self._i18n_original_choices:
                        return orig_set(self._i18n_translated_choices[self._i18n_original_choices.index(value)])
                    if value in self._i18n_translated_choices:
                        return orig_set(value)
                except Exception:
                    pass
                return orig_set(value)
            obj.GetStringSelection = types.MethodType(get_string_selection, obj)
            obj.SetStringSelection = types.MethodType(set_string_selection, obj)
        return obj
    wx.Choice = choice

    orig_static_box = wx.StaticBox
    def static_box(*args, **kwargs):
        if "label" in kwargs:
            kwargs["label"] = traducir(kwargs["label"])
        elif len(args) >= 3 and isinstance(args[2], str):
            args = list(args)
            args[2] = traducir(args[2])
        return orig_static_box(*args, **kwargs)
    wx.StaticBox = static_box

    orig_dialog = wx.Dialog
    class Dialog(orig_dialog):
        def __init__(self, *args, **kwargs):
            if "title" in kwargs:
                kwargs["title"] = traducir(kwargs["title"])
            elif len(args) >= 2 and isinstance(args[1], str):
                args = list(args)
                args[1] = traducir(args[1])
            super().__init__(*args, **kwargs)
    wx.Dialog = Dialog

    orig_dir_dialog = wx.DirDialog
    def dir_dialog(*args, **kwargs):
        if len(args) >= 2 and isinstance(args[1], str):
            args = list(args)
            args[1] = traducir(args[1])
        if "message" in kwargs:
            kwargs["message"] = traducir(kwargs["message"])
        return orig_dir_dialog(*args, **kwargs)
    wx.DirDialog = dir_dialog

    orig_menu_append = wx.Menu.Append
    def menu_append(self, *args, **kwargs):
        args = list(args)
        if len(args) >= 2 and isinstance(args[1], str):
            args[1] = traducir(args[1])
        if "item" in kwargs and isinstance(kwargs["item"], str):
            kwargs["item"] = traducir(kwargs["item"])
        if "helpString" in kwargs and isinstance(kwargs["helpString"], str):
            kwargs["helpString"] = traducir(kwargs["helpString"])
        return orig_menu_append(self, *args, **kwargs)
    wx.Menu.Append = menu_append

    if hasattr(wx.Menu, "AppendRadioItem"):
        orig_append_radio = wx.Menu.AppendRadioItem
        def append_radio_item(self, id, item, *args, **kwargs):
            # Los nombres de idiomas se dejan en su forma nativa para que el usuario los reconozca.
            return orig_append_radio(self, id, item, *args, **kwargs)
        wx.Menu.AppendRadioItem = append_radio_item

    orig_menubar_append = wx.MenuBar.Append
    def menubar_append(self, menu, title):
        return orig_menubar_append(self, menu, traducir(title))
    wx.MenuBar.Append = menubar_append

    orig_append_submenu = getattr(wx.Menu, "AppendSubMenu", None)
    if orig_append_submenu:
        def append_submenu(self, submenu, text, *args, **kwargs):
            return orig_append_submenu(self, submenu, traducir(text), *args, **kwargs)
        wx.Menu.AppendSubMenu = append_submenu

    orig_add_page = wx.Notebook.AddPage
    def add_page(self, page, text, *args, **kwargs):
        return orig_add_page(self, page, traducir(text), *args, **kwargs)
    wx.Notebook.AddPage = add_page

    orig_insert_column = wx.ListCtrl.InsertColumn
    def insert_column(self, col, heading, *args, **kwargs):
        return orig_insert_column(self, col, traducir(heading), *args, **kwargs)
    wx.ListCtrl.InsertColumn = insert_column

    orig_set_name = wx.Window.SetName
    def set_name(self, name):
        return orig_set_name(self, traducir(name))
    wx.Window.SetName = set_name

    orig_set_label = wx.Window.SetLabel
    def set_label(self, label):
        return orig_set_label(self, traducir(label))
    wx.Window.SetLabel = set_label

    try:
        orig_frame_set_status = wx.Frame.SetStatusText
        def set_status_text(self, text, *args, **kwargs):
            return orig_frame_set_status(self, traducir(text), *args, **kwargs)
        wx.Frame.SetStatusText = set_status_text
    except Exception:
        pass
