"""Offline unit tests for scripts/add_manual_override.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import add_manual_override as amo  # noqa: E402


class ManualOverrideTests(unittest.TestCase):
    def test_validate_title_id_accepts_ps5_ps4_and_rejects_bad(self):
        self.assertEqual(amo.validate_title_id("ppsa02572"), "PPSA02572")
        self.assertEqual(amo.validate_title_id("CUSA00411"), "CUSA00411")
        with self.assertRaises(ValueError):
            amo.validate_title_id("INVALID")
        with self.assertRaises(ValueError):
            amo.validate_title_id("PPSA123")

    def test_parse_link_arg_rejects_redirectors_and_non_http(self):
        good = amo.parse_link_arg("Akia=https://akirabox.com/abc/file")
        self.assertEqual(good, {"name": "Akia", "url": "https://akirabox.com/abc/file"})

        bare = amo.parse_link_arg("https://vikingfile.com/f/xyz")
        self.assertEqual(bare, {"name": "vikingfile.com", "url": "https://vikingfile.com/f/xyz"})

        for bad in (
            "Akia=https://downloadgameps3.net/archives/54618",
            "https://downloadgameps3.com/guide/",
            "Ad=https://clk.sh/xyz",
            "Bad=ftp://example.com/file.pkg",
            "Bad=not-a-url",
        ):
            with self.assertRaises(ValueError, msg=f"should reject {bad}"):
                amo.parse_link_arg(bad)

    def test_upsert_merges_links_idempotently_and_sorts(self):
        doc = {"name": "Manual", "version": 1, "packages": []}
        doc = amo.upsert_override(
            doc,
            title_id="PPSA02572",
            title="Alan Wake 2 Deluxe Edition",
            version="01.200.009",
            region="EUR",
            password="DLPSGAME.COM",
            links=[{"name": "Akia", "url": "https://akirabox.com/1/file"}],
        )
        doc = amo.upsert_override(
            doc,
            title_id="PPSA02572",
            title="Alan Wake 2 Deluxe Edition",
            version="01.200.009",
            region="EUR",
            password="DLPSGAME.COM",
            links=[
                {"name": "Akia", "url": "https://akirabox.com/1/file"},
                {"name": "Viki", "url": "https://vikingfile.com/f/2"},
            ],
        )
        doc = amo.upsert_override(
            doc,
            title_id="PPSA00001",
            title="Alpha Game",
            version="01.000.000",
            links=[{"name": "Viki", "url": "https://vikingfile.com/f/alpha"}],
        )
        self.assertEqual([p["titleId"] for p in doc["packages"]], ["PPSA00001", "PPSA02572"])
        aw2 = doc["packages"][1]
        self.assertEqual([l["url"] for l in aw2["downloadLinks"]], ["https://akirabox.com/1/file", "https://vikingfile.com/f/2"])
        self.assertIn("DLPSGAME.COM", aw2["description"])

    def test_remove_override_by_title_and_optional_version(self):
        doc = {"name": "Manual", "version": 1, "packages": []}
        doc = amo.upsert_override(doc, title_id="PPSA02572", title="AW2", version="01.200.009", links=[{"name": "A", "url": "https://akirabox.com/1/file"}])
        doc = amo.upsert_override(doc, title_id="PPSA02572", title="AW2", version="01.200.010", links=[{"name": "B", "url": "https://akirabox.com/2/file"}])

        doc, removed = amo.remove_override(doc, title_id="PPSA02572", version="01.200.009")
        self.assertEqual(removed, 1)
        self.assertEqual([p["version"] for p in doc["packages"]], ["01.200.010"])

        doc, removed2 = amo.remove_override(doc, title_id="PPSA02572")
        self.assertEqual(removed2, 1)
        self.assertEqual(doc["packages"], [])

    def test_cli_add_list_remove_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual-overrides.json"
            rc = amo.main([
                "--file", str(path),
                "add",
                "--title-id", "PPSA02572",
                "--title", "Alan Wake 2 Deluxe Edition",
                "--version", "01.200.009",
                "--region", "EUR",
                "--password", "DLPSGAME.COM",
                "--link", "Akia=https://akirabox.com/test/file",
            ])
            self.assertEqual(rc, 0)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["packages"]), 1)
            self.assertEqual(amo.main(["--file", str(path), "list"]), 0)
            self.assertEqual(amo.main(["--file", str(path), "remove", "--title-id", "PPSA02572"]), 0)
            saved2 = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved2["packages"], [])


if __name__ == "__main__":
    unittest.main()
