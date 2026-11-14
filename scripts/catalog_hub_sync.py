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

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "catalogs"
SOURCES_MANIFEST = ROOT / "sources.json"
REPORT = ROOT / "SYNC_REPORT.md"
USER_AGENT = "ps5-catalogs-hub/1.0 (+https://github.com/AICyberGuardian/ps5-catalogs-hub)"
RAW_BASE = "https://raw.githubusercontent.com/AICyberGuardian/ps5-catalogs-hub/main/catalogs"


@dataclass(frozen=True)
class Feed:
    filename: str
    source_id: str
    name: str
    urls: tuple[str, ...]
    description: str


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
    ),
    Feed(
        "blackbox_catalog.json",
        "evox-blackbox",
        "evoX BlackBox",
        (
            "https://raw.githubusercontent.com/nexgen999/evoX-CoreOS/main/json/pegasus-dl/blackbox_catalog.json",
        ),
        "Archive.org / Vikingfile direct mirrors",
    ),
    Feed(
        "jamzi94-ps5.json",
        "phoenix-dl-ps5",
        "Phoenix DL PS5 (Jamzi94)",
        ("https://raw.githubusercontent.com/Jamzi94/catalog-V2/main/ps5-catalog.json",),
        "Link-Vault / Rootz mirrors",
    ),
    Feed(
        "pegasus-ps4-catalog.json",
        "ps4-fpkg-collection-catalog",
        "PS4 FPKG Collection",
        (
            "https://raw.githubusercontent.com/M3hmetSa1t/pegasus-ps4-collection-catalog/main/pegasus-ps4-catalog.json",
        ),
        "Internet Archive clean base + updates",
    ),
    Feed(
        "homebrew-page.json",
        "homebrew-page",
        "PS5 Homebrew (homebrew.page)",
        (
            "https://homebrew.page/catalog/v1.json",
            # Host/router homebrew-isolation may sinkhole homebrew.page; ProsperoStore is the successor feed.
            "https://prosperostore.net/catalog/v1.json",
            "https://raw.githubusercontent.com/darkxex/ps5-homebrew-catalog/main/catalog/v1.json",
        ),
        "Official GitHub Releases homebrew catalog",
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
            "items": 0,
            "bytes": 0,
            "sha256": "",
            "upstream": DEFAULT_URL,
            "changed": False,
            "ok": False,
            "error": str(exc),
        }


def write_manifest(rows: list[dict[str, Any]]) -> bool:
    sources = []
    for row in rows:
        if not row["ok"]:
            continue
        sources.append(
            {
                "id": row["id"],
                "name": row["name"],
                "url": f"{RAW_BASE}/{row['filename']}",
                "items": row["items"],
                "sha256": row["sha256"],
                "upstream": row["upstream"],
            }
        )

    existing_gen_at = None
    if SOURCES_MANIFEST.exists():
        try:
            existing = json.loads(SOURCES_MANIFEST.read_text(encoding="utf-8"))
            if existing.get("sources") == sources and existing.get("generatedAt"):
                existing_gen_at = existing["generatedAt"]
        except Exception:
            pass

    manifest = {
        "name": "AICyberGuardian PS5 Catalogs Hub",
        "version": "1.0.0",
        "generatedAt": existing_gen_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rawBase": RAW_BASE,
        "sources": sources,
    }
    raw = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return write_if_changed(SOURCES_MANIFEST, raw)


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
        "| Source | Items | Changed | Status | Upstream |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for r in rows:
        status = "OK" if r["ok"] else f"FAIL: {r['error'][:80]}"
        lines.append(
            f"| `{r['id']}` | {r['items']} | {'yes' if r['changed'] else 'no'} | {status} | `{r['upstream']}` |"
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    CATALOGS.mkdir(parents=True, exist_ok=True)
    rows = sync_direct_feeds()
    rows.append(sync_jobee())
    write_manifest(rows)
    write_report(rows)
    failures = sum(1 for r in rows if not r["ok"])
    print(f"manifest={SOURCES_MANIFEST} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
