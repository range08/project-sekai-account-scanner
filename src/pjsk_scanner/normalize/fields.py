"""Shared validation helpers for suite payload boundaries."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.errors import SuitePayloadError


def rows(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise SuitePayloadError(f"Suite field {field} must be an array")
    if not all(isinstance(row, dict) for row in value):
        raise SuitePayloadError(f"Suite field {field} must contain objects")
    return value


def object_field(payload: dict[str, Any], field: str) -> dict[str, Any] | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SuitePayloadError(f"Suite field {field} must be an object")
    return value


def int_field(
    row: dict[str, Any], field: str, context: str, *, required: bool = False
) -> int | None:
    value = row.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise SuitePayloadError(f"{context}.{field} must be an integer")
    return value


def str_field(
    row: dict[str, Any], field: str, context: str, *, required: bool = False
) -> str | None:
    value = row.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise SuitePayloadError(f"{context}.{field} must be a string")
    return value


def bool_field(row: dict[str, Any], field: str, context: str) -> bool | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SuitePayloadError(f"{context}.{field} must be a boolean")
    return value
