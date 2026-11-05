# CareerFlow ATS redesign — Astra audit and implementation brief

This document consolidates the Astra architecture audit, the manager-resume skill review, the approved ATS/Codex requirements, and the implementation decisions on `codex/ats-redesign`.

## Contents

- [Audit findings](#audit-findings)
- [Design conclusions](#design-conclusions)
- [Functional specification](#functional-specification)
- [Implementation map](#implementation-map)
- [Validation and open limits](#validation-and-open-limits)

## Audit findings

### Current ATS measures text overlap, not managerial quality

The existing local matcher is a deterministic lexical heuristic. It can identify explicit vacancy phrases and likely resume evidence, but it cannot reliably infer role family, grade, personal attribution, achievement causality, or semantic fit. Its percentage is not a hiring probability and should remain clearly distinct from a manager-resume quality score.

### Existing ATS history is vacancy-bound

`ats_analyses` requires both a vacancy and a match percentage. It cannot represent a resume-only audit or an assessment with insufficient input. A new assessment history is needed rather than overloading the existing table or changing the meaning of historical ATS rows.

### Broad AI context can mix source material

The report-building path can include the working resume, another resume referenced by ATS, attachments, notes, and prior AI responses. A focused audit must use only the explicitly selected resume version. A vacancy match may add only the confirmed description for that specific vacancy.

### Prompt language and result routing were coupled to prompt text

Built-in prompts were English-only, and AI match rendering used an English prefix check. Translating prompts without a stable action/template identity could break old result rendering. User-edited prompt text also must survive a UI language change.

### Assessment output needs source and deletion lifecycle

An asynchronous model run can finish after its resume or vacancy changes. Its result must be stored as historical evidence with source hashes/snapshots, rather than overwriting a current vacancy score. Saved evidence quotes also need a deletion policy when a resume is removed.

### The skill must be adapted to the available inputs

`Grill My Resume as Manager` is calibrated for project, delivery, technical, and product-manager resumes. It calls for line references, XYZ evidence review, six named anti-personas, role-family and grade-inflation checks, a 10-second recruiter read, a stated structure rubric, and at most five fix directions. It prohibits paste-ready rewritten resume bullets. Its multi-vacancy pool mode is not appropriate for one vacancy, and plain text cannot validate visual layout.

## Design conclusions

- Keep the local lexical ATS matcher, manager-resume audit, and vacancy-specific match as three distinct outputs.
- Use an additive, versioned assessment record with assessment kind, rubric and prompt versions, model/effort, locale, selected resume ID/version/hash, and optional vacancy description snapshot/revision.
- For manager audit, use only the selected resume. For vacancy match, use that resume plus the confirmed description for that vacancy. Do not reuse broad report context.
- Preserve completed assessments as historical records. Mark them stale if the source changes; redact the assessment content if the source resume is deleted.
- Compute the manager-audit weighted total in application code from the skill's six axes. Do not mix this quality score with vacancy fit or call either a probability of hiring.
- Built-in prompts follow the selected interface language. Preserve user-edited text on language changes. Use stable action identifiers rather than parsing prompt wording.
- Keep Codex explicit and non-interactive. Results do not modify a resume automatically; the user reviews and saves any resulting draft as a separate immutable version.

## Functional specification

### Localized AI/Codex prompts

- Provide Russian and English built-in templates for vacancy analysis, resume improvement, ATS review, interview preparation, interview-note analysis, and tailored-resume drafting.
- Keep user-authored prompt text when the interface language changes; refresh only an untouched built-in prompt.
- Keep vacancy matching in the ATS review workflow, where selected-source and provenance rules can be enforced.
- Preserve legacy AI-run history display for previously saved actions.

### Manager-resume audit

- Run only after explicit user action and against one selected, non-deleted resume version.
- Number resume lines as stable `L1…Ln` references.
- Classify evidence as achievement, process, scope, or noise. Treat achievement as PASS only when action, change, and measurable result/artifact/time are evidenced; check personal attribution and employer-vanity metrics.
- Assess the six named signals: Project administrator, Project proxy, Ritual agile PM, Unimmersed delivery manager, Manager-router, and General management without domain. Each uses `CLEAR`, `PARTIAL`, or `NONE` with supporting quotes/references.
- Compare claimed and supported role family and grade; include grade-inflation checks and five 10-second recruiter checks.
- State and apply Rubric T where the text permits a structural review; call out what cannot be judged from plain text.
- Return the six skill axes: Evidence, RoleClarity, AntiPersonaClean, TenSecondRead, KeywordFit, and Structure. Use weights 0.25, 0.20, 0.20, 0.15, 0.10, and 0.10 respectively; compute the overall percentage in application code.
- Return no more than five improvement directions. Do not produce replacement bullets or paste-ready CV sections.

### Vacancy-specific match

- Require a confirmed vacancy description and a selected resume version belonging to that vacancy or a Master Resume version.
- Compare each vacancy requirement with resume evidence. Return `covered`, `partial`, `not_evidenced`, or `insufficient_input`, with resume line references and a short vacancy quote.
- Treat missing evidence as “not evidenced in this version,” not proof that the candidate lacks the skill.
- Do not calculate a synthetic overall match percentage or probability of employment. Report insufficient input instead of fabricating precision.

### History, privacy, and edits

- Store assessment type, engine, rubric version, prompt template ID/version, language, model, reasoning effort, resume version/hash, and vacancy snapshot/revision when applicable.
- Mark records historical when the resume hash or vacancy description/revision changes.
- On resume deletion, retain the historical record identity but redact its result and response evidence.
- Keep user review as the boundary for edits. Tailored output can enter the existing editable draft flow; saving creates a new immutable version with its source lineage.
- Send no content to Codex automatically. An explicit Codex assessment sends only the selected resume and, for a match, the confirmed vacancy description.

## Implementation map

- Localized built-in prompts and dirty-text preservation: [`careerflow/static/app.js`](../careerflow/static/app.js).
- ATS assessment service, source snapshots/hashes, result validation, and deterministic score calculation: [`careerflow/ats_review.py`](../careerflow/ats_review.py).
- Additive SQLite schema and migration version 11: [`careerflow/db.py`](../careerflow/db.py).
- Assessment HTTP endpoints and app registration: [`careerflow/routes_ats.py`](../careerflow/routes_ats.py), [`careerflow/api.py`](../careerflow/api.py).
- Resume-deletion redaction: [`careerflow/resumes.py`](../careerflow/resumes.py).
- ATS review controls and result rendering: [`careerflow/static/app.js`](../careerflow/static/app.js), [`careerflow/static/app.css`](../careerflow/static/app.css).
- Focused API/provenance/deletion tests: [`tests/test_ats_review.py`](../tests/test_ats_review.py), [`tests/test_ats_ui.cjs`](../tests/test_ats_ui.cjs), [`tests/test_spa_workflows.cjs`](../tests/test_spa_workflows.cjs).
- Product documentation: [`README.md`](../README.md), [`README.ru.md`](../README.ru.md).

## Validation and open limits

- The implementation was validated with `compileall`, 115 Python unit tests, JavaScript syntax validation, and the analytics, ATS, responsive-layout, and SPA workflow checks.
- Codex assessments still depend on the user's local Codex CLI being installed and authenticated. The browser UI was not used; the running app's LAN health endpoint was checked with an HTTP request.
- The manager score is a rubric score, not a predictive hiring model. Vacancy matching deliberately has no single percentage.
- The local lexical ATS remains a limited text heuristic; semantic interpretation is confined to the explicit Codex assessment.
