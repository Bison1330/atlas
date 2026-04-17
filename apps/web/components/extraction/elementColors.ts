/** Per-kind color tokens used by the element list, inspector, and preview. */

export interface KindStyle {
  label: string;
  /** CSS color for stroke / borders. */
  stroke: string;
  /** CSS color for fills (semi-transparent). */
  fill: string;
  /** Tailwind text class for inline labels. */
  textClass: string;
  /** Display order (smaller = first). */
  order: number;
}

export const KIND_STYLES: Record<string, KindStyle> = {
  wall: {
    label: "Walls",
    stroke: "#3B82F6",
    fill: "rgba(59, 130, 246, 0.10)",
    textClass: "text-accent",
    order: 1,
  },
  door: {
    label: "Doors",
    stroke: "#F59E0B",
    fill: "rgba(245, 158, 11, 0.18)",
    textClass: "text-amber-300",
    order: 2,
  },
  window: {
    label: "Windows",
    stroke: "#22D3EE",
    fill: "rgba(34, 211, 238, 0.18)",
    textClass: "text-cyan-300",
    order: 3,
  },
  room: {
    label: "Rooms",
    stroke: "#10B981",
    fill: "rgba(16, 185, 129, 0.10)",
    textClass: "text-emerald-300",
    order: 4,
  },
  column: {
    label: "Columns",
    stroke: "#A78BFA",
    fill: "rgba(167, 139, 250, 0.20)",
    textClass: "text-violet-300",
    order: 5,
  },
  stair: {
    label: "Stairs",
    stroke: "#FB7185",
    fill: "rgba(251, 113, 133, 0.18)",
    textClass: "text-rose-300",
    order: 6,
  },
  dimension: {
    label: "Dimensions",
    stroke: "#94A3B8",
    fill: "rgba(148, 163, 184, 0.10)",
    textClass: "text-slate-300",
    order: 7,
  },
  annotation: {
    label: "Annotations",
    stroke: "#94A3B8",
    fill: "rgba(148, 163, 184, 0.10)",
    textClass: "text-slate-300",
    order: 8,
  },
  symbol: {
    label: "Symbols",
    stroke: "#94A3B8",
    fill: "rgba(148, 163, 184, 0.10)",
    textClass: "text-slate-300",
    order: 9,
  },
  other: {
    label: "Other",
    stroke: "#64748B",
    fill: "rgba(100, 116, 139, 0.08)",
    textClass: "text-text-muted",
    order: 10,
  },
};

export function styleFor(kind: string): KindStyle {
  return KIND_STYLES[kind] ?? KIND_STYLES.other;
}
