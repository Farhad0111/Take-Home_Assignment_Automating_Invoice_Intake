"""Unit tests for src/validation/rules.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.validation.rules import validate
from src.validation.result import ValidationStatus


def _base_lines():
    return [
        {"description": "Product A", "quantity": 10, "unit": "pcs",
         "unit_price": 10000, "amount": 100000, "tax_code": "T10"},
        {"description": "Delivery", "quantity": None, "unit": "lot",
         "unit_price": None, "amount": 5000, "tax_code": "T10"},
    ]


def _base_call(**overrides):
    defaults = dict(
        partner_code="P-1001",
        invoice_number="INV-001",
        issue_date="2026-01-15",
        due_date="2026-02-28",
        subtotal=105000,
        tax_amount=10500,   # floor(0.10 * 105000) = 10500
        total_amount=115500,
        lines=_base_lines(),
        overall_confidence=0.9,
        registered_invoices=[],
    )
    defaults.update(overrides)
    return validate(**defaults)


class TestPassCase:
    def test_all_valid(self):
        result = _base_call()
        assert result.status == ValidationStatus.PASS
        assert not result.has_errors
        assert not result.has_warnings


class TestPartnerValidation:
    def test_missing_partner(self):
        result = _base_call(partner_code=None)
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "PARTNER_NOT_FOUND" for i in result.issues)


class TestDateValidation:
    def test_missing_issue_date(self):
        result = _base_call(issue_date=None)
        assert result.status == ValidationStatus.FAIL

    def test_bad_issue_date_format(self):
        result = _base_call(issue_date="15/01/2026")
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "DATE_INVALID" for i in result.issues)

    def test_due_before_issue(self):
        result = _base_call(issue_date="2026-02-01", due_date="2026-01-01")
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "DUE_DATE_BEFORE_ISSUE" for i in result.issues)

    def test_missing_due_date_is_warning(self):
        result = _base_call(due_date=None)
        # Missing due date is a warning, not an error
        assert any(i.severity == "WARN" for i in result.issues)


class TestAmountValidation:
    def test_subtotal_mismatch(self):
        result = _base_call(subtotal=999999)
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "SUBTOTAL_MISMATCH" for i in result.issues)

    def test_tax_mismatch(self):
        result = _base_call(tax_amount=9999)
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "TAX_MISMATCH" for i in result.issues)

    def test_total_mismatch(self):
        result = _base_call(total_amount=999999)
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "TOTAL_MISMATCH" for i in result.issues)

    def test_tax_floor_rounding(self):
        """Tax should use floor rounding, matching the API exactly."""
        # T10 on 100001 = floor(10000.1) = 10000
        lines = [{"description": "X", "quantity": 1, "unit": "pcs",
                  "unit_price": 100001, "amount": 100001, "tax_code": "T10"}]
        expected_tax = 10000  # floor(0.10 * 100001)
        result = _base_call(
            subtotal=100001,
            tax_amount=expected_tax,
            total_amount=100001 + expected_tax,
            lines=lines,
        )
        assert result.status == ValidationStatus.PASS

    def test_mixed_tax_codes(self):
        """Verify T10 + T08 mixed lines compute correctly."""
        lines = [
            {"description": "A", "quantity": 1, "unit": "pcs",
             "unit_price": 100000, "amount": 100000, "tax_code": "T10"},
            {"description": "B", "quantity": 1, "unit": "pcs",
             "unit_price": 50000, "amount": 50000, "tax_code": "T08"},
        ]
        # T10: floor(0.10 * 100000) = 10000
        # T08: floor(0.08 * 50000)  = 4000
        # total tax = 14000
        result = _base_call(
            subtotal=150000,
            tax_amount=14000,
            total_amount=164000,
            lines=lines,
        )
        assert result.status == ValidationStatus.PASS


class TestDuplicateDetection:
    def test_duplicate_invoice(self):
        registered = [{"partner_code": "P-1001", "invoice_number": "INV-001"}]
        result = _base_call(registered_invoices=registered)
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "DUPLICATE_INVOICE" for i in result.issues)

    def test_no_false_positive_different_partner(self):
        registered = [{"partner_code": "P-9999", "invoice_number": "INV-001"}]
        result = _base_call(registered_invoices=registered)
        assert result.status == ValidationStatus.PASS

    def test_no_false_positive_different_number(self):
        registered = [{"partner_code": "P-1001", "invoice_number": "INV-999"}]
        result = _base_call(registered_invoices=registered)
        assert result.status == ValidationStatus.PASS


class TestNoLines:
    def test_empty_lines(self):
        result = _base_call(lines=[])
        assert result.status == ValidationStatus.FAIL
        assert any(i.code == "NO_LINES" for i in result.issues)
