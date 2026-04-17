# atlas-web M5 — Q&A chat panel

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the thinnest slice of a Q&A chat UI that shows the M5 API
off honestly — grounded answers, real citations, extraction-status
caveats — without committing to live-editing the viewer every time
a citation chip is clicked?

### Sub-questions

- Where does the chat panel live on the existing
  `/drawings/[id]` page — right sidebar, bottom drawer, separate
  route?
- How do citation chips behave on click — zoom the viewer to the
  element's bbox, or display metadata inline and defer the
  viewer interaction?
- How are the four distinct API response shapes (supported
  bucket, unsupported question, 503 no-key, 401/429 auth-layer
  error) rendered without shipping four special-case UIs?
- How is the `unvalidated_on_real_drawings` meta flag surfaced so
  users see the M4 Phase 3 caveat at the right moment?
- Is chat history persisted or session-only?

## Why this matters

Opens **D-20** (chat UX shape + citation behaviour). This is the
single most distinctive capability on the roadmap — "ask questions
of a drawing, get grounded cited answers" — and the slice that
most changes what a user thinks Atlas does. Get the first
touch wrong and every subsequent feature has to rebuild trust.

---

## Position

Opinionated. Each section ends with a decision.

### 1. Slice choice — sidebar panel, citation-as-metadata, session-only history

The ask bundled chat + citation linking + real-time feel + error
modes. Separating them:

| Option | In v1 | Why |
|---|:-:|---|
| Sidebar chat panel on `/drawings/[id]` | ✓ | consistent with ElementInspector, doesn't cover the drawing |
| Bottom drawer | ✗ | covers drawings on tall monitors, harder to read answers alongside the plan |
| Separate `/ask` route | ✗ | decouples chat from the drawing context it needs |
| Citation click → zoom+highlight viewer | ✗ | touches `SheetCanvas` state we don't currently expose; own slice |
| Citation click → show metadata inline | ✓ | minimal, informative, unlocks the viewer interaction for a follow-up |
| Persist chat history | ✗ | needs a new DB table; session-only is enough for the demo |
| Streaming responses | ✗ | API is synchronous (<5s); spinner is enough |
| Multi-turn context | ✗ | M5 API is single-turn; adding on the client means false context |
| Example-question empty state | ✓ | 5 buckets means most users need a prompt to know what to ask |

**Decision: sidebar panel, citation-as-metadata, session-only history.**

### 2. Panel layout

Right sidebar on the existing drawing detail page. Collapsible
(chevron toggle) so users on narrow monitors can hide it. When
expanded, grabs ~360px of width from the viewer area.

```
┌─────────────────────────────────────┬──────────────────┐
│                                     │  Q&A    [×]      │
│                                     │  ─────────────   │
│        SheetCanvas                  │  [caveat banner] │
│        (existing viewer)            │                  │
│                                     │  > how many      │
│                                     │    exterior doors│
│                                     │                  │
│                                     │    Found 3 walls │
│                                     │    [chip][chip]..│
│                                     │                  │
│                                     │  [input box    ▶]│
└─────────────────────────────────────┴──────────────────┘
```

Header carries the panel title, a close/collapse chevron, and
— critically — the extraction-status caveat banner. Scrollable
message list fills the middle. Input box pinned to the bottom.

**Rejected:** tabbed sidebar (Q&A / Elements / Takeoffs) — too
much UI state to manage; the ExtractionsSection already lives
below the viewer, not in the sidebar. Keep sidebars single-purpose
for now.

### 3. Citation chip behaviour (D-20-A)

**Decision: citation chips are inert metadata in v1.** Each chip
displays kind + NCS layer (e.g. "wall · A-WALL-EXTR"). Hover
reveals the bbox and display label from the API. **Click does
nothing** in v1 except maybe expand to show more detail inline.

**Why not zoom-to-viewer:** `SheetCanvas` manages its own
OpenSeadragon viewport internally and doesn't expose an
imperative `focusBbox(...)` handle. Adding one means touching the
viewer state model, which is its own research task — the
"highlighted element" pattern is also needed for
`ElementInspector` one day, for M6 annotations, and for project
overlays. Defer all of those to a single **`web/m2-viewer-focus`**
slice that lands the primitive once.

v1 chip behaviour still demonstrates grounding — users see which
specific elements the answer is based on, their layers, and their
positions. That's the core contract of M5; the zoom-and-highlight
is polish.

### 4. Response-shape handling

The API returns four distinct shapes. Plan for one renderer that
branches on `answer_type`:

