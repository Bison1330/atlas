/**
 * Slim "demo mode" banner, rendered at the top of the protected app
 * shell when the logged-in user is the shared demo account.
 *
 * Keeping it deliberately narrow: one line, subtle styling (not
 * alarming), no dismiss button. "You are on a demo" is state the user
 * should always be able to see — hiding the notice would just confuse
 * them later when uploads reset.
 */
export function DemoBanner() {
  return (
    <div
      role="status"
      aria-label="Demo mode notice"
      className="flex items-center gap-2 border-b border-border-subtle bg-bg-elevated px-4 py-2 text-sm text-text-secondary"
    >
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 flex-none rounded-full bg-accent-dim"
      />
      <span>
        <span className="font-medium text-text-primary">Demo mode</span>
        {" — "}
        this is shared sample data. Uploads and changes may be reset
        periodically.
      </span>
    </div>
  );
}
