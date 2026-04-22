"use client";

import { useState } from "react";


const PROMPTS = [
  "I want to redo my kitchen in my 1980s colonial. Open it up to the living room, add an island with seating, replace the cabinets.",
  "Small galley kitchen remodel, 8ft × 12ft, want to maximize counter space and storage on a tight budget.",
  "Designing a kitchen for a new build — 400 sqft, open to the dining and family rooms, we love cooking and entertaining.",
];


/**
 * Collapsible "Try an example" section for the /app homepage.
 *
 * Clicking a prompt populates the composer but does NOT auto-submit
 * — the user should read and tweak before sending.
 */
export function ExamplePrompts({ onPick }: { onPick: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text-primary transition-colors"
        aria-expanded={open}
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        Try an example
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {PROMPTS.map((p) => (
            <li key={p}>
              <button
                type="button"
                onClick={() => onPick(p)}
                className="block w-full rounded-lg border border-border-subtle bg-bg-surface hover:border-accent/60 hover:bg-bg-elevated text-left px-2 py-1.5 text-sm text-text-secondary transition-colors"
              >
                {p}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
