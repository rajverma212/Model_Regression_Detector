# CI/CD — Deployment Safety Gate

MRDS ships two GitHub Actions workflows in [.github/workflows/](../.github/workflows/). They turn the platform into a **deployment-safety gate**: when an LLM-affecting change is proposed, the evaluation suite runs and the result is compared against the active baseline. A blocking regression fails the build and (with branch protection) **blocks the merge**.

Both workflows are thin orchestration over the existing `mrds` CLI — **no evaluation logic lives in YAML**. The same commands run identically on a developer's laptop and in CI (CLI-first design).

---

## Workflows

### `ci.yml` — fast checks (every push & PR)

| Step | Command |
|------|---------|
| Checkout | `actions/checkout` |
| Set up Python 3.11 | `actions/setup-python` |
| Install | `pip install -e ".[dev]"` |
| Lint | `ruff check .` |
| Format check | `ruff format --check .` |
| Tests | `pytest -q` |

No secrets, no model calls — OpenAI is mocked in tests. This job should always pass before merge.

### `eval.yml` — the regression gate

Triggers:
- **`pull_request`** filtered to `prompts/**`, `datasets/**`, `src/mrds/features/**`, `config/**` (only runs when an LLM-affecting change is proposed).
- **`push` to `main`** (same path filter) — re-evaluates and promotes the baseline.
- **`workflow_dispatch`** — manual run.
- **`schedule`** (nightly) — full-dataset run to catch drift.

Steps:
1. Checkout → Set up Python → Install package
2. `pytest -q`
3. Restore the cached baseline database (`data/eval.db`)
4. Preflight: detect whether `OPENAI_API_KEY` is available (fork PRs have none → gate is skipped with a warning)
5. `mrds evaluate` — smoke subset (`--max-cases 25`) on PRs, full set on `main`/nightly; captures the `run_id`
6. `mrds compare` — **the gate**; its exit code controls pass/fail
7. Upload `reports/` as a workflow artifact (`always()`, even on failure)
8. On green `main` only: `mrds promote-baseline` + save the baseline DB to the cache

---

## Merge-blocking behaviour

`mrds compare` exit codes (from [`cli/exit_codes.py`](../src/mrds/cli/exit_codes.py)):

| Exit | Meaning | Job result |
|------|---------|-----------|
| `0` | No regression, warning-only regression, or no baseline yet | ✅ pass |
| `1` | **Blocking (CRITICAL) regression** | ❌ fail → merge blocked |
| `2` | Usage/runtime error | ❌ fail |

The `compare` step runs the command directly with no `|| true`, so the exit code propagates to the step → job. To enforce blocking on merges, mark **`Evaluation Gate / regression-gate`** as a *required status check* in the repository's branch-protection rules. Warnings pass the gate but appear in the report artifact.

## Baseline lifecycle in CI

The active baseline lives in the persisted SQLite DB (`data/eval.db`). Because CI runners are ephemeral, the workflow uses `actions/cache`:

- **PRs** restore the most recent baseline cache (via `restore-keys` prefix) read-only and compare against it. If no baseline exists yet, `compare` reports "nothing to compare" and exits `0`.
- **Green `main`** runs `promote-baseline` and save the updated DB to the cache, so subsequent PRs gate against shipped quality.

For a stronger guarantee than cache (which can be evicted), commit baseline metrics or store the DB in an external artifact/bucket and restore it in step 3 — the CLI is unchanged either way.

## Secrets

| Secret | Used by | Notes |
|--------|---------|-------|
| `OPENAI_API_KEY` | `eval.yml` (`evaluate`) | Maps to the `OPENAI_API_KEY` env var the feature reads. Absent on fork PRs → the gate self-skips. |

`SLACK_WEBHOOK_URL` will be added when Slack alerting lands (next sprint).

---

## Local testing

Because the workflows only call the CLI, you can reproduce the gate locally:

```bash
pip install -e ".[dev]"
export OPENAI_API_KEY=sk-...            # required for live evaluate

# Mirror the gate
mrds evaluate --feature email_classifier --segment-field category --max-cases 25
mrds compare  --feature email_classifier --report-dir reports
echo "compare exit code: $?"            # 1 == would block the merge

# Establish / advance the baseline
mrds promote-baseline --run <run_id> --promoted-by you
```

Run the full test suite (no API key needed — OpenAI is mocked):

```bash
ruff check . && ruff format --check . && pytest -q
```

### Validate workflow syntax

```bash
python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" \
  .github/workflows/ci.yml .github/workflows/eval.yml && echo OK
```

`tests/unit/test_workflows.py` also validates that both workflows parse, define jobs, filter on the required paths, invoke the `mrds` CLI, and upload artifacts.

### Run the workflows locally (optional)

[`act`](https://github.com/nektos/act) can execute the workflows in Docker:

```bash
act pull_request -W .github/workflows/eval.yml --secret OPENAI_API_KEY=sk-...
```
