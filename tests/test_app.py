import unittest
from pathlib import Path
from uuid import uuid4

from app import create_app
from inpost import CheckResult, normalize_point


class FakeClient:
    def __init__(self):
        self.calls = 0

    def list_points(self):
        self.calls += 1
        return [normalize_point({
            "n": "SPA01N", "l": {"a": 50.827, "o": 15.521},
            "c": "Szklarska Poręba", "g": "szklarska-poreba",
            "e": "Turystyczna", "b": "8A", "r": "dolnośląskie",
        })]

    def check(self, _point):
        return CheckResult("active", {"PM10": {"value": 18.0}}, None, "https://inpost.pl/page")


class AppTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path(__file__).parent / f"test-data-{uuid4().hex}"
        self.data_dir.mkdir()
        self.client = FakeClient()
        app = create_app(self.client, self.data_dir)
        app.testing = True
        self.http = app.test_client()

    def tearDown(self):
        assert self.data_dir.resolve().parent == Path(__file__).parent.resolve()
        for file in self.data_dir.iterdir():
            assert file.is_file()
            file.unlink()
        self.data_dir.rmdir()

    def test_map_search_and_measurements(self):
        response = self.http.get("/api/points?west=15&south=50&east=16&north=51")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["points"][0]["status"], "unknown")
        self.assertEqual(self.http.get("/api/search?q=SPA01N").json["points"][0]["n"], "SPA01N")

        checked = self.http.post("/api/points/SPA01N/check")
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json["status"], "active")
        self.assertEqual(checked.json["measurements"]["PM10"]["value"], 18)
        self.assertEqual(self.http.get("/api/points/SPA01N").json["status"], "active")
        self.assertEqual(self.client.calls, 1)

    def test_invalid_bbox_and_unknown_code(self):
        self.assertEqual(self.http.get("/api/points?west=x&south=50&east=16&north=51").status_code, 400)
        self.assertEqual(self.http.post("/api/points/NOPE/check").status_code, 404)


if __name__ == "__main__":
    unittest.main()
