"""Offline unit tests for scripts/dlps_edits.py. Run: python -m unittest tests/test_dlps_edits.py -v"""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dlps_edits as de  # noqa: E402


def _b64(html_str: str) -> str:
    return base64.b64encode(html_str.encode("utf-8")).decode("ascii")


def _wp_post(
    *,
    slug: str,
    title: str,
    date: str,
    modified: str,
    blocks: list[tuple[str, str]],
    poster: str = "https://img.example/cover.jpg",
) -> dict:
    parts = [f'<img src="{poster}" />']
    for heading, inner_html in blocks:
        parts.append(
            f"<p>{heading}</p>"
            f'<div class="su-spoiler"><div class="secure-data" data-payload="{_b64(inner_html)}"></div></div>'
        )
    return {
        "id": 1,
        "slug": slug,
        "link": f"https://dlpsgame.com/{slug}/",
        "date": date,
        "modified": modified,
        "title": {"rendered": title},
        "content": {"rendered": "\n".join(parts)},
    }


class DlpsEditsParserTests(unittest.TestCase):
    def test_per_block_multi_title_id_isolation_and_host_allowlist(self):
        post = _wp_post(
            slug="cyberpunk-2077-ps5",
            title="Cyberpunk 2077 &#8211; Ultimate Edition",
            date="2026-01-09T00:00:00",
            modified="2026-11-28T01:00:00",
            blocks=[
                (
                    "PPSA03974 – EUR (v02.310.100)",
                    '<p>PPSA03974 EUR Game (v02.310.100): '
                    '<a href="https://downloadgameps3.net/archives/99999">Akia</a> '
                    '<a href="https://akirabox.com/abc123/file">Akia Direct</a> '
                    '<a href="https://clk.sh/skipme">Ad</a> '
                    '<a href="https://x.com/someone">Social</a></p>'
                    "<p>Password: (DLPSGAME.COM)</p>",
                ),
                (
                    "PPSA04029 – USA (v02.120.000)",
                    '<p>PPSA04029 USA Game (v02.120.000): '
                    '<a href="https://vikingfile.com/f/usa123">Viki</a></p>',
                ),
            ],
        )
        parsed = de.parse_wp_post(post)
        self.assertEqual(parsed["title"], "Cyberpunk 2077 – Ultimate Edition")
        self.assertEqual(len(parsed["blocks"]), 2)

        b1, b2 = parsed["blocks"]
        self.assertEqual(b1["titleId"], "PPSA03974")
        self.assertEqual(b1["version"], "02.310.100")
        self.assertEqual(b1["region"], "EUR")
        self.assertEqual(b1["password"], "DLPSGAME.COM")
        self.assertEqual([l["url"] for l in b1["directLinks"]], ["https://akirabox.com/abc123/file"])
        self.assertEqual(b1["gatedCount"], 1)

        self.assertEqual(b2["titleId"], "PPSA04029")
        self.assertEqual(b2["version"], "02.120.000")
        self.assertEqual(b2["region"], "USA")
        self.assertEqual([l["url"] for l in b2["directLinks"]], ["https://vikingfile.com/f/usa123"])
        self.assertEqual(b2["gatedCount"], 0)

    def test_delta_overlay_keeps_only_net_new_direct_links_and_reuses_poster(self):
        post_direct = _wp_post(
            slug="tlou-ps5",
            title="The Last of Us Part I",
            date="2025-09-11T00:00:00",
            modified="2026-11-26T12:00:00",
            blocks=[
                (
                    "PPSA03396 – EUR (v01.004.000)",
                    '<p>PPSA03396 EUR (v01.004.000): '
                    '<a href="https://vikingfile.com/f/already">Viki Old</a> '
                    '<a href="https://akirabox.com/brandnew/file">Akia New</a></p>',
                )
            ],
        )
        post_gated = _wp_post(
            slug="alan-wake-2-ps5",
            title="Alan Wake 2",
            date="2026-06-09T00:00:00",
            modified="2026-11-25T01:21:43",
            blocks=[
                (
                    "PPSA02572 – EUR (v01.200.009)",
                    '<p>By UNLiMiTED PPSA02572 EUR (v01.200.009): '
                    '<a href="https://downloadgameps3.net/archives/54618">Akia</a> '
                    '<a href="https://downloadgameps3.net/archives/54620">Rootz</a></p>',
                )
            ],
        )
        baseline_dlps = {
            "packages": [
                {
                    "titleId": "PPSA03396",
                    "title": "The Last of Us Part I",
                    "posterUrl": "https://pegasus-dl.dev/api/posters/clean-tlou",
                    "downloadSource": "https://dlpsgame.com/tlou-ps5/",
                    "downloadLinks": [{"name": "Viki", "url": "https://vikingfile.com/f/already"}],
                },
                {
                    "titleId": "PPSA02572",
                    "title": "Alan Wake 2",
                    "version": "01.200.007",
                    "downloadSource": "https://dlpsgame.com/alan-wake-2-ps5/",
                    "downloadLinks": [{"name": "Old", "url": "https://1fichier.com/?old"}],
                },
            ]
        }

        overlay, watch_rows, stats = de.build_dlps_edits([post_direct, post_gated], baseline_dlps)
        self.assertEqual(len(overlay["packages"]), 1)
        pkg = overlay["packages"][0]
        self.assertEqual(pkg["titleId"], "PPSA03396")
        self.assertEqual(pkg["posterUrl"], "https://pegasus-dl.dev/api/posters/clean-tlou")
        self.assertEqual([l["url"] for l in pkg["downloadLinks"]], ["https://akirabox.com/brandnew/file"])
        self.assertEqual(stats["new_direct_links"], 1)

        by_slug = {r["slug"]: r for r in watch_rows}
        self.assertEqual(by_slug["tlou-ps5"]["status"], "AUTO_ADDED")
        self.assertEqual(by_slug["alan-wake-2-ps5"]["status"], "NEEDS_MANUAL")
        self.assertEqual(by_slug["alan-wake-2-ps5"]["latestVersion"], "01.200.009")
        self.assertEqual(by_slug["alan-wake-2-ps5"]["gatedLinks"], 2)

    def test_manual_override_flips_watchlist_status_to_overridden(self):
        post_gated = _wp_post(
            slug="alan-wake-2-ps5",
            title="Alan Wake 2",
            date="2026-06-09T00:00:00",
            modified="2026-11-25T01:21:43",
            blocks=[
                (
                    "PPSA02572 – EUR (v01.200.009)",
                    '<p>PPSA02572 EUR (v01.200.009): <a href="https://downloadgameps3.net/archives/54618">Akia</a></p>',
                )
            ],
        )
        overrides = {
            "packages": [
                {
                    "titleId": "PPSA02572",
                    "title": "Alan Wake 2 Deluxe Edition",
                    "version": "01.200.009",
                    "downloadLinks": [{"name": "Akia", "url": "https://akirabox.com/resolved/file"}],
                }
            ]
        }
        _, watch_rows, _ = de.build_dlps_edits([post_gated], {"packages": []}, manual_overrides=overrides)
        self.assertEqual(watch_rows[0]["status"], "OVERRIDDEN")

    def test_watchlist_markdown_and_idempotent_comparison(self):
        rows = [
            {
                "modified": "2026-11-25",
                "published": "2026-06-09",
                "titleIds": ["PPSA02572"],
                "title": "Alan Wake 2",
                "slug": "alan-wake-2-ps5",
                "postUrl": "https://dlpsgame.com/alan-wake-2-ps5/",
                "latestVersion": "01.200.009",
                "autoDirectNew": 0,
                "gatedLinks": 6,
                "status": "NEEDS_MANUAL",
            }
        ]
        md1 = de.render_watchlist_markdown(rows, generated_at="2026-11-28T03:00:00Z")
        md2 = de.render_watchlist_markdown(rows, generated_at="2026-11-28T04:00:00Z")
        self.assertIn("PPSA02572", md1)
        self.assertIn("NEEDS_MANUAL", md1)
        self.assertTrue(de.watchlist_body_equal(md1, md2))

        rows[0]["status"] = "OVERRIDDEN"
        md3 = de.render_watchlist_markdown(rows, generated_at="2026-11-28T04:00:00Z")
        self.assertFalse(de.watchlist_body_equal(md1, md3))

    def test_multi_feed_baseline_excludes_links_and_versions_already_in_other_hub_feeds(self):
        post_overlap = _wp_post(
            slug="mk1-ps5",
            title="Mortal Kombat 1",
            date="2025-03-24T00:00:00",
            modified="2026-11-26T00:00:00",
            blocks=[
                (
                    "PPSA07570 – USA (v01.010.001)",
                    '<p>PPSA07570 USA (v01.010.001): '
                    '<a href="https://datanodes.to/already-in-jamzi">Data Old</a> '
                    '<a href="https://akirabox.com/truly-new/file">Akia Truly New</a></p>',
                )
            ],
        )
        post_covered_by_pfs = _wp_post(
            slug="covered-ps5",
            title="Covered By PFS",
            date="2025-05-01T00:00:00",
            modified="2026-11-26T00:00:00",
            blocks=[
                (
                    "PPSA11111 – EUR (v01.005.000)",
                    '<p>PPSA11111 EUR (v01.005.000): '
                    '<a href="https://downloadgameps3.net/archives/11111">Viki</a></p>',
                )
            ],
        )
        dlps_doc = {"packages": []}
        jamzi_doc = {
            "packages": [
                {
                    "titleId": "PPSA07570",
                    "title": "Mortal Kombat 1",
                    "downloadLinks": [{"name": "Data", "url": "https://datanodes.to/already-in-jamzi"}],
                }
            ]
        }
        pfs_doc = {
            "packages": [
                {
                    "titleId": "PPSA11111",
                    "title": "Covered By PFS",
                    "version": "01.005.000",
                    "downloadLinks": [{"name": "Viki", "url": "https://vikingfile.com/f/pfs"}],
                }
            ]
        }
        overlay, watch_rows, stats = de.build_dlps_edits([post_overlap, post_covered_by_pfs], [dlps_doc, jamzi_doc, pfs_doc])
        self.assertEqual(len(overlay["packages"]), 1)
        self.assertEqual([l["url"] for l in overlay["packages"][0]["downloadLinks"]], ["https://akirabox.com/truly-new/file"])
        self.assertEqual(stats["new_direct_links"], 1)
        by_slug = {r["slug"]: r for r in watch_rows}
        self.assertEqual(by_slug["covered-ps5"]["status"], "COVERED")

    def test_partial_status_when_auto_direct_added_and_latest_block_gated(self):
        post = _wp_post(
            slug="astro-bot-free-ps5",
            title="ASTRO BOT",
            date="2025-12-28T00:00:00",
            modified="2026-11-28T00:00:00",
            blocks=[
                (
                    "PPSA21564 – USA (v01.019.000)",
                    '<p>PPSA21564 USA (v01.019.000): <a href="https://downloadgameps3.net/archives/70001">Akia</a></p>',
                ),
                (
                    "PPSA21567 – EUR (v01.019.000)",
                    '<p>PPSA21567 EUR (v01.019.000): <a href="https://filekeeper.net/abc">FileK</a></p>',
                ),
            ],
        )
        _, watch_rows, stats = de.build_dlps_edits([post], [{"packages": []}])
        self.assertEqual(watch_rows[0]["status"], "PARTIAL")
        self.assertEqual(stats["partial"], 1)


if __name__ == "__main__":
    unittest.main()
