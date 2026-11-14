# ps5-catalogs-hub

Stable, auto-updated PS5 Library catalog mirrors for AICyberGuardian's FW 13.42 console stack.

## Purpose

- Fetch canonical upstream catalogs hourly
- Validate JSON before publish
- Adapt non-standard feeds (Jobee'sLair Homebrew) into Pegasus / PS5 Library schema
- Serve durable HTTPS URLs the console can poll with ETag / `If-None-Match`

PS5 Library on the console re-checks online sources about every 10 minutes. This hub only needs to refresh upstream mirrors about once per hour.

## Layout

```text
catalogs/           # Published JSON catalogs (raw GitHub URLs)
sources.json        # Manifest of stable console source URLs
scripts/            # Sync + adapter tooling
.github/workflows/  # Hourly GitHub Actions sync
```

## Console usage

Add sources from `sources.json` in PS5 Library (`http://<console>:9999/` → Settings → Catalogs), or use the migration helper in the PS5-JB workspace.

Prefer these hub URLs over ephemeral `file:` snapshots and over direct upstream raw links that can vanish.

## Local sync

```powershell
python scripts/catalog_hub_sync.py
```

## License

Catalog JSON content remains owned by respective upstream maintainers. Hub tooling is Apache-2.0.
