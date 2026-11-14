#!/usr/bin/env python3
"""Adapt JVK3R/JobeesLair-Homebrew index.json into Pegasus/PS5 Library schema."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://raw.githubusercontent.com/JVK3R/JobeesLair-Homebrew/main/index.json"
USER_AGENT = "ps5-catalogs-hub/1.0 (+https://github.com/AICyberGuardian/ps5-catalogs-hub)"


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slug_title_id(app_id: str, index: int) -> str:
    """Generate a stable non-colliding homebrew slug for catalogs lacking Title IDs."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", app_id)[:18].upper() or f"APP{index:04d}"
    return f"HB{cleaned[:16]}"


def adapt(index: dict[str, Any]) -> dict[str, Any]:
    packages: list[dict[str, Any]] = []
    apps = index.get("apps") or []
    for i, app in enumerate(apps):
        if not isinstance(app, dict):
            continue
        files = app.get("files") or []
        links = []
        for f in files:
            if not isinstance(f, dict):
                continue
            url = f.get("url")
            if not url:
                continue
            name = f.get("name") or Path(str(url)).name
            kind = f.get("kind") or "file"
            links.append({"name": f"{name} ({kind})", "url": url})
        if not links:
            continue
        release = app.get("release") or {}
        version = release.get("tag") or app.get("version") or "unknown"
        packages.append(
            {
                "titleId": slug_title_id(str(app.get("id") or app.get("name") or i), i),
                "title": app.get("name") or app.get("id") or f"homebrew-{i}",
                "version": version,
                "category": app.get("category") or "homebrew",
                "posterUrl": app.get("icon") or "",
                "originalPosterUrl": app.get("hero") or app.get("icon") or "",
                "description": app.get("description") or app.get("about") or "",
                "downloadSource": (
                    f"https://github.com/{app['repo']}"
                    if app.get("repo")
                    else index.get("source") or DEFAULT_URL
                ),
                "downloadLinks": links,
                "author": app.get("author") or "",
                "repo": app.get("repo") or "",
                "upstreamId": app.get("id") or "",
            }
        )

    return {
        "name": "Jobee'sLair Homebrew (adapted)",
        "version": "1.0.0",
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": DEFAULT_URL,
        "packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "catalogs" / "jobeeslair-homebrew.json",
    )
    args = parser.parse_args()
    adapted = adapt(fetch_json(args.url))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(adapted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} packages={len(adapted['packages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
