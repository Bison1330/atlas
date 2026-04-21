/**
 * Auth-related browser helpers + shared types.
 *
 * The session itself is a cookie managed by the API. This module
 * just provides the small bits that don't belong in ``api.ts``:
 * the redirect-target sanitizer, and a type re-export for callers
 * that don't want to import from the big API module.
 */

export type { AuthUser } from "./api";


/**
 * Sanitize a ``?next=`` redirect target.
 *
 * We only permit same-origin absolute paths — protects against
 * attackers crafting login links that bounce the user to an
 * external site after authenticating (open-redirect CVE class).
 *
 * Returns the input when safe, or ``fallback`` otherwise.
 */
export function isSafeRedirect(target: string | undefined | null): boolean {
  if (!target) return false;
  // Must start with `/` (absolute path).
  if (!target.startsWith("/")) return false;
  // Must NOT start with `//` or `/\`  (protocol-relative / backslash-
  // smuggling URLs that some parsers treat as external).
  if (target.startsWith("//") || target.startsWith("/\\")) return false;
  return true;
}


/** Resolve a safe redirect target or return the fallback.
 *
 * Default fallback is ``/drawings`` — that's the logged-in workspace
 * landing (where users actually go to do work). ``/me`` is the
 * profile page, rarely the intended destination after a sign-in.
 */
export function safeNextPath(
  target: string | undefined | null,
  fallback: string = "/drawings",
): string {
  return isSafeRedirect(target) ? (target as string) : fallback;
}
