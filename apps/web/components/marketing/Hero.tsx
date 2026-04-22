import Link from "next/link";

import { DemoCTA } from "./DemoCTA";

/**
 * Landing hero. Two columns on desktop (copy left, video placeholder
 * right), stacks on mobile. Warm gradient in the placeholder uses
 * study-model palette values (see studyModelPalette.ts) so the
 * marketing visual reads of-a-piece with the 3D viewer.
 *
 * The "See how it works ↓" button scroll-anchors to #product, which
 * is the ScrollNarrative section id.
 */
export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 bg-grid-fade pointer-events-none" aria-hidden />
      <div className="relative mx-auto max-w-[1200px] px-3 pt-8 pb-10 md:pt-12 md:pb-16">
        <div className="grid grid-cols-1 md:grid-cols-[1.1fr_1fr] gap-6 md:gap-8 items-center">
          <div className="order-2 md:order-1">
            <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-text-muted mb-3">
              Built for homeowners and small business owners
            </p>
            <h1 className="font-display text-4xl md:text-5xl lg:text-6xl leading-[1.05] text-text-primary tracking-tight">
              Atlas is on your side
              <br className="hidden sm:block" /> when you build.
            </h1>
            <p className="mt-3 text-lg text-text-secondary max-w-[560px]">
              Describe your project. Get plans, 3D walkthroughs, real
              costs, and code checks — without hiring an architect or
              getting rolled by a contractor.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <DemoCTA variant="primary" size="lg">
                Try the demo
              </DemoCTA>
              <Link
                href="#product"
                className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-transparent hover:border-text-muted text-text-secondary hover:text-text-primary px-4 py-2 text-base transition-colors"
              >
                See how it works <span aria-hidden>↓</span>
              </Link>
            </div>
          </div>

          <div className="order-1 md:order-2">
            <HeroVideoPlaceholder />
          </div>
        </div>
      </div>
    </section>
  );
}


function HeroVideoPlaceholder() {
  return (
    <div>
      <div
        className="relative aspect-video w-full overflow-hidden rounded-xl border border-border-subtle shadow-elevated"
        style={{
          // Warm gradient from the study-model palette — interior
          // wall cream → exterior wall cream → floor taupe → ground.
          // Keeps the hero reading of-a-piece with the 3D viewer.
          backgroundImage:
            "linear-gradient(135deg, #F2EEE6 0%, #E8E2D6 40%, #C9C2B4 75%, #A8A29A 100%)",
        }}
        aria-label="Product preview placeholder"
      >
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at 30% 20%, rgba(255,245,230,0.6) 0%, transparent 60%)",
          }}
          aria-hidden
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full bg-white/40 backdrop-blur-sm ring-1 ring-white/60 shadow-elevated"
            aria-hidden
          >
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <path
                d="M7 5.5v11l9-5.5-9-5.5z"
                fill="#2B2723"
              />
            </svg>
          </div>
        </div>
      </div>
      <p className="mt-1 text-center text-xs text-text-muted">
        Product preview — recording coming soon
      </p>
    </div>
  );
}
