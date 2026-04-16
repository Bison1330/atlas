import { SectionHeader } from "./Capabilities";

const steps = [
  {
    n: "01",
    title: "Ingest",
    body: "PDFs, DWGs, BIM exports. Atlas normalizes every sheet into a common structured representation.",
  },
  {
    n: "02",
    title: "Structure",
    body: "Rooms, walls, doors, windows — lifted from geometry and annotation with per-element confidence.",
  },
  {
    n: "03",
    title: "Reason",
    body: "Checks, comparisons, and answers grounded in sheet citations. Every claim points back to a drawing.",
  },
];

export function Approach() {
  return (
    <section id="approach" className="border-b border-border-subtle">
      <div className="mx-auto max-w-[1200px] px-3 py-16 md:py-20">
        <SectionHeader eyebrow="Approach" title="From sheet to reasoning" />
        <ol className="mt-6 grid gap-2 md:grid-cols-3">
          {steps.map((step) => (
            <li
              key={step.n}
              className="rounded-lg border border-border-subtle bg-bg-surface p-3"
            >
              <div className="font-mono text-xs text-text-muted">{step.n}</div>
              <div className="mt-1 text-lg font-medium text-text-primary">
                {step.title}
              </div>
              <p className="mt-1 text-sm text-text-secondary">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
