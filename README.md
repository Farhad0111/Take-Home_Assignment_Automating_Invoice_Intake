# Invoice Intake Automation

Automates the manual entry of Japanese supplier invoices into an accounting system using a multimodal LLM (GPT-4o-mini), deterministic normalisation, business-rule validation, and a human review UI for edge cases.

---

## How to Run

> **Windows note:** Use `py` instead of `python` (Python Launcher for Windows).

### Prerequisites

```powershell
pip install -r requirements.txt
```

### Step 1 — Start the Accounting API (Terminal 1, keep open)

```powershell
cd "C:\Users\Farhad\Desktop\Take-Home_Assignment_Automating_Invoice_Intake"
py accounting_api.py
```

Expected output:
```
Mock Accounting API listening on http://localhost:8080
  API key: demo-key-1234
  Press Ctrl+C to stop.
```

### Step 2 — Run the Pipeline (Terminal 2)

```powershell
py scripts/start.py --headless
```

Processes all 12 invoices. Auto-registers high-confidence ones. Saves results to `data/results/results.json`.

### Step 3 — Open the Review UI (Terminal 2)

```powershell
py scripts/start.py --ui-only
```

Opens http://localhost:5000 automatically. Review, correct, and approve/reject flagged invoices.

### Or: Run Everything in One Command

```powershell
py scripts/start.py
```

### Run Unit Tests

```powershell
py -m pytest tests/ -v
```

Expected: **43 passed**

---

## All Commands

| Command | What it does |
|---|---|
| `py accounting_api.py` | Start mock accounting API on port 8080 |
| `py scripts/start.py` | Pipeline + prompt to open UI |
| `py scripts/start.py --headless` | Pipeline only, no UI |
| `py scripts/start.py --ui-only` | Open review UI only |
| `py -m pytest tests/ -v` | Run all unit tests |

---

## Input

| File | Type | Description |
|---|---|---|
| `invoices/invoice_01.pdf` | PDF (text layer) | Japanese supplier invoice |
| `invoices/invoice_02.pdf` | PDF (text layer) | Japanese supplier invoice |
| `invoices/invoice_03.pdf` | PDF (text layer) | Japanese supplier invoice |
| `invoices/invoice_04.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_05.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_06.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_07.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_08.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_09.pdf` | PDF (scanned) | PDF containing only a scan |
| `invoices/invoice_10.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_11.jpg` | Scanned image | Office copier scan |
| `invoices/invoice_12.jpg` | Scanned image | Office copier scan |

All invoices are **Japanese business documents** (請求書). The AI handles the Japanese text — no manual translation needed.

---

## Output

### 1. `data/raw_extractions/<invoice>.json` — What the AI read

```json
{
  "supplier_name": "株式会社山田製作所",
  "registration_no": "T1010001000101",
  "invoice_number": "YM-2026-0001",
  "issue_date_raw": "令和8年1月7日",
  "due_date_raw": "翌月末",
  "subtotal_raw": "168,000",
  "tax_amount_raw": "16,800",
  "total_amount_raw": "184,800",
  "lines": [
    {
      "description": "精密部品 A-100",
      "quantity": 120,
      "unit": "個",
      "unit_price": 1250,
      "amount": 150000,
      "tax_rate_hint": 0.10
    }
  ],
  "confidence": {
    "supplier_name": 0.98,
    "invoice_number": 0.95,
    "issue_date_raw": 0.90,
    "subtotal_raw": 0.92
  }
}
```

### 2. `data/normalized/<invoice>.json` — After normalisation

```json
{
  "partner_code": "P-1001",
  "invoice_number": "YM-2026-0001",
  "issue_date": "2026-01-07",
  "due_date": "2026-01-31",
  "subtotal": 168000,
  "tax_amount": 16800,
  "total_amount": 184800,
  "lines": [
    {
      "description": "精密部品 A-100",
      "quantity": 120,
      "unit": "個",
      "unit_price": 1250,
      "amount": 150000,
      "tax_code": "T10"
    }
  ]
}
```

