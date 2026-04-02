# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for RT Viewer Launcher.

Build:
    pip install pyinstaller pystray pillow watchdog
    pyinstaller launcher.spec

Output: dist/RTViewer/RTViewer.exe  (folder mode for easier updates)

The EXE bundles:
  - launcher.py         (this launcher/supervisor)
  - api_server.py       (FastAPI backend)
  - frontend/dist/      (pre-built Node.js production server)

Node.js itself is NOT bundled — it must be installed separately.
The launcher will find 'node' on PATH automatically.
"""

import sys
from pathlib import Path

BASE = Path(SPECPATH)

# ── Collect all data files ──────────────────────────────────────────────────
datas = [
    # Backend script (run as subprocess)
    (str(BASE / "api_server.py"),      "."),
    # Frontend production build
    (str(BASE / "frontend" / "dist"),  "frontend/dist"),
    # Dicom data placeholder (empty dir will be created at runtime)
]

# ── Hidden imports needed by FastAPI / uvicorn / watchdog ──────────────────
hiddenimports = [
    # FastAPI / Starlette
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "starlette",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "fastapi",
    "fastapi.middleware.cors",
    # Data
    "numpy",
    "pydicom",
    "pydicom.encoders",
    "PIL",
    "PIL.Image",
    # Watchdog
    "watchdog",
    "watchdog.observers",
    "watchdog.observers.polling",   # fallback observer (works everywhere)
    "watchdog.events",
    # Tray
    "pystray",
    "pystray._win32",
    # Misc
    "h11",
    "anyio",
    "anyio._backends._asyncio",
    "sniffio",
    "click",
]

a = Analysis(
    [str(BASE / "launcher.py")],
    pathex=[str(BASE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "skimage", "cv2",
        "IPython", "jupyter", "notebook",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RTViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # No console window — tray icon only
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,            # Add a .ico file path here if you have one
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RTViewer",
)
