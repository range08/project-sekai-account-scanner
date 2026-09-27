"""Command-line interface for master sync, import, and reporting."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pjsk_scanner.backends.api.credential_discovery import discover_kr_environment
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.extractor import ApiExtractor
from pjsk_scanner.backends.api.protocol import ApiProtocolConfig
from pjsk_scanner.doctor import format_doctor, run_doctor
from pjsk_scanner.errors import ApiBackendError, ScannerError
from pjsk_scanner.export.json_exporter import export_account, load_account
from pjsk_scanner.export.summary import render_summary
from pjsk_scanner.local_config import load_env_file, write_private_env
from pjsk_scanner.master.downloader import MasterDataDownloader
from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.normalize.account import normalize_suite_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pjsk-scan",
        description="Extract and normalize your Project SEKAI account progression.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="show a traceback for unexpected errors"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    master = commands.add_parser("master", help="manage regional master data")
    master_commands = master.add_subparsers(dest="master_command", required=True)
    sync = master_commands.add_parser("sync", help="download or update master tables")
    _add_region(sync)
    sync.add_argument("--cache-dir", type=Path, default=Path("data/master"))
    sync.add_argument(
        "--base-url",
        help="override the raw master-data base URL (useful for mirrors)",
    )
    sync.add_argument("--timeout", type=float, default=30.0)

    importer = commands.add_parser("import", help="import account progression")
    import_commands = importer.add_subparsers(dest="import_source", required=True)
    raw = import_commands.add_parser("raw", help="normalize a saved suite-user JSON")
    raw.add_argument("path", type=Path)
    _add_region(raw)
    _add_import_paths(raw)
    api = import_commands.add_parser("api", help="fetch your account from KR")
    _add_region(api)
    _add_import_paths(api)
    api.add_argument("--env-file", type=Path, default=Path(".env"))

    credentials = commands.add_parser(
        "credentials", help="manage local API credentials"
    )
    credential_commands = credentials.add_subparsers(
        dest="credentials_command", required=True
    )
    discover = credential_commands.add_parser(
        "discover", help="read your rooted Android KR installation safely"
    )
    _add_region(discover)
    discover.add_argument("--adb", help="ADB executable; can be a Windows adb.exe")
    discover.add_argument(
        "--serial", help="ADB serial when multiple devices are connected"
    )
    discover.add_argument("--env-file", type=Path, default=Path(".env"))

    doctor = commands.add_parser(
        "doctor", help="check local configuration without game API requests"
    )
    _add_region(doctor)
    doctor.add_argument("--adb", help="ADB executable; can be a Windows adb.exe")
    doctor.add_argument(
        "--serial", help="ADB serial when multiple devices are connected"
    )
    doctor.add_argument("--env-file", type=Path, default=Path(".env"))
    doctor.add_argument("--master-dir", type=Path, default=Path("data/master"))
    doctor.add_argument("--output-dir", type=Path, default=Path("data/output"))

    report = commands.add_parser("report", help="summarize normalized account JSON")
    report.add_argument("path", type=Path)
    return parser


def _add_region(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--region", choices=("kr",), default="kr")


def _add_import_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--master-dir", type=Path, default=Path("data/master"))
    parser.add_argument("--output", type=Path, default=Path("data/output/account.json"))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, keeping expected failures concise and credential-safe."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "master" and args.master_command == "sync":
            downloader = MasterDataDownloader(
                args.cache_dir,
                timeout_seconds=args.timeout,
                base_url=args.base_url,
            )
            paths = downloader.sync(args.region)
            print(
                f"Synced {len(paths)} KR master tables to "
                f"{args.cache_dir / args.region}"
            )
            return 0
        if args.command == "import" and args.import_source == "raw":
            suite = _read_suite_json(args.path)
            master = MasterDataRepository(args.master_dir, args.region)
            account = normalize_suite_payload(suite, master, region=args.region)
            destination = export_account(account, args.output)
            print(f"Wrote normalized account JSON to {destination}")
            return 0
        if args.command == "import" and args.import_source == "api":
            load_env_file(args.env_file)
            credentials = ApiCredentials.from_environment()
            ApiProtocolConfig.from_environment()
            master = MasterDataRepository(args.master_dir, args.region)
            account = ApiExtractor(master, credentials).extract()
            destination = export_account(account, args.output)
            print(f"Wrote normalized account JSON to {destination}")
            return 0
        if args.command == "credentials" and args.credentials_command == "discover":
            load_env_file(args.env_file)
            discovered = discover_kr_environment(adb=args.adb, serial=args.serial)
            destination = write_private_env(discovered, args.env_file)
            print(
                f"Discovered {len(discovered)} KR account/API fields and wrote them "
                "to the Git-ignored local config with owner-only permissions."
            )
            try:
                ApiProtocolConfig.from_environment()
            except ApiBackendError as error:
                print(f"pjsk-scan: {error}", file=sys.stderr)
                return 1
            print(
                f"Required AES protocol configuration is present in {destination.name}."
            )
            return 0
        if args.command == "doctor":
            checks = run_doctor(
                region=args.region,
                env_file=args.env_file,
                master_dir=args.master_dir,
                output_dir=args.output_dir,
                adb=args.adb,
                serial=args.serial,
            )
            print(format_doctor(checks))
            return 0 if all(check.ok for check in checks) else 1
        if args.command == "report":
            print(render_summary(load_account(args.path)))
            return 0
        parser.error("Unknown command")
    except (ScannerError, ValueError, OSError) as error:
        if args.debug:
            raise
        print(f"pjsk-scan: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        if args.debug:
            raise
        print(
            f"pjsk-scan: unexpected error ({type(error).__name__}); "
            "rerun with --debug for details",
            file=sys.stderr,
        )
        return 1
    return 2


def _read_suite_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Suite JSON file not found: {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"Could not read valid suite JSON from {path}") from None


if __name__ == "__main__":
    raise SystemExit(main())
