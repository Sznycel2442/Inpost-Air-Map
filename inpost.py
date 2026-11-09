"""Small, independent client for the public InPost locker pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import urlsplit

POINTS_URL = "https://inpost.pl/sites/default/files/points.json"
AIR_URL = "https://inpost.pl/shipx-point-data/{id}/{code}/air_index_level"
SHIPX_PATTERN = re.compile(
    r'data-shipx-url="(?:/en)?/shipx-point-data/(\d+)/([^/" ]+)/air_index_level"'
)


class InPostError(Exception):
    """A request or response from InPost cannot be used."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def slug(value: str) -> str:
    """Match the URL form used by the InPost parcel locker pages."""
    value = value.translate(str.maketrans({"ł": "l", "Ł": "L"}))
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def locker_url(point: dict, english: bool = False) -> str:
    prefix = "parcel-locker" if english else "paczkomat"
    path = slug(
        f"{prefix}-{point['g']}-{point['n']}-{point['e']}-paczkomaty-{point['r']}"
    )
    return f"https://inpost.pl/{'en/' if english else ''}{path}"


def normalize_point(raw: dict) -> dict | None:
    """Retain only the public fields needed by the map."""
    try:
        code = str(raw["n"]).upper()
        lat = float(raw["l"]["a"])
        lon = float(raw["l"]["o"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        point = {
            "n": code,
            "lat": lat,
            "lon": lon,
            "city": str(raw.get("c") or ""),
            "street": str(raw.get("e") or ""),
            "building": str(raw.get("b") or ""),
            "description": str(raw.get("d") or ""),
            "g": str(raw.get("g") or raw.get("c") or ""),
            "e": str(raw.get("e") or ""),
            "r": str(raw.get("r") or ""),
        }
        point["url"] = locker_url(point)
        return point
    except (KeyError, TypeError, ValueError):
        return None


def parse_sensor_lines(lines: object) -> dict[str, dict]:
    """Parse every numeric sensor supplied by InPost, including new sensor keys."""
    measurements = {}
    if not isinstance(lines, list):
        return measurements
    for line in lines:
        if not isinstance(line, str):
            continue
        parts = line.split(":")
        if len(parts) < 2 or not re.fullmatch(r"[A-Z][A-Z0-9_]*", parts[0]):
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if not -1e9 < value < 1e9:
            continue
        entry = {"value": value}
        if len(parts) > 2 and parts[2]:
            try:
                entry["norm"] = float(parts[2])
            except ValueError:
                pass
        measurements[parts[0]] = entry
    return measurements


@dataclass
class CheckResult:
    status: str
    measurements: dict[str, dict]
    air_index_level: str | None
    page_url: str | None
    error: str | None = None


class InPostClient:
    """Fetch the same page and AJAX response used by the HA integration."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            def session_factory():
                from curl_cffi.requests import Session

                return Session(impersonate="chrome", timeout=20)
        self.session_factory = session_factory

    def list_points(self) -> list[dict]:
        with self.session_factory() as session:
            response = session.get(POINTS_URL)
            self._check_response(response)
            payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise InPostError("Lista paczkomatów ma nieoczekiwany format")
        points = [point for raw in items if (point := normalize_point(raw))]
        if not points:
            raise InPostError("Lista paczkomatów jest pusta")
        return points

    def check(self, point: dict) -> CheckResult:
        with self.session_factory() as session:
            page_url, locker_id = self._find_page(session, point)
            if locker_id is None:
                return CheckResult("no_data", {}, None, None)

            # The page request establishes the cookies used by the AJAX call.
            response = session.post(
                AIR_URL.format(id=locker_id, code=point["n"]),
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": "https://inpost.pl",
                    "Referer": page_url,
                },
            )
            self._check_response(response)
            try:
                payload = response.json()
            except (ValueError, TypeError) as exc:
                raise InPostError("Odpowiedź pomiarowa nie jest JSON") from exc
        if not isinstance(payload, dict):
            raise InPostError("Odpowiedź pomiarowa ma nieoczekiwany format")
        measurements = parse_sensor_lines(payload.get("air_sensors"))
        index = payload.get("air_index_level")
        return CheckResult(
            "active" if measurements else "no_data",
            measurements,
            str(index) if index is not None else None,
            page_url,
        )

    def _find_page(self, session, point: dict) -> tuple[str | None, str | None]:
        errors = []
        for page_url in (locker_url(point), locker_url(point, english=True)):
            try:
                response = session.get(page_url)
                self._check_response(response)
            except InPostError as exc:
                errors.append(exc)
                continue
            if urlsplit(str(response.url)).path.rstrip("/") in (
                "/znajdz-paczkomat",
                "/en/find-parcel-locker",
            ):
                continue
            match = SHIPX_PATTERN.search(response.text)
            if match and match.group(2).upper() == point["n"]:
                return page_url, match.group(1)
        if errors:
            raise errors[-1]
        return None, None

    @staticmethod
    def _check_response(response) -> None:
        status = response.status_code
        if status >= 400:
            raise InPostError(f"InPost zwrócił HTTP {status}", status)
