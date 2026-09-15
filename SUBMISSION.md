# Submission

- Name: Md. Farhad Billah
- Submission date (YYYY-MM-DD): 2026-09-15
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

![Invoice intake pipeline](Demo/Pipeline%20Architecture/Pipeline%20Architecture.png)

**Key technology decisions:**

```
      invoices (PDF / JPG)
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

## 5. How I used AI, and how I checked it

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

| Invoice | Result | How I handled it |
|---|---|---|
| invoice_01.pdf | `NEEDS_REVIEW` | Detected as a duplicate invoice, so it was not registered again. |
| invoice_02.pdf | `NEEDS_REVIEW` | The extracted subtotal and tax did not match the recalculated values. |
| invoice_03.pdf | `NEEDS_REVIEW` | The supplier could not be matched to a partner in the accounting master. |
| invoice_04.jpg | `NEEDS_REVIEW` | The supplier could not be matched to a partner in the accounting master. |
| invoice_05.jpg | `NEEDS_REVIEW` | Detected as a duplicate invoice, so it was sent for review. |
| invoice_06.jpg | `NEEDS_REVIEW` | The supplier could not be matched to a partner in the accounting master. |
| invoice_07.jpg | `NEEDS_REVIEW` | The supplier could not be matched to a partner in the accounting master. |
| invoice_08.jpg | `NEEDS_REVIEW` | The supplier could not be matched, and the tax and total also failed validation. |
| invoice_09.pdf | `NEEDS_REVIEW` | The supplier could not be matched and the extracted total did not pass validation. |
| invoice_10.jpg | `NEEDS_REVIEW` | The supplier could not be matched to a partner in the accounting master. |
| invoice_11.jpg | `EXTRACTION_FAILED` | The extraction was retried up to three times but did not produce a usable result. |
| invoice_12.jpg | `NEEDS_REVIEW` | The extracted subtotal and tax did not match the recalculated values. |

These results are taken from `data/results/results.json` from the latest pipeline run. In this run, no invoice was automatically registered because every document either failed a validation check or failed extraction.

---

## 7. Cost, limits, and risk in production

The main cost is the vision API call. For the sample invoices, I estimate roughly $0.003 to $0.008 per document, depending on the number of pages, image detail, and whether a retry is needed. The exact amount will vary with the OpenAI pricing and the size of each document, so I would treat this as a planning estimate rather than a fixed price.

At the current estimate, processing 1,000 invoices would cost approximately $3–$8 for extraction. The pipeline processes documents sequentially, one at a time, with each API request allowed up to three attempts. For the 12 sample invoices, the total processing time is approximately 2 minutes, although slow API responses or retries may increase the runtime. At this rate, processing 1,000 invoices sequentially would take around 1.5–2.5 hours, while 10× parallel processing could reduce this to approximately 15 minutes. The current sequential approach is sufficient for the present volume, while larger volumes would benefit from controlled batching and rate limiting.

The main production risks I see are:

1. **API limits or temporary failures:** A larger batch may hit OpenAI rate limits or experience timeouts. The current code retries extraction failures, but a production version should also use explicit rate limiting, logging, and monitoring.
2. **Changes to the partner master:** If a supplier changes its name or the partner list is not updated, valid invoices may be sent to manual review. Fetching the partner list at the start of each run helps, but it does not replace keeping the master data accurate.
3. **Poor-quality or handwritten invoices:** Blurry scans, stamps, and handwritten changes can reduce extraction confidence or produce incorrect amounts. The validation checks and review step reduce this risk, but they cannot make an unreadable document reliable automatically.
4. **Multi-page review:** The extractor can send all pages to the model, but the review screen currently focuses on the document preview available to the reviewer. A production UI should make every page easy to inspect.

The current safeguards are the confidence threshold, deterministic calculation checks, duplicate detection, retries, and the human review workflow. Every processed invoice is also written to `data/results/results.json`. For production, I would add a reconciliation report comparing registered invoice numbers and totals with the accounting system, plus an alert or daily report so the accounting team can spot-check automatically registered invoices.

---

## 8. What I would do with another 8 hours

With another eight hours, I would focus first on making the pipeline more reliable at a larger volume, then improve the controls around registered invoices and the human review experience.

**1. Add controlled batching and rate limiting (about 4 hours)**

The current pipeline processes invoices sequentially because sending all 12 documents to the OpenAI API at the same time could cause rate-limit or timeout problems. I would add a small worker pool with a rate limiter, rather than unrestricted parallel requests. This would reduce processing time for larger batches while still respecting the API limits. I would also add clearer logging for retries and failed documents.

**2. Add a reconciliation report (about 2 hours)**

After each run, I would generate a CSV or summary report containing the invoices that were automatically registered, their totals, partner codes, and accounting IDs. The report could highlight differences between the values extracted by the pipeline and the values accepted by the accounting API. This would give the accounting team a simple way to review the batch and catch problems early.

**3. Improve the review workflow (about 2 hours)**

The review screen already shows the document and the extracted form, but I would make it more user-friendly for someone processing many invoices. I would keep the invoice preview and form visible side by side, add a clear status and issue summary at the top, and highlight the fields that need attention. The reviewer should be able to edit supplier, date, amount, tax, and invoice number fields directly without leaving the page.

I would also add simple navigation between review items, support all pages of a multi-page invoice, and make important form fields link to the relevant part of the document where possible. Before approval, the UI should show the corrected values and any remaining validation errors so the reviewer can confirm the result. These changes would make it easier to compare the source document with the extracted data and reduce the chance of approving an invoice with an unresolved issue.

These improvements would keep the main design unchanged: use AI for extraction, use deterministic code for validation, and keep a human involved whenever the system is not sufficiently confident.
