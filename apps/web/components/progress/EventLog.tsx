"use client";

import { useEffect, useRef } from "react";
import { IngestStatusEvent } from "@/lib/api";
import { formatTime } from "@/lib/format";

interface Props {
  events: IngestStatusEvent[];
  paused?: boolean;
}

/**
 * Live event stream — the "what just happened" feed.
 *
 * Auto-scrolls to the bottom when new events arrive, but only if the
 * user is already at the bottom. If they've scrolled up to inspect
 * an earlier event, we leave the scroll position alone.
 */
export function EventLog({ events, paused }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events.length]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    stickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 16;
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-border-subtle bg-bg-surface">
      <div className="flex items-center justify-between border-b border-border-subtle px-3 py-1.5">
        <h3 className="text-sm font-medium text-text-primary">Event stream</h3>
        <div className="flex items-center gap-1">
          <span
            className={[
              "h-1.5 w-1.5 rounded-full",
              paused ? "bg-text-muted" : "animate-pulse bg-accent",
            ].join(" ")}
            aria-hidden
          />
          <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            {paused ? "idle" : "live"}
          </span>
        </div>
      </div>
      <div
        ref={ref}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[12px] leading-relaxed"
      >
        {events.length === 0 ? (
          <p className="text-text-muted">Waiting for the worker to pick up the job…</p>
        ) : (
          <ul className="space-y-0.5">
            {events.map((e, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="shrink-0 text-text-muted">{formatTime(e.at)}</span>
                <span className={`shrink-0 ${toneFor(e.status)}`}>
                  [{e.status}]
                </span>
                <span className="text-text-secondary">
                  {e.message ?? "(no message)"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function toneFor(status: string): string {
  if (status === "completed") return "text-accent";
  if (status === "failed") return "text-rose-300";
  if (status === "rasterizing" || status === "tiling") return "text-sky-300";
  return "text-text-muted";
}
