"use client";

// TODO(v2): this control is drawing-centric — it lives on the drawing
// page and treats projects as an afterthought grouping. V2.0 inverts
// that: the project (one user undertaking) is the primary container;
// drawings are one possible input to a project. When the v2
// conversational front door lands this control is likely replaced by
// an "attach existing drawing to a project" step inside the project's
// own UI. Preserved for now because drawings/[id]/page.tsx imports it
// and ripping it out would force a simultaneous rework of the drawing
// page.

import { useEffect, useState } from "react";

import {
  ApiClientError,
  type ProjectSummary,
  assignDrawingToProject,
  listProjects,
} from "@/lib/api";


/**
 * Small inline control for setting the project on a drawing.
 *
 * Collapsed: chip showing the current project name (or "No project"),
 * click to expand.
 *
 * Expanded: list of the caller's projects — click one to assign,
 * or "Remove from project" to unassign. Projects are fetched lazily
 * on first expand so the drawing page doesn't block on it.
 */
export function AssignProjectControl({
  drawingId,
  initialProjectId,
  initialProjectName,
}: {
  drawingId: string;
  initialProjectId: string | null;
  initialProjectName: string | null;
}) {
  const [projectId, setProjectId] = useState(initialProjectId);
  const [projectName, setProjectName] = useState(initialProjectName);
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | "__unassign__" | null>(null);

  useEffect(() => {
    if (!open || projects !== null || loading) return;
    const ctl = new AbortController();
    setLoading(true);
    listProjects(ctl.signal)
      .then((r) => setProjects(r.projects))
      .catch((e) => {
        if (ctl.signal.aborted) return;
        setError(e instanceof ApiClientError ? e.message : "Could not load projects.");
      })
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, [open, projects, loading]);

  async function assign(next: ProjectSummary | null) {
    setError(null);
    setPendingId(next?.id ?? "__unassign__");
    try {
      await assignDrawingToProject(drawingId, next?.id ?? null);
      setProjectId(next?.id ?? null);
      setProjectName(next?.name ?? null);
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : "Could not assign.");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="relative inline-block text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded border border-border-subtle bg-bg-surface hover:bg-bg-elevated text-text-secondary px-1.5 py-0.5"
      >
        <span className="text-text-muted">project:</span>
        <span className="text-text-primary">
          {projectName ?? "none"}
        </span>
        <span className="text-text-muted" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open ? (
        <div className="absolute z-20 mt-1 w-64 rounded border border-border-subtle bg-bg-base shadow-lg p-1">
          {loading ? (
            <div className="text-text-muted px-1 py-1">Loading…</div>
          ) : error ? (
            <div className="text-red-400 px-1 py-1">{error}</div>
          ) : projects === null || projects.length === 0 ? (
            <div className="text-text-muted px-1 py-1">
              No projects yet.{" "}
              <a href="/projects" className="text-accent hover:underline">
                Create one
              </a>
              .
            </div>
          ) : (
            <ul className="max-h-56 overflow-y-auto">
              {projects.map((p) => {
                const selected = p.id === projectId;
                const pending = pendingId === p.id;
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => !selected && assign(p)}
                      className={`w-full text-left rounded px-1 py-0.5 transition-colors ${
                        selected
                          ? "bg-bg-elevated text-text-primary"
                          : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary"
                      }`}
                    >
                      {selected ? "✓ " : ""}
                      {p.name}
                      {pending ? " …" : ""}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          {projectId ? (
            <button
              type="button"
              disabled={pendingId === "__unassign__"}
              onClick={() => assign(null)}
              className="w-full text-left rounded mt-1 px-1 py-0.5 text-text-muted hover:bg-bg-elevated hover:text-red-400 border-t border-border-subtle"
            >
              {pendingId === "__unassign__" ? "Removing…" : "Remove from project"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
