"""Run the self-contained public-package demonstration."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from recipe import Refused, apply_local, approve, prepare, read_json


def demo_result() -> dict:
    root = Path(__file__).resolve().parent
    transcript = read_json(root / "fixtures" / "synthetic_meeting.json")
    model_output = read_json(root / "fixtures" / "selected_model_output.json")
    human_review = read_json(root / "fixtures" / "human_review.json")
    plan = prepare(transcript, model_output, human_review=human_review)
    if plan != prepare(transcript, model_output, human_review=human_review):
        raise Refused("Preparation is not deterministic")
    approval = approve(plan, "synthetic-local-review", human_review=human_review)
    with TemporaryDirectory(prefix="meeting-to-tasks-") as directory:
        target = Path(directory) / "tasks.sqlite3"
        first = apply_local(plan, approval, target, human_review=human_review)
        repeat = apply_local(plan, approval, target, human_review=human_review)
    if (first["inserted"], repeat["inserted"], repeat["total_stored"]) != (2, 0, 2):
        raise Refused("Demo count reconciliation failed")
    if first["external_write"] or repeat["external_write"]:
        raise Refused("Demo unexpectedly performed an external write")
    return {
        "author": "Naoya / jokv213",
        "fixture_status": "SYNTHETIC_ONLY_NOT_PRODUCTION",
        "model_output_status": "selected_fixture_not_live_call",
        "first_run": {
            key: first[key]
            for key in (
                "input_count",
                "inserted",
                "already_present",
                "total_stored",
                "external_write",
            )
        },
        "repeat_run": {
            key: repeat[key]
            for key in (
                "input_count",
                "inserted",
                "already_present",
                "total_stored",
                "external_write",
            )
        },
    }


def main() -> int:
    try:
        result = demo_result()
    except (OSError, Refused, sqlite3.Error) as exc:
        print(f"DEMO_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
