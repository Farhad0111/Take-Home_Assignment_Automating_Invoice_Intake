# Invoice Intake Automation

An end-to-end invoice intake pipeline for Japanese supplier invoices. The system reads PDF and image invoices with GPT-4o-mini vision, converts the extracted values into accounting-system format, validates the result with deterministic rules, and automatically registers only the records that are safe to send to the accounting API.

The project is intentionally split between probabilistic extraction and deterministic processing:

- The LLM reads the document and returns structured fields with per-field confidence scores.
- Python normalizes Japanese dates, JPY amounts, tax codes, and supplier names.
- Python validation mirrors the accounting API's business rules before a request is made.
- A risk gate decides between automatic registration and human review.
- The mock accounting API provides partner data, duplicate detection, and server-side validation.

## What The System Does

For every supported file in `invoices/`, the pipeline:

1. Loads the invoice as one or more images.
2. Sends the images to GPT-4o-mini with an extraction schema and Japanese-invoice instructions.
3. Parses the JSON response and retries transient API or parsing failures up to three total attempts.
4. Saves the raw extraction to `data/raw_extractions/`.
5. Matches the supplier to an accounting partner.
6. Converts dates, amounts, and tax hints into normalized values.
7. Saves the normalized record to `data/normalized/`.
8. Checks partner, date, line, tax, total, and duplicate rules.
9. Sends only `PASS` records with confidence of at least `0.85` to the automatic registration path.
10. Sends warnings, failures, low-confidence records, and unmatched suppliers to review status.
11. Saves one result record per input file to `data/results/results.json`.

The LLM is never trusted as the final authority for accounting math. The normalizer and validation layer recalculate values from line items, and the API validates the request again.

## Requirements

- Windows with the Python Launcher (`py`)
- Python 3.10 or newer
- An OpenAI API key with access to GPT-4o-mini
- Internet access for OpenAI API calls
- `pip` for installing dependencies

Install dependencies from the project root:

```powershell
cd "C:\Users\Farhad\Desktop\Take-Home_Assignment_Automating_Invoice_Intake"
py -m pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root. Do not commit this file or expose the OpenAI key.

```dotenv
OPENAI_API_KEY=sk-proj-your-key-here
ACCOUNTING_API_URL=http://localhost:8080
ACCOUNTING_API_KEY=demo-key-1234
```

Defaults used by the code are:

| Variable | Default | Used by |
|---|---|---|
| `OPENAI_API_KEY` | No default | `src/extractor/llm_client.py` |
| `ACCOUNTING_API_URL` | `http://localhost:8080` | `src/accounting_client/client.py` |
| `ACCOUNTING_API_KEY` | `demo-key-1234` | `src/accounting_client/client.py` and `accounting_api.py` |

## How To Run

### 1. Start the mock accounting API

Open Terminal 1 and keep it running:

```powershell
py accounting_api.py
```

Expected startup output:

```text
Mock Accounting API listening on http://localhost:8080
  API key: demo-key-1234
  Press Ctrl+C to stop.
```

The API stores registered invoices in memory. Restarting `accounting_api.py` clears its records.

### 2. Run the pipeline

Open Terminal 2:

```powershell
py scripts/start.py
```

`scripts/start.py` checks the API health endpoint and then calls `src.pipeline.run_pipeline()`. The pipeline processes all supported files in `invoices/` in sorted filename order.

### 3. Run the tests

```powershell
py -m pytest tests/ -v
```

The repository's unit-test suite covers date parsing, partner matching, and validation rules. The expected count in the original assignment is 43 tests; the exact count may change as tests are added.

### Reset registered invoices

The mock API exposes a reset endpoint. With the API running, use:

```powershell
Invoke-RestMethod -Method Delete `
  -Uri http://localhost:8080/invoices `
  -Headers @{"X-API-Key" = "demo-key-1234"}
