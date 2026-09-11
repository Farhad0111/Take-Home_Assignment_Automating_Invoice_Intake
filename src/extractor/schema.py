"""
Data classes representing the raw LLM extraction output.

Every field that can be unreliable carries a confidence score (0.0 – 1.0).
The pipeline uses these scores to decide whether to auto-register or route
the invoice to human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RawLineItem:
    """A single line item as returned by the LLM."""

    description: str
    quantity: Optional[int]
    unit: str
    unit_price: Optional[int]
    amount: int
    tax_rate_hint: Optional[float]  # 0.10 or 0.08 as extracted from invoice
    tax_code: str = "T10"           # normalised later


@dataclass
class RawInvoice:
    """Raw structured data extracted from one invoice file."""

    # Identification
    supplier_name: str
    registration_no: Optional[str]   # T-number printed on invoice
    invoice_number: str

    # Dates (as extracted strings, before normalisation)
    issue_date_raw: str
    due_date_raw: Optional[str]

    # Amounts (as extracted — may still be strings with ¥ / commas)
    subtotal_raw: str
    tax_amount_raw: str
    total_amount_raw: str

    # Line items
    lines: List[RawLineItem]

    # Per-field confidence (0.0 – 1.0)
    confidence: dict = field(default_factory=dict)

    # Source file
    source_file: str = ""


@dataclass
class ExtractionResult:
    """Output of the LLM extraction step for one invoice file."""

    source_file: str
    raw: Optional[RawInvoice]
    success: bool
    error: Optional[str] = None

    @property
    def overall_confidence(self) -> float:
        if not self.raw or not self.raw.confidence:
            return 0.0
        values = list(self.raw.confidence.values())
        return sum(values) / len(values)
