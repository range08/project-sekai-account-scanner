from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pjsk_scanner.backends.api import extractor as api_extractor
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.extractor import ApiExtractor


def test_api_adapter_uses_upstream_login_then_normalizes_in_memory(
    master: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "suite-user.json").read_text(
            encoding="utf-8"
        )
    )
    clients: list[FakeClient] = []

    class FakeClient:
        def __init__(self, region: str, logger: object) -> None:
            self.region = region
            self.logger = logger
            self.account_info: dict[str, Any] = {}
            self.user_info: dict[str, Any] = {}
            self.headers = {"x-session-token": "synthetic-session-token"}
            self.payload = payload
            clients.append(self)

        def login(self) -> dict[str, Any]:
            self.user_info = self.payload
            return self.payload

    class FakeCredential:
        def __init__(self, **values: object) -> None:
            self.values = values

    fake_accounts = SimpleNamespace(
        AccountRegion=SimpleNamespace(KR="kr"),
        TwKrCredential=FakeCredential,
        credential_to_account_info=lambda credential: {
            "synthetic": credential.values["sdk_open_id"]
        },
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
    assert clients[0].account_info == {}
    assert clients[0].user_info == {}
    assert clients[0].headers == {}
