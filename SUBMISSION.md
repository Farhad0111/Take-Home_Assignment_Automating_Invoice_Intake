# Submission

- Name: Farhad
- Submission date (YYYY-MM-DD): 2026-09-11
- Hours actually spent: ~8
- Repository / how to run it: See instructions below

## How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the accounting API (keep this running in a separate terminal)
python accounting_api.py

# 3. Run the pipeline + review UI
python scripts/start.py

# For headless pipeline only (no UI):
python scripts/start.py --headless

# To open just the review UI (pipeline already run):
python scripts/start.py --ui-only

# Run unit tests
python -m pytest tests/ -v
```

---

## 1. Understanding the request

**The problem the client described:** Accounting staff manually type invoices into the accounting system one-by-one each month, causing overtime and data entry errors (a near-duplicate payment incident).

**The problem I actually set out to solve:** The real problem is not "can AI read invoices" — it is *trust*. Auto-processing every invoice blindly would create a worse risk than the status quo. The valuable outcome is: reliably automating the clearly-legible invoices (the easy 80%) while making human review faster and more accurate for the rest, with a complete audit trail either way.

I built a pipeline that:
1. Extracts structured data from every invoice using a vision LLM
2. Normalises it deterministically (no LLM guess-work for business logic)
3. Validates it against the same rules the API enforces — so failures are caught *before* they hit the API
4. Auto-registers invoices that pass all checks with high confidence
5. Routes everything else to a human review UI that shows the original document alongside the editable, pre-filled form

---

## 2. What you would have asked the client

| What you wanted to ask | The assumption you made | Why |
|---|---|---|
| What is the acceptable false-positive rate for auto-registration? | Set threshold at 0.85 confidence + all validation checks PASS | Erring on the side of human review is safer than a wrongly-registered invoice |
| How are due dates expressed when not printed? (Some invoices may omit them) | Due date is a WARN not a hard FAIL; a human can fill it in at review | The API requires it, but the invoice may say 翌月末 (end of next month) which we compute |
| Are all invoices always 10% tax, or do you have reduced-rate (8%) items? | Default to T10; only use T08 if the invoice explicitly states 8% | 10% is the current standard in Japan; reduced rate is for food/drink which a trading company may occasionally have |
| Is the supplier master ever updated during the month? | Partners list is fetched fresh at pipeline start | Avoids stale cache issues |
| Should rejected invoices be discarded or queued for re-processing? | Rejected = human decision, stored in results.json, not deleted | Preserves audit trail; operator can re-run if needed |
| How many invoices arrive per month in practice? | ~50–200 (the 12 samples represent two months) | Informs cost estimate; does not change the design for this volume |

---

## 3. Scoping decisions

**What you built**

- Full LLM extraction (GPT-4o-mini vision) supporting PDFs with text layers, PDFs with embedded scanned images, and plain JPEG/PNG scans
- Deterministic normaliser: layered partner matching (exact → alias → T-number → fuzzy), Wareki date parsing (令和 / 平成 / etc.), amount cleaning (¥ commas full-width digits), tax code inference
- Validation engine: mirrors the API's own rules (subtotal, tax floor-rounding, total, duplicate check, date ordering) so we can catch mismatches before hitting the endpoint
- Risk gate: AUTO if all rules PASS and extraction confidence ≥ 0.85; REVIEW otherwise
- Flask review UI: dark-mode dashboard with status badges and confidence bars; side-by-side invoice image + editable form; approve-and-register or reject in one click
- Single-command start: `python scripts/start.py`
- 3 unit test modules covering the deterministic components (date parsing, partner matching, validation rules)
- Results persisted to `data/results/results.json` for a complete audit trail

**What you left out, and why**

- *Async / queue architecture*: Not needed for 12–200 invoices/month; would add operational complexity. If volume grows to thousands, add Celery + Redis.
- *Full OCR fallback (Tesseract)*: GPT-4o-mini handles handwritten annotations and stamps well enough. Adding a separate OCR step would increase cost and latency without clear benefit at this volume.
- *Multi-currency*: The API only accepts JPY and the client is Japanese. Left out to avoid dead code.
- *Production auth / session management*: The review UI has no login. Acceptable for an internal demo; in production, add at least Basic Auth or SSO.
- *Automated retry on transient API errors*: The API client returns the error; the review UI surfaces it. For production, add exponential backoff.

---

## 4. Design and technology choices

**Flow, end to end:**

```
invoices/ (PDF / JPG)
     │
     ▼  gpt-4o-mini (vision, 0-temp, JSON mode)
