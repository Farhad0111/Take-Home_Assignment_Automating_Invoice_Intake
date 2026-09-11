"""
Validation result data classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class ValidationIssue:
    """A single validation finding."""

    severity: str          # "ERROR" or "WARN"
    code: str              # e.g. "SUBTOTAL_MISMATCH"
    message: str
    detail: Optional[str] = None


@dataclass
class ValidationResult:
    """Aggregate result of all validation checks for one invoice."""

    status: ValidationStatus
    issues: List[ValidationIssue] = field(default_factory=list)
    overall_confidence: float = 0.0

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "ERROR" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "WARN" for i in self.issues)

    def add_error(self, code: str, message: str, detail: str = None):
        self.issues.append(ValidationIssue("ERROR", code, message, detail))
        self.status = ValidationStatus.FAIL

    def add_warning(self, code: str, message: str, detail: str = None):
        self.issues.append(ValidationIssue("WARN", code, message, detail))
        if self.status == ValidationStatus.PASS:
            self.status = ValidationStatus.WARN
