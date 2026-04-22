"""V1 kitchen intake — the Opus conversation that produces a KitchenBrief.

Session 1 of the V1 kitchen plan. Two concrete intake implementations
and one protocol:

- :class:`KitchenIntake` — the protocol routes depend on.
- :class:`ClaudeKitchenIntake` — Anthropic-backed Opus interview.
- :class:`FakeKitchenIntake` — scripted responses for tests.

The LLM speaks with two tools available:

- ``update_brief(field_updates)`` — merged into ``extracted_fields``.
- ``complete_brief(summary)`` — flips the brief's status to
  ``complete`` and signals the intake is done.

The route layer persists everything. This service is pure
orchestration against the Anthropic SDK + a system prompt, with no
DB or Redis dependencies, so it's trivial to swap for a fake in tests.

See ``docs/v1-kitchen-architecture.md`` §6 for the prompt skeleton
this module expands on and §2 for the KitchenBrief schema the LLM
populates via ``update_brief``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Flagship Opus per the architecture commitment. Intake quality
# dominates the rest of the pipeline, so the cost lift over Sonnet
# is acceptable — Kevin's guidance: per-design LLM budget does not
# include renders, so don't micro-optimize here.
OPUS_MODEL = "claude-opus-4-7"

# Max tokens per turn. 1024 is comfortable for "1–3 short paragraphs"
# plus one or two tool calls. Too small risks truncation mid-tool-use.
MAX_TOKENS = 1024


SYSTEM_PROMPT = """\
You are Atlas, an AI kitchen designer helping a homeowner or small business owner plan their kitchen project. Your role in this conversation is to interview the user to build a complete, structured brief of their project so you can design candidate kitchen layouts for them.

Required fields to extract (you must have confident values for all before the brief is complete):

PROJECT SCOPE:
- scope_type: "remodel" | "new_build" | "addition"
- kitchen_layout_goal: "galley" | "L-shape" | "U-shape" | "island" | "peninsula" | "open_concept" | "unsure"
- primary_purpose: "family_daily_cooking" | "entertaining_focused" | "minimal_use" | "professional_chef" | "mixed"

CURRENT SPACE (if remodel/addition):
- approximate_dimensions: width_ft and length_ft (both required)
- existing_features_to_keep: free text
- existing_features_to_change: free text
- load_bearing_walls_known: "yes" | "no" | "unsure"
- plumbing_locations_known: "yes" | "no" | "approximate"

WHAT THE USER WANTS:
- style_direction: one of [modern, traditional, farmhouse, transitional, contemporary, industrial, scandinavian, mixed]
- must_have_features: array of strings (e.g., "island with seating for 4", "double oven", "large pantry")
- dealbreakers: array of strings
- appliance_priorities: which appliances matter most to upgrade
- budget_range: low_usd and high_usd (try to get a range even if the user is hesitant)

CONSTRAINTS:
- location_address_or_zip: needed for code + cost lookups; okay to start with zip only
- timeline: "asap" | "3_months" | "6_months" | "flexible"
- hoa_or_historic_district: "yes" | "no" | "unsure"
- accessibility_needs: free text or "none"

CONVERSATION RULES:

- Ask 1-2 questions at a time, never a wall of questions.
- Acknowledge what the user said before asking the next thing.
- Use plain language. Avoid jargon. Never say "NKBA," "IRC," "egress," or "envelope" to the user.
- If the user says something impossible ("I want a 20-foot island in a 10-foot kitchen"), push back gently with specifics.
- If the user is hesitant on budget, offer ranges ("Most kitchen remodels run between X and Y in your area — does that sound right?").
- If the user's first message is very detailed, extract everything you can and confirm rather than re-asking.
- After every user message, you silently update your internal understanding of their project.

OUTPUT FORMAT:

Every response has two parts:

1. A conversational message to the user (warm, helpful, 1-3 short paragraphs max).
2. A structured update to the brief fields you were able to extract or update from the most recent exchange, using the `update_brief` tool.

WHEN TO COMPLETE:

When you have confident values for all REQUIRED fields above, call the `complete_brief` tool with your final summary. Your conversational message to the user says "I have everything I need to design your kitchen. Let me put together three options." Do not ask any more questions after calling this tool.

TONE:

