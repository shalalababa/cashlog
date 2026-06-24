"""Run the Cashlog API server.

Usage (from backend/):  python -m scripts.serve   ->  http://127.0.0.1:8000

The port can be overridden with ``CASHLOG_PORT`` (the desktop shell picks a free
ephemeral port and passes it in so it never collides with another local service).

This is also the PyInstaller entry point for the desktop sidecar. When frozen,
the package is already importable and the repo path insert is skipped; we hand
uvicorn the app *object* (not the "module:attr" import string) so it works the
same way in a bundled binary.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from cashlog.api import app  # noqa: E402


def _ensure_log_streams() -> None:
    """A windowed (console=False) frozen build has ``sys.stdout``/``stderr`` set
    to ``None``; uvicorn's logging would crash writing to them. Point them at a
    log file in the data dir so the sidecar runs silently but stays diagnosable.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    from cashlog import config
    try:
        config.ensure_data_dirs()
        sink = open(config.DATA_DIR / "backend.log", "a", encoding="utf-8")
    except Exception:
        import io
        sink = io.StringIO()
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


def _resolve_port() -> int:
    raw = os.environ.get("CASHLOG_PORT", "").strip()
    if raw:
        try:
            n = int(raw)
            if 0 < n < 65536:
                return n
        except ValueError:
            pass
    return 8000


def main() -> int:
    if getattr(sys, "frozen", False):
        _ensure_log_streams()
    uvicorn.run(app, host="127.0.0.1", port=_resolve_port(), reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
