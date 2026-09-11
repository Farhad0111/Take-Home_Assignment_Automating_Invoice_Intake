"""
Partner matching: maps the supplier name extracted from an invoice
to a partner_code in the accounting API's partner master.

Matching strategy (in order, first match wins):
  1. Exact name match
  2. Alias match
  3. Tax registration number match (T-number)
  4. Fuzzy character overlap (≥ 60 % of characters in common)

Returns (partner_code, confidence) or (None, 0.0) if no match.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


def _normalize(text: str) -> str:
    """Strip whitespace and common noise for comparison."""
    return re.sub(r"[\s　株式会社有限会社合同会社]", "", text)


def _char_overlap_ratio(a: str, b: str) -> float:
    """Jaccard-style overlap of character sets (handles partial matches)."""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def match_partner(
    supplier_name: str,
    registration_no: Optional[str],
    partners: List[Dict],
) -> Tuple[Optional[str], float]:
    """
    Return (partner_code, confidence) for the best matching partner.

    Args:
        supplier_name: Name extracted from the invoice.
        registration_no: T-number extracted from the invoice (may be None).
        partners: List of partner dicts from GET /partners.
    """
    if not partners:
        return None, 0.0

    norm_supplier = _normalize(supplier_name)

    # -----------------------------------------------------------------------
    # Pass 1: Exact name match
    # -----------------------------------------------------------------------
    for p in partners:
        if p["name"] == supplier_name or _normalize(p["name"]) == norm_supplier:
            return p["partner_code"], 1.0

    # -----------------------------------------------------------------------
    # Pass 2: Alias match
    # -----------------------------------------------------------------------
    for p in partners:
        for alias in p.get("aliases", []):
            if alias == supplier_name or _normalize(alias) == norm_supplier:
                return p["partner_code"], 0.95

    # -----------------------------------------------------------------------
    # Pass 3: Tax registration number match
    # -----------------------------------------------------------------------
    if registration_no:
        clean_reg = registration_no.strip()
        for p in partners:
            if p.get("registration_no") == clean_reg:
                return p["partner_code"], 0.90

    # -----------------------------------------------------------------------
    # Pass 4: Fuzzy character overlap
    # -----------------------------------------------------------------------
    best_code: Optional[str] = None
    best_ratio = 0.0

    for p in partners:
        candidates = [p["name"]] + p.get("aliases", [])
        for candidate in candidates:
            ratio = _char_overlap_ratio(norm_supplier, _normalize(candidate))
            if ratio > best_ratio:
                best_ratio = ratio
                best_code = p["partner_code"]

    if best_ratio >= 0.60:
        # Scale confidence: 0.60 overlap → 0.70 conf, 1.0 overlap → 0.88 conf
        confidence = 0.70 + (best_ratio - 0.60) * (0.18 / 0.40)
        return best_code, round(confidence, 3)

    return None, 0.0
