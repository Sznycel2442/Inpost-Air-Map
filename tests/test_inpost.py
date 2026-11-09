import unittest

from inpost import InPostClient, InPostError, normalize_point, parse_sensor_lines


RAW_POINT = {
    "n": "SPA01N", "l": {"a": 50.827, "o": 15.521}, "c": "Szklarska Poręba",
    "g": "szklarska-poreba", "e": "Turystyczna", "b": "8A", "r": "dolnośląskie",
}


class Response:
    def __init__(self, payload=None, text="", status=200, url="https://inpost.pl/page"):
        self.payload = payload
        self.text = text
        self.status_code = status
        self.url = url

    def json(self):
        return self.payload


class Session:
    def __init__(self, pages, air):
        self.pages = list(pages)
        self.air = air
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, _url):
        return self.pages.pop(0)

    def post(self, url, headers):
        self.posts.append((url, headers))
        return self.air


class InPostTests(unittest.TestCase):
    def test_null_index_does_not_hide_all_measurements(self):
        marker = '<div data-shipx-url="/shipx-point-data/25882/SPA01N/air_index_level">'
        session = Session(
            [Response(text=marker)],
            Response(payload={
                "message": "", "air_index_level": None,
                "air_sensors": ["PM25:12:20", "PM10:18:40", "NO2:7:", "O3:21:"],
            }),
        )
        point = normalize_point(RAW_POINT)
        result = InPostClient(lambda: session).check(point)
        self.assertEqual(result.status, "active")
        self.assertIsNone(result.air_index_level)
        self.assertEqual(set(result.measurements), {"PM25", "PM10", "NO2", "O3"})
        self.assertIn("/25882/SPA01N/", session.posts[0][0])

    def test_english_page_is_used_after_polish_redirect(self):
        marker = '<div data-shipx-url="/en/shipx-point-data/25882/SPA01N/air_index_level">'
        session = Session(
            [Response(url="https://inpost.pl/znajdz-paczkomat"), Response(text=marker)],
            Response(payload={"air_index_level": None, "air_sensors": ["PM10:18:40"]}),
        )
        result = InPostClient(lambda: session).check(normalize_point(RAW_POINT))
        self.assertEqual(result.status, "active")
        self.assertIn("/en/", result.page_url)

    def test_empty_sensors_are_not_called_active(self):
        marker = '<div data-shipx-url="/shipx-point-data/25882/SPA01N/air_index_level">'
        session = Session(
            [Response(text=marker)],
            Response(payload={"air_index_level": None, "air_sensors": []}),
        )
        result = InPostClient(lambda: session).check(normalize_point(RAW_POINT))
        self.assertEqual(result.status, "no_data")

    def test_http_error_is_not_confused_with_missing_sensors(self):
        marker = '<div data-shipx-url="/shipx-point-data/25882/SPA01N/air_index_level">'
        session = Session([Response(text=marker)], Response(status=403))
        with self.assertRaises(InPostError) as raised:
            InPostClient(lambda: session).check(normalize_point(RAW_POINT))
        self.assertEqual(raised.exception.status_code, 403)

    def test_sensor_parser_keeps_new_sensor_types(self):
        parsed = parse_sensor_lines(["PM25:12.5:20", "CO2:480:", "BAD:x:", None])
        self.assertEqual(parsed["PM25"], {"value": 12.5, "norm": 20.0})
        self.assertEqual(parsed["CO2"], {"value": 480.0})
        self.assertNotIn("BAD", parsed)


if __name__ == "__main__":
    unittest.main()
