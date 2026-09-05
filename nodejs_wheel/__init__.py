"""Compatibilidad mínima para pytubefix con Node portable.

Evita distribuir el paquete completo nodejs-wheel-binaries (que incluye npm y
miles de rutas profundas). Pytubefix solo necesita
``nodejs_wheel.executable.ROOT_DIR`` para localizar node.exe.
"""
