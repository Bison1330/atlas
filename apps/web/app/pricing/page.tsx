import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { MarketingHeader } from "@/components/marketing/MarketingHeader";
import { PricingStrip } from "@/components/marketing/PricingStrip";
import { PricingTable } from "@/components/marketing/PricingTable";
import { ProjectPackCallout } from "@/components/marketing/ProjectPackCallout";


export const metadata = {
  title: "Pricing — Atlas",
  description:
    "One price, everything included. Homeowner $29/mo, Business $79/mo, or a single $99 Project Pack. No per-floor-plan fees.",
};


export default function PricingPage() {
  return (
    <div className="min-h-screen flex flex-col bg-bg-base">
      <MarketingHeader />
      <main className="flex-1">
        <section className="mx-auto max-w-[1200px] px-3 pt-10 md:pt-14 text-center">
          <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-text-muted mb-2">
            Pricing
          </p>
          <h1 className="font-display text-4xl md:text-5xl text-text-primary leading-tight tracking-tight">
            Pick what fits. Switch any time.
          </h1>
          <p className="mx-auto mt-2 max-w-[620px] text-lg text-text-secondary">
            One price. Everything included. No per-floor-plan fees, no
            hidden per-user seats, no sales call required.
          </p>
        </section>

        <PricingTable />
        <PricingStrip />
        <ProjectPackCallout />
      </main>
      <MarketingFooter />
    </div>
  );
}
