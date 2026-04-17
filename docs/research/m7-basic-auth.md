# M7 — Basic authentication (thin slice)

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the smallest auth milestone that makes Atlas safe to deploy
publicly — and what deliberately waits until there's a concrete
need for it?

### Sub-questions

- Which of several candidate slices (email/password, OAuth-only,
  magic-link, share-links-only) gives the right
  cost/reach/complexity trade-off for first-release?
- What does the user + session data model look like?
- How do existing drawings transition to user ownership without
  data loss?
- What's the minimum security hardening needed at the API layer?
- What about *projects / teams / invitations / roles* — the
  richer features the original M7 brief lists?

## Why this matters

Opens **D-11, D-12, D-13.** Determines the first auth primitive
on the schema, the session model every future protected endpoint
will lean on, and the migration pattern for moving existing
unowned data under user control. Also sets the precedent — every
later collaboration feature (projects, teams, invites, RBAC)
inherits whatever this milestone lands.

---

## Position

Opinionated. Each section ends with a decision.

### 0. Pushback on scope

The original brief bundles six capabilities: auth, user model,
projects, team collaboration, migration, security. That's five to
ten engineering-months of work across at least three distinct
product surfaces. Shipping it as one milestone repeats a pattern
the project's own feedback notes warn against: "parallel tracks
tend to leave both at 80%" (`feedback_milestones.md`).

The milestone column in `HANDOFF.md` already implicitly splits
this: **M7 was "Team collaboration (projects, roles)"**. Auth is
the *precondition* for that work, not the work itself. The right
move is to name this milestone honestly.

**Decision: M7 = basic authentication (accounts + drawing
ownership). Projects / teams / invitations / roles become M8.**

A one-milestone-per-concern breakdown:

| M   | Scope                                  | Depends on |
|-----|----------------------------------------|------------|
| M7  | Email+password auth, `owner_id` on drawings, per-user isolation | — |
| M7.1 | Password reset + email verification    | M7         |
| M8  | Projects (drawings → project), per-project membership | M7 |
| M8.1 | Invitations, roles (admin/member/viewer) within a project | M8 |
| M9  | OAuth (Google/GitHub) as alternative to password | M7 |
| M10 | Public read-only share links (scoped tokens) | M7 |

Keeping these separate lets each ship end-to-end; collapsing them
leaves all of them at 80%.

### 1. Pick the auth slice

Candidates considered:

| Option | Cost | Reach | Friction | Verdict |
|--------|------|-------|----------|---------|
| **A: Email + password, cookie sessions, Redis-backed** | 1 new table, 4 endpoints, well-tested libs | Universal (any email works) | Low (no 3rd party) | **Pick this.** |
| B: OAuth-only (Google/GitHub) | 0 password handling, 1 provider integration, stack of callback plumbing | Excluded users without those accounts | Low (click-through) | Layer in later as M9 |
| C: Magic-link (email-only, no passwords) | No hashing; email-sending infra *required* | Universal but depends on inbox | High (mail latency) | Email infra is its own project — defer |
| D: Share-links-only (no accounts) | Trivial | N/A — not really auth | N/A | Complementary, not primary; add as M10 |

**Decision: A (email + password, cookie sessions, Redis-backed).**

Rationale:

- **Self-contained.** No third-party dependency, no outbound email
  delivery, no OAuth callback plumbing on day one. Everything
  needed lives in the existing Postgres + Redis stack.
- **Well-worn patterns.** Argon2id password hashing, HTTP-only
  SameSite cookies, server-side session store. Zero novelty
  risk — bog-standard web auth.
- **Composes cleanly with later additions.** M9 (OAuth) adds
  login methods; it doesn't reshape the user table. M8 (projects)
  adds a membership table; it doesn't change auth. Nothing here
  forecloses future work.

### 2. User + session data model

One new table + one Redis prefix.

```
users
  id              UUID PK
  email           VARCHAR(255) UNIQUE NOT NULL  CHECK email ~ simple email regex
  email_verified  BOOLEAN NOT NULL DEFAULT FALSE
  password_hash   VARCHAR(255) NOT NULL          (argon2id output including params)
  display_name    VARCHAR(120)                   NULL
  is_active       BOOLEAN NOT NULL DEFAULT TRUE
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  last_login_at   TIMESTAMPTZ                    NULL

INDEX users(email)   -- for login lookup
```

