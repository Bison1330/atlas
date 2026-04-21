"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { DrawingSummary, sheetHas2DTiles } from "@/lib/api";
import { Model3DCanvas } from "./Model3DCanvas";
import { SheetCanvas } from "./SheetCanvas";
import { SheetSwitcher } from "./SheetSwitcher";

interface Props {
  drawing: DrawingSummary;
}

type ViewMode = "2d" | "3d";

/**
 * Multi-sheet viewer surface.
 *
 * Keyboard shortcuts intentionally mirror the bare minimum a power
 * user expects on day one — left/right to flip pages, "1" to jump
 * to the first page, "v" to toggle the 2D ↔ 3D canvas. We
 * deliberately do *not* swallow input that any normal text field
 * would handle.
 *
 * **Default mode** is chosen from the first sheet's metadata: DXF-
 * sourced drawings have no 2D tiles, so landing on 2D would show a
 * "preview unavailable" empty state. We pick 3D up front for those,
 * and disable the 2D pill with a tooltip.
 */
export function ViewerView({ drawing }: Props) {
  const sheets = drawing.sheets;
  const [activeId, setActiveId] = useState<string | null>(sheets[0]?.id ?? null);

  const active = sheets.find((s) => s.id === activeId) ?? sheets[0] ?? null;
  const twoDAvailable = useMemo(
    () => sheets.some(sheetHas2DTiles),
    [sheets],
  );
  const [mode, setMode] = useState<ViewMode>(twoDAvailable ? "2d" : "3d");
  const activeHasTiles = active ? sheetHas2DTiles(active) : false;

  // If the user navigates to a sheet that lacks 2D tiles while in 2D
  // mode, slide over to 3D automatically — beats the empty state on
  // sheet-change.
  useEffect(() => {
    if (mode === "2d" && active && !activeHasTiles) {
      setMode("3d");
    }
  }, [mode, active, activeHasTiles]);

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
      else if (e.key === "v" || e.key === "V") {
        setMode((prev) => {
          // Respect the 2D-unavailable guard here too — `V` is a
          // power-user shortcut, but it still shouldn't land on a
          // broken mode.
          if (prev === "3d" && !activeHasTiles) return "3d";
          return prev === "2d" ? "3d" : "2d";
        });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goto, sheets, activeHasTiles]);

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
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-border-subtle bg-bg-surface p-0.5">
            {(["2d", "3d"] as const).map((m) => {
              const disabled = m === "2d" && !activeHasTiles;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => !disabled && setMode(m)}
                  aria-pressed={mode === m}
                  aria-disabled={disabled}
                  disabled={disabled}
                  title={
                    disabled
                      ? "Not available for this drawing"
                      : undefined
                  }
                  className={[
                    "rounded-md px-3 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors",
                    mode === m
                      ? "bg-accent/15 text-accent shadow-glow"
                      : disabled
                      ? "cursor-not-allowed text-text-muted/40"
                      : "text-text-muted hover:text-text-secondary",
                  ].join(" ")}
                >
                  {m}
                </button>
              );
            })}
          </div>
          {mode === "2d" && activeHasTiles && (
            <p className="font-mono text-[11px] text-text-muted">
              {active.width_px}×{active.height_px}px · {active.dpi} DPI · zoom 0–{active.max_zoom}
            </p>
          )}
        </div>
      </div>

      <SheetSwitcher
        drawingId={drawing.id}
        sheets={sheets}
        active={active.id}
        onSelect={setActiveId}
      />

      <div className="h-[70vh] min-h-[480px]">
        {mode === "2d" ? (
          <SheetCanvas
            drawingId={drawing.id}
            sheet={active}
            onSwitchToMode3D={() => setMode("3d")}
          />
        ) : (
          <Model3DCanvas drawingId={drawing.id} sheet={active} />
        )}
      </div>

      <p className="text-xs text-text-muted">
        {mode === "2d"
          ? "Pan with click-drag · pinch or scroll to zoom · ←/→ to flip pages · V to toggle 3D"
          : "Drag to orbit · scroll to zoom · pitch down for floor plan · R to reset · V to toggle 2D"}
      </p>
    </div>
  );
}
