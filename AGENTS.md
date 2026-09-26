# CareerFlow Agent Instructions

## Authority and operating mode

These instructions apply to execution work in this repository.

- In conversation mode—questions, explanations, planning, brainstorming, or code discussion without requested changes—use the model selected by the user. Do not delegate or escalate solely because the project is open.
- Execution mode begins when the user requests implementation, modification, migration, review, audit, or another action affecting project state.
- An explicit user choice of model, effort, or no-delegation policy overrides automatic model routing for that task only. It does not override architecture, scope, Git, safety, security, testing, validation, documentation, or Definition of Done requirements.
- Priority: explicit task instruction → task-specific repository rules → default routing below → current conversation model.

Before execution:

1. Read this file and the relevant parts of `README.md`.
2. Establish scope, acceptance criteria, affected boundaries, and validation.
3. Select routing from the table below.
4. If model-specific subagents are available, delegate to the selected executor unless the user overrides delegation. Give agents only the necessary context, constraints, relevant files, and validation criteria.
5. Keep routing commentary brief unless the user asks for detail.

## Model routing

A bounded task has sufficiently clear scope, expected result, architectural boundaries, acceptance criteria, and validation. A fine-grained edit is localized and has a clear result.

Choose the least expensive model likely to complete the task correctly:

| Work | Default |
| --- | --- |
| Fine-grained edit; simple HTML/CSS/UI | GPT-5.6 Luna Low |
| Coordinated UI/responsive work; bounded work using established patterns | GPT-5.6 Luna Medium |
| Bounded implementation with clear scope, boundaries, affected components, acceptance criteria, and validation | GPT-5.6 Luna High |
| Backend, API, database, business logic, integrations, complex debugging, substantial refactoring, persistence/lifecycle, architecture-sensitive or judgment-heavy work | GPT-5.6 Sol High |
| Routine independent review | GPT-6 Sol Medium |
| Substantial multi-file or regression-sensitive audit | GPT-6 Sol High |
| Unusually deep or high-risk audit | GPT-6 Sol xHigh, only when justified |
| Major architectural uncertainty, migration, data-loss/security risk, or high-risk cross-system decision | GPT-6 Astra, effort chosen for the task |

GPT-6 Luna is not an automatic routing target, but the user may select it explicitly.

Use Luna when the implementation approach is already clear; use Sol when the model must determine the correct approach. Escalate Luna to Sol when scope becomes ambiguous, root cause is unknown, architecture or migration decisions appear, subsystem boundaries expand, persistence/lifecycle risk grows, or repeated validation failures suggest that retries are no longer economical.

For mixed tasks, split work along natural technical boundaries when useful; do not promote the entire task or fragment a small tightly coupled task unnecessarily. Use multiple subagents only for concrete value such as independent parallel work, natural subsystem separation, approach comparison, or an approved independent review. Do not create agent swarms.

## Independent review and architectural escalation

Validation is the primary assurance mechanism. AI review is an optional additional layer.

- GPT-6 Sol review runs only when the user requests it or approves a clearly explained recommendation.
- A reviewer must independently check requirements, diff, regressions, edge cases, architectural boundaries, and tests without assuming the implementation is correct.
- Use Medium for bounded review, High for substantial or regression-sensitive review, and xHigh only for unusually deep/high-risk audits or explicit user request.
- GPT-6 Astra is not a routine final reviewer. Use it only for architectural/high-risk questions, on direct user request or after explicit approval.
- Do not automatically chain developer, reviewer, second reviewer, and Astra.

## Project map and invariants

Use `README.md` as the canonical product overview and source for setup, runtime data, architecture, and validation commands. Use `pyproject.toml` for supported Python and dependency constraints. Read affected modules and their tests before changing behavior.

CareerFlow is a local-first application:

```text
Vanilla browser SPA → FastAPI routes → domain/service modules
                                  → SQLite metadata + local storage
```

Preserve these boundaries and invariants:

- Keep HTTP concerns in `routes_*.py`, domain behavior in the corresponding service modules, application composition in `api.py`, and SQLite/schema handling in `db.py`.
- Continue using standard `sqlite3` unless an explicitly approved architectural change requires otherwise.
- Treat `data/` and `storage/` as user-owned runtime state. Never use, rewrite, delete, or migrate the real working data during tests or routine development.
- Startup schema changes must remain idempotent and backward-compatible with existing databases. Preserve legacy records unless an approved migration says otherwise.
- Resume versions are historical records: preserve version uniqueness, source lineage and cycle guards, vacancy scoping, and at most one submitted resume per vacancy.
- ATS results preserve the resume and vacancy-description provenance used for analysis. Changing the description invalidates the current match while retaining historical analysis.
- Preserve timeline events for domain actions that currently create them.
- Archive is non-destructive. Permanent vacancy deletion must retain the explicit resume-preservation policy and keep database/file cleanup consistent.
- Preserve path containment, filename sanitization, upload limits, and cleanup of partially written files.
- Codex execution remains non-interactive, read-only, ephemeral, validated, and `shell=False`. It returns text and must not mutate CVs, vacancies, or project files automatically.
- Do not weaken local-first behavior or send user data externally except through an explicit user-triggered integration already documented by the product.

## Implementation, documentation, and safety

- Make the smallest coherent change that satisfies the acceptance criteria.
- Follow existing patterns unless the task explicitly requires an architectural change.
- Preserve unrelated and pre-existing worktree changes; inspect `git status` and the final diff.
- Do not run destructive Git or filesystem operations, rewrite history, or commit unrelated changes.
- Follow the user's requested commit strategy. Temporary planning state must remain local and must not be committed.
- Update `README.md` when user-visible behavior, setup, environment variables, data/backup behavior, architecture, or validation commands change.
- Do not duplicate detailed architecture in this file; add or update a canonical document if future complexity requires one.

## Validation

Run checks proportionate to the change. The full project validation is:

```bash
.venv/bin/python -m compileall -q careerflow tests run.py
.venv/bin/python -m unittest discover -s tests -v
node --check careerflow/static/app.js
node tests/test_ats_ui.cjs
node tests/test_spa_workflows.cjs
```

Use targeted tests while iterating, then run every relevant command above. Cross-layer, persistence, lifecycle, or broadly shared UI changes normally require the full suite. Tests must use temporary SQLite and storage paths, never working data. Perform focused manual UI/API checks when automation does not cover the changed behavior.

## Definition of Done

A task is complete when:

- acceptance criteria and architectural boundaries are satisfied;
- relevant automated, static, integration, and manual checks pass;
- compatibility, persistence, lifecycle, and security invariants remain intact;
- documentation is updated where required;
- the final diff is scoped and contains no accidental or unrelated changes;
- any temporary task state is removed;
- remaining risks or unverified checks are reported explicitly.
