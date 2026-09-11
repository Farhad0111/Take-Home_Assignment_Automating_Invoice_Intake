"""
Business-rule validation for normalised invoices.

These checks mirror exactly what the accounting API enforces, so we can
catch mismatches *before* hitting the API and surface them in the review UI.

Rules:
  - PARTNER_EXISTS      partner_code must not be None
  - DATE_VALID          issue_date and due_date must be parseable YYYY-MM-DD
  - DUE_AFTER_ISSUE     due_date >= issue_date
  - SUBTOTAL_MATCH      subtotal == sum(line.amount)
  - TAX_MATCH           tax == floor(rate * subtotal_per_code)
  - TOTAL_MATCH         total == subtotal + tax
  - DUPLICATE           invoice_number + partner_code not already registered
"""

from __future__ import annotations

import math
from datetime import date
from typing import Dict, List, Optional

from .result import ValidationResult, ValidationStatus

TAX_RATES: Dict[str, float] = {"T10": 0.10, "T08": 0.08}


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def validate(
    partner_code: Optional[str],
    invoice_number: str,
    issue_date: Optional[str],
    due_date: Optional[str],
    subtotal: Optional[int],
    tax_amount: Optional[int],
    total_amount: Optional[int],
    lines: List[Dict],
    overall_confidence: float = 1.0,
    registered_invoices: Optional[List[Dict]] = None,
) -> ValidationResult:
    """
    Run all business-rule checks and return a ValidationResult.

    Args:
        partner_code: Normalised partner code (or None if unmatched).
        invoice_number: Invoice number string.
        issue_date: YYYY-MM-DD or None.
        due_date: YYYY-MM-DD or None.
        subtotal: Integer JPY.
        tax_amount: Integer JPY.
        total_amount: Integer JPY.
        lines: List of dicts with keys: amount (int), tax_code (str).
        overall_confidence: From the extraction step.
        registered_invoices: List of already-registered invoice dicts for dup check.
    """
    result = ValidationResult(
        status=ValidationStatus.PASS,
        overall_confidence=overall_confidence,
    )

    # ------------------------------------------------------------------
    # PARTNER_EXISTS
    # ------------------------------------------------------------------
    if not partner_code:
        result.add_error(
            "PARTNER_NOT_FOUND",
            "Supplier could not be matched to any partner in the master.",
        )

    # ------------------------------------------------------------------
    # DATE_VALID + DUE_AFTER_ISSUE
    # ------------------------------------------------------------------
    parsed_issue = None
    parsed_due = None

    if not issue_date:
        result.add_error("DATE_MISSING", "Issue date could not be parsed.")
    else:
        parsed_issue = _parse_date(issue_date)
        if parsed_issue is None:
            result.add_error("DATE_INVALID", f"Issue date '{issue_date}' is not YYYY-MM-DD.")

    if not due_date:
        result.add_warning("DUE_DATE_MISSING", "Due date is missing; will need to be set manually.")
    else:
        parsed_due = _parse_date(due_date)
        if parsed_due is None:
            result.add_error("DUE_DATE_INVALID", f"Due date '{due_date}' is not YYYY-MM-DD.")

    if parsed_issue and parsed_due and parsed_due < parsed_issue:
        result.add_error(
            "DUE_DATE_BEFORE_ISSUE",
            f"Due date {due_date} is before issue date {issue_date}.",
        )

    # ------------------------------------------------------------------
    # Lines must not be empty
    # ------------------------------------------------------------------
    if not lines:
        result.add_error("NO_LINES", "Invoice has no line items.")
        return result

    # ------------------------------------------------------------------
    # SUBTOTAL_MATCH
    # ------------------------------------------------------------------
    expected_subtotal = sum(line.get("amount", 0) for line in lines)
    if subtotal is None:
        result.add_error("SUBTOTAL_MISSING", "Subtotal amount could not be parsed.")
    elif subtotal != expected_subtotal:
        result.add_error(
            "SUBTOTAL_MISMATCH",
            f"Subtotal {subtotal} ≠ sum of line amounts {expected_subtotal}.",
            detail=f"expected={expected_subtotal}, received={subtotal}",
        )

    # ------------------------------------------------------------------
    # TAX_MATCH  (per-code, rounded down — mirrors the API exactly)
    # ------------------------------------------------------------------
    subtotal_by_code: Dict[str, int] = {}
    unknown_codes = []
    for line in lines:
        code = line.get("tax_code", "T10")
        if code not in TAX_RATES:
            unknown_codes.append(code)
        subtotal_by_code[code] = subtotal_by_code.get(code, 0) + line.get("amount", 0)

    if unknown_codes:
        result.add_error("UNKNOWN_TAX_CODE", f"Unknown tax codes: {unknown_codes}")

    if not unknown_codes:
        expected_tax = sum(
            math.floor(TAX_RATES[code] * amt)
            for code, amt in subtotal_by_code.items()
        )
        if tax_amount is None:
            result.add_error("TAX_MISSING", "Tax amount could not be parsed.")
        elif tax_amount != expected_tax:
            result.add_error(
                "TAX_MISMATCH",
                f"Tax amount {tax_amount} ≠ recalculated tax {expected_tax}.",
                detail=f"expected={expected_tax}, received={tax_amount}",
            )

    # ------------------------------------------------------------------
    # TOTAL_MATCH
    # ------------------------------------------------------------------
    if subtotal is not None and tax_amount is not None and total_amount is not None:
        expected_total = subtotal + tax_amount
        if total_amount != expected_total:
            result.add_error(
                "TOTAL_MISMATCH",
                f"Total {total_amount} ≠ subtotal {subtotal} + tax {tax_amount} = {expected_total}.",
            )

    # ------------------------------------------------------------------
    # DUPLICATE CHECK
    # ------------------------------------------------------------------
    if registered_invoices and partner_code and invoice_number:
        for reg in registered_invoices:
            if (
                reg.get("partner_code") == partner_code
                and reg.get("invoice_number") == invoice_number
            ):
                result.add_error(
                    "DUPLICATE_INVOICE",
                    f"Invoice {invoice_number} is already registered for partner {partner_code}.",
                )
                break

    return result
