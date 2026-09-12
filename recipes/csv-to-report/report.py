"""Deterministic CSV-to-report example using synthetic business data only."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

REQUIRED_COLUMNS = ("record_id", "department", "amount_yen")
STATUS_VALUES = {"EMPTY_INPUT", "OK", "REVIEW_REQUIRED"}
INTEGER_PATTERN = re.compile(r"[0-9]+\Z")


class CSVReportError(ValueError):
    """The input or report contract cannot be accepted safely."""


class NarrativeMismatch(CSVReportError):
    """The prose does not contain the calculated numbers exactly."""


def _empty_metrics() -> dict[str, int | str]:
    return {
        "status": "EMPTY_INPUT",
        "source_rows": 0,
        "valid_amount_rows": 0,
        "missing_amount_rows": 0,
        "invalid_amount_rows": 0,
        "duplicate_record_rows": 0,
        "total_amount_yen": 0,
    }


def _calculate_status(metrics: dict[str, int | str]) -> str:
    if metrics["source_rows"] == 0:
        return "EMPTY_INPUT"
    quality_flags = (
        metrics["missing_amount_rows"],
        metrics["invalid_amount_rows"],
        metrics["duplicate_record_rows"],
    )
    return "OK" if not any(quality_flags) else "REVIEW_REQUIRED"


def analyze_csv_text(csv_text: str) -> dict[str, int | str]:
    """Calculate reconciliation metrics from a CSV string.

    ``amount_yen`` accepts non-negative integer text. Blank values are missing;
    non-blank values that are not integers are invalid and are excluded from the
    total. Repeated ``record_id`` rows remain in the source total and are flagged
    instead of being silently deduplicated.
    """

    if not isinstance(csv_text, str):
        raise CSVReportError("CSV input must be text")

    try:
        reader = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            return _empty_metrics()
        if len(fieldnames) != len(set(fieldnames)):
            raise CSVReportError("CSV header contains duplicate columns")
        missing_columns = set(REQUIRED_COLUMNS) - set(fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise CSVReportError(f"CSV is missing required columns: {missing}")

        metrics = _empty_metrics()
        seen_ids: set[str] = set()
        for row in reader:
            if None in row:
                raise CSVReportError("CSV row has more values than its header")
            metrics["source_rows"] += 1

            record_id = row.get("record_id")
            if not isinstance(record_id, str) or not record_id.strip():
                raise CSVReportError("record_id must not be empty")
            record_id = record_id.strip()
            if record_id in seen_ids:
                metrics["duplicate_record_rows"] += 1
            else:
                seen_ids.add(record_id)

            raw_amount = row.get("amount_yen")
            if raw_amount is None or not raw_amount.strip():
                metrics["missing_amount_rows"] += 1
                continue
            amount_text = raw_amount.strip()
            if not INTEGER_PATTERN.fullmatch(amount_text):
                metrics["invalid_amount_rows"] += 1
                continue
            try:
                amount = int(amount_text)
            except ValueError:
                metrics["invalid_amount_rows"] += 1
                continue
            metrics["valid_amount_rows"] += 1
            metrics["total_amount_yen"] += amount
    except csv.Error as exc:
        raise CSVReportError(f"CSV parsing failed: {exc}") from exc

    metrics["status"] = _calculate_status(metrics)
    return metrics


def _metric_int(metrics: dict[str, int | str], key: str) -> int:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CSVReportError(f"Metric {key} must be a non-negative integer")
    return value


def _validated_metrics(metrics: dict[str, int | str]) -> dict[str, int | str]:
    if not isinstance(metrics, dict):
        raise CSVReportError("Metrics must be an object")
    for key in (
        "source_rows",
        "valid_amount_rows",
        "missing_amount_rows",
        "invalid_amount_rows",
        "duplicate_record_rows",
        "total_amount_yen",
    ):
        _metric_int(metrics, key)
    status = metrics.get("status")
    if not isinstance(status, str) or status not in STATUS_VALUES:
        raise CSVReportError("Metric status is invalid")
    return metrics


def render_narrative(metrics: dict[str, int | str]) -> str:
    """Render the fixed prose fixture used as the AI-writing boundary."""

    metrics = _validated_metrics(metrics)
    return (
        "CSV集計では、"
        f"データ行数は{_metric_int(metrics, 'source_rows')}行、"
        f"金額が有効な行は{_metric_int(metrics, 'valid_amount_rows')}行、"
        f"欠損は{_metric_int(metrics, 'missing_amount_rows')}件、"
        f"数値エラーは{_metric_int(metrics, 'invalid_amount_rows')}件、"
        f"重複IDの後続行は{_metric_int(metrics, 'duplicate_record_rows')}件、"
        f"合計金額は{_metric_int(metrics, 'total_amount_yen'):,}円です。"
        f"状態は{metrics['status']}です。"
    )


def _extract_number(narrative: str, label: str, unit: str) -> int:
    pattern = re.compile(rf"{re.escape(label)}\s*(?:は|:|：)\s*([0-9][0-9,]*)\s*{re.escape(unit)}")
    matches = pattern.findall(narrative)
    if len(matches) != 1:
        raise NarrativeMismatch(f"Narrative must contain exactly one value for {label}")
    return int(matches[0].replace(",", ""))


def verify_narrative(narrative: str, metrics: dict[str, int | str]) -> bool:
    """Verify every report number and status against deterministic metrics."""

    if not isinstance(narrative, str) or not narrative.strip():
        raise NarrativeMismatch("Narrative must be non-empty text")
    metrics = _validated_metrics(metrics)
    expected_fields = (
        ("データ行数", "行", "source_rows"),
        ("金額が有効な行", "行", "valid_amount_rows"),
        ("欠損", "件", "missing_amount_rows"),
        ("数値エラー", "件", "invalid_amount_rows"),
        ("重複IDの後続行", "件", "duplicate_record_rows"),
        ("合計金額", "円", "total_amount_yen"),
    )
    for label, unit, key in expected_fields:
        observed = _extract_number(narrative, label, unit)
        expected = _metric_int(metrics, key)
        if observed != expected:
            raise NarrativeMismatch(f"{key}: narrative={observed}, calculated={expected}")

    status_matches = re.findall(r"状態\s*(?:は|:|：)\s*([A-Z_]+)", narrative)
    if len(status_matches) != 1 or status_matches[0] != metrics["status"]:
        raise NarrativeMismatch(
            f"status: narrative={status_matches[0] if status_matches else None}, "
            f"calculated={metrics['status']}"
        )
    return True


def build_report(csv_text: str, narrative: str | None = None) -> dict[str, object]:
    """Build a report and reject prose until its numbers reconcile."""

    metrics = analyze_csv_text(csv_text)
    report_text = render_narrative(metrics) if narrative is None else narrative
    verify_narrative(report_text, metrics)
    return {
        "metrics": metrics,
        "narrative": report_text,
        "narrative_verified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile a synthetic CSV into a checked report")
    parser.add_argument("--csv", required=True, type=Path, help="Synthetic CSV input")
    args = parser.parse_args(argv)
    try:
        result = build_report(args.csv.read_text(encoding="utf-8"))
    except (CSVReportError, OSError, UnicodeError) as exc:
        print(
            json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
