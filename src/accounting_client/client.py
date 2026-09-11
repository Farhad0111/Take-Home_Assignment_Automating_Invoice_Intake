"""
Thin wrapper around the accounting system REST API.

All methods return (success: bool, data: dict | None, error: dict | None).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE = os.getenv("ACCOUNTING_API_URL", "http://localhost:8080")
_KEY = os.getenv("ACCOUNTING_API_KEY", "demo-key-1234")
_HEADERS = {"X-API-Key": _KEY, "Content-Type": "application/json"}

ResponseTuple = Tuple[bool, Optional[Dict], Optional[Dict]]


def _call(method: str, path: str, **kwargs) -> ResponseTuple:
    url = f"{_BASE}{path}"
    try:
        resp = requests.request(method, url, headers=_HEADERS, timeout=10, **kwargs)
        body = resp.json()
        return body.get("success", False), body.get("data"), body.get("error")
    except requests.RequestException as exc:
        return False, None, {"code": "CONNECTION_ERROR", "message": str(exc)}


def health() -> ResponseTuple:
    """GET /health — no auth required."""
    try:
        resp = requests.get(f"{_BASE}/health", timeout=5)
        body = resp.json()
        return body.get("success", False), body.get("data"), body.get("error")
    except requests.RequestException as exc:
        return False, None, {"code": "CONNECTION_ERROR", "message": str(exc)}


def get_partners() -> Tuple[bool, Optional[List[Dict]], Optional[Dict]]:
    """GET /partners — returns list of partner dicts."""
    ok, data, err = _call("GET", "/partners")
    if ok and data:
        return True, data.get("partners", []), None
    return False, None, err


def get_tax_codes() -> ResponseTuple:
    """GET /tax-codes."""
    return _call("GET", "/tax-codes")


def get_invoices() -> Tuple[bool, Optional[List[Dict]], Optional[Dict]]:
    """GET /invoices — returns list of registered invoice records."""
    ok, data, err = _call("GET", "/invoices")
    if ok and data:
        return True, data.get("invoices", []), None
    return False, None, err


def delete_invoices() -> ResponseTuple:
    """DELETE /invoices — clears all registered invoices."""
    return _call("DELETE", "/invoices")


def register_invoice(payload: Dict) -> ResponseTuple:
    """
    POST /invoices — register a single invoice.

    Args:
        payload: Dict matching the API schema (partner_code, invoice_number,
                 issue_date, due_date, currency, lines, subtotal, tax_amount,
                 total_amount).
    Returns:
        (success, data, error) tuple.
    """
    return _call("POST", "/invoices", json=payload)
