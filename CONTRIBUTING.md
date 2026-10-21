# Contributing

Thanks for helping improve CareerFlow. The project is a local-first, single-user application; contributions should preserve that boundary and the existing FastAPI/service/SQLite separation.

## Before opening an issue or pull request

- Use synthetic resumes, vacancies, names, contact details, and attachments in examples and tests.
- Never attach a real resume, vacancy export, database, `.env`, backup, or log containing personal data or credentials.
- Keep product behavior and persistent-data compatibility unless the change specifically requires otherwise.
- For security issues, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

Requirements: Python 3.11 or newer and Node.js 24 or newer for the JavaScript checks. The application itself does not require Node.js.

Install the hash-locked development environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
```

Run the complete local checks:

```bash
.venv/bin/python -m compileall -q careerflow tests run.py
.venv/bin/python -m unittest discover -s tests -v
node --check careerflow/static/app.js
node tests/test_analytics_ui.cjs
node tests/test_ats_ui.cjs
node tests/test_responsive_ui.cjs
node tests/test_spa_workflows.cjs
.venv/bin/ruff check careerflow tests run.py
.venv/bin/bandit -r careerflow run.py -ll
.venv/bin/pip-audit --local
```

The tests use temporary SQLite and storage paths. Do not point test settings at `data/` or `storage/`.

## Pull requests

- Keep changes focused and explain the user-visible behavior or risk being addressed.
- Add regression tests for behavior changes and failure paths.
- Update the README or canonical docs when setup, environment variables, data handling, or supported behavior changes.
- Run the checks above and report any skipped command and why.
- Do not commit `.env`, databases, generated runtime files, real user data, or files under `temporary/`.
- Do not rewrite shared Git history or change GitHub visibility as part of a pull request.
