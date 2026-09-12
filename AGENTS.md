# Project Instructions

## Purpose

This repository contains small, reproducible business AI recipes. The current recipe demonstrates how to turn a synthetic meeting transcript into evidence-linked task candidates, require a separate review input, and apply approved tasks idempotently to a temporary local SQLite database.

## Files and verification

- `recipe.py`: deterministic validation, approval binding, and local SQLite application.
- `fixtures/`: synthetic transcript, selected model-output fixture, and synthetic review input.
- `run_demo.py`: disposable end-to-end demonstration.
- `verify.py`: manifest, trust-boundary, refusal-path, determinism, and count checks.
- `.github/workflows/verify.yml`: Python 3.11 and 3.12 verification.

Run `python3 -B verify.py` and `python3 -B run_demo.py` before committing. Both commands must finish without network access. The expected counts are first insert 2, repeat insert 0, and total stored 2.

## Constraints

Use only synthetic data in tracked files. Do not add credentials, customer data, company artifacts, local paths, or runtime databases. Keep execution offline and preserve the separate human-review input; model output must never grant itself approval. Unknown owners and due dates remain `null`. Do not add an external write path without an explicit design and review of authentication, authorization, idempotency, and rollback behavior.
