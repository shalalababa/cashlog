"""Importer invariants — runnable with pytest or directly."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import importer  # noqa: E402


def test_external_uid_is_deterministic():
    a = importer.make_external_uid("支出", 42, "abc123")
    b = importer.make_external_uid("支出", 42, "abc123")
    assert a == b, "same (sheet, row, hash) must yield the same uid across runs"


def test_external_uid_varies_with_inputs():
    base = importer.make_external_uid("支出", 42, "abc123")
    assert importer.make_external_uid("入账", 42, "abc123") != base   # sheet
    assert importer.make_external_uid("支出", 43, "abc123") != base   # row
    assert importer.make_external_uid("支出", 42, "def456") != base   # content hash


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
