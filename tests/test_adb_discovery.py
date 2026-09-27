from __future__ import annotations

import subprocess
from typing import Any

import pytest

from pjsk_scanner import adb
from pjsk_scanner.backends.api.credential_discovery import (
    derive_unity_user_agent,
    parse_android_preferences,
)
from pjsk_scanner.errors import DeviceDiscoveryError


def test_parse_android_preferences_extracts_only_strings() -> None:
    parsed = parse_android_preferences(
        b'<map><string name="SDK_OPENID">synthetic-open-id</string>'
        b'<string name="SEKAI_CREDENTIAL">synthetic-access-token</string>'
        b'<int name="SEKAI_ACCOUNT_USER_ID" value="42" />'
        b"</map>"
    )

    assert parsed == {
        "SDK_OPENID": "synthetic-open-id",
        "SEKAI_CREDENTIAL": "synthetic-access-token",
    }


def test_credential_discovery_rejects_credential_matching_sdk_open_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDevice:
        def verify_package_and_root(self) -> None:
            return None

        def read_private_file(self, path: str) -> bytes:
            if path.endswith("playerprefs.xml"):
                return (
                    b'<map><string name="SDK_OPENID">same-secret-value</string>'
                    b'<string name="SEKAI_CREDENTIAL">same-secret-value</string>'
                    b'<string name="SEKAI_ACCOUNT_INSTALL_ID">install-id</string></map>'
                )
            return b'<map><string name="sp_device_id">device-id</string></map>'

        def property(self, name: str) -> str:
            return "model" if name == "ro.product.model" else "14"

    monkeypatch.setattr(
        "pjsk_scanner.backends.api.credential_discovery.resolve_adb_executable",
        lambda _adb=None: "adb",
    )
    monkeypatch.setattr(
        "pjsk_scanner.backends.api.credential_discovery.select_device",
        lambda *_args, **_kwargs: FakeDevice(),
    )
    monkeypatch.setattr(
        "pjsk_scanner.backends.api.credential_discovery._user_agent_from_installed_client",
        lambda _device: pytest.fail("must reject before inspecting APK libraries"),
    )

    from pjsk_scanner.backends.api.credential_discovery import discover_kr_environment

    with pytest.raises(DeviceDiscoveryError, match="refusing to treat") as error:
        discover_kr_environment()

    assert "same-secret-value" not in str(error.value)


def test_android_preferences_reject_malformed_xml() -> None:
    with pytest.raises(DeviceDiscoveryError, match="malformed"):
        parse_android_preferences(b"<map><string")


def test_user_agent_is_derived_from_installed_unity_versions() -> None:
    libunity = b"UnityPlayer/ (UnityWebRequest/1.0, libcurl/8.10.1\x00"
    il2cpp = b"build Unity 2022.3.62f3 metadata"

    user_agent = derive_unity_user_agent(libunity, il2cpp)

    assert user_agent == (
        "UnityPlayer/2022.3.62f3 (UnityWebRequest/1.0, libcurl/8.10.1)"
    )


def test_user_agent_derivation_rejects_ambiguous_client_versions() -> None:
    with pytest.raises(DeviceDiscoveryError, match="ambiguous"):
        derive_unity_user_agent(
            b"UnityPlayer/ (UnityWebRequest/1.0, libcurl/8.10.1\x00",
            b"2022.3.62f2 2022.3.62f3",
        )


def test_windows_adb_path_is_mapped_for_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adb.os, "name", "posix")

    assert (
        adb._normalize_executable_path(r"C:\LDPlayer\LDPlayer14\adb.exe")
        == "/mnt/c/LDPlayer/LDPlayer14/adb.exe"
    )


def test_explicit_windows_adb_path_is_validated_after_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adb.os, "name", "posix")
    monkeypatch.setattr(adb, "_is_executable", lambda path: path.endswith("adb.exe"))

    assert (
        adb.resolve_adb_executable(r"C:\LDPlayer\adb.exe") == "/mnt/c/LDPlayer/adb.exe"
    )


def test_device_selection_prefers_a_single_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert args[0][1:] == ["devices", "-l"]
        return subprocess.CompletedProcess(
            args[0],
            0,
            "List of devices attached\nemulator-5554 device product:x\n"
            "phone-serial device product:y\n",
            "",
        )

    monkeypatch.setattr(adb.subprocess, "run", fake_run)
    selected = adb.select_device("adb.exe")

    assert selected.serial == "emulator-5554"


def test_package_apk_paths_accept_android_install_directory_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adb.AdbDevice,
        "run",
        lambda _self, *_args, **_kwargs: (
            b"package:/data/app/~~GCJVwHU56RWqldPetAtE0g==/"
            b"com.pjsekai.kr-cgDMy8mfTTlYvLCnZYEVEQ==/base.apk\n"
            b"package:/data/app/~~GCJVwHU56RWqldPetAtE0g==/"
            b"com.pjsekai.kr-cgDMy8mfTTlYvLCnZYEVEQ==/split_config.arm64_v8a.apk\n"
        ),
    )
    device = adb.AdbDevice("adb", "emulator-test")

    assert device.package_apk_paths() == (
        "/data/app/~~GCJVwHU56RWqldPetAtE0g==/"
        "com.pjsekai.kr-cgDMy8mfTTlYvLCnZYEVEQ==/base.apk",
        "/data/app/~~GCJVwHU56RWqldPetAtE0g==/"
        "com.pjsekai.kr-cgDMy8mfTTlYvLCnZYEVEQ==/split_config.arm64_v8a.apk",
    )


def test_remote_apk_reader_accepts_package_manager_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (
        "/data/app/~~GCJVwHU56RWqldPetAtE0g==/"
        "com.pjsekai.kr-cgDMy8mfTTlYvLCnZYEVEQ==/split_config.arm64_v8a.apk"
    )
    device = adb.AdbDevice("adb", "emulator-test")
    monkeypatch.setattr(
        adb.AdbDevice,
        "run",
        lambda _self, *args, **_kwargs: b"synthetic-apk",
    )

    assert device.read_remote_binary(path, max_bytes=100) == b"synthetic-apk"


def test_adb_command_uses_explicit_windows_executable_and_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, b"safe", b"")

    monkeypatch.setattr(adb.subprocess, "run", fake_run)
    device = adb.AdbDevice(r"C:\LDPlayer\adb.exe", "emulator-5554")

    assert device.run("shell", "getprop", "ro.product.model") == b"safe"
    assert calls == [
        [
            r"C:\LDPlayer\adb.exe",
            "-s",
            "emulator-5554",
            "shell",
            "getprop",
            "ro.product.model",
        ]
    ]


def test_private_adb_reader_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = adb.AdbDevice("adb", "emulator-test")
    monkeypatch.setattr(
        adb.AdbDevice,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid path must not run ADB"),
    )

    with pytest.raises(DeviceDiscoveryError, match="outside the game app"):
        device.read_private_file("/data/user/0/com.pjsekai.kr/../../etc/passwd")
