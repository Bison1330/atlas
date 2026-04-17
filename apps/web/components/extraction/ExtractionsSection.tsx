"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ElementDetail,
  ExtractionRunSummary,
  getElements,
  getExtractions,
} from "@/lib/api";
import { DxfDropZone } from "./DxfDropZone";
import { ElementInspector } from "./ElementInspector";
import { ElementList } from "./ElementList";
import { ElementPreview } from "./ElementPreview";
import { ExtractionProgress } from "./ExtractionProgress";

interface Props {
  drawingId: string;
}

type Mode =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "active"; run: ExtractionRunSummary }
  | { kind: "done"; run: ExtractionRunSummary; elements: ElementDetail[] }
  | { kind: "failed"; run: ExtractionRunSummary }
  | { kind: "error"; message: string };

/**
 * Top-level extraction surface that lives below the M1 viewer.
 *
 * State machine:
 *
 *     loading                           ← initial fetch
 *     ↓
 *     empty            (no runs)        ← shows DxfDropZone CTA
 *     ↓ [user uploads DXF]
 *     active           (queued/running) ← shows ExtractionProgress
 *     ↓ [terminal event]
 *     done             (completed)      ← shows list + inspector + preview
 *     OR failed                         ← shows error + retry
 *
 * The "extract again" affordance from the done state goes back to
 * empty so the dropzone re-appears (the new run becomes the latest).
 */
export function ExtractionsSection({ drawingId }: Props) {
  const [mode, setMode] = useState<Mode>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { extractions } = await getExtractions(drawingId);
      const latest = extractions[0];
      if (!latest) {
        setMode({ kind: "empty" });
        return;
      }
      if (latest.status === "completed") {
        const { elements } = await getElements(drawingId, {
          source_id: latest.id,
          include: ["geometry"],
        });
        setMode({
          kind: "done",
          run: latest,
          elements: elements as ElementDetail[],
        });
      } else if (latest.status === "failed") {
        setMode({ kind: "failed", run: latest });
      } else {
        setMode({ kind: "active", run: latest });
      }
    } catch (err) {
      setMode({ kind: "error", message: (err as Error).message });
    }
  }, [drawingId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onUploaded = useCallback((run: ExtractionRunSummary) => {
    setMode({ kind: "active", run });
    setSelectedId(null);
  }, []);

  const onCompleted = useCallback(async () => {
    await refresh();
  }, [refresh]);

  const onFailed = useCallback(async () => {
    await refresh();
  }, [refresh]);

  return (
    <section className="mt-6">
      <header className="mb-3 flex items-baseline justify-between">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted">
            Step 2 — extract
          </p>
          <h2 className="text-2xl font-medium tracking-tight text-text-primary">
            Element extraction
          </h2>
        </div>
        {mode.kind === "done" && (
          <button
            type="button"
            onClick={() => setMode({ kind: "empty" })}
            className="rounded-md border border-border-subtle px-2 py-1 text-xs text-text-secondary hover:border-text-muted hover:text-text-primary"
          >
            Run again
          </button>
        )}
      </header>

      {renderBody(mode, drawingId, onUploaded, onCompleted, onFailed, selectedId, setSelectedId)}
    </section>
  );
}

function renderBody(
  mode: Mode,
  drawingId: string,
  onUploaded: (run: ExtractionRunSummary) => void,
  onCompleted: () => void,
  onFailed: () => void,
  selectedId: string | null,
  setSelectedId: (id: string) => void,
) {
  if (mode.kind === "loading") {
    return (
      <div className="space-y-2">
        <div className="h-16 animate-pulse rounded-lg bg-bg-surface" />
        <div className="h-32 animate-pulse rounded-lg bg-bg-surface" />
      </div>
    );
  }

  if (mode.kind === "error") {
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
        <p className="text-sm text-text-primary">
          Couldn&apos;t load extractions: {mode.message}
        </p>
      </div>
    );
  }

  if (mode.kind === "empty") {
    return (
      <div className="rounded-lg border border-border-subtle bg-bg-surface/40 p-4">
        <p className="mb-2 text-sm text-text-secondary">
          Upload a DXF and Atlas will classify entities by their NCS layer
          (e.g.{" "}
          <span className="font-mono text-accent">A-WALL-EXTR</span> →
          exterior wall) and persist them as IFC-shaped elements with
          confidence scores.
        </p>
        <DxfDropZone drawingId={drawingId} onQueued={onUploaded} />
      </div>
    );
  }

  if (mode.kind === "active") {
    return (
      <ExtractionProgress
        drawingId={drawingId}
        run={mode.run}
        onCompleted={onCompleted}
        onFailed={onFailed}
      />
    );
  }

  if (mode.kind === "failed") {
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-4">
        <p className="font-mono text-[11px] uppercase tracking-wider text-rose-300">
          {mode.run.error_code ?? "extraction_failed"}
        </p>
        <p className="mt-1 text-sm text-text-primary">
          {mode.run.error_message ?? "Extraction failed."}
        </p>
        <p className="mt-2 text-xs text-text-muted">
          Try uploading a different DXF, or check that the file follows
          NCS layer conventions.
        </p>
      </div>
    );
  }

  // mode.kind === "done"
  const selected = mode.elements.find((e) => e.id === selectedId) ?? null;
  return (
    <div className="space-y-3">
      <ExtractionMetaBar run={mode.run} elementCount={mode.elements.length} />
      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div className="space-y-3">
          <ElementPreview
            elements={mode.elements}
            selectedId={selectedId}
            onSelect={setSelectedId}
            sourceFilename={(mode.run.params?.dxf_filename as string) ?? undefined}
          />
          <div className="h-[300px]">
            <ElementList
              elements={mode.elements}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
        </div>
        <div className="h-[620px]">
          <ElementInspector element={selected} />
        </div>
      </div>
    </div>
  );
}

function ExtractionMetaBar({
  run,
  elementCount,
}: {
  run: ExtractionRunSummary;
  elementCount: number;
}) {
  const filename = (run.params?.dxf_filename as string) ?? "—";
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-lg border border-border-subtle bg-bg-surface px-3 py-2">
      <p className="text-sm text-text-secondary">
        <span className="font-medium text-text-primary">
          {elementCount} element{elementCount === 1 ? "" : "s"}
        </span>{" "}
        extracted from <span className="font-mono">{filename}</span>
      </p>
      <p className="font-mono text-[11px] text-text-muted">
        {run.producer_name}@{run.producer_version}
      </p>
    </div>
  );
}
