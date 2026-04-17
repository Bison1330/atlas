import { SectionHeader } from "./Capabilities";

const milestones = [
  { id: "M0", title: "Foundation", status: "live" as const, note: "monorepo, stack, CI/CD" },
  { id: "M1", title: "Ingest pipeline", status: "live" as const, note: "PDF → sheets → tiles" },
  { id: "M2", title: "Structured drawings", status: "live" as const, note: "DXF → elements (walls, doors, rooms, symbols)" },
  { id: "M3", title: "Enhanced analysis", status: "active" as const, note: "takeoffs · room connectivity · eval framework" },
  { id: "M4", title: "Coordination checks", status: "planned" as const, note: "clashes, drift" },
  { id: "M5", title: "Design-intent Q&A", status: "planned" as const, note: "grounded answers" },
  { id: "M6", title: "Review workspace", status: "planned" as const, note: "annotations, exports" },
];

const statusStyles: Record<"live" | "active" | "planned", string> = {
  live: "border-accent/40 bg-accent/5 text-accent",
  active: "border-accent/60 bg-accent/10 text-accent",
  planned: "border-border-subtle bg-bg-surface text-text-muted",
};

const statusLabel: Record<"live" | "active" | "planned", string> = {
  live: "● live",
  active: "◐ active",
  planned: "planned",
};

export function Status() {
  return (
    <section id="status" className="border-b border-border-subtle bg-bg-base">
      <div className="mx-auto max-w-[1200px] px-3 py-16 md:py-20">
        <SectionHeader eyebrow="Status" title="Build roadmap" />
        <p className="mt-2 max-w-[680px] text-sm text-text-secondary">
          Public, incremental milestones. Each one ships end-to-end before the
          next one starts.
        </p>
        <ul className="mt-6 divide-y divide-border-subtle overflow-hidden rounded-lg border border-border-subtle bg-bg-surface">
          {milestones.map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div className="flex items-center gap-3">
                <span
                  className={`inline-flex w-16 justify-center rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wider ${statusStyles[m.status]}`}
                >
                  {m.id}
                </span>
                <div>
                  <div className="text-sm font-medium text-text-primary">
                    {m.title}
                  </div>
                  <div className="text-xs text-text-muted">{m.note}</div>
                </div>
              </div>
              <span className="font-mono text-xs uppercase tracking-wider text-text-muted">
                {statusLabel[m.status]}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
