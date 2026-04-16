const items = [
  {
    title: "Structured drawings",
    body: "A schema-typed view of a sheet: rooms, walls, doors, windows, columns, dimensions. Not pixels — objects with geometry and confidence.",
    tag: "atlas-core",
  },
  {
    title: "Coordination checks",
    body: "Cross-discipline clashes, missing references, spec-drawing drift — flagged at ingest, not in a field RFI.",
    tag: "later",
  },
  {
    title: "Design-intent review",
    body: "Ask the drawing set questions. Atlas answers with sheet citations, not vibes.",
    tag: "later",
  },
];

export function Capabilities() {
  return (
    <section
      id="capabilities"
      className="border-b border-border-subtle bg-bg-base"
    >
      <div className="mx-auto max-w-[1200px] px-3 py-16 md:py-20">
        <SectionHeader eyebrow="Capabilities" title="What Atlas does" />
        <div className="mt-6 grid gap-2 md:grid-cols-3">
          {items.map((item) => (
            <article
              key={item.title}
              className="group relative overflow-hidden rounded-lg border border-border-subtle bg-bg-surface p-3 transition-colors hover:border-text-muted"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-text-primary">
                  {item.title}
                </h3>
                <span className="font-mono text-xs text-text-muted uppercase tracking-wider">
                  {item.tag}
                </span>
              </div>
              <p className="mt-1 text-sm text-text-secondary">{item.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function SectionHeader({
  eyebrow,
  title,
}: {
  eyebrow: string;
  title: string;
}) {
  return (
    <div>
      <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent">
        {eyebrow}
      </span>
      <h2 className="mt-1 text-3xl font-medium tracking-tight text-text-primary md:text-4xl">
        {title}
      </h2>
    </div>
  );
}
