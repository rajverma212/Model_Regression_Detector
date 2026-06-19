/**
 * Typed client for the MRDS Evaluation OS API.
 *
 * Server components call the backend directly (absolute origin). Client components
 * call the same paths relatively (`/api/...`), proxied by the Next rewrite. The shapes
 * below mirror `src/mrds/api/serializers.py` exactly.
 */

const SERVER_ORIGIN = process.env.MRDS_API_URL ?? "http://127.0.0.1:8000";

export type Health = "healthy" | "warning" | "critical" | "unknown";

export interface SparkPoint {
  sequence: number;
  label: string;
  pass_rate: number;
}

export interface FeatureOverview {
  feature: string;
  display_name: string;
  health: Health;
  run_count: number;
  latest_run_label: string | null;
  latest_run_uuid: string | null;
  latest_pass_rate: number | null;
  baseline_pass_rate: number | null;
  has_baseline: boolean;
  baseline_delta: number | null;
  runs_with_regressions: number;
  segment_field: string | null;
  sparkline: SparkPoint[];
}

export interface RunSummary {
  run_uuid: string;
  sequence: number;
  label: string;
  short_label: string;
  status: string;
  model: string;
  prompt_version: string;
  dataset_version: string;
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  total_tokens: number;
  triggered_by: string;
  pass_rate: number;
  total_cases: number;
  passed: number;
  failed: number;
  errored: number;
  health: Health;
  is_baseline: boolean;
}

export interface ScorerStat {
  name: string;
  label: string;
  mean_score: number;
  pass_rate: number;
  passed: number;
  count: number;
}

export interface SegmentStat {
  segment: string;
  count: number;
  passed: number;
  pass_rate: number;
  scorer_means: Record<string, number>;
}

export interface Metrics {
  total_cases: number;
  passed: number;
  failed: number;
  errored: number;
  pass_rate: number;
  segment_field: string | null;
  scorers: ScorerStat[];
  segments: SegmentStat[];
  latency: {
    count: number;
    total_ms: number;
    mean_ms: number;
    min_ms: number;
    p50_ms: number;
    p95_ms: number;
    max_ms: number;
  };
  tokens: {
    total_tokens: number;
    total_input_tokens: number;
    total_output_tokens: number;
    mean_tokens_per_case: number;
  };
}

export interface ScoreDetail {
  name: string;
  passed: boolean;
  score: number;
  detail: string;
}

export interface CaseRow {
  case_id: string;
  difficulty: string;
  outcome: "passed" | "failed" | "errored";
  passed: boolean;
  errored: boolean;
  input: Record<string, unknown>;
  input_text: string;
  expected: Record<string, unknown>;
  actual: Record<string, unknown> | null;
  error: string | null;
  scorers: ScoreDetail[];
  failed_scorers: string[];
  summary: string;
}

export interface Verdict {
  health: Health;
  headline: string;
  standing: string;
  evidence: string;
  baseline_delta: number | null;
}

export interface MetricComparison {
  name: string;
  label: string;
  kind: string;
  baseline_value: number;
  candidate_value: number;
  delta: number;
  relative_delta: number | null;
  severity: string;
  regressed: boolean;
  reason: string;
}

export interface Comparison {
  feature: string;
  baseline_run_id: string;
  candidate_run_id: string;
  baseline_prompt_version: string;
  candidate_prompt_version: string;
  baseline_dataset_version: string;
  candidate_dataset_version: string;
  prompt_changed: boolean;
  dataset_changed: boolean;
  severity: string;
  warning_count: number;
  critical_count: number;
  is_blocking: boolean;
  has_regression: boolean;
  comparisons: MetricComparison[];
  regressions: MetricComparison[];
}

export interface Recommendations {
  is_perfect: boolean;
  total_cases: number;
  failing_cases: number;
  current_pass_rate: number;
  points_to_recover: number;
  gap_to_baseline: number | null;
  by_category: { category: string; failing: number; recoverable_points: number }[];
}

