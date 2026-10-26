# Example checks

Checks this project enforces that a general reviewer would not know, under a "## <repo name>" heading, plus "## All repos". These are rules to catch, not to stop flagging. Every finder gets its repo's section and "All repos" (lens L5).

## acme-web

- Every API call goes through `src/api/client.ts`, so retries and auth stay in one place.

## acme-api

- A new route is listed in `openapi/acme.yaml` in the same change.
- To check a migration, apply it to a scratch database under `/tmp/preflight-probes/`, never the shared one.

## All repos

- An error code added on one side is added on the other side too.
