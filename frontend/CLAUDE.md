# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The Vue half of the `oracle` monorepo — the repo-wide picture, cross-cutting `make` targets, and the conventions shared by both apps live in the root `CLAUDE.md`.

A Vue 3 SPA (TypeScript, Vite, PrimeVue) over the backend's HTTP API: upload documents, pick which ones to search, run a full-text search, read the matching chunks.

## Commands

All commands run from `frontend/`, using `pnpm` (never `npm`/`yarn` — the lockfile is `pnpm-lock.yaml`).

```bash
pnpm install             # install deps per pnpm-lock.yaml
pnpm dev                 # Vite dev server on 127.0.0.1:5173
pnpm dev --host          # also serve on the LAN (see "Reaching the API" below)
pnpm test                # run the full Vitest suite
pnpm test tests/api.test.ts      # run a single test file (no `--`; that runs everything)
pnpm test:e2e            # run the Playwright suite (starts its own backend + Vite)
pnpm test:e2e --headed   # watch it in a real browser
pnpm typecheck           # vue-tsc -b — the real typechecker (plain --noEmit checks nothing)
pnpm build               # vue-tsc -b && vite build
pnpm add <package>       # add a runtime dependency
pnpm add -D <package>    # add a dev-only dependency
```

The backend must be running for the app to do anything: `cd ../backend && uv run oracle-server`.

**`vite build` is not a typecheck** — Vite strips types without checking them, so a build can succeed while the code is badly broken. `pnpm typecheck` is the authority here, and it is what "typechecker" means in the root CLAUDE.md's finish-work rule.

## Architecture

- `src/api.ts` is the only place that talks to the backend. Every call goes through the internal `request()` helper, which unwraps FastAPI's `{"detail": ...}` error bodies and throws `ApiError`. Components catch `ApiError` and render the message; they never call `fetch` directly. Add new endpoints here, with a typed interface mirroring the server's Pydantic response model.
- **Uploads are asynchronous.** `POST /documents` returns `202` with the document `pending`; the backend chunks it in the background. `api.ts` exposes `waitForDocument(id, { signal })`, which polls `GET /documents/{id}` with capped exponential backoff (0.5s → 5s, 60 attempts) until the status is terminal. `App.vue` starts one poll per `pending` document it sees — after an upload, but also on load, which covers a reload mid-ingest or an upload from another tab — and patches the row in place when it settles. The polls share an `AbortController` that `onUnmounted` aborts.
- `src/App.vue` owns the state (document list, selection, loading, error) and passes it down. The three components under `src/components/` are presentational and talk to the API only for their own action (`DocumentUpload` uploads, `SearchPanel` searches); the document list is fetched once in `App.vue` and refreshed via the `uploaded` event.
- PrimeVue 4 with the Aura preset, configured in `src/main.ts`. Components are imported individually where used (`import DataTable from 'primevue/datatable'`), not registered globally. Let the theme own the look: `src/style.css` is deliberately minimal, and colours come from PrimeVue CSS variables (`--p-text-muted-color`, `--p-content-background`) rather than hard-coded values.
- Tests live in top-level `tests/`, not alongside source, mirroring the backend's convention. `include: ['tests/**/*.test.ts']` is set in `vite.config.ts`. Component tests mount with the PrimeVue plugin installed and assert against rendered PrimeVue markup (`.p-card`, `.p-tag`, `input.p-checkbox-input`).
- `tsconfig.app.json` includes `tests/**/*.ts` as well as `src/`, so test files are typechecked too. Keep it that way.

## Testing tiers

Vitest (`tests/`, jsdom) covers component rendering and the API client's logic — the backoff maths, the attempt cap, abort-on-unmount — with `fetch` mocked. It is the fast tier; put new logic here.

Playwright (`e2e/`, real Chromium) covers only the upload→poll→settle flow, because that is the one thing jsdom cannot honestly test: **jsdom's `File` is not serializable by a real multipart POST**, so an upload from jsdom reaches the backend as `422 field required: file`. `pnpm test:e2e` starts its own uvicorn (against a throwaway database via `ORACLE_DB_PATH`/`ORACLE_UPLOADS_DIR`) and its own Vite, so it needs nothing running first.

Gotchas that cost real time here, all in `playwright.config.ts`:

