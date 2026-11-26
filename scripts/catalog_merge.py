#!/usr/bin/env python3
"""Pure adapt/merge helpers for ps5-catalogs-hub (no network, no filesystem; unit-testable).

Design rules (see docs/superpowers/specs):
* Games: only EXACT duplicate download URLs for the same titleId are removed. Title-ID overlap alone
  is never treated as redundancy (different hosts/mirrors are the point). Per-source package
  descriptions are kept untouched.
* Homebrew: one entry per GitHub repo (priority order decides which source's metadata wins).
* Payloads: Payload Manager format, deduped by exact URL, then by (name, version).
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Iterable

Json = dict[str, Any]

# Keys a Pegasus-schema consumer expects to exist even when blank (never stripped by compaction).
REQUIRED_KEYS = frozenset({"titleId", "title", "downloadLinks"})

GITHUB_SLUG_RE = re.compile(r"github\.com/([^/\s]+/[^/\s#?]+)", re.I)


def repo_slug(value: Any) -> str:
    """Lower-case ``owner/repo`` from a GitHub URL or slug; empty string if none."""
    if not value:
        return ""
    s = str(value).strip()
    m = GITHUB_SLUG_RE.search(s)
    if m:
        return m.group(1).removesuffix(".git").lower()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", s):
        return s.lower()
    return ""


def hb_slug_title_id(app_id: str, index: int) -> str:
    """Stable non-colliding homebrew slug for feeds lacking Title IDs (same rule as the Jobee adapter)."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", app_id)[:18].upper() or f"APP{index:04d}"
    return f"HB{cleaned[:16]}"


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def compact_package(pkg: Json) -> Json:
    """Drop internal ``_*`` bookkeeping, empty values and a poster duplicated in originalPosterUrl."""
    out = {k: v for k, v in pkg.items() if not k.startswith("_") and (k in REQUIRED_KEYS or not _empty(v))}
    if out.get("originalPosterUrl") == out.get("posterUrl"):
        out.pop("originalPosterUrl", None)
    return out


def _links(pkg: Json) -> list[Json]:
    return [l for l in (pkg.get("downloadLinks") or []) if isinstance(l, dict) and l.get("url")]


# --------------------------------------------------------------------------- games


def merge_game_catalogs(catalogs: Iterable[tuple[str, Json]], name: str) -> tuple[Json, Json]:
    """Merge Pegasus-schema game catalogs (priority = iteration order).

    Returns (document, stats). A link is dropped only when the exact same URL was already kept for
    the same titleId; a package left without links is dropped.
    """
    seen: dict[str, set[str]] = {}
    out: list[Json] = []
    stats = {"packages_in": 0, "links_in": 0, "links_dropped": 0, "packages_dropped": 0}
    for _sid, doc in catalogs:
        for pkg in doc.get("packages", []):
            stats["packages_in"] += 1
            tid = str(pkg.get("titleId") or "")
            urls = seen.setdefault(tid, set())
            kept: list[Json] = []
            for link in _links(pkg):
                stats["links_in"] += 1
                url = str(link["url"]).strip()
                if url in urls:
                    stats["links_dropped"] += 1
                    continue
                urls.add(url)
                kept.append(link)
            if not kept:
                stats["packages_dropped"] += 1
                continue
            new = compact_package(pkg)
            new["downloadLinks"] = kept
            out.append(new)
    stats["packages_out"] = len(out)
    stats["links_out"] = sum(len(p["downloadLinks"]) for p in out)
    return {"name": name, "version": 1, "packages": out}, stats


# --------------------------------------------------------------------------- homebrew adapters


def adapt_prospero(doc: Json) -> list[Json]:
    pkgs: list[Json] = []
    for a in doc.get("apps", []) or []:
        url = a.get("artifact_url")
        if not url:
            continue
        fname = str(url).rsplit("/", 1)[-1]
        pkgs.append(
            compact_package(
                {
                    "titleId": a.get("titleid") or "",
                    "title": a.get("name"),
                    "version": a.get("version"),
                    "category": a.get("category") or a.get("kind") or "homebrew",
                    "posterUrl": a.get("icon_url"),
                    "description": a.get("description"),
                    "downloadSource": a.get("source_repo"),
                    "downloadLinks": [{"name": f"{fname} (app)", "url": url}],
                    "author": a.get("author"),
                    "repo": repo_slug(a.get("source_repo")),
                    "checksum": a.get("sha256"),
                    "license": a.get("license"),
                    "sources": ["prosperostore"],
                }
            )
        )
    return pkgs


