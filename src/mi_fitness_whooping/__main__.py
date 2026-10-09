"""Explicit basic daily analytics command over the existing Legacy run contract."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from mi_fitness_whooping.basic import day_report, history_report, run_and_read


def main() -> int:
    if sys.argv[1:2] == ["reconcile"]:
        # Target-owned canonical source history; its own arguments and JSON output.
        from mi_fitness_whooping.ingestion.reconcile import main as reconcile_main
        return reconcile_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description="Existing Mi Fitness daily analytics")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reconcile", help="rebuild canonical source history (see `reconcile --help`)")
    run = commands.add_parser("run", help="run existing calculations and show a date")
    run.add_argument("--source", type=Path, required=True)
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--profile", type=Path)
    run.add_argument("--day", type=date.fromisoformat)
    day = commands.add_parser("day", help="read one selected date")
    day.add_argument("--db", type=Path, required=True)
    day.add_argument("--day", type=date.fromisoformat, required=True)
    history = commands.add_parser("history", help="read an inclusive date range")
    history.add_argument("--db", type=Path, required=True)
    history.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    history.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            answer = run_and_read(args.source, args.db, args.day, args.profile)
        elif args.command == "day":
            answer = day_report(args.db, args.day)
        else:
            answer = history_report(args.db, args.start, args.end)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 1
    print(json.dumps(answer, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