- **The E2E database is emptied inside the `webServer` command**, not in the config body and not in a `globalSetup`. Playwright re-imports the config in every worker process, and starts `webServer` *before* `globalSetup` — either would delete the database out from under a server that had already migrated it, and every request would then fail with `no such table: documents` against a freshly created empty file.
- **Ingestion is slow now** — every chunk is embedded on the CPU during processing (~18s for the 60-page fixture), which is why the specs wait for `ready` with 60s expect timeouts and the config sets a 180s per-test timeout (Playwright's 30s default would trip first). Don't tighten these because a run looked quick. The `arrivesPending` rewrite trick predates embedding, when ingestion was ~0.5s and a spec waiting for a real `pending` row raced the backend; it still guarantees the only thing moving a row to terminal is the client's poll, so keep it. **If you change these specs, verify they still fail when `watchPending()` in `App.vue` is commented out** — that check is what caught them being vacuous in the first place.
- The backend server downloads the embedding model at startup on its first ever run, so the first `pnpm test:e2e` on a machine is slower to boot (the webServer entry allows 180s for this). The model cache is shared with dev (`backend/data/models`); only the database, uploads, and vector db are per-run throwaways.

## Reaching the API

The SPA calls **relative** `/api/*` URLs, so the API is always same-origin with the page. In dev, `vite.config.ts` proxies `/api` to `http://127.0.0.1:8000` and strips the prefix (the backend serves its routes at the root: `/documents`, not `/api/documents`).

This is deliberate and worth preserving:

- It works unchanged when the page is loaded from another machine (`pnpm dev --host`), because no backend host is baked into the bundle. The proxy hop happens on the machine running Vite, so its `127.0.0.1` is correct even when the browser is elsewhere.
- Same-origin means **no CORS**. The backend only adds `CORSMiddleware` if `ORACLE_ALLOWED_ORIGINS` is set, and it normally isn't.
- It mirrors the intended production setup (a reverse proxy serving `dist/` and forwarding `/api` to uvicorn), so dev and prod run the same code path.

`VITE_API_BASE_URL` overrides the base with an absolute origin, but that is genuinely cross-origin and then needs `ORACLE_ALLOWED_ORIGINS` set on the backend to match. Prefer the proxy. Note Vite inlines `import.meta.env.VITE_*` **at build time** — a built bundle cannot be repointed at runtime.

## Gotchas

- **`typescript` is pinned to `~6.0.2`. Do not upgrade to 7.** TypeScript 7 is the native (Go) port: its npm package ships no JavaScript compiler API (the root export is just `lib/version.cjs`) and no `tsserver`. `vue-tsc` fails to start on it (`ERR_PACKAGE_PATH_NOT_EXPORTED` for `typescript/lib/tsc`), and the native `tsc` cannot read `.vue` files at all — it reports `TS2307: Cannot find module './App.vue'` for every SFC import. `vite build` and `vitest` still pass on TS 7, which makes this a *silent* loss of all Vue typechecking. Revisit only when `@vue/language-tools`/`vue-tsc` ships TS 7 support; its current `typescript: >=5.0.0` peer range permits 7 by semver but does not work.
- **Never add a `declare module '*.vue'` shim.** It silences editor errors by making every component `any`, destroying prop/emit typechecking. Modern create-vue deliberately omits it; if `.vue` imports fail to resolve, the editor's Vue language server is misconfigured — the code is fine (`pnpm typecheck` will confirm).
- **PrimeVue 4's `DataTable` has no `isDataSelectable` prop** (that's PrimeReact). Vue silently ignores unknown props, so a row-selectability rule written that way appears to work and does nothing. `DocumentTable.vue` enforces it instead by routing `v-model:selection` through a computed whose setter filters out unready rows — which also stops the header select-all from grabbing them. Check the real PrimeVue 4 API before reaching for a prop you remember.
- **A document is only searchable once its status is `ready`.** Uploading returns `202` with the document `pending`: the backend chunks it in a background task (both `.pdf` and `.docx` are supported), after which it settles on `ready` or `failed` — `failed` still happens for a corrupt or unparseable file. Unready rows are greyed out and cannot be selected — don't treat `pending` as selectable. A `pending` document needs polling (`GET /documents`) to learn its outcome; the upload response never carries it.
- **Selection filtering is client-side.** `POST /search` searches every document; `SearchPanel` narrows the results to the checked rows. An empty selection means "search everything", not "search nothing". If the corpus grows, push this into SQL rather than filtering more aggressively here.
- Search results carry `page_number`, which is `null` for chunks with no page information — render the page only when it is present.
- **Search is hybrid and fused server-side** (reciprocal rank fusion over top-10 BM25 + top-10 vector, capped at 5 results): each result carries `sources`, the list of indexes that returned it (`'bm25'`, `'vector'`, or both). The frontend only renders one tag per source — never re-merge, re-rank, or dedupe here. Fusion means `chunk_id` is unique per result and safe as a list key. A query with no keyword match still returns vector-sourced results (nearest neighbours, no threshold) — an empty result list only happens when nothing is indexed.
