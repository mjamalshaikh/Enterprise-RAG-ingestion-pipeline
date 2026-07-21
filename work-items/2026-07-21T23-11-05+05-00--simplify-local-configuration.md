# Simplify local configuration

**Recorded:** 2026-07-21T23:11:05+05:00

## Prompt

> there is so much duplication in 3 .env.* files and 2 local-access.* file.
> how can we make it simple?

> ok please make the changes suggested by you.

## Change intent

- Replace the three overlapping environment templates with two committed,
  non-secret runtime profiles: host and container.
- Consolidate all credentials into the ignored `secrets/local-access.env` file
  and retain a committed names-only template for onboarding.
- Keep worker-specific database DSNs and Qdrant permissions in separate,
  ignored least-privilege worker files.
- Provide a prepare-only command to generate missing local credentials before
  the first Docker Compose startup.
