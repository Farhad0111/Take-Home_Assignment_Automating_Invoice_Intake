"""
Risk gate: decides whether an invoice should be auto-registered or
sent to the human review queue.

Decision matrix:
  status=PASS  AND  confidence >= HIGH_CONF  →  AUTO
  status=PASS  AND  confidence <  HIGH_CONF  →  REVIEW
  status=WARN  (any)                         →  REVIEW
  status=FAIL  (any)                         →  REVIEW  (cannot register)
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .result import ValidationResult

HIGH_CONF_THRESHOLD = 0.85


class Disposition(str, Enum):
    AUTO = "AUTO"      # Safe to register automatically
    REVIEW = "REVIEW"  # Route to human review queue


def gate(validation: "ValidationResult", extraction_confidence: float) -> Disposition:
    """
    Determine processing disposition.

    Args:
        validation: Result of running the validation rules.
        extraction_confidence: Overall confidence from the LLM extraction step.
    Returns:
        Disposition.AUTO or Disposition.REVIEW
    """
    from .result import ValidationStatus  # local to avoid circular

    if validation.status == ValidationStatus.FAIL:
        return Disposition.REVIEW

    if validation.status == ValidationStatus.WARN:
        return Disposition.REVIEW

    # Status is PASS — check confidence
    if extraction_confidence >= HIGH_CONF_THRESHOLD:
        return Disposition.AUTO

    return Disposition.REVIEW
