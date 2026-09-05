# Accessible Music Downloader

[README en español](README.md)

Accessible Music Downloader is a Windows desktop application designed around keyboard and screen-reader accessibility, especially for NVDA and JAWS users.

> **Responsible use:** use the application only with content you have the right or permission to download and follow the applicable service terms.

## Project status

Current public stable release: **1.8.0**.

Current work branch: **1.8.1 test build**, focused on maintenance, search metadata, optional browser-session fallback and accessible documentation.

Included languages: Español, English, Français, Italiano, Português and Русский. `idiomas/es.json` is the master catalog and all six language files must keep matching keys.

## 1.8.1 test changes

- Simpler YouTube result rows: index, title, channel, publication date, views and duration. URLs remain available internally but are no longer displayed as a list column.
- Deferred metadata enrichment keeps large searches responsive.
- Optional preference for YouTube metadata in the application's selected language.
- Optional browser-session fallback when YouTube requests verification or sign-in.
- Manual download-engine updates compare versions first and no longer reinstall the same version unnecessarily.
- Startup and shutdown timing changes to avoid cutting off screen-reader announcements.
- Professional tagged PDF and TXT manuals in all six languages.
- Persistent Favorites: Alt+F adds or removes the focused video, while Tools > Favorites provides playback, download, information and removal actions.

- Persistent download queue with Alt+Q, Ctrl+Shift+Q and Tools > Download queue.

See [RELEASE_NOTES_1_8_1_PRUEBA.md](RELEASE_NOTES_1_8_1_PRUEBA.md) for details.

## Accessibility

The project prioritizes keyboard navigation, predictable tab order, screen-reader labels, concise announcements and avoiding mandatory technical setup for end users.

## Development

Use the complete Windows build folder, run `PREPARAR_MODO_ROBUSTO.bat`, then `ABRIR_PROGRAMA.bat`. Large third-party binaries are intentionally kept out of the source repository.

See [docs/DOCUMENTACION_TECNICA.md](docs/DOCUMENTACION_TECNICA.md) for implementation notes.

## Translation checks

```text
python tools/verificar_traducciones.py
python tools/verificar_textos_interfaz.py
```

## Security

Users should not be instructed to disable Windows Defender. Releases should include a SHA-256 hash and ideally be code-signed when an appropriate certificate is available.

## Contact

Developed by Nicolás Alfaro.

Email: alfaronico8@gmail.com

Official project: https://github.com/nicoalfaro2026/descargador-musica-accesible

## License

This project is distributed under the **GNU General Public License v3.0 (GPL-3.0)**. See [LICENSE](LICENSE).

- Improved playlists integrated with Favorites and the download queue: contents, full playlist and range selection.
