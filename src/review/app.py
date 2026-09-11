"""
Flask human-review UI for the invoice intake pipeline.

Routes:
  GET  /                          — Dashboard: list all invoices with status
  GET  /review/<invoice_id>       — Side-by-side review form
  POST /review/<invoice_id>/approve  — Submit (corrected) data to API
  POST /review/<invoice_id>/reject   — Mark as rejected
  GET  /image/<filename>          — Serve invoice images

Start with: flask --app src.review.app run --port 5000
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.accounting_client import client as api

RESULTS_FILE = ROOT / "data" / "results" / "results.json"
INVOICES_DIR = ROOT / "invoices"

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_results() -> List[Dict]:
    if not RESULTS_FILE.exists():
        return []
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def _save_results(results: List[Dict]):
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _get_invoice(invoice_id: str) -> Optional[Dict]:
    results = _load_results()
    for r in results:
        if r.get("source_file") == invoice_id:
            return r
    return None


def _image_to_data_uri(path: Path) -> str:
    """Convert an image file to a base64 data URI."""
    try:
        from PIL import Image  # noqa: PLC0415
        import io  # noqa: PLC0415

        with Image.open(str(path)) as img:
            img = img.convert("RGB")
            # Resize for display (max 900px wide)
            max_w = 900
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _pdf_first_page_data_uri(path: Path) -> str:
    """Render first page of a PDF to data URI."""
    try:
        from pypdf import PdfReader  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        import io  # noqa: PLC0415

        reader = PdfReader(str(path))
        page = reader.pages[0]
        page_images = list(page.images)
        if page_images:
            buf = io.BytesIO(page_images[0].data)
            img = Image.open(buf).convert("RGB")
        else:
            # Text-layer PDF: render text as image
            from src.extractor.llm_client import _text_to_image  # noqa: PLC0415
            text = page.extract_text() or "(no text)"
            img = _text_to_image(text)

        max_w = 900
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _get_image_data_uri(filename: str) -> str:
    path = INVOICES_DIR / filename
    if not path.exists():
        return ""
    if path.suffix.lower() == ".pdf":
        return _pdf_first_page_data_uri(path)
    return _image_to_data_uri(path)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}Invoice Review{% endblock %} — Invoice Intake</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #232635;
    --border: #2e3148;
    --accent: #6366f1;
    --accent-hover: #818cf8;
    --green: #22c55e;
    --yellow: #eab308;
    --red: #ef4444;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --radius: 10px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  a { color: var(--accent-hover); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* NAV */
  nav { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 2rem; display: flex; align-items: center; gap: 1.5rem; height: 56px; }
  nav .brand { font-weight: 700; font-size: 1.1rem; color: var(--text); letter-spacing: -0.3px; }
  nav .brand span { color: var(--accent); }
  nav .nav-link { color: var(--muted); font-size: 0.875rem; font-weight: 500; transition: color .15s; }
  nav .nav-link:hover { color: var(--text); text-decoration: none; }

  /* MAIN */
  .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
  h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.25rem; }
  .subtitle { color: var(--muted); font-size: 0.875rem; margin-bottom: 2rem; }

  /* BADGES */
  .badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
  .badge-green  { background: rgba(34,197,94,.15);  color: #4ade80; }
  .badge-yellow { background: rgba(234,179,8,.15);  color: #fbbf24; }
  .badge-red    { background: rgba(239,68,68,.15);  color: #f87171; }
  .badge-blue   { background: rgba(99,102,241,.15); color: #a5b4fc; }
  .badge-gray   { background: rgba(148,163,184,.1); color: #94a3b8; }

  /* CARDS */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.5rem; }

  /* TABLE */
  table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  thead th { text-align: left; color: var(--muted); font-weight: 500; font-size: 0.75rem; text-transform: uppercase; letter-spacing: .05em; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); }
  tbody tr { transition: background .1s; }
  tbody tr:hover { background: rgba(255,255,255,.03); }
  tbody td { padding: 0.875rem 1rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tbody tr:last-child td { border-bottom: none; }

  /* BUTTONS */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 18px; border-radius: 8px; font-size: 0.875rem; font-weight: 500; cursor: pointer; border: none; transition: all .15s; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { background: var(--accent-hover); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(99,102,241,.4); }
  .btn-success { background: var(--green); color: #fff; }
  .btn-success:hover { background: #16a34a; }
  .btn-danger  { background: var(--red); color: #fff; }
  .btn-danger:hover  { background: #dc2626; }
  .btn-ghost   { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
  .btn-ghost:hover   { background: var(--border); }
  .btn-sm { padding: 5px 12px; font-size: 0.8rem; }

  /* FORM */
  .form-group { margin-bottom: 1rem; }
  label { display: block; font-size: 0.8rem; font-weight: 500; color: var(--muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: .04em; }
  input[type=text], input[type=number], select, textarea {
    width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); padding: 8px 12px; font-size: 0.875rem; font-family: inherit;
    transition: border-color .15s;
  }
  input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
  textarea { resize: vertical; min-height: 60px; }

  /* SPLIT VIEW */
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; align-items: start; }
  @media (max-width: 1024px) { .split { grid-template-columns: 1fr; } }
  .invoice-image { width: 100%; border-radius: 8px; border: 1px solid var(--border); }
  .sticky-panel { position: sticky; top: 1rem; }

  /* ALERT */
  .alert { padding: 10px 14px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 1rem; display: flex; gap: 8px; align-items: flex-start; }
  .alert-error  { background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3); color: #fca5a5; }
  .alert-warn   { background: rgba(234,179,8,.1); border: 1px solid rgba(234,179,8,.3); color: #fde68a; }
  .alert-info   { background: rgba(99,102,241,.1); border: 1px solid rgba(99,102,241,.3); color: #c7d2fe; }
  .alert-success { background: rgba(34,197,94,.1); border: 1px solid rgba(34,197,94,.3); color: #bbf7d0; }

  /* LINES TABLE */
  .lines-table input { padding: 4px 8px; font-size: 0.8rem; }

  /* STAT CARDS */
  .stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem; }
  .stat-card .value { font-size: 1.8rem; font-weight: 700; }
  .stat-card .label { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }

  /* CONFIDENCE BAR */
  .conf-bar { height: 4px; background: var(--border); border-radius: 4px; margin-top: 4px; }
  .conf-bar-fill { height: 100%; border-radius: 4px; transition: width .3s; }

  .flash { padding: 12px 16px; border-radius: 8px; margin-bottom: 1.5rem; font-size: 0.875rem; }
  .flash-success { background: rgba(34,197,94,.15); border: 1px solid rgba(34,197,94,.4); color: #86efac; }
  .flash-error   { background: rgba(239,68,68,.15); border: 1px solid rgba(239,68,68,.4); color: #fca5a5; }

  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; background: var(--surface2); color: var(--muted); margin-right: 4px; }
</style>
</head>
<body>
<nav>
  <span class="brand">⚡ Invoice <span>Intake</span></span>
  <a href="/" class="nav-link">Dashboard</a>
  <a href="/api/registered" class="nav-link" target="_blank">Registered</a>
</nav>
<div class="container">
{% block content %}{% endblock %}
</div>
</body>
</html>
"""

