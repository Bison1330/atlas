"use client";

/**
 * Project-type pills for the /app homepage.
 *
 * V1: only Kitchen is active; the rest render "Coming soon" on hover
 * and are non-interactive. The onSelect callback only fires for
 * clickable pills.
 */

type PillId = "kitchen" | "bathroom" | "retail" | "office" | "upload";


interface PillDef {
  id: PillId;
  label: string;
  emoji: string;
  active: boolean;
}


const PILLS: PillDef[] = [
  { id: "kitchen", label: "Kitchen", emoji: "🏠", active: true },
  { id: "bathroom", label: "Bathroom", emoji: "🛁", active: false },
  { id: "retail", label: "Retail space", emoji: "🏪", active: false },
  { id: "office", label: "Office", emoji: "💼", active: false },
  { id: "upload", label: "Upload plans", emoji: "📐", active: false },
];


export function ProjectTypePills({
  selected,
  onSelect,
}: {
  selected: PillId;
  onSelect: (id: PillId) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-1 mb-3">
      {PILLS.map((p) => {
        const isSelected = p.active && p.id === selected;
        const disabled = !p.active;
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => p.active && onSelect(p.id)}
            disabled={disabled}
            title={disabled ? "Coming soon" : undefined}
            aria-pressed={isSelected}
            aria-disabled={disabled}
            className={[
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-sm transition-colors",
              isSelected
                ? "border-accent bg-accent/[0.08] text-text-primary shadow-glow"
                : disabled
                ? "border-border-subtle bg-bg-surface text-text-muted cursor-not-allowed opacity-60"
                : "border-border-subtle bg-bg-surface text-text-secondary hover:border-text-muted hover:text-text-primary",
            ].join(" ")}
          >
            <span aria-hidden>{p.emoji}</span>
            <span>{p.label}</span>
            {disabled && (
              <span className="ml-0.5 font-mono text-[9px] uppercase tracking-wider text-text-muted">
                Soon
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}


export type { PillId };
