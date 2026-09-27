# Project SEKAI Account Scanner

Project SEKAI Account Scanner imports a player's own progression data and
normalizes it into a versioned JSON format. The first supported server is KR.
Offline `/suite/user` import is the primary workflow; an optional live API
adapter uses the upstream `sekai-client` project.

This is an unofficial third-party tool. It is not affiliated with SEGA, Colorful
Palette, or the publishers of Project SEKAI. Unofficial API interaction may
carry account or Terms of Service risk. This project makes no claim that using
it is safe from account sanctions. You are responsible for deciding whether to
use it.

## Status

- Offline KR suite import, master-data enrichment, normalized JSON, and text
  report are implemented.
- Cards, character progression, materials/currencies, music results, decks, and
  Challenge Live solo stages are normalized.
- A local WSL2/Windows LDPlayer discovery command reads the rooted KR install,
  derives the device fingerprint, and writes only verified fields to an
  owner-only `.env`; it currently refuses the unresolved access-token mapping.
- Live KR extraction uses the pinned upstream client with a fail-closed
  authentication/suite-read request guard. This checkout has not performed a
  live account request because the access-token mapping and current
  `AES_KEY`/`AES_IV` material remain unverified.
- The vision backend is an interface stub. Screenshot recognition is future
  work.

## Architecture

Both extraction paths return the same typed `NormalizedAccount` model:

```text
raw suite JSON ───────┐
                      ├──> NormalizedAccount ───> versioned JSON / report
KR API adapter ───────┘
future vision adapter ─┘
```

The normalized dataclasses are dependency-free. Raw suite dictionaries are
validated at the import boundary and are not used by the exporter or report.
The master repository loads tables once and provides indexed ID lookups to the
normalizers.

## Setup

The project targets Python 3.12 and uses `uv`:

```bash
uv sync --group dev
uv run pjsk-scan --help
```

## Master data

