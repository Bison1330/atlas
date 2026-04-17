# M5 — Design-Intent Q&A

**Status:** in progress (research pre-code)
**Owner:** Kevin
**Last updated:** 2026-04-17

---

## Question

What's the *smallest* version of "ask questions of a drawing and get
grounded, cited answers" that ships end-to-end on top of M1–M4 data,
and what deliberately stays out of scope?

### Sub-questions

- What's the first user story — the narrowest case that still has
  real value?
- What does a citation look like on the wire and in the UI?
- How do we measure whether an answer is correct?
- What's the delivery surface for the first iteration?
- What's the blast radius of M4's unvalidated real-drawing
  behavior on M5 answer quality?

## Why this matters

Closes **D-07** (to be logged): the shape of Atlas's Q&A contract.
Determines the first API endpoint, the response schema, and the
eval harness shape that M5's definition of done depends on. Also
sets the precedent for every future LLM-touching feature in Atlas —
if we get grounded-citation wrong here, every later feature
inherits the confusion.

---

## Position

This note is deliberately opinionated. Each section ends with a
concrete decision, not a menu. Alternatives that were considered
and rejected are noted.

---

## 1. Primary user story

**Decision: start with structured takeoffs-style queries over a
single drawing.** Examples:

- "How many exterior doors on this sheet?"
- "What's the total wall length on floor 1?"
- "Which room has the largest area?"
- "Is the living room adjacent to the kitchen?" *(uses M3 adjacency)*
- "What rooms does door #3 connect?" *(uses M3 hosting)*

**Why this first.** The structured answer already exists in the
DB; the LLM's job is narrow — parse natural language into a query
over elements/rooms/adjacencies, then format the answer with
citations. No rules engine, no IBC knowledge base, no
hallucination surface for numeric facts.

**Rejected alternatives:**

- *Code compliance ("Does this egress path meet IBC 1005.3?").*
  Needs a rules engine Atlas doesn't have. Real codes are
  jurisdiction-specific (IBC vs. local amendments vs. state
  supplements); building this without that infrastructure
  guarantees wrong confident answers.
- *Free-form design critique ("What's wrong with this layout?").*
  No ground truth; eval impossible; LLM hallucination
  unconstrained. Right product eventually, wrong starting point.
- *Cross-drawing comparison.* Every question in scope for the
  first iteration is single-drawing. Multi-drawing needs a
  different indexing approach; leave it for after single-drawing
  is solid.

### Answer-class taxonomy

Every answerable question in the first iteration falls into one of
these five buckets. Anything outside returns "I can't answer that
yet — here's what I can answer."

| Bucket        | Shape                                          | M-layer used     |
|---------------|------------------------------------------------|------------------|
| **Count**     | "How many {kind} on {scope}?"                  | M2 elements      |
| **Quantity**  | "Total {linear\|area} of {kind} on {scope}?"   | M2 elements + M3 takeoffs |
| **Rank**      | "Which room is {largest\|smallest\|…}?"        | M2 + M3          |
| **Adjacency** | "Is {A} next to {B}?" / "What connects X?"     | M3 connectivity  |
| **Lookup**    | "What's the area of {named room}?"             | M2 elements      |

Five buckets is enough that "what's in scope" is legible to users
in 30 seconds, and narrow enough that eval coverage is tractable.

## 2. Citation contract

**Decision.** An answer is a tuple:

```jsonc
{
  "answer": "There are 3 exterior doors on this sheet.",
  "answer_type": "count",
  "citations": [
    {
      "element_id": "9f3...",
      "sheet_id": "a12...",
      "kind": "door",
      "ncs_layer": "A-DOOR",
      "bbox": {"minx": 2.5, "miny": 0, "maxx": 3.5, "maxy": 1},
      "display_label": "Door at (3, 0)"
    },
    ...
  ],
  "query_interpretation": {
    "bucket": "count",
    "filter": {"kind": "door", "ncs_minor_group": "EXTR"}
  },
  "confidence": {
    "extraction_min": 0.87,
    "answer_certainty": "high"
  }
}
```

Why each field:

- **`citations[]` is the ground truth.** The answer text is
  generated *from* the citations, never the other way around. If
  there are 3 citations, the answer must say 3.
- **`element_id` + `bbox` + `sheet_id`** is the minimum a UI needs
  to highlight the source on a rendered sheet. No new tables; all
  fields already exist on `Element`.
- **`query_interpretation`** is the machine-readable version of
  what the LLM understood. It's what the eval harness asserts on —
  not the prose answer, which is fuzzy. If interpretation is right
  and the elements in the DB are right, the answer is right by
  construction.
- **`confidence.extraction_min`** is the *lowest* confidence of any
  cited element. If the extractor was shaky about any of the
  doors counted, the user sees that.
