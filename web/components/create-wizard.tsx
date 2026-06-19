"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleCheck,
  FileJson,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { activateFeature, type ActivationResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/status";

interface FieldSpec {
  name: string;
  type: string;
  values: string[];
  required: boolean;
}
interface ScorerSpec {
  field: string;
  scorer: string;
}
interface Spec {
  feature_name: string;
  input_fields: FieldSpec[];
  output_fields: FieldSpec[];
  scoring: ScorerSpec[];
  segment_field: string | null;
}

const STEPS = ["Define", "Dataset", "Schema", "Prompt", "Activate"] as const;

const SAMPLE = JSON.stringify(
  [
    { id: "c1", input: { message: "I was double charged this month" }, expected_output: { category: "billing" } },
    { id: "c2", input: { message: "The app crashes on launch" }, expected_output: { category: "technical" } },
    { id: "c3", input: { message: "How do I reset my password?" }, expected_output: { category: "account" } },
    { id: "c4", input: { message: "Do you have a student discount?" }, expected_output: { category: "general" } },
    { id: "c5", input: { message: "My invoice total looks wrong" }, expected_output: { category: "billing" } },
    { id: "c6", input: { message: "Two-factor codes never arrive" }, expected_output: { category: "account" } },
  ],
  null,
  2,
);

export function CreateWizard() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [type, setType] = useState("classification");
  const [text, setText] = useState("");
  const [spec, setSpec] = useState<Spec | null>(null);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activating, setActivating] = useState(false);
  const [activated, setActivated] = useState<ActivationResult | null>(null);

  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

  function parseCases(): unknown[] | null {
    try {
      const v = JSON.parse(text);
      const cases = Array.isArray(v) ? v : (v as { cases?: unknown[] }).cases;
      if (!Array.isArray(cases) || cases.length === 0) throw new Error();
      return cases;
    } catch {
      setError("Dataset must be a JSON array of cases (or { cases: [...] }).");
      return null;
    }
  }

  async function infer() {
    const cases = parseCases();
    if (!cases) return;
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/onboarding/infer", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ feature_name: slug, feature_type: type, cases }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Could not infer a schema from this dataset.");
        return;
      }
      setSpec(data.spec);
      setPrompt(data.prompt);
      setStep(2);
    } catch {
      setError("Inference request failed.");
    } finally {
      setLoading(false);
    }
  }

  async function activate() {
    const cases = parseCases();
    if (!cases) return;
    setError(null);
    setActivating(true);
    try {
      const result = await activateFeature({
        feature_name: slug,
        feature_type: type,
        cases,
        system_prompt: prompt,
      });
      setActivated(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Activation failed.");
    } finally {
      setActivating(false);
    }
  }

  const canNext = step === 0 ? slug.length >= 2 : step === 1 ? text.trim().length > 0 : true;

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[200px_1fr]">
      {/* Stepper */}
      <ol className="hidden lg:block">
        {STEPS.map((label, i) => (
          <li key={label} className="relative flex items-start gap-3 pb-7 last:pb-0">
            {i < STEPS.length - 1 && (
              <span className="absolute left-[11px] top-6 h-full w-px bg-line" />
            )}
            <span
              className={cn(
                "z-10 grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px] font-mono transition-colors",
                i < step
                  ? "border-signal bg-signal text-ink"
                  : i === step
                    ? "border-signal text-signal"
                    : "border-line text-mute",
              )}
            >
              {i < step ? <Check size={13} /> : i + 1}
            </span>
            <span className={cn("pt-0.5 text-[13px]", i === step ? "text-bright" : "text-mute")}>{label}</span>
          </li>
        ))}
      </ol>

      {/* Step body */}
      <div className="min-w-0">
        {step === 0 && (
          <Panel title="Define the feature" sub="Name the AI feature and pick its shape.">
            <label className="block">
              <span className="kicker">Feature name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Support Intent Classifier"
                className="mt-1.5 h-11 w-full rounded-xl border border-line bg-surface/50 px-3.5 text-[14px] text-text placeholder:text-mute focus:border-signal/40 focus:outline-none"
              />
              {slug && <p className="mt-1.5 font-mono text-[11.5px] text-mute">id: {slug}</p>}
            </label>
            <div className="mt-5">
              <span className="kicker">Kind</span>
              <div className="mt-1.5 grid grid-cols-2 gap-3">
                {[
                  { k: "classification", t: "Classification", d: "One label per input" },
                  { k: "routing", t: "Routing", d: "Multiple labels (e.g. category + priority)" },
                ].map((o) => (
                  <button
                    key={o.k}
                    type="button"
                    onClick={() => setType(o.k)}
                    className={cn(
                      "rounded-xl border p-4 text-left transition-colors",
                      type === o.k ? "border-signal/50 bg-signal/[0.07]" : "border-line bg-surface/30 hover:border-line-2",
                    )}
                  >
                    <p className="text-[14px] font-medium text-bright">{o.t}</p>
                    <p className="mt-1 text-[12px] text-mute">{o.d}</p>
                  </button>
                ))}
              </div>
            </div>
          </Panel>
        )}

        {step === 1 && (
          <Panel
            title="Bring your golden dataset"
            sub="Labeled examples are the ground truth. Eval OS infers the schema from them."
          >
            <div className="mb-3 flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => setText(SAMPLE)}>
                <Sparkles size={14} /> Load sample
              </Button>
              <label className="cursor-pointer">
                <Button size="sm" variant="ghost" asChild>
                  <span>
                    <Upload size={14} /> Upload .json
                  </span>
                </Button>
                <input
                  type="file"
                  accept="application/json,.json"
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file) setText(await file.text());
                  }}
                />
              </label>
            </div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder='[ { "id": "c1", "input": { "message": "…" }, "expected_output": { "category": "billing" } } ]'
              spellCheck={false}
              className="h-72 w-full resize-none rounded-xl border border-line bg-ink-2 p-4 font-mono text-[12.5px] leading-relaxed text-dim placeholder:text-mute focus:border-signal/40 focus:outline-none"
            />
          </Panel>
        )}

        {step === 2 && spec && (
          <Panel title="Inferred schema" sub="Eval OS read your labels and proposed this contract.">
            <SchemaReview spec={spec} />
          </Panel>
        )}

        {step === 3 && (
          <Panel title="Instructions" sub="A starter prompt, scaffolded from the schema. Edit freely.">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              spellCheck={false}
              className="h-72 w-full resize-none rounded-xl border border-line bg-ink-2 p-4 font-mono text-[12.5px] leading-relaxed text-text focus:border-signal/40 focus:outline-none"
            />
          </Panel>
        )}

        {step === 4 && spec && !activated && (
          <Panel title="Ready to activate" sub="">
            <div className="flex items-start gap-4 rounded-xl border border-healthy/25 bg-healthy/[0.05] p-5">
              <CircleCheck className="mt-0.5 shrink-0 text-healthy" size={22} />
              <div>
                <p className="text-[15px] font-medium text-bright">{slug} is defined and validated.</p>
                <p className="mt-1.5 text-[13px] leading-relaxed text-dim">
                  Activation writes the feature bundle into the platform, registers it, runs its first
                  evaluation, and promotes the result as a baseline — after which{" "}
                  <span className="text-text">{slug}</span> appears in Mission Control. This calls the
                  model, so it can take a moment.
                </p>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <Summary k="Output fields" v={String(spec.output_fields.length)} />
              <Summary k="Scorers" v={String(spec.scoring.length)} />
              <Summary k="Segment" v={spec.segment_field ?? "—"} />
            </div>
            <div className="mt-6 flex gap-3">
              <Button variant="signal" disabled={activating} onClick={activate}>
                {activating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                {activating ? "Activating…" : "Activate feature"}
              </Button>
              <Button asChild variant="ghost">
                <Link href="/">
                  <ArrowLeft size={15} /> Cancel
                </Link>
              </Button>
            </div>
          </Panel>
        )}

        {step === 4 && activated && (
          <Panel title="Activated" sub="">
            <div className="flex items-start gap-4 rounded-xl border border-healthy/25 bg-healthy/[0.05] p-5">
              <CircleCheck className="mt-0.5 shrink-0 text-healthy" size={22} />
              <div>
                <p className="text-[15px] font-medium text-bright">
                  {activated.feature} is live in Mission Control.
                </p>
                <p className="mt-1.5 text-[13px] leading-relaxed text-dim">
                  First evaluation complete and promoted as the baseline.
                </p>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-4 gap-3">
              <Summary k="Cases" v={String(activated.summary.total_cases)} />
              <Summary k="Passed" v={String(activated.summary.passed)} />
              <Summary k="Failed" v={String(activated.summary.failed)} />
              <Summary k="Pass rate" v={`${Math.round(activated.summary.pass_rate * 100)}%`} />
            </div>
            <div className="mt-6 flex gap-3">
              <Button asChild variant="signal">
                <Link href={`/features/${activated.feature}`}>
                  Open {activated.feature} <ArrowRight size={15} />
                </Link>
              </Button>
              <Button asChild variant="ghost">
                <Link href="/">
                  <ArrowLeft size={15} /> Mission Control
                </Link>
              </Button>
            </div>
          </Panel>
        )}

        {error && (
          <p className="mt-4 rounded-lg border border-critical/30 bg-critical/[0.07] px-3.5 py-2.5 text-[13px] text-critical">
            {error}
          </p>
        )}

        {/* Nav */}
        {step < 4 && (
          <div className="mt-6 flex items-center justify-between">
            <Button
              variant="ghost"
              onClick={() => {
                setError(null);
                setStep((s) => Math.max(0, s - 1));
              }}
              disabled={step === 0}
            >
              <ArrowLeft size={15} /> Back
            </Button>
            <Button
              variant="signal"
              disabled={!canNext || loading}
              onClick={() => {
                setError(null);
                if (step === 1) infer();
                else setStep((s) => s + 1);
              }}
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : null}
              {step === 1 ? "Infer schema" : "Continue"}
              {!loading && <ArrowRight size={15} />}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Panel({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="panel p-6">
      <h2 className="font-display text-2xl text-bright">{title}</h2>
      {sub && <p className="mt-1.5 text-[13.5px] text-dim">{sub}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function SchemaReview({ spec }: { spec: Spec }) {
  return (
    <div className="space-y-5">
      <FieldGroup title="Input" fields={spec.input_fields} icon={<FileJson size={14} className="text-mute" />} />
      <FieldGroup title="Output" fields={spec.output_fields} icon={<FileJson size={14} className="text-signal" />} />
      <div>
        <p className="kicker mb-2">Scoring</p>
        <div className="flex flex-wrap gap-2">
          {spec.scoring.map((s) => (
            <Tag key={s.field} className="border-signal/25 text-signal/90">
              {s.field} → {s.scorer}
            </Tag>
          ))}
          {spec.segment_field && <Tag>segment: {spec.segment_field}</Tag>}
        </div>
      </div>
    </div>
  );
}

function FieldGroup({ title, fields, icon }: { title: string; fields: FieldSpec[]; icon: React.ReactNode }) {
  return (
    <div>
      <p className="kicker mb-2 flex items-center gap-1.5">
        {icon} {title}
      </p>
      <div className="overflow-hidden rounded-xl border border-line">
        {fields.map((f, i) => (
          <div
            key={f.name}
            className={cn("flex items-center gap-3 px-4 py-2.5 text-[13px]", i > 0 && "border-t border-line")}
          >
            <span className="font-mono text-text">{f.name}</span>
            <Tag>{f.type}</Tag>
            {f.values.length > 0 && (
              <span className="truncate font-mono text-[11.5px] text-mute">{f.values.join(" · ")}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Summary({ k, v }: { k: string; v: string }) {
  return (
    <div className="panel-inset p-4">
      <p className="kicker">{k}</p>
      <p className="mt-1 font-mono text-lg text-bright">{v}</p>
    </div>
  );
}
