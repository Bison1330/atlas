"use client";

import { useEffect, useState } from "react";
import { TakeoffReport, getTakeoffs } from "@/lib/api";
import { styleFor } from "./elementColors";

interface Props {
  drawingId: string;
  /** Pin to a specific extraction run; defaults to the latest completed. */
  sourceId?: string;
}

/**
 * Material takeoff report for a drawing.
 *
 * Fetches GET /drawings/{id}/takeoffs and renders one card per
 * category (walls, rooms, doors, …) with counts + linear/area
 * aggregates. Subcategory rows (NCS minor for walls, NCS major
 * for rooms when there are multiple) live inside their parent
 * card, indented.
 *
 * Units caveat is shown prominently — we report DXF-unit raw
 * numbers because the schema doesn't yet record the source CAD's
 * authoring units. Better to be honest than to silently mislabel.
 */
export function TakeoffPanel({ drawingId, sourceId }: Props) {
  const [report, setReport] = useState<TakeoffReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError(null);
    getTakeoffs(drawingId, { source_id: sourceId }).then(
      (r) => {
        if (!cancelled) setReport(r);
      },
      (err) => {
        if (!cancelled) setError((err as Error).message);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [drawingId, sourceId]);

  if (error) {
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
        <p className="text-sm text-text-primary">
          Couldn&apos;t load takeoff: {error}
        </p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="space-y-2">
        <div className="h-12 animate-pulse rounded-lg bg-bg-surface" />
        <div className="h-32 animate-pulse rounded-lg bg-bg-surface" />
      </div>
    );
  }

  if (report.total_elements === 0) {
    return null;
  }

  return (
    <section className="rounded-lg border border-border-subtle bg-bg-surface">
      <header className="flex items-baseline justify-between border-b border-border-subtle px-3 py-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
            Material takeoff
          </p>
          <p className="text-sm font-medium text-text-primary">
            {report.total_elements} element{report.total_elements === 1 ? "" : "s"}
            {" · "}
            {report.kinds_present.length} kind
            {report.kinds_present.length === 1 ? "" : "s"}
          </p>
        </div>
        <p className="font-mono text-[10px] text-text-muted">
          {report.units.linear}
        </p>
      </header>

      <ul className="divide-y divide-border-subtle">
        {report.categories.map((cat) => (
          <CategoryRow key={cat.kind} category={cat} />
        ))}
      </ul>

      <footer className="border-t border-border-subtle bg-bg-base/40 px-3 py-2 text-[11px] text-text-muted">
        <span className="font-mono uppercase tracking-wider text-text-muted">
          units note ·{" "}
        </span>
        {report.units.note}
      </footer>
    </section>
  );
}

function CategoryRow({
  category,
}: {
  category: TakeoffReport["categories"][number];
}) {
  const sty = styleFor(category.kind);
  const aggregate = formatAggregate(
    category.total_linear_units,
    category.total_area_units,
  );

  return (
    <li>
      <div className="flex items-baseline justify-between gap-3 px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: sty.stroke }}
          />
          <span className={`text-sm font-medium ${sty.textClass}`}>
            {category.label}
          </span>
          <span className="font-mono text-[11px] text-text-muted">
            ×{category.count}
          </span>
        </div>
        {aggregate && (
          <span className="font-mono text-sm tabular-nums text-text-primary">
            {aggregate}
          </span>
        )}
      </div>

      {category.subcategories.length > 0 && (
        <ul className="border-t border-border-subtle/40 bg-bg-base/30">
          {category.subcategories.map((sub) => (
            <li
              key={sub.label}
              className="flex items-baseline justify-between gap-3 px-6 py-1"
            >
              <span className="font-mono text-[11px] text-text-secondary">
                {sub.label}
              </span>
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-[10px] text-text-muted">
                  ×{sub.count}
                </span>
                <span className="font-mono text-xs tabular-nums text-text-primary">
                  {formatAggregate(sub.linear_units, sub.area_units) ?? "—"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function formatAggregate(
  linear: number | null,
  area: number | null,
): string | null {
  if (linear != null) return `${linear.toLocaleString(undefined, { maximumFractionDigits: 2 })} LF`;
  if (area != null) return `${area.toLocaleString(undefined, { maximumFractionDigits: 2 })} SF`;
  return null;
}
