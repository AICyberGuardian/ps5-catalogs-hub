#!/usr/bin/env python3
"""Manage curated browser-resolved overrides in catalogs/manual-overrides.json.

Examples:
    python scripts/add_manual_override.py add \\
        --title-id PPSA02572 \\
        --title "Alan Wake 2 Deluxe Edition" \\
        --version 01.200.009 \\
        --region EUR \\
        --password DLPSGAME.COM \\
        --link "Akia=https://akirabox.com/.../file" \\
        --link "Viki=https://vikingfile.com/f/..."

    python scripts/add_manual_override.py list
    python scripts/add_manual_override.py remove --title-id PPSA02572 --version 01.200.009
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

Json = dict[str, Any]

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "catalogs" / "manual-overrides.json"
DEFAULT_NAME = "AICyberGuardian PS5 Manual Overrides"
TITLE_ID_RE = re.compile(r"^(PPSA|CUSA)\d{5}$")

BLOCKED_REDIRECT_HOSTS: tuple[str, ...] = (
    "downloadgameps3.net",
    "downloadgameps3.com",
    "dlpsgame.com",
    "clk.sh",
    "ouo.io",
    "ouo.press",
    "shrinkearn.com",
    "linkvertise.com",
)


def validate_title_id(title_id: str) -> str:
    tid = title_id.strip().upper()
    if not TITLE_ID_RE.fullmatch(tid):
        raise ValueError(f"Invalid titleId {title_id!r}: expected PPSA##### or CUSA#####")
    return tid


def parse_link_arg(spec: str) -> dict[str, str]:
    raw = spec.strip()
    if "=" in raw and not raw.startswith(("http://", "https://")):
        name, url = raw.split("=", 1)
        name = name.strip()
        url = url.strip()
    else:
        url = raw
        name = ""

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid HTTP(S) download URL: {url!r}")
    host = parsed.hostname.lower()
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_REDIRECT_HOSTS):
        raise ValueError(
            f"Refusing redirector/shortener URL {url!r} ({host}); paste the resolved file-hoster URL instead."
        )
    if not name:
        name = host.removeprefix("www.")
    return {"name": name, "url": url}


def load_overrides(path: Path) -> Json:
    if not path.exists():
        return {"name": DEFAULT_NAME, "version": 1, "packages": []}
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or not isinstance(doc.get("packages"), list):
        raise ValueError(f"Malformed overrides catalog: {path}")
    return doc


def save_overrides(path: Path, doc: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def upsert_override(
    doc: Json,
    *,
    title_id: str,
    title: str,
    version: str,
    links: list[dict[str, str]],
    region: str = "",
    password: str = "",
    notes: str = "",
    poster_url: str = "",
    download_source: str = "",
) -> Json:
    tid = validate_title_id(title_id)
    ver = version.strip().lstrip("vV")
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title must not be empty")
    if not links:
        raise ValueError("at least one validated --link is required")

    # Re-validate every link defensively
    validated_links = [parse_link_arg(f"{l['name']}={l['url']}" if l.get("name") else l["url"]) for l in links]

    desc_parts = ["Manual override"]
    if region.strip():
        desc_parts.append(f"Region: {region.strip().upper()}")
    if password.strip():
        desc_parts.append(f"Password: {password.strip()}")
    if notes.strip():
        desc_parts.append(notes.strip())

    packages = [dict(p) for p in doc.get("packages", [])]
    existing = next(
        (p for p in packages if str(p.get("titleId") or "").upper() == tid and str(p.get("version") or "").lstrip("vV") == ver),
        None,
    )

    if existing is not None:
        existing["title"] = clean_title
        existing["description"] = " | ".join(desc_parts)
        if poster_url.strip():
            existing["posterUrl"] = poster_url.strip()
        if download_source.strip():
            existing["downloadSource"] = download_source.strip()
        seen = {str(l.get("url") or "").strip() for l in existing.get("downloadLinks") or []}
        merged_links = list(existing.get("downloadLinks") or [])
        for link in validated_links:
            if link["url"] not in seen:
                seen.add(link["url"])
                merged_links.append(link)
        existing["downloadLinks"] = merged_links
    else:
        entry: Json = {
            "titleId": tid,
            "title": clean_title,
            "category": "game",
            "description": " | ".join(desc_parts),
            "downloadLinks": validated_links,
        }
        if ver:
            entry["version"] = ver
        if poster_url.strip():
            entry["posterUrl"] = poster_url.strip()
        if download_source.strip():
            entry["downloadSource"] = download_source.strip()
        packages.append(entry)

    packages.sort(key=lambda p: (str(p.get("titleId") or ""), str(p.get("version") or ""), str(p.get("title") or "").lower()))
    return {"name": doc.get("name") or DEFAULT_NAME, "version": 1, "packages": packages}


def remove_override(doc: Json, *, title_id: str, version: str | None = None) -> tuple[Json, int]:
    tid = validate_title_id(title_id)
    ver = version.strip().lstrip("vV") if version else None
    kept: list[Json] = []
    removed = 0
    for p in doc.get("packages", []):
        p_tid = str(p.get("titleId") or "").upper()
        p_ver = str(p.get("version") or "").lstrip("vV")
        if p_tid == tid and (ver is None or p_ver == ver):
            removed += 1
            continue
        kept.append(p)
    return {"name": doc.get("name") or DEFAULT_NAME, "version": 1, "packages": kept}, removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage catalogs/manual-overrides.json")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="Path to manual-overrides.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add or update a manual override entry")
    p_add.add_argument("--title-id", required=True, help="PS5/PS4 Title ID (e.g. PPSA02572)")
    p_add.add_argument("--title", required=True, help="Display title")
    p_add.add_argument("--version", default="", help="Package version (e.g. 01.200.009)")
    p_add.add_argument("--region", default="", help="Region code (EUR/USA/JPN/ASIA)")
    p_add.add_argument("--password", default="", help="Archive password if required")
    p_add.add_argument("--notes", default="", help="Optional release notes")
    p_add.add_argument("--poster-url", default="", help="Optional cover image URL")
    p_add.add_argument("--source-url", default="", help="Optional upstream reference post URL")
    p_add.add_argument("--link", action="append", required=True, help="Label=URL or bare URL (repeatable)")

    p_rm = sub.add_parser("remove", help="Remove manual override entry")
    p_rm.add_argument("--title-id", required=True)
    p_rm.add_argument("--version", default=None)

    sub.add_parser("list", help="List manual override entries")

    args = parser.parse_args(argv)
    try:
        doc = load_overrides(args.file)
        if args.cmd == "add":
            parsed_links = [parse_link_arg(spec) for spec in args.link]
            updated = upsert_override(
                doc,
                title_id=args.title_id,
                title=args.title,
                version=args.version,
                links=parsed_links,
                region=args.region,
                password=args.password,
                notes=args.notes,
                poster_url=args.poster_url,
                download_source=args.source_url,
            )
            save_overrides(args.file, updated)
            print(f"saved {args.file} (packages={len(updated['packages'])})")
            return 0
        if args.cmd == "remove":
            updated, count = remove_override(doc, title_id=args.title_id, version=args.version)
            save_overrides(args.file, updated)
            print(f"removed {count} entry/entries from {args.file} (packages={len(updated['packages'])})")
            return 0
        if args.cmd == "list":
            pkgs = doc.get("packages", [])
            if not pkgs:
                print("(no manual overrides)")
            for p in pkgs:
                print(f"{p.get('titleId')} | v{p.get('version') or '-'} | {p.get('title')} ({len(p.get('downloadLinks') or [])} links)")
            return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
