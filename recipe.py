"""Deterministic, standard-library-only meeting-to-task public recipe."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path


class Refused(ValueError):
    """A public recipe precondition was not satisfied."""


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise Refused("JSON input is missing")
    if path.stat().st_size > 2_000_000:
        raise Refused("JSON input exceeds the 2 MB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused("JSON input cannot be read") from exc
    if not isinstance(value, dict):
        raise Refused("JSON input must be an object")
    return value


def text_value(value: object, label: str, limit: int = 5000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Refused(f"Invalid {label}")
    return value


def _validate_model_output(model_output: dict) -> tuple[dict, dict]:
    if not isinstance(model_output, dict) or set(model_output) != {
        "fixture_metadata",
        "proposal",
    }:
        raise Refused("Model output must contain fixture metadata and proposal")
    metadata = model_output["fixture_metadata"]
    proposal = model_output["proposal"]
    required_metadata = {
        "fixture_id",
        "fixture_kind",
        "selected",
        "label",
        "model",
        "captured_on",
        "source_is_synthetic",
        "is_production_data",
        "is_production_result",
        "live_api_call",
    }
    if not isinstance(metadata, dict) or set(metadata) != required_metadata:
        raise Refused("Model output metadata is incomplete or has unexpected fields")
    if (
        metadata["fixture_kind"] != "selected_model_output_fixture"
        or metadata["selected"] is not True
        or metadata["label"] != "SYNTHETIC_ONLY_NOT_PRODUCTION"
        or metadata["model"] != "gpt-5.6-luna / max"
        or metadata["source_is_synthetic"] is not True
        or metadata["is_production_data"] is not False
        or metadata["is_production_result"] is not False
        or metadata["live_api_call"] is not False
    ):
        raise Refused("Only a clearly labelled synthetic model fixture is accepted")
    text_value(metadata["fixture_id"], "fixture ID", 200)
    text_value(metadata["model"], "model label", 100)
    text_value(metadata["captured_on"], "capture date", 10)
    if not isinstance(proposal, dict):
        raise Refused("Model proposal must be an object")
    return metadata, proposal


def _validate_human_review(
    human_review: object,
    meeting_id: str,
    source_hash: str,
    lines: dict[str, str],
) -> dict:
    required = {
        "schema_version",
        "meeting_id",
        "source_hash",
        "human_confirmed_action_line_ids",
    }
    if not isinstance(human_review, dict) or set(human_review) != required:
        raise Refused("A separate human review input is required")
    if type(human_review["schema_version"]) is not int or human_review["schema_version"] != 1:
        raise Refused("Unsupported human review schema")

    reviewed_meeting = text_value(human_review["meeting_id"], "review meeting ID", 100)
    reviewed_source_hash = text_value(human_review["source_hash"], "review source hash", 64)
    if reviewed_meeting != meeting_id or reviewed_source_hash != source_hash:
        raise Refused("Human review does not match this meeting and source")

    raw_line_ids = human_review["human_confirmed_action_line_ids"]
    if not isinstance(raw_line_ids, list) or len(raw_line_ids) > len(lines):
        raise Refused("Human-confirmed action line IDs must be a valid array")
    reviewed_line_ids = []
    for raw_line_id in raw_line_ids:
        line_id = text_value(raw_line_id, "reviewed action line ID", 100)
        if line_id not in lines or line_id in reviewed_line_ids:
            raise Refused("Human review contains an unknown or duplicate source line")
        reviewed_line_ids.append(line_id)

    return {
        "schema_version": 1,
        "meeting_id": meeting_id,
        "source_hash": source_hash,
        "human_confirmed_action_line_ids": sorted(reviewed_line_ids),
    }


def prepare(
    transcript: dict,
    model_output: dict,
    *,
    human_review: dict | None = None,
) -> dict:
    if not isinstance(transcript, dict) or set(transcript) != {"meeting_id", "lines"}:
        raise Refused("Transcript must contain only a meeting ID and source lines")
    meeting_id = text_value(transcript.get("meeting_id"), "meeting ID", 100)
    source_lines = transcript.get("lines")
    if not isinstance(source_lines, list) or not source_lines:
        raise Refused("Transcript lines are required")
    lines: dict[str, str] = {}
    for item in source_lines:
        if not isinstance(item, dict) or set(item) != {"id", "text"}:
            raise Refused("Invalid transcript line")
        line_id = text_value(item["id"], "line ID", 100)
        if line_id in lines:
            raise Refused("Duplicate source line ID")
        lines[line_id] = text_value(item["text"], "source line", 10000)

    source_hash = digest(transcript)
    review = _validate_human_review(human_review, meeting_id, source_hash, lines)
    human_confirmed_action_line_ids = set(review["human_confirmed_action_line_ids"])
    _, proposal = _validate_model_output(model_output)
    if set(proposal) != {"tasks"} or not isinstance(proposal["tasks"], list):
        raise Refused("Proposal must contain only a tasks array")
    if len(proposal["tasks"]) > 100:
        raise Refused("At most 100 tasks can be reviewed in one plan")

    tasks = []
    seen = set()
    for task in proposal["tasks"]:
        if not isinstance(task, dict) or set(task) != {"title", "owner", "due", "evidence"}:
            raise Refused("Unexpected task fields; model output is data, not instructions")
        title = text_value(task["title"], "task title", 300)
        evidence = task["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise Refused("Each task requires source evidence")
        quotes = []
        for reference in evidence:
            if not isinstance(reference, dict) or set(reference) != {"line_id", "quote"}:
                raise Refused("Invalid evidence reference")
            line_id = text_value(reference["line_id"], "evidence line ID", 100)
            quote = text_value(reference["quote"], "quote", 10000)
            if line_id not in lines or quote not in lines[line_id]:
                raise Refused("Evidence quote does not match the named source line")
            if line_id not in human_confirmed_action_line_ids:
                raise Refused("Task evidence is not human-confirmed as actionable")
            quotes.append(quote)
        if not any(title in quote for quote in quotes):
            raise Refused("Task title must be grounded in source evidence")

        owner, due = task["owner"], task["due"]
        if owner is not None:
            owner = text_value(owner, "owner", 100)
            if not any(owner in quote for quote in quotes):
                raise Refused("Owner has no matching source text; use null if unknown")
        if due is not None:
            due = text_value(due, "due date", 10)
            try:
                valid_date = date.fromisoformat(due).isoformat() == due
            except ValueError:
                valid_date = False
            if not valid_date or not any(due in quote for quote in quotes):
                raise Refused("Due date must be explicit ISO text in evidence; otherwise use null")

        task_id = digest([meeting_id, source_hash, task])
        if task_id in seen:
            raise Refused("Duplicate task in one proposal")
        seen.add(task_id)
        tasks.append({"id": task_id, **task})

    return {
        "schema_version": 1,
        "meeting_id": meeting_id,
        "source_hash": source_hash,
        "source": transcript,
        "human_review": review,
        "model_output": model_output,
        "tasks": tasks,
        "destination": "LOCAL_SIMULATOR",
        "model_execution": "captured_fixture_only",
    }


def validate_plan(plan: dict, *, human_review: dict | None = None) -> None:
    required = {
        "schema_version",
        "meeting_id",
        "source_hash",
        "source",
        "human_review",
        "model_output",
        "tasks",
        "destination",
        "model_execution",
    }
    if not isinstance(plan, dict) or set(plan) != required:
        raise Refused("Invalid plan schema")
    model_output = plan.get("model_output")
    if not isinstance(model_output, dict):
        raise Refused("Plan is missing its selected model output")
    expected = prepare(plan.get("source", {}), model_output, human_review=human_review)
    if canonical(expected) != canonical(plan):
        raise Refused("Plan does not match its source and task definitions")


def approve(plan: dict, actor: str, *, human_review: dict | None = None) -> dict:
    validate_plan(plan, human_review=human_review)
    text_value(actor, "local reviewing operator", 100)
    return {
        "schema_version": 1,
        "plan_hash": digest(plan),
        "actor": actor,
        "scope": "LOCAL_SIMULATOR_ONLY",
    }


def apply_local(
    plan: dict,
    approval: dict,
    target: str | Path,
    *,
    human_review: dict | None = None,
) -> dict:
    validate_plan(plan, human_review=human_review)
    if not isinstance(approval, dict):
        raise Refused("Local approval is required")
    if (
        set(approval) != {"schema_version", "plan_hash", "actor", "scope"}
        or approval["schema_version"] != 1
        or approval["scope"] != "LOCAL_SIMULATOR_ONLY"
        or approval["plan_hash"] != digest(plan)
    ):
        raise Refused("Local approval does not match this plan")
    text_value(approval["actor"], "reviewing operator", 100)

    target = Path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(target, timeout=10)
    except (OSError, sqlite3.Error) as exc:
        raise Refused("Local simulator database cannot be opened") from exc
    try:
        target.chmod(0o600)
        db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        inserted = 0
        with db:
            for task in plan["tasks"]:
                prior = db.execute("SELECT payload FROM tasks WHERE id=?", (task["id"],)).fetchone()
                if prior and prior[0] != canonical(task):
                    raise Refused("Existing task ID has different content")
                inserted += db.execute(
                    "INSERT OR IGNORE INTO tasks VALUES (?,?)", (task["id"], canonical(task))
                ).rowcount
        all_tasks = [
            json.loads(row[0]) for row in db.execute("SELECT payload FROM tasks ORDER BY id")
        ]
        return {
            "mode": "LOCAL_SIMULATOR",
            "input_count": len(plan["tasks"]),
            "inserted": inserted,
            "already_present": len(plan["tasks"]) - inserted,
            "total_stored": len(all_tasks),
            "external_write": False,
            "tasks": all_tasks,
        }
    finally:
        db.close()
