/**
 * Mock cost-estimate card. Line items with ranges; totals row in a
 * warm accent so the number lands as the main read.
 */
export function CostBreakdown() {
  const items = [
    { label: "Cabinets + hardware", lo: 18, hi: 25 },
    { label: "Countertops", lo: 4, hi: 8 },
    { label: "Flooring", lo: 3, hi: 6 },
    { label: "Labor", lo: 28, hi: 36 },
  ];

  const total = items.reduce(
    (acc, it) => ({ lo: acc.lo + it.lo, hi: acc.hi + it.hi }),
    { lo: 0, hi: 0 },
  );

  return (
    <div className="w-full max-w-[460px] rounded-xl border border-border-subtle bg-bg-surface p-3 shadow-elevated">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            Estimated cost range
          </p>
          <p className="mt-0.5 text-sm font-medium text-text-primary">
            Kitchen remodel · Oakland CA
          </p>
        </div>
        <span className="rounded-full border border-border-subtle bg-bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-text-secondary">
          2025 data
        </span>
      </div>

      <div
        className="rounded-lg px-2 py-2 mb-2"
        style={{
          background:
            "linear-gradient(135deg, rgba(242,238,230,0.12), rgba(232,226,214,0.06))",
          borderLeft: "3px solid #E8E2D6",
        }}
      >
        <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
          Total range
        </p>
        <p className="font-display text-2xl text-text-primary leading-tight">
          ${total.lo},000 – ${total.hi},000
        </p>
      </div>

      <ul className="divide-y divide-border-subtle">
        {items.map((it) => (
          <li
            key={it.label}
            className="flex items-center justify-between py-1 text-sm"
          >
            <span className="text-text-secondary">{it.label}</span>
            <span className="font-mono text-text-primary">
              ${it.lo}–{it.hi}k
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs text-text-muted">
        Based on public bid data for your region, inflation-adjusted.
      </p>
    </div>
  );
}
