import { DemoCTA } from "./DemoCTA";

export function ProjectPackCallout() {
  return (
    <section className="mx-auto max-w-[1200px] px-3 pb-10 md:pb-14">
      <div className="mx-auto max-w-[760px] rounded-xl border border-border-subtle bg-bg-surface p-3 md:p-4">
        <div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4">
          <div className="flex-1">
            <p className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
              Project Pack
            </p>
            <p className="mt-0.5">
              <span className="font-display text-3xl text-text-primary">$99</span>
              <span className="ml-1 text-sm text-text-muted">one-time</span>
            </p>
            <p className="mt-1 text-sm text-text-secondary max-w-[520px]">
              Single project, complete package, no subscription. For
              homeowners who want to plan one thing and move on.
            </p>
          </div>
          <div className="shrink-0">
            <DemoCTA variant="primary" size="md">
              Try the demo
            </DemoCTA>
          </div>
        </div>
      </div>
    </section>
  );
}
