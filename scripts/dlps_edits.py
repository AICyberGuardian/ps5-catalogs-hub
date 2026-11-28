#!/usr/bin/env python3
"""Zero-bypass incremental delta overlay & watchlist for in-place dlpsgame.com PS5 post edits.

Reads only the public dlpsgame.com WordPress REST API (HTTP 200, no anti-bot bypass) ordered by
`modified desc`. Extracts direct file-hoster links from base64 `.secure-data` blocks, emits a
compact Pegasus-schema delta catalog containing only net-new `(titleId, url)` pairs missing from
`catalogs/dlps.json`, and builds an idempotent Markdown watchlist (`DLPS_EDITS.md`) for posts
whose latest blocks remain gated behind `downloadgameps3.net` redirector pages.
"""

from __future__ import annotations

import base64
import html as htmllib
import json
import re
import urllib.parse
import urllib.request
from typing import Any

Json = dict[str, Any]

WP_API_BASE = "https://dlpsgame.com/wp-json/wp/v2/posts"
PS5_CATEGORY_ID = 63019
USER_AGENT = "ps5-catalogs-hub/1.0 (+https://github.com/AICyberGuardian/ps5-catalogs-hub)"

TITLE_ID_RE = re.compile(r"\b((?:PPSA|CUSA)\d{5})\b", re.I)
VERSION_RE = re.compile(r"\bv?(\d{1,2}\.\d{2,3}(?:\.\d{3})?)\b", re.I)
REGION_RE = re.compile(r"\b(EUR|USA|JPN|ASIA)\b")
PASSWORD_RE = re.compile(r"pass?word\s*[:：]\s*[\(\[\s]*([^\s\)\]<,]+)", re.I)
PAYLOAD_TAG_RE = re.compile(r'<div[^>]+class="[^"]*secure-data[^"]*"[^>]+data-payload="([A-Za-z0-9+/=\s_-]+)"', re.I)
ANCHOR_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
TAG_RE = re.compile(r"<[^>]+>")

DIRECT_HOST_SUFFIXES: tuple[str, ...] = (
    "akirabox.com",
    "akirabox.to",
    "vikingfile.com",
    "vik1ngfile.site",
    "vik1ngf1le.online",
    "datanodes.to",
    "datanodes.co",
    "filekeeper.net",
    "datavaults.co",
    "buzzheavier.com",
    "1fichier.com",
    "mediafire.com",
    "rootz.so",
    "gofile.io",
    "ranoz.gg",
    "mega.nz",
    "mega.co.nz",
    "archive.org",
    "transfer.it",
    "pixeldrain.com",
    "fuckingfast.co",
    "fuckingfast.net",
    "1cloudfile.com",
    "fileditchfiles.st",
)

GATED_REDIRECT_HOSTS: tuple[str, ...] = ("downloadgameps3.net",)


