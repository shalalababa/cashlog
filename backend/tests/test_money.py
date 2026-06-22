"""Money helpers — runnable with pytest or directly (python tests/test_money.py)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cashlog import money  # noqa: E402


def test_parse_decimal():
    assert money.parse_decimal(5.51) == Decimal("5.51")          # no float tail
    assert money.parse_decimal("840") == Decimal("840")
    assert money.parse_decimal(None) is None
    assert money.parse_decimal("") is None
    assert money.parse_decimal("100.。") is None                  # workbook junk
    assert money.parse_decimal(True) is None                      # bool guard
    assert money.parse_decimal(-11.98) == Decimal("-11.98")


def test_to_minor():
    assert money.to_minor("5.51", 2) == 551
    assert money.to_minor("840", 0) == 840                        # JPY, 0 minor units
    # Negative *expenses* are legitimate (category credits: 红包净支出 / 被请客),
    # and the schema intentionally allows them so SUMIFS matches the workbook.
    assert money.to_minor("-11.98", 2) == -1198
    assert money.to_minor("0.005", 2) == 1                        # ROUND_HALF_UP


def test_conversion_matches_workbook():
    # 支出 R2: 840 JPY * 0.0501 = 42.084 CNY
    micro = money.to_base_micro(840, 0, "0.0501")
    assert money.base_micro_to_cny(micro) == Decimal("42.08")
    # 支出 R3: 5.51 USD * 7.2986 = 40.215286 CNY
    micro = money.to_base_micro(551, 2, "7.2986")
    assert money.base_micro_to_cny(micro) == Decimal("40.22")
    assert micro == 40215286                                      # full micro precision


def test_rate_to_str():
    assert money.rate_to_str(7.2986) == "7.2986"
    assert money.rate_to_str("0.0501") == "0.0501"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _run()
