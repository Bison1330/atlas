"use client";

import { use, useCallback, useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ExtractionsSection } from "@/components/extraction/ExtractionsSection";
import { ProgressView } from "@/components/progress/ProgressView";
import { AssignProjectControl } from "@/components/projects/AssignProjectControl";
import { ViewerView } from "@/components/viewer/ViewerView";
import { ApiClientError, DrawingStatus, DrawingSummary, getDrawing, getDrawingStatus } from "@/lib/api";

export default function DrawingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [snapshot, setSnapshot] = useState<DrawingStatus | null>(null);
  const [summary, setSummary] = useState<DrawingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);

  // Initial fetch — decides whether to render progress or viewer first.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await getDrawingStatus(id);
        if (cancelled) return;
        setSnapshot(status);
        if (status.status === "completed") {
          const full = await getDrawing(id);
          if (!cancelled) setSummary(full);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiClientError && err.status === 404) {
          setError("That drawing doesn't exist (or it expired).");
        } else {
          setError((err as Error).message);
        }
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const onCompleted = useCallback((full: DrawingSummary) => {
    setSummary(full);
  }, []);

  // With a complete drawing, split the viewport: scrollable main
  // (viewer + extractions) on the left, Q&A chat panel on the right.
  // During ingest / on errors we stick with the centered single-column
  // layout.
  const ready = !error && bootstrapped && summary;

  // Breadcrumb prefers the filename; the raw UUID slice reads as debug
  // text to a non-dev visitor (flagged in the external review). Fall
  // back to "Drawing <shortid>" pre-bootstrap so the crumb is never
  // empty and never a bare UUID.
  const trailLabel = summary?.source_filename ?? `Drawing ${id.slice(0, 8)}`;

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader trail={`drawings / ${trailLabel}`} />

      {ready ? (
        <div className="flex-1 flex min-h-0">
          <main className="flex-1 overflow-y-auto px-3 py-6 min-w-0">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-sm text-text-secondary truncate min-w-0">
                {summary.project_name ?? summary.source_filename}
              </div>
              <AssignProjectControl
                drawingId={id}
                initialProjectId={null}
                initialProjectName={summary.project_name}
              />
            </div>
            <ViewerView drawing={summary} />
            <ExtractionsSection drawingId={id} />
          </main>
          <ChatPanel drawingId={id} />
        </div>
      ) : (
        <main className="mx-auto max-w-[1200px] px-3 py-6 w-full">
          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
              <p className="text-sm text-text-primary">{error}</p>
            </div>
          )}

          {!error && !bootstrapped && (
            <div className="space-y-3">
              <div className="h-7 w-1/3 animate-pulse rounded bg-bg-surface" />
              <div className="h-32 animate-pulse rounded-xl bg-bg-surface" />
              <div className="h-48 animate-pulse rounded-xl bg-bg-surface" />
            </div>
          )}

          {!error && bootstrapped && !summary && (
            <ProgressView
              drawingId={id}
              initialSnapshot={snapshot}
              onCompleted={onCompleted}
            />
          )}
        </main>
      )}
    </div>
  );
}
