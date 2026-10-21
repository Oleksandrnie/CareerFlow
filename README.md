# CareerFlow

CareerFlow is a local-first workspace for organizing a job search. Track vacancies, keep a history of tailored resume versions, compare a resume with a vacancy, and collect notes and interview events in one place.

**Status:** early-stage personal project. Version `0.1.0` is proposed for the first release and has not been published.

[English](README.md) · [Русский](README.ru.md)

All records and uploaded files stay on your computer by default. The optional Codex integration runs only after you explicitly start an action; the selected resume, vacancy and attachment context may be sent to the model configured in your local Codex CLI account.

## What it does

- Track vacancies through Saved, Applied, Interview, Waiting, Offer and Rejected, with an event timeline and interview rounds.
- Import vacancy descriptions from pasted text, supported documents, or a public static HTML page; review the cleaned text before saving.
- Keep a global Master Resume and immutable, vacancy-specific resume versions with source lineage.
- Run a local heuristic ATS comparison that records the resume version and vacancy-description snapshot used for the analysis.
- Save dated notes, local attachments, and portable Markdown reports.
- Optionally ask the local Codex CLI to analyze a vacancy, match or improve a resume, review ATS findings, or draft a tailored resume. Results are read-only until you explicitly save a new resume version.
- Use the browser interface in English or Russian, with light and dark themes and responsive layouts.

## Architecture

```text
Browser SPA (vanilla JavaScript)
        │ same-origin requests
        ▼
FastAPI routes → domain services → SQLite + local file storage
        │
        └── optional, explicit Codex CLI action
```

The project uses Python 3.11 or newer, FastAPI, SQLite from the Python standard library, vanilla JavaScript and CSS. Documents are processed locally. Vacancy URL import fetches public static HTML and does not run page JavaScript or use site credentials.

## Quick start

Requirements: Python 3.11 or newer. For AI actions, install and authenticate the Codex CLI separately; the core application does not require it.

```sh
git clone https://github.com/Oleksandrnie/CareerFlow.git
cd CareerFlow
./start.sh
```

Open <http://127.0.0.1:8000>. Press `Ctrl+C` to stop the server. The first run creates local `data/` and `storage/` directories.

### Manual installation

```sh
python3 -m venv .venv
# macOS/Linux
.venv/bin/python -m pip install -e .
.venv/bin/python run.py
```

On Windows, use `.venv\Scripts\python.exe` for the commands after environment creation.

### Configuration

CareerFlow reads optional `KEY=VALUE` settings from `.env` in the project root. Environment variables already set by your shell take precedence. See [`.env.example`](.env.example) for a copyable template.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAREERFLOW_HOST` | `127.0.0.1` | Bind address. Keep loopback for a single-user local setup. |
| `CAREERFLOW_PORT` | `8000` | Local HTTP port. |
| `CAREERFLOW_RELOAD` | `0` | Set to `1` to enable Uvicorn reload for development. |
| `CAREERFLOW_DATA_DIR` | `<project>/data` | Directory for the SQLite database. |
| `CAREERFLOW_STORAGE_DIR` | `<project>/storage` | Directory for original documents, attachments and reports. |
| `CAREERFLOW_DATABASE` | `<data dir>/careerflow.db` | Optional explicit SQLite database path. |
| `CAREERFLOW_CODEX_BINARY` | `codex` | Codex CLI executable name or path. |
| `CAREERFLOW_CODEX_TIMEOUT` | `180` | Codex action timeout in seconds. |
| `CAREERFLOW_CODEX_MODEL`, `CAREERFLOW_CODEX_EFFORT` | `gpt-5.6-luna`, `low` | Default model and reasoning effort for general Codex actions. |
| `CAREERFLOW_CLEANING_CODEX_MODEL`, `CAREERFLOW_CLEANING_CODEX_EFFORT` | `gpt-5.6-luna`, `low` | Vacancy-cleaning model and effort. |
| `CAREERFLOW_CLEANING_ESCALATION_CODEX_MODEL`, `CAREERFLOW_CLEANING_ESCALATION_CODEX_EFFORT` | `gpt-5.6-sol`, `medium` | Optional escalation profile for vacancy cleaning. |

Do not put API keys, passwords or access tokens in `.env`. CareerFlow does not need a provider API key; the Codex CLI uses its own local authentication.

### Network access

The service has no authentication. The default loopback binding limits access to the current computer. LAN binding is available only for a trusted private network and exposes all application data to other reachable devices. Do not expose CareerFlow to the public Internet. Browser write requests are restricted to same-origin origins, and requests with public Host names are rejected; these checks do not provide user authentication.

## Try the demo scenario

The files in [`examples/`](examples/) are fictional and contain no real candidate or employer data:

1. Add `examples/demo-vacancy.txt` from the **Add vacancy** form.
2. Add `examples/demo-resume.md` to **Master Resume**.
3. Create a vacancy-specific resume version, run the ATS comparison, then add a note or interview event.
4. Export the vacancy as Markdown to see the local report format.

No Codex account or external service is needed for this scenario.

## Development and checks

Create the hash-locked development environment and run the project checks:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
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

`requirements-dev.lock` pins the full development dependency tree and package hashes from `pyproject.toml`.

The Node checks use Node.js 24 or newer. Tests use temporary database and storage directories. Never put private resumes or vacancy material into tests, examples, screenshots, or issue reports. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution instructions and [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Privacy and limitations

- CareerFlow is a single-user local application. It has no authentication, multi-user isolation, hosted service, cloud sync or built-in account system.
- The application does not automatically send records to an external service. Explicitly started Codex actions can send the context shown in the interface through the locally configured CLI account.
- Vacancy URL import supports public static HTML only; authenticated pages, CAPTCHA, JavaScript-rendered pages and OCR are not supported.
- PDF import requires a text layer. Audio is stored as a file and is not transcribed.
- ATS results are heuristic guidance, not hiring predictions. Historical results retain the resume and vacancy-description provenance used for the analysis.
- Before upgrading, make a backup of `data/` and `storage/` together. The app runs backward-compatible SQLite schema migrations on startup.

## Roadmap

The project is at an early MVP stage. Possible next steps include more import and export options, additional workflow polish, and deeper documentation. There is no committed public roadmap or release date; feature requests are welcome through GitHub Issues.

## License and author

CareerFlow is released under the [MIT License](LICENSE). Copyright © 2026 Oleksandr Niemchenko.

Contributions are welcome under the same license. Start with [CONTRIBUTING.md](CONTRIBUTING.md); please use synthetic data in examples and bug reports.
