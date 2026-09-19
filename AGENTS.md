# Project Instructions

## Purpose

This repository contains small, reproducible business AI recipes. The meeting recipe turns a synthetic transcript into evidence-linked task candidates and requires a separate review input before a temporary local SQLite apply. The CSV recipe reconciles synthetic rows and checks that report prose matches calculated metrics. The Jev recipe replays a recorded synthetic support-triage response and abstains to `review` when its provisional gate is not met.

## Files and verification

- `recipe.py`: deterministic validation, approval binding, and local SQLite application.
- `recipes/csv-to-report/report.py`: standard-library CSV reconciliation CLI.
- `fixtures/`: synthetic transcript, selected model-output fixture, and synthetic review input.
- `recipes/csv-to-report/`: synthetic CSV inputs and CSV recipe documentation.
- `recipes/jev-support-triage/`: synthetic pre-labels, recorded Jev response fields, offline classifier, and optional direct-live contract.
- `run_demo.py`: disposable end-to-end demonstration.
- `verify.py`: exact file manifest, trust-boundary, refusal-path, CSV edge-case, determinism, and count checks.
- `.github/workflows/verify.yml`: Python 3.11 and 3.12 verification.

From the repository root, run `python3 -B verify.py`, `python3 -B run_demo.py`, `python3 -B recipes/csv-to-report/report.py --csv recipes/csv-to-report/sales.csv`, and `python3 -B recipes/jev-support-triage/triage.py --offline` before committing. These commands must finish without network access. The meeting demo expects first insert 2, repeat insert 0, total stored 2; the CSV report expects 4 source rows, 1 missing amount, and a checked total of 4,500 yen; the Jev recipe expects 16 recorded cases, 10 correct automatic single-team decisions, 1 `other` review, and 5 review-gated cases.

## Constraints

Use only synthetic data in tracked files. Do not add credentials, customer data, company artifacts, local paths, or runtime databases. Keep execution offline and preserve the separate human-review input; model output must never grant itself approval. Unknown owners and due dates remain `null`. Do not add an external write path without an explicit design and review of authentication, authorization, idempotency, and rollback behavior.

The Jev response fixture is explicitly recorded provider output, not a new live call. Its offline path must remain key-free and network-free. The optional `--live` path may read only `TYPESAFE_API_KEY` from the environment and may send only the bundled synthetic cases to TypeSafe direct `jev-1.13.0`; it must not log the key or provider body, accept custom input, send replies, or perform any external write. Do not expand Jev to prose generation, arithmetic, date comparison, or automatic approval.
