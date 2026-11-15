# Game/Homebrew Catalog Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split hub manifests and console consumers so PS5 Library is games-only, ProsperoStore owns official homebrew, and Jobee'sLair covers Prospero gaps.

**Architecture:** Keep flat `catalogs/*.json` URLs; tag feeds as game/homebrew; emit `sources-games.json` + `sources-homebrew.json`; migrate Library sources; deploy ProsperoStore `PPSA99000`.

**Tech Stack:** Python 3 hub sync, GitHub Actions hourly, PS5 Library `/api/catalog`, ShadowMountPlus `:10101`, FTP `:2121`.

**Spec:** [docs/superpowers/specs/2026-11-14-game-homebrew-catalog-separation-design.md](../specs/2026-11-14-game-homebrew-catalog-separation-design.md)

## Global Constraints

- Flat `catalogs/<name>.json` paths must not change (existing console HTTPS URLs).
- Never create `/data/ps5_autoloader/`.
- No timestamp-only commit churn; preserve `generatedAt` when content unchanged.
- Do not add homebrew feeds back into PS5 Library.
- ProsperoStore installs from live prosperostore.net; hub Prospero JSON is mirror/docs only.
- Console IP: `<console-lan-ip>`. Hub checkout: local clone of this repo.

## File Map

| File | Responsibility |
|---|---|
| `scripts/catalog_hub_sync.py` | Tag feeds; write dual manifests |
| `sources-games.json` | Library-facing game source list |
| `sources-homebrew.json` | Prospero + Jobee mirrors with consumer hints |
| `sources.json` | Compatibility manifest (games primary; document homebrew mirrors) |
| `README.md` | Document three-consumer model |
| `SYNC_REPORT.md` | Continue reporting all feeds |
| PS5-JB migration script | Remove Library homebrew sources; verify games-only |
| PS5-JB Prospero deploy | Stage `PPSA99000` to `/data/homebrew/` |

---

### Task 1: Tag feeds and emit dual manifests

**Files:**
- Modify: `scripts/catalog_hub_sync.py`
- Create: `sources-games.json`, `sources-homebrew.json` (via sync)
- Modify: `sources.json` writer

- [ ] **Step 1: Extend `Feed` dataclass**

Add `kind: str` (`"game"` or `"homebrew"`). Mark the seven game feeds as `"game"`. Mark `homebrew-page` and `prosperostore` as `"homebrew"`. Jobee row in `sync_jobee()` also `kind="homebrew"`.

- [ ] **Step 2: Split `write_manifest()`**

Write:
1. `sources-games.json` — only `ok` rows with `kind=="game"`
2. `sources-homebrew.json` — Prospero + Jobee only (prefer `id=prosperostore`; if both Prospero and homebrew-page succeed and are identical, include Prospero once; still sync both files to disk)
3. `sources.json` — games list as `sources`, plus `"homebrewMirrors"` array pointing at homebrew entries (or document in README that top-level `sources` is games-focused — prefer explicit `homebrewMirrors` for clarity)

Each entry keeps: `id`, `name`, `url`, `items`, `sha256`, `upstream`. Homebrew entries also include `"consumer": "prospero-native"` or `"jobee-native"`.

- [ ] **Step 3: Run sync locally**

```powershell
cd <hub-checkout>
python scripts/catalog_hub_sync.py
python -c "import json; g=json.load(open('sources-games.json',encoding='utf-8')); h=json.load(open('sources-homebrew.json',encoding='utf-8')); print(len(g['sources']), [s['id'] for s in g['sources']]); print(len(h['sources']), [s['id'] for s in h['sources']])"
```

Expected: games count `7`; homebrew ids exactly `prosperostore`, `jobeeslair-homebrew`.

- [ ] **Step 4: Commit hub sync changes**

```powershell
git add scripts/catalog_hub_sync.py sources.json sources-games.json sources-homebrew.json SYNC_REPORT.md catalogs/
git commit -m "Split hub manifests into games and homebrew consumers."
```

---

### Task 2: Update hub README for three-consumer model

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite Console usage section**

Document:
- Library → `sources-games.json`
- ProsperoStore app → live prosperostore.net (hub `prosperostore.json` is mirror)
- Jobee'sLair → native live feed (hub `jobeeslair-homebrew.json` is adapted backup)

- [ ] **Step 2: Commit**

```powershell
git add README.md
git commit -m "Document games vs homebrew consumer split."
```

---

### Task 3: Push hub and verify CI

- [ ] **Step 1: Push `main`**

```powershell
git push origin HEAD
```

- [ ] **Step 2: Confirm Actions**

```powershell
gh run list --repo AICyberGuardian/ps5-catalogs-hub --limit 3
```

Expect latest sync workflow success.

---

### Task 4: Remove homebrew sources from PS5 Library

**Files:**
- Create/modify: private PS5-JB workspace script `scripts/migrate_library_games_only.py` (console-side; not published in this hub)

- [ ] **Step 1: Snapshot current sources**

```powershell
python -c "import urllib.request,json; print(json.dumps(json.load(urllib.request.urlopen('http://<console-lan-ip>:9999/api/catalog-sources')),indent=2)[:4000])"
```

Record ids that are homebrew / Jobee / prosperostore / homebrew-page.

- [ ] **Step 2: Remove non-game Library sources**

Via Library catalog API, remove every source whose URL is not a games hub catalog (`dlps`, `zer0`, `pippo`, `pfs`, `blackbox_catalog`, `jamzi94-ps5`, `pegasus-ps4-catalog`).

Do **not** remove game sources. Do **not** re-add Prospero or Jobee JSON.

- [ ] **Step 3: Verify**

Assert:
- source count == 7
- all URLs under hub `catalogs/` game filenames
- failures == 0
- no `file:` sources

- [ ] **Step 4: Commit PS5-JB script/docs note** (if new script)

---

### Task 5: Deploy ProsperoStore `PPSA99000`

**Files / assets:**
- Prefer verified `darkxex/ProsperoStore` release `PPSA99000.zip` v1.000.116 (or a locally staged copy outside this public repo)
- Use private PS5-JB safe-deploy patterns (FTP + SMP rescan); do not commit console deploy tooling here

- [ ] **Step 1: Verify package hash locally**

Confirm zip/sha256 against release notes before transfer.

- [ ] **Step 2: Deploy to `/data/homebrew/PPSA99000/`**

Publish `eboot.bin` last. Do not touch `/data/ps5_autoloader/`.

- [ ] **Step 3: SMP rescan + assert**

```text
title_id == PPSA99000
installed == true
managed == true
```

- [ ] **Step 4: Dual-boot invariant check**

FTP `LIST /data/ps5_autoloader/` must still fail with 550.

---

### Task 6: End-to-end verification

- [ ] **Step 1: Hub raw URLs**

Fetch `sources-games.json` and `sources-homebrew.json` from raw GitHub; confirm schema.

- [ ] **Step 2: Library**

`GET :9999` catalog health — 7 sources, games only, 0 failures.

- [ ] **Step 3: Prospero**

Home screen / SMP shows ProsperoStore; user can launch (manual TV check).

- [ ] **Step 4: Jobee**

SMP still lists `PPSA99471`; no Library Jobee source.

- [ ] **Step 5: Update session notes**

Append short note to latest PS5-scene continuation snapshot or AGENTS.md if required by workspace rules — games-only Library + Prospero deployed.

---

## Done when

- [x] Design approved (#1)
- [ ] Hub dual manifests live on `main`
- [ ] Library games-only (7 HTTPS sources)
- [ ] ProsperoStore installed on NVMe
- [ ] Jobee remains complementary native store, not Library feed
