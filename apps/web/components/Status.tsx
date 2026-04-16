import { SectionHeader } from "./Capabilities";

const milestones = [
  { id: "M0", title: "Foundation", status: "live" as const, note: "monorepo, stack, CI/CD" },
  { id: "M1", title: "Ingest pipeline", status: "planned" as const, note: "PDF → sheets → tiles" },
  { id: "M2", title: "Structured drawings", status: "planned" as const, note: "rooms, walls, doors" },
  { id: "M3", title: "Coordination checks", status: "planned" as const, note: "clashes, drift" },
  { id: "M4", title: "Design-intent Q&A", status: "planned" as const, note: "grounded answers" },
  { id: "M5", title: "Review workspace", status: "planned" as const, note: "annotations, exports" },
  { id: "M6", title: "Team collaboration", status: "planned" as const, note: "projects, roles" },
];

const statusStyles: Record<"live" | "planned", string> = {
  live: "border-accent/40 bg-accent/5 text-accent",
  planned: "border-border-subtle bg-bg-surface text-text-muted",
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
                {m.status === "live" ? "● live" : "planned"}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
