# Take-Home_Assignment_Automating_Invoice_Intake
[Invoices (PDF / Scans)]
         │
         ▼
┌─────────────────────────────────┐
│  Multi-modal LLM Extractor      │  (Gemini 2.0 Flash / GPT-4o-mini / Claude 3.5 Sonnet)
│  - Structured JSON Output       │  Extracts raw text, dates, line items, supplier info
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Deterministic Normalizer       │
│  - Partner Matcher (T-number,   │  Matches against GET /partners (aliases & tax IDs)
│    exact name, aliases, fuzzy)  │
│  - Date Parser (Wareki / ISO)   │  Converts 令和8年, 2026/01/15, 翌月末 -> YYYY-MM-DD
│  - Tax & Currency Cleaner       │  Assigns T10 / T08, strips commas/yen symbols
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Validation & Reconciliation    │
│  - Subtotal == sum(lines)       │
│  - Tax == floor(subtotal * rate)│  Pre-validates exactly what the API enforces
│  - Partner exists               │  Flags discrepancies before hitting API
│  - Duplicate check              │
└────────┬───────────────┬────────┘
         │ Passed        │ Warnings / Mismatch
         ▼               ▼
┌────────────────────────────────────────────────────────┐
│ Human-in-the-Loop Review Screen (Streamlit or FastAPI) │
│ - Side-by-side view (Image + Extracted Fields)         │
│ - Visual alerts on validation mismatches / low conf    │
│ - 1-Click "Approve & Register" or batch process        │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
             [POST /invoices to API]
