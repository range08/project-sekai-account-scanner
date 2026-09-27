from __future__ import annotations

import logging

import pytest

from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.protocol import ApiProtocolConfig
from pjsk_scanner.errors import ApiBackendError
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


def test_redacts_protocol_configuration() -> None:
    redacted = redact_mapping(
        {
            "AES_KEY": "synthetic-aes-key",
            "aesIv": "synthetic-aes-iv",
            "APP_HASH": "synthetic-app-hash",
        }
    )
    assert redacted == {
        "AES_KEY": "[REDACTED]",
        "aesIv": "[REDACTED]",
        "APP_HASH": "[REDACTED]",
    }

    text = redact_text(
        "AES_KEY=synthetic-aes-key AES_IV:synthetic-aes-iv APP_HASH=synthetic-app-hash"
    )
    assert "synthetic-aes-key" not in text
    assert "synthetic-aes-iv" not in text
    assert "synthetic-app-hash" not in text


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


def test_log_filter_redacts_protocol_values() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        "test.py",
        1,
        "AES_KEY=%s AES_IV=%s APP_HASH=%s",
        ("synthetic-aes-key", "synthetic-aes-iv", "synthetic-app-hash"),
        None,
    )

    assert RedactionFilter().filter(record)
    message = record.getMessage()
    assert message == "AES_KEY=[REDACTED] AES_IV=[REDACTED] APP_HASH=[REDACTED]"


def test_redacts_android_sdk_tokens_and_identifiers() -> None:
    secret_values = (
        "fake-device-token",
        "fake-cache-token",
        "fake-sp-device-id",
        "fake-tt-token",
        "fake-cookie",
    )
    message = redact_text(
        "device_token=fake-device-token token_cache=fake-cache-token "
        "sp_device_id=fake-sp-device-id X-Tt-Token=fake-tt-token "
        "Cookie=fake-cookie"
    )

    assert all(secret not in message for secret in secret_values)
    assert message.count("[REDACTED]") == len(secret_values)


def test_redacts_entire_cookie_header() -> None:
    message = redact_text("Cookie=sessionid=fake-session; sessionid_ss=fake-session-ss")

    assert "fake-session" not in message
    assert "fake-session-ss" not in message


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


def test_protocol_preflight_requires_aes_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AES_KEY", raising=False)
    monkeypatch.delenv("AES_IV", raising=False)

    with pytest.raises(ApiBackendError, match="AES_KEY, AES_IV"):
        ApiProtocolConfig.from_environment()


def test_malformed_protocol_error_and_repr_never_expose_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "synthetic-protocol-secret-that-is-too-long"
    monkeypatch.setenv("AES_KEY", secret)
    monkeypatch.setenv("AES_IV", "abcdefghijklmnop")

    with pytest.raises(ApiBackendError) as captured:
        ApiProtocolConfig.from_environment()

    assert secret not in str(captured.value)
    assert secret not in caplog.text


def test_protocol_preflight_rejects_malformed_iv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AES_KEY", "0123456789abcdef")
    monkeypatch.setenv("AES_IV", "too-short")

    with pytest.raises(ApiBackendError, match="AES_IV must encode 16 bytes"):
        ApiProtocolConfig.from_environment()


def test_protocol_config_hides_valid_secret_values_from_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aes_key = "0123456789abcdef"
    aes_iv = "abcdefghijklmnop"
    app_hash = "synthetic-app-hash"
    monkeypatch.setenv("AES_KEY", aes_key)
    monkeypatch.setenv("AES_IV", aes_iv)
    monkeypatch.setenv("APP_VER", "3.6.0")
    monkeypatch.setenv("APP_HASH", app_hash)

    config = ApiProtocolConfig.from_environment()

    assert config.app_version == "3.6.0"
    assert aes_key not in repr(config)
    assert aes_iv not in repr(config)
    assert app_hash not in repr(config)
