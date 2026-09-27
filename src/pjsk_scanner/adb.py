"""Read-only ADB access, including Windows adb.exe from WSL2."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pjsk_scanner.errors import DeviceDiscoveryError

PACKAGE_NAME = "com.pjsekai.kr"
_WINDOWS_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def resolve_adb_executable(explicit: str | None = None) -> str:
    """Find ADB from an option, environment, PATH, or Windows LDPlayer install."""
    configured = explicit or os.environ.get("PJSK_ADB")
    if configured:
        resolved = _normalize_executable_path(configured)
        if _is_executable(resolved):
            return resolved
        raise DeviceDiscoveryError("Configured ADB executable was not found")

    for command in ("adb", "adb.exe"):
        located = shutil.which(command)
        if located:
            return located

    powershell = _find_powershell()
    if powershell is not None:
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$found = Get-Command adb.exe -ErrorAction SilentlyContinue
if ($found) { $found.Source; exit 0 }
$programFilesX86 = [Environment]::GetFolderPath('ProgramFilesX86')
$roots = @($env:SystemDrive + '\LDPlayer')
if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles 'LDPlayer') }
if ($programFilesX86) { $roots += (Join-Path $programFilesX86 'LDPlayer') }
foreach ($root in $roots) {
  if (Test-Path $root) {
    $items = Get-ChildItem $root -Filter adb.exe -File -Recurse |
      Select-Object -First 1 -ExpandProperty FullName
    if ($items) { $items; exit 0 }
  }
}
exit 1
"""
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            candidate = result.stdout.strip().splitlines()
            if candidate:
                resolved = _normalize_executable_path(candidate[-1].strip())
                if _is_executable(resolved):
                    return resolved
    raise DeviceDiscoveryError(
        "ADB was not found; pass --adb with the Windows or Linux ADB executable"
    )


@dataclass(frozen=True)
class AdbDevice:
    """A connected ADB target selected for local inspection."""

    executable: str
    serial: str
    timeout_seconds: float = 20.0

    def run(self, *arguments: str, input_data: bytes | None = None) -> bytes:
        """Run ADB without echoing command output or errors to the terminal."""
        try:
            result = subprocess.run(
                [self.executable, "-s", self.serial, *arguments],
                input=input_data,
                check=False,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError):
            raise DeviceDiscoveryError("ADB command failed or timed out") from None
        if result.returncode != 0:
            raise DeviceDiscoveryError("ADB command failed; check device authorization")
        return result.stdout

    def verify_package_and_root(self) -> None:
        """Require the expected installed game and a functioning root shell."""
        package_paths = self.run("shell", "pm", "path", PACKAGE_NAME).decode(
            "utf-8", errors="replace"
        )
        if not any(line.startswith("package:") for line in package_paths.splitlines()):
            raise DeviceDiscoveryError(
                "Project SEKAI KR package com.pjsekai.kr is not installed "
                "on this device"
            )
        root_output = self.run(
            "shell", "su", "-c", "sh", input_data=b"id\nexit\n"
        ).decode("utf-8", errors="replace")
        if not re.search(r"\buid=0\(root\)", root_output):
            raise DeviceDiscoveryError(
                "Root access is required to inspect Project SEKAI KR app data"
            )

    def read_private_file(self, path: str) -> bytes:
        """Read a fixed, absolute Android path through a root shell."""
        app_root = PurePosixPath("/data/user/0/com.pjsekai.kr")
        candidate = PurePosixPath(path)
        if (
            not candidate.is_absolute()
            or not candidate.is_relative_to(app_root)
            or candidate == app_root
            or ".." in candidate.parts
            or "\0" in path
            or "\n" in path
        ):
            raise DeviceDiscoveryError(
                "Refusing to read outside the game app directory"
            )
        script_path = "'" + path.replace("'", "'\\''") + "'"
        return self.run(
            "shell",
            "su",
            "-c",
            "sh",
            input_data=f"cat {script_path}\nexit\n".encode(),
        )

    def property(self, name: str) -> str:
        """Read one Android system property without exposing shell diagnostics."""
        if not re.fullmatch(r"ro\.[A-Za-z0-9_.]+", name):
            raise DeviceDiscoveryError("Invalid Android property name")
        return (
            self.run("shell", "getprop", name).decode("utf-8", errors="replace").strip()
        )

    def package_apk_paths(self) -> tuple[str, ...]:
        """Return package-manager paths for the verified game package."""
        output = self.run("shell", "pm", "path", PACKAGE_NAME).decode(
            "utf-8", errors="replace"
        )
        paths = tuple(
            line.removeprefix("package:").strip()
            for line in output.splitlines()
            if line.startswith("package:/data/app/")
            # Package manager paths include encoded install-directory names,
            # commonly ``~~<base64>==``. Keep the allowed alphabet narrow while
            # accepting those names; the path is passed as one ADB argument,
            # never interpolated into a remote shell command.
            and re.fullmatch(r"/data/app/[A-Za-z0-9._~+=/-]+\.apk", line[8:])
        )
        if not paths:
            raise DeviceDiscoveryError("Could not locate the installed game APK")
        return paths

    def read_remote_binary(self, path: str, *, max_bytes: int) -> bytes:
        """Stream a bounded installed-package file over ADB without saving it."""
        if not re.fullmatch(r"/data/app/[A-Za-z0-9._~+=/-]+\.apk", path):
            raise DeviceDiscoveryError("Refusing to read a non-package APK path")
        data = self.run("exec-out", "cat", path)
        if len(data) > max_bytes:
            raise DeviceDiscoveryError(
                "Installed game APK exceeds the inspection limit"
            )
        return data


def select_device(
    executable: str, serial: str | None = None, timeout_seconds: float = 20.0
) -> AdbDevice:
    """Select one authorized emulator, rejecting ambiguous multi-device setups."""
    try:
        result = subprocess.run(
            [executable, "devices", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        raise DeviceDiscoveryError("Could not query connected ADB devices") from None
    if result.returncode != 0:
        raise DeviceDiscoveryError("Could not query connected ADB devices")
    devices: list[tuple[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2:
            devices.append((fields[0], fields[1]))
    available = [name for name, state in devices if state == "device"]
    if serial is not None:
        if serial not in available:
            raise DeviceDiscoveryError("The requested ADB device is not authorized")
        selected = serial
    else:
        emulators = [name for name in available if name.startswith("emulator-")]
        candidates = emulators if emulators else available
        if len(candidates) != 1:
            if not candidates:
                raise DeviceDiscoveryError(
                    "No authorized ADB device is connected; start LDPlayer "
                    "and authorize ADB"
                )
            raise DeviceDiscoveryError(
                "Multiple ADB devices are connected; select one with --serial"
            )
        selected = candidates[0]
    return AdbDevice(executable, selected, timeout_seconds)


def _find_powershell() -> str | None:
    for command in ("powershell.exe", "powershell"):
        found = shutil.which(command)
        if found:
            return found
    if os.name == "nt":
        return "powershell.exe"
    candidate = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    return str(candidate) if candidate.is_file() else None


def _normalize_executable_path(value: str) -> str:
    match = _WINDOWS_PATH.fullmatch(value)
    if match and os.name != "nt":
        drive, remainder = match.groups()
        return f"/mnt/{drive.lower()}/{remainder.replace(chr(92), '/')}"
    return value


def _is_executable(value: str) -> bool:
    if os.path.isfile(value):
        return os.name == "nt" or os.access(value, os.X_OK)
    return shutil.which(value) is not None
