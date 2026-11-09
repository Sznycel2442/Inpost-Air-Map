"""Local map and cache for InPost Air measurements."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import Lock
import time

from flask import Flask, jsonify, request, send_from_directory

from inpost import InPostClient, InPostError

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("INPOST_AIR_MAP_DATA_DIR", ROOT / "data"))
CATALOG_MAX_AGE = timedelta(hours=24)
FRESH_MAX_AGE = timedelta(minutes=15)
MAP_LIMIT = 500


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Catalog:
    def __init__(self, client: InPostClient, cache_file: Path):
        self.client = client
        self.cache_file = cache_file
        self.points: list[dict] = []
        self.by_code: dict[str, dict] = {}
        self.loaded_at: datetime | None = None
        self.lock = Lock()
        self._read_cache()

    def _read_cache(self):
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self._set_points(payload["points"], datetime.fromisoformat(payload["loaded_at"]))
        except (FileNotFoundError, KeyError, ValueError, TypeError):
            pass

    def _set_points(self, points: list[dict], loaded_at: datetime):
        self.points = points
        self.by_code = {point["n"]: point for point in points}
        self.loaded_at = loaded_at

    def ensure_loaded(self):
        with self.lock:
            if self.loaded_at and now_utc() - self.loaded_at < CATALOG_MAX_AGE:
                return
            try:
                points = self.client.list_points()
            except Exception:
                if self.points:
                    return  # Use the last downloaded list when InPost is down.
                raise
            loaded_at = now_utc()
            self._set_points(points, loaded_at)
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"points": points, "loaded_at": loaded_at.isoformat()}),
                encoding="utf-8",
            )
            temporary.replace(self.cache_file)


class Results:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS results (
                    code TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    measurements TEXT NOT NULL,
                    air_index_level TEXT,
                    page_url TEXT,
                    error TEXT
                )"""
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_many(self, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        placeholders = ",".join("?" for _ in codes)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT code,status,checked_at,measurements,air_index_level,page_url,error "
                f"FROM results WHERE code IN ({placeholders})",
                codes,
            ).fetchall()
        return {row[0]: self._row(row) for row in rows}

    def get(self, code: str) -> dict | None:
        return self.get_many([code]).get(code)

    @staticmethod
    def _row(row) -> dict:
        checked_at = datetime.fromisoformat(row[2])
        status = row[1]
        if status == "active" and now_utc() - checked_at >= FRESH_MAX_AGE:
            status = "stale"
        return {
            "status": status,
            "checked_at": row[2],
            "measurements": json.loads(row[3]),
            "air_index_level": row[4],
            "page_url": row[5],
            "error": row[6],
        }

    def save(self, code: str, result: dict):
        with self._connect() as db:
            db.execute(
                """INSERT INTO results
                   (code,status,checked_at,measurements,air_index_level,page_url,error)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET
                   status=excluded.status,
                   checked_at=excluded.checked_at,
                   measurements=excluded.measurements,
                   air_index_level=excluded.air_index_level,
                   page_url=excluded.page_url,
                   error=excluded.error""",
                (
                    code,
                    result["status"],
                    result["checked_at"],
                    json.dumps(result["measurements"]),
                    result.get("air_index_level"),
                    result.get("page_url"),
                    result.get("error"),
                ),
            )


def create_app(client=None, data_dir: Path | None = None):
    app = Flask(__name__, static_folder=None)
    client = client or InPostClient()
    data_dir = data_dir or DATA_DIR
    catalog = Catalog(client, data_dir / "points.json")
    results = Results(data_dir / "results.sqlite3")
    check_lock = Lock()
    last_check = 0.0

    def load_catalog():
        try:
            catalog.ensure_loaded()
            return None
        except Exception as exc:
            return jsonify({"error": f"Nie udało się pobrać listy paczkomatów: {exc}"}), 503

    def point_with_result(point):
        return {**point, **(results.get(point["n"]) or {"status": "unknown"})}

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "static", "index.html")

    @app.get("/static/<path:filename>")
    def static_file(filename):
        return send_from_directory(ROOT / "static", filename)

    @app.get("/api/points")
    def points():
        if failure := load_catalog():
            return failure
        try:
            west, south, east, north = (
                float(request.args[key]) for key in ("west", "south", "east", "north")
            )
        except (KeyError, ValueError):
            return jsonify({"error": "Podaj west, south, east i north"}), 400
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
            return jsonify({"error": "Nieprawidłowe granice mapy"}), 400
        visible = [
            point
            for point in catalog.points
            if west <= point["lon"] <= east and south <= point["lat"] <= north
        ]
        selected = visible[:MAP_LIMIT]
        statuses = results.get_many([point["n"] for point in selected])
        return jsonify(
            {
                "points": [
                    {**point, "status": statuses.get(point["n"], {}).get("status", "unknown")}
                    for point in selected
                ],
                "total": len(visible),
                "truncated": len(visible) > MAP_LIMIT,
            }
        )

    @app.get("/api/search")
    def search():
        if failure := load_catalog():
            return failure
        query = request.args.get("q", "").strip().casefold()
        if len(query) < 2:
            return jsonify({"points": []})
        matches = [
            point
            for point in catalog.points
            if query in point["n"].casefold() or query in point["city"].casefold()
        ][:20]
        return jsonify({"points": [point_with_result(point) for point in matches]})

    @app.get("/api/points/<code>")
    def detail(code):
        if failure := load_catalog():
            return failure
        point = catalog.by_code.get(code.upper())
        if point is None:
            return jsonify({"error": "Nie znaleziono paczkomatu"}), 404
        return jsonify(point_with_result(point))

    @app.post("/api/points/<code>/check")
    def check(code):
        nonlocal last_check
        if failure := load_catalog():
            return failure
        point = catalog.by_code.get(code.upper())
        if point is None:
            return jsonify({"error": "Nie znaleziono paczkomatu"}), 404
        with check_lock:
            delay = 1.5 - (time.monotonic() - last_check)
            if delay > 0:
                time.sleep(delay)
            last_check = time.monotonic()
            try:
                checked = client.check(point)
                result = {
                    "status": checked.status,
                    "measurements": checked.measurements,
                    "air_index_level": checked.air_index_level,
                    "page_url": checked.page_url,
                    "error": checked.error,
                }
            except InPostError as exc:
                result = {
                    "status": "error",
                    "measurements": {},
                    "error": str(exc),
                }
            except Exception as exc:
                result = {
                    "status": "error",
                    "measurements": {},
                    "error": f"Błąd połączenia: {type(exc).__name__}",
                }
            result["checked_at"] = now_utc().isoformat()
            results.save(point["n"], result)
        return jsonify(point_with_result(point))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8765, debug=False, threaded=True)