You are on the user's side. Your job is to help them get a great kitchen without getting ripped off by bad information or bad contractors. You're a knowledgeable friend, not a salesperson.
"""


UPDATE_BRIEF_TOOL: dict[str, Any] = {
    "name": "update_brief",
    "description": (
        "Merge newly extracted or confirmed fields into the user's "
        "kitchen brief. Call this every turn that produces new "
        "structured knowledge. Send only the fields you learned this "
        "turn — the server merges with whatever the brief already "
        "contained. Nested objects (like approximate_dimensions) "
        "replace the whole object, not individual keys."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "field_updates": {
                "type": "object",
                "description": (
                    "Partial KitchenBrief. Keys must match the "
                    "schema listed in the system prompt. Skip "
                    "fields you don't yet know — don't guess."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["field_updates"],
    },
}


COMPLETE_BRIEF_TOOL: dict[str, Any] = {
    "name": "complete_brief",
    "description": (
        "Call exactly once, when every required field is filled with "
        "a confident value. This flips the brief's status to "
        "'complete' and stops the intake conversation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "object",
                "description": (
                    "A short structured recap of the project you "
                    "just scoped. At minimum include scope_type, "
                    "kitchen_layout_goal, budget_range, and "
                    "style_direction. Free-form otherwise — this "
                    "is a human-readable confirmation, not the "
                    "canonical brief state."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["summary"],
    },
}


TOOLS: list[dict[str, Any]] = [UPDATE_BRIEF_TOOL, COMPLETE_BRIEF_TOOL]


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeTurnResult:
    """One turn of Atlas's side of the intake conversation.

    Both ``field_updates`` and ``is_complete`` are derived from the
    tool calls the model made — the service normalizes whatever mix
    of tool_use blocks + text blocks came back into something the
    route can persist without re-parsing the Anthropic response.
    """

    assistant_message: str
    field_updates: dict[str, Any] = field(default_factory=dict)
    is_complete: bool = False
    completion_summary: dict[str, Any] | None = None
    model: str = ""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class KitchenIntake(Protocol):
    """Interface every intake implementation satisfies.

    ``messages`` is the Anthropic-style conversation history the
    caller has accumulated — the service neither loads nor saves
    state, so tests can script exact inputs without a DB.
    """

    def send_turn(self, messages: list[dict[str, Any]]) -> IntakeTurnResult: ...


# ---------------------------------------------------------------------------
# Real Claude interpreter
# ---------------------------------------------------------------------------


class ClaudeKitchenIntake:
    """Opus-backed intake with tool-use for structured extraction.

    We don't pin ``tool_choice`` to a specific tool (as qa_interpreter
    does) — the model should freely choose whether to call
    ``update_brief`` this turn, ``complete_brief``, both, or neither
    (if the user just said "hi"). Forcing a tool every turn would
    mangle the conversation.

    Constructing this with ``api_key=None`` raises — the service
    layer checks the setting first and 503s before we get here.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPUS_MODEL,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        if not api_key:
            raise ValueError(
                "ClaudeKitchenIntake requires a non-empty api_key"
            )
        # Lazy-imported so ``anthropic`` stays an optional dep for
        # no-key dev environments (tests use FakeKitchenIntake).
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def send_turn(self, messages: list[dict[str, Any]]) -> IntakeTurnResult:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=TOOLS,
            messages=messages,
        )

        text_parts: list[str] = []
        field_updates: dict[str, Any] = {}
        is_complete = False
        completion_summary: dict[str, Any] | None = None

        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", ""))
            elif btype == "tool_use":
                name = getattr(block, "name", "")
                payload = getattr(block, "input", {}) or {}
                if name == "update_brief":
                    incoming = payload.get("field_updates") or {}
                    if isinstance(incoming, dict):
                        field_updates.update(incoming)
                elif name == "complete_brief":
                    is_complete = True
                    summary = payload.get("summary")
                    if isinstance(summary, dict):
                        completion_summary = summary

        return IntakeTurnResult(
            assistant_message="\n\n".join(p.strip() for p in text_parts if p).strip(),
            field_updates=field_updates,
            is_complete=is_complete,
            completion_summary=completion_summary,
            model=self._model,
        )


# ---------------------------------------------------------------------------
# Fake for tests
# ---------------------------------------------------------------------------


class FakeKitchenIntake:
    """Scripted intake for tests.

    Returns the pre-queued :class:`IntakeTurnResult` instances in
    order, one per ``send_turn`` call. Tests that want to exercise
    the route happy path pre-queue, say, 5 turns ending with
    ``is_complete=True``; tests that want to verify persistence after
    one turn queue one result.

    Raises :class:`AssertionError` if the route asks for more turns
    than were scripted — catches "happy path accidentally fell
    through to the real network" bugs loudly.
    """

    def __init__(self, scripted: list[IntakeTurnResult]) -> None:
        self._scripted = list(scripted)
        self._cursor = 0
        self.recorded_turns: list[list[dict[str, Any]]] = []

    def send_turn(self, messages: list[dict[str, Any]]) -> IntakeTurnResult:
        self.recorded_turns.append([dict(m) for m in messages])
        if self._cursor >= len(self._scripted):
            raise AssertionError(
                "FakeKitchenIntake: send_turn called "
                f"{self._cursor + 1} times but only "
                f"{len(self._scripted)} results were scripted"
            )
        result = self._scripted[self._cursor]
        self._cursor += 1
        return result
