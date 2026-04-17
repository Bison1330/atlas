"""Interpreter implementations for the M5 Q&A service.

Two concrete :class:`Interpreter` implementations live here:

- :class:`ClaudeInterpreter` — calls the Anthropic API with
  ``tool_choice`` pinned to our ``classify_query`` tool so the
  model is forced to emit valid structured JSON (no free-form
  parsing).
- :class:`FakeInterpreter` — a dict lookup by question string;
  used in unit + route tests so nothing here touches the real API.

The system prompt (in :data:`SYSTEM_PROMPT`) is long and stable;
it's designed to be a prompt-cache hit across requests.

The real Claude call is *intentionally* lazy-imported so that the
``anthropic`` package is an optional dependency for dev envs
without an API key. Local tests + CI pass without it.
"""

from __future__ import annotations

from typing import Any

from app.services.qa import Interpreter, QueryInterpretation

# Default model. Haiku is ample for classification-style prompts;
# upgrade to Sonnet 4.6 only if eval shows interpretation errors.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


SYSTEM_PROMPT = """\
You are the query classifier for Atlas, a tool that extracts structured
building data from architectural drawings (walls, rooms, doors,
windows, columns). Your only job is to translate a user's natural-
language question about a drawing into a structured query by calling
the ``classify_query`` tool.

There are exactly 5 supported answer buckets. If the question does
not fit one, return ``bucket="unsupported"`` with a short
``unsupported_reason`` and a ``suggested_phrasing`` that *would*
fit, when obvious.

=== Buckets ===

1. **count** — "how many {kind} on {scope}".
   filter: {kind: wall|door|window|column|room|stair,
            ncs_major_group?: str, ncs_minor_group?: "EXTR"|"INTR"|...}

2. **quantity** — "total {length|area} of {kind}".
   filter: {kind: wall|room, metric: length|area,
            ncs_major_group?: str, ncs_minor_group?: str}

3. **rank** — "largest|smallest {kind} by {metric}".
   filter: {kind: room|wall, metric: area|length,
            direction: max|min}

4. **adjacency** — room-to-room connections via doors.
   filter: {query_type: "rooms_connected",
            room_a: "room 1"|"room 2"|..., room_b: same}
   OR     {query_type: "room_neighbors",
            room_a: "room 1"|"room 2"|...}

5. **lookup** — a single attribute of a specific element.
   filter: {kind: room, identifier: "room 1"|...,
            attribute: "area"}

=== Rules ===

- Rooms are identified as "room 1", "room 2", etc., ordered by
  descending area (so "room 1" is always the largest). If the user
  says "the largest room", prefer bucket=rank; if they say
  "room 1" explicitly, bucket=lookup.
- ncs_minor_group "EXTR" = exterior, "INTR" = interior.
- If the question is vague, multi-turn, requires reasoning beyond
  the 5 buckets (code-compliance, cost, design critique), or
  references data not present (drawing_context lists what's
  available), return bucket=unsupported.
- Never fabricate element IDs or counts. Only classify.
"""


TOOL_SCHEMA: dict[str, Any] = {
    "name": "classify_query",
    "description": "Emit the structured interpretation of the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "bucket": {
                "type": "string",
                "enum": [
                    "count", "quantity", "rank",
                    "adjacency", "lookup", "unsupported",
                ],
            },
            "filter": {
                "type": "object",
                "description": (
                    "Bucket-specific filter parameters. "
                    "See system prompt for the schema per bucket."
                ),
                "additionalProperties": True,
            },
            "unsupported_reason": {
                "type": "string",
                "description": "Present only when bucket=unsupported.",
            },
            "suggested_phrasing": {
                "type": "string",
                "description": (
                    "Present when bucket=unsupported AND a close-by "
                    "supported rephrasing is obvious."
                ),
            },
        },
        "required": ["bucket", "filter"],
    },
}


# ---------------------------------------------------------------------------
# Real Claude interpreter
# ---------------------------------------------------------------------------


class ClaudeInterpreter:
    """Anthropic-backed interpreter using forced tool use.

    Constructing this with ``api_key=None`` raises — the service
    layer checks the setting first and returns 503 before we get
    here, so reaching this constructor with no key is a bug.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 512,
    ) -> None:
        if not api_key:
            raise ValueError("ClaudeInterpreter requires a non-empty api_key")
        # Lazy import: keeps ``anthropic`` an optional dep for
        # environments without a key.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def interpret(
        self, question: str, drawing_context: dict[str, Any]
    ) -> QueryInterpretation:
        user_msg = (
            f"Drawing context: {drawing_context}\n\n"
            f"Question: {question}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "classify_query"},
            messages=[{"role": "user", "content": user_msg}],
        )
        # Tool-use forcing guarantees the first content block is a
        # tool_use block; if that assumption breaks we surface a
        # structured "unsupported" rather than crash.
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                args = block.input  # type: ignore[attr-defined]
                return _coerce_interpretation(args)
        return QueryInterpretation(
            bucket="unsupported",
            unsupported_reason="model returned no tool call",
        )


def _coerce_interpretation(args: dict[str, Any]) -> QueryInterpretation:
    bucket = args.get("bucket")
    allowed = {"count", "quantity", "rank", "adjacency", "lookup", "unsupported"}
    if bucket not in allowed:
        return QueryInterpretation(
            bucket="unsupported",
            unsupported_reason=f"unknown bucket returned by model: {bucket!r}",
        )
    flt = args.get("filter") or {}
    if not isinstance(flt, dict):
        flt = {}
    return QueryInterpretation(
        bucket=bucket,  # type: ignore[arg-type]
        filter=flt,
        unsupported_reason=args.get("unsupported_reason"),
        suggested_phrasing=args.get("suggested_phrasing"),
    )


# ---------------------------------------------------------------------------
# Fake interpreter — tests / eval-without-API-key mode
# ---------------------------------------------------------------------------


class FakeInterpreter(Interpreter):
    """Dict-lookup interpreter — question → QueryInterpretation.

    Unknown questions yield a ``bucket="unsupported"`` interpretation
    so tests can assert the service handles the default path too.
    """

    def __init__(self, mapping: dict[str, QueryInterpretation]) -> None:
        self._mapping = dict(mapping)

    def interpret(
        self, question: str, drawing_context: dict[str, Any]
    ) -> QueryInterpretation:
        key = question.strip().lower()
        for q, interp in self._mapping.items():
            if q.strip().lower() == key:
                return interp
        return QueryInterpretation(
            bucket="unsupported",
            unsupported_reason=f"fake interpreter has no mapping for: {question!r}",
        )