```

This clears the API's in-memory registration list. It does not delete JSON files under `data/`.

### Current command and UI status

The current `scripts/start.py` accepts no command-line flags. The implemented entry point is `py scripts/start.py`.

The pipeline currently writes `NEEDS_REVIEW` records and persists their issues in `data/results/results.json`, but this checkout does not contain the `src/review/` Flask UI described in the original assignment outline. Therefore `--headless` and `--ui-only` are not implemented by the current script. Review records must currently be inspected or handled using the saved JSON and the API.

The startup health check currently probes `http://localhost:8080/health` directly. `ACCOUNTING_API_URL` is used by the accounting client for partner and invoice requests; if the API is moved to another host or port, update `scripts/start.py` as well as `.env`.

## Pipeline Architecture


![Invoice intake pipeline](Demo/Pipeline%20Architecture/Pipeline%20Architecture.png)

```
invoices/ (PDF / JPG)
     │
     ▼
┌────────────────────────────┐
│   Multimodal LLM           │  GPT-4o-mini vision (temperature=0)
│   Document Extraction      │  Returns structured JSON + per-field
│                            │  confidence score (0.0 – 1.0)
│                            │  JSON repair on parse failure
│                            │  Retry up to 3 times
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

### Stage 1: File loading and extraction

`src/extractor/llm_client.py` handles the document boundary.

- PDF files are rendered page by page with PyMuPDF at approximately 144 DPI.
- JPEG and PNG files are converted to JPEG bytes with Pillow.
- Every page is attached to a single vision request.
- The system prompt requires one JSON object with supplier, registration number, invoice number, dates, amounts, line items, tax hints, and confidence values.
- GPT-4o-mini is called with `temperature=0` and a maximum of 4096 tokens.
- The parser removes accidental code fences, tries normal JSON parsing, and then applies lightweight repair for trailing commas, control characters, and truncated closing brackets.
- API errors and JSON parse failures are retried up to `MAX_RETRIES = 3` with exponential delays of 2 and 4 seconds between attempts.
- File loading errors are treated as permanent and are not retried.

The extraction result is represented by the data classes in `src/extractor/schema.py`:

- `RawInvoice` contains the values as read from the document.
- `RawLineItem` contains description, quantity, unit, unit price, amount, and an optional tax-rate hint.
- `ExtractionResult` contains success/error state and computes overall confidence as the arithmetic mean of the returned confidence values.

### Stage 2: Raw extraction output

After a successful extraction, `src/pipeline.py` writes one file with the same stem as the source invoice:

```text
data/raw_extractions/invoice_01.json
```

Example shape:

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
      "tax_rate_hint": 0.1
    }
  ],
  "confidence": {
    "supplier_name": 0.98,
    "invoice_number": 0.95,
    "issue_date_raw": 0.9
  }
}
```

Raw values deliberately retain the document's original date and amount notation so extraction can be audited separately from normalization.

### Stage 3: Supplier matching

`src/normalizer/partner_matcher.py` maps the extracted supplier to the partner master returned by `GET /partners`. Matching is attempted in this order:

1. Exact company name, including a normalized comparison that removes whitespace and common Japanese company suffixes.
2. Exact alias match.
3. Exact tax registration number (T-number).
4. Fuzzy character-set overlap, accepted at 60% or higher.

The matcher returns `(partner_code, confidence)`. Confidence values are 1.0 for exact matches, 0.95 for aliases, 0.90 for registration numbers, and a scaled value for fuzzy matches. No match returns `(None, 0.0)` and creates a validation error.

The mock partner master contains five fictional suppliers:

| Code | Name | Aliases |
|---|---|---|
| `P-1001` | 株式会社山田製作所 | ヤマダ製作所, 山田製作所 |
| `P-1002` | 有限会社佐藤商店 | 佐藤商店 |
| `P-1003` | 東京フーズ株式会社 | 東京フーズ |
| `P-1004` | 大阪機械工業株式会社 | 大阪機械, 大阪機械工業 |
| `P-1005` | みらいITソリューションズ株式会社 | みらいIT, みらいITソリューションズ |

The assignment invoices may contain fictional names that are not in this master. That is expected: those invoices are routed to review rather than silently assigned to the wrong partner. In a real deployment, the partner master would be populated with the organization's actual suppliers.

### Stage 4: Date normalization