DASHBOARD_HTML = BASE_HTML.replace("{% block content %}{% endblock %}", """
{% block content %}
<h1>Invoice Review Dashboard</h1>
<p class="subtitle">Pipeline results for {{ results|length }} invoices</p>

{% if flash_msg %}
<div class="flash flash-{{ flash_type }}">{{ flash_msg }}</div>
{% endif %}

<div class="stats">
  <div class="stat-card">
    <div class="value" style="color:#4ade80">{{ counts.REGISTERED }}</div>
    <div class="label">Auto-registered</div>
  </div>
  <div class="stat-card">
    <div class="value" style="color:#fbbf24">{{ counts.NEEDS_REVIEW }}</div>
    <div class="label">Needs review</div>
  </div>
  <div class="stat-card">
    <div class="value" style="color:#f87171">{{ counts.REGISTRATION_FAILED + counts.EXTRACTION_FAILED }}</div>
    <div class="label">Failed</div>
  </div>
  <div class="stat-card">
    <div class="value" style="color:#a5b4fc">{{ counts.APPROVED }}</div>
    <div class="label">Approved manually</div>
  </div>
  <div class="stat-card">
    <div class="value" style="color:#94a3b8">{{ counts.REJECTED }}</div>
    <div class="label">Rejected</div>
  </div>
</div>

<div class="card">
<table>
  <thead>
    <tr>
      <th>File</th>
      <th>Supplier</th>
      <th>Invoice #</th>
      <th>Total (JPY)</th>
      <th>Confidence</th>
      <th>Status</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
  {% for r in results %}
  <tr>
    <td><code style="font-size:0.8rem">{{ r.source_file }}</code></td>
    <td>{{ r.supplier_name or '—' }}</td>
    <td style="font-size:0.8rem">{{ r.invoice_number or '—' }}</td>
    <td style="text-align:right">{{ '{:,}'.format(r.total_amount) if r.total_amount else '—' }}</td>
    <td style="min-width:100px">
      {% set conf = ((r.extraction_confidence or 0) * 100)|int %}
      <div style="font-size:0.75rem;color:var(--muted)">{{ conf }}%</div>
      <div class="conf-bar"><div class="conf-bar-fill" style="width:{{ conf }}%;background:{% if conf >= 85 %}#4ade80{% elif conf >= 60 %}#fbbf24{% else %}#f87171{% endif %}"></div></div>
    </td>
    <td>
      {% set s = r.status %}
      {% if s == 'REGISTERED' %}
        <span class="badge badge-green">✓ Registered</span>
      {% elif s == 'NEEDS_REVIEW' %}
        <span class="badge badge-yellow">⚠ Review</span>
      {% elif s == 'APPROVED' %}
        <span class="badge badge-blue">✓ Approved</span>
      {% elif s == 'REJECTED' %}
        <span class="badge badge-gray">✗ Rejected</span>
      {% elif s == 'REGISTRATION_FAILED' %}
        <span class="badge badge-red">✗ API Error</span>
      {% elif s == 'EXTRACTION_FAILED' %}
        <span class="badge badge-red">✗ Extract Fail</span>
      {% else %}
        <span class="badge badge-gray">{{ s }}</span>
      {% endif %}
      {% if r.accounting_id %}
        <span class="tag">{{ r.accounting_id }}</span>
      {% endif %}
    </td>
    <td>
      {% if r.status in ['NEEDS_REVIEW', 'REGISTRATION_FAILED', 'EXTRACTION_FAILED'] %}
        <a href="/review/{{ r.source_file }}" class="btn btn-primary btn-sm">Review →</a>
      {% else %}
        <a href="/review/{{ r.source_file }}" class="btn btn-ghost btn-sm">View</a>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% endblock %}
""")

