// TODO(v2): this row shows only name + description + age, which
// reads more like a folder than a project. V2.0 project cards need:
//   - Project type badge (kitchen remodel / coffee-shop fit-out / …)
//   - Lifecycle state (designing / priced / quoted / permitted)
//   - Thumbnail (stylized 3D render or AI photoreal image)
//   - Cost estimate chip once pricing runs
// Rewrite as a card, not a dense row, once the v2 list page is built.
import type { ProjectSummary } from "@/lib/api";


function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - then);
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}


/**
 * One row in the projects list. Matches the dense-list layout of
 * DrawingRow so the two indexes feel like siblings. No link yet —
 * the project detail page is a follow-up slice; this v1 just shows
 * the project name + optional description + age.
 */
export function ProjectRow({ project }: { project: ProjectSummary }) {
  return (
    <div className="block rounded border border-border-subtle bg-bg-surface px-2 py-1.5 mb-1">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm text-text-primary font-medium truncate">
            {project.name}
          </div>
          {project.description ? (
            <div className="text-xs text-text-secondary mt-0.5 truncate">
              {project.description}
            </div>
          ) : null}
        </div>
        <div className="text-xs text-text-muted shrink-0">
          {formatRelative(project.updated_at)}
        </div>
      </div>
    </div>
  );
}
