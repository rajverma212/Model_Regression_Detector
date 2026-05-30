-- MRDS SQLite system-of-record schema.
-- Feature-agnostic: features are identified by name; structured payloads are JSON.

CREATE TABLE IF NOT EXISTS prompt_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name  TEXT    NOT NULL,
    version       TEXT    NOT NULL,
    content_hash  TEXT    NOT NULL UNIQUE,
    path          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name  TEXT    NOT NULL,
    version       TEXT    NOT NULL,
    content_hash  TEXT    NOT NULL UNIQUE,
    path          TEXT    NOT NULL DEFAULT '',
    case_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid            TEXT    NOT NULL UNIQUE,
    feature_name        TEXT    NOT NULL,
    prompt_version_id   INTEGER REFERENCES prompt_versions(id),
    dataset_version_id  INTEGER REFERENCES dataset_versions(id),
    model               TEXT    NOT NULL,
    judge_enabled       INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'completed',
    git_sha             TEXT,
    triggered_by        TEXT    NOT NULL DEFAULT 'local',
    started_at          TEXT    NOT NULL,
    finished_at         TEXT    NOT NULL,
    duration_seconds    REAL    NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    total_cost_usd      REAL    NOT NULL DEFAULT 0,
    metrics_json        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_feature ON runs(feature_name);

CREATE TABLE IF NOT EXISTS test_results (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id              TEXT    NOT NULL,
    expected_difficulty  TEXT,
    input_json           TEXT    NOT NULL,
    expected_json        TEXT    NOT NULL,
    actual_json          TEXT,
    passed               INTEGER NOT NULL,
    scores_json          TEXT    NOT NULL,
    latency_ms           REAL    NOT NULL DEFAULT 0,
    input_tokens         INTEGER NOT NULL DEFAULT 0,
    output_tokens        INTEGER NOT NULL DEFAULT 0,
    total_tokens         INTEGER NOT NULL DEFAULT 0,
    error                TEXT
);
CREATE INDEX IF NOT EXISTS idx_test_results_run ON test_results(run_id);

CREATE TABLE IF NOT EXISTS baselines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name  TEXT    NOT NULL,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    is_active     INTEGER NOT NULL DEFAULT 1,
    promoted_by   TEXT    NOT NULL,
    promoted_at   TEXT    NOT NULL,
    note          TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_baselines_active ON baselines(feature_name, is_active);

CREATE TABLE IF NOT EXISTS regressions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    baseline_run_id  INTEGER NOT NULL REFERENCES runs(id),
    metric           TEXT    NOT NULL,
    baseline_value   REAL    NOT NULL,
    candidate_value  REAL    NOT NULL,
    delta            REAL    NOT NULL,
    severity         TEXT    NOT NULL,
    detected_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_regressions_run ON regressions(run_id);
