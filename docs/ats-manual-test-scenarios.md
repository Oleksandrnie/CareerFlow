# CareerFlow ATS — manual test scenarios

Use this guide to explore the ATS redesign without needing to judge every output from scratch. Start with the short checks, then run the guided scenario if you want comparable feedback. Use only the fictional test data below when sending content to Codex.

## Before testing

- On the phone, connect to the same trusted Wi-Fi network as the computer and open `http://192.168.0.102:8765`.
- CareerFlow has no login. Anyone who can reach this address can view and change its data. Avoid public or guest Wi-Fi.
- Do not send a personal resume to Codex just for a smoke test. Use the synthetic resume below; Codex runs only after you explicitly press an assessment button.
- The app can save local ATS history and test records. Delete only the synthetic resume/vacancy created for this scenario if you want to clean up.

## Quick exploration — choose any order

### Q1. Phone layout and basic navigation

Open the app on the phone and move between Vacancies, Master Resume, Analytics, and a vacancy's Resume / ATS / AI / Codex tabs.

**Look for:** no clipped controls or sideways page scrolling; vacancy list opens and closes; selected tab and vacancy remain visible; the ATS resume selector and action buttons are reachable.

### Q2. Language and built-in prompts

Open AI / Codex, note a built-in prompt, switch the interface language, and return to AI / Codex. Then type a short custom sentence into the prompt and switch language again.

**Look for:** built-in prompt changes to match the interface language; the manually edited sentence remains unchanged. Switching language should keep the same vacancy and tab.

### Q3. Resume selection

In a vacancy's ATS tab, change the selected resume between a Master Resume version and a Vacancy Resume version, if both exist.

**Look for:** the selector names the kind, version, and label; running local ATS identifies the exact selected version in its saved result.

### Q4. Local comparison vs. Codex review

Run **Run local comparison**, then separately run **Audit this resume** or **Match against vacancy**.

**Look for:** local coverage is described as heuristic text matching; Codex results are saved in a separate history; neither overwrites the other; the vacancy match history names its vacancy, especially when using a Master Resume against more than one job.

### Q5. Manager audit result shape

Run **Audit this resume** on a synthetic or otherwise safe resume.

**Look for:** line references, role family and grade, six named risk checks, evidence / achievement review, five recruiter-read checks, structure rubric, six-axis score and at most five fix directions. The score is a resume rubric, not a hiring probability; advice should not contain replacement bullets ready to paste.

### Q6. Vacancy match and historical status

Run **Match against vacancy**, then edit and reconfirm the vacancy description and reopen ATS history.

**Look for:** each requirement has a status and resume line reference; there is no invented total match percentage or hire probability. The earlier run is marked historical after its vacancy source changes.

### Q7. Deleted-source redaction (optional)

Only after confirming that the selected resume is the synthetic test version, delete that version and reopen ATS history.

**Look for:** the historical assessment remains identifiable, but resume evidence and saved response content are redacted. Do not use a real resume for this destructive check.

## Guided scenario — Technical Project Manager, about 15 minutes

This is the recommended path if you want us to compare observations against specific expected outcomes.

### A. Create a synthetic Master Resume

In Master Resume, create a new, separate series named `QA — Technical Project Manager` and paste:

```text
Target: Middle Technical Project Manager
Experience: 4 years coordinating SaaS platform delivery.
Led migration of 12 API services across 3 teams; median release lead time fell from 10 weeks to 4 weeks over 9 months.
Owned delivery plans, dependencies, and risk reviews for 6 engineers and 2 analysts; 92% of milestones met their planned quarter in the last two quarters.
Introduced weekly planning and retrospectives for the platform group.
Worked with Product, Engineering, QA, and Security on release scope and acceptance.
Technical context: REST APIs, PostgreSQL, AWS, CI/CD. Tools: Jira, Confluence.
Strengths: proactive communicator and team player.
Education: Bachelor of Information Systems.
```

The text intentionally includes measurable delivery outcomes, a scope statement, a process-only line, technical context, and soft-skill claims. The audit should distinguish these categories; it need not assign any exact numeric score.

### B. Create a synthetic vacancy

Create a vacancy titled `QA — Technical Project Manager` with this description, then confirm the cleaned description:

```text
Middle Technical Project Manager — SaaS platform
Requirements:
- At least 3 years managing technical projects or platform delivery.
- Experience planning API or cloud migrations across engineering teams.
- Own delivery plans, risks, dependencies, milestones, and release acceptance.
- Work with Product, Engineering, QA, and Security stakeholders.
- Understand REST APIs and relational databases such as PostgreSQL.
- Jira experience is preferred.
```

### C. Run local comparison

In that vacancy's ATS tab, select `QA — Technical Project Manager` Master Resume and run the local comparison.

**Expected:** the result identifies the Master Resume version; the API/cloud, planning, stakeholder, and technical evidence can be inspected. Treat the percentage as lexical guidance only.

### D. Run manager audit

Click **Audit this resume**.

**Expected:** the output cites actual resume lines; identifies the migration/time reduction and milestone result as outcome evidence, the team size as scope, planning/retrospectives as process, and the soft-skill claims as weak/noise if the model considers them relevant. It includes all six named risk checks, five recruiter-read checks, role/grade and grade-inflation fields, Rubric T, six axes, and no more than five directions. Do not expect a particular score; check completeness, citations, and whether each claim is supported.

**Isolation check:** the manager audit must not quote or compare against the vacancy description, even though it was launched from a vacancy card. The backend regression test verifies that the vacancy text is excluded from this action; the browser display alone cannot prove the exact prompt payload.

### E. Run vacancy match

Click **Match against vacancy**.

**Expected:** each requirement has `covered`, `partial`, `not_evidenced`, or `insufficient_input`, with a short vacancy quote and references to resume lines. Do not expect a single percentage or hiring probability. History should display the synthetic vacancy title next to this result.

### F. Check locale preservation

Go to AI / Codex, change the interface language and verify an untouched built-in prompt. Type `Keep this sentence`, switch language again, and confirm it remains in the prompt field.

**Expected:** the built-in prompt follows the selected locale; the custom sentence is preserved. The current vacancy and tab remain selected.

### G. Check source history

Change and reconfirm the synthetic vacancy description, then return to ATS history.

**Expected:** the previous vacancy match is still present and visibly historical. If you choose to test deletion, delete only the synthetic Master Resume version and confirm its assessment evidence is redacted.

## What to send back

You can report only exceptions; passing every step does not need a long write-up. Copy this small template and fill what you observed:

```text
Scenario: Q__ / Guided step __
Device/browser and approximate screen width:
What I did:
What I expected:
What happened instead:
Resume line references / vacancy title involved:
Screenshot (synthetic data only):
```

For model-generated content, flag a concrete unsupported statement, missing source citation, missing rubric section, or misleading score. We can then compare that observation with the saved source snapshot and decide whether to change the prompt, presentation, or ATS logic.
