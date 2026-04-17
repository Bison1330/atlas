import type { IngestStatus } from "@/lib/api";

/**
 * Small colored dot + label matching the lifecycle stage.
 *
 * ``completed`` is blue (accent), ``failed`` red, everything in
 * between yellow (in-progress). Keeps the row scannable without
 * reading the text — which is what most users do.
 */

const STATUS_LABELS: Record<IngestStatus, string> = {
  queued: "Queued",
  validating: "Validating",
  rasterizing: "Rasterizing",
  tiling: "Tiling",
  completed: "Ready",
  failed: "Failed",
};


export function StatusDot({
  status,
  progress,
}: {
  status: IngestStatus;
  progress: number;
}) {
  const color =
    status === "completed" ? "bg-accent"
    : status === "failed" ? "bg-red-400"
    : "bg-yellow-400 animate-pulse";

  const label = STATUS_LABELS[status];
  const suffix =
    status !== "completed" && status !== "failed"
      ? ` · ${progress}%`
      : "";

  return (
    <span className="inline-flex items-center gap-0.5 text-xs text-text-secondary">
      <span className={`h-1 w-1 rounded-full ${color}`} aria-hidden />
      {label}{suffix}
    </span>
  );
}
