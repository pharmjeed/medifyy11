"""تجميع المقاييس اليومي يدوياً (م15) — بديل cron العامل عند غياب Redis.

python scripts/aggregate_metrics.py [--day 2026-08-02]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import system_session  # noqa: E402
from app.services.metrics import aggregate_daily_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", help="YYYY-MM-DD (افتراضي: الأمس)")
    args = parser.parse_args()
    day = dt.date.fromisoformat(args.day) if args.day else None
    with system_session() as db:
        result = aggregate_daily_metrics(db, day)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
