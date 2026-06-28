"""CLI импорта: python -m app.gosdata <resources> <csv-файл>."""
from __future__ import annotations

import sys

from ..database import SessionLocal
from .core import run_import_resources

_RUNNERS = {"resources": run_import_resources}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _RUNNERS:
        print("Использование: python -m app.gosdata <resources> <csv-файл>")
        return 2
    target, path = argv[1], argv[2]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print(f"Не удалось прочитать файл: {exc}")
        return 2
    with SessionLocal() as db:
        report = _RUNNERS[target](db, text)
    print(report.summary())
    for e in report.errors[:20]:
        print("  ", e)
    if len(report.errors) > 20:
        print(f"  …и ещё {len(report.errors) - 20} ошибок")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
