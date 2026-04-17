import Link from "next/link";

import type { DrawingListItem } from "@/lib/api";

import { StatusDot } from "./StatusDot";


function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}


function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - then);
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}


/**
 * One row in the drawings list. Link-on-click to the viewer.
 *
 * Design tokens only — no hardcoded colors. Matches the dense-list
 * layout decision from the research doc (D-19-B).
 */
export function DrawingRow({ drawing }: { drawing: DrawingListItem }) {
  const sheets =
    drawing.page_count === null
      ? null
      : drawing.page_count === 1
        ? "1 sheet"
        : `${drawing.page_count} sheets`;

  return (
    <Link
      href={`/drawings/${drawing.id}`}
      className="block rounded border border-border-subtle bg-bg-surface hover:bg-bg-elevated hover:border-accent/40 transition-colors px-2 py-1.5 mb-1"
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm text-text-primary font-medium truncate">
            {drawing.source_filename}
          </div>
          <div className="text-xs text-text-muted truncate mt-0.5 flex items-center gap-1 flex-wrap">
            {drawing.project_name ? (
              <span>
                <span className="text-text-muted">project:</span>{" "}
                <span className="text-text-secondary">{drawing.project_name}</span>
              </span>
            ) : null}
            {drawing.project_id ? (
              <span className="rounded-sm border border-border-subtle px-0.5 py-0 text-[10px] text-text-secondary uppercase">
                shared
              </span>
            ) : null}
            <span className="text-text-muted">
              {drawing.is_owner ? "you" : "shared with you"}
            </span>
            <span className="text-text-muted">·</span>
            <span>{formatRelative(drawing.updated_at)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusDot status={drawing.status} progress={drawing.progress_percent} />
          {sheets ? (
            <span className="text-xs text-text-muted">{sheets}</span>
          ) : null}
          <span className="text-xs text-text-muted font-mono">
            {formatBytes(drawing.size_bytes)}
          </span>
        </div>
      </div>
    </Link>
  );
}
