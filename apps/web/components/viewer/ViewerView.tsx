"use client";

import { useCallback, useEffect, useState } from "react";
import { DrawingSummary } from "@/lib/api";
import { SheetCanvas } from "./SheetCanvas";
import { SheetSwitcher } from "./SheetSwitcher";

interface Props {
  drawing: DrawingSummary;
}

/**
 * Multi-sheet viewer surface.
 *
 * Keyboard shortcuts intentionally mirror the bare minimum a power
 * user expects on day one — left/right to flip pages, "1" to jump
 * to the first page. We deliberately do *not* swallow input that
 * any normal text field would handle.
 */
export function ViewerView({ drawing }: Props) {
  const sheets = drawing.sheets;
  const [activeId, setActiveId] = useState<string | null>(sheets[0]?.id ?? null);
  const active = sheets.find((s) => s.id === activeId) ?? sheets[0] ?? null;

  const goto = useCallback(
    (delta: number) => {
      if (!active) return;
      const idx = sheets.findIndex((s) => s.id === active.id);
      if (idx === -1) return;
      const next = sheets[Math.max(0, Math.min(sheets.length - 1, idx + delta))];
      if (next) setActiveId(next.id);
    },
    [active, sheets],
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName)
      )
        return;
      if (e.key === "ArrowRight" || e.key === "j") goto(+1);
      else if (e.key === "ArrowLeft" || e.key === "k") goto(-1);
      else if (e.key === "1" && sheets[0]) setActiveId(sheets[0].id);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goto, sheets]);

  if (!active) {
    return (
      <p className="rounded-lg border border-border-subtle bg-bg-surface p-3 text-sm text-text-muted">
        This drawing has no sheets to display.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
            page {active.page_number} of {sheets.length}
          </p>
          <h2 className="text-lg font-medium text-text-primary">
            {active.title ?? `Page ${active.page_number}`}
          </h2>
        </div>
        <p className="font-mono text-[11px] text-text-muted">
          {active.width_px}×{active.height_px}px · {active.dpi} DPI · zoom 0–{active.max_zoom}
        </p>
      </div>

      <SheetSwitcher
        drawingId={drawing.id}
        sheets={sheets}
        active={active.id}
        onSelect={setActiveId}
      />

      <div className="h-[70vh] min-h-[480px]">
        <SheetCanvas drawingId={drawing.id} sheet={active} />
      </div>

      <p className="text-xs text-text-muted">
        Pan with click-drag · pinch or scroll to zoom · ←/→ to flip pages
      </p>
    </div>
  );
}
