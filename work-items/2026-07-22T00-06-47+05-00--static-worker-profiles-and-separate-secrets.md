# Static worker profiles and separate secrets

**Recorded:** 2026-07-22T00:06:47+05:00

## Prompt

> i don't intend to use provision_local_access.ps1 and i haven't ran it yet.
> so how about that you make the env files of each worker and keep secrets
> separately?

## Change intent

- Commit one non-secret configuration profile for each worker.
- Keep passwords and API keys exclusively in the ignored runtime-secret file.
- Make the provisioning script optional for database-user creation rather than
  a dependency for worker configuration files.
