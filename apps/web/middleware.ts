/**
 * Cookie-presence gate for protected routes.
 *
 * Runs at the edge on every request. Deliberately does NOT validate
 * the session (no DB / Redis access from edge) — just checks whether
 * an ``atlas_session`` cookie exists. Missing cookie on a protected
 * path → 307 redirect to ``/login?next=<original-path>``.
 *
 * The actual validation (is this session still live in Redis? is
 * the user still active?) happens server-side in
 * ``app/(protected)/layout.tsx`` via a call to ``/auth/me``.
 * If validation fails, the layout redirects to /login as well.
 *
 * Protected paths are declared by the ``matcher`` config below. Add
 * paths here as new protected UI slices land.
 */

import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "atlas_session";

export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has(SESSION_COOKIE);
  if (hasSession) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  // Preserve the original target so post-login can land the user
  // back where they were headed. Sanitized in the login page.
  url.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(url);
}

export const config = {
  // Keep this list tight — only gate what actually exists and needs
  // authentication. /login, /register, / stay public; static assets
  // (_next/, icon.svg) also stay public.
  matcher: [
    "/me/:path*",
    "/drawings/:path*",
    "/upload/:path*",
    "/app/:path*",
  ],
};
