"use client";

import { IngestStatus } from "@/lib/api";
import { stageDef } from "@/lib/stages";

interface Props {
  status: IngestStatus;
  percent: number;
  message: string | null;
  errored?: boolean;
}

/**
 * The big "what's happening right now" panel.
 *
 * The bar uses a content-first transition: the width animates so the
 * eye tracks the progress, but the underlying message updates in
 * place to keep the line height stable.
 */
export function OverallProgress({ status, percent, message, errored }: Props) {
  const stage = stageDef(status);

  return (
    <div className="rounded-xl border border-border-subtle bg-bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted">
            {errored ? "halted" : status === "completed" ? "done" : "in progress"}
          </p>
          <h2 className="mt-0.5 text-xl font-medium tracking-tight text-text-primary">
            {errored ? "Pipeline failed" : stage.label}
          </h2>
        </div>
        <div className="text-right">
          <p
            className={[
              "font-mono text-2xl tabular-nums tracking-tight",
              errored ? "text-rose-300" : "text-accent",
            ].join(" ")}
          >
            {percent}%
          </p>
          <p className="text-[11px] text-text-muted">overall</p>
        </div>
      </div>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-bg-elevated"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={[
            "h-full rounded-full transition-[width] duration-500 ease-out",
            errored ? "bg-rose-400/80" : "bg-accent shadow-glow",
          ].join(" ")}
          style={{ width: `${Math.max(2, Math.min(100, percent))}%` }}
        />
      </div>

      <p className="mt-2 min-h-[20px] text-sm text-text-secondary">
        {message ?? (errored ? "An unrecoverable error stopped the ingest." : "Working…")}
      </p>
    </div>
  );
}