`src/normalizer/date_parser.py` returns ISO dates in `YYYY-MM-DD` format. It supports:

- Japanese eras: `令和8年1月15日`, `平成30年3月20日`
- Romanized eras: `R8.1.15`, `H30/03/20`
- Japanese western notation: `2026年1月15日`
- Slash, dot, and dash notation: `2026/01/15`, `2026.01.15`, `2026-01-15`
- Relative terms: `翌月末` and `月末`
- Full-width digits

Relative terms use the current date by default. Tests pass an explicit reference date so the behavior is deterministic. An unparseable value becomes `None` and is reported by validation.

### Stage 5: Currency and tax normalization

`src/normalizer/tax_currency.py` provides two deterministic conversions:

- `clean_amount()` removes `¥`, `￥`, commas, spaces, `円`, and full-width digits, returning an integer JPY amount. It also supports negative credit-note markers such as `-`, `▲`, and `△`.
- `infer_tax_code()` maps a tax hint near `0.08` to `T08`. Missing or ambiguous hints default to `T10`.

If subtotal, tax, or total cannot be parsed, `src/pipeline.py` computes the missing value where enough line data is available and records a normalization note. The value still goes through validation.

### Stage 6: Normalized output

`src/pipeline.py` writes the normalized record to `data/normalized/<invoice-stem>.json`.

```json
{
  "supplier_name": "株式会社山田製作所",
  "partner_code": "P-1001",
  "partner_match_confidence": 1.0,
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
  ],
  "extraction_confidence": {
    "supplier_name": 0.98
  },
  "normalisation_notes": []
}
```

### Stage 7: Validation and reconciliation

`src/validation/rules.py` mirrors the accounting API's checks. It returns a `ValidationResult` with `PASS`, `WARN`, or `FAIL` and a list of structured issues.

The checks are:

- `PARTNER_NOT_FOUND`: a partner code is required.
- `DATE_MISSING` and `DATE_INVALID`: issue date must be present and parseable.
- `DUE_DATE_MISSING`: missing due date is a warning because it can be supplied during review.
- `DUE_DATE_INVALID`: a supplied due date must be ISO-formatted.
- `DUE_DATE_BEFORE_ISSUE`: due date cannot precede issue date.
- `NO_LINES`: at least one line item is required.
- `SUBTOTAL_MISSING` or `SUBTOTAL_MISMATCH`: subtotal must equal the sum of line amounts.
- `TAX_MISSING` or `TAX_MISMATCH`: tax is recalculated per tax code using `floor(rate * subtotal_for_code)`.
- `UNKNOWN_TAX_CODE`: only `T10` and `T08` are supported.
- `TOTAL_MISMATCH`: total must equal subtotal plus tax.
- `DUPLICATE_INVOICE`: the same partner and invoice number cannot already be registered.

Any error produces `FAIL`. A warning without an error produces `WARN`. Only a completely clean record produces `PASS`.

### Stage 8: Risk gate

`src/validation/risk_gate.py` applies the safety threshold:

| Validation | Overall extraction confidence | Disposition |
|---|---:|---|
| `PASS` | `>= 0.85` | `AUTO` |
| `PASS` | `< 0.85` | `REVIEW` |
| `WARN` | Any | `REVIEW` |
| `FAIL` | Any | `REVIEW` |

The threshold is `HIGH_CONF_THRESHOLD = 0.85`. A matching supplier or clean amount does not override a validation failure or low extraction confidence.

### Stage 9: Registration and duplicate behavior

`src/accounting_client/client.py` is a small REST wrapper. It adds the `X-API-Key` header and returns `(success, data, error)` tuples for API calls.

For an `AUTO` record, the pipeline sends `POST /invoices` with:

- `partner_code`
- `invoice_number`
- `issue_date` and `due_date`
- `currency: "JPY"`
- normalized line items
- integer subtotal, tax, and total amounts

On success, the API returns an accounting ID such as `ACC-0001`, and the result status becomes `REGISTERED`. If the API rejects the request, the result status becomes `REGISTRATION_FAILED`.

