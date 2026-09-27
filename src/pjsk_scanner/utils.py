"""Small privacy helpers shared by CLI and optional integrations."""

from __future__ import annotations

import logging
import re
from typing import Any

_SECRET_KEY_PARTS = (
    "access_token",
    "accesstoken",
    "session_token",
    "sessiontoken",
    "token",
    "token_cache",
    "devicetoken",
    "sp_device_id",
    "sdk_open_id",
    "sdkopenid",
    "credential",
    "signature",
    "authorization",
    "device_id",
    "deviceid",
    "device_model",
    "devicemodel",
    "install_id",
    "installid",
    "user_agent",
    "useragent",
    "os_version",
    "osversion",
    "aes_key",
    "aeskey",
    "aes_iv",
    "aesiv",
    "app_hash",
    "apphash",
    "user_id",
    "userid",
    "x_if",
    "xif",
    "x_kc",
    "xkc",
    "x-session-token",
    "x-tt-token",
    "cookie",
    "set_cookie",
)
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(access[_-]?token|session[_-]?token|token(?:[_-]?cache)?|"
    r"device[_-]?token|sp[_-]?device[_-]?id|x[_-]?tt[_-]?token|"
    r"sdk[_-]?open[_-]?id|"
    r"credential|signature|authorization|device[_-]?id|install[_-]?id|"
    r"user[_-]?id|device[_-]?model|user[_-]?agent|os[_-]?version|"
    r"aes[_-]?key|aes[_-]?iv|app[_-]?hash|x[_-]?(?:if|kc))"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;&]+"
)
_COOKIE_PATTERN = re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\r\n]*")


def redact_mapping(value: Any) -> Any:
    """Return a copy of nested data with credential-like fields masked."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).replace("-", "_").casefold()
            if any(
                part.replace("-", "_") in normalized_key for part in _SECRET_KEY_PARTS
            ):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_mapping(item)
        return redacted
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_mapping(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    """Mask common credential key/value pairs in text before logging."""
    value = _AUTHORIZATION_PATTERN.sub(r"\1[REDACTED]", value)
    value = _COOKIE_PATTERN.sub(r"\1[REDACTED]", value)
    return _KEY_VALUE_PATTERN.sub(r"\1\2[REDACTED]", value)


class RedactionFilter(logging.Filter):
    """Redact credential key/value pairs from formatted log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return True