export interface RunDetail {
  run_uuid: string;
  feature: string;
  display_name: string;
  label: string;
  short_label: string;
  sequence: number | null;
  model: string;
  prompt_version: string;
  dataset_version: string;
  status: string;
  triggered_by: string;
  start_time: string;
  end_time: string;
  duration_seconds: number;
  is_baseline: boolean;
  segment_field: string | null;
  verdict: Verdict;
  metrics: Metrics;
  baseline: { run_uuid: string | null; label: string | null; pass_rate: number | null } | null;
  regression: Comparison | null;
  recommendations: Recommendations;
  cases: CaseRow[];
}

export interface TrendPoint {
  run_uuid: string;
  sequence: number | null;
  label: string;
  started_at: string;
  pass_rate: number;
  errored: number;
  mean_latency_ms: number;
  p95_latency_ms: number;
  total_tokens: number;
  scorer_means: Record<string, number>;
}

export interface BaselineInfo {
  id: number;
  run_id: number;
  run_uuid: string | null;
  run_label: string | null;
  is_active: boolean;
  promoted_by: string;
  promoted_at: string;
  note: string;
  pass_rate: number | null;
}

export interface BaselineResponse {
  active: BaselineInfo | null;
  history: BaselineInfo[];
}

export interface DatasetCase {
  case_id: string;
  input: Record<string, unknown>;
  input_text: string;
  expected: Record<string, unknown>;
  difficulty: string;
  notes: string;
  category: string | null;
}

export interface DatasetView {
  feature: string;
  version: string;
  description: string;
  case_count: number;
  segment_field: string | null;
  coverage: {
    by_difficulty: { key: string; count: number }[];
    by_category: { key: string; count: number }[];
  };
  cases: DatasetCase[];
}

export interface RegressionsResponse {
  run_uuid: string;
  feature: string;
  has_baseline: boolean;
  comparison: Comparison | null;
  root_cause: Record<string, CaseRow[]>;
  persisted: {
    metric: string;
    baseline_value: number;
    candidate_value: number;
    delta: number;
    severity: string;
  }[];
}

async function serverGet<T>(path: string): Promise<T> {
  const res = await fetch(`${SERVER_ORIGIN}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

/** Resilient fleet fetch for the shell/home; returns [] if the API is unreachable. */
export async function getFeatures(): Promise<FeatureOverview[]> {
  try {
    return await serverGet<FeatureOverview[]>("/api/features");
  } catch {
    return [];
  }
}

export interface ActivationResult {
  feature: string;
  run_id: string;
  baseline_id: number;
  summary: {
    total_cases: number;
    passed: number;
    failed: number;
    errored: number;
    pass_rate: number;
  };
}

export interface ActivateRequest {
  feature_name: string;
  feature_type: string;
  cases: unknown[];
  system_prompt: string;
}

/** Activate an onboarded feature end-to-end (install → register → evaluate → baseline). */
export async function activateFeature(body: ActivateRequest): Promise<ActivationResult> {
  const res = await fetch("/api/onboarding/activate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail ?? "Activation failed.");
  return data as ActivationResult;
}

export const getFeature = (f: string) => serverGet<FeatureOverview>(`/api/features/${f}`);
export const getRuns = (f: string) => serverGet<RunSummary[]>(`/api/features/${f}/runs`);
export const getTrend = (f: string) => serverGet<TrendPoint[]>(`/api/features/${f}/trend`);
export const getDataset = (f: string) => serverGet<DatasetView>(`/api/features/${f}/dataset`);
export const getBaseline = (f: string) => serverGet<BaselineResponse>(`/api/features/${f}/baseline`);
export const getRun = (uuid: string) => serverGet<RunDetail>(`/api/runs/${uuid}`);
export const getRunRegressions = (uuid: string) =>
  serverGet<RegressionsResponse>(`/api/runs/${uuid}/regressions`);
export const compareRuns = (a: string, b: string) =>
  serverGet<Comparison>(`/api/compare?a=${a}&b=${b}`);
