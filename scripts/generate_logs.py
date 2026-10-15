#!/usr/bin/env python3
"""Write a synthetic application log with injected error spikes.

    python scripts/generate_logs.py --minutes 360 --out sample_logs/app.log
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from opspilot.loggen import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-10-01T08:00:00", help="UTC start time (ISO)")
    parser.add_argument("--minutes", type=int, default=360)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("sample_logs/app.log"))
    args = parser.parse_args()

    lines = generate(datetime.fromisoformat(args.start), minutes=args.minutes, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} lines to {args.out}")


if __name__ == "__main__":
    main()
