/**
 * Mock "red-flag questions" card from the contractor engagement
 * package. Shows three of the ~15 V1 questions; title and copy keep
 * the homeowner-advocate tone from the vision doc.
 */
export function RedFlagQuestions() {
  const questions = [
    "Does the bid include permit fees?",
    "What's the timeline for payment milestones?",
    "Who handles the engineer's stamp if we remove that wall?",
  ];

  return (
    <div className="w-full max-w-[460px] rounded-xl border border-border-subtle bg-bg-surface p-3 shadow-elevated">
      <div className="mb-2 flex items-center gap-1">
        <span
          aria-hidden
          className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/15 text-amber-400"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path
              d="M6 1.5l4.5 8h-9l4.5-8z"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinejoin="round"
              fill="none"
            />
            <path
              d="M6 5v2.5"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </span>
        <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
          Ask your contractor
        </p>
      </div>

      <p className="mb-2 text-sm font-medium text-text-primary">
        Three things this bid doesn’t answer yet.
      </p>

      <ol className="space-y-1.5">
        {questions.map((q, i) => (
          <li
            key={q}
            className="flex items-start gap-2 rounded border border-border-subtle bg-bg-elevated px-2 py-1"
          >
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/15 font-mono text-xs text-accent">
              {i + 1}
            </span>
            <span className="text-sm text-text-primary leading-snug">
              {q}
            </span>
          </li>
        ))}
      </ol>

      <p className="mt-2 text-xs text-text-muted">
        Plus 12 more, tailored to this project.
      </p>
    </div>
  );
}