KR enrichment tables come from
[Sekai-World/sekai-master-db-kr-diff](https://github.com/Sekai-World/sekai-master-db-kr-diff).
The scanner downloads only cards, rarities, characters, character profiles and
ranks, materials, music and difficulties, skills, and master lessons. Files are
cached under `data/master/kr`; ETag and Last-Modified headers avoid fetching
unchanged files. Each response is checked as a JSON array of objects before it
replaces the cached file. Music achievement and Challenge Live high-score
reward tables are also fetched for enrichment.

```bash
uv run pjsk-scan master sync --region kr
```

For a mirror, pass `--base-url` with a URL whose files use the same names and
JSON layouts. Additional regions can be configured in the downloader's region
source map.

## Offline import

Provide a JSON file containing an already obtained `/suite/user/{userId}`
response and sync master data first:

```bash
uv run pjsk-scan import raw ./suite-user.json --region kr
```

The normalized file is written to `data/output/account.json` by default. Set a
different destination with `--output`; set a different master cache with
`--master-dir`.

The importer recognizes the `userGamedata`, `userProfile`, `userCards`,
`userChargedCurrency`, `userCharacters`, `userMaterials`, `userMusicResults`,
`userMusicAchievements`, `userDecks`, and Challenge Live stage, score, reward,
and solo deck fields documented by the current
[Haruki suite schema](https://github.com/Team-Haruki/Haruki-Sekai-API/blob/b12f2d92de0ed5b889d5242b173ee89ba9b66cd3/Data/structures/6.4.0/suite.avsc).
It records the names of non-empty suite fields it does not normalize in
`unprocessedSuiteFields`; their raw values are not copied into the normalized
file. Unknown master IDs remain in the result with missing enrichment fields.

## Optional live KR import

The upstream
[Sekai-World/sekai-client](https://github.com/Sekai-World/sekai-client) is a
source checkout rather than a distributable Python package. The adapter loads
it from a local Git checkout and uses its `TwKrCredential`, account conversion,
authentication, protocol, and suite-fetch implementation. It does not copy the
upstream protocol code into this repository.

The expected upstream revision is
[`bfae1c53454777bec4107c43295d350e114d7f85`](https://github.com/Sekai-World/sekai-client/commit/bfae1c53454777bec4107c43295d350e114d7f85).
That revision targets Python 3.12 and requires the account credentials and
protocol configuration below for KR. The optional `api` extra installs the
runtime dependency set declared by that upstream revision.

```bash
mkdir -p .local
git clone https://github.com/Sekai-World/sekai-client.git .local/sekai-client
git -C .local/sekai-client checkout bfae1c53454777bec4107c43295d350e114d7f85
uv sync --group dev --extra api
export SEKAI_CLIENT_PATH="$PWD/.local/sekai-client"
```

### Windows LDPlayer from WSL2

The discovery command supports Linux `adb` and Windows `adb.exe`. In WSL2 it
checks Windows PATH and common LDPlayer install roots. If it cannot find ADB,
pass its WSL-mounted path with `--adb`; pass `--serial` when multiple devices
are connected. It does not start or stop an ADB server.

The Android package must be `com.pjsekai.kr`, and the emulator must allow root
access. The command verifies both before reading app-private data. It reads the
`SDK_OPENID` and `SEKAI_CREDENTIAL` strings from game PlayerPrefs,
`sp_device_id` from SDK preferences, and `SEKAI_ACCOUNT_INSTALL_ID` from
PlayerPrefs. It gets model/OS values from Android properties and derives the
Unity user-agent from installed APK libraries. It never reads another app's
data, dumps process memory, or modifies game data. ADB root can access private
game data, so use it only with your own emulator and keep `.env` and account
exports private.

```bash
uv run pjsk-scan credentials discover --region kr
# If needed, add --adb /mnt/<drive>/<path-to-LDPlayer>/adb.exe
# If multiple devices are attached, add --serial <adb-serial>
```

The seven account fields are written to `.env` only after Git-ignore validation
and with owner-only permissions. On the inspected KR 6.4.0 install,
`SDK_OPENID` and `SEKAI_CREDENTIAL` contain the same value. The command refuses
to treat that duplicate as the API access token and exits without writing any
discovered fields. This is deliberate: the scanner has not verified that the
game's stored `SEKAI_CREDENTIAL` is the `accessToken` expected by the pinned
client. It does not print either value. It also cannot recover the AES protocol
key from the inspected install.

### Non-network preflight

Run doctor before any live import:

```bash
uv run pjsk-scan doctor --region kr
```

Doctor performs no Project SEKAI HTTP requests. It checks Python 3.12, the
pinned local client checkout, credential/protocol configuration without
printing values, master tables, writable output/cache paths, the read-only
request guard, and ADB package/root access. Missing or malformed AES settings
fail preflight before API client authentication.

After the account credential mapping and current protocol settings are
independently verified, the local sequence is:

```bash
uv sync --group dev --extra api
uv run pjsk-scan master sync --region kr
uv run pjsk-scan credentials discover --region kr
uv run pjsk-scan doctor --region kr
# Only after doctor exits successfully:
uv run pjsk-scan import api --region kr
uv run pjsk-scan report data/output/account.json
```

If device selection is ambiguous, add `--serial <adb-serial>` to `credentials
discover` and `doctor`. If Windows ADB is not found automatically, add
`--adb /mnt/<drive>/<path-to-adb.exe>` to both commands. The current local
configuration stops before a successful doctor: the stored access-token
relationship and AES values have not been verified. No live authentication or
account request has been made.

### Account and protocol configuration

`credentials discover`, `doctor`, and `import api` load `.env` automatically;
explicit process environment values take precedence. You may pass another file
with `--env-file`. Never run `source .env`, paste values into shell history, or
commit the file. `.env.example` contains names/placeholders only.

The required KR account fields are:

```text
SEKAI_KR_SDK_OPEN_ID
SEKAI_KR_ACCESS_TOKEN
SEKAI_KR_DEVICE_ID
SEKAI_KR_INSTALL_ID
SEKAI_KR_USER_AGENT
SEKAI_KR_DEVICE_MODEL
SEKAI_KR_OS_VERSION
```

The upstream client requires all seven for its current KR credential model.
For the inspected installation, the scanner does not set the duplicated
`SEKAI_CREDENTIAL` value as the API access token. The optional live adapter
uses only values supplied through `.env` or the process environment; normal CLI
logs redact credentials, tokens, cookies, and protocol secrets.

The protocol layer separately requires `AES_KEY` and `AES_IV`. The pinned
client accepts AES key material as hex or UTF-8 representing 16, 24, or 32
bytes, and an IV representing 16 bytes. The scanner validates these lengths
before any game API request and never includes their values in errors or logs.
Never commit the values. In the current local investigation, these settings
were not found in the inspected SharedPreferences, app JSON/config field names,
or SQLite databases; opaque SDK cache blocks were not decoded. The metadata
contains generic `encryptionKey`/`encryptionIv` labels, but their owner and
values could not be established from the protected IL2CPP build. The pinned
upstream client cannot start the read-only API flow without verified protocol
settings. Do not substitute stale values from old client builds. `APP_VER` and
`APP_HASH` are optional fallback overrides for the initial KR headers; the
pinned client first tries its published TW/KR app-identity feed and retains
the overrides if that feed is unavailable. They are not account credentials.

```bash
uv run pjsk-scan import api --region kr
```

The live adapter uses the pinned client's private `_authenticate()` and
`_apply_auth_headers_and_version_info()` methods, then calls
`fetch_suite_user()`. For KR, the authentication method may make a read-only
GET to the published app-identity feed, then POST to `/user/auth` and
`/user/{userId}/login` to create/use a game session and obtain session/version
state; the scanner then GETs `/suite/user/{userId}`. It does not call
`APIClient.login()`, tutorial PATCH endpoints, or the login-bonus home refresh
PUT endpoint. Its transport guard allows only those three game routes in order,
binds login and suite retrieval to the numeric user ID returned by
authentication, rejects direct low-level transport calls, disables HTTP
redirects, and disables upstream automatic recovery that could log in again or
make progression changes. Authentication itself still creates/uses a game
session and is unofficial API interaction. Live behavior can change with
server or client updates. The suite payload is normalized in memory; live
import writes only the normalized account JSON, not a raw response file.

This live command remains unavailable until the local account credential
mapping and current AES configuration are verified and doctor passes. No live
authentication or account scan has been attempted from this checkout.

## Output schema

Normalized JSON uses `schemaVersion: 1`, `region`, and `generatedAt`, then
typed `profile`, `chargedCurrency`, `cards`, `characters`, `materials`,
`musicResults`, `musicAchievements`, `decks`, and Challenge Live stage, score,
reward, and deck sections. Card entries include the source level, skill
level, master rank, special-training status, and fields enriched from KR master
data, including rarity limits and skill text. Per-card power is `null` because
the suite card records do not contain those stats and this version does not
calculate them.

Card JSON exposes `baseMaxLevel` and `trainingMaxLevel` from master data.
`maxLevel` is the effective cap: trained cards use the training cap, confirmed
untrained cards use the base cap, and an unrecognized training state leaves
`maxLevel` null when the two caps differ.

The source has direct full-combo and all-perfect flags. Those flags are
preserved as reported. `cleared` is `true` when one of those flags confirms a
clear and otherwise remains `null`; the exporter does not infer a clear from an
unverified `playResult` string. Similarly, unknown special-training status
strings are preserved, with the derived trained boolean left `null`.

Normalized output may contain your in-game display name, progression, and
account data. Output and cache directories are ignored by Git. JSON exports are
written with owner-only file permissions on supported systems. Treat them as
private account data and do not share them casually. Raw suite dumps are
potentially more sensitive; importing does not retain or write them.

## Report

```bash
uv run pjsk-scan report data/output/account.json
```

The report includes owned cards by rarity, confirmed special training, card
rank/skill caps when available, character ranks, material quantities, music
results, decks, and Challenge Live stages. Caps are read from the synced master
tables rather than guessed in report code.

## Tests and checks

Tests use deterministic synthetic account and master-data fixtures. They do not
contact the game or require credentials.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

CI runs the same lint, format, type-check, and test steps on GitHub-hosted
runners with Python 3.12.

## Limitations

- KR is the only configured server.
- The importer normalizes the progression domains listed above. It reports
  names of additional non-empty suite fields without retaining their values.
- Master data is fetched from a third-party repository and may lag the game.
- Live API extraction depends on the pinned upstream checkout and current
  service behavior; it has not been tested with a real account.
- Vision/screenshot extraction is not implemented.
