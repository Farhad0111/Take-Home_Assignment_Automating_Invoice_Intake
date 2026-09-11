"""
Currency and tax normalisation for Japanese invoices.

Amount cleaning:
  - Strips ¥ ￥ , spaces and full-width digits → plain Python int (JPY)

Tax code inference:
  - Uses the tax_rate_hint from extraction (0.10 → T10, 0.08 → T08)
  - Falls back to T10 (the current standard rate) when ambiguous
"""

from __future__ import annotations

import re
from typing import Optional

_FULL_WIDTH_DIGITS = str.maketrans(
    "０１２３４５６７８９",
    "0123456789",
)


def clean_amount(raw: str) -> Optional[int]:
    """
    Convert an amount string from the invoice to a plain integer (JPY).

    Handles: ¥1,234,567  /  ￥1,234,567  /  1,234,567円  /  1234567
    Returns None if the string cannot be parsed.
    """
    if raw is None:
        return None

    # Normalise full-width digits
    s = str(raw).translate(_FULL_WIDTH_DIGITS)

    # Strip currency symbols, commas, spaces, 円
    s = re.sub(r"[¥￥,\s円]", "", s)

    # Handle negative amounts (credit notes)
    negative = s.startswith("-") or s.startswith("▲") or s.startswith("△")
    s = s.lstrip("-▲△").strip()

    # Remove any trailing text (e.g. "1234567 (税込)")
    m = re.match(r"(\d+)", s)
    if not m:
        return None

    value = int(m.group(1))
    return -value if negative else value


def infer_tax_code(tax_rate_hint: Optional[float]) -> str:
    """
    Map a tax rate float to a tax code string.

    Args:
        tax_rate_hint: 0.10, 0.08, or None (extracted from invoice).
    Returns:
        "T10" or "T08". Defaults to "T10" when hint is absent or ambiguous.
    """
    if tax_rate_hint is None:
        return "T10"

    # Allow small floating point tolerance
    if abs(tax_rate_hint - 0.08) < 0.005:
        return "T08"

    # 0.10, 10.0 (percent), or anything else → T10
    return "T10"
