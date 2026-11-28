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
  dlps-edits.json         # Auto delta overlay: net-new direct hoster links from edited dlpsgame posts
  manual-overrides.json   # Curated browser-resolved links (highest merge priority in games-merged)
sources-games.json        # PS5 Library - 8 individual external game feeds
sources-merged.json       # Single-URL merged catalogs (games / homebrew / payloads)
sources-payloads.json     # Payload Manager (:8084) feed (merged) + upstream list
sources-homebrew.json     # Prospero + Jobee mirrors (not Library sources)
sources.json              # Compatibility: games in sources + homebrewMirrors
DLPS_EDITS.md             # Watchlist of recent in-place dlpsgame.com edits (NEEDS_MANUAL / AUTO_ADDED)
scripts/                  # Sync + adapter + merge + dlps_edits + manual override CLI
tests/                    # Offline unit tests: python -m unittest discover -s tests -v
docs/superpowers/         # Specs + implementation plans
.github/workflows/        # Hourly GitHub Actions sync
```

## Merged (concise) catalogs - so the console ingests less

All built hourly by `scripts/catalog_hub_sync.py`, minified JSON, content-idempotent (no churn commits).

| File | What it is | Measured (2026-11-28) |
|---|---|---|
| `catalogs/games-merged.json` | The 8 game feeds + `manual-overrides.json` (first) + `dlps-edits.json` (direct-link delta overlay from edited `dlpsgame.com` posts) in one URL. **Only exact duplicate URLs for the same titleId are dropped** (title-ID overlap is never treated as redundancy; mirrors on other hosts stay). Lossless: every `(titleId,url)` pair is preserved. | 23.13 MB -> 11.11 MB; 70,833 -> 46,225 links; 6,204 pkgs; 0 pairs lost |
| `catalogs/homebrew-merged.json` | ProsperoStore + Solanum + RecompStore + AnchorPS5 + Jobee'sLair Homebrew, **one entry per GitHub repo or download URL** (priority in that order; `sources` lists every feed carrying it). AnchorPS5 entries without a live release are pruned. Mirror only - not a PS5 Library source. | 478 entries, 0.36 MB |
| `catalogs/payloads-merged.json` | ps5-payloads-atlas + PLDMGR_JSON + ps5-payloads-mirror in Payload Manager format, deduped by URL then (name, version). Browse / on-demand only. | 141 payloads, 0.08 MB |

**Use ONE of:** `games-merged.json` (recommended — includes `manual-overrides.json` and `dlps-edits.json` automatically) **or** the 8 individual game URLs from `sources-games.json` (external feeds only; does **not** receive overlays). Using both re-ingests the same data. Switch helper (dry-run default): `PS5-JB/scripts/migrate_ps5_library_to_merged_games.py`.

Payload Manager: Settings -> Manage Sources -> Add Source -> `https://raw.githubusercontent.com/AICyberGuardian/ps5-catalogs-hub/main/catalogs/payloads-merged.json`.

## Console usage

1. In PS5 Library (`http://<console>:9999/` → Settings → Catalogs), add **only** the single `games-merged.json` URL from `sources-merged.json` **or** the 8 URLs from `sources-games.json` (never both).
2. Install/update official homebrew via the ProsperoStore app (not Library).
3. Use Jobee'sLair for complementary scene homebrew.

Prefer these hub game URLs over ephemeral `file:` snapshots and over direct upstream raw links that can vanish.

## Local sync & manual overrides

```powershell
python scripts/catalog_hub_sync.py
```

Check [`DLPS_EDITS.md`](DLPS_EDITS.md) for recent in-place edits on `dlpsgame.com` marked `NEEDS_MANUAL` (redirector-gated releases). After resolving hoster links in your browser, add them to `catalogs/manual-overrides.json` and rebuild `games-merged.json`:

```powershell
python scripts/add_manual_override.py add `
  --title-id PPSA02572 `
  --title "Alan Wake 2 Deluxe Edition" `
  --version 01.200.009 `
  --region EUR `
  --password DLPSGAME.COM `
  --link "Akia=https://akirabox.com/.../file" `
  --link "Viki=https://vikingfile.com/f/..."
python scripts/catalog_hub_sync.py
```

## License

Catalog JSON content remains owned by respective upstream maintainers. Hub tooling is Apache-2.0.