Sessions live in Redis, not Postgres:

```
key:    atlas:session:{session_id}
value:  JSON {user_id, created_at, ip_seen, ua_seen}
TTL:    14 days (sliding — extends on use)
```

Why Redis over DB sessions:

- **Revocation is a single DEL.** No GC job; TTL handles expiry.
- **Redis is already in the stack.** No new infrastructure.
- **Read-path cost is cheap** (one GET per request on protected
  routes, amortized by the request round-trip).

Session IDs are opaque 256-bit tokens (`secrets.token_urlsafe(32)`)
signed with a server-side secret via `itsdangerous`
(BadSignature → 401). No JWT — we actively *want* revocation to
be cheap, and JWT's revocation story is notoriously painful.

### 3. Password policy + hashing (D-12)

**Hash:** argon2id via `argon2-cffi`. Parameters: 64 MiB memory,
3 iterations, 4 parallelism (OWASP password-storage cheatsheet
recommendation as of late-2025; the cheatsheet's knob order is
stable between minor revisions, so we track it via a comment in
the config).

**Policy:**

- Minimum 10 characters. No max (accept passphrases).
- No composition rules (numbers/symbols/etc.) — NIST SP 800-63B
  has been explicit about dropping these for years.
- No periodic rotation. NIST again.
- Check against the top-1000 most-common-passwords list (ship the
  list in-repo; it's ~10 KB of text).

**Rejected alternatives:**

- bcrypt — fine, but the 72-byte silent-truncation behavior is a
  footgun and argon2id is the current recommendation.
- scrypt — less ecosystem; not worth the divergence.
- Plain sha256 + salt — no.

### 4. Cookie / session mechanics

Cookie name: `atlas_session`.

Attributes:

- `HttpOnly` (JS can't read it)
- `Secure` (HTTPS only — Caddy already terminates TLS in prod)
- `SameSite=Lax` (sent on top-level GETs, blocked on third-party POSTs)
- `Path=/`
- Max-Age: 14 days on login; refreshed on each use (sliding)

CSRF:

- Use Starlette's request-header check: all state-changing
  endpoints (POST/PATCH/DELETE) require `X-Atlas-CSRF` header
  containing a value the login response handed back.
- Double-submit pattern: the CSRF token is also stored in a
  readable (non-HttpOnly) cookie so the Next.js app can echo it
  on every mutation.
- Rejected: synchronizer token pattern (requires server-side
  per-request state; overkill for our traffic).

### 5. Drawing migration strategy (D-13)

Atlas has existing drawings in prod/dev that were uploaded before
any auth existed. Three options considered:

| Option | What it does | Verdict |
|--------|--------------|---------|
| Wipe and restart | Drop every drawing; start fresh after M7 | Dev-only; unacceptable for real data |
| Null-owner legacy | Add `owner_id NULLABLE`; pre-M7 rows stay NULL; new rows require it | **Pick this.** |
| Single "legacy" user | Create one synthetic user, assign every existing drawing | Loses the ability to claim later; forces an immediate owner |

**Decision: nullable `owner_id` on drawings, with an explicit
"unclaimed" semantic.**

Schema:

```
ALTER TABLE drawings
  ADD COLUMN owner_id UUID NULL
    REFERENCES users(id) ON DELETE RESTRICT;

CREATE INDEX ix_drawings_owner_id ON drawings(owner_id);
```

Access rules:

- Unauthenticated requests: only `/health`, `/auth/register`,
  `/auth/login` work. Everything else 401s.
- Authenticated requests: you see drawings where
  `owner_id = :self OR owner_id IS NULL` (the legacy-claimable
  pool) — BUT you can only mutate / ask questions / annotate
  drawings you own.
- `POST /drawings` (upload) sets `owner_id = current_user.id`.
- `POST /drawings/{id}/claim` — an authenticated user can claim a
  legacy drawing iff `owner_id IS NULL`. First-come-first-served;
  admin-override path can land later.

Why nullable: lets self-hosted deployments hang on to their
existing data through the migration. Drops the requirement for a
one-off bulk-assignment script. The "claim" endpoint gives users
a documented path to take ownership.

### 6. API surface

New:

```
POST   /auth/register    {email, password, display_name?}       → 201 UserOut (also logs in)
POST   /auth/login       {email, password}                       → 200 UserOut + Set-Cookie
POST   /auth/logout      ∅                                        → 204  (clears cookie, DELs session)
GET    /auth/me          ∅                                        → 200 UserOut (401 if not logged in)
POST   /drawings/{id}/claim  ∅                                    → 200 DrawingOut (400 if already owned)
```

Updated — every existing protected endpoint gets a dependency:

- `POST/GET/DELETE /drawings/*`
- `POST /drawings/{id}/ask` (M5)
- `POST/GET/PATCH/DELETE /drawings/{id}/annotations` (M6)
- `GET /drawings/{id}/connectivity`, `/takeoffs`, `/elements`, etc.

The dependency is a FastAPI `Depends(current_user)` that reads the
session cookie + Redis, returns the user row or raises 401.

**Ownership check** is a second dependency layered on top:
`Depends(current_user_owns_drawing)` which resolves the drawing
id from the path and 403s if `drawing.owner_id != user.id` (null
owner_id special-cases for reads, not writes).

### 7. Rate limiting + basic abuse protection

Minimum bar for public deployment:

- **Login:** 5 failed attempts per `(email, ip)` per 15 minutes →
  return 429 with `Retry-After`. Backed by Redis counter with
  sliding window.
- **Register:** 3 per IP per hour. (Mitigates email-enumeration
  via timing but doesn't claim to prevent it.)
- **Every authenticated endpoint:** soft cap 60 req/min/user
  (generous; tightens later if abuse surfaces).

No WAF, no CAPTCHA, no bot detection — those are separate
projects. Caddy does baseline TLS hardening already.

### 8. Evaluation / acceptance

Pure pytest + Redis integration. No Claude, no geometry.

Target: ~25 tests.

- Register with valid payload → 201 + cookie set + user in DB.
- Register duplicate email → 409 conflict.
- Register weak password → 422.
- Register password in common-passwords list → 422.
- Register invalid email → 422.
- Login valid → 200, cookie set, `last_login_at` bumped.
- Login wrong password → 401 (constant-time latency verified at
  median).
- Login nonexistent email → 401 (same shape as wrong password so
  clients can't enumerate).
- Login 5 times bad → 429 on the 6th.
- Logout → 204; session gone from Redis; subsequent /auth/me → 401.
- /auth/me without cookie → 401.
- /auth/me with tampered cookie → 401.
- Upload without login → 401.
- Upload with login → 201 and drawing.owner_id = current user.
- GET /drawings sees own + null-owner drawings; not others'.
- PATCH someone else's annotation → 403.
- Claim null-owner drawing → 200 + owner_id set.
- Claim already-owned drawing → 400.
- Session expires after 14d of inactivity (integration with faked
  Redis TTL).
- Password reuse across login attempts *does* match (sanity).
- Password rehash on login detects outdated params (future-proofing).
- CSRF header missing on a mutating call → 403.
- CSRF header mismatched → 403.
- CSRF header matching the cookie → 200.
- Argon2id parameters in the hash string match the configured
  policy (regression test — catches accidental downgrades).

Acceptance for merging:

- [ ] Migration runs up + down cleanly.
- [ ] Every pre-M7 protected endpoint is now auth-gated (tests
  verify each returns 401 when called anonymously).
- [ ] Existing 134 API tests pass — updated to authenticate first.
- [ ] The M4 extraction eval, M5 Q&A eval (when API key present),
  and all the worker + atlas-core suites still pass.

### 9. Delivery surface

**API first, UI deferred.** Same pattern as M5, M6.

The UI debt is now real: Atlas has *three* pending UI slices —
M5b (Q&A chat), M6b (annotation anchors), and M7b (login /
account pages). My recommendation is to consolidate them into
one **viewer-app slice** after M7 API lands:

- Build the Next.js pages once: login, protected-route HOC,
  viewer shell, chat panel, annotation chips.
- Ships as a separate project ("atlas-web M2") rather than three
  small UI efforts.

This means M7 API ships without a UI. Demos continue to be
curl-based. That's acceptable because M7 *isn't* a user-facing
feature — it's infrastructure everything else sits on.

### 10. Risk assessment

#### 10.1 M4 Phase 3 still blocked

Every auth-protected endpoint still sits on top of an extractor
that's unverified on real drawings. Auth adds a layer of
credibility (anonymous users can't abuse the system) but doesn't
fix the underlying accuracy question. The `extraction_status:
"unvalidated_on_real_drawings"` flag continues to ship on M5 and
M6 responses.

#### 10.2 Accumulated UI debt

As of this milestone's planning: **three UI slices are deferred**
(M5b, M6b, M7b). This is tolerable for now (API-first shipping
pattern), but it compounds. Sooner or later a "consolidate the
frontend" milestone is required — this research doc doesn't try
to scope that. Flag it loudly in HANDOFF.

#### 10.3 Auth implementation pitfalls

Auth is a category of code where "mostly right" is still broken.
Specific pitfalls this design tries to head off:

- **Timing attacks on email enumeration.** Login latency is the
  same whether the email exists or the password is wrong — both
  paths call argon2.verify() with a dummy hash on the missing-email
  branch.
- **Session fixation.** New session ID generated on every login,
  not just reused. Existing Redis session on the same key is
  evicted.
- **Cookie scope.** `Domain=` attribute is unset so the cookie
  is scoped to the origin that set it (prevents subdomain
  leakage).
- **CSRF.** Double-submit token on every POST/PATCH/DELETE.
- **Common-password rejection.** Stops the easy failures. Not a
  substitute for rate limiting.
- **Secrets rotation.** Session-signing key lives in env var
  `ATLAS_SESSION_SECRET`; rotating it invalidates all sessions
  (by design — that's the point of a secret).

#### 10.4 What's explicitly NOT done in M7

Enumerated so nobody assumes these landed:

- Projects / teams / orgs.
- Invitations.
- Role system (admin/member/viewer) — everyone is just an owner
  of their own drawings.
- OAuth (Google / GitHub / Apple).
- Email verification (the boolean column exists; the verification
  flow doesn't).
- Password reset.
- 2FA / TOTP.
- Audit log.
- Admin dashboard.
- Per-organization billing / quotas.
- Session management UI ("log out all other devices").
- Account deletion / GDPR export.

Several of these are small follow-ups (password reset = 1 week of
work); several are their own milestones (teams = M8, projects =
M8, roles = M8.1, billing = M11+).

## Implications for Atlas

- **New migration:** `0005_users_and_owner_id.py` — creates
  `users` and adds nullable `owner_id` + index on `drawings`.
- **New model:** `User` in `atlas-db`.
- **New service / route / dep:** `apps/api/app/services/auth.py`,
  `apps/api/app/routes/auth.py`, plus
  `apps/api/app/core/auth_dep.py` for the FastAPI `Depends`
  helpers.
- **New package deps:** `argon2-cffi`, `itsdangerous`.
- **New settings:** `ATLAS_SESSION_SECRET` (required in prod),
  `ATLAS_SESSION_TTL_SECONDS` (default 14 days),
  `ATLAS_COMMON_PASSWORDS_PATH` (default points at in-repo file).
- **Existing routes updated:** every drawing-scoped endpoint gets
  an auth dependency. Tests all need a `logged_in_client` fixture.
- **HANDOFF update:** milestone table — M7 scope narrows,
  explicitly move teams/projects/invites/roles to M8 with a
  dependency arrow on M7.

## Open follow-ups

- **M7.1 password reset + email verification.** Needs outbound
  email infra (SES? Resend? postfix?). Smallish follow-up once
  we pick an email provider.
- **M8 projects + teams.** First real multi-user collaboration.
  Research note when we're ready.
- **M9 OAuth.** Separate auth provider integration; additive.
- **M10 share links.** Scoped read-only access without account;
  composes with M7.
- **UI consolidation.** M5b + M6b + M7b → one frontend slice,
  scheduled after M7 API is solid.

## Decision log entries to open

- **D-11 — M7 scope = basic auth only.** Projects / teams /
  roles / invitations / OAuth all move to later milestones.
- **D-12 — argon2id + cookie sessions in Redis.** Session IDs
  signed with `itsdangerous`. CSRF via double-submit cookie.
- **D-13 — Drawings get a nullable `owner_id` with a
  `POST /drawings/{id}/claim` endpoint for legacy data.** No
  bulk-assignment script; claim-on-first-use.
