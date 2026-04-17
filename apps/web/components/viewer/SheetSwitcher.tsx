"use client";

import { SheetSummary, previewUrl } from "@/lib/api";

interface Props {
  drawingId: string;
  sheets: SheetSummary[];
  active: string;
  onSelect: (sheetId: string) => void;
}

/**
 * Filmstrip of sheet thumbnails along the top of the viewer.
 *
 * Previews are loaded lazily; the browser handles eviction. Active
 * sheet gets the accent border so it's immediately findable.
 */
export function SheetSwitcher({ drawingId, sheets, active, onSelect }: Props) {
  return (
    <ol className="flex gap-2 overflow-x-auto py-2">
      {sheets.map((sheet) => {
        const isActive = sheet.id === active;
        return (
          <li key={sheet.id} className="shrink-0">
            <button
              type="button"
              onClick={() => onSelect(sheet.id)}
              aria-pressed={isActive}
              className={[
                "group flex flex-col items-center gap-1 rounded-lg border bg-bg-surface p-1 transition-all",
                isActive
                  ? "border-accent shadow-glow"
                  : "border-border-subtle hover:border-text-muted",
              ].join(" ")}
            >
              <div className="relative h-20 w-16 overflow-hidden rounded bg-bg-elevated">
                {sheet.preview_s3_key ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={previewUrl(drawingId, sheet.id)}
                    alt={`Preview of page ${sheet.page_number}`}
                    loading="lazy"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center font-mono text-[10px] text-text-muted">
                    no preview
                  </div>
                )}
              </div>
              <span
                className={[
                  "font-mono text-[10px] uppercase tracking-wider",
                  isActive ? "text-accent" : "text-text-muted group-hover:text-text-secondary",
                ].join(" ")}
              >
                p {sheet.page_number}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
