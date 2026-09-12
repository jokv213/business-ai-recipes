"""Verify the detached public-package candidate with the standard library."""

from __future__ import annotations

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
    except Refused:
        return
    raise AssertionError("invalid input was accepted")


def verify(
    root: Path | None = None,
    *,
    transcript: object = _MISSING,
    model_output: object = _MISSING,
    human_review: object = _MISSING,
) -> dict:
    root = (root or Path(__file__).resolve().parent).resolve()
    _assert_candidate_boundary(root)

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
    print("PASS: candidate boundary and synthetic fixture labels")
    print("PASS: separate human-reviewed evidence boundary")
    print("PASS: deterministic prepare and schema validation")
    print(
        "PASS: first_run.inserted={first_inserted}; "
        "repeat_run.inserted={repeat_inserted}; "
        "repeat_run.total_stored={stored}; external_write={external_write}".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
