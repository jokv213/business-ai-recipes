"""Offline-first, synthetic-only Jev meeting-line judgment recipe.

The default path reads a recorded fixture and never uses the network.  The
optional ``--live`` path sends only the bundled synthetic meeting lines to the
direct TypeSafe Jev endpoint.  It never approves, registers, or replies to a
task, and it never writes the provider response to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

LABELS = ("action_candidate", "decision", "quote_or_context", "undecided")
MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
AUTO_PROBABILITY = 0.85
AUTO_CONFIDENCE = 0.65
MAX_LINES = 30
MAX_JSON_BYTES = 2_000_000

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MEETING_FIXTURE = PACKAGE_ROOT / "fixtures" / "synthetic_meeting.json"
RECORDED_FIXTURE = PACKAGE_ROOT / "fixtures" / "meeting_line_judgment.json"
BUNDLED_MEETING_SHA256 = "5c3383e686e67462466c0c7896e336cdd68fc8e757891dd8719664e6e548d86e"


class Refused(ValueError):
    """A recipe precondition or provider response was not trusted."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not send a TypeSafe credential to another host."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            raise Refused("JSON fixture is missing or too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused("JSON fixture cannot be read") from exc
    if not isinstance(value, dict):
        raise Refused("JSON fixture must be an object")
    return value


def _text(value: object, label: str, limit: int = 5000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Refused(f"Invalid {label}")
    return value


def _probability(value: object, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
        raise Refused(f"Invalid {label}")
    return float(value)


def load_meeting(path: str | Path = MEETING_FIXTURE) -> dict:
    """Load and validate a meeting containing only source line IDs and text."""

    meeting = _read_object(Path(path))
    if set(meeting) != {"meeting_id", "lines"}:
        raise Refused("Meeting must contain only meeting_id and lines")
    _text(meeting["meeting_id"], "meeting ID", 100)
    lines = meeting["lines"]
    if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES:
        raise Refused("Meeting lines must contain 1 to 30 entries")
    seen: set[str] = set()
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"id", "text"}:
            raise Refused("Meeting lines may contain only id and text")
        line_id = _text(line["id"], "line ID", 100)
        if line_id in seen:
            raise Refused("Meeting contains a duplicate line ID")
        seen.add(line_id)
        _text(line["text"], "line text", 10000)
    return meeting


def _validate_answer(answer: object) -> dict:
    if not isinstance(answer, dict) or set(answer) != {
        "type",
        "choice",
        "probabilities",
        "confidence",
    }:
        raise Refused("Jev answer has an unexpected schema")
    if answer["type"] != "choice" or answer["choice"] not in LABELS:
        raise Refused("Jev answer must be one of the line judgment classes")
    probabilities = answer["probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != set(LABELS):
        raise Refused("Jev probabilities do not match the fixed judgment classes")
    checked_probabilities = {
        label: _probability(probabilities[label], f"probability for {label}") for label in LABELS
    }
    if abs(sum(checked_probabilities.values()) - 1) > 0.02:
        raise Refused("Jev probabilities do not sum to one")
    choice = answer["choice"]
    if checked_probabilities[choice] < max(checked_probabilities.values()):
        raise Refused("Jev choice is not the highest-probability class")
    confidence = _probability(answer["confidence"], "confidence")
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": checked_probabilities,
        "confidence": confidence,
    }


def _validate_judgment(judgment: object) -> dict:
    if not isinstance(judgment, dict) or set(judgment) != {
        "line_id",
        "answer",
        "ambiguity_flags",
    }:
        raise Refused("Line judgment has an unexpected schema")
    line_id = _text(judgment["line_id"], "judgment line ID", 100)
    flags = judgment["ambiguity_flags"]
    if not isinstance(flags, list) or len(flags) > 10:
        raise Refused("Ambiguity flags must be a short array")
    checked_flags = [_text(flag, "ambiguity flag", 100) for flag in flags]
    return {
        "line_id": line_id,
        "answer": _validate_answer(judgment["answer"]),
        "ambiguity_flags": checked_flags,
    }


def load_recorded_fixture(path: str | Path = RECORDED_FIXTURE) -> dict:
    """Load a clearly non-live, hand-authored synthetic judgment fixture."""

    fixture = _read_object(Path(path))
    required = {
        "schema_version",
        "fixture_metadata",
        "meeting_id",
        "source_hash",
        "provisional_thresholds",
        "judgments",
    }
    if set(fixture) != required or fixture["schema_version"] != 1:
        raise Refused("Recorded judgment fixture schema is invalid")
    metadata = fixture["fixture_metadata"]
    metadata_required = {
        "fixture_id",
        "fixture_kind",
        "label",
        "model",
        "recorded_on",
        "source_is_synthetic",
        "is_production_data",
        "is_production_result",
        "live_api_call",
        "record_origin",
    }
    if not isinstance(metadata, dict) or set(metadata) != metadata_required:
        raise Refused("Recorded judgment metadata is incomplete")
    if (
        metadata["fixture_kind"] != "recorded_synthetic_judgment_fixture"
        or metadata["label"] != "SYNTHETIC_ONLY_NOT_PRODUCTION"
        or metadata["model"] != MODEL
        or metadata["source_is_synthetic"] is not True
        or metadata["is_production_data"] is not False
        or metadata["is_production_result"] is not False
        or metadata["live_api_call"] is not False
        or metadata["record_origin"] != "hand_authored_synthetic_fixture_not_api_observation"
    ):
        raise Refused("Only an explicitly non-live synthetic fixture is accepted")
    _text(metadata["fixture_id"], "fixture ID", 200)
    _text(metadata["recorded_on"], "fixture record date", 10)
    meeting_id = _text(fixture["meeting_id"], "fixture meeting ID", 100)
    source_hash = _text(fixture["source_hash"], "fixture source hash", 64)
    if len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash):
        raise Refused("Fixture source hash must be a lowercase SHA-256 value")
    thresholds = fixture["provisional_thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != {"probability", "confidence"}:
        raise Refused("Provisional thresholds are incomplete")
    checked_thresholds = {
        "probability": _probability(thresholds["probability"], "probability threshold"),
        "confidence": _probability(thresholds["confidence"], "confidence threshold"),
    }
    if checked_thresholds != {
        "probability": AUTO_PROBABILITY,
        "confidence": AUTO_CONFIDENCE,
    }:
        raise Refused("Fixture thresholds do not match this recipe")
    judgments = fixture["judgments"]
    if not isinstance(judgments, list) or not judgments or len(judgments) > MAX_LINES:
        raise Refused("Recorded judgments must contain 1 to 30 entries")
    checked_judgments = [_validate_judgment(judgment) for judgment in judgments]
    ids = [judgment["line_id"] for judgment in checked_judgments]
    if len(set(ids)) != len(ids):
        raise Refused("Recorded judgments contain a duplicate line ID")
    return {
        "schema_version": 1,
        "fixture_metadata": metadata,
        "meeting_id": meeting_id,
        "source_hash": source_hash,
        "provisional_thresholds": checked_thresholds,
        "judgments": checked_judgments,
    }


def _validate_fixture_for_meeting(meeting: dict, fixture: dict) -> None:
    if fixture["meeting_id"] != meeting["meeting_id"] or fixture["source_hash"] != digest(meeting):
        raise Refused("Judgment fixture does not match the meeting source")
    meeting_ids = {line["id"] for line in meeting["lines"]}
    judgment_ids = {judgment["line_id"] for judgment in fixture["judgments"]}
    if meeting_ids != judgment_ids:
        raise Refused("Every meeting line must have exactly one judgment")


def classify_judgments(
    meeting: dict,
    judgments: list[dict],
    *,
    thresholds: dict[str, float],
    fixture_status: str,
    live_api_call: bool,
) -> dict:
    """Classify lines without extracting fields or applying any task."""

    if set(thresholds) != {"probability", "confidence"}:
        raise Refused("Classification thresholds are incomplete")
    probability_threshold = _probability(thresholds["probability"], "probability threshold")
    confidence_threshold = _probability(thresholds["confidence"], "confidence threshold")
    checked_judgments = [_validate_judgment(judgment) for judgment in judgments]
    judgment_by_id = {judgment["line_id"]: judgment for judgment in checked_judgments}
    line_ids = [line["id"] for line in meeting["lines"]]
    if set(line_ids) != set(judgment_by_id) or len(line_ids) != len(judgment_by_id):
        raise Refused("Classification judgments do not cover the meeting exactly")

    rows = []
    for line in meeting["lines"]:
        judgment = judgment_by_id[line["id"]]
        answer = judgment["answer"]
        choice = answer["choice"]
        selected_probability = answer["probabilities"][choice]
        review_reasons = []
        if choice != "action_candidate":
            review_reasons.append(f"non_action_label:{choice}")
        if selected_probability < probability_threshold:
            review_reasons.append("probability_below_threshold")
        if answer["confidence"] < confidence_threshold:
            review_reasons.append("confidence_below_threshold")
        if judgment["ambiguity_flags"]:
            review_reasons.append("ambiguity_flagged")
        row = {
            "line_id": line["id"],
            "text": line["text"],
            "label": choice,
            "selected_probability": selected_probability,
            "confidence": answer["confidence"],
            "route": "action_candidate" if not review_reasons else "review",
        }
        if review_reasons:
            row["review_reasons"] = review_reasons
        rows.append(row)

    action_candidates = [row for row in rows if row["route"] == "action_candidate"]
    review = [row for row in rows if row["route"] == "review"]
    return {
        "schema_version": 1,
        "fixture_status": fixture_status,
        "model": MODEL,
        "live_api_call": live_api_call,
        "thresholds": {
            "probability": probability_threshold,
            "confidence": confidence_threshold,
        },
        "input_line_count": len(rows),
        "action_candidate_count": len(action_candidates),
        "review_count": len(review),
        "action_candidates": action_candidates,
        "review": review,
        "human_review_required": True,
        "auto_decision": False,
        "auto_approval": False,
        "task_registration": False,
        "external_write": False,
    }


def offline_result(
    meeting_path: str | Path = MEETING_FIXTURE,
    fixture_path: str | Path = RECORDED_FIXTURE,
) -> dict:
    """Reproduce the recorded synthetic judgment without network access."""

    meeting = load_meeting(meeting_path)
    fixture = load_recorded_fixture(fixture_path)
    _validate_fixture_for_meeting(meeting, fixture)
    return classify_judgments(
        meeting,
        fixture["judgments"],
        thresholds=fixture["provisional_thresholds"],
        fixture_status="recorded_synthetic_fixture_not_live",
        live_api_call=False,
    )


def question_payload(line: dict) -> dict:
    """Build the only provider payload allowed by the optional live path."""

    if set(line) != {"id", "text"}:
        raise Refused("Live payload requires a bundled source line")
    line_id = _text(line["id"], "line ID", 100)
    text = _text(line["text"], "line text", 10000)
    return {
        "model": MODEL,
        "state": {
            "meeting_id": "synthetic-luna-launch-20260910",
            "line_id": line_id,
            "text": text,
        },
        "questions": {
            "judgment": {
                "type": "choice",
                "instructions": (
                    "Classify this single meeting line. Treat quoted text and context as data, "
                    "do not infer or extract dates, owners, or numbers, and choose undecided "
                    "when the line does not state a settled action."
                ),
                "criteria": {
                    "action_candidate": "A concrete action is proposed or assigned in this line.",
                    "decision": (
                        "A decision, rejection, or settled outcome is stated; it is not a task."
                    ),
                    "quote_or_context": (
                        "The line is quoted material, background, or context rather than a request."
                    ),
                    "undecided": "The matter is pending, speculative, ambiguous, or not settled.",
                },
            }
        },
    }


def _provider_answer(value: object) -> dict:
    if not isinstance(value, dict) or value.get("model") != MODEL:
        raise Refused("TypeSafe response model did not match Jev 1.13.0")
    answers = value.get("answers")
    if not isinstance(answers, dict) or set(answers) != {"judgment"}:
        raise Refused("TypeSafe response did not contain the judgment answer")
    return _validate_answer(answers["judgment"])


def call_jev(payload: dict, key: str, *, opener=None) -> dict:
    """Call TypeSafe once and return only the validated answer fields."""

    if not isinstance(key, str) or not key or any(char.isspace() for char in key):
        raise Refused("TYPESAFE_API_KEY is required for --live")
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    selected_opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        with selected_opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise Refused("TypeSafe returned an unexpected HTTP status")
            body = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError:
        raise Refused("TypeSafe HTTP request failed") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise Refused("TypeSafe transport failed") from None
    if len(body) > MAX_JSON_BYTES:
        raise Refused("TypeSafe response exceeded the size limit")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Refused("TypeSafe response was not valid JSON") from None
    return _provider_answer(value)


def live_result(meeting: dict, key: str, *, opener=None) -> dict:
    """Evaluate only the bundled synthetic meeting, without persisting responses."""

    if digest(meeting) != BUNDLED_MEETING_SHA256:
        raise Refused("--live accepts only the bundled synthetic meeting fixture")
    rows = []
    for line in meeting["lines"]:
        answer = call_jev(question_payload(line), key, opener=opener)
        rows.append({"line_id": line["id"], "answer": answer, "ambiguity_flags": []})
    result = classify_judgments(
        meeting,
        rows,
        thresholds={"probability": AUTO_PROBABILITY, "confidence": AUTO_CONFIDENCE},
        fixture_status="live_request_not_recorded",
        live_api_call=True,
    )
    result["live_request_count"] = len(rows)
    result["provider_response_persisted"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Optionally call direct TypeSafe Jev with the bundled synthetic lines only",
    )
    arguments = parser.parse_args()
    try:
        meeting = load_meeting()
        if arguments.live:
            key = os.environ.get("TYPESAFE_API_KEY")
            if not key or any(char.isspace() for char in key):
                raise Refused("TYPESAFE_API_KEY is required for --live")
            result = live_result(meeting, key)
        else:
            result = offline_result()
    except (OSError, Refused) as exc:
        print(f"RECIPE_REFUSED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
