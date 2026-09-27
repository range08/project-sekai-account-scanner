"""Errors shown to users by the scanner CLI."""


class ScannerError(Exception):
    """Base error with a safe, user-facing message."""


class SuitePayloadError(ScannerError):
    """The imported suite user payload is malformed or incomplete."""


class MasterDataError(ScannerError):
    """Master data could not be loaded, validated, or downloaded."""


class ApiBackendError(ScannerError):
    """The optional live API backend could not fetch account data."""
