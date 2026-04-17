"use client";

import { IngestStatus } from "@/lib/api";
import { STAGES, STAGE_INDEX, stageDef } from "@/lib/stages";

interface Props {
  status: IngestStatus;
  errored?: boolean;
}

/**
 * Horizontal stepper for the four pipeline stages.
 *
 * The active stage pulses softly. Completed stages turn accent-green
 * and earn a checkmark. The "Ready" stage only fills in once we hit
 * `completed` — it's intentionally distinct so the user can see the
 * difference between "still tiling" and "finished".
 */
export function StageStepper({ status, errored = false }: Props) {
  const idx = errored ? STAGE_INDEX.tiling : STAGE_INDEX[status];

  return (
    <ol className="flex w-full items-center" aria-label="Ingest progress">
      {STAGES.map((stage, i) => {
        const isLast = i === STAGES.length - 1;
        const state =
          errored && i >= idx
            ? "errored"
            : i < idx
              ? "done"
              : i === idx
                ? "active"
                : "pending";

        return (
          <li key={stage.status} className="flex flex-1 items-center">
            <div className="flex flex-col items-center">
              <Dot state={state} />
              <p
                className={[
                  "mt-1 max-w-[120px] text-center text-xs font-medium tracking-tight",
                  state === "done"
                    ? "text-text-secondary"
                    : state === "active"
                      ? "text-accent"
                      : state === "errored"
                        ? "text-rose-300"
                        : "text-text-muted",
                ].join(" ")}
              >
                {stage.label}
              </p>
              <p className="mt-0.5 hidden max-w-[140px] text-center text-[11px] leading-tight text-text-muted md:block">
                {stage.short}
              </p>
            </div>
            {!isLast && (
              <div
                className={[
                  "mb-5 h-px flex-1 transition-colors duration-500",
                  state === "done" || (state === "active" && i + 1 <= idx)
                    ? "bg-accent/60"
                    : "bg-border-subtle",
                ].join(" ")}
                aria-hidden
              />
            )}
          </li>
        );
      })}
      {errored && (
        <li className="ml-3 hidden md:block">
          <span className="rounded-md border border-rose-500/40 bg-rose-500/[0.06] px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider text-rose-300">
            {stageDef("failed").label}
          </span>
        </li>
      )}
    </ol>
  );
}

function Dot({ state }: { state: "done" | "active" | "pending" | "errored" }) {
  if (state === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-bg-base shadow-glow">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M5 13l4 4L19 7"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  if (state === "active") {
    return (
      <span className="relative flex h-6 w-6 items-center justify-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-accent/30" aria-hidden />
        <span className="relative h-3 w-3 rounded-full bg-accent" />
      </span>
    );
  }
  if (state === "errored") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-rose-500/60 bg-rose-500/[0.08] text-rose-300">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M6 6l12 12M18 6L6 18"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border-subtle bg-bg-surface" aria-hidden>
      <span className="h-1.5 w-1.5 rounded-full bg-text-muted" />
    </span>
  );
}
