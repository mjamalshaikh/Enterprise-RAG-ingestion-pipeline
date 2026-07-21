# Consolidate local MinIO secrets

**Recorded:** 2026-07-21T22:46:17+05:00

## Prompt

> i have deleted secrets/docker-desktop-minio.env file and merged its content
> inside local-access.env. please update the repository accordingly.

## Change intent

- Use the consolidated ignored `secrets/local-access.env` file for MinIO
  credentials in runtime settings and Docker Desktop commands.
- Keep the tracked template limited to secret variable names.
