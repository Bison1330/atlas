import type { AskCitation } from "@/lib/api";


/**
 * Metadata chip for one cited element.
 *
 * Inert in v1 (D-20-A): shows kind + NCS layer + display label
 * on hover. Clicking does nothing. A follow-up
 * ``web/m2-viewer-focus`` slice will add a viewport imperative
 * handle on SheetCanvas so clicks jump to the element's bbox.
 */
export function CitationChip({ citation }: { citation: AskCitation }) {
  const subtitle = citation.ncs_layer ?? citation.kind;
  const bboxText = citation.bbox
    ? `bbox (${citation.bbox.minx.toFixed(1)}, ${citation.bbox.miny.toFixed(1)}) → (${citation.bbox.maxx.toFixed(1)}, ${citation.bbox.maxy.toFixed(1)})`
    : "no bbox";
  const title = `${citation.display_label}\n${bboxText}`;

  return (
    <span
      title={title}
      className="inline-flex items-center gap-0.5 rounded border border-border-subtle bg-bg-elevated px-1 py-0 text-xs text-text-secondary"
    >
      <span className="font-mono text-text-muted uppercase">
        {citation.kind}
      </span>
      <span className="text-text-secondary">·</span>
      <span className="font-mono">{subtitle}</span>
    </span>
  );
}