After a successful registration, the pipeline adds the partner and invoice number to its in-process duplicate list so later files in the same run are blocked. At startup it also calls `GET /invoices`, so records already registered by an earlier run are detected. This explains the common rerun behavior:

- An invoice that registered successfully in an earlier run remains stored by the running mock API.
- Running the pipeline again sees that record as a duplicate.
- The duplicate is routed to `NEEDS_REVIEW` instead of being registered twice.
- Restart the mock API or call `DELETE /invoices` to reset the demo state.

The three invoices that registered in an earlier run were the ones whose supplier matched the partner master and whose amounts passed reconciliation. On a later run they can be blocked as duplicates by design.

## API Reference

The mock server in `accounting_api.py` uses Python's standard library HTTP server. All endpoints except `/health` require `X-API-Key: demo-key-1234`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check and registered count; no authentication |
| `GET` | `/partners` | Partner master used by the normalizer |
| `GET` | `/tax-codes` | Returns `T10` (10%) and `T08` (8%) |
| `GET` | `/invoices` | Lists in-memory registered invoices |
| `POST` | `/invoices` | Validates and registers one invoice |
| `DELETE` | `/invoices` | Clears all in-memory registrations |

`POST /invoices` enforces the request shape, JPY integer amounts, known partner, known tax codes, date ordering, line subtotal, per-code tax, total, and duplicate uniqueness. The server recalculates amounts from lines instead of trusting the submitted totals.

Important response codes include:

| HTTP status | Error code | Meaning |
|---:|---|---|
| `401` | `UNAUTHORIZED` | Missing or invalid API key |
| `400` | `PARTNER_NOT_FOUND` / `UNKNOWN_TAX_CODE` | Unknown master data |
| `409` | `DUPLICATE_INVOICE` | Partner and invoice number already exist |
| `422` | `AMOUNT_MISMATCH` / `VALIDATION_ERROR` | Invalid accounting values or request shape |

## Input Files

The `invoices/` directory accepts `.pdf`, `.jpg`, `.jpeg`, and `.png` files. The sample set contains Japanese business invoices, including text-layer PDFs, scanned PDFs, and scanned images.

The extractor treats every PDF as a visual document. This means both text-layer and image-only PDFs follow the same rendering path and preserve tables and layout for the vision model.

## Output Files

### `data/raw_extractions/`

The closest representation of what GPT-4o-mini returned. Dates and amounts still use their extracted notation, and confidence values are retained.

### `data/normalized/`

The deterministic accounting-ready representation. It includes normalized dates, integer JPY amounts, partner code, tax codes, and any normalization notes.

### `data/results/results.json`

An array containing one final result record per source file. Typical fields are:

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
  "partner_match_confidence": 1.0,
  "validation_status": "PASS",
  "validation_issues": [],
  "disposition": "AUTO",
  "accounting_id": "ACC-0001",
  "api_result": "success"
}
```

Possible statuses are:

| Status | Meaning |
|---|---|
| `REGISTERED` | Automatically passed validation and was accepted by the API |
| `NEEDS_REVIEW` | Warning, validation failure, duplicate, unmatched partner, or low confidence |
| `REGISTRATION_FAILED` | Eligible for automatic registration, but the API rejected it |
| `EXTRACTION_FAILED` | File loading, model, parsing, or data-mapping failure |

## Project Structure

```

invoice-intake/
│
├── README.md                          ← This file
├── SUBMISSION.md                      ← Assignment submission document
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
│   └── test_validation_rules.py      ← 14 tests (math, duplicates, dates)
│
│
└── Demo/
    ├── screenshots/
    └── demo_video.mp4

