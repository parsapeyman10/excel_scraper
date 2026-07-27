"""Industrial BOM Integrity & Placement Validator."""

from .config import AppSettings, ValidationProfile
from .core.engine import BomValidationEngine, validate_file
from .io_excel.reader import clear_caches
from .models import (
    BomLine,
    Issue,
    Layer,
    LineResult,
    Placement,
    Severity,
    Status,
    ValidationReport,
    ValidationSummary,
)
from .version import APP_ID, APP_NAME, ORG_NAME, __version__

__all__ = [
    "__version__",
    "APP_ID",
    "APP_NAME",
    "ORG_NAME",
    "AppSettings",
    "ValidationProfile",
    "BomLine",
    "Issue",
    "Layer",
    "LineResult",
    "Placement",
    "Severity",
    "Status",
    "ValidationReport",
    "ValidationSummary",
    "BomValidationEngine",
    "validate_file",
    "clear_caches",
]
