import { DemoCTA } from "./DemoCTA";


type Cell = string | boolean;


interface Tier {
  name: string;
  price: string;
  pricePeriod?: string;
  blurb: string;
  highlight?: boolean;
}


const TIERS: Tier[] = [
  { name: "Free", price: "$0", pricePeriod: "", blurb: "Try before you commit" },
  {
    name: "Homeowner",
    price: "$29",
    pricePeriod: "/ month",
    blurb: "For your project",
    highlight: true,
  },
  {
    name: "Business",
    price: "$79",
    pricePeriod: "/ month",
    blurb: "For your space",
  },
];


// Row order controls the visual sequence. Cell values:
//  true  → check
//  false → dash
//  string → literal (e.g. "Limited", "Watermarked")
const ROWS: Array<{ label: string; cells: [Cell, Cell, Cell] }> = [
  { label: "Active projects", cells: ["1", "Unlimited", "Unlimited"] },
  { label: "AI floor plan generation", cells: [true, true, true] },
  { label: "3D walkthrough", cells: [true, true, true] },
  { label: "Code lookup (residential)", cells: ["Limited", true, true] },
  { label: "Code lookup (commercial)", cells: [false, false, true] },
  { label: "ADA compliance", cells: [false, false, true] },
  { label: "AI photoreal renders", cells: ["5 / mo", "100 / mo", "300 / mo"] },
  { label: "Cost estimation", cells: ["Basic", true, true] },
  { label: "Contractor engagement package", cells: [false, true, true] },
  { label: "Bid comparison tool", cells: [false, true, true] },
  {
    label: "Output formats (PDF)",
    cells: ["Watermarked", "Full", "Full"],
  },
  { label: "Output formats (DWG/DXF)", cells: [false, false, true] },
  { label: "Support", cells: ["Community", "Email", "Priority"] },
];


/**
 * Pricing tier table. Three columns, Homeowner column highlighted.
 *
 * Renders as a proper table on desktop and as three stacked cards on
 * mobile — a scroll-x table reads terribly on 375px. The card mode
 * duplicates the "Try the demo" CTA per tier so the path to the app
 * is always one click away.
 */
export function PricingTable() {
  return (
    <section className="mx-auto max-w-[1200px] px-3 py-10 md:py-14">
      {/* Desktop: true table layout */}
      <div className="hidden md:block">
        <div className="grid grid-cols-[1.4fr_repeat(3,_1fr)] rounded-xl border border-border-subtle overflow-hidden bg-bg-surface">
          <div className="bg-bg-base border-b border-border-subtle" />
          {TIERS.map((t) => (
            <TierHeader key={t.name} tier={t} />
          ))}

          {ROWS.map((r, i) => (
            <div
              key={r.label}
              className="contents"
              role="row"
            >
              <div
                className={[
                  "px-2 py-1.5 text-sm text-text-secondary border-b border-border-subtle",
                  i === ROWS.length - 1 ? "border-b-0" : "",
                ].join(" ")}
              >
                {r.label}
              </div>
              {r.cells.map((cell, ci) => (
                <div
                  key={ci}
                  className={[
                    "px-2 py-1.5 text-sm text-center border-b border-border-subtle",
                    i === ROWS.length - 1 ? "border-b-0" : "",
                    TIERS[ci].highlight ? "bg-accent/[0.04]" : "",
                  ].join(" ")}
                >
                  <CellView value={cell} />
                </div>
              ))}
            </div>
          ))}

          <div className="bg-bg-base" />
          {TIERS.map((t) => (
            <div
              key={t.name}
              className={[
                "px-2 py-2 text-center border-t border-border-subtle",
                t.highlight ? "bg-accent/[0.04]" : "",
              ].join(" ")}
            >
              <DemoCTA
                variant={t.highlight ? "primary" : "ghost"}
                size="sm"
              >
                Try the demo
              </DemoCTA>
            </div>
          ))}
        </div>
      </div>

      {/* Mobile: stacked tier cards */}
      <div className="md:hidden space-y-3">
        {TIERS.map((t, ti) => (
          <div
            key={t.name}
            className={[
              "rounded-xl border px-3 py-3",
              t.highlight
                ? "border-accent/60 bg-accent/[0.06] shadow-glow"
                : "border-border-subtle bg-bg-surface",
            ].join(" ")}
          >
            <TierHeader tier={t} embedded />
            <ul className="mt-2 space-y-1">
              {ROWS.map((r) => (
                <li
                  key={r.label}
                  className="flex items-start justify-between gap-2 py-0.5 text-sm"
                >
                  <span className="text-text-secondary">{r.label}</span>
                  <span className="shrink-0 text-right">
                    <CellView value={r.cells[ti]} />
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3">
              <DemoCTA
                variant={t.highlight ? "primary" : "ghost"}
                size="md"
              >
                Try the demo
              </DemoCTA>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


function TierHeader({ tier, embedded }: { tier: Tier; embedded?: boolean }) {
  return (
    <div
      className={[
        embedded ? "" : "px-2 py-3 border-b border-border-subtle",
        tier.highlight && !embedded ? "bg-accent/[0.06]" : "",
        "text-center",
      ].join(" ")}
    >
      <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
        {tier.name}
      </p>
      <p className="mt-0.5">
        <span
          className={[
            "font-display text-3xl leading-none",
            tier.highlight ? "text-accent" : "text-text-primary",
          ].join(" ")}
        >
          {tier.price}
        </span>
        {tier.pricePeriod ? (
          <span className="ml-0.5 text-sm text-text-muted">
            {tier.pricePeriod}
          </span>
        ) : null}
      </p>
      <p className="mt-0.5 text-xs text-text-muted">{tier.blurb}</p>
    </div>
  );
}


function CellView({ value }: { value: Cell }) {
  if (value === true) {
    return (
      <span
        aria-label="Included"
        className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400"
      >
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
  if (value === false) {
    return (
      <span aria-label="Not included" className="text-text-muted">
        —
      </span>
    );
  }
  return <span className="text-text-secondary">{value}</span>;
}
