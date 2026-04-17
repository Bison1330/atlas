# atlas-web M7 — auth UI (thin frontend slice)

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the smallest frontend slice that enables any of M5–M8 to be
used in a browser, and which frontend work explicitly waits for
later slices?

### Sub-questions

- How do cookies set by FastAPI reach Next.js cleanly — same-origin
  via proxy, or cross-origin with credentials mode?
- Where does the auth check live in the App Router — server
  components, client components, or middleware?
- How is the CSRF double-submit token handled without leaking it
  beyond the client boundary?
- How do we preserve `?next=/original-path` through the redirect
  chain so post-login lands the user back where they tried to go?
- What about the 15.1.x Next.js runtime quirks we already hit once
  (the `'aa'` TypeError during the dev-stack restart)?

## Why this matters

Opens **D-18** (frontend auth architecture). Every future UI slice
(M5b chat, M6b annotations-on-viewer, M8b projects) sits on top of
whatever this slice lands. Get the session + CSRF flow wrong once
and every subsequent feature inherits a corrupt auth layer that's
annoying to refactor out.

Also: this is the primitive that turns Atlas from "API you can
curl" into "thing a person visits in a browser." It's
disproportionately load-bearing for that reason alone.

---

## Position

Opinionated. Each section ends with a decision.

### 0. Scope is ruthlessly narrow — intentionally

Out of scope for this slice, each documented with the follow-up
it belongs in:

| Out | Goes in |
|-----|---------|
| Drawings list / upload UI        | **web/m2-drawings-ui** |
| Sheet viewer with tile rendering | **web/m2-viewer** |
| Element bbox overlay             | **web/m2-viewer** |
| Q&A chat panel + citation chips  | **web/m5-chat** |
| Annotation anchoring on viewer   | **web/m6-annotations** |
| Project list / member management | **web/m8-projects** |
| Drawing→project assignment UI    | **web/m8-projects** |
| Password reset / email verify    | **web/m7.1** (depends on M7.1 email infra) |

In scope:

- `/login` (client component, form → POST to API, redirect on success).
- `/register` (same shape, hits `/auth/register`).
- `/me` (server-rendered; shows `{email, display_name, logout button}`).
- Next.js middleware: protected-route redirect with `?next=` preservation.
- Shared fetch wrapper: session-included + CSRF header injection.
- Existing landing page (`/`) unchanged for anonymous visitors.

**Decision: auth UI only.** 2–3 days of work. Unlocks every later
slice with zero throwaway.

### 1. Cookie transport — same-origin via Next.js rewrites

**Decision: same-origin via Next.js `rewrites`.** All client code
calls `/api/*` paths; Next.js proxies them to FastAPI. Cookies set
by FastAPI land on the same origin the browser loaded the page
from, no `SameSite=None` / cross-origin dance.

In dev (docker-compose):

```js
// apps/web/next.config.js
async rewrites() {
  return [
    { source: '/api/:path*', destination: `${process.env.INTERNAL_API_URL}/:path*` },
  ];
}
```

`INTERNAL_API_URL` is the compose-internal hostname (`http://api:8000`)
when Next.js runs inside the compose network. In prod behind Caddy,
Caddy already does the path-stripped `/api/*` → API proxy, so
Next.js rewrites aren't consulted — `fetch('/api/auth/me')` from a
browser loaded via Caddy hits the API directly via Caddy. **One
code path, two deployments.**

Rejected alternatives:

- *Cross-origin with `credentials: 'include'`.* Works but requires
  `SameSite=None` on cookies (weaker CSRF posture), explicit CORS
  origin allowlists, and browser quirks around third-party cookie
  blocking. All of this goes away with same-origin.
- *Server-side proxy through Next.js API routes.* Each mutation
  becomes a Next.js route that forwards to FastAPI and re-emits
  cookies. Duplicated set-cookie logic; more code.
- *Next.js Server Actions for auth.* Server Actions are the
  modern-idiomatic way, but they push the call further from the
  FastAPI request/response shape. Harder to debug when the API
  returns structured errors with `request_id` fields. Skip.

### 2. Where the auth check lives

**Decision: three-tier.**

1. **Middleware** (`middleware.ts`): cookie-*presence* check only.
   If a protected path has no `atlas_session` cookie, redirect to
   `/login?next=<path>`. Doesn't validate — validation is async DB
   + Redis work that shouldn't happen in edge middleware.

2. **Server component** (`app/(protected)/layout.tsx`): calls
   `GET /api/auth/me` server-side with the forwarded cookie. On
   401, `redirect('/login')`. Happens once per page render.

3. **Client components**: never do the auth check themselves.
   They `useSession()` from a tiny hook that reads the data the
   server component passed down via context or props.

Flow diagram for an unauthenticated user hitting `/me`:

