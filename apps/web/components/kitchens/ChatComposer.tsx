"use client";

import { FormEvent, KeyboardEvent, useRef, useState } from "react";


/**
 * Centered chat composer used on /app (empty state) and as the
 * in-conversation input on /app/kitchens/[id].
 *
 * Submit on Enter; Shift+Enter inserts a newline. Button click
 * submits too. Auto-grows the textarea up to `maxRows`.
 */
export function ChatComposer({
  value,
  onChange,
  onSubmit,
  placeholder,
  disabled = false,
  submitLabel = "Send",
  minRows = 2,
  maxRows = 8,
  autoFocus = false,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: (value: string) => void | Promise<void>;
  placeholder?: string;
  disabled?: boolean;
  submitLabel?: string;
  minRows?: number;
  maxRows?: number;
  autoFocus?: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e?: FormEvent<HTMLFormElement>) {
    e?.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || pending || disabled) return;
    setPending(true);
    try {
      await onSubmit(trimmed);
    } finally {
      setPending(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void handleSubmit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={[
        "w-full rounded-xl border transition-colors",
        "border-border-subtle bg-bg-surface focus-within:border-accent/60",
        disabled ? "opacity-60 pointer-events-none" : "",
      ].join(" ")}
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        rows={minRows}
        style={{ maxHeight: `${maxRows * 1.5}rem` }}
        autoFocus={autoFocus}
        disabled={disabled || pending}
        className="block w-full resize-none bg-transparent px-3 py-2 text-base text-text-primary placeholder:text-text-muted focus:outline-none"
      />
      <div className="flex items-center justify-between gap-2 border-t border-border-subtle px-2 py-1">
        <p className="text-xs text-text-muted">
          <kbd className="font-mono text-[10px]">Enter</kbd> to send ·
          {" "}
          <kbd className="font-mono text-[10px]">Shift+Enter</kbd> for a new line
        </p>
        <button
          type="submit"
          disabled={disabled || pending || !value.trim()}
          className="inline-flex items-center gap-1 rounded-full bg-accent hover:bg-accent-dim text-white font-medium px-3 py-1 text-sm transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {pending ? "Sending…" : submitLabel}
          {!pending && <span aria-hidden>→</span>}
        </button>
      </div>
    </form>
  );
}
