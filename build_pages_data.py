"""Build static point and measurement snapshots for GitHub Pages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from inpost import InPostClient, InPostError

ROOT = Path(__file__).resolve().parent
SITE_DATA = ROOT / "site-data"
WATCHLIST = ("SPA01N", "AJE01BAPP")
PUBLIC_FIELDS = ("n", "lat", "lon", "city", "street", "building", "description", "url")


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def load_results(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload.get("results"), dict):
            return payload
    except (FileNotFoundError, ValueError, AttributeError):
        pass
    return {"results": {}, "cursor": 0}


def select_codes(points: list[dict], previous: dict, count: int, extra: list[str]) -> tuple[list[str], int]:
    by_code = {point["n"]: point for point in points}
    selected = [code for code in dict.fromkeys([*WATCHLIST, *(code.upper() for code in extra)]) if code in by_code]
    cursor = int(previous.get("cursor", 0)) % len(points)
    for index in range(min(count, len(points))):
        code = points[(cursor + index) % len(points)]["n"]
        if code not in selected:
            selected.append(code)
    return selected, (cursor + min(count, len(points))) % len(points)


def build(client: InPostClient, folder: Path, count: int, extra: list[str], pause: float = 1.5) -> dict:
    if count < 0 or pause < 0:
        raise ValueError("count and pause must be non-negative")
    points = client.list_points()
    if not points:
        raise ValueError("No parcel lockers in InPost's point list")
    by_code = {point["n"]: point for point in points}
    previous = load_results(folder / "readings.json")
    selected, cursor = select_codes(points, previous, count, extra)
    results = {code: value for code, value in previous["results"].items() if code in by_code}

    for position, code in enumerate(selected, start=1):
        print(f"[{position}/{len(selected)}] {code}", flush=True)
        try:
            reading = client.check(by_code[code])
            results[code] = {
                "status": reading.status,
                "measurements": reading.measurements,
                "air_index_level": reading.air_index_level,
                "page_url": reading.page_url,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            # A failed request must not erase the last confirmed measurement.
            if code not in results or results[code].get("status") != "active":
                results[code] = {
                    "status": "error",
                    "measurements": {},
                    "error": str(exc) if isinstance(exc, InPostError) else type(exc).__name__,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            print(f"  {exc}", flush=True)
        if position < len(selected):
            time.sleep(pause)

    generated_at = datetime.now(timezone.utc).isoformat()
    write_json(folder / "points.json", [
        {key: point[key] for key in PUBLIC_FIELDS} for point in points
    ])
    payload = {"generated_at": generated_at, "cursor": cursor, "results": results}
    write_json(folder / "readings.json", payload)
    return {"points": len(points), "checked": len(selected), "with_measurements": sum(value.get("status") == "active" for value in results.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=20, help="Additional lockers to scan in rotating order")
    parser.add_argument("--code", action="append", default=[], help="Always check this locker code")
    parser.add_argument("--pause", type=float, default=1.5, help="Seconds between checks")
    args = parser.parse_args()
    print(build(InPostClient(), SITE_DATA, args.count, args.code, args.pause))
