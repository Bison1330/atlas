"use client";

import { IngestStatus } from "@/lib/api";
import { stageDef } from "@/lib/stages";

/**
 * Side panel that explains the *current* pipeline stage in plain
 * English. Updates in place as the stage advances — same surface,
 * fresh contents — so the user can learn what each step does
 * without leaving the progress page.
 */
export function EducationCard({ status }: { status: IngestStatus }) {
  const stage = stageDef(status);

  return (
    <div className="rounded-xl border border-border-subtle bg-bg-surface p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
        What&apos;s happening
      </p>
      <h3 className="mt-1 text-base font-medium text-text-primary">{stage.label}</h3>
      <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
        {stage.detail}
      </p>
    </div>
  );
}
