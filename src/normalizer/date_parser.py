"""
Date parsing for Japanese invoices.

Handles:
  - Wareki (Japanese era) dates: 令和8年1月15日, R8.1.15, 令和08年01月15日
  - Western slash/dot/dash: 2026/01/15, 2026.01.15, 2026-01-15
  - Relative terms: 翌月末 (end of next month), 月末 (end of month)
  - Kanji-mixed: 2026年1月15日

All outputs are YYYY-MM-DD strings.  Returns None on failure.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Era tables
# ---------------------------------------------------------------------------

ERA_TABLE = {
    # Japanese name → (romaji prefix, start year in western calendar)
    "令和": ("R", 2019),
    "平成": ("H", 1989),
    "昭和": ("S", 1926),
    "大正": ("T", 1912),
}

ERA_ROMAJI = {
    "R": 2019,
    "H": 1989,
    "S": 1926,
    "T": 1912,
}

# Digit maps (full-width → ASCII)
_FULL_WIDTH = str.maketrans(
    "０１２３４５６７８９",
    "0123456789",
)


def _normalize_digits(s: str) -> str:
    return s.translate(_FULL_WIDTH)


def _end_of_month(y: int, m: int) -> str:
    last = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-{last:02d}"


def parse_date(raw: str, reference_date: Optional[date] = None) -> Optional[str]:
    """
    Parse a date string from a Japanese invoice into YYYY-MM-DD.

    Args:
        raw: The date string as extracted from the invoice.
        reference_date: Used to resolve relative terms like 翌月末.
                        Defaults to today.

    Returns:
        YYYY-MM-DD string, or None if parsing fails.
    """
    if not raw:
        return None

    ref = reference_date or date.today()
    s = _normalize_digits(raw.strip())

    # -----------------------------------------------------------------------
    # Relative terms
    # -----------------------------------------------------------------------
    if "翌月末" in s:
        # End of the month after reference month
        next_month = ref.month % 12 + 1
        next_year = ref.year + (1 if ref.month == 12 else 0)
        return _end_of_month(next_year, next_month)

    if "月末" in s and "翌" not in s:
        return _end_of_month(ref.year, ref.month)

    # -----------------------------------------------------------------------
    # Wareki — kanji prefix: 令和8年1月15日
    # -----------------------------------------------------------------------
    for era_kanji, (_, start_year) in ERA_TABLE.items():
        pattern = rf"{era_kanji}(\d{{1,2}})年(\d{{1,2}})月(\d{{1,2}})日"
        m = re.search(pattern, s)
        if m:
            era_y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            year = start_year + era_y - 1
            return f"{year:04d}-{mo:02d}-{dy:02d}"

    # -----------------------------------------------------------------------
    # Wareki — romaji prefix: R8.1.15 or R08/01/15
    # -----------------------------------------------------------------------
    m = re.match(r"([RHSTrhst])(\d{1,2})[./\-](\d{1,2})[./\-](\d{1,2})", s)
    if m:
        prefix = m.group(1).upper()
        start = ERA_ROMAJI.get(prefix)
        if start:
            era_y, mo, dy = int(m.group(2)), int(m.group(3)), int(m.group(4))
            year = start + era_y - 1
            return f"{year:04d}-{mo:02d}-{dy:02d}"

    # -----------------------------------------------------------------------
    # Western: 2026年1月15日
    # -----------------------------------------------------------------------
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{dy:02d}"

    # -----------------------------------------------------------------------
    # Western ISO-like: 2026/01/15, 2026.01.15, 2026-01-15
    # -----------------------------------------------------------------------
    m = re.search(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})", s)
    if m:
        y, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{dy:02d}"

    return None
