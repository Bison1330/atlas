"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiClientError, authDemoLogin } from "@/lib/api";

type Variant = "primary" | "ghost" | "nav";
type Size = "sm" | "md" | "lg";

interface Props {
  children?: React.ReactNode;
  variant?: Variant;
  size?: Size;
  className?: string;
  // Optional label shown while the session is being established.
  pendingLabel?: string;
}

/**
 * Shared "Try the demo" control used across every marketing surface.
 *
 * Hits POST /auth/demo-login (see lib/api.authDemoLogin), then routes
 * to /drawings — the same landing the LoginForm demo button uses,
 * so there's exactly one demo-entry flow in the app.
 *
 * Errors surface as a small red sentence next to the button — we
 * deliberately avoid toast/modal here because marketing pages
 * shouldn't need a toaster provider.
 */
export function DemoCTA({
  children = "Try the demo",
  variant = "primary",
  size = "md",
  className = "",
  pendingLabel = "Loading demo…",
}: Props) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setError(null);
    setSubmitting(true);
    try {
      await authDemoLogin();
      router.push("/drawings");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "rate_limited") {
        setError("Too many demo attempts. Try again in a few minutes.");
      } else if (err instanceof ApiClientError && err.code === "demo_login_not_available") {
        setError("Demo is currently unavailable.");
      } else {
        setError("Could not start the demo. Please try again.");
      }
      setSubmitting(false);
    }
  }

  const base =
    "inline-flex items-center justify-center gap-1 rounded-full font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed";
  const sizes: Record<Size, string> = {
    sm: "px-2 py-0.5 text-sm",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-2 text-base",
  };
  const variants: Record<Variant, string> = {
    primary:
      "bg-accent hover:bg-accent-dim text-white shadow-glow",
    ghost:
      "border border-border-subtle bg-transparent hover:border-text-muted text-text-secondary hover:text-text-primary",
    nav:
      "text-text-secondary hover:text-text-primary",
  };

  return (
    <span className="inline-flex flex-col items-start">
      <button
        type="button"
        onClick={onClick}
        disabled={submitting}
        className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      >
        {submitting ? pendingLabel : children}
        {!submitting && variant === "primary" ? (
          <span aria-hidden>→</span>
        ) : null}
      </button>
      {error ? (
        <span className="mt-0.5 text-xs text-red-400" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
