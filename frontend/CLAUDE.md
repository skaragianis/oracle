# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The Vue half of the `oracle` monorepo (repo-wide picture: root `CLAUDE.md`). A Vue 3 SPA (TypeScript, Vite, PrimeVue 4 / Aura) over the backend's HTTP API: upload documents, pick which to search, run hybrid search, read the matching chunks.

## Commands

Run from `frontend/` with `pnpm` (never `npm`/`yarn`). The backend must be running for anything to work (`cd ../backend && uv run oracle-server`).

```bash
pnpm install
pnpm dev                     # Vite on 127.0.0.1:5173 (add --host for LAN)
pnpm test                    # full Vitest suite
pnpm test tests/api.test.ts  # single file (no `--`)
pnpm test:e2e                # Playwright (starts its own backend + Vite)
pnpm typecheck               # vue-tsc — the real typecheck
```

**`vite build` and `vitest` do NOT typecheck** — they strip types. `pnpm typecheck` (vue-tsc) is the authority.

## Architecture

- `src/api.ts` is the only place that talks to the backend. Every call goes through `request()`, which unwraps FastAPI `{"detail": ...}` bodies and throws `ApiError`; components catch it and render the message. Add endpoints here with a typed interface mirroring the server's Pydantic model.
- `src/App.vue` owns all state (document list, selection, loading, error) and passes it down; `src/components/` are presentational and call the API only for their own action. The document list is fetched once and refreshed via the `uploaded` event.
- **Uploads are async.** `POST /documents` returns 202 `pending`; the backend chunks in the background. `api.ts`'s `waitForDocument(id, {signal})` polls `GET /documents/{id}` with capped backoff. `App.vue` polls each `pending` doc it sees (after upload and on load — covers reloads / other tabs) and patches the row when it settles; polls share an `AbortController` aborted on unmount.
- PrimeVue components are imported individually where used, not registered globally. Let the theme own the look — `src/style.css` is minimal; colours come from PrimeVue CSS vars (`--p-*`).

## Testing tiers

- **Vitest** (`tests/`, jsdom, `fetch` mocked) is the fast tier for component rendering and API-client logic — put new logic here. Component tests mount with the PrimeVue plugin and assert against rendered markup (`.p-card`, `input.p-checkbox-input`). `tsconfig.app.json` typechecks `tests/` too — keep it that way.
- **Playwright** (`e2e/`, real Chromium) covers only the upload→poll→settle flow, because **jsdom's `File` isn't serializable by a real multipart POST** (an upload from jsdom reaches the backend as `422 field required`). It starts its own uvicorn + Vite against a throwaway db.

Playwright gotchas (all in `playwright.config.ts`):
- The e2e **database is emptied inside the `webServer` command**, not in the config body or a `globalSetup` — Playwright re-imports the config per worker and starts `webServer` before `globalSetup`, so either would delete the db out from under a migrated server (`no such table: documents`).
- **Ingestion is slow** (~18s for the 60-page fixture, embedding on CPU) — specs use 60s waits and a 180s per-test timeout; don't tighten them. The first-ever run also downloads the embedding model (webServer allows 180s). If you change these specs, verify they still fail when `watchPending()` in `App.vue` is commented out — that's what catches vacuous specs.

## Reaching the API

The SPA calls **relative** `/api/*` (same-origin, no CORS). In dev, `vite.config.ts` proxies `/api` → `http://127.0.0.1:8000` and strips the prefix; the proxy hop runs where Vite runs, so `--host` works unchanged. This mirrors prod (a reverse proxy serving `dist/` + `/api`). `VITE_API_BASE_URL` overrides with an absolute origin, but that's cross-origin and needs `ORACLE_ALLOWED_ORIGINS` on the backend — prefer the proxy. Vite inlines `VITE_*` at build time; a built bundle can't be repointed.

## Gotchas

- **`typescript` is pinned to `~6.0.2` — do not upgrade to 7.** The native (Go) port ships no compiler API or `tsserver`; `vue-tsc` fails to start and native `tsc` can't read `.vue`. `vite build`/`vitest` still pass on TS 7, making it a *silent* loss of all Vue typechecking. Revisit only when `vue-tsc` supports TS 7.
- **Never add a `declare module '*.vue'` shim** — it makes every component `any`, destroying prop/emit typechecking. If `.vue` imports don't resolve, the editor's Vue language server is misconfigured; the code is fine (`pnpm typecheck` confirms).
- **PrimeVue 4 ≠ PrimeReact.** `DataTable` has no `isDataSelectable` prop (Vue silently ignores unknown props); `DocumentTable.vue` enforces row-selectability by routing `v-model:selection` through a computed whose setter filters unready rows. Check the real PrimeVue 4 API before using a prop you remember.
- **A document is only searchable once `ready`.** Unready rows are greyed out and can't be selected — don't treat `pending` as selectable. The upload response never carries the outcome; poll for it.
- **Search selection is server-side.** `SearchPanel` sends `search(query, sources, documentIds)`; the default is all ready docs selected (`App.vue` auto-selects newly-ready docs via an `offered` set without undoing manual deselections). An empty selection — of docs or of sources — disables "Ask Oracle", so the frontend never searches nothing or everything by accident. `DocumentTable`'s custom "Select all" checkbox reflects/toggles the ready docs (checked / indeterminate / unchecked).
- Each result carries `sources` (`'bm25'`/`'vector'`/both) and `page_number` (`null` when absent — render only when present). Fusion is server-side and makes `chunk_id` unique per result (safe as a list key) — never re-merge, re-rank, or dedupe client-side. With vector selected, a query with no keyword match still returns nearest-neighbour hits, so an empty result list only means "nothing indexed" when both sources are checked.
