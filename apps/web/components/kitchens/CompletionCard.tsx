/**
 * Final-message callout rendered at the bottom of the conversation
 * once Atlas flips the brief to complete. Reassures the user their
 * input is saved and sets expectations about the generation gap.
 */
export function CompletionCard() {
  return (
    <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/[0.06] p-3">
      <p className="font-mono text-[10px] uppercase tracking-wider text-emerald-400">
        Your brief is complete
      </p>
      <p className="mt-1 text-base text-text-primary">
        I would now design 3 candidate kitchen plans, check code
        compliance, and estimate costs.
      </p>
      <p className="mt-1.5 text-sm text-text-secondary">
        Generation is coming in a few days. Your brief is saved — when
        generation launches, you’ll be notified.
      </p>
      <div className="mt-2">
        <button
          type="button"
          disabled
          aria-disabled
          className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-bg-elevated text-text-muted px-3 py-1 text-sm cursor-not-allowed"
          title="Coming soon"
        >
          Start generation
          <span className="font-mono text-[9px] uppercase tracking-wider">
            Soon
          </span>
        </button>
      </div>
    </div>
  );
}
