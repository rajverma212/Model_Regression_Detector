# Deploying the Evaluation OS to Vercel

The app is **live on Vercel** as two projects from this one GitHub repo, both
auto-redeploying on every `git push` to `main`:

| Project | Root directory | What it is | Live URL |
|---------|----------------|------------|----------|
| `mrds-web` | `web` | the Next.js UI | **https://mrds-web.vercel.app** ← visit this |
| `model-regression-detector` | *(repo root)* | FastAPI as a Python serverless function | https://model-regression-detector.vercel.app |

The frontend reaches the backend through one environment variable, `MRDS_API_URL`
(set on the `mrds-web` project to the backend URL).

> **How Vercel runs it (one caveat):** Vercel is serverless, so the live site's database is
> **read-only** — every page shows the seeded demo data perfectly, but the in-UI
> "Promote to baseline" won't *permanently* save online (it works fully when run locally).
> The first visit after idle may take a few seconds to wake (cold start).

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

How `api/index.py` works on Vercel: it adds repo-root `src/` to `sys.path`, copies the bundled
`data/seed.db` → `/tmp/eval.db` (the only writable path) on cold start, points the platform at
it via `MRDS_DATABASE_PATH`, and serves the unchanged `mrds.api.app:app`.

## Reproducing it from scratch

If you ever recreate the projects (dashboard → **Add New… → Project**, import the repo twice):

- **Backend project:** Root Directory = repo root. Framework Preset = **Other** (the repo-root
  `vercel.json` drives the build). Verify `…/api/health` returns `{"status":"ok",…}`.
- **Frontend project:** Root Directory = **`web`**. Framework auto-detects **Next.js**. Add env
  var `MRDS_API_URL` = the backend URL (no trailing slash).
- New Vercel projects sometimes default to **Deployment Protection on** (blocks public access)
  and **Framework: unset** — turn protection off and confirm the framework, per project, in
  Settings.

CLI equivalent (auth stays on your machine): `npx vercel login`, then `npx vercel --prod` from
the repo root (backend) and from `web/` (frontend); `npx vercel git connect <repo-url>` wires
auto-deploy. Local dev is unchanged: `python -m mrds.api` + `npm run dev` (see `web/README.md`).
