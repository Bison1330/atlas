"use client";

import { useEffect, useRef } from "react";
import { ExtractionRunSummary, ExtractionStatus } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { useExtractionEvents } from "@/lib/useExtractionEvents";

interface Props {
  drawingId: string;
  run: ExtractionRunSummary;
  onCompleted: () => void;
  onFailed?: () => void;
}

const STAGES: { id: ExtractionStatus; label: string; short: string }[] = [
  { id: "queued", label: "Queued", short: "Waiting for a worker" },
  { id: "running", label: "Extracting", short: "Reading DXF + classifying entities" },
  { id: "completed", label: "Done", short: "Elements ready" },
];

const STAGE_ORDER: Record<ExtractionStatus, number> = {
  queued: 0,
  running: 1,
  completed: 2,
  failed: -1,
};

/**
 * Live status panel for one extraction run.
 *
 * Subscribes to the extraction event stream via :func:`useExtractionEvents`
 * and shows three things:
 *  - a 3-step stage indicator (queued → running → completed),
 *  - the latest milestone message (e.g. "elements_so_far: 150"),
 *  - a scrolling event log so a power user can watch the run land.
 *
 * Calls ``onCompleted`` exactly once when extraction reaches the
 * terminal completed state, so the parent can fetch elements and
 * pivot the UI.
 */
export function ExtractionProgress({ drawingId, run, onCompleted, onFailed }: Props) {
  const { events, status, connection } = useExtractionEvents(drawingId, run.id);
  const calledTerminalRef = useRef(false);

  // Initial status comes from the run row; once events flow it's the
  // newer source of truth.
  const effectiveStatus: ExtractionStatus = status ?? run.status;

  useEffect(() => {
    if (calledTerminalRef.current) return;
    if (effectiveStatus === "completed") {
      calledTerminalRef.current = true;
      onCompleted();
    } else if (effectiveStatus === "failed") {
      calledTerminalRef.current = true;
      onFailed?.();
    }
  }, [effectiveStatus, onCompleted, onFailed]);

  const idx = STAGE_ORDER[effectiveStatus];
  const errored = effectiveStatus === "failed";

  // Latest meaningful message for the headline.
  const latest = events[events.length - 1];
  const headline = headlineFor(effectiveStatus, latest, run);

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface">
      <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
            Extraction
          </p>
          <p className="text-sm font-medium text-text-primary">{headline}</p>
        </div>
        <ConnectionBadge isLive={connection.kind === "open"} />
      </div>

      {/* Stage indicator */}
      <ol className="flex items-center gap-2 px-3 py-3" aria-label="Extraction progress">
        {STAGES.map((stage, i) => {
          const state =
            errored && i >= 1
              ? "errored"
              : i < idx
                ? "done"
                : i === idx
                  ? "active"
                  : "pending";
          const isLast = i === STAGES.length - 1;
          return (
            <li key={stage.id} className="flex flex-1 items-center">
              <Dot state={state} />
              <div className="ml-2 min-w-0">
                <p
                  className={[
                    "text-xs font-medium",
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
                <p className="hidden text-[10px] text-text-muted md:block">
                  {stage.short}
                </p>
              </div>
              {!isLast && (
                <div
                  className={[
                    "ml-2 h-px flex-1",
                    state === "done" ? "bg-accent/60" : "bg-border-subtle",
                  ].join(" ")}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>

      {errored && (
        <div className="mx-3 mb-3 rounded-md border border-rose-500/30 bg-rose-500/[0.06] p-2">
          <p className="font-mono text-[11px] uppercase tracking-wider text-rose-300">
            {run.error_code ?? latest?.error_code ?? "extraction_failed"}
          </p>
          <p className="mt-1 text-sm text-text-primary">
            {run.error_message ?? latest?.error_message ?? "Extraction failed."}
          </p>
        </div>
      )}

      {/* Event log */}
      <EventLog events={events} runStartedAt={run.created_at} />
    </div>
  );
}

function headlineFor(
  status: ExtractionStatus,
  latest: { type?: string; elements_so_far?: number; summary?: Record<string, unknown> } | undefined,
  run: ExtractionRunSummary,
): string {
  if (status === "queued") return "Waiting in queue…";
  if (status === "running") {
    if (latest?.elements_so_far)
      return `Classifying entities — ${latest.elements_so_far} elements so far`;
    return "Reading DXF…";
  }
  if (status === "completed") {
    const summary = (latest?.summary as { elements_written?: number } | undefined) ??
      (run.summary as { elements_written?: number });
    const n = summary?.elements_written;
    return n != null
      ? `Extracted ${n} element${n === 1 ? "" : "s"}.`
      : "Extraction complete.";
  }
  if (status === "failed") return "Extraction failed.";
  return "Extracting…";
}

function ConnectionBadge({ isLive }: { isLive: boolean }) {
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-text-muted">
      <span
        className={[
          "h-1.5 w-1.5 rounded-full",
          isLive ? "animate-pulse bg-accent" : "bg-text-muted",
        ].join(" ")}
        aria-hidden
      />
      {isLive ? "live" : "idle"}
    </span>
  );
}

function Dot({
  state,
}: {
  state: "done" | "active" | "pending" | "errored";
}) {
  if (state === "done") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-bg-base">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
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
      <span className="relative flex h-5 w-5 items-center justify-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-accent/30" aria-hidden />
        <span className="relative h-2.5 w-2.5 rounded-full bg-accent" />
      </span>
    );
  }
  if (state === "errored") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border border-rose-500/60 bg-rose-500/[0.08] text-rose-300">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
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
    <span className="flex h-5 w-5 items-center justify-center rounded-full border border-border-subtle bg-bg-surface" aria-hidden>
      <span className="h-1.5 w-1.5 rounded-full bg-text-muted" />
    </span>
  );
}

function EventLog({
  events,
  runStartedAt,
}: {
  events: { type: string; elements_so_far?: number; receivedAt: number }[];
  runStartedAt: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div
      ref={ref}
      className="max-h-32 overflow-y-auto border-t border-border-subtle px-3 py-2 font-mono text-[11px] leading-relaxed"
    >
      <div className="text-text-muted">
        {formatTime(runStartedAt)} <span className="text-accent">[queued]</span> Run created
      </div>
      {events.map((e, i) => {
        const verb = e.type.split(".")[1] ?? e.type;
        const detail =
          verb === "progress" && e.elements_so_far != null
            ? ` ${e.elements_so_far} elements so far`
            : "";
        return (
          <div key={i} className="text-text-secondary">
            <span className="text-text-muted">{formatTime(new Date(e.receivedAt).toISOString())}</span>{" "}
            <span className={tone(verb)}>[{verb}]</span>
            {detail}
          </div>
        );
      })}
    </div>
  );
}

function tone(verb: string): string {
  if (verb === "completed") return "text-accent";
  if (verb === "failed") return "text-rose-300";
  if (verb === "started" || verb === "progress") return "text-sky-300";
  return "text-text-muted";
}
