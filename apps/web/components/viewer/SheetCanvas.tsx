"use client";

import { useEffect, useRef, useState } from "react";
import { SheetSummary, sheetHas2DTiles, tileUrl } from "@/lib/api";

interface Props {
  drawingId: string;
  sheet: SheetSummary;
  /** Called when the empty-state CTA is clicked to jump to 3D. */
  onSwitchToMode3D?: () => void;
}

/**
 * OpenSeadragon-backed deep-zoom viewer for a single rendered sheet.
 *
 * Tiles live in S3 at a deterministic path; we hand OpenSeadragon a
 * minimal custom TileSource so it can request only the tiles inside
 * the current viewport at the appropriate zoom level. That's the
 * mechanism that makes pan/zoom feel instant for sheets the size of
 * a small mural.
 *
 * The library is imported dynamically so it never enters the SSR
 * bundle (it touches `window` and `document` at module load).
 *
 * DXF-sourced drawings skip the rasterize/tile pipeline entirely and
 * have no 2D tile metadata. We detect that up front with
 * :func:`sheetHas2DTiles` and render a friendly empty state with a
 * "Switch to 3D" CTA instead of booting OpenSeadragon (which would
 * surface a red programmer-facing error — the first thing external
 * reviewers saw on demo drawings).
 */
export function SheetCanvas({ drawingId, sheet, onSwitchToMode3D }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const hasTiles = sheetHas2DTiles(sheet);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!hasTiles) {
      // Don't try to construct a TileSource for a DXF-sourced sheet;
      // the empty-state UI below handles this path.
      return;
    }

    let viewer: { destroy: () => void } | null = null;
    let cancelled = false;

    (async () => {
      const { default: OpenSeadragon } = await import("openseadragon");
      if (cancelled || !containerRef.current) return;

      const fullW = sheet.width_px!;
      const fullH = sheet.height_px!;
      const tileSize = sheet.tile_size!;
      const maxZoom = sheet.max_zoom!;

      const tileSource = {
        // Custom OpenSeadragon TileSource — just the methods OSD needs.
        width: fullW,
        height: fullH,
        tileSize,
        tileOverlap: 0,
        minLevel: 0,
        maxLevel: maxZoom,
        // OSD asks for level dimensions when computing tile grids.
        getLevelScale(level: number) {
          return Math.pow(0.5, maxZoom - level);
        },
        getNumTiles(level: number): { x: number; y: number } {
          const scale = Math.pow(0.5, maxZoom - level);
          const w = Math.max(1, Math.ceil(fullW * scale));
          const h = Math.max(1, Math.ceil(fullH * scale));
          return {
            x: Math.max(1, Math.ceil(w / tileSize)),
            y: Math.max(1, Math.ceil(h / tileSize)),
          };
        },
        getTileUrl(level: number, x: number, y: number): string {
          return tileUrl(drawingId, sheet.id, level, x, y);
        },
      } as unknown as Parameters<typeof OpenSeadragon>[0]["tileSources"];

      const instance = OpenSeadragon({
        element: containerRef.current,
        tileSources: tileSource,
        prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@5/build/openseadragon/images/",
        showNavigationControl: true,
        showNavigator: true,
        navigatorPosition: "BOTTOM_RIGHT",
        navigatorAutoFade: true,
        gestureSettingsMouse: { clickToZoom: false, scrollToZoom: true },
        gestureSettingsTouch: { pinchToZoom: true, scrollToZoom: false },
        animationTime: 0.6,
        springStiffness: 7,
        immediateRender: false,
        preserveImageSizeOnResize: true,
        visibilityRatio: 1,
        constrainDuringPan: true,
        minZoomImageRatio: 0.9,
        maxZoomPixelRatio: 2,
      });
      instance.addHandler("open", () => setReady(true));
      instance.addHandler("open-failed", () =>
        setError("OpenSeadragon failed to load the tile source."),
      );
      viewer = instance as unknown as { destroy: () => void };
    })().catch((err) => {
      if (!cancelled) setError(`Viewer init failed: ${(err as Error).message}`);
    });

    return () => {
      cancelled = true;
      if (viewer) viewer.destroy();
    };
  }, [drawingId, sheet, hasTiles]);

  // Friendly empty state for DXF-sourced drawings without 2D tiles.
  // Explicitly *not* the red error treatment — this is expected state,
  // not a bug, and pushing the user straight to 3D is the actionable
  // move.
  if (!hasTiles) {
    return (
      <div className="relative flex h-full w-full items-center justify-center rounded-xl border border-border-subtle bg-bg-surface p-6 text-center">
        <div className="max-w-md space-y-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted">
            2D preview unavailable
          </p>
          <p className="text-sm text-text-secondary">
            This drawing was ingested from a DXF, so there are no
            rasterized 2D tiles. Switch to 3D to explore the extracted
            geometry.
          </p>
          {onSwitchToMode3D && (
            <button
              type="button"
              onClick={onSwitchToMode3D}
              className="rounded-md border border-border-subtle bg-bg-elevated px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:border-text-muted hover:bg-bg-surface"
            >
              Switch to 3D
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-border-subtle bg-black/40">
      <div ref={containerRef} className="h-full w-full" aria-label="Sheet viewer" />
      {!ready && !error && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-text-muted">
          <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-bg-surface px-3 py-1.5">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
            <span className="font-mono text-[11px] uppercase tracking-wider">
              loading tiles
            </span>
          </div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center p-3 text-center">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
            <p className="font-mono text-[11px] uppercase tracking-wider text-rose-300">
              viewer error
            </p>
            <p className="mt-1 text-sm text-text-secondary">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
