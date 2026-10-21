# Security policy

## Supported versions

Security fixes are prepared for the current `0.1.x` development line. Older versions may not receive fixes.

## Reporting a vulnerability

Please do not disclose a vulnerability in a public issue or include a resume, vacancy, database, attachment, log, or other personal data in a report.

Use GitHub's **Report a vulnerability** flow for this repository when private vulnerability reporting is available. If that option is unavailable, contact the maintainer privately through the [CareerFlow GitHub profile](https://github.com/Oleksandrnie) and ask for a private reporting channel. Include a concise description, affected version/commit, impact, and safe reproduction steps using synthetic data. Do not include working credentials or exploit payloads that access real user data.

The maintainer will acknowledge a report when possible, validate it, and coordinate a fix and disclosure timeline with the reporter. Please allow time for a fix before public disclosure.

## Data and deployment notes

CareerFlow is a single-user local application with no authentication. It binds to loopback by default. Do not expose it to the public Internet. If you explicitly enable LAN access, use only a trusted private network and understand that anyone who can reach the app can access or change its data.

Vacancies, resumes, attachments, generated reports, and SQLite files remain on the configured local paths. When the user explicitly runs a Codex action, the selected local Codex CLI account may receive the resume/vacancy context needed for that action.