```

### File-by-file responsibilities

| File | Responsibility |
|---|---|
| `scripts/start.py` | Adds the project root to `sys.path`, checks `/health`, and starts the pipeline |
| `src/pipeline.py` | Coordinates extraction, normalization, validation, gating, registration, and output files |
| `src/extractor/llm_client.py` | Converts input documents to images, calls OpenAI vision, repairs/parses JSON, and retries failures |
| `src/extractor/prompts.py` | Defines the model role, output schema, and Japanese invoice extraction rules |
| `src/extractor/schema.py` | Defines typed dataclasses for raw invoices, lines, and extraction results |
| `src/normalizer/partner_matcher.py` | Matches supplier names, aliases, and T-numbers to partner codes |
| `src/normalizer/date_parser.py` | Parses Wareki, western, full-width, and relative dates |
| `src/normalizer/tax_currency.py` | Cleans JPY amounts and maps tax hints to API tax codes |
| `src/validation/rules.py` | Recalculates and checks dates, lines, tax, totals, and duplicates |
| `src/validation/result.py` | Stores validation status and structured issues |
| `src/validation/risk_gate.py` | Applies the `0.85` confidence threshold and validation status |
| `src/accounting_client/client.py` | Performs authenticated API calls and normalizes response handling |
| `accounting_api.py` | Provides the local partner master and server-side accounting rules |

## Testing Strategy

The tests focus on deterministic logic that does not require an API key or network access:

- `test_date_parser.py` covers western dates, Japanese era dates, relative month-end dates, full-width digits, and invalid input.
- `test_partner_matcher.py` covers exact names, aliases, registration numbers, fuzzy matches, and unmatched suppliers.
- `test_validation_rules.py` covers passing records, missing partners, invalid dates, date ordering, missing due dates, subtotal/tax/total mismatches, unknown tax codes, empty lines, and duplicate invoices.

The LLM integration is intentionally not called by the unit tests because it requires a live OpenAI key and incurs cost. For an integration run, start the mock API, configure `.env`, and execute `py scripts/start.py`.

## Troubleshooting

### `Accounting API is NOT running`

Start `py accounting_api.py` in another terminal. The pipeline can technically continue with an empty partner list, but all supplier matches will fail and automatic registration cannot succeed.

### Most invoices become `NEEDS_REVIEW`

Inspect `validation_issues`, `normalisation_notes`, and both confidence fields in `data/results/results.json`. Common causes are:

- The extracted supplier is not in the five-entry demo partner master.
- A prior run already registered the same partner/invoice-number pair.
- A date or amount could not be parsed.
- Line amounts do not reconcile to subtotal, tax, or total.
- Overall extraction confidence is below `0.85`.

This is the expected behavior for uncertain or unknown data. It prevents a guessed supplier or incorrect amount from being posted automatically.

### Duplicate invoices after rerunning

The mock API keeps records in memory while its process is running. Use the `DELETE /invoices` command above or restart the API to reset the demo. Re-running the pipeline without resetting is useful for demonstrating duplicate protection.

### OpenAI key or package errors

Confirm `.env` is in the project root, then reinstall dependencies:

```powershell
py -m pip install -r requirements.txt
```

PDF processing requires PyMuPDF, image processing requires Pillow, HTTP calls use Requests, and the model client uses the OpenAI Python package.

## Design Decisions And Production Considerations

- Deterministic normalization and validation are kept outside the LLM so accounting rules are testable and repeatable.
- Confidence is treated as a routing signal, not proof of correctness.
- Partner matching is deliberately conservative: no match becomes review rather than an invented partner code.
- The API validates every automatic registration again, providing a second boundary against bad data.
- The demo API is in-memory and not a production accounting system. A deployment would use persistent storage, authentication and secret management, structured logging, rate limits, idempotency keys, and an actual review workflow.
- Relative due dates such as `翌月末` depend on the parser reference date. Production processing should make that reference date explicit for reproducibility.
- The current mock partner master contains fictional sample data. Real deployments must synchronize the organization's supplier master and registration numbers.

## Cost And Performance Estimate

The original assignment estimates approximately $0.005 per invoice with GPT-4o-mini and roughly 5 to 15 seconds per invoice, depending on image size, page count, API latency, and retries. Actual cost and duration depend on the current OpenAI pricing and request payloads.

| Metric | Value |
|---|---|
| LLM used | GPT-4o-mini (vision) |
| Cost per invoice | ~$0.005 USD |
| 1,000 invoices/month | ~$5 USD |
| Processing time per invoice | 5–15 seconds |
| Time for 12 invoices | ~2 minutes |