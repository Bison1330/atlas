import type { AnswerCertainty, AskResponse } from "@/lib/api";

import { CitationChip } from "./CitationChip";


/**
 * Renders one assistant response. Handles all supported buckets
 * plus ``unsupported`` in a single branch-on-answer_type flow.
 *
 * Confidence badge and extraction-status info are both surfaced;
 * the header-level caveat banner lives in ChatPanel, but the
 * per-response confidence (high/medium/low) shows up here.
 */
export function AnswerCard({
  payload,
  onSuggestedPhrasing,
}: {
  payload: AskResponse;
  onSuggestedPhrasing?: (text: string) => void;
}) {
  if (payload.answer_type === "unsupported") {
    return <UnsupportedCard payload={payload} onSuggestedPhrasing={onSuggestedPhrasing} />;
  }
  return <AnsweredCard payload={payload} />;
}


function AnsweredCard({ payload }: { payload: AskResponse }) {
  return (
    <div className="rounded border border-border-subtle bg-bg-surface p-1.5">
      <p className="text-sm text-text-primary whitespace-pre-wrap">
        {payload.answer}
      </p>
      {payload.citations.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-0.5">
          {payload.citations.map((c) => (
            <CitationChip key={c.element_id} citation={c} />
          ))}
        </div>
      ) : null}
      <AnswerFooter payload={payload} />
    </div>
  );
}


function UnsupportedCard({
  payload,
  onSuggestedPhrasing,
}: {
  payload: AskResponse;
  onSuggestedPhrasing?: (text: string) => void;
}) {
  const suggested = payload.query_interpretation.suggested_phrasing;
  return (
    <div className="rounded border border-border-subtle bg-bg-surface/60 p-1.5">
      <p className="text-sm text-text-secondary">{payload.answer}</p>
      {suggested && onSuggestedPhrasing ? (
        <button
          type="button"
          onClick={() => onSuggestedPhrasing(suggested)}
          className="mt-1 inline-flex items-center gap-0.5 rounded border border-accent/30 bg-accent/5 text-accent hover:bg-accent/10 px-1 py-0 text-xs transition-colors"
        >
          Try: <span className="font-medium">{suggested}</span>
        </button>
      ) : null}
    </div>
  );
}


function AnswerFooter({ payload }: { payload: AskResponse }) {
  const certainty = payload.confidence.answer_certainty;
  const extractionMin = payload.confidence.extraction_min;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-text-muted">
      <CertaintyBadge value={certainty} />
      {extractionMin !== null ? (
        <span className="font-mono">
          min confidence: {extractionMin.toFixed(2)}
        </span>
      ) : null}
    </div>
  );
}


function CertaintyBadge({ value }: { value: AnswerCertainty }) {
  const color =
    value === "high"
      ? "text-accent"
      : value === "medium"
        ? "text-yellow-400"
        : "text-text-muted";
  return <span className={color}>certainty: {value}</span>;
}
