# Example repos

Notes per repo, under a "## <repo name>" heading that matches `profile.json`. The context file gives every finder and check its own repo's section. Say which guidance applies, how to run the gates, which files are generated, and which facts must stay in step with another file or repo.

## acme-web (`acme/web`, folder `web`)

A React web app that calls acme-api.

- **Guidance:** `AGENTS.md`, `docs/style.md`.
- **Gates:** `npm run lint`, `npm run typecheck`, `npm test -- <changed test files>`.
- **Generated:** `src/generated/` comes from acme-api's OpenAPI file. Fix the API, never the copy.
- **Mirrors:** the error codes in `src/errors.ts` and acme-api's `docs/errors.md`.

## acme-api (`acme/api`, folder `api-server`)

The HTTP API that acme-web calls.

- **Guidance:** `CONTRIBUTING.md`.
- **Gates:** `make lint test`.
- **Generated:** `openapi/client/`.
- **Mirrors:** `docs/errors.md` and acme-web's `src/errors.ts`.
