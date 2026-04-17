"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, ExtractionRunSummary, uploadDxf } from "@/lib/api";
import { formatBytes } from "@/lib/format";

const MAX_BYTES = 100 * 1024 * 1024; // matches API DXF cap
const ACCEPT = ".dxf,application/dxf,application/octet-stream";

type Phase =
  | { kind: "idle" }
  | { kind: "ready"; file: File }
  | { kind: "uploading"; file: File; loaded: number; total: number }
  | { kind: "error"; message: string };

interface Props {
  drawingId: string;
  onQueued: (run: ExtractionRunSummary) => void;
}

/**
 * Compact DXF drop zone.
 *
 * Variant of M1's PDF DropZone — same drag/drop ergonomics, same XHR
 * progress wiring — but tuned for the smaller, more frequent
 * extraction trigger surface. Lives inline on the drawing detail
 * page rather than on its own route.
 */
export function DxfDropZone({ drawingId, onQueued }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => {
      window.removeEventListener("dragover", stop);
      window.removeEventListener("drop", stop);
    };
  }, []);

  const validate = (file: File): string | null => {
    if (file.size === 0) return "That file is empty.";
    if (file.size > MAX_BYTES)
      return `File is ${formatBytes(file.size)}. Max is ${formatBytes(MAX_BYTES)}.`;
    if (!file.name.toLowerCase().endsWith(".dxf"))
      return "Atlas accepts .dxf files for element extraction.";
    return null;
  };

  const accept = useCallback((file: File) => {
    const err = validate(file);
    if (err) {
      setPhase({ kind: "error", message: err });
      return;
    }
    setPhase({ kind: "ready", file });
  }, []);

  const upload = useCallback(async () => {
    if (phase.kind !== "ready") return;
    const file = phase.file;
    setPhase({ kind: "uploading", file, loaded: 0, total: file.size });
    try {
      const run = await uploadDxf(drawingId, file, {
        onProgress: (loaded, total) =>
          setPhase({ kind: "uploading", file, loaded, total }),
      });
      onQueued(run);
      setPhase({ kind: "idle" });
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? `${err.message} (${err.code})`
          : (err as Error).message;
      setPhase({ kind: "error", message: msg });
    }
  }, [phase, drawingId, onQueued]);

  const reset = useCallback(() => setPhase({ kind: "idle" }), []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) accept(file);
  };

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) accept(file);
    e.target.value = "";
  };

  const isBusy = phase.kind === "uploading";

  return (
    <div className="w-full">
      <label
        htmlFor="atlas-dxf-input"
        onDragEnter={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={[
          "group block cursor-pointer rounded-lg border-2 border-dashed p-3 transition-all duration-150",
          dragActive
            ? "border-accent bg-accent/[0.06] shadow-glow"
            : "border-border-subtle bg-bg-surface/50 hover:border-text-muted hover:bg-bg-elevated",
          isBusy ? "pointer-events-none opacity-90" : "",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          id="atlas-dxf-input"
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={handlePick}
          disabled={isBusy}
        />

        <div className="flex items-center gap-3">
          <div
            className={[
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border transition-colors",
              dragActive
                ? "border-accent bg-accent/[0.08] text-accent"
                : "border-border-subtle bg-bg-elevated text-text-muted",
            ].join(" ")}
            aria-hidden
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>

          <div className="min-w-0 flex-1">
            {phase.kind === "idle" && (
              <>
                <p className="text-sm font-medium text-text-primary">
                  Drop a DXF, or <span className="text-accent">click to browse</span>
                </p>
                <p className="text-xs text-text-muted">
                  Up to {formatBytes(MAX_BYTES)} · classified by NCS layer
                </p>
              </>
            )}
            {phase.kind === "ready" && (
              <>
                <p className="truncate font-mono text-sm text-text-secondary">
                  {phase.file.name}
                </p>
                <p className="text-xs text-text-muted">
                  {formatBytes(phase.file.size)} · ready to extract
                </p>
              </>
            )}
            {phase.kind === "uploading" && (
              <>
                <p className="truncate font-mono text-sm text-text-secondary">
                  {phase.file.name}
                </p>
                <p className="text-xs text-text-muted">
                  Uploading · {Math.round((phase.loaded / Math.max(1, phase.total)) * 100)}%
                </p>
              </>
            )}
            {phase.kind === "error" && (
              <>
                <p className="text-sm font-medium text-rose-300">{phase.message}</p>
                <p className="text-xs text-text-muted">Click to try a different file.</p>
              </>
            )}
          </div>

          {phase.kind === "ready" && (
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  reset();
                }}
                className="rounded-md border border-border-subtle px-2 py-1 text-xs text-text-secondary hover:border-text-muted hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  upload();
                }}
                className="rounded-md bg-accent px-2 py-1 text-xs font-medium text-bg-base hover:bg-accent-dim"
              >
                Extract
              </button>
            </div>
          )}
          {phase.kind === "error" && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                reset();
              }}
              className="rounded-md border border-border-subtle px-2 py-1 text-xs text-text-secondary hover:border-text-muted hover:text-text-primary"
            >
              Reset
            </button>
          )}
        </div>

        {phase.kind === "uploading" && (
          <div
            className="mt-2 h-1 overflow-hidden rounded-full bg-bg-elevated"
            role="progressbar"
            aria-valuenow={phase.loaded}
            aria-valuemax={phase.total}
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-150 ease-out"
              style={{
                width: `${Math.min(100, Math.round((phase.loaded / Math.max(1, phase.total)) * 100))}%`,
              }}
            />
          </div>
        )}
      </label>
    </div>
  );
}
