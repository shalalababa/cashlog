"""Run the Cashlog API server.

Usage (from backend/):  python -m scripts.serve   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402


def main() -> int:
    uvicorn.run("cashlog.api:app", host="127.0.0.1", port=8000, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
