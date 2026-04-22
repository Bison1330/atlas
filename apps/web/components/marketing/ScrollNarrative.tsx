"use client";

import { useEffect, useRef, useState } from "react";

import { ChatMockup } from "./illustrations/ChatMockup";
import { CodeChecklist } from "./illustrations/CodeChecklist";
import { CostBreakdown } from "./illustrations/CostBreakdown";
import { KitchenScene } from "./illustrations/KitchenScene";
import { RedFlagQuestions } from "./illustrations/RedFlagQuestions";


interface Step {
  id: string;
  title: string;
  subhead: string;
  mockup: React.ReactNode;
}

const STEPS: Step[] = [
  {
    id: "describe",
    title: "Describe it.",
    subhead:
      "Tell Atlas what you want to build. Plain words. No technical jargon.",
    mockup: <ChatMockup />,
  },
  {
    id: "see",
    title: "See it.",
    subhead:
      "Walk through a 3D model of your project. As real as you need it to be.",
    mockup: <KitchenScene />,
  },
  {
    id: "check",
    title: "Check it.",
    subhead:
      "Atlas looks up your local building code and tells you what you'll need.",
    mockup: <CodeChecklist />,
  },
  {
    id: "price",
    title: "Price it.",
    subhead:
      "Real cost ranges from real data. No lowballs, no surprises.",
    mockup: <CostBreakdown />,
  },
  {
    id: "bring-it-home",
    title: "Bring it home.",
    subhead:
      "Get a contractor-ready package. Know when a bid is fair.",
    mockup: <RedFlagQuestions />,
  },
];


/**
 * Forma-style scrolling narrative. Sticky left rail with a vertical
 * 5-dot stepper; content on the right alternates text/mockup sides
 * between steps for visual rhythm. Active dot is driven by an
 * IntersectionObserver — whichever section's midpoint is closest to
 * the viewport center "owns" the active state.
 *
 * On mobile the rail collapses; each section shows a small inline
 * dot + number instead, so the narrative still reads as a sequence.
 */
export function ScrollNarrative() {
  const [active, setActive] = useState(0);
  const sectionRefs = useRef<Array<HTMLDivElement | null>>([]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Of the currently-intersecting entries, pick whichever has
        // its midpoint closest to the viewport midpoint. Beats
        // "largest intersection ratio" when two sections are both
        // 50% visible.
        const midpoint = window.innerHeight / 2;
        let best: { idx: number; distance: number } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const rect = entry.target.getBoundingClientRect();
          const sectionMid = rect.top + rect.height / 2;
          const distance = Math.abs(sectionMid - midpoint);
          const idx = Number((entry.target as HTMLElement).dataset.index);
          if (Number.isNaN(idx)) continue;
          if (!best || distance < best.distance) {
            best = { idx, distance };
          }
        }
        if (best) setActive(best.idx);
      },
      {
        // Fire continuously while a section is in view so the midpoint
        // comparison stays fresh — a default rootMargin is fine.
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    sectionRefs.current.forEach((el) => {
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  return (
    <section id="product" className="relative">
      <div className="mx-auto max-w-[1200px] px-3 pt-6 pb-4">
        <div className="max-w-[640px]">
          <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-text-muted mb-2">
            How it works
          </p>
          <h2 className="font-display text-3xl md:text-4xl text-text-primary leading-tight">
            Five steps from idea to a contractor you trust.
          </h2>
        </div>
      </div>

      <div className="mx-auto max-w-[1200px] px-3">
        <div className="md:grid md:grid-cols-[80px_1fr] md:gap-6">
          {/* Sticky rail — desktop only */}
          <aside className="hidden md:block">
            <div className="sticky top-16 py-6">
              <ol className="flex flex-col items-center gap-3">
                {STEPS.map((s, i) => {
                  const isActive = i === active;
                  return (
                    <li key={s.id} className="flex flex-col items-center">
                      <button
                        type="button"
                        onClick={() =>
                          document
                            .getElementById(s.id)
                            ?.scrollIntoView({ behavior: "smooth", block: "start" })
                        }
                        aria-label={`Jump to step ${i + 1}: ${s.title}`}
                        className={[
                          "h-3 w-3 rounded-full border transition-all",
                          isActive
                            ? "bg-accent border-accent scale-125 shadow-glow"
                            : "bg-transparent border-border-subtle hover:border-text-muted",
                        ].join(" ")}
                      />
                      {i < STEPS.length - 1 ? (
                        <span
                          aria-hidden
                          className={[
                            "mt-3 h-12 w-px transition-colors",
                            i < active ? "bg-accent/60" : "bg-border-subtle",
                          ].join(" ")}
                        />
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </div>
          </aside>

          <div>
            {STEPS.map((s, i) => {
              const textLeft = i % 2 === 0;
              return (
                <div
                  key={s.id}
                  id={s.id}
                  data-index={i}
                  ref={(el) => {
                    sectionRefs.current[i] = el;
                  }}
                  className="scroll-mt-16 flex min-h-[70vh] md:min-h-[85vh] items-center py-6"
                >
                  <div
                    className={[
                      "grid w-full gap-4 md:gap-6",
                      "md:grid-cols-2 items-center",
                    ].join(" ")}
                  >
                    <div className={textLeft ? "md:order-1" : "md:order-2"}>
                      <p className="md:hidden font-mono text-[10px] uppercase tracking-wider text-text-muted mb-1">
                        Step {i + 1} of {STEPS.length}
                      </p>
                      <h3 className="font-display text-3xl md:text-4xl text-text-primary leading-tight tracking-tight">
                        {s.title}
                      </h3>
                      <p className="mt-2 text-lg text-text-secondary max-w-[460px]">
                        {s.subhead}
                      </p>
                    </div>
                    <div
                      className={[
                        "flex justify-center md:justify-start",
                        textLeft ? "md:order-2 md:justify-end" : "md:order-1",
                      ].join(" ")}
                    >
                      {s.mockup}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
