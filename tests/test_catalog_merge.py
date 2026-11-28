"""Offline unit tests for scripts/catalog_merge.py. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import catalog_hub_sync as chs  # noqa: E402
import catalog_merge as cm  # noqa: E402


def pkg(tid, urls, **kw):
    d = {"titleId": tid, "title": kw.pop("title", tid), "downloadLinks": [{"name": f"L{i}", "url": u} for i, u in enumerate(urls)]}
    d.update(kw)
    return d


class GameMergeTests(unittest.TestCase):
    def test_exact_url_dedupe_same_title_only(self):
        a = {"packages": [pkg("PPSA1", ["https://h/a", "https://h/b"])]}
        b = {"packages": [pkg("PPSA1", ["https://h/b", "https://h/c"]), pkg("PPSA2", ["https://h/b"])]}
        doc, st = cm.merge_game_catalogs([("a", a), ("b", b)], "m")
        urls = {p["titleId"]: [l["url"] for l in p["downloadLinks"]] for p in doc["packages"]}
        flat1 = [l["url"] for p in doc["packages"] if p["titleId"] == "PPSA1" for l in p["downloadLinks"]]
        self.assertEqual(sorted(flat1), ["https://h/a", "https://h/b", "https://h/c"])
        self.assertEqual(len(flat1), len(set(flat1)))
        # same URL under a DIFFERENT titleId must survive (title overlap != redundancy)
        self.assertEqual(urls["PPSA2"], ["https://h/b"])
        self.assertEqual(st["links_dropped"], 1)

    def test_drop_package_without_links_and_keep_mirrors(self):
        a = {"packages": [pkg("PPSA1", ["https://h/a"])]}
        b = {"packages": [pkg("PPSA1", ["https://h/a"]), pkg("PPSA1", ["https://mirror/a"])]}
        doc, st = cm.merge_game_catalogs([("a", a), ("b", b)], "m")
        self.assertEqual(st["packages_dropped"], 1)
        self.assertEqual(len(doc["packages"]), 2)

    def test_compact_strips_internal_and_empty(self):
        p = pkg("PPSA1", ["https://h/a"], _enrichedAt="x", version=None, posterUrl="p", originalPosterUrl="p", description="")
        q = cm.compact_package(p)
        self.assertNotIn("_enrichedAt", q)
        self.assertNotIn("version", q)
        self.assertNotIn("originalPosterUrl", q)
        self.assertNotIn("description", q)
        self.assertIn("downloadLinks", q)

    def test_compact_keeps_required_keys_even_when_blank(self):
        q = cm.compact_package({"titleId": "", "title": "", "downloadLinks": [{"url": "u"}], "version": ""})
        self.assertEqual(q["titleId"], "")
        self.assertIn("title", q)
        self.assertNotIn("version", q)


class HomebrewTests(unittest.TestCase):
    def test_repo_slug(self):
        self.assertEqual(cm.repo_slug("https://github.com/Owner/Repo.git"), "owner/repo")
        self.assertEqual(cm.repo_slug("Owner/Repo"), "owner/repo")
        self.assertEqual(cm.repo_slug("https://example.com/x"), "")

    def test_prospero_adapter(self):
        doc = {"apps": [{"titleid": "PPSA99000", "name": "Store", "artifact_url": "https://github.com/o/r/releases/download/v1/PPSA99000.zip",
                         "sha256": "ab", "source_repo": "https://github.com/o/r", "version": "1"}, {"name": "no url"}]}
        out = cm.adapt_prospero(doc)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["repo"], "o/r")
        self.assertEqual(out[0]["checksum"], "ab")

    def test_recomp_adapter_latest_url_and_explicit(self):
        doc = {"apps": [{"id": "PPSA92001", "name": "A", "source": {"type": "github", "repo": "o/A", "asset": "PPSA92001.zip"}}],
               "v2Apps": [{"id": "PPSA92002", "name": "B", "url": "https://x/y/B.zip", "sha256": "ff", "source": {"type": "github", "repo": "o/B", "asset": "B.zip"}},
                          {"id": "PPSA92003", "name": "C", "source": {"type": "other"}}]}
        out = {p["titleId"]: p for p in cm.adapt_recompstore(doc)}
        self.assertEqual(set(out), {"PPSA92001", "PPSA92002"})
        self.assertEqual(out["PPSA92001"]["downloadLinks"][0]["url"], "https://github.com/o/a/releases/latest/download/PPSA92001.zip")
        self.assertNotIn("checksum", out["PPSA92001"])
        self.assertEqual(out["PPSA92002"]["checksum"], "ff")

    def test_solanum_adapter(self):
        doc = {"apps": [{"id": "x", "name": "X", "title_id": "PPSA1", "repo": "O/X", "icon": {"path": "icons/x.png"},
                         "release": {"tag": "v1", "asset": "X.zip", "sha256": "aa", "content_version": "01.000.000"}},
                        {"id": "y", "name": "Y", "repo": "O/Y"}]}
        out = cm.adapt_solanum(doc, "https://raw/base")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["downloadLinks"][0]["url"], "https://github.com/o/x/releases/download/v1/X.zip")
        self.assertEqual(out[0]["posterUrl"], "https://raw/base/icons/x.png")

    def test_anchor_adapter_prunes_dead_and_matches_assets(self):
        cat = {"apps": [
            {"id": "github:o/live", "name": "Live", "repo": "o/Live", "description": {"en": "d"}, "assets": [{"match": "*.zip", "label": {"en": "App"}}, {"match": "*.elf"}]},
            {"id": "github:o/dead", "name": "Dead", "repo": "o/dead", "assets": [{"match": "*.zip"}]},
            {"id": "github:o/norel", "name": "NoAsset", "repo": "o/noasset", "assets": [{"match": "*.ffpfsc"}]},
        ]}
        rel = {"repos": {"o/live": [
            {"tag_name": "0.9", "prerelease": True, "published_at": "2026-02-01", "assets": [{"name": "pre.zip", "browser_download_url": "https://pre"}]},
            {"tag_name": "0.8", "prerelease": False, "published_at": "2026-01-01", "assets": [
                {"name": "Live.ZIP", "browser_download_url": "https://dl/Live.zip", "digest": "sha256:abc"},
                {"name": "live.elf", "browser_download_url": "https://dl/live.elf"}]}],
            "o/noasset": [{"tag_name": "1", "published_at": "2026-01-01", "assets": [{"name": "x.zip", "browser_download_url": "https://x"}]}]}}
        out = cm.adapt_anchorps5(cat, rel)
        self.assertEqual([p["title"] for p in out], ["Live"])  # dead repo + no matching asset pruned
        self.assertEqual(out[0]["version"], "0.8")  # stable preferred over newer prerelease
        self.assertEqual(len(out[0]["downloadLinks"]), 2)
        self.assertEqual(out[0]["checksum"], "abc")

    def test_merge_homebrew_priority_and_sources(self):
        a = [{"titleId": "PPSA1", "title": "Zed", "repo": "o/z", "downloadSource": "https://github.com/o/z", "downloadLinks": [{"url": "u1"}]}]
        b = [{"titleId": "HBZ", "title": "Zed2", "repo": "o/z", "downloadLinks": [{"url": "u2"}]},
             {"titleId": "HBA", "title": "Alpha", "repo": "o/a", "downloadLinks": [{"url": "u3"}]}]
        doc, st = cm.merge_homebrew([("prospero", a), ("jobee", b)], "m")
        self.assertEqual([p["title"] for p in doc["packages"]], ["Alpha", "Zed"])
        z = doc["packages"][1]
        self.assertEqual(z["titleId"], "PPSA1")
        self.assertEqual(z["sources"], ["prospero", "jobee"])
        self.assertEqual(st["repo_duplicates_merged"], 1)

    def test_merge_homebrew_dedupes_identical_url_across_moved_repos(self):
        prospero = [{"titleId": "PPSA99004", "title": "ProsperoAI", "repo": "quatrixone/prosperoai",
                     "downloadSource": "https://github.com/quatrixone/prosperoai",
                     "downloadLinks": [{"url": "https://github.com/quatrixone/ProsperoAI/releases/download/01.007.000/PPSA99004.zip"}]}]
        anchor = [{"titleId": "HBOLD", "title": "ProsperoAI", "repo": "blackbearreloaded/prosperoai",
                   "downloadSource": "https://github.com/blackbearreloaded/prosperoai",
                   "downloadLinks": [{"url": "https://github.com/quatrixone/ProsperoAI/releases/download/01.007.000/PPSA99004.zip"}]}]
        doc, st = cm.merge_homebrew([("prosperostore", prospero), ("anchorps5", anchor)], "m")
        self.assertEqual(len(doc["packages"]), 1)
        self.assertEqual(doc["packages"][0]["repo"], "quatrixone/prosperoai")
        self.assertEqual(doc["packages"][0]["sources"], ["prosperostore", "anchorps5"])
        self.assertEqual(st["repo_duplicates_merged"], 1)

    def test_carry_over_for_failed_source(self):
        prev = [{"title": "A", "repo": "o/a", "sources": ["prospero", "recompstore"], "downloadLinks": [{"url": "u"}]},
                {"title": "B", "repo": "o/b", "sources": ["jobeeslair"], "downloadLinks": [{"url": "v"}]}]
        got = cm.previous_by_source(prev, "recompstore")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["sources"], ["recompstore"])


class PayloadTests(unittest.TestCase):
    def test_dedupe_url_then_name_version(self):
        atlas = [{"name": "elfldr", "version": "v1", "url": "https://a/elfldr.elf"}]
        other = [{"name": "ElfLdr", "version": "V1", "url": "https://mirror/elfldr.elf"},
                 {"name": "x", "version": "1", "url": "https://a/elfldr.elf"},
                 {"name": "etaHEN", "version": "2", "url": "https://e/etahen.bin"},
                 {"name": "bad", "version": "1"}]
        doc, st = cm.merge_payloads([("atlas", atlas), ("other", other)], "m")
        self.assertEqual([p["name"] for p in doc["payloads"]], ["elfldr", "etaHEN"])
        self.assertEqual(st["duplicates_dropped"], 2)
        self.assertEqual(doc["payloads"][0]["sources"], ["atlas"])


class HubConfigTests(unittest.TestCase):
    def test_game_feeds_and_merge_order_stay_in_sync(self):
        game_feeds = {(f.filename, f.source_id) for f in chs.FEEDS if f.kind == "game"}
        homebrew_feeds = {(f.filename, f.source_id) for f in chs.FEEDS if f.kind == "homebrew"}
        merge_feeds = set(chs.GAME_MERGE_ORDER)
        self.assertEqual(game_feeds, merge_feeds)
        self.assertTrue(homebrew_feeds.isdisjoint(merge_feeds))
        self.assertIn(("padrino-store.json", "padrino-store"), merge_feeds)


if __name__ == "__main__":
    unittest.main()
