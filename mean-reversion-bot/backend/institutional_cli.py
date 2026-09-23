"""Run an offline analysis and preserve a self-contained report (no .env required)."""
import argparse
import json
from pathlib import Path

from app.institutional.service import OPERATIONS, analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("input", type=Path, help="JSON request")
    parser.add_argument("--output", type=Path, required=True, help="New report file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new report filename")
        request = json.loads(args.input.read_text(encoding="utf-8-sig"))
        report = analyze(args.operation, request)
        serialized = json.dumps(report, indent=2, allow_nan=False)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(serialized + "\n")
    except (OSError, ValueError, ArithmeticError) as exc:
        parser.exit(2, f"Analysis failed: {exc}\n")
    print(f"Report {report['report_id']} saved to {args.output}")


if __name__ == "__main__":
    main()
