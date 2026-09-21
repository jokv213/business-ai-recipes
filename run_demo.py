"""Run the self-contained public-package demonstration."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from recipe import Refused, apply_local, approve, prepare, read_json


def line_judgment_summary(root: Path) -> dict:
    path = root / "recipes" / "meeting-line-judgment" / "recipe.py"
    spec = importlib.util.spec_from_file_location("public_meeting_line_judgment", path)
    if spec is None or spec.loader is None:
        raise Refused("Meeting line judgment recipe could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.offline_result()
    except ValueError as exc:
        raise Refused("Meeting line judgment demo failed") from exc
    if (
        result["fixture_status"] != "recorded_synthetic_fixture_not_live"
        or result["action_candidate_count"] != 1
        or result["review_count"] != 5
        or result["external_write"] is not False
        or result["human_review_required"] is not True
    ):
        raise Refused("Meeting line judgment count or boundary reconciliation failed")
    return {
        "fixture_status": result["fixture_status"],
        "action_candidate_count": result["action_candidate_count"],
        "review_count": result["review_count"],
        "human_review_required": result["human_review_required"],
        "external_write": result["external_write"],
    }


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
        "line_judgment": line_judgment_summary(root),
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
