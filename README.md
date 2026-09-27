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
- The live KR adapter is implemented against a pinned upstream client revision.
  It has not been exercised against the live game service as part of the normal
  test suite.
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
That revision targets Python 3.12, requires the credentials listed below for
KR, and exposes `APIClient.login()` / `fetch_suite_user()`.
The optional `api` extra installs the runtime dependency set declared by that
upstream revision.

```bash
mkdir -p .local
git clone https://github.com/Sekai-World/sekai-client.git .local/sekai-client
git -C .local/sekai-client checkout bfae1c53454777bec4107c43295d350e114d7f85
uv sync --group dev --extra api
export SEKAI_CLIENT_PATH="$PWD/.local/sekai-client"
```

Supply these values explicitly in the environment:

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
`.env.example` lists the variable names, but the CLI does not automatically
load a `.env` file. Do not paste secrets into shell history or commit them.
The adapter only reads explicitly supplied environment values. It does not
inspect other applications or processes for credentials. Its upstream logger
is silenced so request headers and tokens do not appear in normal CLI logs.

```bash
uv run --extra api pjsk-scan import api --region kr
```

The API response is normalized in memory and is not saved as a raw file. The
upstream client may make authentication and post-login requests as part of its
login flow. Live behavior can change with server or client updates.

## Output schema

Normalized JSON uses `schemaVersion: 1`, `region`, and `generatedAt`, then
typed `profile`, `chargedCurrency`, `cards`, `characters`, `materials`,
`musicResults`, `musicAchievements`, `decks`, and Challenge Live stage, score,
reward, and deck sections. Card entries include the source level, skill
level, master rank, special-training status, and fields enriched from KR master
data, including rarity limits and skill text. Per-card power is `null` because
the suite card records do not contain those stats and this version does not
calculate them.

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
  service behavior; it has not been validated with a real account in CI.
- Vision/screenshot extraction is not implemented.
