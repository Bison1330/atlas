"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, uploadDrawing } from "@/lib/api";
import { formatBytes } from "@/lib/format";

const MAX_BYTES = 500 * 1024 * 1024; // 500MB cap, matches API config default
const ACCEPTED_TYPES = ["application/pdf"];

type Phase =
  | { kind: "idle" }
  | { kind: "ready"; file: File }
  | { kind: "uploading"; file: File; loaded: number; total: number }
  | { kind: "error"; message: string };

interface Props {
  projectName?: string;
  onUploaded: (drawingId: string) => void;
}

export function DropZone({ projectName, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [dragActive, setDragActive] = useState(false);

  // Suppress browser default for drops anywhere on the page so a stray
  // drop doesn't navigate away from the upload screen mid-DnD.
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
    const looksLikePdf = ACCEPTED_TYPES.includes(file.type) || file.name.toLowerCase().endsWith(".pdf");
    if (!looksLikePdf) return "Atlas accepts PDFs in this milestone.";
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
      const drawing = await uploadDrawing(file, {
        projectName,
        onProgress: (loaded, total) =>
          setPhase({ kind: "uploading", file, loaded, total }),
      });
      onUploaded(drawing.id);
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? `${err.message} (${err.code})`
          : (err as Error).message;
      setPhase({ kind: "error", message: msg });
    }
  }, [phase, projectName, onUploaded]);

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
        htmlFor="atlas-file-input"
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
          "group block cursor-pointer rounded-xl border-2 border-dashed p-6 transition-all duration-150",
          dragActive
            ? "border-accent bg-accent/[0.04] shadow-glow"
            : "border-border-subtle bg-bg-surface hover:border-text-muted hover:bg-bg-elevated",
          isBusy ? "pointer-events-none opacity-90" : "",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          id="atlas-file-input"
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          onChange={handlePick}
          disabled={isBusy}
        />

        <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
          <UploadIcon active={dragActive} />

          {phase.kind === "idle" && (
            <>
              <p className="text-lg font-medium text-text-primary">
                Drop a PDF, or <span className="text-accent">click to browse</span>
              </p>
              <p className="text-sm text-text-muted">
                Up to {formatBytes(MAX_BYTES)} · single file
              </p>
            </>
          )}

          {phase.kind === "ready" && (
            <>
              <p className="font-mono text-sm text-text-secondary">{phase.file.name}</p>
              <p className="text-xs text-text-muted">
                {formatBytes(phase.file.size)} · ready to ingest
              </p>
            </>
          )}

          {phase.kind === "uploading" && (
            <>
              <p className="font-mono text-sm text-text-secondary">{phase.file.name}</p>
              <p className="text-xs text-text-muted">
                {formatBytes(phase.loaded)} / {formatBytes(phase.total)} ·{" "}
                {Math.round((phase.loaded / Math.max(1, phase.total)) * 100)}%
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

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-text-muted">
          Files are uploaded to Atlas object storage and processed asynchronously.
          You&apos;ll see live progress on the next screen.
        </p>
        <div className="flex items-center gap-2">
          {phase.kind === "ready" && (
            <>
              <button
                type="button"
                className="rounded-md border border-border-subtle px-3 py-1.5 text-sm text-text-secondary hover:border-text-muted hover:text-text-primary"
                onClick={reset}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={upload}
                className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg-base transition-colors hover:bg-accent-dim"
              >
                Start ingest
                <Arrow />
              </button>
            </>
          )}
          {phase.kind === "uploading" && (
            <span className="font-mono text-xs text-text-muted">Uploading…</span>
          )}
          {phase.kind === "error" && (
            <button
              type="button"
              onClick={reset}
              className="rounded-md border border-border-subtle px-3 py-1.5 text-sm text-text-secondary hover:border-text-muted hover:text-text-primary"
            >
              Reset
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function UploadIcon({ active }: { active: boolean }) {
  return (
    <div
      className={[
        "flex h-12 w-12 items-center justify-center rounded-full border transition-all duration-150",
        active
          ? "border-accent bg-accent/[0.08] text-accent"
          : "border-border-subtle bg-bg-elevated text-text-muted group-hover:text-text-secondary",
      ].join(" ")}
      aria-hidden
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path
          d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

function Arrow() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M5 12h14M13 6l6 6-6 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