- **`confidence.answer_certainty`** is `high` when every cited
  element passed extraction validation and the query bucket is
  supported; `low` when elements are derived, interpolated, or the
  query touches a boundary case (e.g. "largest room" with two
  rooms within 1% area).

**Rejected alternatives:**

- *LLM writes the answer freely, citations are scraped from
  grounding text.* Inverts the trust model — prose drives truth.
  Wrong direction.
- *New `citations` table.* Premature; answers aren't
  persistent-first-class yet. Save as a JSON field on a `Query`
  row if/when we need history.
- *Sheet-coordinate overlays as the primary citation.* Needed for
  the UI eventually, but derivable from `bbox + sheet_id`. Don't
  bake rendering concerns into the API contract.

## 3. Evaluation approach

**Decision.** Curated Q/A pairs over the Tier 1 synthetic fixtures,
checked with pytest-style assertions against
`query_interpretation` and citation set equality — *not* against
prose.

Why: we know ground truth for every synthetic fixture (one-room
floor has 4 walls, three-room floor has R1-R3 + R2-R3 adjacencies,
etc.). The eval asserts:

1. The LLM's `query_interpretation.bucket` matches the expected
   bucket.
2. The citation `element_id` set matches the expected set.
3. The answer text contains the expected numeric answer (regex
   match — not exact string; LLM phrasing varies).

### Seed eval set — ~25 Q/A pairs

| Fixture                              | Q/A pairs |
|--------------------------------------|-----------|
| one-room-floor                       | 3  |
| two-room-floor                       | 4  |
| three-room-floor                     | 6  |
| insert-elements-floor                | 4  |
| polyline-window-floor                | 2  |
| spline-wall-floor                    | 2  |
| l-shaped-wall-floor                  | 3  |
| explicit-and-derived-room-floor      | 3  |

Covers all 5 answer-class buckets × at least 2 fixtures each.

**Rejected alternatives:**

