"""Build the Cashlog backend as a self-contained PyInstaller sidecar and place
it where the Tauri desktop build expects it (``frontend/src-tauri/binaries/``).

The build runs inside an isolated virtualenv (``backend/.sidecar-venv``) created
*without* system site-packages. That keeps the host environment untouched and
sidesteps the obsolete ``pathlib`` PyPI backport (which, if installed globally,
makes PyInstaller refuse to run).

Usage (from backend/):

    python scripts/build_sidecar.py

Output: ``frontend/src-tauri/binaries/cashlog-backend-<rust-target-triple>[.exe]``
Tauri strips the triple suffix at bundle time and places the binary next to the
app executable, where ``src-tauri/src/main.rs`` finds and launches it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
VENV_DIR = BACKEND_DIR / ".sidecar-venv"
SPEC = BACKEND_DIR / "cashlog-sidecar.spec"
BINARIES_DIR = REPO_ROOT / "frontend" / "src-tauri" / "binaries"
IS_WIN = os.name == "nt"
EXE_SUFFIX = ".exe" if IS_WIN else ""


def _venv_python() -> Path:
    return VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def _run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def _build_frontend() -> None:
    """Produce ``frontend/dist``; the sidecar bundles and serves it as the UI.

    Run via the platform shell so Windows resolves ``npm.cmd`` off PATHEXT
    (``npm`` is not a plain executable there). The command is a trusted constant.
    """
    if not (FRONTEND_DIR / "node_modules").is_dir():
        print("+ (frontend) node_modules missing -> npm install", flush=True)
        subprocess.run("npm install", cwd=FRONTEND_DIR, shell=True, check=True)
    print("+ (frontend) npm run build", flush=True)
    subprocess.run("npm run build", cwd=FRONTEND_DIR, shell=True, check=True)
    if not (FRONTEND_DIR / "dist" / "index.html").is_file():
        print("ERROR: npm run build did not produce frontend/dist/index.html",
              file=sys.stderr)
        raise SystemExit(1)


def _rust_target_triple() -> str:
    """The host triple Tauri uses to name externalBins (from ``rustc -Vv``)."""
    try:
        out = subprocess.run(["rustc", "-Vv"], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    # Sensible fallback for the common desktop targets.
    if IS_WIN:
        return "x86_64-pc-windows-msvc"
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if os.uname().machine == "arm64" else "x86_64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def main() -> int:
    # Build the UI first: the spec bundles frontend/dist into the sidecar (it is
    # the desktop app's served UI), and a frontend failure should abort before
    # the slow venv + pip + PyInstaller steps.
    _build_frontend()

    if not VENV_DIR.exists():
        print(f"Creating isolated build venv at {VENV_DIR} ...", flush=True)
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(VENV_DIR)
    py = _venv_python()

    _run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(py), "-m", "pip", "install", "-r", str(BACKEND_DIR / "requirements.txt")])
    _run([str(py), "-m", "pip", "install", "pyinstaller"])

    # Clean previous build outputs for a deterministic result.
    work_dir = BACKEND_DIR / "build"
    dist_dir = BACKEND_DIR / "dist"
    for d in (work_dir, dist_dir):
        shutil.rmtree(d, ignore_errors=True)

    # Pin --distpath/--workpath: PyInstaller otherwise writes them relative to the
    # current working dir, so the script would only work when run from backend/.
    _run([
        str(py), "-m", "PyInstaller", "--clean", "--noconfirm",
        "--distpath", str(dist_dir), "--workpath", str(work_dir),
        str(SPEC),
    ])

    built = BACKEND_DIR / "dist" / f"cashlog-backend{EXE_SUFFIX}"
    if not built.exists():
        print(f"ERROR: expected build output not found: {built}", file=sys.stderr)
        return 1

    triple = _rust_target_triple()
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    dest = BINARIES_DIR / f"cashlog-backend-{triple}{EXE_SUFFIX}"
    shutil.copy2(built, dest)
    print(f"\nSidecar ready: {dest}  ({dest.stat().st_size // (1024 * 1024)} MB)", flush=True)
    print("Now build the desktop app:  cd frontend && npm run tauri build", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
