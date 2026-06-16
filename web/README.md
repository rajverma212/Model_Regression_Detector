# Eval OS — web frontend

**Live:** https://mrds-web.vercel.app &nbsp;·&nbsp; **API:** https://mrds-api.vercel.app

The product surface for the Model Regression Detection System: an **AI Evaluation
Operating System**. A premium, dark, instrument-grade interface for managing the health,
quality, and evolution of every AI feature you ship — built to replace the Streamlit
prototype with one coherent product.

> Streamlit proved the workflows; this app is the first-class experience. The Python
> evaluation engine, regression detector, golden datasets, baselines, and onboarding are
> reused **unchanged** through a thin HTTP API (`src/mrds/api/`).

## Stack

- **Next.js 16** (App Router, React 19, server components)
- **TypeScript**, strict
- **Tailwind CSS v4** (CSS-first tokens in `app/globals.css`)
- Bespoke **SVG charts** (no chart library — full design control, guaranteed rendering)
- `lucide-react` icons, `motion`, `class-variance-authority`

## Running locally

The frontend needs the Python API running (it is the data plane).

```bash
# 1) From the repo root — seed demo data (deterministic, offline) and start the API
python -m mrds.demo            # one-time: seeds data/eval.db with a realistic history
python -m mrds.api             # serves http://127.0.0.1:8000  (or: mrds-api)

# 2) In web/ — start the frontend (proxies /api/* to the API)
npm install
npm run dev                    # http://localhost:3000
```

Point the app at a non-default API origin with `MRDS_API_URL` (used by both the
server-component fetchers and the `/api/*` rewrite in `next.config.ts`).

## Architecture

- **Server components** fetch from the API directly (`lib/api.ts`, absolute origin).
- **Client components** (filters, compare, promote, the create wizard) call `/api/*`
  same-origin; `next.config.ts` rewrites that to the Python API, so there is no CORS.
- `lib/api.ts` is the single typed contract; its interfaces mirror
  `src/mrds/api/serializers.py` exactly.

## Information architecture

```
Mission Control (/)            fleet health — every feature's verdict, trend, baseline
└─ Feature workspace (/features/[feature])
   ├─ Overview                 latest verdict + quality breakdown + trend + baseline
   ├─ Runs                     evaluation timeline
   ├─ Run detail               verdict-first → metrics → why it regressed → test log
   ├─ Trends                   quality / speed / cost over time
   ├─ Compare                  any two runs, metric deltas
   ├─ Regressions              root cause: a regressed metric → the exact failing cases
   ├─ Dataset                  the golden examples + coverage
   └─ Baseline                 the trusted bar + promotion history
Create (/create)               dataset → inferred schema → prompt → activate
```

## Design system

Aesthetic: **instrument-grade observatory.** Warm-ink dark field, one cool
instrument-cyan signal accent, and a strict **green / amber / red verdict triad** reserved
only for AI-health semantics. Three type roles: **Instrument Serif** (hero/display),
**Hanken Grotesk** (UI), **JetBrains Mono** (every metric and id, so numbers read like
instrument readouts). Tokens live in `app/globals.css`; primitives in `components/ui/`.
