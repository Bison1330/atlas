"use client";

import { useEffect, useRef } from "react";

import type { KitchenMessage } from "@/lib/api";


/**
 * Message feed for the intake conversation.
 *
 * - User messages right-aligned with a warm bubble (reads as "my
 *   messages" the way every consumer chat surface does).
 * - Assistant messages left-aligned on a subtle surface bubble.
 * - Markdown rendering is deferred — plain text is the V1 contract,
 *   and the intake prompt keeps Atlas's voice short enough that
 *   headings/lists aren't needed. Revisit when generation replies
 *   arrive in S3.
 * - Auto-scroll to bottom on every new message or while pending,
 *   so an in-flight turn doesn't strand the user mid-scroll.
 */
export function KitchenConversation({
  messages,
  pending,
  pendingUserMessage,
}: {
  messages: KitchenMessage[];
  pending: boolean;
  pendingUserMessage: string | null;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Defer to next frame so fresh DOM nodes measure correctly.
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [messages.length, pending]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto px-2 py-3 space-y-2"
      aria-live="polite"
      aria-label="Kitchen intake conversation"
    >
      {messages.map((m) => (
        <MessageBubble key={m.id} role={m.role} content={m.content} />
      ))}

      {/* Optimistic echo of the user's just-submitted turn so the
          feed doesn't go blank while Atlas thinks. */}
      {pending && pendingUserMessage ? (
        <MessageBubble role="user" content={pendingUserMessage} />
      ) : null}

      {pending ? <AssistantTyping /> : null}
    </div>
  );
}


function MessageBubble({
  role,
  content,
}: {
  role: "user" | "assistant" | "system";
  content: string;
}) {
  if (role === "system") return null;

  const isUser = role === "user";
  return (
    <div
      className={[
        "flex",
        isUser ? "justify-end" : "justify-start",
      ].join(" ")}
    >
      <div
        className={[
          "max-w-[85%] rounded-2xl px-3 py-1.5 text-base leading-relaxed whitespace-pre-wrap",
          isUser
            ? "rounded-br-sm bg-accent/[0.12] text-text-primary border border-accent/30"
            : "rounded-bl-sm bg-bg-surface text-text-primary border border-border-subtle",
        ].join(" ")}
      >
        {content}
      </div>
    </div>
  );
}


function AssistantTyping() {
  return (
    <div className="flex justify-start" aria-hidden>
      <div className="rounded-2xl rounded-bl-sm border border-border-subtle bg-bg-surface px-3 py-1.5">
        <span className="inline-flex gap-0.5">
          <span className="h-1.5 w-1.5 rounded-full bg-text-muted animate-pulse" />
          <span className="h-1.5 w-1.5 rounded-full bg-text-muted animate-pulse [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-text-muted animate-pulse [animation-delay:300ms]" />
        </span>
      </div>
    </div>
  );
}
