"""Future screenshot-based extraction backend contract.

The planned pipeline is screenshot/frame capture, card-grid detection,
master-image fingerprint matching, then numeric OCR for visible progression.
Production recognition is intentionally not part of this initial version.
"""

from __future__ import annotations

from pathlib import Path

from pjsk_scanner.errors import ScannerError
from pjsk_scanner.models import NormalizedAccount


class VisionBackend:
    """Placeholder that will eventually return the shared domain model."""

    def extract(self, screenshots: list[Path]) -> NormalizedAccount:
        del screenshots
        raise ScannerError("Vision extraction is not implemented yet")
