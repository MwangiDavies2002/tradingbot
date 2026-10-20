"""Deterministic synthetic CSV for smoke testing, not market-performance evidence."""
import argparse
import csv
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = []
    for i in range(260):
        close = 100 + .03 * i + 2 * math.sin(i * math.pi / 10)
        previous = rows[-1][4] if rows else close
        rows.append((i * 300, previous, max(previous, close) + .3 + .001 * i,
                     min(previous, close) - .3 + .001 * i, close, 10))
    with args.output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
        writer.writerows(rows)
    print(f"Saved synthetic fixture: {args.output}")


if __name__ == "__main__":
    main()
