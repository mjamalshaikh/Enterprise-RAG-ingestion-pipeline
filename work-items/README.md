# Work-item audit trail

This directory records the user requests that motivated repository changes. Each request is stored in a separate, timestamped Markdown file and includes the implementation outcome.

## Convention

- Filename: `<recorded-at>--<short-slug>.md`, using ISO-8601 local time with Windows-safe separators.
- Treat records as append-only. Add a new work item for a follow-up request instead of rewriting an earlier prompt.
- Preserve the request verbatim in the **Prompt** section. Link the files or commits that implement it in **Outcome**.

The timestamps are when the prompt was recorded in this repository; they are not a claim about the time the user originally sent the message.
