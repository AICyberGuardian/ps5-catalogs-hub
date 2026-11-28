# Zero-Bypass DLPS Edits Overlay, Watchlist & Manual Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture unindexed direct file-hoster links from in-place edited `dlpsgame.com` PS5 posts, track redirector-gated edits in `DLPS_EDITS.md`, and support curated browser-resolved links via `catalogs/manual-overrides.json` merged into `catalogs/games-merged.json`.

**Architecture:** Pure stdlib parser/builder (`scripts/dlps_edits.py`) + validated CLI (`scripts/add_manual_override.py`) wired as fail-soft overlays into `scripts/catalog_hub_sync.py` and `.github/workflows/sync-catalogs.yml`.

**Tech Stack:** Python 3.12 stdlib, `unittest`, GitHub Actions.

## Global Constraints

- Zero anti-bot / Cloudflare challenge bypass; never fetch `downloadgameps3.net`.
- Flat `catalogs/*.json` URLs unchanged; `sources-games.json` keeps the 8 external game feeds; zero homebrew in game catalogs.
- Content-idempotent outputs (no timestamp-only commit churn in `dlps-edits.json`, `manual-overrides.json`, or `DLPS_EDITS.md`).
- Fail-soft WP REST API polling (carry over prior `catalogs/dlps-edits.json` if upstream fails).
- Zero external Python dependencies (stdlib only).

---

### Task 1: `scripts/dlps_edits.py` — Pure Per-Block Parser, Delta Builder & Watchlist Renderer

**Files:**
- Create: `tests/test_dlps_edits.py`
- Create: `scripts/dlps_edits.py`

**Interfaces:**
- Produces:
  - `parse_wp_post(post: dict[str, Any]) -> dict[str, Any]`
  - `build_dlps_edits(posts: list[dict[str, Any]], baseline_dlps: dict[str, Any], manual_overrides: dict[str, Any] | None = None, *, name: str = ...) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]`
  - `render_watchlist_markdown(rows: list[dict[str, Any]], *, generated_at: str) -> str`
  - `watchlist_body_equal(existing_md: str, new_md: str) -> bool`
  - `fetch_modified_ps5_posts(*, pages: int = 2, per_page: int = 100, user_agent: str = ...) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing tests in `tests/test_dlps_edits.py`** covering per-block multi-TitleID isolation, base64 `.secure-data` decoding, direct hoster allowlist vs. `downloadgameps3.net` exclusion, delta filtering against baseline `dlps.json`, watchlist status classification (`NEEDS_MANUAL`, `AUTO_ADDED`, `OVERRIDDEN`, `COVERED`), and `watchlist_body_equal` idempotency.
- [ ] **Step 2: Run `python -m unittest tests/test_dlps_edits.py -v`** and verify RED (`ModuleNotFoundError: No module named 'dlps_edits'`).
- [ ] **Step 3: Implement `scripts/dlps_edits.py`** with minimal clean stdlib code.
- [ ] **Step 4: Run `python -m unittest tests/test_dlps_edits.py -v`** and verify GREEN.

---

### Task 2: `scripts/add_manual_override.py` & `catalogs/manual-overrides.json`

**Files:**
- Create: `tests/test_manual_override.py`
- Create: `scripts/add_manual_override.py`
- Create: `catalogs/manual-overrides.json`

**Interfaces:**
- Produces:
  - `validate_title_id(title_id: str) -> str`
  - `parse_link_arg(spec: str) -> dict[str, str]`
  - `upsert_override(doc: dict[str, Any], *, title_id: str, title: str, version: str, links: list[dict[str, str]], region: str = "", password: str = "", notes: str = "", poster_url: str = "", download_source: str = "") -> dict[str, Any]`
  - `remove_override(doc: dict[str, Any], *, title_id: str, version: str | None = None) -> tuple[dict[str, Any], int]`
  - CLI `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write failing tests in `tests/test_manual_override.py`** covering valid `PPSA`/`CUSA` validation, rejection of invalid Title IDs and redirector URLs (`downloadgameps3.net`, `clk.sh`), idempotent upsert/merge by `(titleId, version)`, deterministic sorting, and `remove_override`.
- [ ] **Step 2: Run `python -m unittest tests/test_manual_override.py -v`** and verify RED.
- [ ] **Step 3: Implement `scripts/add_manual_override.py` and seed `catalogs/manual-overrides.json`**.
- [ ] **Step 4: Run `python -m unittest tests/test_manual_override.py -v`** and verify GREEN.

---

### Task 3: Integrate Overlays & Watchlist into `scripts/catalog_hub_sync.py`, CI & Docs

**Files:**
- Modify: `tests/test_catalog_merge.py`
- Modify: `scripts/catalog_hub_sync.py`
- Modify: `.github/workflows/sync-catalogs.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `dlps_edits.fetch_modified_ps5_posts`, `dlps_edits.build_dlps_edits`, `dlps_edits.render_watchlist_markdown`, `dlps_edits.watchlist_body_equal`
- Produces:
  - `build_dlps_edits_and_watchlist()` in `scripts/catalog_hub_sync.py`
  - `GAME_OVERLAY_PREFIX` / `GAME_OVERLAY_SUFFIX` merged into `catalogs/games-merged.json`

- [ ] **Step 1: Add failing config/integration tests in `tests/test_catalog_merge.py`** verifying overlay constants (`manual-overrides.json` prefix, `dlps-edits.json` suffix) and confirming `FEEDS` (`kind=="game"`) remains strictly 8 external feeds without homebrew.
- [ ] **Step 2: Run `python -m unittest discover -s tests -v`** and verify RED.
- [ ] **Step 3: Update `scripts/catalog_hub_sync.py` and `.github/workflows/sync-catalogs.yml`**.
- [ ] **Step 4: Run `python -m unittest discover -s tests -v`** and verify GREEN.
- [ ] **Step 5: Run `python scripts/catalog_hub_sync.py` twice** to sync `dlps-edits.json`, `DLPS_EDITS.md`, and `games-merged.json`, verifying 0 failures on Run 1 and 100% `[SAME]` / zero diff churn on Run 2.
- [ ] **Step 6: Update `README.md`** with freshly measured metrics and manual override usage instructions, then re-run full test suite and JSON integrity checks.
