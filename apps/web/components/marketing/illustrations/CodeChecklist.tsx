/**
 * Mock code-check result card. Shows four items: two green passes and
 * two amber warnings — the balance the real product should hit.
 * User-visible strings avoid "AHJ" / "IBC" / "section 305" jargon.
 */
export function CodeChecklist() {
  const items = [
    { label: "Ceiling height, 8'0\" minimum", status: "ok" as const },
    { label: "Egress window in bedroom", status: "ok" as const },
    {
      label: "Load-bearing wall removal — needs an engineer's stamp",
      status: "warn" as const,
    },
    {
      label: "Electrical panel upgrade may be required",
      status: "warn" as const,
    },
  ];

  return (
    <div className="w-full max-w-[460px] rounded-xl border border-border-subtle bg-bg-surface p-3 shadow-elevated">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            Local code check · Oakland CA
          </p>
          <p className="mt-0.5 text-sm font-medium text-text-primary">
            Kitchen remodel
          </p>
        </div>
        <span className="rounded-full border border-border-subtle bg-bg-elevated px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-text-secondary">
          2 flags
        </span>
      </div>

      <ul className="space-y-1">
        {items.map((item) => (
          <li
            key={item.label}
            className="flex items-start gap-1.5 rounded border border-border-subtle bg-bg-elevated px-2 py-1"
          >
            <StatusIcon status={item.status} />
            <span className="text-sm text-text-primary leading-snug">
              {item.label}
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs text-text-muted">
        Atlas checked 11 code requirements against your project scope.
      </p>
    </div>
  );
}


function StatusIcon({ status }: { status: "ok" | "warn" }) {
  if (status === "ok") {
    return (
      <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
          <path
            d="M1.5 5.5l2 2 5-5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  return (
    <span className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-400">
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
        <path
          d="M5 1.5v4.5M5 7.75v0.75"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}
