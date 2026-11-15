# ps5-catalogs-hub

Stable, auto-updated catalog mirrors for AICyberGuardian's FW 13.42 console stack.

## Purpose

- Fetch canonical upstream catalogs hourly
- Validate JSON before publish
- Adapt non-standard feeds (Jobee'sLair Homebrew) into a Pegasus-compatible schema
- Serve durable HTTPS URLs consumers can poll with ETag / `If-None-Match`

## Consumers (approved split)

| Consumer | Role | Manifest |
|---|---|---|
| **PS5 Library** (`:9999`) | Gigabit game dumps (AllDebrid / Rest Mode) | [`sources-games.json`](sources-games.json) |
| **ProsperoStore** (`PPSA99000`) | Official signed homebrew install/update | Live [prosperostore.net](https://prosperostore.net/) (hub `prosperostore.json` is a mirror only) |
| **Jobee'sLair** (`PPSA99471`) | Scene / extra homebrew Prospero does not ship | Native live.jlx (hub `jobeeslair-homebrew.json` is an adapted backup) |

Do **not** add homebrew mirrors from `sources-homebrew.json` into PS5 Library.

## Layout

```text
catalogs/                 # Published JSON catalogs (stable flat raw GitHub URLs)
sources-games.json        # PS5 Library — games only
sources-homebrew.json     # Prospero + Jobee mirrors (not Library sources)
sources.json              # Compatibility: games in sources + homebrewMirrors
scripts/                  # Sync + adapter tooling
docs/superpowers/         # Spec + implementation plan
.github/workflows/        # Hourly GitHub Actions sync
```

## Console usage

1. In PS5 Library (`http://<console>:9999/` → Settings → Catalogs), add **only** URLs from `sources-games.json`.
2. Install/update official homebrew via the ProsperoStore app (not Library).
3. Use Jobee'sLair for complementary scene homebrew.

Prefer these hub game URLs over ephemeral `file:` snapshots and over direct upstream raw links that can vanish.

## Local sync

```powershell
python scripts/catalog_hub_sync.py
```

## License

Catalog JSON content remains owned by respective upstream maintainers. Hub tooling is Apache-2.0.