```
Browser:   GET /me
           ↓
Middleware (edge): no atlas_session cookie
           → 307 /login?next=/me

Browser:   GET /login?next=/me
           ↓ (no middleware redirect — /login is public)
Server comp: render LoginPage
```

For an authenticated user:

```
Browser:   GET /me (with atlas_session cookie)
           ↓
Middleware: cookie present, pass through
           ↓
Server layout: forward cookie → GET /api/auth/me
             ↓
          200 { email, display_name, ... }
          → render protected tree with user in context
```

Rejected alternatives:

- *All auth in middleware.* Tempting but middleware's edge runtime
  can't hit the FastAPI cleanly (network egress patterns differ);
  also no DB session validation, just cookie signature check which
  we deliberately moved to Redis.
- *All auth in client components.* Works but flashes unauth'd
  content before redirect lands. Bad UX, also easy to ship buggy
  protection that only hides UI but doesn't prevent data leaks.

### 3. CSRF double-submit — a 10-line fetch wrapper

**Decision:** single module `lib/api.ts` that wraps `fetch` and:

1. Ensures `credentials: 'include'`.
2. For mutating methods (POST/PATCH/PUT/DELETE), reads
   `atlas_csrf` cookie from `document.cookie` and adds
   `X-Atlas-CSRF` header.
3. Normalizes error shape: on non-2xx, reads `{error: {code, message}}`
   from the body, throws a typed `APIError` with the code as the
   discriminant.

Shape:

```ts
// lib/api.ts (sketch)
export async function api(path: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const headers = new Headers(init?.headers);
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
    const csrf = readCookie('atlas_csrf');
    if (csrf) headers.set('X-Atlas-CSRF', csrf);
  }
  const res = await fetch(`/api${path}`, { ...init, headers, credentials: 'include' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new APIError(body.error?.code ?? 'unknown', body.error?.message ?? res.statusText, res.status);
  }
  return res;
}
```

Every hook that talks to the backend goes through this. No
`fetch()` calls scattered across components. When the CSRF
contract changes (e.g., rotated token format) it's a one-line edit.

