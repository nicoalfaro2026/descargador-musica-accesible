import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from functools import lru_cache
from pathlib import Path

try:
    from config import BASE_DIR, DATA_DIR, VERSION
except Exception:  # Evita fallos si se importa muy temprano.
    BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "datos"
    VERSION = "1.8.0"

URL_YTDLP_EXE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
NOMBRE_MOTOR = "yt-dlp.exe"


def _normalizar(ruta):
    try:
        return str(Path(ruta).resolve())
    except Exception:
        return str(ruta)


def _agregar_unico(lista, carpeta):
    if not carpeta:
        return
    carpeta = _normalizar(carpeta)
    if carpeta not in lista:
        lista.append(carpeta)


def carpetas_posibles_motor():
    carpetas = []

    # Un motor actualizado en datos tiene prioridad. Esto permite actualizar
    # incluso si Windows no deja sobrescribir el yt-dlp.exe incluido con la app.
    _agregar_unico(carpetas, DATA_DIR)

    if getattr(sys, "frozen", False):
        _agregar_unico(carpetas, Path(sys.executable).resolve().parent)
        _agregar_unico(carpetas, getattr(sys, "_MEIPASS", ""))
    else:
        _agregar_unico(carpetas, Path(__file__).resolve().parent)

    _agregar_unico(carpetas, BASE_DIR)
    _agregar_unico(carpetas, os.getcwd())

    bases = list(carpetas)
    for base in bases:
        base = Path(base)
        _agregar_unico(carpetas, base / "_internal")
        _agregar_unico(carpetas, base / "bin")
        _agregar_unico(carpetas, base / "motor")
        _agregar_unico(carpetas, base / "ytdlp")
        _agregar_unico(carpetas, base / "_internal" / "bin")
        _agregar_unico(carpetas, base / "_internal" / "motor")
        _agregar_unico(carpetas, base / "_internal" / "ytdlp")

    return carpetas




