/**
 * Server-side Atlas API client.
 *
 * Used by Next.js server components and route handlers. Unlike the
 * browser wrapper in ``api.ts``, this one:
 *
 * - Reads cookies from Next's ``next/headers`` instead of
 *   ``document.cookie`` (no window on the server).
 * - Talks directly to ``INTERNAL_API_URL`` inside the compose
 *   network, not via the client-facing ``/api/*`` rewrite.
 * - Doesn't add the CSRF header — CSRF is a browser-only concern
 *   (the double-submit pattern defends against cross-origin POSTs
 *   from the victim's browser, not server-to-server calls).
 */

import { cookies } from "next/headers";

import type { AuthUser, DrawingListResponse } from "./api";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://api:8000";


/** Forward the incoming request's cookie jar to the API. */
async function forwardedHeaders(): Promise<Headers> {
  const headers = new Headers();
  // next/headers' cookies() is async in Next 15.
  const jar = await cookies();
  const serialized = jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  if (serialized) headers.set("cookie", serialized);
  return headers;
}


/** Server-side GET /auth/me. Returns null on 401, throws on other errors. */
export async function authMeOrNull(): Promise<AuthUser | null> {
  const res = await fetch(`${INTERNAL_API_URL}/auth/me`, {
    headers: await forwardedHeaders(),
    // Server fetches aren't deduped across renders without explicit
    // caching; auth is per-request so we opt out.
    cache: "no-store",
  });
  if (res.status === 401) return null;
  if (!res.ok) {
    throw new Error(`/auth/me returned ${res.status}`);
  }
  return res.json();
}


/** Server-side GET /drawings. Returns null on 401 (let the page redirect). */
export async function listDrawingsServer(): Promise<DrawingListResponse | null> {
  const res = await fetch(`${INTERNAL_API_URL}/drawings`, {
    headers: await forwardedHeaders(),
    cache: "no-store",
  });
  if (res.status === 401) return null;
  if (!res.ok) {
    throw new Error(`/drawings returned ${res.status}`);
  }
  return res.json();
}
