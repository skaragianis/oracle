# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Oracle: use LLMs to ask questions of provided documents. A monorepo of two apps:

- `backend/` — Python (uv): a CLI and a FastAPI server sharing one package. See `backend/CLAUDE.md`.
- `frontend/` — Vue 3 SPA (pnpm, Vite, PrimeVue) over the server's HTTP API. See `frontend/CLAUDE.md`.

Each app's CLAUDE.md is authoritative for its commands, architecture, and gotchas — read it before working in that directory. Their conventions don't cross over (Python rules don't apply to the frontend, and vice versa); the rules below are the repo-wide exceptions.

## Conventions (both apps, and root-level files)

Start work by confirming the affected app's tests pass first. Never finish work until its tests, linter, and typechecker are all clean — `make test` and `make lint` cover the whole project; each app's CLAUDE.md names the underlying commands.

**Don't add narrating comments.** No comments that restate what the code already says, re-explain an env var or an API the reader can look up, or turn a self-explanatory line into a paragraph. A comment earns its place only when the *why* is genuinely non-obvious from the code — a real gotcha, a non-local constraint, a decision that looks wrong until explained. When in doubt, leave it out and let the names and structure carry the meaning.

## Root-level commands

The Makefile is the entry point for cross-cutting work; `make help` lists all targets.

```bash
make up      # build the docker image and run the whole app at http://localhost:8080
make down    # stop and remove the container (the data volume is kept)
make test    # backend pytest + frontend vitest
make lint    # backend ruff + ty, frontend vue-tsc
```

Per-component `*-run`/`*-test` targets exist too (`cli-`, `server-`, `backend-`, `frontend-`); dev still means running `make server-run` and `make frontend-run` in two terminals — docker is for running the app, not developing it.

## Docker

`Dockerfile` at the root builds one image for everything: a node stage builds the SPA, then a debian stage runs uvicorn behind nginx, which serves `dist/` and proxies `/api/` to it — the same same-origin shape as the Vite dev proxy, so no CORS. The nginx config and startup script are BuildKit heredocs inside the Dockerfile; there are no separate config files to keep in sync.

Persistent state (the SQLite database and the uploads folder) is one dataset and lives together on a single volume: the image sets `ORACLE_DB_PATH=/data/oracle.db` and `ORACLE_UPLOADS_DIR=/data/uploads`, and `make up` mounts the `oracle-data` named volume at `/data`. `make up` is rerunnable — it rebuilds and replaces the container without touching the volume. Keep the two env vars pointing at the same place; rows without their files (or vice versa) are corrupt state.