def adapt_recompstore(doc: Json) -> list[Json]:
    pkgs: list[Json] = []
    v2 = doc.get("v2Apps")
    apps = list(doc.get("apps", []) or []) + (list(v2) if isinstance(v2, list) else [])
    for a in apps:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        src = a.get("source") if isinstance(a.get("source"), dict) else {}
        repo = repo_slug(src.get("repo")) if src.get("type") == "github" else ""
        asset = src.get("asset")
        explicit = a.get("url") or ""
        if explicit:
            link_url, checksum = explicit, a.get("sha256")
            link_name = str(explicit).rsplit("/", 1)[-1] or "app"
        elif repo and asset:
            link_url = f"https://github.com/{repo}/releases/latest/download/{asset}"
            checksum, link_name = None, asset
        else:
            continue
        desc = a.get("blurb") or (a.get("description") or "")[:240]
        if a.get("needs"):
            desc = f"{desc} Needs: {a['needs']}".strip()
        pkgs.append(
            compact_package(
                {
                    "titleId": a["id"],
                    "title": a.get("name"),
                    "version": a.get("version"),
                    "category": a.get("category") or a.get("kind") or "homebrew",
                    "posterUrl": a.get("icon"),
                    "description": desc,
                    "downloadSource": f"https://github.com/{repo}" if repo else explicit,
                    "downloadLinks": [{"name": f"{link_name} (app)", "url": link_url}],
                    "author": a.get("author") or a.get("dev"),
                    "repo": repo,
                    "checksum": checksum,
                    "sources": ["recompstore"],
                }
            )
        )
    return pkgs


def adapt_solanum(doc: Json, raw_base: str) -> list[Json]:
    pkgs: list[Json] = []
    for a in doc.get("apps", []) or []:
        rel = a.get("release") or {}
        repo, tag, asset = repo_slug(a.get("repo")), rel.get("tag"), rel.get("asset")
        if not (repo and tag and asset):
            continue
        icon = a.get("icon") if isinstance(a.get("icon"), dict) else {}
        poster = f"{raw_base}/{icon['path']}" if icon.get("path") else None
        pkgs.append(
            compact_package(
                {
                    "titleId": a.get("title_id") or hb_slug_title_id(str(a.get("id") or repo), 0),
                    "title": a.get("name"),
                    "version": rel.get("content_version") or tag,
                    "category": a.get("category") or "homebrew",
                    "posterUrl": poster,
                    "description": a.get("summary"),
                    "downloadSource": f"https://github.com/{repo}",
                    "downloadLinks": [
                        {"name": f"{asset} (app)", "url": f"https://github.com/{repo}/releases/download/{tag}/{asset}"}
                    ],
                    "author": a.get("author"),
                    "repo": repo,
                    "checksum": rel.get("sha256"),
                    "license": a.get("license"),
                    "sources": ["solanum"],
                }
            )
        )
    return pkgs


def _loc(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("en") or next(iter(value.values()), "") or "")
    return str(value or "")


def adapt_anchorps5(catalog: Json, releases: Json) -> list[Json]:
    """AnchorPS5 resolves assets from its releases index; apps without a live release are pruned."""
    relmap = {str(k).lower(): v for k, v in (releases.get("repos") or {}).items()}
    pkgs: list[Json] = []
    for i, a in enumerate(catalog.get("apps", []) or []):
        repo = repo_slug(a.get("repo"))
        rels = [r for r in relmap.get(repo, []) if isinstance(r, dict) and not r.get("draft")]
        stable = [r for r in rels if not r.get("prerelease")]
        pool = sorted(stable or rels, key=lambda r: r.get("published_at") or "", reverse=True)
        if not pool:
            continue
        rel = pool[0]
        links: list[Json] = []
        used: set[str] = set()
        digest = ""
        for spec in a.get("assets", []) or []:
            pat = str(spec.get("match") or "*").lower()
            for asset in rel.get("assets", []) or []:
                name = str(asset.get("name") or "")
                url = asset.get("browser_download_url")
                if url and name.lower() not in used and fnmatch.fnmatch(name.lower(), pat):
                    used.add(name.lower())
                    label = _loc(spec.get("label"))
                    links.append({"name": f"{name} ({label})" if label else name, "url": url})
                    digest = digest or str(asset.get("digest") or "").removeprefix("sha256:")
                    break
        if not links:
            continue
        pkgs.append(
            compact_package(
                {
                    "titleId": hb_slug_title_id(repo or str(a.get("id") or ""), i),
                    "title": a.get("name"),
                    "version": rel.get("tag_name"),
                    "category": "homebrew",
                    "posterUrl": a.get("iconUrl"),
                    "description": _loc(a.get("description")),
                    "downloadSource": f"https://github.com/{repo}",
                    "downloadLinks": links,
                    "author": a.get("author"),
                    "repo": repo,
                    "checksum": digest,
                    "sources": ["anchorps5"],
                }
            )
        )
    return pkgs


