# CareerFlow Agent Instructions

## Model routing

- Use `gpt-5.6-luna` with reasoning effort `low` for HTML/CSS work and straightforward visual/responsive layout changes.
- Escalate layout work to `gpt-5.6-luna` with reasoning effort `medium` only when the visual composition or responsive behavior is materially complex.
- Use `gpt-5.6-sol` with reasoning effort `high` for backend, database, API, business logic, integrations, tests, documentation, architecture, and other non-layout work.
- Split mixed tasks along that boundary instead of assigning the entire task to one model.

These routing rules apply to future project work unless the user gives a more specific instruction.