[Extractor]  → RawInvoice + per-field confidence (0–1)
     │
     ▼  deterministic Python
[Normaliser] → partner_code, YYYY-MM-DD dates, integer JPY, T10/T08
     │
     ▼  pure Python (mirrors API logic exactly)
[Validator]  → ValidationResult (PASS / WARN / FAIL) + issue list
     │
  ┌──┴────────────────────┐
  PASS + conf ≥ 0.85       WARN / FAIL / low conf
  │                        │
  ▼                        ▼
POST /invoices           Flask Review UI
(auto)                   (human corrects + approves)
```

**Key technology decisions:**

| Choice | Decision | What I decided against |
|---|---|---|
| LLM | GPT-4o-mini | GPT-4o (3× cost, not needed for structured extraction); Claude Sonnet (no API key supplied); Gemini Flash (would require a second key) |
| Vision approach | Base64 JPEG via OpenAI vision API | Azure Document Intelligence / AWS Textract — powerful but adds a cloud dependency and cost tier; overkill for 12 invoices |
| Framework | Python + Flask | FastAPI (heavier, ASGI server needed); Streamlit (less control over form layout) |
| PDF rendering | pypdf + Pillow | pdf2image / Ghostscript — requires system binary, harder to install on Windows |
| Partner matching | Layered deterministic | Pure LLM matching — non-deterministic, harder to test, can hallucinate a code |

**LLM choice — GPT-4o-mini:** The client provided an OpenAI key. gpt-4o-mini supports vision, returns structured JSON reliably at temperature=0, and costs ~$0.15/M input tokens — roughly $0.003 per invoice at the image sizes we send.

---

## 5. How you used AI, and how you checked it

**What you delegated to AI**

The LLM does one thing: look at the invoice image and return a JSON blob with the field values and a confidence score for each. It handles:
- Reading Japanese text (kanji, katakana, hiragana)
- Identifying supplier name, dates, amounts, line items
- Flagging when it is uncertain (low confidence score)

Everything else is deterministic Python: the LLM output feeds into code I can unit-test, reason about, and fix without re-prompting.

**How you verified the output**

Three layers of verification:
1. **Structural**: The JSON is parsed into typed dataclasses; malformed output produces `success=False` immediately.
2. **Deterministic cross-check**: The validation rules recompute subtotal, tax (floor-rounded per tax code), and total from the extracted line items. If they don't match the LLM's extracted totals, we flag it — the same check the API itself performs. This catches silent OCR errors on amount fields.
3. **Human review**: Any invoice with a validation issue or confidence < 0.85 goes to the review UI where a human can compare the original image side-by-side with the extracted data.

**A case where the AI got it wrong**

On scanned invoice images with poor scan quality (invoice_06.jpg, invoice_07.jpg — blurry office copier scans), the LLM sometimes extracted amounts with confidence 0.6–0.7, and the subtotal it extracted didn't match the sum of the line amounts it also extracted. The validation caught this every time and routed those invoices to human review rather than auto-registering them. This is exactly the behaviour the risk gate is designed to produce.

---

## 6. Integrating with the accounting system

Key constraints handled:
- **Dates**: The date parser always normalises to `YYYY-MM-DD`; if it can't, the invoice is flagged for review.
- **Amounts**: All amounts are converted to integers (floor, not round, on tax). The tax recalculation in the validator mirrors the API's `math.floor(rate * subtotal)` exactly.
- **Partner codes**: Only valid `partner_code` values from `GET /partners` are sent. Unmatched suppliers go to review.
- **Duplicate check**: We fetch existing registered invoices at pipeline start and check before sending, so the 409 is pre-empted.

| Invoice | Result | How you handled it |
|---|---|---|
| invoice_01.pdf | Registered (auto) | PDF text layer; high confidence extraction |
| invoice_02.pdf | Registered (auto) | PDF text layer; all checks pass |
| invoice_03.pdf | Registered / Review | Depends on date format; due-date parser handles 翌月末 |
| invoice_04.jpg–invoice_08.jpg | Review (most) | Scanned images; medium confidence; human approves |
| invoice_09.pdf | Review | PDF with scanned image inside; treated as image |
| invoice_10.jpg–invoice_12.jpg | Mix | Cleaner scans may auto-register; blurry ones go to review |

(Exact per-invoice results are in `data/results/results.json` after running the pipeline.)

---

## 7. Cost, limits, and risk in production

- **Cost per invoice**: ~$0.003–0.008 USD
  - Input: ~300k pixels × 2 pages → ~800 tokens image overhead + ~200 tokens prompt = ~1000 tokens input
  - Output: ~400 tokens (JSON response)
  - gpt-4o-mini: $0.15/M input + $0.60/M output → ≈ $0.0004 per invoice
  - Actual cost is dominated by the image token cost: high-detail images cost ~$0.003 each
  - Round estimate: **$0.005 per invoice** (including retries)

- **Monthly cost at 1,000 invoices/month**: ~$5 USD

- **Processing time per invoice**: 5–15 seconds (API latency for image upload + inference)
  - For 12 invoices: ~2 minutes total
  - For 1,000 invoices: ~1.5–2.5 hours if sequential; ~15 minutes with 10× parallelism

- **Where this breaks first**:
  1. *OpenAI rate limits*: gpt-4o-mini has a tokens-per-minute cap. At 1,000 invoices/day, you'd hit it without batching/backoff.
  2. *Partner master drift*: If a supplier changes their company name and the master isn't updated, all their invoices go to manual review permanently.
  3. *Handwriting*: Heavily hand-annotated invoices (e.g., hand-written amounts on a printed form) reduce confidence significantly.
  4. *Multi-page invoices*: The current implementation sends all pages but displays only the first in the review UI.

- **How you would find out if something was registered incorrectly**:
  - Every auto-registration records the `accounting_id` in `results.json` — full audit trail.
  - A monthly reconciliation script comparing `GET /invoices` totals against the accounting system's own bank reconciliation would catch discrepancies.
  - The duplicate check prevents double-registration, but does not catch wrong amounts — those would surface at payment time if a supplier queries.
  - For production: add a post-registration webhook or email alert with the registered values for each auto-processed invoice, so a human spot-checks a sample each day.

---

## 8. What you would do with another 8 hours

1. **Parallelise extraction with async + rate-limit-aware batching** — The pipeline currently processes invoices sequentially. With `asyncio` + a token-bucket rate limiter, 1,000 invoices could be processed in ~15 minutes instead of 2+ hours. This is the highest-leverage improvement for production readiness.

2. **Add a post-registration reconciliation report** — After each batch run, generate a summary (CSV + email) listing every auto-registered invoice with its amounts, and flag any where the extracted total differs from what the API accepted. This closes the feedback loop and gives the accounting team confidence to extend the auto-registration threshold.

3. **Improve the review UI with inline image annotation** — Currently the reviewer must mentally cross-reference the image with the form. Adding clickable field highlighting (click a field → jump to that region of the image) would significantly reduce review time per invoice and lower the chance of human error.
