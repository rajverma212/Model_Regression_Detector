# Deploying the Evaluation OS to Vercel

The whole app runs on Vercel as **two projects from this one GitHub repo** — both
auto-redeploy on every `git push` to `main`:

| Project | Root directory | What it is | URL you'll get |
|---------|----------------|------------|----------------|
| **Backend** | *(repo root)* | FastAPI as a Python serverless function (`api/index.py`, `vercel.json`) | `…-api.vercel.app` |
| **Frontend** | `web` | the Next.js UI (zero-config) | `…-web.vercel.app` ← you visit this |

The frontend reaches the backend through one environment variable, `MRDS_API_URL`.

> **Heads-up (how Vercel works):** Vercel is serverless, so the live site's database is
> **read-only** — every page shows the seeded demo data perfectly, but the in-UI
> "Promote to baseline" won't *permanently* save online (it works fully when run
> locally). The first visit after idle may take a few seconds to wake up (cold start).

---

## Option A — Vercel dashboard (click-through, most reliable)

**1. Backend project**
1. vercel.com → **Add New… → Project** → import `rajverma212/Model_Regression_Detector`.
2. Leave **Root Directory** as the repo root. Framework Preset: **Other** (the `vercel.json` drives it).
3. **Deploy.** When it's done, copy the URL (e.g. `https://mrds-api.vercel.app`) and check it works: open `…/api/health` — you should see `{"status":"ok",…}`.

**2. Frontend project**
1. **Add New… → Project** → import the **same repo** again.
2. Set **Root Directory** to **`web`**. Framework Preset auto-detects **Next.js**.
3. Under **Environment Variables**, add: `MRDS_API_URL` = the backend URL from step 1 (no trailing slash).
4. **Deploy.** Open the frontend URL — that's your live Evaluation OS.

Both projects are now linked to the repo, so any `git push` to `main` redeploys them automatically.

---

## Option B — Vercel CLI (from this terminal)

```bash
npx vercel login                       # you approve in the browser; auth stays on your machine

# Backend (from the repo root)
npx vercel --prod                      # accept defaults; note the deployment URL

# Frontend (from web/)
cd web
npx vercel link                        # link a second project to the same repo
npx vercel env add MRDS_API_URL production   # paste the backend URL when prompted
npx vercel --prod
```

(`vercel git connect` links a project to GitHub so pushes auto-deploy.)

---

## Updating the live site

Just push:

```bash
git add -A && git commit -m "…" && git push origin main
```

Vercel rebuilds both projects automatically. To refresh the demo data baked into the
backend, regenerate `data/seed.db` and commit it:

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

## How it fits together

- `api/index.py` adds repo-root `src/` to the path, copies `data/seed.db` → `/tmp/eval.db`
  (writable), and serves the unchanged `mrds.api.app:app`.
- `vercel.json` bundles `src/`, `data/seed.db`, `datasets/`, `prompts/`, `config/` into the
  function and routes all requests to it.
- The frontend's `next.config.ts` rewrite + server fetchers both read `MRDS_API_URL`, so no
  frontend code changes are needed — only that env var.
- Local dev is unchanged: `python -m mrds.api` + `npm run dev` (see `web/README.md`).
