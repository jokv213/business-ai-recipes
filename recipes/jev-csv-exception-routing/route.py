"""Offline comparison of a fixed keyword baseline and recorded Jev Choices."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROUTES = ("accounting", "sales_ops", "data_quality")
CHOICES = (*ROUTES, "review")
FLAG_ORDER = ("missing_amount", "invalid_amount", "duplicate_record_id")
KEYWORDS = {
    "accounting": ("経理", "会計", "請求書"),
    "sales_ops": ("営業管理", "受注管理", "営業部"),
    "data_quality": ("データ管理", "取込管理", "CSV管理"),
}
PROBABILITY_THRESHOLD = 0.85
CONFIDENCE_THRESHOLD = 0.65
MAX_FIXTURE_BYTES = 200_000
MAX_EXPLANATION_LENGTH = 500

CASES_PATH = Path(__file__).with_name("cases.json")
RECORDED_PATH = Path(__file__).with_name("recorded-answers.json")


class RoutingError(ValueError):
    """The synthetic fixture or recorded Choice contract is unsafe to use."""


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise RoutingError(f"fixture is missing: {path.name}")
    if path.stat().st_size > MAX_FIXTURE_BYTES:
        raise RoutingError(f"fixture is too large: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoutingError(f"fixture is not valid JSON: {path.name}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_case(case: object, *, seen_rows: set[int]) -> dict:
    if not isinstance(case, dict):
        raise RoutingError("each case must be an object")
    required = {"id", "finding", "explanation", "group", "expected_route", "dangerous"}
    if set(case) != required:
        raise RoutingError("case fields must be exactly the documented value-free schema")
    case_id = case["id"]
    if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 80:
        raise RoutingError("case id is invalid")
    finding = case["finding"]
    if not isinstance(finding, dict) or set(finding) != {"data_row", "flags"}:
        raise RoutingError(f"finding schema is invalid: {case_id}")
    data_row = finding["data_row"]
    if isinstance(data_row, bool) or not isinstance(data_row, int) or data_row < 1:
        raise RoutingError(f"finding data_row is invalid: {case_id}")
    if data_row in seen_rows:
        raise RoutingError(f"finding data_row is duplicated: {data_row}")
    seen_rows.add(data_row)
    flags = finding["flags"]
    if not isinstance(flags, list) or not flags or len(flags) != len(set(flags)):
        raise RoutingError(f"finding flags are invalid: {case_id}")
    if any(flag not in FLAG_ORDER for flag in flags):
        raise RoutingError(f"finding has an unsupported flag: {case_id}")
    if [flag for flag in FLAG_ORDER if flag in flags] != flags:
        raise RoutingError(f"finding flags are not in deterministic order: {case_id}")
    explanation = case["explanation"]
    if not isinstance(explanation, str) or not explanation.strip():
        raise RoutingError(f"case explanation is invalid: {case_id}")
    if len(explanation) > MAX_EXPLANATION_LENGTH:
        raise RoutingError(f"case explanation is too long: {case_id}")
    group = case["group"]
    if group not in {"candidate", "review"}:
        raise RoutingError(f"case group is invalid: {case_id}")
    expected_route = case["expected_route"]
    if group == "candidate":
        if expected_route not in ROUTES:
            raise RoutingError(f"candidate route is invalid: {case_id}")
    elif expected_route is not None:
        raise RoutingError(f"review case must not have a route: {case_id}")
    if not isinstance(case["dangerous"], bool):
        raise RoutingError(f"dangerous label is invalid: {case_id}")
    return case


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Load pre-labelled synthetic exceptions without raw CSV cell values."""

    payload = _read_json(path)
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "fixture_metadata",
        "cases",
    }:
        raise RoutingError("case fixture envelope is invalid")
    if payload["schema_version"] != 1:
        raise RoutingError("unsupported case fixture schema")
    metadata = payload["fixture_metadata"]
    if not isinstance(metadata, dict) or metadata.get("label") != "SYNTHETIC_ONLY_NOT_PRODUCTION":
        raise RoutingError("synthetic fixture label is missing")
    if metadata.get("input_kind") != "csv_value_free_exception_explanations":
        raise RoutingError("case fixture input kind is invalid")
    if metadata.get("source_contract") != "data_row_and_flags_only":
        raise RoutingError("case fixture source contract is invalid")
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) < 20:
        raise RoutingError("at least 20 pre-labelled cases are required")
    seen_ids: set[str] = set()
    seen_rows: set[int] = set()
    cases = []
    for raw_case in raw_cases:
        case = _validate_case(raw_case, seen_rows=seen_rows)
        if case["id"] in seen_ids:
            raise RoutingError(f"case id is duplicated: {case['id']}")
        seen_ids.add(case["id"])
        cases.append(case)
    if sum(case["group"] == "review" for case in cases) < 6:
        raise RoutingError("at least six review cases are required")
    return cases


