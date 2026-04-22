import { DemoCTA } from "./DemoCTA";

export function FinalCTA() {
  return (
    <section className="relative overflow-hidden">
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 50% 100%, rgba(255,245,230,0.10) 0%, transparent 60%)",
        }}
        aria-hidden
      />
      <div className="relative mx-auto max-w-[1200px] px-3 py-14 md:py-20 text-center">
        <h2 className="font-display text-4xl md:text-5xl text-text-primary leading-tight tracking-tight">
          Try the demo.
        </h2>
        <p className="mt-2 text-lg text-text-secondary">
          No signup. No credit card. Real product.
        </p>
        <div className="mt-4 flex justify-center">
          <DemoCTA variant="primary" size="lg" />
        </div>
      </div>
    </section>
  );
}
