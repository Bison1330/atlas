"use client";

import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";


/**
 * Input box + send button. Controlled so the parent can pre-fill
 * the input (example prompts, suggested rephrasings).
 *
 * Enter submits; Shift+Enter adds a newline.
 */
export function QuestionInput({
  value,
  onChange,
  onSubmit,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: (text: string) => void;
  disabled?: boolean;
}) {
  const [composing, setComposing] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  // Re-focus after an external pre-fill so the user can edit
  // inline without reaching for the mouse.
  useEffect(() => {
    if (value && ref.current) {
      ref.current.focus();
    }
  }, [value]);

  const trimmed = value.trim();

  function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !composing) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-t border-border-subtle bg-bg-surface p-1.5 flex items-end gap-1"
    >
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        rows={2}
        placeholder="Ask a question about this drawing…"
        disabled={disabled}
        className="flex-1 rounded bg-bg-elevated border border-border-subtle text-text-primary px-1 py-0.5 text-sm focus:outline-none focus:border-accent transition-colors resize-none disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={disabled || !trimmed}
        className="rounded bg-accent hover:bg-accent-dim disabled:bg-bg-elevated disabled:text-text-muted text-white px-1.5 py-0.5 text-sm transition-colors"
      >
        {disabled ? "…" : "Ask"}
      </button>
    </form>
  );
}
