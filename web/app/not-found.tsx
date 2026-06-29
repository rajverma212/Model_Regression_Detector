import Link from "next/link";
import { ArrowLeft } from "lucide-react";

// Rendered when a route calls `notFound()` — most often a feature or run that was
// activated through the web UI on the Vercel demo deploy and lived only in one
// serverless instance's ephemeral /tmp (see docs/deploy-vercel.md). The demo
// features (baked into the committed seed DB) are always present.

export default function NotFound() {
  return (
    <div className="panel mx-auto mt-10 max-w-lg p-10 text-center">
      <p className="kicker text-mute">Not found</p>
      <p className="mt-3 font-display text-2xl leading-snug text-bright">
        This feature isn’t available here.
      </p>
      <p className="mt-2 text-[14px] text-dim">
        On the hosted demo, features you activate online aren’t durable — they
        live on a single serverless instance and disappear when it sleeps. The
        seeded demo features are always available. Run locally for persistent
        onboarding.
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex items-center gap-2 rounded-full border border-line-2 bg-surface-2 px-5 py-2.5 text-[13px] font-medium text-bright transition-colors hover:border-signal/50"
      >
        <ArrowLeft size={14} /> Back to Mission Control
      </Link>
    </div>
  );
}
