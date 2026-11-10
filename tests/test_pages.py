import json
from pathlib import Path
import unittest
from uuid import uuid4

from build_pages_data import build
from inpost import CheckResult, normalize_point


class SnapshotClient:
    def list_points(self):
        return [normalize_point({
            "n": "TEST01M", "t": 1, "l": {"a": 50, "o": 15},
            "c": "Testowo", "g": "testowo", "e": "Główna",
            "b": "1", "r": "dolnośląskie",
        })]

    def check(self, point):
        assert point["n"] == "TEST01M"
        return CheckResult("active", {"PM25": {"value": 12.0}}, None, point["url"])


class PagesTests(unittest.TestCase):
    def test_static_snapshot_preserves_measurement_with_null_index(self):
        folder = Path(__file__).parent / f"test-data-{uuid4().hex}"
        folder.mkdir()
        try:
            summary = build(SnapshotClient(), folder, 0, ["TEST01M"], pause=0)
            points = json.loads((folder / "points.json").read_text(encoding="utf-8"))
            readings = json.loads((folder / "readings.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["with_measurements"], 1)
            self.assertEqual(points[0]["n"], "TEST01M")
            self.assertEqual(readings["results"]["TEST01M"]["measurements"]["PM25"]["value"], 12)
            self.assertIsNone(readings["results"]["TEST01M"]["air_index_level"])
        finally:
            assert folder.resolve().parent == Path(__file__).parent.resolve()
            for file in folder.iterdir():
                assert file.is_file()
                file.unlink()
            folder.rmdir()

    def test_pages_entry_is_html_with_relative_assets(self):
        html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-mode="pages"', html)
        self.assertIn('href="static/style.css"', html)
        self.assertIn('src="static/app.js"', html)
        self.assertIn('integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="', html)
        self.assertNotIn('src="/static/app.js"', html)


if __name__ == "__main__":
    unittest.main()
