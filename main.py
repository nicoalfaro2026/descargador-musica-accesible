import sys


def _argumento_reproduccion_rapida():
    """Si el programa se abrió para reproducir un archivo directamente
    (por ejemplo, con "Reproducir con Descargador de Música Accesible"
    desde el menú Abrir con de Windows), devuelve la ruta de ese archivo."""
    argumentos = sys.argv[1:]
    if "--reproducir-rapido" in argumentos:
        indice = argumentos.index("--reproducir-rapido")
        if indice + 1 < len(argumentos):
            return argumentos[indice + 1]
    return None


if __name__ == "__main__":
    _ruta_reproduccion_rapida = _argumento_reproduccion_rapida()
    if _ruta_reproduccion_rapida:
        # Camino rápido: solo se importa lo indispensable para reproducir,
        # sin la ventana principal ni la bienvenida hablada.
        from reproductor import reproducir_rapido

        reproducir_rapido(_ruta_reproduccion_rapida)
    else:
        from utils import limpiar_archivos_obsoletos_instalacion

        limpiar_archivos_obsoletos_instalacion()

        from ui import iniciar

        iniciar()
