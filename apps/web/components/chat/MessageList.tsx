"use client";

import { useEffect, useRef } from "react";

import type { AskResponse } from "@/lib/api";

import { AnswerCard } from "./AnswerCard";


/**
 * Entry in the session-only chat history.
 *
 * Discriminator-based so the renderer can cleanly branch:
 *   - user:    rendered as a right-aligned bubble
 *   - assistant: rendered via AnswerCard
 *   - system(error): rendered as an inline warning with code
 */
export type ChatEntry =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; payload: AskResponse }
  | {
      id: string;
      role: "system";
      variant: "error";
      code: string;
      message: string;
    };


export function MessageList({
  entries,
  onSuggestedPhrasing,
}: {
  entries: ChatEntry[];
  onSuggestedPhrasing: (text: string) => void;
}) {
  // Auto-scroll to the newest entry when the list grows.
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  return (
    <div
      ref={ref}
      className="flex-1 overflow-y-auto px-1.5 py-1 space-y-1"
    >
      {entries.map((entry) => (
        <MessageRow
          key={entry.id}
          entry={entry}
          onSuggestedPhrasing={onSuggestedPhrasing}
        />
      ))}
    </div>
  );
}


function MessageRow({
  entry,
  onSuggestedPhrasing,
}: {
  entry: ChatEntry;
  onSuggestedPhrasing: (text: string) => void;
}) {
  if (entry.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[280px] rounded border border-border-subtle bg-bg-elevated text-text-primary px-1 py-0.5 text-sm">
          {entry.content}
        </div>
      </div>
    );
  }
  if (entry.role === "assistant") {
    return (
      <AnswerCard
        payload={entry.payload}
        onSuggestedPhrasing={onSuggestedPhrasing}
      />
    );
  }
  // system error
  return (
    <div className="rounded border border-red-400/40 bg-red-400/5 px-1 py-0.5 text-xs">
      <span className="font-mono text-red-400 uppercase">{entry.code}</span>
      <span className="text-text-secondary"> — {entry.message}</span>
    </div>
  );
}
