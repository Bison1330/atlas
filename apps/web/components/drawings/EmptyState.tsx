import Link from "next/link";


/**
 * Shown when the user has no drawings they can read — neither owned
 * nor shared. First-run experience.
 */
export function EmptyState() {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface text-center py-6 px-3">
      <h2 className="text-xl font-semibold text-text-primary">
        You haven&apos;t uploaded any drawings yet.
      </h2>
      <p className="text-sm text-text-secondary mt-1">
        Upload a PDF plan set to get started. Once ingest finishes, you can
        upload a DXF for structured element extraction.
      </p>
      <Link
        href="/upload"
        className="inline-flex items-center gap-1 mt-3 rounded bg-accent hover:bg-accent-dim text-white font-medium px-2 py-1 text-sm transition-colors"
      >
        Upload your first drawing
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M5 12h14M13 6l6 6-6 6"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </Link>
      <p className="text-xs text-text-muted mt-2">
        Supported formats: PDF. DXF extraction is a step after upload.
      </p>
    </div>
  );
}