def adapt_jobee(doc: Json) -> list[Json]:
    """Hub's adapted Jobee catalog is already Pegasus-shaped; just tag the source."""
    out = []
    for p in doc.get("packages", []) or []:
        q = compact_package(p)
        q["repo"] = repo_slug(q.get("repo") or q.get("downloadSource"))
        q["sources"] = ["jobeeslair"]
        out.append(compact_package(q))
    return out


def previous_by_source(prev_pkgs: Iterable[Json], source_id: str) -> list[Json]:
    """Carry-over: packages a failed source contributed to the previous merged output."""
    out = []
    for p in prev_pkgs:
        if source_id in (p.get("sources") or []):
            q = dict(p)
            q["sources"] = [source_id]
            out.append(q)
    return out


def merge_homebrew(ordered: Iterable[tuple[str, list[Json]]], name: str) -> tuple[Json, Json]:
    """One entry per GitHub repo or download URL (first source in priority order wins)."""
    by_key: dict[str, Json] = {}
    by_url: dict[str, str] = {}
    order: list[str] = []
    dup = 0
    url_dup = 0
    for sid, pkgs in ordered:
        for pkg in pkgs:
            slug = repo_slug(pkg.get("repo") or pkg.get("downloadSource"))
            key = f"repo:{slug}" if slug else f"id:{str(pkg.get('titleId') or '').lower()}:{str(pkg.get('title') or '').lower()}"
            urls = [str(l["url"]).strip() for l in _links(pkg)]
            matched_key = key if key in by_key else next((by_url[u] for u in urls if u in by_url), None)
            if matched_key is not None:
                dup += 1
                if key not in by_key:
                    url_dup += 1
                srcs = by_key[matched_key].setdefault("sources", [])
                if sid not in srcs:
                    srcs.append(sid)
                continue
            q = dict(pkg)
            q["sources"] = [sid]
            by_key[key] = q
            order.append(key)
            for u in urls:
                by_url.setdefault(u, key)
    packages = sorted(
        (by_key[k] for k in order),
        key=lambda p: (str(p.get("title") or "").lower(), str(p.get("titleId") or "")),
    )
    stats = {
        "packages_out": len(packages),
        "repo_duplicates_merged": dup,
        "url_duplicates_merged": url_dup,
    }
    return {"name": name, "version": 1, "packages": packages}, stats


# --------------------------------------------------------------------------- payloads


def merge_payloads(ordered: Iterable[tuple[str, list[Json]]], name: str) -> tuple[Json, Json]:
    """Payload Manager format. Dedupe by exact URL, then by (name, version); first source wins."""
    seen_url: set[str] = set()
    seen_nv: set[tuple[str, str]] = set()
    out: list[Json] = []
    dropped = 0
    for sid, items in ordered:
        for it in items:
            if not isinstance(it, dict) or not it.get("url"):
                continue
            url = str(it["url"]).strip()
            nv = (str(it.get("name") or it.get("filename") or "").strip().lower(), str(it.get("version") or "").strip().lower())
            if url in seen_url or (nv[0] and nv in seen_nv):
                dropped += 1
                continue
            seen_url.add(url)
            seen_nv.add(nv)
            q = dict(it)
            q["sources"] = [sid]
            out.append(q)
    out.sort(key=lambda p: (str(p.get("name") or "").lower(), str(p.get("version") or "")))
    return {"name": name, "payloads": out}, {"payloads_out": len(out), "duplicates_dropped": dropped}
