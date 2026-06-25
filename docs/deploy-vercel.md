# Deploying the Evaluation OS to Vercel

The app is **live on Vercel** as two projects from this one GitHub repo, both
auto-redeploying on every `git push` to `main`:

| Project | Root directory | What it is | Live URL |
|---------|----------------|------------|----------|
| `mrds-web` | `web` | the Next.js UI | **https://mrds-web.vercel.app** ← visit this |
| `mrds-api` | *(repo root)* | FastAPI as a Python serverless function | https://mrds-api.vercel.app |

The frontend reaches the backend through one environment variable, `MRDS_API_URL`
(set on the `mrds-web` project to the backend URL).

> **How Vercel runs it (one caveat):** Vercel is serverless with a filesystem that is
> **read-only except `/tmp`**. On cold start the backend assembles a single **writable working
> root** under `/tmp` (a copy of `config/`, `prompts/`, `datasets/`, `specs/` and the seeded
> `eval.db`) and points the platform at it. So everything works *within a warm instance* —
> including **end-to-end feature activation** (Create → Activate → first evaluation → baseline →
> Mission Control) and in-UI baseline promotion — but anything written online (new features,
> promotions, runs) is **ephemeral**: `/tmp` is per-instance and resets on a cold start. Run
> locally (or on any persistent host) for durable onboarding. The first visit after idle may
> take a few seconds to wake (cold start).
>
> Activating a feature online also requires `ANTHROPIC_API_KEY` set on the `mrds-api` project
> (the first evaluation calls the model). Without it, activation returns a clear `422` rather
> than fabricating an empty baseline.
>
> **Durable cloud onboarding** (features that survive cold starts and feed CI gating) needs a
> persistent volume + external database, plus committing the generated bundle
> (`specs/`, `prompts/`, `datasets/`) to git so CI sees it — out of scope for this demo deploy.

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

How `api/index.py` works on Vercel: it adds repo-root `src/` to `sys.path`; on cold start it
copies the bundled read-only assets (`config/`, `prompts/`, `datasets/`, `specs/`) and the seeded
`data/seed.db` into a writable working root at `/tmp/mrds`, `chdir`s there, and sets
`MRDS_PLATFORM_ROOT` + `MRDS_DATABASE_PATH` to it — giving the platform one consistent, writable
root for both reads and activation writes — then serves the unchanged `mrds.api.app:app`.
(`includeFiles` in the repo-root `vercel.json` must bundle those asset dirs so they exist to copy.)

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