- *LLM-graded eval (Claude grades Claude's own answers).* Too
  noisy for gating; fine as a secondary signal later.
- *Human eval as the primary bar.* Too slow for iteration; reserve
  for periodic quality audits.
- *Exact-string prose matching.* Flaky; LLMs paraphrase.

### What eval doesn't cover (honestly)

- Real-drawing behavior — see Section 5.
- Ambiguous questions ("is the house open-plan?"). No ground
  truth → not in eval → not in scope.
- Multi-turn context ("...and what about on floor 2?"). Single-turn
  only for the first iteration.

## 4. Delivery surface

**Decision.** `POST /drawings/{id}/ask` first. Synchronous. No UI.

```
POST /drawings/{drawing_id}/ask
Body: { "question": "How many exterior doors?", "sheet_id": "..." | null }
→ 200 { answer, citations, query_interpretation, confidence }
→ 400 { error: "unsupported_bucket", suggested_phrasing: "..." }
```

Why:

- **API first.** The contract is what needs iteration; the UI is a
  thin wrapper once the contract is stable. Eval + curl + pytest
  exercise the contract without Playwright.
- **Synchronous.** Typical LLM response is <5 s; no need for the
  RQ + websocket machinery yet. If tail latency becomes a problem
  we can add a `POST /ask-async` later without breaking the sync
  path.
- **Drawing-scoped.** Multi-drawing is out of scope; the URL makes
  that explicit.

**UI lands in a follow-up slice**, once eval shows the API answers
reliably. Sketch: a chat panel next to the sheet viewer, with
clicking a citation chip scrolling/zooming the viewer to the
cited `bbox`. That's M5b — not M5.

**Rejected alternatives:**

- *Async RQ job with WS progress events.* Overkill for one-shot
  questions at current latency.
- *Streaming responses.* Worth doing eventually for long answers;
  not in scope for the first iteration.
- *Global `/ask` without drawing_id.* Forces retrieval across all
  drawings — different problem. Keep it bounded.

### Implementation sketch (not a commitment)

1. New `apps/api/app/services/qa.py`:
   - `interpret(question) → QueryInterpretation` (Claude API call,
     narrow prompt — "classify into one of 5 buckets + extract
     filter params").
   - `execute(interpretation, drawing_id) → AnswerPayload` (pure
     SQL/in-memory over elements — no LLM).
   - `format(answer_payload, interpretation) → str` (second
     Claude call — "write a natural sentence from these facts").
2. Eval harness `scripts/eval_qa.py` — same pattern as
   `eval_extraction.py`; manifests under
   `tests/fixtures/qa-eval/*.yaml`.
3. Claude API usage — `claude-sonnet-4-6` for both calls is
   fine; `claude-haiku-4-5` probably enough for interpretation.
   Use prompt caching on the system prompt (rules + bucket
   taxonomy), which is long and stable.

### What this commits us to

- Two LLM calls per question (interpretation + formatting). Budget
  ~1k input tokens + 200 output each → ~$0.002/query on Sonnet,
  much less with caching. Acceptable.
- A second source of truth for element facts: the DB's view of
  what's in a drawing *is* the answer. Any future "richer context"
  (floor levels, user corrections, cross-drawing relationships) has
  to flow through this service or users will get inconsistent
  answers across endpoints.

## 5. Risk assessment — M4 validation gap

**The gap.** M4 Phase 1 + 2 code is tested on 8 synthetic DXF
fixtures. Phase 3 (real-drawing validation) is blocked on
procurement — no Revit, Archicad, or real permit PDF samples exist
in the corpus. See [`m4-phase3-procurement.md`](./m4-phase3-procurement.md).

**What that means for M5.** Every M5 answer is grounded in M2's
extraction output. If the extractor mis-classified or missed
elements on a real drawing:

- `answer: "There are 3 exterior doors"` is *confidently wrong*
  when the real count is 5 and the extractor dropped two INSERT
  doors that used an unusual block naming convention.
- `query_interpretation` looks right, `citations` are internally
  consistent, `confidence` is high — but the answer is built on
  sand. This is the worst failure mode for a user-facing feature.

**Mitigations in the M5 design:**

1. **`confidence.extraction_min` in every response.** Surfaces the
   weakest-cited-element's confidence. If any cited door has
   confidence 0.6, the user sees it.
2. **Explicit "answered from N elements" line in the formatted
   answer.** "Found 3 exterior doors (extracted from the DXF,
   extractor version 0.1.0)." Puts the data lineage in front of
   the reader.
3. **No extrapolation beyond what was extracted.** The service
   never answers "there should be N doors for a room this size" —
   only what's literally in the DB.

**What mitigations can't fix.** If the extractor silently drops an
entity type, the service literally cannot cite it. The only real
fix is M4 Phase 3 sign-off on real files. Until then:

- Document the gap in the API response (`meta.extraction_status:
  "unvalidated_on_real_drawings"`) until a Tier 2 eval passes.
- Gate public-facing M5 (web UI, external demo) on Phase 3
  procurement + eval. Internal/synthetic use is fine.

**Concrete pre-M5-ship checklist:**

- [ ] M5 API returns `meta.extraction_status` honestly.
- [ ] Seed eval (~25 Q/A pairs) passes on synthetic fixtures.
- [ ] At least one Tier 2 fixture (Revit export) is on disk and
  passes extraction eval (Phase 3 sign-off) **before** any M5 UI
  ships externally.

The second bullet is achievable now; the third is procurement-gated.

## Implications for Atlas

- **New API service:** `apps/api/app/services/qa.py` + route
  `/drawings/{id}/ask`. No new DB tables in the first iteration.
- **New dev dependency:** `anthropic` SDK in `apps/api`. Environment
  variable `ANTHROPIC_API_KEY`; missing key → service returns 503
  with a clear message so local dev without credentials still
  works for everything else.
- **New eval harness:** `scripts/eval_qa.py` patterned on
  `eval_extraction.py`.
- **Citation surface in the web app (M5b).** Thin — renders
  `citations[]` as chips that link to viewer bboxes.
- **Nothing to change in M2/M3/M4.** The citation contract consumes
  existing `Element` / `Sheet` / `ElementSource` fields.

## Open follow-ups

- **LLM choice.** Haiku 4.5 for interpretation, Sonnet 4.6 for
  formatting is the working hypothesis; needs latency + accuracy
  benchmarking once the service exists. Opus 4.7 is overkill for
  the narrow query-parse task.
- **Rate limiting / cost controls.** Not urgent pre-public; worth
  sketching before M5b UI so we don't ship a "spend the API
  budget by mashing the chat button" feature.
- **Caching.** The `(drawing_id, question_hash)` → answer cache is
  trivial and high-value once the answer is deterministic; hold
  until after the first iteration so we know what "deterministic"
  means in practice.
- **Multi-turn.** Not in scope for M5. Worth noting what the
  minimum schema extension would be (`conversation_id` + prior
  turn context) so we don't design ourselves into a corner.

## Decision log entries to open

- **D-07 — M5 Q&A contract.** Record the answer-payload shape, the
  5-bucket taxonomy, and the "citations drive answer, not the
  other way" constraint. Status: decided by this note.
- **D-08 — M4 → M5 sequencing.** Record the decision to proceed
  with M5 on synthetic-only extraction, gated on Phase 3 for any
  external release. Status: needs user confirmation.