| `answer_type` | Render |
|---|---|
| `count` / `quantity` / `rank` / `adjacency` / `lookup` | prose from `answer` + citations as chips |
| `unsupported` | prose ("I can't answer that yet — …") + suggested_phrasing rendered as a clickable "try: X" pill that pre-fills the input |
| HTTP 503 `llm_unavailable` | inline warning in place of an answer: "Q&A is unavailable — an administrator hasn't set ANTHROPIC_API_KEY." |
| HTTP 401 / 429 | 401 auto-redirects to login via existing fetchApi wrapper; 429 shows a specific "rate limited — try again shortly" message |

Every answer regardless of type carries two badges:

- **Confidence badge** from `confidence.answer_certainty`
  (high/medium/low). Shown in subtle text.
- **Extraction status caveat** from `meta.extraction_status`.
  When `"unvalidated_on_real_drawings"` (today's default), a
  persistent small warning in the panel header reads
  "Extraction is unvalidated on real CAD files." Links to
  `docs/research/m4-phase3-procurement.md` in the GitHub repo
  (or, in the product-facing eventual future, to an in-app
  explainer page).

**Rejected:** hiding the extraction-status caveat unless the
user explicitly asks for it. The whole research-doc thread from
M5 onwards said this flag should be unavoidable in user surfaces.
Don't bury it.

### 5. Empty state — examples per bucket

Before any question has been asked, the message area shows:

```
Ask about this drawing.

Try questions like:
  • How many exterior doors are there?      (count)
  • What's the total wall length?           (quantity)
  • Which is the largest room?              (rank)
  • Is the living room connected to the     (adjacency)
    kitchen?
  • What's the area of room 1?              (lookup)

Answers are grounded in the extracted elements.
```

Click any example → pre-fills the input box (doesn't auto-submit).

Why: the 5-bucket taxonomy is legible *in the research doc* but
invisible to a first-time user. Telling them what shape of
question works removes the "why did I just get an `unsupported`
response" friction.

### 6. Chat history data model (client-side only)

```ts
type ChatEntry =
  | { role: 'user'; content: string; id: string }
  | { role: 'assistant'; payload: AskResponse; id: string }
  | { role: 'system'; variant: 'error'; code: string; message: string; id: string };
```

Kept in a `useReducer` store local to the panel component. Drops
on page navigation/refresh. A future slice (`web/m5-chat-history`)
can add persistence when users ask for it — the API would need a
new table + endpoints, scope bigger than this slice.

### 7. API client shape

New in `lib/api.ts`:

```ts
export interface AskCitation {
  element_id: string;
  sheet_id: string;
  kind: string;
  ncs_layer: string | null;
  bbox: { minx: number; miny: number; maxx: number; maxy: number } | null;
  display_label: string;
}

export interface AskResponse {
  answer: string;
  answer_type: 'count'|'quantity'|'rank'|'adjacency'|'lookup'|'unsupported';
  citations: AskCitation[];
  query_interpretation: {
    bucket: string;
    filter: Record<string, unknown>;
    unsupported_reason: string | null;
    suggested_phrasing: string | null;
  };
  confidence: {
    extraction_min: number | null;
    answer_certainty: 'high' | 'medium' | 'low';
  };
  meta: {
    source_id: string | null;
    extraction_status: string;
    interpreter_model: string | null;
  };
}

export async function askDrawing(
  drawingId: string,
  question: string,
  opts?: { signal?: AbortSignal },
): Promise<AskResponse> { ... }
```

Routes through `fetchApi` so it inherits session + CSRF (POST is
mutating). Errors surface as `ApiClientError` with `code` set to
`llm_unavailable` / `rate_limited` etc.; the chat renderer
switches on `code`.

### 8. Eval / acceptance

**Manual smoke (must pass before merge):**
- [ ] `/drawings/[id]` renders with the sidebar panel collapsed
  by default; chevron expands it.
- [ ] Expanded panel shows the caveat banner and example questions.
- [ ] Sending a question hits the API and renders either an
  answer with citations, an unsupported message, or a 503.
- [ ] 503 rendering is clear about what to do ("admin needs to
  set ANTHROPIC_API_KEY").
- [ ] Citation chips show the element's kind and NCS layer.
- [ ] Extraction-status caveat is visible in the header at all
  times when Q&A is usable.
- [ ] Clicking a suggested_phrasing pill on an unsupported
  response pre-fills the input box.
- [ ] Works on the tiny `/drawings` fixture drawing (the one
  seeded during the last slice smoke test).

**Automated:**
- Defer. Playwright infra still doesn't exist; the API-side pytest
  suite already covers the response shapes. Chat rendering is
  pure-presentation and low-logic.

### 9. Delivery surface

Single branch `web/m5-chat`. Files:

- `apps/web/lib/api.ts` — new `askDrawing()` + types.
- `apps/web/components/chat/ChatPanel.tsx` — the sidebar.
- `apps/web/components/chat/MessageList.tsx` — scrollable stack.
- `apps/web/components/chat/AnswerCard.tsx` — renders one response
  (prose + confidence + citations).
- `apps/web/components/chat/CitationChip.tsx` — the metadata chip.
- `apps/web/components/chat/QuestionInput.tsx` — textarea + send.
- `apps/web/components/chat/ExamplePrompts.tsx` — the empty state.
- `apps/web/app/(protected)/drawings/[id]/page.tsx` — wire the
  panel in (existing page).

No API changes. No migration.

### 10. Risk assessment

#### 10.1 M4 Phase 3 gate is more visible now

Shipping this slice puts the "extraction may be wrong" caveat in
front of the first person who types a question. That's working
as intended — the research doc from M5 said this should be
unavoidable. Naming it here just to confirm we're not softening
the message: the caveat banner is *not* hidable.

#### 10.2 Users will try hard questions and get "unsupported"

The 5-bucket taxonomy handles structured queries. A reasonable
person will try "does this layout comply with IBC 1005?" which
returns `unsupported`. The `suggested_phrasing` hook is the only
mitigation — and it only helps when the LLM actually proposes a
reasonable rephrase. When it doesn't, we fall back to a generic
"I can't answer that yet" message. Users may assume Atlas is
broken rather than correctly-scoped. The example-questions empty
state is the primary defence; if eval shows this isn't enough,
we add an on-unsupported "Here's what I *can* answer" link.

#### 10.3 Cost drift without a rate limit

Each question is ~1k in + 200 out tokens on Claude, so ~$0.002
per query on Sonnet (less on Haiku). No per-user rate limit
today beyond the M7 session rate limits (which are auth-focused,
not Q&A-focused). If someone authenticated spams the endpoint
they can burn ANTHROPIC_API_KEY budget.

**Mitigation:** add a 20-per-minute-per-user Q&A rate limit on
the API side. One-line addition to the ask route. Call it a
v1 shipping requirement — not a future slice. I'll include it
in the implementation even though it's technically an API change
(small enough to ride along).

#### 10.4 Panel state vs. viewer state drift

The chat panel lives *next to* the viewer. Both can have "active
drawing" concepts. They should agree — if the user switches
sheets in the viewer, the answer citations don't auto-follow
(citations are drawing-scoped, not sheet-scoped, which matches
the API). A citation's `sheet_id` is information we surface in
the chip tooltip but don't use to change viewer state in v1.
When `web/m2-viewer-focus` lands, clicking a citation will jump
to its sheet + zoom to bbox.

## Implications for Atlas

- **New API rate limit** — 20/min/user on `/drawings/{id}/ask`.
  Uses the existing `app/core/rate_limit.py` primitive. One pytest
  test for the 429 path.
- **New web components** — 6 small components under
  `apps/web/components/chat/`.
- **Existing page update** — `/drawings/[id]` layout shifts
  slightly to accommodate the right sidebar.
- **No new env vars.** Uses the already-set `ANTHROPIC_API_KEY`.
- **Existing extraction / viewer components** unchanged.

## Open follow-ups

- **web/m2-viewer-focus** — imperative `focusBbox(sheetId, bbox)`
  handle on `SheetCanvas`. Unblocks citation-click-to-viewer here,
  element-click-in-inspector, and M6 annotation anchoring.
- **web/m5-chat-history** — persistence. New `chat_sessions` +
  `chat_messages` tables. API endpoints for list/get/delete.
- **web/m5-multi-turn** — client-side context carryover (send
  last N turns with each new question). Needs prompt tuning.
- **Per-project Q&A** — ask across every drawing in a project.
  Context-window budgeting matters. Separate research note.

## Decision log entries to open

- **D-20-A — chat citation chips are inert metadata in v1.**
  Zoom-to-viewer defers to `web/m2-viewer-focus`.
- **D-20-B — chat history is session-only (no persistence).**
  Persistence adds a new DB table + endpoints; revisit when users
  ask for it.
- **D-20-C — ask endpoint gains a per-user rate limit** (20/min).
  Protects ANTHROPIC_API_KEY budget; included in this slice.