def _hostname(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_direct_host_url(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    host = _hostname(url)
    if not host:
        return False
    return any(host == dom or host.endswith("." + dom) for dom in DIRECT_HOST_SUFFIXES)


def is_gated_redirect_url(url: str) -> bool:
    host = _hostname(url)
    return any(host == dom or host.endswith("." + dom) for dom in GATED_REDIRECT_HOSTS)


def _strip_html(raw: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(TAG_RE.sub(" ", raw))).strip()


def _decode_payload(payload: str) -> str:
    cleaned = re.sub(r"\s+", "", payload)
    padded = cleaned + "=" * (-len(cleaned) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(padded).decode("utf-8", errors="replace")
        except Exception:
            continue
    return ""


def _normalize_version(v: str) -> str:
    return v.strip().lstrip("vV")


def _extract_version(text: str) -> str:
    # Prefer 3-part PS5 version strings (e.g. 01.200.009) over 2-part firmware notes (e.g. 9.00, 4.03)
    all_vers = VERSION_RE.findall(text)
    if not all_vers:
        return ""
    three_part = [v for v in all_vers if v.count(".") == 2]
    if three_part:
        return _normalize_version(three_part[0])
    # Filter out obvious firmware strings like "4.03" or "9.00" when preceded by "works on" / "fw"
    for v in all_vers:
        if not re.search(rf"(?:works\s+on|fw|firmware|backport|bp)\s*[:\-]?\s*v?{re.escape(v)}", text, re.I):
            return _normalize_version(v)
    return _normalize_version(all_vers[0])


def _extract_poster(content_html: str) -> str:
    for src in IMG_RE.findall(content_html):
        s = src.strip()
        if s.startswith(("http://", "https://")) and not any(
            skip in s.lower() for skip in ("gravatar", "emoji", "icon", "ads", "doubleclick")
        ):
            return s
    return ""


def _host_label(url: str, link_text: str) -> str:
    txt = _strip_html(link_text)
    host = _hostname(url).removeprefix("www.")
    if txt and txt.lower() not in ("here", "download", "link", "mirror"):
        return txt
    return host or "Mirror"


def parse_wp_post(post: Json) -> Json:
    """Parse one WP REST API post into per-block structured metadata and links."""
    raw_title = (post.get("title") or {}).get("rendered") if isinstance(post.get("title"), dict) else str(post.get("title") or "")
    title = _strip_html(raw_title)
    content = (post.get("content") or {}).get("rendered") if isinstance(post.get("content"), dict) else str(post.get("content") or "")
    post_url = str(post.get("link") or "").strip()
    slug = str(post.get("slug") or "").strip()
    published = str(post.get("date") or "")[:10]
    modified = str(post.get("modified") or "")[:10]
    poster = _extract_poster(content)

    # Fallback post-wide Title ID (only used if neither block nor preceding heading specifies one)
    post_tids = [m.upper() for m in TITLE_ID_RE.findall(content)]
    fallback_tid = post_tids[0] if post_tids else ""

    blocks: list[Json] = []
    for match in PAYLOAD_TAG_RE.finditer(content):
        preceding = _strip_html(content[max(0, match.start() - 300) : match.start()])
        decoded_html = _decode_payload(match.group(1))
        decoded_text = _strip_html(decoded_html)

        tids_block = [m.upper() for m in TITLE_ID_RE.findall(decoded_text)]
        tids_pre = [m.upper() for m in TITLE_ID_RE.findall(preceding)]
        title_id = tids_block[0] if tids_block else (tids_pre[-1] if tids_pre else fallback_tid)

        version = _extract_version(decoded_text) or _extract_version(preceding)
        reg_m = REGION_RE.search(decoded_text) or REGION_RE.search(preceding)
        region = reg_m.group(1) if reg_m else ""
        pw_m = PASSWORD_RE.search(decoded_text)
        password = pw_m.group(1).strip("()[]") if pw_m else ""

        direct_links: list[Json] = []
        seen_urls: set[str] = set()
        gated_count = 0
        for href, anchor_txt in ANCHOR_RE.findall(decoded_html):
            url = htmllib.unescape(href).strip()
            if not url:
                continue
            if is_gated_redirect_url(url):
                gated_count += 1
                continue
            if is_direct_host_url(url) and url not in seen_urls:
                seen_urls.add(url)
                label_parts = [p for p in (region, f"v{version}" if version else "", _host_label(url, anchor_txt)) if p]
                direct_links.append({"name": " - ".join(label_parts), "url": url})

        blocks.append(
            {
                "titleId": title_id,
                "version": version,
                "region": region,
                "password": password,
                "directLinks": direct_links,
                "gatedCount": gated_count,
            }
        )

    return {
        "slug": slug,
        "title": title,
        "postUrl": post_url,
        "published": published,
        "modified": modified,
        "posterUrl": poster,
        "blocks": blocks,
    }


def _baseline_index(docs: Json | list[Json | None] | None) -> tuple[dict[str, set[str]], dict[str, str], dict[str, set[str]]]:
    urls_by_tid: dict[str, set[str]] = {}
    posters_by_tid: dict[str, str] = {}
    versions_by_tid: dict[str, set[str]] = {}
    doc_list = docs if isinstance(docs, list) else ([docs] if isinstance(docs, dict) else [])
    for doc in doc_list:
        if not isinstance(doc, dict):
            continue
        for pkg in doc.get("packages") or []:
            if not isinstance(pkg, dict):
                continue
            tid = str(pkg.get("titleId") or "").upper()
            if not tid:
                continue
            if pkg.get("posterUrl") and tid not in posters_by_tid:
                posters_by_tid[tid] = str(pkg["posterUrl"])
            ver = _normalize_version(str(pkg.get("version") or ""))
            if ver:
                versions_by_tid.setdefault(tid, set()).add(ver)
            desc = str(pkg.get("description") or "")
            for v in VERSION_RE.findall(desc):
                versions_by_tid.setdefault(tid, set()).add(_normalize_version(v))
            for link in pkg.get("downloadLinks") or []:
                if isinstance(link, dict) and link.get("url"):
                    urls_by_tid.setdefault(tid, set()).add(str(link["url"]).strip())
    return urls_by_tid, posters_by_tid, versions_by_tid


def build_dlps_edits(
    posts: list[Json],
    baseline_docs: Json | list[Json | None] | None,
    manual_overrides: Json | None = None,
    *,
    name: str = "DLPSGame In-Place Edits (direct hosters overlay)",
    max_watch_rows: int = 50,
) -> tuple[Json, list[Json], Json]:
    """Build delta overlay catalog + edited-posts watchlist from WP REST API posts."""
    base_urls, base_posters, base_versions = _baseline_index(baseline_docs)
    _, _, override_versions = _baseline_index(manual_overrides)

    # Group net-new direct links by (titleId, version) so each overlay package is clean and scoped
    grouped: dict[tuple[str, str], Json] = {}
    seen_overlay_urls: dict[str, set[str]] = {}
    watch_rows: list[Json] = []
    stats = {"posts_scanned": len(posts), "edited_posts": 0, "new_direct_links": 0, "needs_manual": 0, "partial": 0}

    for raw_post in posts:
        parsed = parse_wp_post(raw_post)
        is_edit = bool(parsed["published"] and parsed["modified"] and parsed["published"] != parsed["modified"])
        post_new_direct = 0
        post_tids: list[str] = []

        for block in parsed["blocks"]:
            tid = block["titleId"]
            if not tid:
                continue
            if tid not in post_tids:
                post_tids.append(tid)
            ver = block["version"]
            new_links: list[Json] = []
            for link in block["directLinks"]:
                u = link["url"]
                if u in base_urls.get(tid, set()) or u in seen_overlay_urls.get(tid, set()):
                    continue
                seen_overlay_urls.setdefault(tid, set()).add(u)
                new_links.append(link)
            if new_links:
                post_new_direct += len(new_links)
                stats["new_direct_links"] += len(new_links)
                key = (tid, ver)
                if key not in grouped:
                    desc_parts = [f"Edited on dlpsgame.com ({parsed['modified']})"]
                    if block["region"]:
                        desc_parts.append(f"Region: {block['region']}")
                    if block["password"]:
                        desc_parts.append(f"Password: {block['password']}")
                    pkg: Json = {
                        "titleId": tid,
                        "title": parsed["title"] or tid,
                        "category": "game",
                        "downloadSource": parsed["postUrl"],
                        "description": " | ".join(desc_parts),
                        "downloadLinks": list(new_links),
                    }
                    if ver:
                        pkg["version"] = ver
                    poster = base_posters.get(tid) or parsed["posterUrl"]
                    if poster:
                        pkg["posterUrl"] = poster
                    grouped[key] = pkg
                else:
                    grouped[key]["downloadLinks"].extend(new_links)

        if is_edit and parsed["blocks"]:
            stats["edited_posts"] += 1
            top = parsed["blocks"][0]
            top_tid = top["titleId"] or (post_tids[0] if post_tids else "")
            top_ver = top["version"]
            top_gated = top["gatedCount"]
            has_override = bool(top_tid and top_ver and top_ver in override_versions.get(top_tid, set()))
            in_baseline = bool(top_tid and top_ver and top_ver in base_versions.get(top_tid, set()))
            if has_override:
                status = "OVERRIDDEN"
            elif top_gated > 0 and not top["directLinks"] and not in_baseline:
                if post_new_direct > 0:
                    status = "PARTIAL"
                    stats["partial"] += 1
                else:
                    status = "NEEDS_MANUAL"
                    stats["needs_manual"] += 1
            elif post_new_direct > 0:
                status = "AUTO_ADDED"
            else:
                status = "COVERED"

            watch_rows.append(
                {
                    "modified": parsed["modified"],
                    "published": parsed["published"],
                    "titleIds": post_tids or ([top_tid] if top_tid else []),
                    "title": parsed["title"] or parsed["slug"],
                    "slug": parsed["slug"],
                    "postUrl": parsed["postUrl"],
                    "latestVersion": top_ver,
                    "autoDirectNew": post_new_direct,
                    "gatedLinks": top_gated,
                    "status": status,
                }
            )

    packages = sorted(
        grouped.values(),
        key=lambda p: (str(p.get("titleId") or ""), str(p.get("version") or ""), str(p.get("title") or "").lower()),
    )
    watch_rows.sort(key=lambda r: (r["modified"], r["slug"]), reverse=True)
    watch_rows = watch_rows[:max_watch_rows]
    stats["packages_out"] = len(packages)
    return {"name": name, "version": 1, "packages": packages}, watch_rows, stats


def render_watchlist_markdown(rows: list[Json], *, generated_at: str) -> str:
    needs = sum(1 for r in rows if r["status"] == "NEEDS_MANUAL")
    partial = sum(1 for r in rows if r["status"] == "PARTIAL")
    auto = sum(1 for r in rows if r["status"] == "AUTO_ADDED")
    overridden = sum(1 for r in rows if r["status"] == "OVERRIDDEN")
    lines = [
        "# DLPSGame In-Place Edits Watchlist",
        "",
        f"Generated: {generated_at}",
        (
            f"Tracked recent edits: {len(rows)} (`NEEDS_MANUAL`: {needs}, `PARTIAL`: {partial}, "
            f"`AUTO_ADDED`: {auto}, `OVERRIDDEN`: {overridden})"
        ),
        "",
        "Posts modified after initial publication on `dlpsgame.com`, checked against all 8 synced game feeds.",
        "Net-new direct file-hoster links are auto-captured into `catalogs/dlps-edits.json` and merged into",
        "`catalogs/games-merged.json`. Rows marked `NEEDS_MANUAL` (or `PARTIAL`) have a latest block gated",
        "behind `downloadgameps3.net` — resolve in your browser and add via `python scripts/add_manual_override.py add ...`.",
        "",
        "| Modified | Published | Title ID(s) | Title | Latest Version | Auto Direct (+new) | Gated Redirects | Status | Post |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for r in rows:
        tids = ", ".join(f"`{t}`" for t in r["titleIds"]) or "-"
        ver = f"`{r['latestVersion']}`" if r["latestVersion"] else "-"
        safe_title = str(r["title"]).replace("|", "/")
        lines.append(
            f"| {r['modified']} | {r['published']} | {tids} | {safe_title} | {ver} | "
            f"{r['autoDirectNew']} | {r['gatedLinks']} | `{r['status']}` | [dlps]({r['postUrl']}) |"
        )
    return "\n".join(lines) + "\n"


def _strip_generated_line(md: str) -> str:
    return "\n".join(line for line in md.splitlines() if not line.startswith("Generated:"))


def watchlist_body_equal(existing_md: str, new_md: str) -> bool:
    """Compare two watchlist documents ignoring the volatile Generated timestamp line."""
    return _strip_generated_line(existing_md) == _strip_generated_line(new_md)


def fetch_modified_ps5_posts(
    *,
    pages: int = 2,
    per_page: int = 100,
    user_agent: str = USER_AGENT,
    timeout: int = 45,
) -> list[Json]:
    """Fetch recent modified PS5 posts from the open dlpsgame.com WordPress REST API."""
    posts: list[Json] = []
    for page in range(1, pages + 1):
        qs = urllib.parse.urlencode(
            {
                "categories": PS5_CATEGORY_ID,
                "orderby": "modified",
                "order": "desc",
                "per_page": per_page,
                "page": page,
                "_fields": "id,date,modified,slug,link,title,content",
            }
        )
        req = urllib.request.Request(f"{WP_API_BASE}?{qs}", headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not isinstance(batch, list) or not batch:
            break
        posts.extend(batch)
        if len(batch) < per_page:
            break
    return posts
