"""Live KR extraction through the upstream client's public login flow."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.backends.api.client import (
    load_upstream_modules,
    quiet_upstream_logger,
)
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.errors import ApiBackendError, ScannerError
from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import NormalizedAccount
from pjsk_scanner.normalize.account import normalize_suite_payload


class ApiExtractor:
    """Fetch own KR account data via sekai-client, then normalize immediately."""

    def __init__(
        self,
        master: MasterDataRepository,
        credentials: ApiCredentials,
    ) -> None:
        self.master = master
        self.credentials = credentials

    def extract(self) -> NormalizedAccount:
        client: Any | None = None
        suite_payload: object | None = None
        try:
            api_client_type, accounts_module = load_upstream_modules()
            account_region = accounts_module.AccountRegion.KR
            upstream_credential = accounts_module.TwKrCredential(
                region=account_region,
                sdk_open_id=self.credentials.sdk_open_id,
                access_token=self.credentials.access_token,
                device_id=self.credentials.device_id,
                install_id=self.credentials.install_id,
                user_agent=self.credentials.user_agent,
                device_model=self.credentials.device_model,
                os_version=self.credentials.os_version,
            )
            account_info = accounts_module.credential_to_account_info(
                upstream_credential
            )
            client = api_client_type(region="kr", logger=quiet_upstream_logger())
            client.account_info = account_info
            # APIClient.login() authenticates and calls its public
            # fetch_suite_user() method. The current upstream flow does not
            # initialize the JP-only cookie for KR.
            suite_payload = client.login()
            return normalize_suite_payload(suite_payload, self.master, region="kr")
        except ScannerError:
            raise
        except Exception as error:
            # Upstream exceptions may embed requests or auth details. Keep the
            # error type only; never propagate a message containing credentials.
            raise ApiBackendError(
                "Live KR account extraction failed "
                f"({type(error).__name__}); check the credentials and client setup"
            ) from None
        finally:
            if client is not None:
                client.account_info = {}
                client.user_info = {}
                headers = getattr(client, "headers", None)
                if isinstance(headers, dict):
                    headers.clear()
            suite_payload = None
