# Deploying the Evaluation OS to Vercel

The app is **live on Vercel** as two projects from this one GitHub repo, both
auto-redeploying on every `git push` to `main`:

| Project | Root directory | What it is | Live URL |
|---------|----------------|------------|----------|
| `mrds-web` | `web` | the Next.js UI | **https://mrds-web.vercel.app** ← visit this |
| `mrds-api` | *(repo root)* | FastAPI as a Python serverless function | https://mrds-api.vercel.app |

The frontend reaches the backend through one environment variable, `MRDS_API_URL`
(set on the `mrds-web` project to the backend URL).

> **How Vercel runs it:** Vercel is serverless with a filesystem that is **read-only except
> `/tmp`**. Since feature bundles live in the database (the DB-only cutover), the only state
> the backend needs is its database. The entrypoint picks one of two modes from env:
>
> - **Durable (Turso)** — set `MRDS_STORAGE_BACKEND=libsql`, `TURSO_DATABASE_URL`, and
>   `TURSO_AUTH_TOKEN` on the `mrds-api` project. Requests run against a Turso **embedded
>   replica** (reads local, writes to the remote primary), so activated features, runs, and
>   baseline promotions **survive cold starts and are shared across instances**. On first
>   deploy an empty primary is auto-seeded with the built-in features + demo narrative
>   (idempotent). This is the production mode for online onboarding.
> - **Demo fallback (no Turso env)** — copy the committed, pre-seeded `data/seed.db` to
>   `/tmp/eval.db` and use SQLite. Everything works *within a warm instance* — including
>   end-to-end activation — but writes are **ephemeral** (reset on a cold start).
>
> The first visit after idle may take a few seconds to wake (cold start).
>
> **Turso setup (once):** `turso db create mrds-eval` → `turso db show mrds-eval --url` gives
> `TURSO_DATABASE_URL` (`libsql://…`); `turso db tokens create mrds-eval` gives
> `TURSO_AUTH_TOKEN`. Add both plus `MRDS_STORAGE_BACKEND=libsql` to the `mrds-api` Vercel
> project env and redeploy; the schema and seed content are created automatically.
>
> Activating a feature online also requires `ANTHROPIC_API_KEY` set on the `mrds-api` project
> (the first evaluation calls the model). Without it, activation returns a clear `422` rather
> than fabricating an empty baseline.
>
> **Durable cloud onboarding** (features that survive cold starts) — deploy the backend to a
> host with a **persistent disk** instead of serverless `/tmp`. The same code runs unchanged;
> see [deploy-render.md](deploy-render.md). (Feeding online-activated features into CI gating
> additionally needs the generated bundle — `specs/`, `prompts/`, `datasets/` — committed to git
> so CI sees it.)

## Updating the live site

Just push — both projects rebuild automatically (~1–2 min):

```bash
git add -A && git commit -m "…" && git push origin main
```

To refresh the demo data baked into the backend, regenerate `data/seed.db` and commit it:

```bash
python - <<'PY'
import os
from mrds.db import EvaluationStore, open_database
from mrds.demo import seed_demo
os.path.exists("data/seed.db") and os.remove("data/seed.db")
db = open_database("data/seed.db"); seed_demo(EvaluationStore(db))
db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)"); db.close()
PY
```

## The config that makes it work (and the traps)

Two projects share one repo, so the build config has to keep them apart. Three things matter:

1. **`vercel.json` (repo root)** — the *backend* project's config: builds `api/index.py` as a
   Python function, bundles `src/`, `data/seed.db`, `datasets/`, `prompts/`, `config/` into it
   (`includeFiles`), and routes all requests to it.
2. **`web/vercel.json`** — the *frontend* project's config (`{"framework":"nextjs"}`). **This is
   required.** With Root Directory = `web`, Vercel reads `web/vercel.json`; without it, Vercel
   applies the backend's repo-root `vercel.json` `routes` to the frontend's build and **404s
   every page**. (This was the bug that took the deploy several tries.)
3. **No repo-root `.vercelignore` that excludes `web/`.** Vercel applies a repo-root
   `.vercelignore` to *every* project's Git build, so ignoring `web/` deletes the whole app
   before it builds (empty ~9 ms build → 404). `.gitignore` already keeps `.venv` and
   `node_modules` out of Git clones, so no `.vercelignore` is needed.

How `api/index.py` works on Vercel: it adds repo-root `src/` to `sys.path`, `chdir`s to the
repo root (so read-only `config/settings.yaml` resolves), copies the seeded `data/seed.db` →
`/tmp/eval.db` (the only writable state the DB-native platform needs) on cold start, points
`MRDS_DATABASE_PATH` at it, and serves the unchanged `mrds.api.app:app`. (`includeFiles` in the
repo-root `vercel.json` bundles `config/` and `data/seed.db`.)

## Reproducing it from scratch

If you ever recreate the projects (dashboard → **Add New… → Project**, import the repo twice):

- **Backend project:** Root Directory = repo root. Framework Preset = **Other** (the repo-root
  `vercel.json` drives the build). Verify `…/api/health` returns `{"status":"ok",…}`. For online
  feature activation, set env var `ANTHROPIC_API_KEY` (otherwise activation returns `422`).
- **Frontend project:** Root Directory = **`web`**. Framework auto-detects **Next.js**. Add env
  var `MRDS_API_URL` = the backend URL (no trailing slash).
- New Vercel projects sometimes default to **Deployment Protection on** (blocks public access)
  and **Framework: unset** — turn protection off and confirm the framework, per project, in
  Settings.

CLI equivalent (auth stays on your machine): `npx vercel login`, then `npx vercel --prod` from
the repo root (backend) and from `web/` (frontend); `npx vercel git connect <repo-url>` wires
auto-deploy. Local dev is unchanged: `python -m mrds.api` + `npm run dev` (see `web/README.md`).