**Server-side fetches** (from server components): separate helper
`lib/api-server.ts` that reads `cookies()` from Next's server API
and forwards `Cookie: atlas_session=...` explicitly. Doesn't need
CSRF (server-side calls aren't subject to CSRF by definition).

### 4. Redirect after login — preserve `?next=`

**Decision: middleware appends, login page reads, login POST
success navigates.**

Concrete:

- Middleware redirects protected-path + no-cookie → `/login?next=%2Fme`.
- `/login` page reads `searchParams.next`, uses it as the post-login
  redirect target. Default when absent is `/me`.
- Post-login: the server sets the session cookie in its Set-Cookie
  response. The client's fetch wrapper doesn't need to read the
  cookie — the browser stores it automatically. Client then calls
  `router.push(nextPath)`.

Security notes:

- Sanitize `next`: must start with `/`, must not start with `//` (protocol-relative), must not be an external URL. Small regex.
- Don't blindly trust `next` to point at a valid route. If it 404s, the user lands on a 404 — acceptable.

### 5. Design integration

**Decision: stay inside the M0 design tokens. No new CSS.**

- Dark theme: `bg-bg-base`, `bg-bg-surface`, `text-primary`,
  `text-secondary`, `text-muted`, `accent`, `accent.dim`.
- Typography: Inter sans, JetBrains Mono mono.
- 8px spacing grid.
- Form inputs: match the existing Atlas aesthetic — subtle
  borders (`border.subtle`), rounded corners, no heavy shadows.
- Buttons: `bg-accent` for primary, ghost style for secondary.

**Explicit non-goals:**
- New component library (shadcn, Radix, etc.). Yes, eventually;
  not for 3 form pages and a profile display.
- Animation / transition polish. Functional first, polish later.

### 6. Eval / acceptance

No Playwright / RTL infra today — setting it up is its own slice.
For v1, two layers of coverage:

**Manual smoke (must pass before merge):**
- [ ] Visit `/` → landing page renders (unchanged).
- [ ] Visit `/me` anonymous → redirect to `/login?next=%2Fme`.
- [ ] `/login` form renders, error on wrong password, success on right.
- [ ] After login → lands on `/me`, shows your email + display name.
- [ ] Logout button → POST clears session, lands back on `/`.
- [ ] `/register` form: duplicate email shows error, valid submission logs you in.
- [ ] `/register` weak password → validation error surfaced.
- [ ] Deep-link `/me?next=/something` after register → redirects to `/something`.

**Automated (tiny, pragmatic):**
- Unit tests for the fetch wrapper (CSRF header injection logic,
  error coercion). Vitest — it's already in the Next.js 15 template
  if we enable it; if not, it's ~10 min setup.
- Unit test for the `next` sanitizer (`isSafeRedirect('/foo')` →
  true, `isSafeRedirect('//evil.com')` → false).

**Explicitly deferred:**
- E2E browser tests via Playwright — lives in the next UI slice
  once we have more than 3 pages to test.
- Accessibility audit — keyboard focus, ARIA. Real concern but one
  slice at a time.

### 7. Delivery surface + branch strategy

**Branch: `web/m7-auth-ui` (current branch).**

Merge pattern same as M4–M8: research doc first (this note),
implementation next, merge to main as a single `--no-ff` merge.

**Not behind a feature flag.** The routes are new (`/login`,
`/register`, `/me`) — they don't alter the landing page. Flipping
the merge to main immediately gates existing protected API
endpoints behind a real UI path. Low blast radius.

### 8. Risk assessment

#### 8.1 Next.js 15.1.x runtime quirks

We hit a `TypeError: reading 'aa'` earlier in this session on the
web container — a minified-runtime error that resolved with a
container restart. It's a known nuisance in 15.1.x. Mitigation:
pin to a specific patch version (15.1.3 is what M0 installed); if
we hit it again during this slice, upgrade to the latest 15.x
patch.

#### 8.2 SSR + cookies race

Next.js 15 App Router's `cookies()` is async in some contexts and
sync in others. Forwarding the incoming request's `Cookie` header
to a server-side fetch has a specific idiom (use `headers()` from
`next/headers`, not `document.cookie` — that's client-only). I'll
put one helper (`forwardedHeaders()`) in `lib/api-server.ts` and
use it everywhere; reduces the chance of getting the incantation
subtly wrong on one route and having auth silently not work.

#### 8.3 Public-facing gate still closed

My M5/M6/M7 research docs all said "public release waits on M4
Phase 3." Shipping this slice lets *someone who knows the URL* hit
register / login on `165.227.98.195:3000`. That's not a public
announcement, but it's functionally a private beta entry point.

Mitigation: don't announce the URL. Keep the registered user pool
small (you + whoever you explicitly invite). Add an HTTP Basic
auth layer at the Caddy level if you want a harder external gate.
Or add a feature flag env var (`ATLAS_REGISTRATION_OPEN=false`)
that 403s `/auth/register` unless set — simple invite-wall.

**None of these are required for this slice**; they're knobs to
consider before inviting more than a handful of users.

#### 8.4 Email validator strictness

We discovered during M7 smoke test that Pydantic's `EmailStr`
rejects `.test` / `.local` / `.internal` / `.example` TLDs because
email-validator marks them as reserved. Registration forms that
let users type in whatever will hit this. Surface the specific
error message in the UI, not just "invalid email" — the diagnosis
("that TLD is reserved, try a real one") is user-hostile if we
swallow it.

## Implications for Atlas

- **Apps touched:** `apps/web/` only.
- **New files:**
  - `apps/web/middleware.ts`
  - `apps/web/next.config.js` updated with `rewrites()` block.
  - `apps/web/lib/api.ts` + `apps/web/lib/api-server.ts`
  - `apps/web/lib/auth.ts` (session type, isSafeRedirect helper)
  - `apps/web/app/login/page.tsx`
  - `apps/web/app/register/page.tsx`
  - `apps/web/app/(protected)/layout.tsx`
  - `apps/web/app/(protected)/me/page.tsx`
  - `apps/web/components/LoginForm.tsx`, `RegisterForm.tsx`, `LogoutButton.tsx`
- **New env:** `INTERNAL_API_URL` set in `docker-compose.yml` web service.
- **No API changes.** Everything needed already lives in `/auth/*`.
- **No migration.** No schema touched.
- **HANDOFF update:** add an "atlas-web" milestone track showing
  this slice + the deferred follow-ups (drawings UI, viewer, chat,
  annotations, projects).

## Open follow-ups

- **web/m2-drawings-ui** — list + upload page. Needs an API client
  for `POST /drawings/upload` and `GET /drawings/{id}/status`
  polling. Medium effort (~3 days).
- **web/m2-viewer** — the hard slice. Sheet tile rendering +
  element bbox overlays. Likely a week of focused work. Can reuse
  OpenLayers / leaflet-style tile grid OR build a minimal
  canvas-based renderer. Decision for its own research doc.
- **web/m5-chat + web/m6-annotations** — both hang off the viewer.
  Sequenced after m2-viewer.
- **web/m8-projects** — project list + member management. Doesn't
  need the viewer.
- **Playwright E2E infra** — needed before any of the above can
  have real regression tests.

## Decision log entries to open

- **D-18 — atlas-web M7 auth UI architecture.** Same-origin via
  Next.js rewrites; three-tier auth check (middleware presence +
  server-component validation + client hooks); CSRF via a fetch
  wrapper; stay inside M0 design tokens.
