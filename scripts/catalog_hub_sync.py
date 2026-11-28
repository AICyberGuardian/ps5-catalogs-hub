#!/usr/bin/env python3
"""Fetch, validate, and publish canonical PS5 catalogs into this hub repo."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_merge  # noqa: E402
import dlps_edits  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "catalogs"
SOURCES_MANIFEST = ROOT / "sources.json"
SOURCES_GAMES = ROOT / "sources-games.json"
SOURCES_HOMEBREW = ROOT / "sources-homebrew.json"
REPORT = ROOT / "SYNC_REPORT.md"
DLPS_EDITS_REPORT = ROOT / "DLPS_EDITS.md"
USER_AGENT = "ps5-catalogs-hub/1.0 (+https://github.com/AICyberGuardian/ps5-catalogs-hub)"
RAW_BASE = "https://raw.githubusercontent.com/AICyberGuardian/ps5-catalogs-hub/main/catalogs"

HOMEBREW_CONSUMERS = {
    "prosperostore": "prospero-native",
    "homebrew-page": "prospero-native",
    "jobeeslair-homebrew": "jobee-native",
}


@dataclass(frozen=True)
class Feed:
    filename: str
    source_id: str
    name: str
    urls: tuple[str, ...]
    description: str
    kind: str  # "game" | "homebrew"


FEEDS: tuple[Feed, ...] = (
    Feed(
        "dlps.json",
        "dlpsgame",
        "DLPSGame",
        (
            "https://pegasus-dl.dev/catalogs/dlps.json",
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/dlps.json",
        ),
        "Multi-host debrid mirrors",
        "game",
    ),
    Feed(
        "zer0.json",
        "zer0game",
        "ZER0GAME",
        (
            "https://pegasus-dl.dev/catalogs/zer0.json",
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/zer0.json",
        ),
        "Direct mirrors (Gofile / Fuckingfast)",
        "game",
    ),
    Feed(
        "pippo.json",
        "pippo-exfat",
        "Pippo .exFAT",
        (
            "https://pegasus-dl.dev/catalogs/pippo.json",
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/pippo.json",
        ),
        "exFAT mountable folder dumps",
        "game",
    ),
    Feed(
        "pfs.json",
        "pfs-catalog",
        "PFS Direct Rips",
        (
            "https://pegasus-dl.dev/catalogs/pfs.json",
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/pfs.json",
        ),
        "Native .ffpfsc ShadowMountPlus containers",
        "game",
    ),
    Feed(
        "blackbox_catalog.json",
        "evox-blackbox",
        "evoX BlackBox",
        (
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/blackbox_catalog.json",
        ),
        "Archive.org / Vikingfile direct mirrors",
        "game",
    ),
    Feed(
        "jamzi94-ps5.json",
        "phoenix-dl-ps5",
        "Phoenix DL PS5 (Jamzi94)",
        ("https://raw.githubusercontent.com/Jamzi94/catalog-V2/main/ps5-catalog.json",),
        "Link-Vault / Rootz mirrors",
        "game",
    ),
    Feed(
        "padrino-store.json",
        "padrino-store",
        "Padrino Store",
        ("https://pegasus-dl.dev/catalogs/padrino-store.json",),
        "ZSTD / VikingFile / Archive.org PS5 mirrors",
        "game",
    ),
    Feed(
        "pegasus-ps4-catalog.json",
        "ps4-fpkg-collection-catalog",
        "PS4 FPKG Collection",
        (
            "https://raw.githubusercontent.com/M3hmetSa1t/pegasus-ps4-collection-catalog/main/pegasus-ps4-catalog.json",
        ),
        "Internet Archive clean base + updates",
        "game",
    ),
    Feed(
        "homebrew-page.json",
        "homebrew-page",
        "PS5 Homebrew (homebrew.page alias)",
        (
            "https://homebrew.page/catalog/v1.json",
            # Host/router homebrew-isolation may sinkhole homebrew.page; ProsperoStore is the successor feed.
            "https://prosperostore.net/catalog/v1.json",
            "https://raw.githubusercontent.com/darkxex/ps5-homebrew-catalog/main/catalog/v1.json",
        ),
        "Alias mirror of ProsperoStore catalog (URL stability)",
        "homebrew",
    ),
    Feed(
        "prosperostore.json",
        "prosperostore",
        "ProsperoStore",
        (
            "https://prosperostore.net/catalog/v1.json",
            "https://homebrew.page/catalog/v1.json",
        ),
        "ProsperoStore homebrew catalog",
        "homebrew",
    ),
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_items(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("packages", "apps", "payloads", "entries", "games", "items", "titles"):
            val = data.get(key)
            if isinstance(val, list):
                return len(val)
    return 0


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def fetch_first(urls: tuple[str, ...]) -> tuple[str, bytes]:
    errors: list[str] = []
    for url in urls:
        try:
            return url, fetch_bytes(url)
        except Exception as exc:  # noqa: BLE001 - collect and continue
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def write_if_changed(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes().replace(b"\r\n", b"\n")
        incoming = data.replace(b"\r\n", b"\n")
        if existing == incoming:
            return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return True


def sync_direct_feeds() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feed in FEEDS:
        dest = CATALOGS / feed.filename
        try:
            used_url, raw = fetch_first(feed.urls)
            parsed = json.loads(raw.decode("utf-8"))
            changed = write_if_changed(dest, raw)
            rows.append(
                {
                    "id": feed.source_id,
                    "name": feed.name,
                    "filename": feed.filename,
                    "kind": feed.kind,
                    "items": count_items(parsed),
                    "bytes": len(raw),
                    "sha256": sha256_hex(raw),
                    "upstream": used_url,
                    "changed": changed,
                    "ok": True,
                    "error": "",
                }
            )
            print(
                f"[{'UPDT' if changed else 'SAME'}] {feed.filename:28} items={count_items(parsed):5d} "
                f"via {used_url}"
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "id": feed.source_id,
                    "name": feed.name,
                    "filename": feed.filename,
                    "kind": feed.kind,
                    "items": 0,
                    "bytes": 0,
                    "sha256": "",
                    "upstream": feed.urls[0],
                    "changed": False,
                    "ok": False,
                    "error": str(exc),
                }
            )
            print(f"[FAIL] {feed.filename:28} {exc}")
    return rows


def sync_jobee() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from adapt_jobee_homebrew_catalog import DEFAULT_URL, adapt, fetch_json  # type: ignore

    dest = CATALOGS / "jobeeslair-homebrew.json"
    try:
        existing_catalog = None
        if dest.exists():
            try:
                existing_catalog = json.loads(dest.read_text(encoding="utf-8"))
            except Exception:
                existing_catalog = None
        adapted = adapt(fetch_json(DEFAULT_URL), existing_catalog=existing_catalog)
        raw = (json.dumps(adapted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        changed = write_if_changed(dest, raw)
        row = {
            "id": "jobeeslair-homebrew",
            "name": "Jobee'sLair Homebrew (adapted)",
            "filename": "jobeeslair-homebrew.json",
            "kind": "homebrew",
            "items": count_items(adapted),
            "bytes": len(raw),
            "sha256": sha256_hex(raw),
            "upstream": DEFAULT_URL,
            "changed": changed,
            "ok": True,
            "error": "",
        }
        print(
            f"[{'UPDT' if changed else 'SAME'}] jobeeslair-homebrew.json     "
            f"items={row['items']:5d} via {DEFAULT_URL}"
        )
        return row
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] jobeeslair-homebrew.json     {exc}")
        return {
            "id": "jobeeslair-homebrew",
            "name": "Jobee'sLair Homebrew (adapted)",
            "filename": "jobeeslair-homebrew.json",
            "kind": "homebrew",
            "items": 0,
            "bytes": 0,
            "sha256": "",
            "upstream": DEFAULT_URL,
            "changed": False,
            "ok": False,
            "error": str(exc),
        }


def _entry_from_row(row: dict[str, Any], *, include_consumer: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "url": f"{RAW_BASE}/{row['filename']}",
        "items": row["items"],
        "sha256": row["sha256"],
        "upstream": row["upstream"],
    }
    if include_consumer:
        entry["consumer"] = HOMEBREW_CONSUMERS.get(row["id"], "unknown")
    return entry


def _preserve_generated_at(path: Path, payload_key: str, payload: Any) -> str | None:
    if not path.exists():
        return None
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get(payload_key) == payload and existing.get("generatedAt"):
            return str(existing["generatedAt"])
    except Exception:
        return None
    return None


def _homebrew_manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prospero once (canonical) + Jobee; still sync homebrew-page.json to disk separately."""
    by_id = {r["id"]: r for r in rows if r.get("ok")}
    selected: list[dict[str, Any]] = []
    if "prosperostore" in by_id:
        selected.append(by_id["prosperostore"])
    elif "homebrew-page" in by_id:
        selected.append(by_id["homebrew-page"])
    if "jobeeslair-homebrew" in by_id:
        selected.append(by_id["jobeeslair-homebrew"])
    return selected


