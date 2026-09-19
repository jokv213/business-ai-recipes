"""Verify the detached public-package candidate with the standard library."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from recipe import Refused, apply_local, approve, prepare, read_json, validate_plan

EXPECTED_FILES = {
    ".github/workflows/verify.yml",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "recipe.py",
    "run_demo.py",
    "verify.py",
    "fixtures/synthetic_meeting.json",
    "fixtures/selected_model_output.json",
    "fixtures/human_review.json",
    "recipes/csv-to-report/README.md",
    "recipes/csv-to-report/report.py",
    "recipes/csv-to-report/sales.csv",
    "recipes/csv-to-report/examples/empty.csv",
    "recipes/csv-to-report/examples/duplicate.csv",
    "recipes/csv-to-report/examples/mixed-strings.csv",
    "recipes/jev-support-triage/README.md",
    "recipes/jev-support-triage/cases.json",
    "recipes/jev-support-triage/observed-answers.json",
    "recipes/jev-support-triage/triage.py",
}
_MISSING = object()


def _files(root: Path) -> set[str]:
    files = set()
    for path in root.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise AssertionError(f"symlink is not allowed: {path.relative_to(root)}")
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def _assert_candidate_boundary(root: Path) -> None:
    if _files(root) != EXPECTED_FILES:
        raise AssertionError(f"candidate file set differs: {_files(root)}")
    forbidden = (
        "/Users" + "/",
        "github" + "_author",
        "config/" + "policy.json",
        ".runtime" + "/",
        "BEGIN " + "PRIVATE KEY",
        "gh" + "p_",
        "xox" + "b-",
    )
    for relative in EXPECTED_FILES:
        path = root / relative
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for fragment in forbidden:
            if fragment in content:
                raise AssertionError(f"forbidden content in {relative}")


def _must_refuse(action) -> None:
    try:
        action()
    except ValueError:
        return
    raise AssertionError("invalid input was accepted")


def _load_csv_recipe(root: Path):
    path = root / "recipes" / "csv-to-report" / "report.py"
    spec = importlib.util.spec_from_file_location("public_csv_to_report", path)
    if spec is None or spec.loader is None:
        raise AssertionError("public CSV recipe could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_jev_recipe(root: Path):
    path = root / "recipes" / "jev-support-triage" / "triage.py"
    spec = importlib.util.spec_from_file_location("public_jev_support_triage", path)
    if spec is None or spec.loader is None:
        raise AssertionError("public Jev recipe could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_csv_report(root: Path) -> dict:
    recipe = _load_csv_recipe(root)
    csv_root = root / "recipes" / "csv-to-report"
    sales_text = (csv_root / "sales.csv").read_text(encoding="utf-8")
    report = recipe.build_report(sales_text)
    expected_sales = {
        "status": "REVIEW_REQUIRED",
        "source_rows": 4,
        "valid_amount_rows": 3,
        "missing_amount_rows": 1,
        "invalid_amount_rows": 0,
        "duplicate_record_rows": 0,
        "total_amount_yen": 4500,
    }
    if report["metrics"] != expected_sales or report["narrative_verified"] is not True:
        raise AssertionError("CSV sample metrics or narrative do not reconcile")

    cases = {
        "empty.csv": {
            "status": "EMPTY_INPUT",
            "source_rows": 0,
            "valid_amount_rows": 0,
            "missing_amount_rows": 0,
            "invalid_amount_rows": 0,
            "duplicate_record_rows": 0,
            "total_amount_yen": 0,
        },
        "duplicate.csv": {
            "status": "REVIEW_REQUIRED",
            "source_rows": 2,
            "valid_amount_rows": 2,
            "missing_amount_rows": 0,
            "invalid_amount_rows": 0,
            "duplicate_record_rows": 1,
            "total_amount_yen": 2400,
        },
        "mixed-strings.csv": {
            "status": "REVIEW_REQUIRED",
            "source_rows": 3,
            "valid_amount_rows": 1,
            "missing_amount_rows": 1,
            "invalid_amount_rows": 1,
            "duplicate_record_rows": 0,
            "total_amount_yen": 1200,
        },
    }
    for name, expected in cases.items():
        actual = recipe.build_report((csv_root / "examples" / name).read_text(encoding="utf-8"))
        if actual["metrics"] != expected or actual["narrative_verified"] is not True:
            raise AssertionError(f"CSV edge case does not reconcile: {name}")

    invalid_csv_inputs = (
        "record_id,amount_yen\nX001,1200\n",
        "record_id,department,amount_yen\n,営業,1200\n",
        "record_id,department,amount_yen\nX001,営業,1200,unexpected\n",
        'record_id,department,amount_yen\nX001,"営業,1200\n',
    )
    for csv_text in invalid_csv_inputs:
        try:
            recipe.analyze_csv_text(csv_text)
        except recipe.CSVReportError:
            continue
        raise AssertionError("invalid CSV input was accepted")

    changed_narrative = report["narrative"].replace("4,500円", "4,501円")
    if changed_narrative == report["narrative"]:
        raise AssertionError("CSV narrative regression probe did not change its total")
    try:
        recipe.build_report(sales_text, narrative=changed_narrative)
    except recipe.NarrativeMismatch:
        pass
    else:
        raise AssertionError("incorrect narrative total was accepted")

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "recipes/csv-to-report/report.py",
            "--csv",
            "recipes/csv-to-report/sales.csv",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode:
        raise AssertionError(f"CSV README command failed: {completed.stderr}")
    cli_result = json.loads(completed.stdout)
    if (
        cli_result.get("metrics") != expected_sales
        or cli_result.get("narrative_verified") is not True
    ):
        raise AssertionError("CSV README command output did not reconcile")
    return {
        "source_rows": expected_sales["source_rows"],
        "missing_amount_rows": expected_sales["missing_amount_rows"],
        "total_amount_yen": expected_sales["total_amount_yen"],
        "edge_cases": len(cases),
        "invalid_inputs_rejected": len(invalid_csv_inputs),
        "narrative_mismatch_rejected": True,
    }


def _verify_jev_recipe(root: Path) -> dict:
    recipe = _load_jev_recipe(root)
    recipe_root = root / "recipes" / "jev-support-triage"
    cases_path = recipe_root / "cases.json"
    recorded_path = recipe_root / "observed-answers.json"
    cases = recipe.load_cases(cases_path)
    report = recipe.reproduce(cases_path, recorded_path)
    expected_summary = {
        "cases": 16,
        "clear_cases": 11,
        "routable_clear_cases": 10,
        "routable_correct_auto": 10,
        "routable_wrong_auto": 0,
        "routable_reviewed": 0,
        "clear_other_cases": 1,
        "clear_other_reviewed": 1,
        "review_cases": 5,
        "review_gated": 5,
        "review_missed": 0,
        "input_tokens": 7655,
        "latency_ms_median": 844.5,
        "latency_ms_max": 2738,
    }
    if report["summary"] != expected_summary:
        raise AssertionError(f"Jev recorded summary changed: {report['summary']}")
    if (
        report["fixture_status"] != "SYNTHETIC_ONLY_NOT_PRODUCTION"
        or report["recorded_response_status"] != "recorded_fixture_not_live_call"
        or report["model"] != "jev-1.13.0"
        or report["input_fixture_sha256"]
        != "cf03bab36b8914a4393f79f402541c2c0f84c24791368749d734c532743904d5"
        or report["recorded_fixture_sha256"]
        != hashlib.sha256(recorded_path.read_bytes()).hexdigest()
        or report["provisional_thresholds"] != {"probability": 0.85, "confidence": 0.65}
        or report["offline"] is not True
        or report["network_calls"] != 0
        or report["external_write"] is not False
    ):
        raise AssertionError("Jev offline boundary or fixture metadata changed")

    rows_by_id = {row["id"]: row for row in report["cases"]}
    expected_review_ids = {
        "jp-unrelated",
        "jp-mixed-login-price",
        "jp-invoice-access",
        "jp-vague",
        "jp-two-requests",
        "jp-injection",
    }
    if {case["id"] for case in cases} != set(rows_by_id):
        raise AssertionError("Jev case IDs do not reconcile")
    if any(rows_by_id[case_id]["action"] != "review" for case_id in expected_review_ids):
        raise AssertionError("Jev review cases were automatically routed")

    changed = json.loads(recorded_path.read_text(encoding="utf-8"))
    changed["cases"][0]["answer"]["choice"] = "billing"
    with TemporaryDirectory(prefix="jev-triage-invalid-") as directory:
        invalid = Path(directory) / "observed-answers.json"
        invalid.write_text(json.dumps(changed), encoding="utf-8")
        _must_refuse(lambda: recipe.reproduce(cases_path, invalid))

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("TYPESAFE_API_KEY", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    offline = subprocess.run(
        [sys.executable, "-B", "recipes/jev-support-triage/triage.py", "--offline"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if offline.returncode:
        raise AssertionError(f"Jev offline README command failed: {offline.stdout}{offline.stderr}")
    cli_report = json.loads(offline.stdout)
    if cli_report["summary"] != expected_summary or cli_report["network_calls"] != 0:
        raise AssertionError("Jev offline CLI output did not reconcile")

    live_without_key = subprocess.run(
        [sys.executable, "-B", "recipes/jev-support-triage/triage.py", "--live"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if live_without_key.returncode == 0 or "TYPESAFE_API_KEY" not in live_without_key.stdout:
        raise AssertionError("Jev live mode did not fail closed without its environment key")

    payload = recipe.question_payload(cases[0]["message"])
    if payload["model"] != "jev-1.13.0" or payload["state"] != {"message": cases[0]["message"]}:
        raise AssertionError("Jev live payload contract changed")
    return {
        "cases": 16,
        "routable_correct_auto": 10,
        "review_gated": 5,
        "network_calls": 0,
        "external_write": False,
    }


def verify(
    root: Path | None = None,
    *,
    transcript: object = _MISSING,
    model_output: object = _MISSING,
    human_review: object = _MISSING,
) -> dict:
    root = (root or Path(__file__).resolve().parent).resolve()
    _assert_candidate_boundary(root)
    csv_summary = _verify_csv_report(root)
    jev_summary = _verify_jev_recipe(root)

    supplied_inputs = (
        transcript is not _MISSING,
        model_output is not _MISSING,
        human_review is not _MISSING,
    )
    if any(supplied_inputs):
        if not all(supplied_inputs):
            raise Refused("Custom verification requires transcript, model output, and human review")
        plan = prepare(transcript, model_output, human_review=human_review)
        validate_plan(plan, human_review=human_review)
        return {
            "files": len(EXPECTED_FILES),
            "prepared_tasks": len(plan["tasks"]),
            "csv_report": csv_summary,
            "jev_report": jev_summary,
            "external_write": False,
        }

    transcript = read_json(root / "fixtures" / "synthetic_meeting.json")
    model_output = read_json(root / "fixtures" / "selected_model_output.json")
    human_review = read_json(root / "fixtures" / "human_review.json")
    metadata = model_output["fixture_metadata"]
    if metadata["label"] != "SYNTHETIC_ONLY_NOT_PRODUCTION":
        raise AssertionError("synthetic fixture label is missing")
    plan = prepare(transcript, model_output, human_review=human_review)
    if plan != prepare(transcript, model_output, human_review=human_review):
        raise AssertionError("prepare is not deterministic")
    reviewed_line_ids = set(human_review["human_confirmed_action_line_ids"])
    if any(
        evidence["line_id"] not in reviewed_line_ids
        for task in plan["tasks"]
        for evidence in task["evidence"]
    ):
        raise AssertionError("a task uses evidence outside the human review input")

    _must_refuse(lambda: prepare(transcript, model_output))
    bad_review = deepcopy(human_review)
    bad_review["source_hash"] = "0" * 64
    _must_refuse(lambda: prepare(transcript, model_output, human_review=bad_review))

    bad_output = deepcopy(model_output)
    bad_output["proposal"]["tasks"][0]["owner"] = "根拠のない担当"
    _must_refuse(lambda: prepare(transcript, bad_output, human_review=human_review))
    bad_output = deepcopy(model_output)
    bad_output["proposal"]["tasks"][0]["execute"] = "do not run"
    _must_refuse(lambda: prepare(transcript, bad_output, human_review=human_review))

    bad_output = deepcopy(model_output)
    bad_output["human_review"] = human_review
    _must_refuse(lambda: prepare(transcript, bad_output, human_review=human_review))
    bad_output = deepcopy(model_output)
    bad_output["proposal"]["human_confirmed_action_line_ids"] = ["L4"]
    _must_refuse(lambda: prepare(transcript, bad_output, human_review=human_review))

    for line in transcript["lines"]:
        if line["id"] in reviewed_line_ids:
            continue
        bad_output = deepcopy(model_output)
        bad_output["proposal"]["tasks"] = [
            {
                "title": line["text"][:300],
                "owner": None,
                "due": None,
                "evidence": [{"line_id": line["id"], "quote": line["text"]}],
            }
        ]
        _must_refuse(
            lambda bad_output=bad_output: prepare(transcript, bad_output, human_review=human_review)
        )

    _must_refuse(lambda: validate_plan(plan))
    changed_review = deepcopy(human_review)
    changed_review["human_confirmed_action_line_ids"].append("L4")
    _must_refuse(lambda: validate_plan(plan, human_review=changed_review))
    approval = approve(plan, "synthetic-local-review", human_review=human_review)
    _must_refuse(lambda: approve(plan, "synthetic-local-review"))
    with TemporaryDirectory(prefix="meeting-to-tasks-verify-") as directory:
        target = Path(directory) / "tasks.sqlite3"
        missing_review_target = Path(directory) / "missing-review.sqlite3"
        _must_refuse(lambda: apply_local(plan, approval, missing_review_target))
        if missing_review_target.exists():
            raise AssertionError("missing human review created a target")
        _must_refuse(lambda: apply_local(plan, {}, target, human_review=human_review))
        first = apply_local(plan, approval, target, human_review=human_review)
        repeat = apply_local(plan, approval, target, human_review=human_review)
        changed = deepcopy(plan)
        changed["tasks"][0]["owner"] = "改変された担当"
        changed_target = Path(directory) / "changed.sqlite3"
        _must_refuse(
            lambda: apply_local(changed, approval, changed_target, human_review=human_review)
        )
        if changed_target.exists():
            raise AssertionError("changed plan created a target")
    expected = (2, 0, 2)
    actual = (first["inserted"], repeat["inserted"], repeat["total_stored"])
    if actual != expected:
        raise AssertionError(f"count reconciliation failed: {actual}")
    if first["external_write"] is not False or repeat["external_write"] is not False:
        raise AssertionError("external write boundary failed")
    return {
        "files": len(EXPECTED_FILES),
        "deterministic_prepare": True,
        "reviewed_action_line_ids": sorted(reviewed_line_ids),
        "csv_report": csv_summary,
        "jev_report": jev_summary,
        "first_inserted": first["inserted"],
        "repeat_inserted": repeat["inserted"],
        "stored": repeat["total_stored"],
        "external_write": False,
    }


def main() -> int:
    try:
        result = verify()
    except (AssertionError, OSError, ValueError) as exc:
        print(f"VERIFY_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: candidate boundary and synthetic fixture labels; files={result['files']}")
    print("PASS: separate human-reviewed evidence boundary")
    print("PASS: deterministic prepare and schema validation")
    print("PASS: CSV README command, edge cases, and narrative reconciliation")
    print("PASS: Jev recorded fixture, provisional abstention gate, and offline/live boundary")
    print(
        "PASS: first_run.inserted={first_inserted}; "
        "repeat_run.inserted={repeat_inserted}; "
        "repeat_run.total_stored={stored}; external_write={external_write}".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
