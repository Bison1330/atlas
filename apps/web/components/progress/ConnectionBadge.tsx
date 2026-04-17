"use client";

import { ConnectionState } from "@/lib/useDrawingProgress";

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  let label: string;
  let tone: string;
  let pulse = false;

  switch (state.kind) {
    case "open":
      label = "Live";
      tone = "border-accent/40 bg-accent/[0.06] text-accent";
      pulse = true;
      break;
    case "connecting":
      label = state.attempt > 0 ? `Connecting (#${state.attempt})` : "Connecting";
      tone = "border-border-subtle bg-bg-surface text-text-secondary";
      break;
    case "reconnecting":
      label = `Reconnecting in ${Math.ceil(state.nextRetryMs / 1000)}s`;
      tone = "border-amber-500/40 bg-amber-500/[0.06] text-amber-300";
      break;
    case "closed":
      label = state.reason;
      tone = "border-rose-500/40 bg-rose-500/[0.06] text-rose-300";
      break;
    case "done":
      label = "Stream closed";
      tone = "border-border-subtle bg-bg-surface text-text-muted";
      break;
  }

  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider",
        tone,
      ].join(" ")}
    >
      <span
        className={[
          "h-1.5 w-1.5 rounded-full",
          pulse ? "animate-pulse bg-accent" : "bg-current",
        ].join(" ")}
        aria-hidden
      />
      {label}
    </span>
  );
}
