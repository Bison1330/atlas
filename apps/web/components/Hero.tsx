export function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-border-subtle">
      <div className="absolute inset-0 grid-lines opacity-60" aria-hidden />
      <div
        className="absolute inset-0 bg-grid-fade pointer-events-none"
        aria-hidden
      />

      <div className="relative mx-auto max-w-[1200px] px-3 pt-16 pb-20 md:pt-24 md:pb-24">
        <span className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-bg-surface px-2 py-0.5 font-mono text-xs text-text-secondary">
          <span className="h-1 w-1 rounded-full bg-accent" />
          Atlas · Working title
        </span>

        <h1 className="mt-3 max-w-[900px] text-4xl font-medium leading-[1.05] tracking-tight text-text-primary md:text-6xl">
          Architecture that{" "}
          <span className="text-accent">checks itself</span>.
        </h1>

        <p className="mt-3 max-w-[680px] text-lg text-text-secondary md:text-xl">
          Atlas ingests construction documents and reasons over them —
          structured drawings, coordination checks, and design-intent reviews
          for AEC teams that can&apos;t afford to miss things.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <a
            href="/upload"
            className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-bg-base transition-colors hover:bg-accent-dim"
          >
            Try the ingest pipeline
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden
            >
              <path
                d="M5 12h14M13 6l6 6-6 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </a>
          <a
            href="#status"
            className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-bg-surface px-3 py-1.5 text-sm font-medium text-text-primary transition-colors hover:border-text-muted"
          >
            Build status
          </a>
        </div>

        <dl className="mt-8 grid max-w-[720px] grid-cols-3 gap-2 border-t border-border-subtle pt-4">
          <Stat label="Disciplines" value="14" hint="CSI sheet set" />
          <Stat label="Element kinds" value="10" hint="rooms → symbols" />
          <Stat label="Milestones shipped" value="4 / 7" hint="M0 · M1 · M2 · M3 live" />
        </dl>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div>
      <dt className="font-mono text-xs uppercase tracking-wider text-text-muted">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-2xl font-medium text-text-primary">
        {value}
      </dd>
      <dd className="text-xs text-text-secondary">{hint}</dd>
    </div>
  );
}
