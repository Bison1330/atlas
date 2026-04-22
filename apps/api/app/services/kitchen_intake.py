"""V1 kitchen intake — the Opus conversation that produces a KitchenBrief.

This module defines the protocol every intake implementation
satisfies plus a test double. The Anthropic-backed ``ClaudeKitchenIntake``
lands alongside the full system prompt + tool definitions in the
next commit (S1 prompt design).

Routes import :class:`KitchenIntake` at module level; tests override
``_get_kitchen_intake`` with :class:`FakeKitchenIntake` so they never
touch the real model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Flagship Opus per the architecture commitment. Intake quality
# dominates the rest of the pipeline, so the cost lift over Sonnet
# is acceptable — Kevin's guidance: per-design LLM budget does not
# include renders, so don't micro-optimize here.
OPUS_MODEL = "claude-opus-4-7"
MAX_TOKENS = 1024


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
# Real Claude interpreter (prompt + tools land in the next commit)
# ---------------------------------------------------------------------------


class ClaudeKitchenIntake:
    """Opus-backed intake. The system prompt and tool schemas land
    in the next commit (``feat(api): kitchen intake Claude Opus
    prompt and tool use``); this skeleton exists so the route module
    can import the class and the dependency factory can
    construct it without a circular import. ``send_turn`` raises
    until the follow-up commit fills it in."""

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
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    def send_turn(self, messages: list[dict[str, Any]]) -> IntakeTurnResult:
        raise NotImplementedError(
            "ClaudeKitchenIntake.send_turn is wired in the "
            "next commit — tests should use FakeKitchenIntake "
            "via the _get_kitchen_intake dependency override."
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