### 3. `data/results/results.json` — Final status of all invoices

```json
{
  "source_file": "invoice_01.pdf",
  "status": "REGISTERED",
  "supplier_name": "株式会社山田製作所",
  "partner_code": "P-1001",
  "invoice_number": "YM-2026-0001",
  "issue_date": "2026-01-07",
  "due_date": "2026-01-31",
  "subtotal": 168000,
  "tax_amount": 16800,
  "total_amount": 184800,
  "extraction_confidence": 0.93,
  "validation_status": "PASS",
  "validation_issues": [],
  "disposition": "AUTO",
  "accounting_id": "ACC-0001",
  "api_result": "success"
}
```

### Invoice Status Values

| Status | Meaning |
|---|---|
| `REGISTERED` | Auto-registered by pipeline |
| `NEEDS_REVIEW` | Routed to human review UI |
| `APPROVED` | Human approved and registered via UI |
| `REJECTED` | Human rejected via UI |
| `REGISTRATION_FAILED` | API returned an error |
| `EXTRACTION_FAILED` | AI could not read the invoice |

---

## Pipeline Architecture

```
invoices/ (PDF / JPG)
     │
     ▼
┌────────────────────────────┐
│   Multimodal LLM           │  GPT-4o-mini vision (temperature=0)
│   Document Extraction      │  Returns structured JSON + per-field
│                            │  confidence score (0.0 – 1.0)
│ Supplier / Invoice / Dates │
│ Lines / Amounts / Tax      │
│ Confidence                 │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ Deterministic Normalizer   │  Pure Python — no AI
│                            │
│ Partner → partner_code     │  Exact → Alias → T-number → Fuzzy
│ Registration number        │
│ Date → YYYY-MM-DD          │  Wareki (令和/平成), kanji, slash, relative
│ Tax → T10 / T08            │  From rate hint or default T10
│ Amount → integer JPY       │  Strips ¥ commas full-width digits
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ Validation & Reconciliation│  Mirrors API rules exactly
│                            │
│ Partner exists             │
│ Date validity              │
│ Subtotal = Σ lines         │
│ Tax = floor(rate × subtotal│
│ Total = subtotal + tax     │
│ Duplicate check            │
└─────────────┬──────────────┘
              │
     ┌────────┴────────┐
     │                 │
     ▼                 ▼
PASS + HIGH CONF.  WARNING / FAIL
(conf ≥ 0.85)      (or conf < 0.85)
     │                 │
     ▼                 ▼
┌─────────────┐   ┌──────────────┐
│ AUTO        │   │ HUMAN REVIEW │
│ REGISTER    │   │              │
│             │   │ Correct data │
│ All checks  │   │ Approve      │
│ pass        │   │ Reject       │
└──────┬──────┘   └──────┬───────┘
       │                 │
       │          ┌──────┴──────┐
       │          │             │
       │          ▼             ▼
       │       APPROVE       REJECT
       │          │
       └──────┬───┘
              │
              ▼
   ┌─────────────────────┐
   │ Accounting API      │
   │ POST /invoices      │
   └─────────────────────┘
```

---

## Project Structure

