"use client";

import { IngestStatus, IngestStatusEvent } from "@/lib/api";
import { useMemo } from "react";

interface Props {
  events: IngestStatusEvent[];
  pageCount: number | null;
}

interface SheetState {
  sheetId: string | null;
  pageNumber: number | null;
  status: IngestStatus;
  percent: number;
  message: string | null;
}

/**
 * Per-sheet state derived from the WS event stream.
 *
 * The events arrive with sheet_id but no page_number — we infer
 * page_number by the order in which sheets first appear in the
 * stream (the worker processes pages in order). When the drawing's
 * `page_count` is known we render placeholder slots for unstarted
 * pages so the grid doesn't flicker as new sheets enter.
 */
export function SheetGrid({ events, pageCount }: Props) {
  const sheets = useMemo(() => buildSheetState(events), [events]);

  // Pad with placeholders up to pageCount so the grid is stable.
  const slots: SheetState[] = pageCount
    ? Array.from({ length: pageCount }, (_, i) => {
        const known = sheets[i];
        return (
          known ?? {
            sheetId: null,
            pageNumber: i + 1,
            status: "queued",
            percent: 0,
            message: null,
          }
        );
      })
    : sheets;

  if (slots.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-text-primary">Sheets</h3>
        <span className="font-mono text-[11px] text-text-muted">
          {slots.filter((s) => s.status === "completed").length} / {slots.length} ready
        </span>
      </div>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {slots.map((sheet) => (
          <SheetCard key={`${sheet.pageNumber}-${sheet.sheetId ?? "stub"}`} sheet={sheet} />
        ))}
      </ul>
    </div>
  );
}

function SheetCard({ sheet }: { sheet: SheetState }) {
  const tone =
    sheet.status === "completed"
      ? "border-accent/40 bg-accent/[0.04]"
      : sheet.status === "failed"
        ? "border-rose-500/40 bg-rose-500/[0.05]"
        : sheet.status === "queued"
          ? "border-border-subtle bg-bg-surface/40"
          : "border-border-subtle bg-bg-surface";

  return (
    <li
      className={[
        "relative overflow-hidden rounded-lg border p-2 transition-colors duration-300",
        tone,
      ].join(" ")}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
          page {sheet.pageNumber ?? "?"}
        </span>
        <StatusPill status={sheet.status} />
      </div>
      <div
        className="mt-2 h-1 overflow-hidden rounded-full bg-bg-elevated"
        role="progressbar"
        aria-valuenow={sheet.percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={[
            "h-full rounded-full transition-[width] duration-300 ease-out",
            sheet.status === "completed"
              ? "bg-accent"
              : sheet.status === "failed"
                ? "bg-rose-400"
                : "bg-accent/60",
          ].join(" ")}
          style={{ width: `${sheet.status === "completed" ? 100 : sheet.percent}%` }}
        />
      </div>
    </li>
  );
}

function StatusPill({ status }: { status: IngestStatus }) {
  const label =
    status === "completed"
      ? "ready"
      : status === "failed"
        ? "failed"
        : status === "queued"
          ? "queued"
          : status;
  const tone =
    status === "completed"
      ? "text-accent"
      : status === "failed"
        ? "text-rose-300"
        : status === "queued"
          ? "text-text-muted"
          : "text-text-secondary";
  return (
    <span className={`font-mono text-[10px] uppercase tracking-wider ${tone}`}>
      {label}
    </span>
  );
}

function buildSheetState(events: IngestStatusEvent[]): SheetState[] {
  // Map sheet_id → derived state, plus a discovery order for page numbers.
  const order: string[] = [];
  const map = new Map<string, SheetState>();
  for (const event of events) {
    if (!event.sheet_id) continue;
    const existing = map.get(event.sheet_id);
    if (!existing) {
      order.push(event.sheet_id);
      map.set(event.sheet_id, {
        sheetId: event.sheet_id,
        pageNumber: order.length,
        status: event.status,
        percent: percentForSheet(event),
        message: event.message,
      });
    } else {
      existing.status = event.status;
      existing.percent = percentForSheet(event);
      existing.message = event.message;
    }
  }
  return order.map((id) => map.get(id)!);
}

function percentForSheet(event: IngestStatusEvent): number {
  // Per-sheet events reuse the drawing's overall percent — for the
  // grid we just want a coarse "this card is done / in progress / not
  // started" signal, so we collapse to {0, 50, 100}.
  if (event.status === "completed") return 100;
  if (event.status === "queued") return 0;
  return 50;
}
