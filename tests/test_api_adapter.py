from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pjsk_scanner.backends.api import extractor as api_extractor
from pjsk_scanner.backends.api.client import (
    install_read_only_request_guard,
    validate_read_only_client,
)
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.extractor import ApiExtractor
from pjsk_scanner.errors import ApiBackendError


def test_api_adapter_authenticates_then_reads_suite_without_login_mutations(
    master: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AES_KEY", "0123456789abcdef")
    monkeypatch.setenv("AES_IV", "abcdefghijklmnop")
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "suite-user.json").read_text(
            encoding="utf-8"
        )
    )
    clients: list[Any] = []
    account_info_values: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, region: str, logger: object) -> None:
            self.region = region
            self.logger = logger
            self.account_info: dict[str, Any] = {}
            self.user_info: dict[str, Any] = {}
            self.version_info: dict[str, Any] = {}
            self.headers = {"x-session-token": "synthetic-bootstrap-token"}
            self._pending_game_user_id: int | None = None
            self._authenticating = False
            self.calls: list[tuple[str, str, bool]] = []
            clients.append(self)

        def call_pjsk_api(
            self,
            endpoint: str,
            method: str = "get",
            body: str | dict[str, Any] = "",
            retry_policy: object | None = None,
            *,
            bypass_error_recovery: bool = False,
        ) -> object:
            del body, retry_policy
            self.calls.append((endpoint, method, bypass_error_recovery))
            return payload if endpoint.startswith("/suite/user/") else {}

        def _authenticate(self) -> dict[str, Any]:
            assert self._authenticating is True
            self.call_pjsk_api(
                "/user/auth", "post", {"accessToken": "synthetic-access-token"}
            )
            self.call_pjsk_api("/user/123456789/login", "post")
            self._pending_game_user_id = 123456789
            return {
                "sessionToken": "synthetic-session-token",
                "appVersion": "3.6.0",
                "dataVersion": "3.6.1.0",
                "assetVersion": "3.6.1.0",
                "multiPlayVersion": "1.0.0",
                "cdnVersion": "1",
                "appVersionStatus": "available",
            }

        def _apply_auth_headers_and_version_info(
            self, auth_data: dict[str, Any]
        ) -> None:
            self.headers["x-session-token"] = auth_data["sessionToken"]
            self.version_info = {"appVersion": auth_data["appVersion"]}

        def fetch_suite_user(self) -> dict[str, Any]:
            assert self.account_info == {}
            assert self._pending_game_user_id == 123456789
            return self.call_pjsk_api(
                f"/suite/user/{self._pending_game_user_id}", "get"
            )  # type: ignore[return-value]

        def login(self) -> None:
            pytest.fail("APIClient.login() must never be used by the scanner")

        def _complete_tutorial_if_needed(self, *_args: object) -> None:
            pytest.fail("tutorial progression must never be changed by the scanner")

        def _post_login_refresh(self, *_args: object) -> None:
            pytest.fail("post-login progression refresh must never run")

    class FakeCredential:
        def __init__(self, **values: object) -> None:
            self.values = values

    def account_info_for(credential: FakeCredential) -> dict[str, Any]:
        info = {
            "userId": "123456789",
            "loginInfo": {"accessToken": credential.values["access_token"]},
        }
        account_info_values.append(info)
        return info

    fake_accounts = SimpleNamespace(
        AccountRegion=SimpleNamespace(KR="kr"),
        TwKrCredential=FakeCredential,
        credential_to_account_info=account_info_for,
    )
    monkeypatch.setattr(
        api_extractor,
        "load_upstream_modules",
        lambda: (FakeClient, fake_accounts),
    )

    credentials = ApiCredentials(
        sdk_open_id="synthetic-open-id",
        access_token="synthetic-access-token",
        device_id="synthetic-device-id",
        install_id="synthetic-install-id",
        user_agent="synthetic-user-agent",
        device_model="synthetic-device-model",
        os_version="synthetic-os-version",
    )
    account = ApiExtractor(master, credentials).extract()

    assert account.cards[0].card_id == 1001
    assert account.profile is not None and account.profile.rank == 42
    assert clients[0].region == "kr"
    assert clients[0].calls == [
        ("/user/auth", "post", True),
        ("/user/123456789/login", "post", True),
        ("/suite/user/123456789", "get", True),
    ]
    assert account_info_values == [{}]
    assert clients[0].account_info == {}
    assert clients[0].user_info == {}
    assert clients[0].version_info == {}
    assert clients[0].headers == {}
    assert clients[0]._pending_game_user_id is None
    assert clients[0]._authenticating is False


def test_request_guard_rejects_progression_mutation() -> None:
    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def call_pjsk_api(
            self, endpoint: str, method: str = "get", *_args: Any
        ) -> None:
            self.calls.append((endpoint, method))

    client = FakeTransport()
    install_read_only_request_guard(client)

    with pytest.raises(ApiBackendError, match="outside the authentication"):
        client.call_pjsk_api(
            "/user/123456789/home/refresh",
            "put",
            {"refreshableTypes": ["login_bonus"]},
        )
    with pytest.raises(ApiBackendError, match="outside the authentication"):
        client.call_pjsk_api(
            "/user/123456789/tutorial", "patch", {"tutorialStatus": "end"}
        )
    assert client.calls == []


def test_incompatible_upstream_fails_closed_without_login_fallback() -> None:
    with pytest.raises(ApiBackendError, match="_authenticate"):
        validate_read_only_client(object())
