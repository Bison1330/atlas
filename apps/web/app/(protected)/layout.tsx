/**
 * Server-side auth gate for routes grouped under ``(protected)``.
 *
 * Edge middleware catches the anonymous-user case (no session
 * cookie → redirect to /login). This layout handles the
 * stale-session case: cookie exists but the session is revoked /
 * expired / pointing at a deleted user. It calls ``/auth/me``
 * server-side; on 401, redirects to /login with ``?next=``
 * preserving the original URL so sign-in lands the user back
 * where they were.
 *
 * All child pages run *after* this validation, so they can treat
 * the presence of an authenticated user as a precondition.
 */

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { ReactNode } from "react";

import { authMeOrNull } from "@/lib/api-server";


export default async function ProtectedLayout({
  children,
}: {
  children: ReactNode;
}) {
  const user = await authMeOrNull();
  if (!user) {
    // Reconstruct the path we were trying to render so we can
    // pass it through ?next= for post-login redirect. Fallback
    // to /me since that's the canonical landing.
    const hdrs = await headers();
    const referer = hdrs.get("x-invoke-path") ?? hdrs.get("referer") ?? "/me";
    redirect(`/login?next=${encodeURIComponent(referer)}`);
  }

  return <>{children}</>;
}
