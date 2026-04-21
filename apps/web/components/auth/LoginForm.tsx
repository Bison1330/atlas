"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiClientError, authDemoLogin, authLogin } from "@/lib/api";
import { safeNextPath } from "@/lib/auth";

import { Field } from "./Field";


export function LoginForm({ nextPath }: { nextPath: string | null }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoSubmitting, setDemoSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authLogin({ email, password });
      router.push(safeNextPath(nextPath));
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "invalid_credentials") {
        setError("Invalid email or password.");
      } else if (err instanceof ApiClientError && err.code === "rate_limited") {
        setError("Too many attempts. Try again in a few minutes.");
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onDemoClick() {
    setError(null);
    setDemoSubmitting(true);
    try {
      await authDemoLogin();
      router.push(safeNextPath(nextPath));
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "rate_limited") {
        setError("Too many demo login attempts. Try again in a few minutes.");
      } else if (err instanceof ApiClientError && err.code === "demo_login_not_available") {
        setError("Demo mode is currently unavailable.");
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setDemoSubmitting(false);
    }
  }

  const anyBusy = submitting || demoSubmitting;

  return (
    <form onSubmit={onSubmit} noValidate>
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={anyBusy}
      />
      <Field
        label="Password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        disabled={anyBusy}
      />
      {error ? (
        <div className="text-sm text-red-400 mb-2" role="alert">
          {error}
        </div>
      ) : null}
      <button
        type="submit"
        disabled={anyBusy || !email || !password}
        className="w-full rounded bg-accent hover:bg-accent-dim disabled:bg-bg-elevated disabled:text-text-muted text-white font-medium py-1 px-2 transition-colors"
      >
        {submitting ? "Signing in…" : "Sign in"}
      </button>

      <div className="mt-3 flex items-center gap-2 text-xs text-text-muted">
        <div className="h-px flex-1 bg-border-subtle" />
        <span>or</span>
        <div className="h-px flex-1 bg-border-subtle" />
      </div>

      <button
        type="button"
        onClick={onDemoClick}
        disabled={anyBusy}
        className="mt-3 w-full rounded border border-border-subtle bg-bg-surface hover:border-text-muted hover:text-text-primary disabled:text-text-muted text-text-secondary font-medium py-1 px-2 transition-colors"
      >
        {demoSubmitting ? "Loading demo…" : "Try the demo"}
      </button>
      <p className="mt-2 text-center text-xs text-text-muted">
        No signup — explore shared sample drawings.
      </p>
    </form>
  );
}
