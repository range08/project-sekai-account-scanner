"""Explicit environment-supplied KR credentials for the optional API backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pjsk_scanner.errors import ApiBackendError


@dataclass(frozen=True, repr=False)
class ApiCredentials:
    sdk_open_id: str = field(repr=False)
    access_token: str = field(repr=False)
    device_id: str = field(repr=False)
    install_id: str = field(repr=False)
    user_agent: str = field(repr=False)
    device_model: str = field(repr=False)
    os_version: str = field(repr=False)

    def __repr__(self) -> str:
        return "ApiCredentials(region='kr', values=[REDACTED])"

    @classmethod
    def from_environment(cls) -> ApiCredentials:
        """Read the credential fields required by the current KR client."""
        env_fields = {
            "sdk_open_id": "SEKAI_KR_SDK_OPEN_ID",
            "access_token": "SEKAI_KR_ACCESS_TOKEN",
            "device_id": "SEKAI_KR_DEVICE_ID",
            "install_id": "SEKAI_KR_INSTALL_ID",
            "user_agent": "SEKAI_KR_USER_AGENT",
            "device_model": "SEKAI_KR_DEVICE_MODEL",
            "os_version": "SEKAI_KR_OS_VERSION",
        }
        values = {key: os.environ.get(name) for key, name in env_fields.items()}
        missing = [env_fields[key] for key, value in values.items() if not value]
        if missing:
            raise ApiBackendError(
                "Missing required KR credential environment variables: "
                + ", ".join(missing)
            )
        return cls(**{key: value for key, value in values.items() if value is not None})
