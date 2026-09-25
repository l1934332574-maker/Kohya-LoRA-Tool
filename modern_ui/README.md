# Modern UI (Windows)

This is a Vue/WebView2 implementation of the existing Windows interface. The home page keeps the engine groups and training entry on the left, project toolbar and rows in the main area, and the fixed log panel at the bottom, with restrained hover, press, list, dialog, and toast transitions.

The modern UI is the default desktop interface. The classic CustomTkinter interface remains available with `--ui classic` as a compatibility fallback. Every registered training mode has a modern workspace that saves its project settings and calls its existing preprocessing and engine training functions directly. Training preflight, progress, stop, resume selection, and the post-preprocessing label review run in the modern task dialogs.

Secondary utilities that were intentionally left unchanged (for example the label editor, export-config dialog, engine guides that still require legacy content, and general-purpose tools) open as isolated classic popups. They receive the current project context where applicable; they do not switch the modern window to the classic training workspace. The model chooser/download UI, environment settings, project creation/import, logs, and preprocessing task are handled directly by the modern UI.

## Prerequisites

- Windows 10 or 11 with Microsoft Edge WebView2 Evergreen Runtime.
- Node.js 20.19+ or 22.12+ to build the frontend.
- Python dependencies from `requirements-ui.txt` for the desktop WebView host.

## Build and run

From the repository root:

```powershell
python -m pip install -r requirements-ui.txt
npm --prefix modern_ui ci
npm --prefix modern_ui run build
python kohya_gui.py --ui next
```

For frontend development, start Vite in one terminal and the desktop host in another. This connects the local Vue page to the native bridge, so project settings, file pickers, and the Qwen / Z-Image training path use the real local environment:

```powershell
npm --prefix modern_ui run dev
python kohya_gui.py --ui next --ui-dev --ui-debug
```

The project list and project operations use the Python bridge. Browser-only previews use sample data; creating, renaming, and deleting in browser preview only affects the current page. Desktop training runs the existing local engine in a worker thread; it does not open the classic training workspace.
