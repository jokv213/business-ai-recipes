# Project Instructions

## Purpose

This repository contains small, reproducible business AI recipes. The meeting recipe turns a synthetic transcript into evidence-linked task candidates and requires a separate review input before a temporary local SQLite apply. The CSV recipe reconciles synthetic rows and checks that report prose matches calculated metrics. The Jev recipes replay recorded synthetic Choice fixtures and abstain to `review` when their provisional gates are not met. The CSV exception recipe classifies only value-free synthetic explanations; Python remains the owner of all CSV metrics and findings.

## Files and verification

- `recipe.py`: deterministic validation, approval binding, and local SQLite application.
- `recipes/csv-to-report/report.py`: standard-library CSV reconciliation CLI.
- `fixtures/`: synthetic transcript, selected model-output fixture, and synthetic review input.
- `recipes/csv-to-report/`: synthetic CSV inputs and CSV recipe documentation.
- `recipes/jev-support-triage/`: synthetic pre-labels, recorded Jev response fields, offline classifier, and optional direct-live contract.
- `recipes/jev-csv-exception-routing/`: 24 synthetic value-free exception explanations, recorded Jev Choice fields, fixed keyword baseline, and offline comparison.
- `run_demo.py`: disposable end-to-end demonstration.
- `verify.py`: exact file manifest, trust-boundary, refusal-path, CSV edge-case, determinism, and both Jev recipe count checks.
- `.github/workflows/verify.yml`: Python 3.11 and 3.12 verification.

From the repository root, run `python3 -B verify.py`, `python3 -B run_demo.py`, `python3 -B recipes/csv-to-report/report.py --csv recipes/csv-to-report/sales.csv`, `python3 -B recipes/jev-support-triage/triage.py --offline`, and `python3 -B recipes/jev-csv-exception-routing/route.py --offline` before committing. These commands must finish without network access. The meeting demo expects first insert 2, repeat insert 0, total stored 2; the CSV report expects 4 source rows, 1 missing amount, and a checked total of 4,500 yen; the support-triage Jev recipe expects 16 recorded cases, 10 correct automatic single-team decisions, 1 `other` review, and 5 review-gated cases; the CSV exception recipe expects 24 cases, baseline false-auto 3, recorded-Jev false-auto 0, and `DO_NOT_RECOMMEND_AUTO_ROUTING`.

## Constraints

Use only synthetic data in tracked files. Do not add credentials, customer data, company artifacts, local paths, or runtime databases. Keep execution offline and preserve the separate human-review input; model output must never grant itself approval. Unknown owners and due dates remain `null`. Do not add an external write path without an explicit design and review of authentication, authorization, idempotency, and rollback behavior.

The support-triage Jev response fixture is explicitly recorded provider output, not a new live call. Its offline path must remain key-free and network-free; its optional `--live` path may read only `TYPESAFE_API_KEY` and may send only bundled synthetic cases, without logging the key or provider body, accepting custom input, sending replies, or performing any external write. The CSV exception fixture is stricter: it has no live path at all, and its recorded `jev-1.13.0` Choice fields are synthetic recorded values with `observed_at=null`. Do not expand either Jev recipe to prose generation, arithmetic, date comparison, automatic correction, external sending, or automatic approval. The CSV exception recipe must not replace or modify `recipes/csv-to-report/report.py`.
