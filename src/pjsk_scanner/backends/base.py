"""Common result contract for API and future screenshot backends."""

from __future__ import annotations

from typing import Protocol

from pjsk_scanner.models import NormalizedAccount


class AccountBackend(Protocol):
    """A source that returns the shared normalized account model."""

    def extract(self) -> NormalizedAccount:
        """Fetch or recognize account progression and normalize it."""
