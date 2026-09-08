# -*- coding: utf-8 -*-
"""Integración con el menú "Abrir con" de Windows.

Esto permite que, al hacer clic derecho (o presionar la tecla Aplicaciones)
sobre una canción, aparezca la opción "Reproducir con Descargador de Música
Accesible". No cambia el reproductor predeterminado del sistema: solo
agrega el programa como una opción más dentro de "Abrir con", para quien
quiera usarlo así.

Todo se guarda únicamente en el registro de Windows del usuario actual
(HKEY_CURRENT_USER), así que no hace falta ser administrador y no afecta a
otras cuentas de la misma computadora.
"""
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # Este módulo solo tiene sentido en Windows.
    winreg = None

NOMBRE_APP_REGISTRO = "DescargadorMusicaAccesible.exe"
NOMBRE_AMIGABLE = "Descargador de Música Accesible"
EXTENSIONES_SOPORTADAS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma")

RAIZ_REGISTRO = f"Software\\Classes\\Applications\\{NOMBRE_APP_REGISTRO}"


def _base_programa():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _comando_apertura():
    """Arma la línea de comando que Windows debe ejecutar al elegir
    "Reproducir con Descargador de Música Accesible" sobre un archivo."""
    if getattr(sys, "frozen", False):
        ejecutable = str(Path(sys.executable).resolve())
        return f'"{ejecutable}" --reproducir-rapido "%1"'

    base = _base_programa()
    interprete = Path(sys.executable)
    # En modo desarrollo, se prefiere pythonw.exe (sin consola) si existe
    # junto al intérprete que se está usando.
    candidato_pythonw = interprete.parent / "pythonw.exe"
    interprete_final = candidato_pythonw if candidato_pythonw.exists() else interprete
    main_py = base / "main.py"
    return f'"{interprete_final}" "{main_py}" --reproducir-rapido "%1"'


def registrar():
    """Agrega el programa a la lista de "Abrir con" de Windows para los
    formatos de audio soportados. Se puede llamar varias veces sin problema
    (vuelve a escribir las mismas claves)."""
    if winreg is None:
        raise RuntimeError("Esta función solo está disponible en Windows.")

    comando = _comando_apertura()

    clave = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RAIZ_REGISTRO)
    try:
        winreg.SetValueEx(clave, "FriendlyAppName", 0, winreg.REG_SZ, NOMBRE_AMIGABLE)
    finally:
        winreg.CloseKey(clave)

    clave_comando = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RAIZ_REGISTRO + "\\shell\\open\\command")
    try:
        winreg.SetValueEx(clave_comando, "", 0, winreg.REG_SZ, comando)
    finally:
        winreg.CloseKey(clave_comando)

    clave_tipos = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RAIZ_REGISTRO + "\\SupportedTypes")
    try:
        for extension in EXTENSIONES_SOPORTADAS:
            winreg.SetValueEx(clave_tipos, extension, 0, winreg.REG_SZ, "")
    finally:
        winreg.CloseKey(clave_tipos)

    return True


def registrado():
    """Indica si el programa ya está agregado al menú Abrir con de Windows."""
    if winreg is None:
        return False
    try:
        clave = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RAIZ_REGISTRO + "\\shell\\open\\command")
        winreg.CloseKey(clave)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _borrar_arbol_registro(hive, ruta):
    """Borra una clave del registro y todas sus subclaves, sin fallar si
    alguna parte ya no existe."""
    if winreg is None:
        return
    try:
        clave = winreg.OpenKey(hive, ruta, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    except Exception:
        return

    subclaves = []
    try:
        indice = 0
        while True:
            try:
                subclaves.append(winreg.EnumKey(clave, indice))
                indice += 1
            except OSError:
                break
    finally:
        winreg.CloseKey(clave)

    for subclave in subclaves:
        _borrar_arbol_registro(hive, ruta + "\\" + subclave)

    try:
        winreg.DeleteKey(hive, ruta)
    except Exception:
        pass


def quitar_registro():
    """Quita la integración agregada por registrar(), si existe."""
    if winreg is None:
        raise RuntimeError("Esta función solo está disponible en Windows.")
    _borrar_arbol_registro(winreg.HKEY_CURRENT_USER, RAIZ_REGISTRO)
    return True
