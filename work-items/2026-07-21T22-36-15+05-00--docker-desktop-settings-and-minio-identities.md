# Docker Desktop settings and MinIO identities

**Recorded:** 2026-07-21T22:36:15+05:00

## Prompt

> considering the provided 6 compose files, please update settings.py file as
> well. you have to update the URLs and ports. also please note that i created
> MinIO users for ingestion and API access. [Credentials redacted: secrets must
> never be committed to prompt-tracking files.]

## Change intent

- Make host-run Python workers default to the published ports from the reviewed
  Docker Desktop compose stacks.
- Preserve container-network endpoints as explicit environment overrides.
- Store the supplied MinIO service credentials only in an ignored local secret
  file, with separate ingestion and API settings.