```
invoice-intake/
│
├── README.md                          ← This file
├── SUBMISSION.md                      ← Assignment submission document
├── .env                               ← API keys (OPENAI_API_KEY)
├── .env.example                       ← Template for .env
├── requirements.txt                   ← Python dependencies
│
├── accounting_api.py                  ← Provided API — behaviour unchanged
│
├── invoices/
│   ├── invoice_01.pdf                 ← PDF (text layer)
│   ├── invoice_02.pdf
│   ├── invoice_03.pdf
│   ├── invoice_04.jpg                 ← Scanned image
│   ├── ...
│   └── invoice_12.jpg
│
├── src/
│   ├── __init__.py
│   │
│   ├── extractor/                     ← GPT-4o-mini vision extraction
│   │   ├── __init__.py
│   │   ├── llm_client.py             ← PDF→image rendering, API call, response parse
│   │   ├── prompts.py                ← System prompt (JSON schema instructions)
│   │   └── schema.py                 ← RawInvoice, RawLineItem, ExtractionResult
│   │
│   ├── normalizer/                    ← Deterministic cleanup (no AI)
│   │   ├── __init__.py
│   │   ├── partner_matcher.py        ← Exact→Alias→T-number→Fuzzy matching
│   │   ├── date_parser.py            ← Wareki/kanji/ISO/relative date parsing
│   │   └── tax_currency.py           ← Amount cleaning, T10/T08 inference
│   │
│   ├── validation/                    ← Business rule checks
│   │   ├── __init__.py
│   │   ├── rules.py                  ← subtotal/tax/total/dup/date checks
│   │   ├── result.py                 ← ValidationResult (PASS/WARN/FAIL)
│   │   └── risk_gate.py              ← AUTO vs REVIEW decision (conf ≥ 0.85)
│   │
│   ├── accounting_client/
│   │   ├── __init__.py
│   │   └── client.py                 ← REST wrapper for POST/GET /invoices
│   │
│   ├── review/
│   │   ├── __init__.py
│   │   └── app.py                    ← Flask review UI (dark-mode, side-by-side)
│   │
│   └── pipeline.py                   ← Orchestrator: ties all steps together
│
├── data/
│   ├── raw_extractions/               ← AI output per invoice (JSON)
│   ├── normalized/                    ← After normalisation (JSON)
│   └── results/
│       └── results.json               ← Final status of all 12 invoices
│
├── tests/
│   ├── __init__.py
│   ├── test_date_parser.py           ← 17 tests (Wareki, kanji, relative dates)
│   ├── test_partner_matcher.py       ← 12 tests (exact, alias, T-number, fuzzy)
│   ├── test_validation_rules.py      ← 14 tests (math, duplicates, dates)
│   └── fixtures/
│
├── scripts/
│   └── start.py                      ← Single entry point (pipeline + UI)
│
└── demo/
    ├── screenshots/
    └── demo_video.mp4
```

---

## Accounting API Endpoints

The mock API runs at `http://localhost:8080`.  
All endpoints (except `/health`) require the header: `X-API-Key: demo-key-1234`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check (no auth) |
| GET | `/partners` | Supplier master (5 companies) |
| GET | `/tax-codes` | T10 (10%) and T08 (8%) |
| POST | `/invoices` | Register an invoice |
| GET | `/invoices` | List all registered invoices |
| DELETE | `/invoices` | Clear all (reset) |

### Partner Master

| Code | Name (Japanese) | Aliases |
|---|---|---|
| P-1001 | 株式会社山田製作所 | ヤマダ製作所, 山田製作所 |
| P-1002 | 有限会社佐藤商店 | 佐藤商店 |
| P-1003 | 東京フーズ株式会社 | 東京フーズ |
| P-1004 | 大阪機械工業株式会社 | 大阪機械, 大阪機械工業 |
| P-1005 | みらいITソリューションズ株式会社 | みらいIT |

### API Rules (enforced server-side)

- Dates: `YYYY-MM-DD` format only
- Amounts: integers in JPY (no decimals)
- Tax: `T10` or `T08` code (not a percentage)
- Partner: must exist in the partner master
- Tax math: `floor(rate × subtotal_per_code)` — the pipeline pre-validates this

---

## Environment Variables (`.env`)

```
OPENAI_API_KEY=sk-proj-...      # GPT-4o-mini API key
ACCOUNTING_API_URL=http://localhost:8080
ACCOUNTING_API_KEY=demo-key-1234
```

---

## Cost Estimate

| Metric | Value |
|---|---|
| LLM used | GPT-4o-mini (vision) |
| Cost per invoice | ~$0.005 USD |
| 1,000 invoices/month | ~$5 USD |
| Processing time per invoice | 5–15 seconds |
| Time for 12 invoices | ~2 minutes |