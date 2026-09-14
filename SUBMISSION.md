# Submission

- Name: Farhad
- Submission date (YYYY-MM-DD): 2026-09-11
- Hours actually spent: ~8
- Repository / how to run it: See instructions below

## How to Run

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the accounting API (keep this running in a separate terminal)
py accounting_api.py

# 3. Run the invoice pipeline in another terminal
py scripts/start.py

# Review records are saved with status NEEDS_REVIEW in:
# data/results/results.json

# 4. Run unit tests
py -m pytest tests/ -v
```

---

## 1. Understanding the request

**The problem the client described:**

The accounting team currently enters invoices into their accounting system manually, one by one. This takes a lot of time every month and has already led to mistakes, including an incident where a typo almost caused the same invoice to be paid twice.

**The problem I actually set out to solve:**

I understood the request as more than just extracting text from invoices using AI. The main challenge is making sure the extracted information is accurate enough to be used safely in an accounting workflow.

I did not want to build a system that blindly trusts AI and automatically registers every invoice. A wrong invoice number, amount, supplier, or date could create financial problems. Instead, I designed the workflow so that AI handles the initial extraction, while deterministic validation and human review provide the necessary safeguards.

The goal is to automate the straightforward cases and reduce the amount of manual work, while sending uncertain or invalid invoices for review rather than forcing them through the system.

The pipeline I built works as follows:

1. Extract structured data from each invoice using a vision LLM.
2. Normalize the extracted values using deterministic Python logic.
3. Validate the data against the accounting API's business rules before making any API requests.
4. Automatically register invoices that pass validation and meet the confidence requirements.
5. Send invoices with extraction problems, validation errors, or low confidence to a review workflow where they can be checked and corrected by a human.

The system is designed to automate invoice processing where possible, while keeping human verification in place for cases that require additional attention.

---

## 2. What I would have asked the client

| What I wanted to ask | The assumption I made | Why |
|---|---|---|
| What is the acceptable false-positive rate for auto-registration? | Set threshold at 0.85 confidence + all validation checks PASS | Erring on the side of human review is safer than a wrongly-registered invoice |
| How are due dates expressed when not printed? (Some invoices may omit them) | Due date is a WARN not a hard FAIL; a human can fill it in at review | The API requires it, but the invoice may say 翌月末 (end of next month) which we compute |
| Are all invoices always 10% tax, or do I have reduced-rate (8%) items? | Default to T10; only use T08 if the invoice explicitly states 8% | 10% is the current standard in Japan; reduced rate is for food/drink which a trading company may occasionally have |
| Is the supplier master ever updated during the month? | Partners list is fetched fresh at pipeline start | Avoids stale cache issues |
| Should rejected invoices be discarded or queued for re-processing? | Rejected = human decision, stored in results.json, not deleted | Preserves audit trail; operator can re-run if needed |
| How many invoices arrive per month in practice? | ~50–200 (the 12 samples represent two months) | Informs cost estimate; does not change the design for this volume |

---

## 3. Scoping decisions

**What I built**

- The extractor accepts PDFs, including PDFs with scanned pages, as well as JPG and PNG files. Each document is converted into images and sent to GPT-4o-mini for structured extraction.
- The extracted values are then cleaned up deterministically. This includes matching the supplier, parsing Japanese dates such as 令和 and 平成, converting amounts to integer JPY values, and selecting the appropriate tax code.
- The validation step checks the invoice using the same rules as the accounting API. It recalculates the subtotal, tax, and total, and also checks dates and possible duplicates before anything is registered.
- The risk gate only allows automatic registration when every validation rule passes and the extraction confidence is at least 0.85. All other invoices are marked for review.
- The pipeline processes the 12 documents sequentially. I kept this deliberate because the OpenAI API should not be overloaded with 12 simultaneous requests, and sequential processing makes failures and duplicate checks easier to handle consistently.
- If an extraction request fails or returns unusable JSON, the same document is attempted up to three times with a short increasing delay between attempts. If all attempts fail, the document is recorded as `EXTRACTION_FAILED` instead of stopping the whole batch.
- The pipeline can be started with `python scripts/start.py`, and the results are saved to `data/results/results.json` so there is an audit record for every document.
- I also added unit tests for the date parser, partner matching, and validation rules.

**What I left out, and why**

There are a few things I intentionally did not include in this version. I did not add parallel or queue-based processing because the current volume is small and sending all 12 documents to the OpenAI API at once could run into rate limits or make failures harder to manage. If the volume grows significantly, I would add controlled batching with rate limiting rather than simply starting all requests together.

I also left out a separate OCR fallback such as Tesseract. GPT-4o-mini can process the sample scans, and adding another OCR service would increase setup, cost, and processing time. For a production system, I would reconsider this for consistently poor-quality scans.

Finally, I did not add multi-currency support because the accounting API only accepts JPY. Adding it now would make the code more complicated without supporting the current use case.

---

## 4. Design and technology choices

**Flow, end to end:**

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
----------------------------------------------------xxxxxx---------------------------------------------------------------------------
## 5. How I used AI, and how I checked it

**What I delegated to AI**

The LLM does one thing: look at the invoice image and return a JSON blob with the field values and a confidence score for each. It handles:
- Reading Japanese text (kanji, katakana, hiragana)
- Identifying supplier name, dates, amounts, line items
- Flagging when it is uncertain (low confidence score)

Everything else is deterministic Python: the LLM output feeds into code I can unit-test, reason about, and fix without re-prompting.

**How I verified the output**

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

| Invoice | Result | How I handled it |
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
  1. *OpenAI rate limits*: gpt-4o-mini has a tokens-per-minute cap. At 1,000 invoices/day, I'd hit it without batching/backoff.
  2. *Partner master drift*: If a supplier changes their company name and the master isn't updated, all their invoices go to manual review permanently.
  3. *Handwriting*: Heavily hand-annotated invoices (e.g., hand-written amounts on a printed form) reduce confidence significantly.
  4. *Multi-page invoices*: The current implementation sends all pages but displays only the first in the review UI.

- **How I would find out if something was registered incorrectly**:
  - Every auto-registration records the `accounting_id` in `results.json` — full audit trail.
  - A monthly reconciliation script comparing `GET /invoices` totals against the accounting system's own bank reconciliation would catch discrepancies.
  - The duplicate check prevents double-registration, but does not catch wrong amounts — those would surface at payment time if a supplier queries.
  - For production: add a post-registration webhook or email alert with the registered values for each auto-processed invoice, so a human spot-checks a sample each day.

---

## 8. What I would do with another 8 hours

1. **Parallelise extraction with async + rate-limit-aware batching** — The pipeline currently processes invoices sequentially. With `asyncio` + a token-bucket rate limiter, 1,000 invoices could be processed in ~15 minutes instead of 2+ hours. This is the highest-leverage improvement for production readiness.

2. **Add a post-registration reconciliation report** — After each batch run, generate a summary (CSV + email) listing every auto-registered invoice with its amounts, and flag any where the extracted total differs from what the API accepted. This closes the feedback loop and gives the accounting team confidence to extend the auto-registration threshold.

3. **Improve the review UI with inline image annotation** — Currently the reviewer must mentally cross-reference the image with the form. Adding clickable field highlighting (click a field → jump to that region of the image) would significantly reduce review time per invoice and lower the chance of human error.
