import type { InputHTMLAttributes } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

/** Single text input with label + optional hint. */
export function Field({ label, hint, id, ...rest }: FieldProps) {
  const inputId = id ?? `field-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <label htmlFor={inputId} className="block mb-2">
      <span className="block text-sm text-text-secondary mb-0.5">{label}</span>
      <input
        id={inputId}
        className="w-full rounded bg-bg-elevated border border-border-subtle text-text-primary px-1.5 py-1 text-sm focus:outline-none focus:border-accent transition-colors"
        {...rest}
      />
      {hint ? (
        <span className="block text-xs text-text-muted mt-0.5">{hint}</span>
      ) : null}
    </label>
  );
}
