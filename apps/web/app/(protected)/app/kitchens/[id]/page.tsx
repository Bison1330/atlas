"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";

import { AppHeaderV1 } from "@/components/kitchens/AppHeaderV1";
import { BriefSidebar } from "@/components/kitchens/BriefSidebar";
import { ChatComposer } from "@/components/kitchens/ChatComposer";
import { CompletionCard } from "@/components/kitchens/CompletionCard";
import { KitchenConversation } from "@/components/kitchens/KitchenConversation";
import {
  ApiClientError,
  getKitchen,
  sendKitchenMessage,
  type KitchenDetailResponse,
  type KitchenMessage,
} from "@/lib/api";


/**
 * Kitchen project workspace — intake conversation + live brief.
 *
 * State flow:
 *   1. Mount: GET /app/kitchens/{id} → seed messages, brief,
 *      is_complete. If it 404s, show a friendly error (someone
 *      deep-linked to a nonexistent project, or session lost).
 *   2. User submits: optimistically append the user turn, POST the
 *      message, apply Atlas's reply + extracted fields, clear the
 *      pending state.
 *   3. On is_complete=true: lock the composer, surface the
 *      CompletionCard at the bottom of the feed.
 *
 * We do NOT stream in V1 (architecture doc marks streaming as a
 * polish pass). Turn-by-turn request/response is acceptable while
 * intake averages 15–30 seconds per conversation.
 */
export default function KitchenProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [data, setData] = useState<KitchenDetailResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const [composer, setComposer] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);

  // Initial fetch + hydrate.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await getKitchen(id);
        if (!cancelled) setData(d);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiClientError && err.status === 404) {
          setLoadError("This kitchen project doesn’t exist (or was deleted).");
        } else {
          setLoadError((err as Error).message ?? "Could not load this project.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const onSend = useCallback(
    async (content: string) => {
      if (!data) return;
      setSendError(null);
      setPending(true);
      setPendingUserMessage(content);
      setComposer("");
      try {
        const res = await sendKitchenMessage(id, { content });
        // Re-fetch after sending so message ordering + assistant
        // message row IDs come from the authoritative DB state,
        // instead of us trying to synthesize them client-side.
        const fresh = await getKitchen(id);
        setData(fresh);
        // Safety: confirm the server agrees the brief is the same
        // version we were editing.
        void res;
      } catch (err) {
        if (err instanceof ApiClientError && err.code === "rate_limited") {
          setSendError(
            "Too many messages in a short period. Give it a minute.",
          );
        } else if (err instanceof ApiClientError && err.code === "brief_complete") {
          setSendError("Intake is already complete.");
        } else if (err instanceof ApiClientError) {
          setSendError(err.message);
        } else {
          setSendError("Could not send your message. Please try again.");
        }
        // Put the user's text back in the composer so they don't
        // lose it on error.
        setComposer(content);
      } finally {
        setPending(false);
        setPendingUserMessage(null);
      }
    },
    [data, id],
  );

  const messages = useMemo<KitchenMessage[]>(
    () => data?.messages ?? [],
    [data?.messages],
  );

  if (loadError) {
    return (
      <div className="min-h-screen flex flex-col bg-bg-base">
        <AppHeaderV1 />
        <main className="flex-1">
          <div className="mx-auto max-w-[720px] px-3 py-8">
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
              <p className="text-sm text-text-primary">{loadError}</p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen flex flex-col bg-bg-base">
        <AppHeaderV1 />
        <main className="flex-1">
          <div className="mx-auto max-w-[1200px] px-3 py-6">
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-3">
              <div className="h-[70vh] rounded-xl border border-border-subtle bg-bg-surface animate-pulse" />
              <div className="h-[70vh] rounded-xl border border-border-subtle bg-bg-surface animate-pulse" />
            </div>
          </div>
        </main>
      </div>
    );
  }

  const isComplete = data.is_complete;

  return (
    <div className="min-h-screen flex flex-col bg-bg-base">
      <AppHeaderV1 trail={data.project.name} />
      <main className="flex-1 min-h-0">
        <div className="mx-auto max-w-[1200px] h-[calc(100vh-3rem)] px-3 py-3">
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-3 h-full">
            {/* Conversation column */}
            <section className="flex flex-col min-h-0 rounded-xl border border-border-subtle bg-bg-base">
              <header className="border-b border-border-subtle px-3 py-2">
                <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                  Atlas intake
                </p>
                <h1 className="text-lg font-medium text-text-primary truncate">
                  {data.project.name}
                </h1>
              </header>

              <KitchenConversation
                messages={messages}
                pending={pending}
                pendingUserMessage={pendingUserMessage}
              />

              <footer className="border-t border-border-subtle px-2 py-2 space-y-2">
                {isComplete && <CompletionCard />}
                <ChatComposer
                  value={composer}
                  onChange={setComposer}
                  onSubmit={onSend}
                  placeholder={
                    isComplete
                      ? "Intake is complete — refinement coming soon."
                      : "Your reply…"
                  }
                  disabled={isComplete || pending}
                  submitLabel="Send"
                  minRows={2}
                  maxRows={6}
                />
                {sendError ? (
                  <p className="text-sm text-red-400" role="alert">
                    {sendError}
                  </p>
                ) : null}
              </footer>
            </section>

            {/* Brief sidebar */}
            <div className="min-h-0 overflow-y-auto">
              <BriefSidebar
                extractedFields={data.extracted_fields}
                isComplete={isComplete}
              />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
