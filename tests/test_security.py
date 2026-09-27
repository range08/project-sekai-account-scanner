from __future__ import annotations

import logging

import pytest

from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.utils import RedactionFilter, redact_mapping, redact_text


def test_redacts_sensitive_mapping_values() -> None:
    value = {
        "accessToken": "fake-access-token",
        "nested": {"device_id": "fake-device-id", "rank": 10},
    }

    redacted = redact_mapping(value)
    assert redacted == {
        "accessToken": "[REDACTED]",
        "nested": {"device_id": "[REDACTED]", "rank": 10},
    }
    assert "fake-access-token" not in repr(redacted)


def test_redacts_key_value_text() -> None:
    redacted = redact_text(
        "accessToken=fake-access-token Authorization: Bearer fake-header-token rank=10"
    )

    assert "fake-access-token" not in redacted
    assert "fake-header-token" not in redacted
    assert "rank=10" in redacted


def test_log_filter_redacts_formatted_record() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        "test.py",
        1,
        "accessToken=%s",
        ("fake-access-token",),
        None,
    )

    assert RedactionFilter().filter(record)
    assert record.getMessage() == "accessToken=[REDACTED]"


def test_credentials_hide_values_from_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "SEKAI_KR_SDK_OPEN_ID": "fake-open-id",
        "SEKAI_KR_ACCESS_TOKEN": "fake-access-token",
        "SEKAI_KR_DEVICE_ID": "fake-device-id",
        "SEKAI_KR_INSTALL_ID": "fake-install-id",
        "SEKAI_KR_USER_AGENT": "fake-agent",
        "SEKAI_KR_DEVICE_MODEL": "fake-model",
        "SEKAI_KR_OS_VERSION": "fake-os",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    credentials = ApiCredentials.from_environment()

    assert "fake-access-token" not in repr(credentials)
    assert "fake-open-id" not in repr(credentials)
