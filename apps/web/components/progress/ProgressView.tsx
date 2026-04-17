"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DrawingStatus,
  DrawingSummary,
  TERMINAL_STATUSES,
  getDrawing,
  getDrawingStatus,
} from "@/lib/api";
import { useDrawingProgress } from "@/lib/useDrawingProgress";
import { ConnectionBadge } from "./ConnectionBadge";
import { EducationCard } from "./EducationCard";
import { EventLog } from "./EventLog";
import { OverallProgress } from "./OverallProgress";
import { SheetGrid } from "./SheetGrid";
import { StageStepper } from "./StageStepper";

interface Props {
  drawingId: string;
  /** When the drawing finishes, render the viewer instead of progress. */
  onCompleted: (summary: DrawingSummary) => void;
  initialSnapshot: DrawingStatus | null;
}

/**
 * Composes the live-progress experience.
 *
 * Data sources, in priority order:
 *  1. The WebSocket event stream (real-time, sub-second latency).
 *  2. The initial REST snapshot (so we render something before the
 *     WS hands us its first event — important when joining late).
 *  3. A fallback REST poll on a slow timer in case the WS dies and
 *     reconnects can't catch the terminal event.
 *
 * When the drawing reaches a terminal `completed` state we fetch the
 * full summary (with sheets) and hand it up to the parent so it can
 * mount the viewer.
 */
export function ProgressView({ drawingId, onCompleted, initialSnapshot }: Props) {
  const { current, events, connection } = useDrawingProgress(drawingId);
  const [snapshot, setSnapshot] = useState<DrawingStatus | null>(initialSnapshot);

  // Keep the lightweight snapshot fresh: the WS gives us per-event
  // updates but the REST snapshot has the canonical page_count which
  // we want for the SheetGrid placeholders.
  useEffect(() => {
    if (!current || snapshot?.page_count) return;
    let cancelled = false;
    getDrawingStatus(drawingId).then(
      (s) => !cancelled && setSnapshot(s),
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [current, snapshot?.page_count, drawingId]);

  // Once we hit terminal, fetch the full summary (which includes the
  // sheets list) and notify the parent.
  useEffect(() => {
    if (!current) return;
    if (current.status !== "completed") return;
    let cancelled = false;
    getDrawing(drawingId).then(
      (d) => {
        if (!cancelled) onCompleted(d);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [current, drawingId, onCompleted]);

  const status = current?.status ?? snapshot?.status ?? "queued";
  const percent = current?.progress_percent ?? snapshot?.progress_percent ?? 0;
  const message = current?.message ?? snapshot?.progress_message ?? null;
  const errored = status === "failed";
  const pageCount = snapshot?.page_count ?? null;

  const isLive =
    connection.kind === "open" || connection.kind === "connecting";
  const isTerminal = TERMINAL_STATUSES.has(status);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <StageStepper status={status} errored={errored} />
        <div className="ml-3 hidden md:block">
          <ConnectionBadge state={connection} />
        </div>
      </div>

      <div className="md:hidden">
        <ConnectionBadge state={connection} />
      </div>

      <OverallProgress
        status={status}
        percent={percent}
        message={message}
        errored={errored}
      />

      {errored && current?.error_code && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/[0.06] p-3">
          <p className="font-mono text-[11px] uppercase tracking-wider text-rose-300">
            {current.error_code}
          </p>
          <p className="mt-1 text-sm text-text-primary">
            {current.message ?? "Pipeline failed."}
          </p>
          <p className="mt-2 text-xs text-text-muted">
            Try uploading the file again, or use a different PDF.
          </p>
          <Link
            href="/upload"
            className="mt-3 inline-flex items-center gap-1 rounded-md border border-border-subtle px-2 py-1 text-xs text-text-secondary hover:border-text-muted hover:text-text-primary"
          >
            Back to upload
          </Link>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <SheetGrid events={events} pageCount={pageCount} />
          <EventLog events={events} paused={!isLive && !isTerminal} />
        </div>
        <EducationCard status={status} />
      </div>
    </div>
  );
}
