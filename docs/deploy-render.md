# Durable backend deploy (persistent disk) — Render

The [Vercel deploy](deploy-vercel.md) runs the backend as a **serverless** function
whose only writable storage is a per-instance `/tmp` that resets on every cold start.
That's fine for browsing the seeded demo, but anything you create online — a feature
you activate, a baseline you promote, a run — lives on a single ephemeral instance and
**vanishes** (and 404s on sibling instances). See [deploy-vercel.md](deploy-vercel.md).

This guide deploys the **same backend, unchanged**, to a host with a **persistent
mounted disk**. SQLite and the feature bundles live on that disk, so online activation
is durable across restarts and redeploys. A disk attaches to one instance, so there's
also exactly one database and platform root — no per-instance split-brain.

> The code already supports this — [`api/index.py`](../api/index.py) notes that "on a
> normal long-lived host none of this applies." The only new pieces are
> [`scripts/start_server.py`](../scripts/start_server.py) (seeds the disk once, then
> serves) and [`render.yaml`](../render.yaml) (the Blueprint).

## How it works

On first boot, [`scripts/start_server.py`](../scripts/start_server.py) copies the
committed read-only assets (`config/`, `prompts/`, `datasets/`, `specs/`) and the seeded
`data/seed.db` onto the disk at `MRDS_PLATFORM_ROOT` (default `/data`), then points the
platform there for **both reads and activation writes**. The copy is idempotent — only
missing items are seeded — so everything written on a previous boot survives. It then
serves `mrds.api.app:app` on `0.0.0.0:$PORT`.

## Deploy on Render (Blueprint)

1. **New → Blueprint**, connect this repo. Render reads [`render.yaml`](../render.yaml)
   and provisions a web service `mrds-api` with a 1 GB disk mounted at `/data`.
2. Pick the **Starter** instance (≈ $7/mo). **A persistent disk requires a paid
   instance — Render's free tier has no disk**, so the free tier cannot make activation
   durable.
3. Set the **`ANTHROPIC_API_KEY`** secret in the Render dashboard (it's declared
   `sync: false`, so it is never committed). Required for online activation — the first
   evaluation calls the model; without it activation returns a clear `422`.
4. Deploy. Verify `https://<your-service>.onrender.com/api/health` returns
   `{"status":"ok",…}`. Pushes to `main` auto-redeploy (`autoDeploy: true`), and the disk
   persists across them.

## Point the frontend at the durable backend

On the **`mrds-web`** Vercel project, set the env var **`MRDS_API_URL`** to the Render
URL (no trailing slash) and redeploy. That's the only change the frontend needs — the
Vercel backend project can stay as a demo or be removed.

## Configuration knobs

| Env var | Default | Purpose |
|---------|---------|---------|
| `MRDS_PLATFORM_ROOT` | `/data` | Durable disk mount; seeded assets + activation writes live here. |
| `MRDS_DATABASE_PATH` | `<root>/eval.db` | SQLite DB; seeded from `data/seed.db` on first boot. |
| `PORT` / `MRDS_API_PORT` | host-provided / `8000` | Bind port; host is forced to `0.0.0.0`. |
| `ANTHROPIC_API_KEY` | — | Required for online activation (first eval calls the model). |

## Other disk hosts

`scripts/start_server.py` is host-agnostic — it honours `$PORT` and binds `0.0.0.0`,
so it works on **Railway** or **Fly.io** too. Provision a volume, mount it at `/data`
(or set `MRDS_PLATFORM_ROOT` to the mount), set `ANTHROPIC_API_KEY`, and use
`python scripts/start_server.py` as the start command.
