"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiClientError, authRegister } from "@/lib/api";
import { safeNextPath } from "@/lib/auth";

import { Field } from "./Field";


export function RegisterForm({ nextPath }: { nextPath: string | null }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authRegister({
        email,
        password,
        display_name: displayName || undefined,
      });
      router.push(safeNextPath(nextPath));
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError) {
        // Surface the specific reason — "too_short" / "common_password"
        // / "email_taken" — not a generic "registration failed" that
        // hides what the user needs to fix. See §8.4 of the research
        // doc on why we don't swallow these.
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={submitting}
      />
      <Field
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        minLength={10}
        hint="At least 10 characters. Long passphrases are better than complex short ones."
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        disabled={submitting}
      />
      <Field
        label="Display name"
        type="text"
        autoComplete="name"
        hint="Optional — shown on annotations you create."
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        disabled={submitting}
      />
      {error ? (
        <div className="text-sm text-red-400 mb-2" role="alert">
          {error}
        </div>
      ) : null}
      <button
        type="submit"
        disabled={submitting || !email || password.length < 10}
        className="w-full rounded bg-accent hover:bg-accent-dim disabled:bg-bg-elevated disabled:text-text-muted text-white font-medium py-1 px-2 transition-colors"
      >
        {submitting ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