REVIEW_HTML = BASE_HTML.replace("{% block title %}Invoice Review{% endblock %}", "{% block title %}Review {{ inv.source_file }}{% endblock %}").replace("{% block content %}{% endblock %}", """
{% block content %}
<div style="display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem">
  <a href="/" class="btn btn-ghost btn-sm">← Back</a>
  <h1 style="margin:0">{{ inv.source_file }}</h1>
  {% set s = inv.status %}
  {% if s == 'REGISTERED' %}<span class="badge badge-green">✓ Registered</span>
  {% elif s == 'NEEDS_REVIEW' %}<span class="badge badge-yellow">⚠ Needs Review</span>
  {% elif s == 'APPROVED' %}<span class="badge badge-blue">✓ Approved</span>
  {% elif s == 'REJECTED' %}<span class="badge badge-gray">✗ Rejected</span>
  {% elif s == 'REGISTRATION_FAILED' %}<span class="badge badge-red">✗ API Error</span>
  {% else %}<span class="badge badge-gray">{{ s }}</span>{% endif %}
</div>

{% if flash_msg %}
<div class="flash flash-{{ flash_type }}">{{ flash_msg }}</div>
{% endif %}

{% for issue in inv.validation_issues %}
<div class="alert alert-{{ 'error' if issue.severity == 'ERROR' else 'warn' }}">
  <strong>{{ issue.code }}</strong>: {{ issue.message }}
  {% if issue.detail %}<span style="opacity:.7"> — {{ issue.detail }}</span>{% endif %}
</div>
{% endfor %}

{% for note in inv.normalisation_notes %}
<div class="alert alert-info">{{ note }}</div>
{% endfor %}

<div class="split">
  <!-- LEFT: Invoice image -->
  <div>
    <div class="card" style="padding:1rem">
      <div style="font-size:0.75rem;color:var(--muted);margin-bottom:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em">Original Document</div>
      {% if image_data %}
        <img src="{{ image_data }}" class="invoice-image" alt="Invoice image">
      {% else %}
        <div style="padding:3rem;text-align:center;color:var(--muted)">Image not available</div>
      {% endif %}
    </div>
  </div>

  <!-- RIGHT: Edit form -->
  <div class="sticky-panel">
    <div class="card">
      <div style="font-size:0.75rem;color:var(--muted);margin-bottom:1rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em">Extracted & Normalised Data</div>
      <form method="POST" action="/review/{{ inv.source_file }}/approve">

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem">
          <div class="form-group" style="grid-column:1/-1">
            <label>Supplier Name (extracted)</label>
            <input type="text" name="supplier_name" value="{{ inv.supplier_name or '' }}" readonly style="opacity:.6">
          </div>

          <div class="form-group" style="grid-column:1/-1">
            <label>Partner Code *</label>
            <select name="partner_code" required>
              <option value="">-- select partner --</option>
              {% for p in partners %}
              <option value="{{ p.partner_code }}" {% if p.partner_code == inv.partner_code %}selected{% endif %}>
                {{ p.partner_code }} — {{ p.name }}
              </option>
              {% endfor %}
            </select>
          </div>

          <div class="form-group" style="grid-column:1/-1">
            <label>Invoice Number *</label>
            <input type="text" name="invoice_number" value="{{ inv.invoice_number or '' }}" required>
          </div>

          <div class="form-group">
            <label>Issue Date * (YYYY-MM-DD)</label>
            <input type="text" name="issue_date" value="{{ inv.issue_date or '' }}" required pattern="\\d{4}-\\d{2}-\\d{2}">
          </div>

          <div class="form-group">
            <label>Due Date * (YYYY-MM-DD)</label>
            <input type="text" name="due_date" value="{{ inv.due_date or '' }}" required pattern="\\d{4}-\\d{2}-\\d{2}">
          </div>

          <div class="form-group">
            <label>Subtotal (JPY) *</label>
            <input type="number" name="subtotal" value="{{ inv.subtotal or '' }}" required>
          </div>

          <div class="form-group">
            <label>Tax Amount (JPY) *</label>
            <input type="number" name="tax_amount" value="{{ inv.tax_amount or '' }}" required>
          </div>

          <div class="form-group" style="grid-column:1/-1">
            <label>Total Amount (JPY) *</label>
            <input type="number" name="total_amount" value="{{ inv.total_amount or '' }}" required>
          </div>
        </div>

        <!-- Line items -->
        <div style="margin-bottom:1rem">
          <label>Line Items</label>
          <div style="overflow-x:auto">
          <table class="lines-table" style="font-size:0.8rem;margin-top:0.5rem">
            <thead>
              <tr style="color:var(--muted)">
                <th style="padding:4px 8px;text-align:left">Description</th>
                <th style="padding:4px 8px;text-align:right">Qty</th>
                <th style="padding:4px 8px">Unit</th>
                <th style="padding:4px 8px;text-align:right">Unit Price</th>
                <th style="padding:4px 8px;text-align:right">Amount</th>
                <th style="padding:4px 8px">Tax</th>
              </tr>
            </thead>
            <tbody>
            {% for i, line in inv.lines|enumerate %}
            <tr>
              <td><input type="text" name="line_desc_{{ i }}" value="{{ line.description }}" style="min-width:150px"></td>
              <td><input type="number" name="line_qty_{{ i }}" value="{{ line.quantity or '' }}" style="width:60px;text-align:right"></td>
              <td><input type="text" name="line_unit_{{ i }}" value="{{ line.unit }}" style="width:50px"></td>
              <td><input type="number" name="line_uprice_{{ i }}" value="{{ line.unit_price or '' }}" style="width:90px;text-align:right"></td>
              <td><input type="number" name="line_amount_{{ i }}" value="{{ line.amount }}" style="width:90px;text-align:right" required></td>
              <td>
                <select name="line_tax_{{ i }}" style="width:65px">
                  <option value="T10" {% if line.tax_code == 'T10' %}selected{% endif %}>T10</option>
                  <option value="T08" {% if line.tax_code == 'T08' %}selected{% endif %}>T08</option>
                </select>
              </td>
            </tr>
            {% endfor %}
            </tbody>
          </table>
          <input type="hidden" name="line_count" value="{{ inv.lines|length }}">
          </div>
        </div>

        <div style="display:flex;gap:0.75rem;flex-wrap:wrap">
          {% if inv.status not in ['REGISTERED', 'APPROVED'] %}
          <button type="submit" class="btn btn-success">✓ Approve &amp; Register</button>
          {% endif %}
          <button type="button" class="btn btn-ghost" onclick="window.history.back()">Cancel</button>
        </div>
      </form>

      {% if inv.status not in ['REGISTERED', 'APPROVED', 'REJECTED'] %}
      <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)">
        <form method="POST" action="/review/{{ inv.source_file }}/reject" style="display:inline">
          <button type="submit" class="btn btn-danger btn-sm" onclick="return confirm('Reject this invoice?')">✗ Reject</button>
        </form>
      </div>
      {% endif %}

      {% if inv.accounting_id %}
      <div class="alert alert-success" style="margin-top:1rem">
        Registered as <strong>{{ inv.accounting_id }}</strong>
      </div>
      {% endif %}

      {% if inv.api_result and inv.api_result != 'success' %}
      <div class="alert alert-error" style="margin-top:1rem">
        API error: {{ inv.api_result }}
      </div>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
""")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    results = _load_results()
    counts = {
        "REGISTERED": 0, "NEEDS_REVIEW": 0, "REGISTRATION_FAILED": 0,
        "EXTRACTION_FAILED": 0, "APPROVED": 0, "REJECTED": 0,
    }
    for r in results:
        s = r.get("status", "UNKNOWN")
        counts[s] = counts.get(s, 0) + 1

    flash_msg = request.args.get("flash", "")
    flash_type = request.args.get("flash_type", "success")

    return render_template_string(
        DASHBOARD_HTML,
        results=results,
        counts=counts,
        flash_msg=flash_msg,
        flash_type=flash_type,
    )