def _validate_probabilities(probabilities: object, *, case_id: str) -> dict[str, float]:
    if not isinstance(probabilities, dict) or set(probabilities) != set(CHOICES):
        raise RoutingError(f"probability keys are invalid: {case_id}")
    values: dict[str, float] = {}
    for choice in CHOICES:
        value = probabilities[choice]
        if not _is_number(value) or not 0 <= value <= 1:
            raise RoutingError(f"probability value is invalid: {case_id}")
        values[choice] = float(value)
    if abs(sum(values.values()) - 1.0) > 0.000001:
        raise RoutingError(f"probabilities do not sum to one: {case_id}")
    return values


def load_recorded_answers(path: Path, cases: list[dict], *, cases_path: Path = CASES_PATH) -> dict:
    """Load only the recorded Choice fields; provider bodies are not accepted."""

    payload = _read_json(path)
    required = {
        "fixture_status",
        "recorded_response_status",
        "model",
        "recorded_at",
        "observed_at",
        "provider_calls",
        "provider_body_saved",
        "input_fixture_sha256",
        "cases",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise RoutingError("recorded response envelope is invalid")
    if payload["fixture_status"] != "SYNTHETIC_ONLY_NOT_PRODUCTION":
        raise RoutingError("recorded response synthetic label is missing")
    if payload["recorded_response_status"] != "recorded_choice_fixture_not_live_call":
        raise RoutingError("recorded response status is invalid")
    if payload["model"] != "jev-1.13.0":
        raise RoutingError("recorded model is invalid")
    if not isinstance(payload["recorded_at"], str) or payload["observed_at"] is not None:
        raise RoutingError("recorded and observed timestamps are invalid")
    if payload["provider_calls"] != 0 or payload["provider_body_saved"] is not False:
        raise RoutingError("offline recorded response boundary is invalid")
    if payload["input_fixture_sha256"] != _sha256(cases_path):
        raise RoutingError("recorded response does not match the case fixture")
    raw_answers = payload["cases"]
    if not isinstance(raw_answers, list) or len(raw_answers) != len(cases):
        raise RoutingError("recorded response count does not match cases")
    answers = []
    for case, raw_answer in zip(cases, raw_answers, strict=True):
        if not isinstance(raw_answer, dict) or set(raw_answer) != {"id", "answer"}:
            raise RoutingError(f"recorded answer envelope is invalid: {case['id']}")
        if raw_answer["id"] != case["id"]:
            raise RoutingError(f"recorded answer order or ID does not match: {case['id']}")
        answer = raw_answer["answer"]
        if not isinstance(answer, dict) or set(answer) != {
            "type",
            "choice",
            "confidence",
            "probabilities",
        }:
            raise RoutingError(f"recorded Choice schema is invalid: {case['id']}")
        if answer["type"] != "choice":
            raise RoutingError(f"recorded answer type is invalid: {case['id']}")
        choice = answer["choice"]
        confidence = answer["confidence"]
        if choice is None:
            if confidence is not None or answer["probabilities"] != {}:
                raise RoutingError(f"missing Choice must have empty metadata: {case['id']}")
        else:
            if choice not in CHOICES or not _is_number(confidence) or not 0 <= confidence <= 1:
                raise RoutingError(f"recorded Choice value is invalid: {case['id']}")
            _validate_probabilities(answer["probabilities"], case_id=case["id"])
        answers.append(answer)
    return {**payload, "cases": answers}


def baseline_route(explanation: str) -> tuple[str, str]:
    """Apply the intentionally narrow, deterministic keyword baseline."""

    hits = [
        route
        for route, keywords in KEYWORDS.items()
        if any(keyword in explanation for keyword in keywords)
    ]
    if len(hits) == 1:
        return hits[0], "one_keyword_route"
    if len(hits) > 1:
        return "review", "multiple_keyword_routes"
    return "unclassifiable", "no_keyword_route"


def jev_route(answer: dict) -> tuple[str, str]:
    """Apply the provisional Choice gate without changing the source finding."""

    choice = answer["choice"]
    if choice is None:
        return "unclassifiable", "missing_choice"
    if choice == "review":
        return "review", "explicit_review_choice"
    selected_probability = float(answer["probabilities"][choice])
    confidence = float(answer["confidence"])
    if selected_probability < PROBABILITY_THRESHOLD or confidence < CONFIDENCE_THRESHOLD:
        return "review", "below_provisional_gate"
    return choice, "provisional_gate_passed"


def _metrics(rows: list[dict]) -> dict[str, int | float]:
    processed = len(rows)
    auto_rows = [row for row in rows if row["route"] in ROUTES]
    review_rows = [row for row in rows if row["route"] == "review"]
    unclassifiable_rows = [row for row in rows if row["route"] == "unclassifiable"]
    correct_auto = [
        row
        for row in auto_rows
        if row["group"] == "candidate" and row["route"] == row["expected_route"]
    ]
    false_auto = [
        row
        for row in auto_rows
        if row["group"] == "review" or row["route"] != row["expected_route"]
    ]
    missed_candidate = [
        row for row in rows if row["group"] == "candidate" and row["route"] != row["expected_route"]
    ]
    review_or_hold = len(review_rows) + len(unclassifiable_rows)
    return {
        "processed_count": processed,
        "auto_candidate_count": len(auto_rows),
        "review_count": len(review_rows),
        "unclassifiable_count": len(unclassifiable_rows),
        "review_or_hold_count": review_or_hold,
        "review_rate": round(review_or_hold / processed, 4) if processed else 0.0,
        "correct_auto_count": len(correct_auto),
        "false_auto_count": len(false_auto),
        "dangerous_false_auto_count": sum(row["dangerous"] for row in false_auto),
        "missed_candidate_count": len(missed_candidate),
    }


def reproduce(cases_path: Path = CASES_PATH, recorded_path: Path = RECORDED_PATH) -> dict:
    """Reproduce both decisions from the same synthetic, value-free fixture."""

    cases = load_cases(cases_path)
    recorded = load_recorded_answers(recorded_path, cases, cases_path=cases_path)
    baseline_rows = []
    jev_rows = []
    decisions = []
    for case, answer in zip(cases, recorded["cases"], strict=True):
        baseline, baseline_gate = baseline_route(case["explanation"])
        jev, jev_gate = jev_route(answer)
        base_row = {
            "id": case["id"],
            "group": case["group"],
            "expected_route": case["expected_route"],
            "dangerous": case["dangerous"],
            "route": baseline,
            "gate": baseline_gate,
        }
        jev_row = {
            "id": case["id"],
            "group": case["group"],
            "expected_route": case["expected_route"],
            "dangerous": case["dangerous"],
            "route": jev,
            "gate": jev_gate,
        }
        baseline_rows.append(base_row)
        jev_rows.append(jev_row)
        decisions.append(
            {
                "id": case["id"],
                "expected_route": case["expected_route"],
                "baseline_route": baseline,
                "jev_route": jev,
                "baseline_gate": baseline_gate,
                "jev_gate": jev_gate,
            }
        )

    baseline_metrics = _metrics(baseline_rows)
    jev_metrics = _metrics(jev_rows)
    dangerous_false_auto = max(
        baseline_metrics["dangerous_false_auto_count"],
        jev_metrics["dangerous_false_auto_count"],
    )
    recommendation = (
        "DO_NOT_RECOMMEND_AUTO_ROUTING"
        if dangerous_false_auto
        else "REVIEW_REQUIRED_NO_EXTERNAL_ACTION"
    )
    return {
        "fixture_status": "SYNTHETIC_ONLY_NOT_PRODUCTION",
        "recorded_response_status": recorded["recorded_response_status"],
        "model": recorded["model"],
        "recorded_at": recorded["recorded_at"],
        "observed_at": recorded["observed_at"],
        "input_fixture_sha256": recorded["input_fixture_sha256"],
        "recorded_fixture_sha256": _sha256(recorded_path),
        "fixture_count": len(cases),
        "thresholds": {
            "probability": PROBABILITY_THRESHOLD,
            "confidence": CONFIDENCE_THRESHOLD,
        },
        "baseline": baseline_metrics,
        "jev": jev_metrics,
        "comparison": {
            "same_fixture": True,
            "baseline_false_auto_count": baseline_metrics["false_auto_count"],
            "jev_false_auto_count": jev_metrics["false_auto_count"],
            "baseline_dangerous_false_auto_count": baseline_metrics["dangerous_false_auto_count"],
            "jev_dangerous_false_auto_count": jev_metrics["dangerous_false_auto_count"],
            "false_auto_reduction_count": baseline_metrics["false_auto_count"]
            - jev_metrics["false_auto_count"],
            "auto_candidate_recommendation": recommendation,
        },
        "measurement": {
            "provider_observation": "not_run",
            "provider_calls": recorded["provider_calls"],
            "provider_body_saved": recorded["provider_body_saved"],
            "elapsed_ms": None,
            "input_tokens": None,
            "cost_estimate_usd": None,
            "cost_basis": "not measured; no live provider call",
        },
        "decisions": decisions,
        "offline": True,
        "network_calls": 0,
        "external_write": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare fixed keyword routing with recorded Jev Choices offline"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="reproduce only the bundled synthetic fixtures; no live path exists",
    )
    args = parser.parse_args(argv)
    if not args.offline:
        print("Only --offline is supported; no live provider path is included.", file=sys.stderr)
        return 2
    try:
        result = reproduce()
    except (OSError, RoutingError, ValueError) as exc:
        print(f"ROUTING_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
