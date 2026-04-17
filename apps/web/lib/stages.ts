/**
 * Stage metadata for the ingest pipeline.
 *
 * Maps the IngestStatus enum from atlas-core into:
 *   - a human-readable label,
 *   - an "active verb" for the live progress UI,
 *   - a one-paragraph technical explanation (shown on hover/expand
 *     so users can learn what each stage actually does).
 *
 * Order matches the lifecycle:
 *   queued → validating → rasterizing → tiling → completed | failed
 */

import type { IngestStatus } from "./api";

export interface StageDef {
  status: IngestStatus;
  label: string;
  active: string; // verb form for "currently doing X"
  short: string; // one-line "what" for the stepper
  detail: string; // one-paragraph technical depth
}

export const STAGES: ReadonlyArray<StageDef> = [
  {
    status: "queued",
    label: "Queued",
    active: "Queueing",
    short: "Waiting for a worker",
    detail:
      "Your PDF was uploaded to object storage and a job was placed on the ingest queue. A worker will pick it up within seconds.",
  },
  {
    status: "validating",
    label: "Validating",
    active: "Analyzing",
    short: "Reading the PDF structure",
    detail:
      "We confirm the file is a parseable PDF, isn't password-protected, and contains at least one page. Page dimensions are captured here so we can size the render correctly.",
  },
  {
    status: "rasterizing",
    label: "Rasterizing",
    active: "Rendering",
    short: "Vector → 300 DPI raster",
    detail:
      "Each page is rendered at 300 DPI using poppler. 300 DPI is the sweet spot for AEC sheets — high enough to keep linework sharp at maximum zoom without producing files we'd be ashamed of.",
  },
  {
    status: "tiling",
    label: "Tiling",
    active: "Generating tiles",
    short: "WebP pyramid for fluid zoom",
    detail:
      "We slice each rendered page into a tile pyramid (up to 7 zoom levels of 512×512 WebP tiles) so the viewer loads only what's on screen. This is the same approach Google Maps uses — the difference between instant pan/zoom and a multi-second wait per gesture.",
  },
  {
    status: "completed",
    label: "Ready",
    active: "Finalizing",
    short: "All artifacts in place",
    detail:
      "Every tile is uploaded, every sheet has a preview, and the database knows about it. The viewer is ready.",
  },
];

export const STAGE_INDEX: Record<IngestStatus, number> = {
  queued: 0,
  validating: 1,
  rasterizing: 2,
  tiling: 3,
  completed: 4,
  failed: -1,
};

export function stageDef(status: IngestStatus): StageDef {
  if (status === "failed") {
    return {
      status: "failed",
      label: "Failed",
      active: "Failed",
      short: "Pipeline halted",
      detail:
        "The pipeline encountered an error it couldn't recover from. The error message above explains what happened.",
    };
  }
  return STAGES[STAGE_INDEX[status]] ?? STAGES[0];
}