def write_manifests(rows: list[dict[str, Any]]) -> bool:
    game_rows = [r for r in rows if r.get("ok") and r.get("kind") == "game"]
    homebrew_rows = _homebrew_manifest_rows(rows)

    game_sources = [_entry_from_row(r) for r in game_rows]
    homebrew_sources = [_entry_from_row(r, include_consumer=True) for r in homebrew_rows]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    games_gen = _preserve_generated_at(SOURCES_GAMES, "sources", game_sources) or now
    hb_gen = _preserve_generated_at(SOURCES_HOMEBREW, "sources", homebrew_sources) or now

    games_manifest = {
        "name": "AICyberGuardian PS5 Catalogs Hub — Games",
        "version": "1.0.0",
        "kind": "games",
        "consumer": "ps5-library",
        "generatedAt": games_gen,
        "rawBase": RAW_BASE,
        "sources": game_sources,
    }
    homebrew_manifest = {
        "name": "AICyberGuardian PS5 Catalogs Hub — Homebrew Mirrors",
        "version": "1.0.0",
        "kind": "homebrew",
        "generatedAt": hb_gen,
        "rawBase": RAW_BASE,
        "note": (
            "Mirrors only. ProsperoStore app uses prosperostore.net live; "
            "Jobee'sLair uses its native live.jlx. Do not add these to PS5 Library."
        ),
        "sources": homebrew_sources,
    }

    compat_sources = game_sources
    compat_homebrew = homebrew_sources
    expected_manifests = {
        "games": "sources-games.json",
        "homebrew": "sources-homebrew.json",
        "merged": "sources-merged.json",
        "payloads": "sources-payloads.json",
    }
    compat_gen = None
    if SOURCES_MANIFEST.exists():
        try:
            existing = json.loads(SOURCES_MANIFEST.read_text(encoding="utf-8"))
            if (
                existing.get("sources") == compat_sources
                and existing.get("homebrewMirrors") == compat_homebrew
                and existing.get("manifests") == expected_manifests
                and existing.get("generatedAt")
            ):
                compat_gen = existing["generatedAt"]
        except Exception:
            pass

    compat_manifest = {
        "name": "AICyberGuardian PS5 Catalogs Hub",
        "version": "1.1.0",
        "generatedAt": compat_gen or now,
        "rawBase": RAW_BASE,
        "sources": compat_sources,
        "homebrewMirrors": compat_homebrew,
        "manifests": expected_manifests,
    }

    changed = False
    changed |= write_if_changed(
        SOURCES_GAMES, (json.dumps(games_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    changed |= write_if_changed(
        SOURCES_HOMEBREW,
        (json.dumps(homebrew_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    changed |= write_if_changed(
        SOURCES_MANIFEST,
        (json.dumps(compat_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    return changed


def write_report(rows: list[dict[str, Any]], force: bool = False) -> None:
    if not force and REPORT.exists() and not any(r["changed"] for r in rows):
        return

    ok = sum(1 for r in rows if r["ok"])
    lines = [
        "# Catalog Hub Sync Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Sources OK: {ok}/{len(rows)}",
        "",
        "| Source | Kind | Items | Changed | Status | Upstream |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for r in rows:
        status = "OK" if r["ok"] else f"FAIL: {r['error'][:80]}"
        lines.append(
            f"| `{r['id']}` | {r.get('kind', '?')} | {r['items']} | "
            f"{'yes' if r['changed'] else 'no'} | {status} | `{r['upstream']}` |"
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Merged / concise catalogs (single URL each; deduped; min-JSON) + payload feeds
# ---------------------------------------------------------------------------

SOURCES_MERGED = ROOT / "sources-merged.json"
SOURCES_PAYLOADS = ROOT / "sources-payloads.json"

# Priority order only decides which copy of an EXACT duplicate URL survives.
GAME_MERGE_ORDER: tuple[tuple[str, str], ...] = (
    ("pfs.json", "pfs-catalog"),
    ("pippo.json", "pippo-exfat"),
    ("zer0.json", "zer0game"),
    ("dlps.json", "dlpsgame"),
    ("blackbox_catalog.json", "evox-blackbox"),
    ("jamzi94-ps5.json", "phoenix-dl-ps5"),
    ("padrino-store.json", "padrino-store"),
    ("pegasus-ps4-catalog.json", "ps4-fpkg-collection-catalog"),
)

# Overlays merged into games-merged.json (not external sources-games.json feeds):
# manual-overrides first so curated labels/versions win; dlps-edits last for net-new direct links.
GAME_OVERLAY_PREFIX: tuple[tuple[str, str], ...] = (("manual-overrides.json", "manual-overrides"),)
GAME_OVERLAY_SUFFIX: tuple[tuple[str, str], ...] = (("dlps-edits.json", "dlps-edits"),)

RECOMPSTORE_URL = "https://recompstore.com/catalog.json"
SOLANUM_URL = "https://raw.githubusercontent.com/Oliv3rmoon/Solanum-Catalog/main/catalog.json"
SOLANUM_RAW_BASE = "https://raw.githubusercontent.com/Oliv3rmoon/Solanum-Catalog/main"
ANCHOR_CATALOG_URL = "https://raw.githubusercontent.com/Kuroge/AnchorPS5-catalog/main/catalog.json"
ANCHOR_RELEASES_URL = "https://raw.githubusercontent.com/Kuroge/AnchorPS5-catalog/main/releases.json"

PAYLOAD_SOURCES: tuple[tuple[str, str], ...] = (
    ("ps5-payloads-atlas", "https://lucaszhongsj.github.io/ps5-payloads-atlas/payloads.json"),
    ("pldmgr-json", "https://raw.githubusercontent.com/RDX-Sci01/PLDMGR_JSON/main/payloads.json"),
    ("ps5-payloads-mirror", "https://raw.githubusercontent.com/siko15006-bot/ps5-payloads-mirror/main/payloads_v3.json"),
)


def _dump_compact(doc: Any) -> bytes:
    return (json.dumps(doc, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None


def fetch_json_optional(url: str) -> Any:
    for attempt in (1, 2):
        try:
            return json.loads(fetch_bytes(url).decode("utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] {url} attempt {attempt}: {exc}")
    return None


def _merged_row(
    rid: str, name: str, filename: str, kind: str, items: int, raw: bytes, upstream: str, changed: bool
) -> dict[str, Any]:
    return {
        "id": rid,
        "name": name,
        "filename": filename,
        "kind": kind,
        "items": items,
        "bytes": len(raw),
        "sha256": sha256_hex(raw),
        "upstream": upstream,
        "changed": changed,
        "ok": True,
        "error": "",
    }


def build_dlps_edits_and_watchlist() -> dict[str, Any]:
    """Poll open dlpsgame WP REST API (orderby=modified) for net-new direct links + watchlist."""
    dest = CATALOGS / "dlps-edits.json"
    baseline_docs = [_load_json(CATALOGS / fn) for fn, _ in GAME_MERGE_ORDER]
    overrides = _load_json(CATALOGS / "manual-overrides.json")
    try:
        posts = dlps_edits.fetch_modified_ps5_posts(pages=2, per_page=100, user_agent=USER_AGENT)
        overlay, watch_rows, stats = dlps_edits.build_dlps_edits(posts, baseline_docs, overrides)
        raw = _dump_compact(overlay)
        changed = write_if_changed(dest, raw)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        watch_md = dlps_edits.render_watchlist_markdown(watch_rows, generated_at=now)
        watch_changed = True
        if DLPS_EDITS_REPORT.exists():
            existing_md = DLPS_EDITS_REPORT.read_text(encoding="utf-8")
            if dlps_edits.watchlist_body_equal(existing_md, watch_md):
                watch_changed = False
        if watch_changed:
            write_if_changed(DLPS_EDITS_REPORT, watch_md.encode("utf-8"))

        print(
            f"[{'UPDT' if changed else 'SAME'}] dlps-edits.json {stats} "
            f"bytes={len(raw)} watchlist={'UPDT' if watch_changed else 'SAME'}"
        )
        return _merged_row(
            "dlps-edits",
            "DLPSGame in-place edits (direct hosters overlay)",
            "dlps-edits.json",
            "overlay-games",
            stats["packages_out"],
            raw,
            f"{dlps_edits.WP_API_BASE}?categories={dlps_edits.PS5_CATEGORY_ID}&orderby=modified",
            changed or watch_changed,
        )
    except Exception as exc:  # noqa: BLE001 - fail-soft overlay; preserve prior snapshot
        print(f"[WARN] dlps-edits.json carry-over after WP API error: {exc}")
        prev_bytes = dest.read_bytes() if dest.exists() else _dump_compact({"name": "DLPSGame In-Place Edits", "version": 1, "packages": []})
        if not dest.exists():
            write_if_changed(dest, prev_bytes)
        prev_doc = _load_json(dest)
        return _merged_row(
            "dlps-edits",
            "DLPSGame in-place edits (direct hosters overlay, carried over)",
            "dlps-edits.json",
            "overlay-games",
            count_items(prev_doc),
            prev_bytes,
            f"{dlps_edits.WP_API_BASE}?categories={dlps_edits.PS5_CATEGORY_ID}&orderby=modified",
            False,
        )


def build_merged_games() -> dict[str, Any] | None:
    docs = []
    external_ids = {sid for _, sid in GAME_MERGE_ORDER}
    for filename, sid in GAME_OVERLAY_PREFIX + GAME_MERGE_ORDER + GAME_OVERLAY_SUFFIX:
        doc = _load_json(CATALOGS / filename)
        if isinstance(doc, dict) and doc.get("packages"):
            docs.append((sid, doc))
    if not docs:
        return None
    merged, stats = catalog_merge.merge_game_catalogs(docs, "AICyberGuardian PS5 Games (merged, deduped)")
    raw = _dump_compact(merged)
    changed = write_if_changed(CATALOGS / "games-merged.json", raw)
    print(f"[{'UPDT' if changed else 'SAME'}] games-merged.json {stats} bytes={len(raw)}")
    row = _merged_row(
        "games-merged", "Games merged (exact-URL deduped)", "games-merged.json", "merged-games",
        stats["packages_out"], raw, "merge of " + ",".join(s for s, _ in docs), changed,
    )
    row["replaces"] = [s for s, _ in docs if s in external_ids]
    row["overlays"] = [sid for _, sid in GAME_OVERLAY_PREFIX + GAME_OVERLAY_SUFFIX]
    return row


def build_merged_homebrew() -> dict[str, Any]:
    prev = (_load_json(CATALOGS / "homebrew-merged.json") or {}).get("packages", [])
    lists: dict[str, list[dict[str, Any]]] = {}

    prospero = _load_json(CATALOGS / "prosperostore.json")
    lists["prosperostore"] = catalog_merge.adapt_prospero(prospero) if isinstance(prospero, dict) else []
    jobee = _load_json(CATALOGS / "jobeeslair-homebrew.json")
    lists["jobeeslair"] = catalog_merge.adapt_jobee(jobee) if isinstance(jobee, dict) else []

    solanum = fetch_json_optional(SOLANUM_URL)
    lists["solanum"] = catalog_merge.adapt_solanum(solanum, SOLANUM_RAW_BASE) if isinstance(solanum, dict) else None
    recomp = fetch_json_optional(RECOMPSTORE_URL)
    lists["recompstore"] = catalog_merge.adapt_recompstore(recomp) if isinstance(recomp, dict) else None
    a_cat, a_rel = fetch_json_optional(ANCHOR_CATALOG_URL), fetch_json_optional(ANCHOR_RELEASES_URL)
    lists["anchorps5"] = (
        catalog_merge.adapt_anchorps5(a_cat, a_rel) if isinstance(a_cat, dict) and isinstance(a_rel, dict) else None
    )

    fallbacks = []
    for sid in ("prosperostore", "solanum", "recompstore", "anchorps5", "jobeeslair"):
        if lists.get(sid) is None or (sid in ("prosperostore", "jobeeslair") and not lists[sid]):
            lists[sid] = catalog_merge.previous_by_source(prev, sid)
            fallbacks.append(sid)
    ordered = [(sid, lists[sid]) for sid in ("prosperostore", "solanum", "recompstore", "anchorps5", "jobeeslair")]
    merged, stats = catalog_merge.merge_homebrew(ordered, "AICyberGuardian PS5 Homebrew (merged, one entry per repo)")
    stats["per_source_in"] = {sid: len(v) for sid, v in ordered}
    stats["carried_over"] = fallbacks
    raw = _dump_compact(merged)
    changed = write_if_changed(CATALOGS / "homebrew-merged.json", raw)
    print(f"[{'UPDT' if changed else 'SAME'}] homebrew-merged.json {stats} bytes={len(raw)}")
    row = _merged_row(
        "homebrew-merged", "Homebrew merged (one entry per repo)", "homebrew-merged.json", "merged-homebrew",
        stats["packages_out"], raw, "merge of " + ",".join(s for s, _ in ordered), changed,
    )
    row["replaces"] = [s for s, _ in ordered]
    return row


def build_merged_payloads() -> dict[str, Any]:
    prev = (_load_json(CATALOGS / "payloads-merged.json") or {}).get("payloads", [])
    ordered = []
    fallbacks = []
    for sid, url in PAYLOAD_SOURCES:
        doc = fetch_json_optional(url)
        items = doc.get("payloads") if isinstance(doc, dict) else None
        if not isinstance(items, list) or not items:
            items = catalog_merge.previous_by_source(prev, sid)
            fallbacks.append(sid)
        ordered.append((sid, items))
    merged, stats = catalog_merge.merge_payloads(ordered, "AICyberGuardian PS5 Payloads (merged, deduped)")
    stats["per_source_in"] = {sid: len(v) for sid, v in ordered}
    stats["carried_over"] = fallbacks
    raw = _dump_compact(merged)
    changed = write_if_changed(CATALOGS / "payloads-merged.json", raw)
    print(f"[{'UPDT' if changed else 'SAME'}] payloads-merged.json {stats} bytes={len(raw)}")
    row = _merged_row(
        "payloads-merged", "Payloads merged (Payload Manager format)", "payloads-merged.json", "merged-payloads",
        stats["payloads_out"], raw, "merge of " + ",".join(s for s, _ in ordered), changed,
    )
    row["replaces"] = [s for s, _ in ordered]
    return row


def _merged_manifest_entry(r: dict[str, Any], consumer: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r["id"],
        "name": r["name"],
        "url": f"{RAW_BASE}/{r['filename']}",
        "items": r["items"],
        "bytes": r["bytes"],
        "sha256": r["sha256"],
        "consumer": consumer,
        "replaces": r.get("replaces", []),
    }
    if r.get("overlays"):
        out["overlays"] = r["overlays"]
    return out


def write_merged_manifests(rows: list[dict[str, Any]]) -> bool:
    by_id = {r["id"]: r for r in rows if r.get("ok")}

    merged_sources = [
        _merged_manifest_entry(by_id[i], c)
        for i, c in (("games-merged", "ps5-library"), ("homebrew-merged", "mirror-only"), ("payloads-merged", "payload-manager"))
        if i in by_id
    ]
    payload_sources = [_merged_manifest_entry(by_id["payloads-merged"], "payload-manager")] if "payloads-merged" in by_id else []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged_doc = {
        "name": "AICyberGuardian PS5 Catalogs Hub - Merged (concise single-URL catalogs)",
        "version": "1.0.0",
        "note": (
            "Use ONE of: the individual game feeds in sources-games.json OR games-merged.json. "
            "Using both re-ingests the same data. homebrew-merged is a mirror (not a PS5 Library source)."
        ),
        "generatedAt": _preserve_generated_at(SOURCES_MERGED, "sources", merged_sources) or now,
        "rawBase": RAW_BASE,
        "sources": merged_sources,
    }
    payload_doc = {
        "name": "AICyberGuardian PS5 Catalogs Hub - Payloads",
        "version": "1.0.0",
        "kind": "payloads",
        "consumer": "payload-manager",
        "note": "Add the merged URL in Payload Manager (:8084) -> Settings -> Manage Sources. Browse/on-demand only.",
        "generatedAt": _preserve_generated_at(SOURCES_PAYLOADS, "sources", payload_sources) or now,
        "rawBase": RAW_BASE,
        "sources": payload_sources,
        "upstreams": [{"id": sid, "url": url} for sid, url in PAYLOAD_SOURCES],
    }
    changed = write_if_changed(SOURCES_MERGED, (json.dumps(merged_doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    changed |= write_if_changed(SOURCES_PAYLOADS, (json.dumps(payload_doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return changed


def main() -> int:
    CATALOGS.mkdir(parents=True, exist_ok=True)
    rows = sync_direct_feeds()
    rows.append(sync_jobee())
    merged_rows = []
    for builder in (build_dlps_edits_and_watchlist, build_merged_games, build_merged_homebrew, build_merged_payloads):
        row = builder()
        if row:
            merged_rows.append(row)
    write_manifests(rows)
    write_merged_manifests(merged_rows)
    write_report(rows + merged_rows)
    failures = sum(1 for r in rows if not r["ok"])
    print(
        f"manifests={SOURCES_GAMES.name},{SOURCES_HOMEBREW.name},{SOURCES_MANIFEST.name},"
        f"{SOURCES_MERGED.name},{SOURCES_PAYLOADS.name} failures={failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
