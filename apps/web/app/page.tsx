import { FinalCTA } from "@/components/marketing/FinalCTA";
import { Hero } from "@/components/marketing/Hero";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { MarketingHeader } from "@/components/marketing/MarketingHeader";
import { PricingStrip } from "@/components/marketing/PricingStrip";
import { ScrollNarrative } from "@/components/marketing/ScrollNarrative";
import { ThreeWaysIn } from "@/components/marketing/ThreeWaysIn";
import { TrustLine } from "@/components/marketing/TrustLine";

/**
 * V1 marketing landing. Public, unauthenticated surface — the
 * middleware leaves "/" open, so this renders for everyone.
 *
 * Structure (top to bottom):
 *  1. MarketingHeader       — sticky nav
 *  2. Hero                  — headline + dual CTA + video placeholder
 *  3. ThreeWaysIn           — pill cards (home / space / project)
 *  4. ScrollNarrative       — 5-step sticky-rail walkthrough
 *  5. PricingStrip          — competitive comparison
 *  6. TrustLine             — one-line data-handling promise
 *  7. FinalCTA              — closing Try-the-demo
 *  8. MarketingFooter       — 4-column footer
 */
export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col bg-bg-base">
      <MarketingHeader />
      <main className="flex-1">
        <Hero />
        <ThreeWaysIn />
        <ScrollNarrative />
        <PricingStrip />
        <TrustLine />
        <FinalCTA />
      </main>
      <MarketingFooter />
    </div>
  );
}
