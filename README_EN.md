# Accessible Music Downloader

[README en español](README.md)

Accessible Music Downloader is a Windows desktop application designed around keyboard and screen-reader accessibility, especially for NVDA and JAWS users.

> **Responsible use:** use the application only with content you have the right or permission to download and follow the applicable service terms.

## Current version

Source base: **1.8.0**.

Included languages: Español, English, Français, Italiano, Português and Русский. All six catalogs use the same keys, with `idiomas/es.json` as the master catalog.

## Main 1.8.0 changes

- Download history is capped at the 1,000 most recent entries and can be cleared without deleting downloaded files.
- Default search count can be set to 20, 50, 75, 100, 150, 200 or 300 results.
- Users can choose whether the program asks for the result count before every search.
- MPV output-device selector with automatic fallback to the Windows default if a saved device disappears.
- Simplified player; full keyboard help remains under **Help > Keyboard shortcuts**.
- Audio formats: MP3, M4A, AAC, OPUS, OGG, WAV and FLAC.
- MP4 video with best available quality or a resolution cap from 144p through 2160p/4K.

## Download architecture

**yt-dlp** is the primary engine, **Deno** provides JavaScript support, and **pytubefix + portable Node** is an automatic fallback for compatible failures. **FFmpeg** handles media conversion and **MPV** handles internal playback.

The final portable release is intended to work without users installing Python, Deno, Node or FFmpeg.

## Development

Use the complete Windows build folder, run `PREPARAR_MODO_ROBUSTO.bat`, then `ABRIR_PROGRAMA.bat`. Large third-party binaries are intentionally kept out of the source repository.

Run `CREAR_VERSION_DISTRIBUIBLE.bat` to create the portable Release package.

## Translation checks

Run:

- `python tools/verificar_traducciones.py`
- `python tools/verificar_textos_interfaz.py`

## Security

Users should not be instructed to disable Windows Defender. Releases should include a SHA-256 hash and ideally be code-signed when an appropriate certificate is available.

## License

The project author should choose the repository license before opening the project to external code contributions.
