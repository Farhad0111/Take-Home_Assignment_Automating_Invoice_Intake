"""
Invoice intake pipeline orchestrator.

For each invoice file in invoices/:
  1. Extract (LLM)
  2. Normalise (partner match, date parse, amount clean)
  3. Validate (business rules)
  4. Gate (AUTO vs REVIEW)
  5. Auto-register PASS+HIGH-CONF invoices
  6. Save results to data/results/results.json

Usage:
    from src.pipeline import run_pipeline
    results = run_pipeline()
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from src.accounting_client import client as api
from src.extractor.llm_client import InvoiceExtractor
from src.normalizer.date_parser import parse_date
from src.normalizer.partner_matcher import match_partner
from src.normalizer.tax_currency import clean_amount, infer_tax_code
from src.validation.result import ValidationStatus
from src.validation.risk_gate import Disposition, gate
from src.validation import rules as vrules

ROOT = Path(__file__).resolve().parent.parent
INVOICES_DIR = ROOT / "invoices"
RESULTS_DIR = ROOT / "data" / "results"
RAW_DIR = ROOT / "data" / "raw_extractions"
NORM_DIR = ROOT / "data" / "normalized"


def _build_api_payload(
    partner_code: str,
    invoice_number: str,
    issue_date: str,
    due_date: str,
    subtotal: int,
    tax_amount: int,
    total_amount: int,
    lines: List[Dict],
) -> Dict:
    return {
        "partner_code": partner_code,
        "invoice_number": invoice_number,
        "issue_date": issue_date,
        "due_date": due_date,
        "currency": "JPY",
        "lines": lines,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
    }


def _normalise_invoice(raw, partners: List[Dict]) -> Dict[str, Any]:
    """
    Convert a RawInvoice into a normalised dict ready for validation.
    Returns a dict with all fields plus a 'normalisation_notes' list.
    """
    notes = []

    # Partner matching
    partner_code, match_conf = match_partner(
        raw.supplier_name,
        raw.registration_no,
        partners,
    )
    if not partner_code:
        notes.append(f"Could not match supplier '{raw.supplier_name}' to any partner.")

    # Date parsing
    issue_date = parse_date(raw.issue_date_raw)
    if not issue_date:
        notes.append(f"Could not parse issue date: '{raw.issue_date_raw}'")

    due_date = parse_date(raw.due_date_raw) if raw.due_date_raw else None
    if raw.due_date_raw and not due_date:
        notes.append(f"Could not parse due date: '{raw.due_date_raw}'")

    # Amount parsing
    subtotal = clean_amount(raw.subtotal_raw)
    tax_amount = clean_amount(raw.tax_amount_raw)
    total_amount = clean_amount(raw.total_amount_raw)

    # Line items
    normalised_lines = []
    for line in raw.lines:
        tax_code = infer_tax_code(line.tax_rate_hint)
        normalised_lines.append({
            "description": line.description,
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_price": line.unit_price,
            "amount": line.amount,
            "tax_code": tax_code,
        })

    # If subtotal is missing, compute from lines
    if subtotal is None and normalised_lines:
        subtotal = sum(l["amount"] for l in normalised_lines)
        notes.append("Subtotal computed from line items (was not parseable).")

    # If tax is missing, compute from subtotal per code
    if tax_amount is None and subtotal is not None and normalised_lines:
        subtotal_by_code: Dict[str, int] = {}
        for line in normalised_lines:
            code = line["tax_code"]
            subtotal_by_code[code] = subtotal_by_code.get(code, 0) + line["amount"]
        tax_rates = {"T10": 0.10, "T08": 0.08}
        tax_amount = sum(
            math.floor(tax_rates[c] * s) for c, s in subtotal_by_code.items()
        )
        notes.append("Tax computed from line items (was not parseable).")

    # If total is missing, compute
    if total_amount is None and subtotal is not None and tax_amount is not None:
        total_amount = subtotal + tax_amount
        notes.append("Total computed from subtotal + tax (was not parseable).")

    return {
        "supplier_name": raw.supplier_name,
        "partner_code": partner_code,
        "partner_match_confidence": match_conf,
        "invoice_number": raw.invoice_number,
        "issue_date": issue_date,
        "due_date": due_date,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "lines": normalised_lines,
        "extraction_confidence": raw.confidence,
        "normalisation_notes": notes,
    }


def process_invoice(
    file_path: Path,
    extractor: InvoiceExtractor,
    partners: List[Dict],
    registered_invoices: List[Dict],
) -> Dict[str, Any]:
    """Process a single invoice file end-to-end."""
    source = file_path.name
    record: Dict[str, Any] = {"source_file": source, "status": "UNKNOWN"}

    # --- Step 1: Extract ---
    extraction = extractor.extract(file_path)
    if not extraction.success or extraction.raw is None:
        record["status"] = "EXTRACTION_FAILED"
        record["error"] = extraction.error
        return record

    raw = extraction.raw
    overall_conf = extraction.overall_confidence

    # Save raw extraction
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{file_path.stem}.json"
    raw_data = {
        "supplier_name": raw.supplier_name,
        "registration_no": raw.registration_no,
        "invoice_number": raw.invoice_number,
        "issue_date_raw": raw.issue_date_raw,
        "due_date_raw": raw.due_date_raw,
        "subtotal_raw": raw.subtotal_raw,
        "tax_amount_raw": raw.tax_amount_raw,
        "total_amount_raw": raw.total_amount_raw,
        "lines": [
            {
                "description": l.description,
                "quantity": l.quantity,
                "unit": l.unit,
                "unit_price": l.unit_price,
                "amount": l.amount,
                "tax_rate_hint": l.tax_rate_hint,
            }
            for l in raw.lines
        ],
        "confidence": raw.confidence,
    }
    raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- Step 2: Normalise ---
    norm = _normalise_invoice(raw, partners)
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    norm_path = NORM_DIR / f"{file_path.stem}.json"
    norm_path.write_text(json.dumps(norm, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # --- Step 3: Validate ---
    validation = vrules.validate(
        partner_code=norm["partner_code"],
        invoice_number=norm["invoice_number"],
        issue_date=norm["issue_date"],
        due_date=norm["due_date"],
        subtotal=norm["subtotal"],
        tax_amount=norm["tax_amount"],
        total_amount=norm["total_amount"],
        lines=norm["lines"],
        overall_confidence=overall_conf,
        registered_invoices=registered_invoices,
    )

    # --- Step 4: Gate ---
    disposition = gate(validation, overall_conf)

    record.update({
        "invoice_number": norm["invoice_number"],
        "supplier_name": norm["supplier_name"],
        "partner_code": norm["partner_code"],
        "issue_date": norm["issue_date"],
        "due_date": norm["due_date"],
        "subtotal": norm["subtotal"],
        "tax_amount": norm["tax_amount"],
        "total_amount": norm["total_amount"],
        "lines": norm["lines"],
        "extraction_confidence": overall_conf,
        "partner_match_confidence": norm["partner_match_confidence"],
        "validation_status": validation.status.value,
        "validation_issues": [
            {"severity": i.severity, "code": i.code, "message": i.message, "detail": i.detail}
            for i in validation.issues
        ],
        "disposition": disposition.value,
        "normalisation_notes": norm["normalisation_notes"],
        "api_result": None,
        "accounting_id": None,
    })

    # --- Step 5: Auto-register if AUTO ---
    if disposition == Disposition.AUTO:
        payload = _build_api_payload(
            partner_code=norm["partner_code"],
            invoice_number=norm["invoice_number"],
            issue_date=norm["issue_date"],
            due_date=norm["due_date"],
            subtotal=norm["subtotal"],
            tax_amount=norm["tax_amount"],
            total_amount=norm["total_amount"],
            lines=norm["lines"],
        )
        ok, data, err = api.register_invoice(payload)
        if ok:
            record["status"] = "REGISTERED"
            record["accounting_id"] = data.get("accounting_id") if data else None
            record["api_result"] = "success"
            # Add to registered list so subsequent invoices see the duplicate
            registered_invoices.append({
                "partner_code": norm["partner_code"],
                "invoice_number": norm["invoice_number"],
            })
        else:
            record["status"] = "REGISTRATION_FAILED"
            record["api_result"] = err
    else:
        record["status"] = "NEEDS_REVIEW"

    return record


def run_pipeline(invoice_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Run the full pipeline over all invoices in invoice_dir.

    Returns a list of result records (one per invoice).
    """
    invoice_dir = invoice_dir or INVOICES_DIR

    # Fetch partners from API (with fallback for when API is offline)
    ok, partners, err = api.get_partners()
    if not ok:
        print(f"[WARNING] Could not fetch partners from API: {err}")
        print("   Make sure the accounting API is running: python accounting_api.py")
        partners = []

    # Fetch already-registered invoices for duplicate detection
    ok2, registered, _ = api.get_invoices()
    registered_invoices: List[Dict] = registered or []

    # Collect invoice files
    invoice_files = sorted(
        [p for p in invoice_dir.iterdir() if p.suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png"}]
    )

    if not invoice_files:
        print(f"No invoice files found in {invoice_dir}")
        return []

    extractor = InvoiceExtractor()
    results: List[Dict[str, Any]] = []

    print(f"\n{'='*60}")
    print(f"  Invoice Intake Pipeline  ---  {len(invoice_files)} files")
    print(f"{'='*60}")

    for i, f in enumerate(invoice_files, 1):
        print(f"\n[{i}/{len(invoice_files)}] Processing {f.name} ...")
        result = process_invoice(f, extractor, partners, registered_invoices)
        results.append(result)

        # Status summary line
        status = result.get("status", "UNKNOWN")
        disp = result.get("disposition", "")
        conf = result.get("extraction_confidence", 0)
        issues = result.get("validation_issues", [])
        issue_str = f"  ({len(issues)} issue(s))" if issues else ""
        print(f"  → {status} | disposition={disp} | conf={conf:.2f}{issue_str}")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / "results.json"
    results_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Print summary table
    _print_summary(results)
    print(f"\nResults saved to {results_path}")

    return results


def _print_summary(results: List[Dict]):
    counts = {"REGISTERED": 0, "NEEDS_REVIEW": 0, "REGISTRATION_FAILED": 0,
              "EXTRACTION_FAILED": 0, "UNKNOWN": 0}
    print(f"\n{'='*60}")
    print(f"  {'File':<20} {'Status':<20} {'Supplier':<20}")
    print(f"  {'-'*58}")
    for r in results:
        status = r.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
        supplier = (r.get("supplier_name") or "—")[:20]
        print(f"  {r['source_file']:<20} {status:<20} {supplier:<20}")
    print(f"\n  Summary: {counts}")
    print(f"{'='*60}")