@app.route("/review/<path:invoice_id>")
def review(invoice_id: str):
    inv = _get_invoice(invoice_id)
    if inv is None:
        return "Invoice not found", 404

    image_data = _get_image_data_uri(invoice_id)

    ok, partners, _ = api.get_partners()
    partners = partners or []

    flash_msg = request.args.get("flash", "")
    flash_type = request.args.get("flash_type", "success")

    # Make enumerate available in template
    return render_template_string(
        REVIEW_HTML,
        inv=inv,
        image_data=image_data,
        partners=partners,
        flash_msg=flash_msg,
        flash_type=flash_type,
        enumerate=enumerate,
    )


@app.route("/review/<path:invoice_id>/approve", methods=["POST"])
def approve(invoice_id: str):
    results = _load_results()
    inv = next((r for r in results if r.get("source_file") == invoice_id), None)
    if inv is None:
        return "Invoice not found", 404

    form = request.form

    # Rebuild lines from form
    line_count = int(form.get("line_count", 0))
    lines = []
    for i in range(line_count):
        desc = form.get(f"line_desc_{i}", "")
        if not desc:
            continue
        qty_raw = form.get(f"line_qty_{i}", "")
        uprice_raw = form.get(f"line_uprice_{i}", "")
        lines.append({
            "description": desc,
            "quantity": int(qty_raw) if qty_raw else None,
            "unit": form.get(f"line_unit_{i}", "式"),
            "unit_price": int(uprice_raw) if uprice_raw else None,
            "amount": int(form.get(f"line_amount_{i}", 0)),
            "tax_code": form.get(f"line_tax_{i}", "T10"),
        })

    payload = {
        "partner_code": form.get("partner_code", ""),
        "invoice_number": form.get("invoice_number", ""),
        "issue_date": form.get("issue_date", ""),
        "due_date": form.get("due_date", ""),
        "currency": "JPY",
        "lines": lines,
        "subtotal": int(form.get("subtotal", 0)),
        "tax_amount": int(form.get("tax_amount", 0)),
        "total_amount": int(form.get("total_amount", 0)),
    }

    ok, data, err = api.register_invoice(payload)

    if ok:
        inv["status"] = "APPROVED"
        inv["accounting_id"] = data.get("accounting_id") if data else None
        inv["api_result"] = "success"
        # Update normalised fields from form
        inv["partner_code"] = payload["partner_code"]
        inv["invoice_number"] = payload["invoice_number"]
        inv["issue_date"] = payload["issue_date"]
        inv["due_date"] = payload["due_date"]
        inv["subtotal"] = payload["subtotal"]
        inv["tax_amount"] = payload["tax_amount"]
        inv["total_amount"] = payload["total_amount"]
        inv["lines"] = lines
        _save_results(results)
        flash = f"✓ Registered as {inv['accounting_id']}"
        flash_type = "success"
    else:
        inv["status"] = "REGISTRATION_FAILED"
        inv["api_result"] = err
        _save_results(results)
        flash = f"✗ API error: {err.get('code','?')} — {err.get('message','')}" if err else "Unknown error"
        flash_type = "error"

    return redirect(url_for("review", invoice_id=invoice_id, flash=flash, flash_type=flash_type))


@app.route("/review/<path:invoice_id>/reject", methods=["POST"])
def reject(invoice_id: str):
    results = _load_results()
    inv = next((r for r in results if r.get("source_file") == invoice_id), None)
    if inv:
        inv["status"] = "REJECTED"
        _save_results(results)
    return redirect(url_for("dashboard", flash=f"Invoice {invoice_id} rejected.", flash_type="success"))


@app.route("/api/registered")
def api_registered():
    ok, data, err = api.get_invoices()
    if ok:
        return jsonify({"success": True, "invoices": data, "count": len(data)})
    return jsonify({"success": False, "error": err}), 500
