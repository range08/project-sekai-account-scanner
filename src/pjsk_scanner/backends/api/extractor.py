"""Read-only live KR extraction through the pinned upstream client."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.backends.api.client import (
    install_read_only_request_guard,
    load_upstream_modules,
    quiet_upstream_logger,
    validate_read_only_client,
)
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.protocol import ApiProtocolConfig
from pjsk_scanner.errors import ApiBackendError, ScannerError
from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import NormalizedAccount
from pjsk_scanner.normalize.account import normalize_suite_payload


class ApiExtractor:
    """Fetch own KR account data without tutorial or login-bonus mutations."""

    def __init__(
        self,
        master: MasterDataRepository,
        credentials: ApiCredentials,
    ) -> None:
        self.master = master
        self.credentials = credentials

    def extract(self) -> NormalizedAccount:
        # Crypto settings are required by the upstream transport. Validate them
        # before importing or invoking anything that can make a network request.
        ApiProtocolConfig.from_environment()
        client: Any | None = None
        suite_payload: object | None = None
        account_info: dict[str, Any] | None = None
        auth_data: object | None = None
        upstream_credential: object | None = None
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
            converted_account_info = accounts_module.credential_to_account_info(
                upstream_credential
            )
            if not isinstance(converted_account_info, dict):
                raise ApiBackendError(
                    "Pinned sekai-client returned invalid KR account information"
                )
            account_info = converted_account_info
            client = api_client_type(region="kr", logger=quiet_upstream_logger())
            validate_read_only_client(client)
            client.account_info = account_info
            install_read_only_request_guard(client)

            # The pinned login() method also completes tutorials and refreshes
            # login bonuses. Use only its auth/session setup and suite read.
            client._authenticating = True
            auth_data = client._authenticate()
            if not isinstance(auth_data, dict):
                raise ApiBackendError(
                    "Pinned sekai-client returned invalid KR authentication data"
                )
            client._apply_auth_headers_and_version_info(auth_data)
            pending_user_id = client._pending_game_user_id
            if not isinstance(pending_user_id, int) or isinstance(
                pending_user_id, bool
            ):
                raise ApiBackendError(
                    "Pinned sekai-client did not retain the authenticated KR user ID"
                )

            # The canonical user ID and session headers are sufficient for this
            # GET. Clearing account credentials also prevents automatic
            # reauthentication in upstream recovery code if that code changes.
            client.account_info = {}
            account_info.clear()
            suite_payload = client.fetch_suite_user()
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
                client.version_info = {}
                headers = getattr(client, "headers", None)
                if isinstance(headers, dict):
                    headers.clear()
                if hasattr(client, "_pending_game_user_id"):
                    client._pending_game_user_id = None
                if hasattr(client, "_authenticating"):
                    client._authenticating = False
            if account_info is not None:
                account_info.clear()
            suite_payload = None
            auth_data = None
            upstream_credential = None