@lru_cache(maxsize=16)
def _salida_version_runtime(ruta):
    try:
        resultado = subprocess.run(
            [str(ruta), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if resultado.returncode == 0:
            return (resultado.stdout or resultado.stderr or "").strip()
    except Exception:
        pass
    return ""


def _tupla_version(texto):
    import re
    match = re.search(r"(?:^|\s|v)(\d+)\.(\d+)(?:\.(\d+))?", str(texto or ""), re.I)
    if not match:
        return None
    return tuple(int(x or 0) for x in match.groups())


def _runtime_compatible(nombre, ruta):
    salida = _salida_version_runtime(str(ruta))
    if not salida:
        return False
    version = _tupla_version(salida)
    if nombre == "deno":
        return bool(version and version >= (2, 3, 0))
    if nombre == "node":
        return bool(version and version >= (22, 0, 0))
    # QuickJS usa versiones por fecha y variantes NG; si responde --version,
    # dejamos que yt-dlp haga la validación fina.
    return True


def buscar_runtime_javascript():
    """Busca un runtime JavaScript compatible con yt-dlp.

    YouTube usa desafíos JavaScript que las versiones modernas de yt-dlp
    resuelven con Deno, Node o QuickJS. Deno es la opción preferida.
    Devuelve un diccionario con nombre/ruta/argumento, o None.
    """
    candidatos = [
        ("deno", "deno.exe" if os.name == "nt" else "deno"),
        ("node", "node.exe" if os.name == "nt" else "node"),
        ("quickjs", "qjs.exe" if os.name == "nt" else "qjs"),
    ]

    carpetas = carpetas_posibles_motor()
    for nombre, ejecutable in candidatos:
        for carpeta in carpetas:
            ruta = Path(carpeta) / ejecutable
            if ruta.exists() and ruta.is_file() and _runtime_compatible(nombre, str(ruta)):
                return {"nombre": nombre, "ruta": str(ruta), "argumento": f"{nombre}:{ruta}"}

        ruta_path = shutil.which(ejecutable) or shutil.which(nombre)
        if ruta_path and _runtime_compatible(nombre, ruta_path):
            return {"nombre": nombre, "ruta": ruta_path, "argumento": f"{nombre}:{ruta_path}"}

    return None


def argumentos_runtime_javascript_cli():
    runtime = buscar_runtime_javascript()
    if not runtime:
        return []
    return ["--js-runtimes", runtime["argumento"]]


def version_runtime_javascript():
    runtime = buscar_runtime_javascript()
    if not runtime:
        return None
    salida = _salida_version_runtime(runtime["ruta"])
    primera = salida.splitlines() if salida else []
    return primera[0].strip() if primera else runtime["nombre"]


def buscar_motor_descarga():
    """Devuelve la ruta de yt-dlp.exe si existe, o None si no existe."""
    nombres = [NOMBRE_MOTOR]
    if os.name != "nt":
        nombres.append("yt-dlp")

    for carpeta in carpetas_posibles_motor():
        for nombre in nombres:
            ruta = Path(carpeta) / nombre
            if ruta.exists() and ruta.is_file():
                return str(ruta)

    return None


def _ejecutar_version(ruta):
    try:
        resultado = subprocess.run(
            [ruta, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if resultado.returncode == 0:
            return (resultado.stdout or "").strip() or "Detectado"
        return f"Error consultando versión: {(resultado.stderr or resultado.stdout or '').strip()}"
    except Exception as exc:
        return f"Error consultando versión: {exc}"


def version_motor_externo():
    ruta = buscar_motor_descarga()
    if not ruta:
        return None
    return _ejecutar_version(ruta)


def version_libreria_interna():
    try:
        import yt_dlp
        return getattr(yt_dlp.version, "__version__", "Detectada")
    except Exception as exc:
        return f"No disponible: {exc}"


def _ruta_objetivo_preferida():
    existente = buscar_motor_descarga()
    if existente:
        return Path(existente)

    # En modo PyInstaller carpeta, suele existir _internal. Si existe, guardamos ahí.
    if getattr(sys, "frozen", False):
        carpeta_exe = Path(sys.executable).resolve().parent
        internal = carpeta_exe / "_internal"
        if internal.exists():
            return internal / NOMBRE_MOTOR
        return carpeta_exe / NOMBRE_MOTOR

    return Path(__file__).resolve().parent / NOMBRE_MOTOR


def _descargar_archivo(url, destino_tmp, callback=None):
    if callback:
        from i18n import traducir
        callback(traducir("Descargando motor de descarga"))

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"DescargadorMusicaAccesible/{VERSION}"},
    )

    with urllib.request.urlopen(req, timeout=90) as respuesta, open(destino_tmp, "wb") as salida:
        total = respuesta.headers.get("Content-Length")
        try:
            total = int(total) if total else 0
        except Exception:
            total = 0

        descargado = 0
        ultimo = -1
        while True:
            bloque = respuesta.read(1024 * 512)
            if not bloque:
                break
            salida.write(bloque)
            descargado += len(bloque)
            if callback and total:
                porcentaje = int((descargado / total) * 100)
                porcentaje_redondo = (porcentaje // 10) * 10
                if porcentaje_redondo != ultimo and porcentaje_redondo > 0:
                    ultimo = porcentaje_redondo
                    from i18n import traducir_formato
                    callback(traducir_formato("Descargando motor {porcentaje} por ciento", porcentaje=porcentaje_redondo))


def actualizar_motor_descarga(callback=None):
    """
    Descarga el ejecutable oficial yt-dlp.exe y lo coloca en la carpeta del programa.
    No usa pip y no llama a sys.executable, para evitar abrir otra instancia del programa.
    """
    objetivo = _ruta_objetivo_preferida()
    objetivo.parent.mkdir(parents=True, exist_ok=True)

    if callback:
        from i18n import traducir
        callback(traducir("Buscando actualización del motor de descarga"))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / "yt-dlp_nuevo.exe"
        _descargar_archivo(URL_YTDLP_EXE, tmp, callback=callback)

        if not tmp.exists() or tmp.stat().st_size < 1024 * 1024:
            raise RuntimeError("La descarga del motor parece incompleta.")

        if callback:
            callback("Verificando motor descargado")

        version_nueva = _ejecutar_version(str(tmp))
        if version_nueva.startswith("Error"):
            raise RuntimeError(version_nueva)

        respaldo = objetivo.with_suffix(".exe.bak") if objetivo.suffix.lower() == ".exe" else objetivo.with_name(objetivo.name + ".bak")

        try:
            if objetivo.exists():
                try:
                    if respaldo.exists():
                        respaldo.unlink()
                    shutil.copy2(objetivo, respaldo)
                except Exception:
                    pass

            shutil.copy2(tmp, objetivo)
        except PermissionError:
            # Si no se puede escribir al lado del EXE, se usa datos como alternativa.
            alternativa = Path(DATA_DIR) / NOMBRE_MOTOR
            alternativa.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp, alternativa)
            objetivo = alternativa
        except Exception:
            # Si hubo un problema reemplazando el motor, intenta restaurar el respaldo.
            try:
                if respaldo.exists():
                    shutil.copy2(respaldo, objetivo)
            except Exception:
                pass
            raise

    # Verificación final del archivo ya instalado.
    version_instalada = _ejecutar_version(str(objetivo))
    if version_instalada.startswith("Error"):
        try:
            if respaldo.exists():
                shutil.copy2(respaldo, objetivo)
        except Exception:
            pass
        raise RuntimeError("El motor descargado no quedó operativo después de instalarse.")

    try:
        if respaldo.exists():
            respaldo.unlink()
    except Exception:
        pass

    if callback:
        callback("Motor de descarga actualizado correctamente")

    version_nueva = version_instalada
    return {
        "ruta": str(objetivo),
        "version": version_nueva,
    }




def version_mas_reciente_disponible(timeout=15):
    """Consulta la versión más reciente publicada de yt-dlp.

    Devuelve una cadena como 2026.03.17 o None si no se pudo consultar.
    """
    try:
        import json
        req = urllib.request.Request(
            "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
            headers={"User-Agent": f"DescargadorMusicaAccesible/{VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", errors="replace"))
        etiqueta = str(datos.get("tag_name", "")).strip()
        if etiqueta.startswith("yt-dlp@"):
            etiqueta = etiqueta.split("@", 1)[1]
        if etiqueta.startswith("v"):
            etiqueta = etiqueta[1:]
        return etiqueta or None
    except Exception:
        return None


def version_instalada_actual():
    """Devuelve una versión válida del motor externo o interno, o None."""
    externa = version_motor_externo()
    if externa and not str(externa).startswith("Error"):
        return externa

    interna = version_libreria_interna()
    if interna and not str(interna).startswith("No disponible"):
        return interna

    return None

def diagnostico_motor_descarga():
    from i18n import traducir, traducir_dinamico, traducir_formato

    ruta = buscar_motor_descarga()
    version_externa = version_motor_externo() if ruta else None
    version_interna = version_libreria_interna()

    lineas = [traducir("Motor de descarga"), ""]

    if ruta and version_externa and not str(version_externa).startswith("Error"):
        lineas.extend([
            traducir("Estado: instalado y operativo."),
            traducir_formato("Versión actual: {version}", version=version_externa),
            traducir_formato("Ruta yt-dlp: {ruta}", ruta=ruta),
            "",
            traducir("El programa usará este motor para buscar, reproducir y descargar."),
        ])
    elif ruta:
        lineas.extend([
            traducir("Estado: archivo yt-dlp detectado, pero no se pudo ejecutar para consultar su versión."),
            traducir_formato("Detalle: {detalle}", detalle=traducir_dinamico(version_externa or traducir("No disponible"))),
            traducir_formato("Ruta yt-dlp: {ruta}", ruta=ruta),
            "",
            traducir("En Windows el programa volverá a comprobar este ejecutable al usarlo."),
        ])
    else:
        lineas.extend([
            traducir("Estado: usando motor interno del programa."),
            traducir_formato("Versión interna: {version}", version=version_interna),
            "",
            traducir("Para instalar o actualizar el motor externo, use Herramientas, Actualizar librería de descarga."),
        ])

    runtime = buscar_runtime_javascript()
    lineas.append("")
    if runtime:
        version_runtime = version_runtime_javascript()
        lineas.append(traducir_formato("Motor JavaScript: {version} detectado.", version=version_runtime or runtime["nombre"]))
        lineas.append(traducir_formato("Ruta JavaScript: {ruta}", ruta=runtime["ruta"]))
    else:
        lineas.extend([
            traducir("Motor JavaScript: no detectado."),
            traducir("YouTube puede fallar en algunos videos hasta disponer de Deno, Node 22 o QuickJS compatible."),
        ])

    lineas.append("")
    try:
        from motor_pytubefix import detalle_disponibilidad
        lineas.append(traducir_formato("Motor alternativo: {detalle}.", detalle=detalle_disponibilidad()))
    except Exception:
        lineas.append(traducir("Motor alternativo: pytubefix no disponible."))

    lineas.extend([
        "",
        traducir("Orden automático: yt-dlp primero; pytubefix solo se usa como respaldo ante fallos compatibles."),
        traducir("Los detalles técnicos de cada intento se guardan en logs/descargador.log."),
    ])

    return "\n".join(lineas)
