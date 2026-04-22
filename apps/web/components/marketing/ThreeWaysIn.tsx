"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { authDemoLogin } from "@/lib/api";


interface Way {
  emoji: string;
  label: string;
  sublabel: string;
}

const WAYS: Way[] = [
  {
    emoji: "🏠",
    label: "A home",
    sublabel: "New build, addition, remodel, or dream house",
  },
  {
    emoji: "🏪",
    label: "A space",
    sublabel: "Retail, restaurant, office, or studio fit-out",
  },
  {
    emoji: "📐",
    label: "A project",
    sublabel: "Already have drawings? Upload and go",
  },
];


/**
 * Three pill cards directly below the hero. All three currently hit
 * the demo-login entry point — the project-type picker becomes a
 * real onboarding flow in a later session, at which point each card
 * will route to a different initial prompt.
 */
export function ThreeWaysIn() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function enter(_way: Way) {
    if (pending) return;
    setPending(true);
    try {
      await authDemoLogin();
      router.push("/drawings");
      router.refresh();
    } catch {
      // Silent fallback — send the user to /login with the demo
      // button visible there.
      router.push("/login");
    }
  }

  return (
    <section className="mx-auto max-w-[1200px] px-3 py-6 md:py-8">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {WAYS.map((way) => (
          <button
            key={way.label}
            type="button"
            onClick={() => enter(way)}
            disabled={pending}
            className={[
              "group flex flex-col items-center gap-1 rounded-xl border border-border-subtle bg-bg-surface",
              "px-3 py-4 text-center transition-all duration-150",
              "hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-elevated",
              "disabled:opacity-60 disabled:cursor-wait",
            ].join(" ")}
          >
            <span aria-hidden className="text-3xl leading-none">
              {way.emoji}
            </span>
            <span className="font-display text-xl text-text-primary">
              {way.label}
            </span>
            <span className="text-sm text-text-muted max-w-[280px]">
              {way.sublabel}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
