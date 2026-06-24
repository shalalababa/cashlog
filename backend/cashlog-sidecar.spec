# PyInstaller spec for the Cashlog backend sidecar.
#
# Produces a single self-contained executable that runs the same FastAPI app as
# `python -m scripts.serve`. The Tauri desktop build bundles this as an
# externalBin so the installed app needs no system Python.
#
# Build it via `python scripts/build_sidecar.py` (isolated venv) rather than
# invoking PyInstaller directly — see docs/DESKTOP.md.
import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is the directory containing this spec file (backend/).
DOCS = os.path.join(SPECPATH, "..", "docs")

# The built single-page UI. The frozen backend mounts this at "/" (see
# config.FRONTEND_DIST / api.py), so it IS the desktop app's UI — without it the
# webview would open a bare 404. build_sidecar.py runs `npm run build` to produce
# it before invoking PyInstaller; fail loudly if someone runs the spec directly.
DIST = os.path.join(SPECPATH, "..", "frontend", "dist")
if not os.path.isdir(DIST):
    raise SystemExit(
        "cashlog-sidecar: frontend/dist is missing — the sidecar must bundle the "
        "built UI it serves. Run `python scripts/build_sidecar.py` (it builds the "
        "frontend first), or `cd frontend && npm run build` before PyInstaller."
    )

# Bundle the read-only assets config.py reads from sys._MEIPASS when frozen:
# schema baseline + additive migrations (under "docs"), and the built UI (under
# "frontend/dist", matching REPO_ROOT/frontend/dist == the bundle dir).
datas = [
    (os.path.join(DOCS, "schema.sql"), "docs"),
    (os.path.join(DOCS, "migrations"), os.path.join("docs", "migrations")),
    (DIST, os.path.join("frontend", "dist")),
]

# uvicorn / our package pull a number of modules in dynamically (by string),
# which static analysis misses — collect them explicitly.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("cashlog")
    + collect_submodules("openpyxl")
)

a = Analysis(
    [os.path.join(SPECPATH, "scripts", "serve.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="cashlog-backend",
    debug=False,
    strip=False,
    upx=False,
    # Windowed: the Tauri window is the UI; no flashing console. serve.py
    # redirects logging to a file when frozen so a None stdout never crashes us.
    console=False,
)
