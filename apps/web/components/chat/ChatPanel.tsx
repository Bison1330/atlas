"use client";

import { useState } from "react";

import { ApiClientError, askDrawing } from "@/lib/api";

import { ExamplePrompts } from "./ExamplePrompts";
import { MessageList, type ChatEntry } from "./MessageList";
import { QuestionInput } from "./QuestionInput";


/**
 * Collapsible right-sidebar chat panel for a drawing viewer.
 *
 * - Session-only history (D-20-B) — state lives here; page
 *   navigation or refresh drops it.
 * - Extraction-status caveat (M4 Phase 3 gate) is pinned to the
 *   header and non-hidable. Every successful response also
 *   carries per-answer certainty shown inline by AnswerCard.
 * - Citation chips are metadata only (D-20-A); viewer focus is
 *   a separate follow-up slice.
 */
export function ChatPanel({
  drawingId,
  initialCollapsed = false,
}: {
  drawingId: string;
  initialCollapsed?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [pending, setPending] = useState(false);
  const [input, setInput] = useState("");

  async function handleAsk(question: string) {
    const userId = crypto.randomUUID();
    setEntries((prev) => [
      ...prev,
      { id: userId, role: "user", content: question },
    ]);
    setInput("");
    setPending(true);
    try {
      const payload = await askDrawing(drawingId, question);
      setEntries((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", payload },
      ]);
    } catch (err) {
      const code = err instanceof ApiClientError ? err.code : "unknown";
      const message =
        err instanceof ApiClientError ? err.message : "Request failed.";
      setEntries((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "system",
          variant: "error",
          code,
          message: friendlyError(code, message),
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className="rounded-l border border-border-subtle border-r-0 bg-bg-surface hover:bg-bg-elevated text-text-secondary px-1 py-2 text-xs font-mono transition-colors [writing-mode:vertical-rl]"
      >
        Q&amp;A
      </button>
    );
  }

  return (
    <aside className="w-[360px] shrink-0 border-l border-border-subtle bg-bg-base flex flex-col h-full">
      <header className="border-b border-border-subtle px-1.5 py-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Q&amp;A</h2>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          aria-label="Collapse chat panel"
          className="text-text-muted hover:text-text-primary text-lg leading-none"
        >
          ×
        </button>
      </header>

      <CaveatBanner />

      {entries.length === 0 ? (
        <ExamplePrompts onPick={setInput} />
      ) : (
        <MessageList entries={entries} onSuggestedPhrasing={setInput} />
      )}

      <QuestionInput
        value={input}
        onChange={setInput}
        onSubmit={handleAsk}
        disabled={pending}
      />
    </aside>
  );
}


function CaveatBanner() {
  // The extraction_status caveat is intentionally non-hidable
  // until M4 Phase 3 lands. See docs/research/m4-phase3-procurement.md.
  return (
    <div className="bg-yellow-400/10 border-b border-yellow-400/20 px-1.5 py-0.5 text-xs text-text-secondary">
      <span className="font-medium text-yellow-400">Note:</span>{" "}
      extraction is unvalidated on real CAD files — answers may be
      wrong where extraction missed or mis-classified elements.
    </div>
  );
}


function friendlyError(code: string, message: string): string {
  switch (code) {
    case "llm_unavailable":
      return "Q&A is unavailable — an administrator hasn't set ANTHROPIC_API_KEY.";
    case "rate_limited":
      return "Too many questions in a short period. Try again in a minute.";
    case "not_authenticated":
      return "Your session expired. Sign in again.";
    default:
      return message;
  }
}
