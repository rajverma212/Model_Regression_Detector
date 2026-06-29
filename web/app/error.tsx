"use client";

// Route-level error boundary. Catches anything thrown while rendering a page or
// nested segment (e.g. a backend 5xx or an unreachable serverless cold start)
// and shows a recoverable fallback inside the app shell — instead of letting the
// exception bubble to Next's full-screen "This page couldn't load" error.

import { useEffect } from "react";
import { RotateCw } from "lucide-react";

export default function RouteError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    // Surfaces in the browser console / Vercel logs; the digest matches server logs.
    console.error(error);
  }, [error]);

  return (
    <div className="panel mx-auto mt-10 max-w-lg p-10 text-center">
      <p className="kicker text-warning">Couldn’t reach the evaluation backend</p>
      <p className="mt-3 font-display text-2xl leading-snug text-bright">
        This view didn’t load.
      </p>
      <p className="mt-2 text-[14px] text-dim">
        Usually a transient serverless cold start — the backend was waking up.
        Retry and it almost always loads on the second try.
      </p>
      <button
        type="button"
        onClick={() => unstable_retry()}
        className="mt-6 inline-flex items-center gap-2 rounded-full border border-line-2 bg-surface-2 px-5 py-2.5 text-[13px] font-medium text-bright transition-colors hover:border-signal/50"
      >
        <RotateCw size={14} /> Retry
      </button>
      {error.digest && (
        <p className="mt-4 font-mono text-[11px] text-mute">ref: {error.digest}</p>
      )}
    </div>
  );
}
