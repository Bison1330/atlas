"use client";

import { useMemo } from "react";
import { ElementSummary } from "@/lib/api";
import { styleFor } from "./elementColors";

interface Props {
  elements: ElementSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/**
 * Scrollable list of extracted elements, grouped by kind.
 *
 * Sticky kind headers carry the count for that group. Each row
 * shows the smallest set of identifying signals (NCS layer +
 * confidence pip) — full IFC properties live in the inspector.
 */
export function ElementList({ elements, selectedId, onSelect }: Props) {
  const grouped = useMemo(() => groupByKind(elements), [elements]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-bg-surface">
      <div className="border-b border-border-subtle px-3 py-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
          Elements
        </p>
        <p className="text-sm font-medium text-text-primary">
          {elements.length} extracted
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {grouped.length === 0 ? (
          <p className="px-3 py-3 text-sm text-text-muted">No elements to show.</p>
        ) : (
          grouped.map(({ kind, items }) => {
            const sty = styleFor(kind);
            return (
              <section key={kind}>
                <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border-subtle bg-bg-surface/95 px-3 py-1 backdrop-blur">
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: sty.stroke }}
                    />
                    <span className={`text-xs font-medium ${sty.textClass}`}>
                      {sty.label}
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-text-muted">
                    {items.length}
                  </span>
                </header>
                <ul>
                  {items.map((el) => (
                    <li key={el.id}>
                      <button
                        type="button"
                        onClick={() => onSelect(el.id)}
                        aria-pressed={selectedId === el.id}
                        className={[
                          "flex w-full items-center justify-between gap-3 border-b border-border-subtle/40 px-3 py-1.5 text-left transition-colors",
                          selectedId === el.id
                            ? "bg-accent/[0.08]"
                            : "hover:bg-bg-elevated",
                        ].join(" ")}
                      >
                        <div className="min-w-0">
                          <p className="truncate font-mono text-[12px] text-text-primary">
                            {el.name ?? el.number ?? el.ncs_layer ?? el.id.slice(0, 8)}
                          </p>
                          <p className="truncate font-mono text-[10px] text-text-muted">
                            {el.ifc_type ?? "—"}
                            {el.ncs_layer ? ` · ${el.ncs_layer}` : ""}
                          </p>
                        </div>
                        <ConfidencePip value={el.confidence} />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}

function ConfidencePip({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <span className="font-mono text-[10px] text-text-muted" title="Deterministic / human-authored">
        —
      </span>
    );
  }
  const tone =
    value >= 0.9
      ? "text-accent"
      : value >= 0.7
        ? "text-amber-300"
        : "text-rose-300";
  return (
    <span className={`font-mono text-[10px] tabular-nums ${tone}`}>
      {Math.round(value * 100)}%
    </span>
  );
}

function groupByKind(
  elements: ElementSummary[],
): { kind: string; items: ElementSummary[] }[] {
  const buckets = new Map<string, ElementSummary[]>();
  for (const el of elements) {
    const arr = buckets.get(el.kind) ?? [];
    arr.push(el);
    buckets.set(el.kind, arr);
  }
  return Array.from(buckets.entries())
    .map(([kind, items]) => ({ kind, items }))
    .sort((a, b) => styleFor(a.kind).order - styleFor(b.kind).order);
}
