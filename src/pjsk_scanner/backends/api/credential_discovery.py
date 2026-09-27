"""Extract the current KR account fingerprint from an owned Android install."""

from __future__ import annotations

import hmac
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import IO

from pjsk_scanner.adb import AdbDevice, resolve_adb_executable, select_device
from pjsk_scanner.errors import DeviceDiscoveryError

_PREFERENCE_DIR = "/data/user/0/com.pjsekai.kr/shared_prefs"
_PLAYER_PREFS = f"{_PREFERENCE_DIR}/com.pjsekai.kr.v2.playerprefs.xml"
_SDK_PREFS = f"{_PREFERENCE_DIR}/tt_game.xml"
_MAX_APK_BYTES = 300 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024
_UNITY_VERSION = re.compile(rb"20[0-9]{2}\.[0-9]+\.[0-9]+f[0-9]+")
_LIBCURL_VERSION = re.compile(rb"libcurl/([0-9]+\.[0-9]+\.[0-9]+)")


def discover_kr_environment(
    *, adb: str | None = None, serial: str | None = None
) -> dict[str, str]:
    """Read only known KR preferences and the installed Unity HTTP fingerprint."""
    executable = resolve_adb_executable(adb)
    device = select_device(executable, serial, timeout_seconds=180.0)
    device.verify_package_and_root()

    player_prefs = parse_android_preferences(device.read_private_file(_PLAYER_PREFS))
    sdk_prefs = parse_android_preferences(device.read_private_file(_SDK_PREFS))
    android_model = device.property("ro.product.model")
    android_version = device.property("ro.build.version.release")
    if not android_model or not android_version:
        raise DeviceDiscoveryError("Android device model or OS version is unavailable")

    sdk_open_id = _required_pref(player_prefs, "SDK_OPENID")
    stored_credential = _required_pref(player_prefs, "SEKAI_CREDENTIAL")
    if hmac.compare_digest(sdk_open_id, stored_credential):
        raise DeviceDiscoveryError(
            "Project SEKAI stores the same value for SDK_OPENID and "
            "SEKAI_CREDENTIAL; refusing to treat it as the API access token. "
            "No credential settings were written."
        )

    user_agent = _user_agent_from_installed_client(device)
    values = {
        "SEKAI_KR_SDK_OPEN_ID": sdk_open_id,
        "SEKAI_KR_ACCESS_TOKEN": stored_credential,
        "SEKAI_KR_DEVICE_ID": _required_pref(sdk_prefs, "sp_device_id"),
        "SEKAI_KR_INSTALL_ID": _required_pref(player_prefs, "SEKAI_ACCOUNT_INSTALL_ID"),
        "SEKAI_KR_USER_AGENT": user_agent,
        "SEKAI_KR_DEVICE_MODEL": android_model,
        "SEKAI_KR_OS_VERSION": android_version,
    }
    return values


def parse_android_preferences(contents: bytes) -> dict[str, str]:
    """Read string-valued entries from an Android SharedPreferences XML map."""
    try:
        root = ET.fromstring(contents)
    except ET.ParseError:
        raise DeviceDiscoveryError(
            "A required Android preference file is malformed"
        ) from None
    if root.tag != "map":
        raise DeviceDiscoveryError(
            "A required Android preference file has an unknown format"
        )
    values: dict[str, str] = {}
    for entry in root:
        name = entry.get("name")
        if name is None or entry.tag != "string":
            continue
        values[name] = entry.text or ""
    return values


def _required_pref(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise DeviceDiscoveryError(
            f"Required Project SEKAI preference {name} was not found or is empty"
        )
    return value


def _user_agent_from_installed_client(device: AdbDevice) -> str:
    abis = device.property("ro.product.cpu.abilist").split(",")
    abis = [abi.strip() for abi in abis if abi.strip()]
    preferred_abi = device.property("ro.product.cpu.abi")
    if not abis:
        abis = [preferred_abi] if preferred_abi else []
    apk_paths = device.package_apk_paths()
    candidates = [
        (abi, path)
        for abi in abis
        for path in apk_paths
        if f"split_config.{abi.replace('-', '_')}" in path
    ]
    preferred = [candidate for candidate in candidates if candidate[0] == preferred_abi]
    if len(preferred) == 1:
        abi, apk_path = preferred[0]
    elif len(candidates) == 1:
        abi, apk_path = candidates[0]
    elif not candidates and len(apk_paths) == 1:
        abi, apk_path = abis[0], apk_paths[0]
    else:
        raise DeviceDiscoveryError(
            "Could not identify the installed game APK split for an app ABI"
        )
    apk_data = device.read_remote_binary(apk_path, max_bytes=_MAX_APK_BYTES)
    try:
        archive = zipfile.ZipFile(io.BytesIO(apk_data))
    except (OSError, zipfile.BadZipFile):
        raise DeviceDiscoveryError(
            "The installed game APK could not be inspected"
        ) from None
    unity_library = _apk_library(archive, f"lib/{abi}/libunity.so")
    engine_versions = _apk_library_matches(
        archive, f"lib/{abi}/libil2cpp.so", _UNITY_VERSION
    )
    return _derive_unity_user_agent(unity_library, engine_versions)


def _apk_library(archive: zipfile.ZipFile, member: str) -> bytes:
    try:
        with archive.open(member) as library:
            data = library.read()
    except (KeyError, OSError, zipfile.BadZipFile):
        raise DeviceDiscoveryError(
            "The installed game APK is missing a required Unity library"
        ) from None
    return data


def derive_unity_user_agent(libunity: bytes, il2cpp: bytes) -> str:
    """Construct UnityWebRequest's agent from version strings in the installed build."""
    return _derive_unity_user_agent(libunity, _matches_in_bytes(_UNITY_VERSION, il2cpp))


def _derive_unity_user_agent(libunity: bytes, engine_versions: set[bytes]) -> str:
    if b"UnityPlayer/" not in libunity or b"UnityWebRequest/1.0, " not in libunity:
        raise DeviceDiscoveryError("Could not derive the installed Unity user agent")
    curl_versions = set(_matches_in_bytes(_LIBCURL_VERSION, libunity))
    if len(engine_versions) != 1 or len(curl_versions) != 1:
        raise DeviceDiscoveryError("Installed Unity version strings are ambiguous")
    engine_version = next(iter(engine_versions)).decode("ascii")
    curl_version = next(iter(curl_versions)).decode("ascii").removeprefix("libcurl/")
    return f"UnityPlayer/{engine_version} (UnityWebRequest/1.0, libcurl/{curl_version})"


def _matches_in_bytes(pattern: re.Pattern[bytes], contents: bytes) -> set[bytes]:
    return {match.group(0) for match in pattern.finditer(contents)}


def _matches_in_stream(pattern: re.Pattern[bytes], stream: IO[bytes]) -> set[bytes]:
    """Find bounded version literals without loading a large library at once."""
    matches: set[bytes] = set()
    carry = b""
    while chunk := stream.read(_CHUNK_BYTES):
        data = carry + chunk
        matches.update(match.group(0) for match in pattern.finditer(data))
        carry = data[-128:]
    return matches


def _apk_library_matches(
    archive: zipfile.ZipFile, member: str, pattern: re.Pattern[bytes]
) -> set[bytes]:
    try:
        with archive.open(member) as library:
            return _matches_in_stream(pattern, library)
    except (KeyError, OSError, zipfile.BadZipFile):
        raise DeviceDiscoveryError(
            "The installed game APK is missing a required Unity library"
        ) from None
