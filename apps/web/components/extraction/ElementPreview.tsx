"use client";

import { useMemo } from "react";
import { ElementDetail } from "@/lib/api";
import { styleFor } from "./elementColors";

interface Props {
  elements: ElementDetail[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Source filename from the ElementSource.params, for the caption. */
  sourceFilename?: string;
}

/**
 * SVG canvas of extracted elements in their *own* DXF coordinate
 * system.
 *
 * **Honest framing.** This is intentionally NOT overlaid on the
 * tile viewer. The DXF lives in DXF units; the viewer renders the
 * rasterized PDF in pixel units; we don't have a registration
 * between the two. Rendering them together would imply alignment
 * we haven't computed. The caption above the canvas spells this
 * out. A future phase can add registration when we have a real
 * story for it (DXF-only sheets where geometry is the source, or
 * a 2-3 anchor-point UI to compute the affine).
 *
 * The canvas auto-fits to the elements' aggregate bounding box
 * with a small margin, flipping Y to match standard CAD
 * conventions (Y-up in the DXF, Y-down in SVG).
 */
export function ElementPreview({
  elements,
  selectedId,
  onSelect,
  sourceFilename,
}: Props) {
  const projection = useMemo(() => computeProjection(elements), [elements]);

  if (!projection) {
    return (
      <div className="rounded-lg border border-dashed border-border-subtle bg-bg-surface/40 p-8 text-center">
        <p className="text-sm text-text-muted">
          No geometry to render — all elements are non-spatial (annotations,
          dimensions, etc.).
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface">
      <div className="flex items-baseline justify-between border-b border-border-subtle px-3 py-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
            Preview
          </p>
          <p className="text-sm font-medium text-text-primary">
            Extracted geometry
          </p>
        </div>
        <p className="font-mono text-[10px] text-text-muted">
          {sourceFilename ? `${sourceFilename} · ` : ""}independent coordinate system
        </p>
      </div>

      <div className="relative bg-black/40 p-2">
        <svg
          viewBox={`0 0 ${projection.width} ${projection.height}`}
          className="block h-[420px] w-full"
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label="Extracted element preview"
        >
          {/* Faint grid for orientation. */}
          <defs>
            <pattern
              id="atlas-grid"
              width="40"
              height="40"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 40 0 L 0 0 0 40"
                fill="none"
                stroke="rgba(255,255,255,0.05)"
                strokeWidth="1"
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#atlas-grid)" />

          {elements.map((el) => (
            <ElementShape
              key={el.id}
              element={el}
              project={projection.project}
              selected={selectedId === el.id}
              onSelect={() => onSelect(el.id)}
            />
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-border-subtle px-3 py-2">
        <Legend />
      </div>
    </div>
  );
}

interface Projection {
  width: number;
  height: number;
  project: (x: number, y: number) => { x: number; y: number };
}

function computeProjection(elements: ElementDetail[]): Projection | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  let any = false;
  for (const el of elements) {
    for (const [x, y] of pointsOf(el)) {
      any = true;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  if (!any) return null;
  if (maxX === minX) maxX = minX + 1;
  if (maxY === minY) maxY = minY + 1;

  const PADDING = 0.05;
  const dx = (maxX - minX) * PADDING;
  const dy = (maxY - minY) * PADDING;
  minX -= dx; maxX += dx; minY -= dy; maxY += dy;

  // Project to a fixed SVG width so viewBox is stable; height follows aspect.
  const svgW = 1000;
  const scale = svgW / (maxX - minX);
  const svgH = (maxY - minY) * scale;

  // Y is flipped: DXF +Y is up, SVG +y is down.
  const project = (x: number, y: number) => ({
    x: (x - minX) * scale,
    y: svgH - (y - minY) * scale,
  });

  return { width: svgW, height: svgH, project };
}

function* pointsOf(el: ElementDetail): Iterable<[number, number]> {
  const g = el.geometry as Record<string, unknown> | undefined;
  if (!g) return;
  const kind = g.kind as string;

  if (kind === "polyline") {
    for (const p of (g.points as { x: number; y: number }[]) ?? []) {
      yield [p.x, p.y];
    }
  } else if (kind === "polygon") {
    for (const p of (g.ring as { x: number; y: number }[]) ?? []) {
      yield [p.x, p.y];
    }
  } else if (kind === "arc" || kind === "circle") {
    const c = g.center as { x: number; y: number } | undefined;
    const r = (g.radius as number) ?? 0;
    if (c) {
      yield [c.x - r, c.y - r];
      yield [c.x + r, c.y + r];
    }
  }
}

function ElementShape({
  element,
  project,
  selected,
  onSelect,
}: {
  element: ElementDetail;
  project: (x: number, y: number) => { x: number; y: number };
  selected: boolean;
  onSelect: () => void;
}) {
  const sty = styleFor(element.kind);
  const baseStrokeWidth = selected ? 2.5 : 1.25;
  const opacity = selected ? 1 : 0.9;

  const g = element.geometry as Record<string, unknown> | undefined;
  if (!g) return null;
  const kind = g.kind as string;

  const commonProps = {
    onClick: onSelect,
    style: { cursor: "pointer", opacity },
  };

  if (kind === "polyline") {
    const pts = ((g.points as { x: number; y: number }[]) ?? []).map((p) => project(p.x, p.y));
    if (pts.length < 2) return null;
    const d = `M ${pts.map((p) => `${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" L ")}`;
    return (
      <path
        d={d}
        fill="none"
        stroke={sty.stroke}
        strokeWidth={baseStrokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        {...commonProps}
      />
    );
  }

  if (kind === "polygon") {
    const pts = ((g.ring as { x: number; y: number }[]) ?? []).map((p) => project(p.x, p.y));
    if (pts.length < 3) return null;
    const d = `M ${pts.map((p) => `${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" L ")} Z`;
    return (
      <path
        d={d}
        fill={sty.fill}
        stroke={sty.stroke}
        strokeWidth={baseStrokeWidth}
        strokeLinejoin="round"
        {...commonProps}
      />
    );
  }

  if (kind === "arc") {
    const c = g.center as { x: number; y: number };
    const r = g.radius as number;
    const a0 = ((g.start_angle_deg as number) ?? 0) * (Math.PI / 180);
    const a1 = ((g.end_angle_deg as number) ?? 0) * (Math.PI / 180);
    const p0 = project(c.x + r * Math.cos(a0), c.y + r * Math.sin(a0));
    const p1 = project(c.x + r * Math.cos(a1), c.y + r * Math.sin(a1));
    const center = project(c.x, c.y);
    // SVG ellipse-arc rx/ry: scale is uniform, so use distance from center.
    const rx = Math.hypot(p0.x - center.x, p0.y - center.y);
    const sweep = ((a1 - a0 + 2 * Math.PI) % (2 * Math.PI));
    const largeArc = sweep > Math.PI ? 1 : 0;
    // Y is flipped, so the "sweep" flag flips too.
    const sweepFlag = 0;
    const d = `M ${center.x.toFixed(2)} ${center.y.toFixed(2)} L ${p0.x.toFixed(2)} ${p0.y.toFixed(2)} A ${rx} ${rx} 0 ${largeArc} ${sweepFlag} ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} Z`;
    return (
      <path
        d={d}
        fill={sty.fill}
        stroke={sty.stroke}
        strokeWidth={baseStrokeWidth}
        {...commonProps}
      />
    );
  }

  if (kind === "circle") {
    const c = g.center as { x: number; y: number };
    const r = g.radius as number;
    const center = project(c.x, c.y);
    const edge = project(c.x + r, c.y);
    const rx = Math.abs(edge.x - center.x);
    return (
      <circle
        cx={center.x}
        cy={center.y}
        r={rx}
        fill={sty.fill}
        stroke={sty.stroke}
        strokeWidth={baseStrokeWidth}
        {...commonProps}
      />
    );
  }

  return null;
}

function Legend() {
  const kinds = ["wall", "door", "room", "window", "column"];
  return (
    <ul className="flex flex-wrap items-center gap-2 text-[11px]">
      {kinds.map((k) => {
        const sty = styleFor(k);
        return (
          <li key={k} className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: sty.stroke }}
            />
            <span className="text-text-secondary">{sty.label}</span>
          </li>
        );
      })}
    </ul>
  );
}
