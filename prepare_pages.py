"""Copy only browser assets into a GitHub Pages deploy directory."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
ASSETS = (
    "index.html",
    "static/app.js",
    "static/style.css",
    "site-data/points.json",
    "site-data/readings.json",
)


def prepare() -> None:
    for relative in ASSETS:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        target = DIST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (DIST / ".nojekyll").touch()


if __name__ == "__main__":
    prepare()
