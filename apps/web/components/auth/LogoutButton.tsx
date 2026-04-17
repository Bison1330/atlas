"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { authLogout } from "@/lib/api";


export function LogoutButton() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  async function onClick() {
    setSubmitting(true);
    try {
      await authLogout();
      router.push("/");
      router.refresh();
    } catch {
      // Logout is best-effort — even if the server call fails,
      // force a refresh so the browser drops the cached user.
      router.push("/");
      router.refresh();
    }
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={submitting}
      className="rounded border border-border-subtle text-text-secondary hover:text-text-primary hover:border-accent bg-bg-elevated disabled:opacity-50 px-2 py-1 text-sm transition-colors"
    >
      {submitting ? "Signing out…" : "Sign out"}
    </button>
  );
}
