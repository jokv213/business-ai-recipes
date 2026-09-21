# Project Instructions

## Purpose

This repository contains small, reproducible business AI recipes. The meeting recipe turns a synthetic transcript into evidence-linked task candidates and requires a separate review input before a temporary local SQLite apply. The CSV recipe reconciles synthetic rows and checks that report prose matches calculated metrics. The Jev recipes replay recorded synthetic Choice fixtures and abstain to `review` when their provisional gates are not met. The CSV exception recipe classifies only value-free synthetic explanations; Python remains the owner of all CSV metrics and findings.

## Files and verification

- `recipe.py`: deterministic validation, approval binding, and local SQLite application.
- `recipes/meeting-line-judgment/recipe.py`: offline-first Jev line-classification candidate; the optional live path is synthetic-only and never performs business writes.
- `recipes/csv-to-report/report.py`: standard-library CSV reconciliation CLI.
- `fixtures/`: synthetic transcript, selected model-output fixture, human review input, and the explicitly non-live meeting-line judgment fixture.
- `recipes/csv-to-report/`: synthetic CSV inputs and CSV recipe documentation.
- `recipes/jev-support-triage/`: synthetic pre-labels, recorded Jev response fields, offline classifier, and optional direct-live contract.
- `recipes/jev-csv-exception-routing/`: 24 synthetic value-free exception explanations, recorded Jev Choice fields, fixed keyword baseline, and offline comparison.
- `run_demo.py`: disposable end-to-end demonstration.
- `verify.py`: exact file manifest, trust-boundary, refusal-path, Jev judgment/abstention, CSV edge-case, determinism, and all Jev recipe count checks.
- `.github/workflows/verify.yml`: Python 3.11 and 3.12 verification.

From the repository root, run `python3 -B verify.py`, `python3 -B run_demo.py`, `python3 -B recipes/meeting-line-judgment/recipe.py`, `python3 -B recipes/csv-to-report/report.py --csv recipes/csv-to-report/sales.csv`, `python3 -B recipes/jev-support-triage/triage.py --offline`, and `python3 -B recipes/jev-csv-exception-routing/route.py --offline` before committing. These commands must finish without network access. The meeting demo expects first insert 2, repeat insert 0, total stored 2; the line-judgment recipe expects 1 action candidate and 5 review rows; the CSV report expects 4 source rows, 1 missing amount, and a checked total of 4,500 yen; the support-triage Jev recipe expects 16 recorded cases, 10 correct automatic single-team decisions, 1 `other` review, and 5 review-gated cases; the CSV exception recipe expects 24 cases, baseline false-auto 3, recorded-Jev false-auto 0, and `DO_NOT_RECOMMEND_AUTO_ROUTING`.

## Constraints

Use only synthetic data in tracked files. Do not add credentials, customer data, company artifacts, local paths, or runtime databases. Keep the default execution offline and preserve the separate human-review input; model output must never grant itself approval. Unknown owners and due dates remain `null`. The Jev line recipe must not extract or persist dates, owners, or numbers, and its optional `--live` path may use only `TYPESAFE_API_KEY`, direct `jev-1.13.0`, and the bundled synthetic lines. It must not print or persist keys, authorization headers, or provider bodies, and must not reply, approve, register tasks, or perform other business writes. Do not add any other external write path without an explicit design and review of authentication, authorization, idempotency, and rollback behavior.

The support-triage Jev response fixture is explicitly recorded provider output, not a new live call. Its offline path must remain key-free and network-free; its optional `--live` path may read only `TYPESAFE_API_KEY` and may send only bundled synthetic cases, without logging the key or provider body, accepting custom input, sending replies, or performing any external write. The CSV exception fixture is stricter: it has no live path at all, and its recorded `jev-1.13.0` Choice fields are synthetic recorded values with `observed_at=null`. Do not expand either Jev recipe to prose generation, arithmetic, date comparison, automatic correction, external sending, or automatic approval. The CSV exception recipe must not replace or modify `recipes/csv-to-report/report.py`.

The line-judgment fixture is explicitly hand-authored synthetic data, not a new live call. Its offline path remains key-free and network-free; its optional `--live` path may read only `TYPESAFE_API_KEY` and may send only the bundled six synthetic lines to direct `jev-1.13.0`. It must not extract or persist dates, owners, or numbers, and must not log the key, authorization headers, provider body, replies, approvals, task registrations, or any other business write. Do not treat a Jev result as an approval or publication decision.
