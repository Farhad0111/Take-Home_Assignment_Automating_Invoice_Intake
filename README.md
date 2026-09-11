Folder Structure:
Take-Home_Assignment_Automating_Invoice_Intake/
│
├── README.md
├── SUBMISSION.md
├── .env.example
├── .gitignore
├── requirements.txt
│
├── accounting_api.py              # Provided API — behavior unchanged
│
├── invoices/
│   ├── invoice_01.pdf
│   ├── invoice_02.pdf
│   ├── ...
│   └── invoice_12.jpg
│
├── src/
│   ├── __init__.py
│   │
│   ├── extractor/
│   │   ├── __init__.py
│   │   ├── llm_client.py
│   │   ├── prompts.py
│   │   └── schema.py
│   │
│   ├── normalizer/
│   │   ├── __init__.py
│   │   ├── partner_matcher.py
│   │   ├── date_parser.py
│   │   └── tax_currency.py
│   │
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── rules.py
│   │   ├── result.py
│   │   └── risk_gate.py
│   │
│   ├── accounting_client/
│   │   ├── __init__.py
│   │   └── client.py
│   │
│   ├── review/
│   │   ├── __init__.py
│   │   └── app.py
│   │
│   └── pipeline.py
│
├── data/
│   ├── raw_extractions/
│   ├── normalized/
│   └── results/
│
├── tests/
│   ├── test_date_parser.py
│   ├── test_partner_matcher.py
│   ├── test_validation_rules.py
│   └── fixtures/
│
├── scripts/
│   └── start.py
│
└── demo/
    ├── screenshots/
    └── demo_video.mp4


Architecture
                         ┌──────────────────────┐
                         │  PDF / Scan Invoice  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌────────────────────────────┐
                    │   Multimodal LLM           │
                    │   Document Extraction      │
                    │                            │
                    │ Supplier / Invoice / Dates │
                    │ Lines / Amounts / Tax      │
                    │ Confidence                 │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │ Deterministic Normalizer   │
                    │                            │
                    │ Partner → partner_code     │
                    │ Registration number        │
                    │ Date → YYYY-MM-DD          │
                    │ Tax → T10 / T08            │
                    │ Amount → integer JPY       │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │ Validation & Reconciliation│
                    │                            │
                    │ Partner exists             │
                    │ Date validity              │
                    │ Subtotal = Σ lines         │
                    │ Tax = floor(rate × subtotal)│
                    │ Total = subtotal + tax     │
                    │ Duplicate check             │
                    └─────────────┬──────────────┘
                                  │
                         ┌────────┴────────┐
                         │                 │
                         ▼                 ▼
                  PASS + HIGH CONF.   WARNING / FAIL
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