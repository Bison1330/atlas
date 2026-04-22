/**
 * Shared competitive-pricing comparison. Four rows: Atlas, Archilogic,
 * Enscape, Matterport. Atlas is visually called out.
 *
 * Used on both the landing (section 5) and the pricing page.
 * Numbers here should match the prices quoted in the public vision
 * doc; if pricing changes, change both places.
 */

interface Row {
  name: string;
  price: string;
  blurb: string;
  atlas?: boolean;
}

const ROWS: Row[] = [
  {
    name: "Atlas Homeowner",
    price: "$29/mo",
    blurb: "Unlimited projects, code checks, cost estimates, AI renders",
    atlas: true,
  },
  {
    name: "Archilogic Plus",
    price: "$24.90/mo",
    blurb: "Per floor plan",
  },
  {
    name: "Enscape Solo",
    price: "$575/year",
    blurb: "Revit plugin only",
  },
  {
    name: "Matterport Starter",
    price: "$14/mo",
    blurb: "Plus a $3K camera",
  },
];


export function PricingStrip() {
  return (
    <section className="mx-auto max-w-[1200px] px-3 py-10 md:py-14">
      <div className="mx-auto max-w-[760px] text-center">
        <h2 className="font-display text-3xl md:text-4xl text-text-primary leading-tight tracking-tight">
          One price. Everything included.
          <br className="hidden sm:block" />
          <span className="text-text-secondary"> No per-floor-plan fees.</span>
        </h2>
      </div>

      <ul className="mx-auto mt-6 max-w-[760px] space-y-1">
        {ROWS.map((r) => (
          <li
            key={r.name}
            className={[
              "grid grid-cols-[1fr_auto] md:grid-cols-[220px_120px_1fr] gap-1.5 md:gap-3 items-baseline",
              "rounded-lg border px-2 py-1.5",
              r.atlas
                ? "border-accent/50 bg-accent/[0.06] shadow-glow"
                : "border-border-subtle bg-bg-surface",
            ].join(" ")}
          >
            <span
              className={[
                "text-sm font-medium",
                r.atlas ? "text-text-primary" : "text-text-secondary",
              ].join(" ")}
            >
              {r.name}
            </span>
            <span
              className={[
                "font-mono text-sm",
                r.atlas ? "text-accent" : "text-text-muted",
              ].join(" ")}
            >
              {r.price}
            </span>
            <span
              className={[
                "text-sm col-span-2 md:col-span-1",
                r.atlas ? "text-text-secondary" : "text-text-muted",
              ].join(" ")}
            >
              {r.blurb}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
