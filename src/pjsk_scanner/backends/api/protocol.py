"""Preflight validation for upstream encryption and version configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pjsk_scanner.errors import ApiBackendError


@dataclass(frozen=True, repr=False)
class ApiProtocolConfig:
    """Validated protocol settings, kept separate from account credentials."""

    aes_key: str = field(repr=False)
    aes_iv: str = field(repr=False)
    app_version: str | None = None
    app_hash: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return (
            "ApiProtocolConfig(aes_key=[REDACTED], aes_iv=[REDACTED], "
            f"app_version={self.app_version!r}, app_hash=[REDACTED])"
        )

    @classmethod
    def from_environment(cls) -> ApiProtocolConfig:
        """Validate AES configuration before the API client can make requests."""
        aes_key = os.environ.get("AES_KEY", "")
        aes_iv = os.environ.get("AES_IV", "")
        missing = [
            name
            for name, value in (("AES_KEY", aes_key), ("AES_IV", aes_iv))
            if not value
        ]
        if missing:
            raise ApiBackendError(
                "Missing required live protocol configuration: " + ", ".join(missing)
            )
        if not _has_valid_material_length(aes_key, (16, 24, 32)):
            raise ApiBackendError(
                "AES_KEY must encode 16, 24, or 32 bytes as hex or UTF-8; value omitted"
            )
        if not _has_valid_material_length(aes_iv, (16,)):
            raise ApiBackendError(
                "AES_IV must encode 16 bytes as hex or UTF-8; value omitted"
            )
        app_version = _optional_override("APP_VER")
        app_hash = _optional_override("APP_HASH")
        return cls(aes_key, aes_iv, app_version, app_hash)


def _has_valid_material_length(value: str, lengths: tuple[int, ...]) -> bool:
    """Match the pinned client's hex-first, then UTF-8 AES material parsing."""
    try:
        material = bytes.fromhex(value)
    except ValueError:
        material = b""
    if len(material) not in lengths:
        material = value.encode("utf-8")
    return len(material) in lengths


def _optional_override(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    if not value.strip():
        raise ApiBackendError(f"{name} must not be empty when configured")
    return value
