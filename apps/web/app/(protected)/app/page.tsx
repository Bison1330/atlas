"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { AppHeaderV1 } from "@/components/kitchens/AppHeaderV1";
import { ChatComposer } from "@/components/kitchens/ChatComposer";
import { ExamplePrompts } from "@/components/kitchens/ExamplePrompts";
import { ProjectTypePills, type PillId } from "@/components/kitchens/ProjectTypePills";
import { ApiClientError, startKitchenProject } from "@/lib/api";


/**
 * Authenticated V1 homepage. Chat composer + project-type pills.
 *
 * Middleware gates this surface; the protected layout re-validates
 * the session. Only Kitchen is wired in V1 — selecting it and
 * submitting creates a new kitchen project and redirects to
 * /app/kitchens/[id] where the intake conversation continues.
 */
export default function AppHomePage() {
  const router = useRouter();
  const [selected, setSelected] = useState<PillId>("kitchen");
  const [composer, setComposer] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(message: string) {
    setError(null);
    try {
      const res = await startKitchenProject({
        project_type: "kitchen_remodel",
        initial_message: message,
      });
      router.push(`/app/kitchens/${res.project.id}`);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "llm_unavailable") {
        setError(
          "Atlas is temporarily unavailable (admin needs to set the API key). Please try again soon.",
        );
      } else if (err instanceof ApiClientError && err.code === "rate_limited") {
        setError(
          "Too many projects started in a short period. Give it a minute.",
        );
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Could not start your project. Please try again.");
      }
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-bg-base">
      <AppHeaderV1 />
      <main className="flex-1 bg-grid-fade">
        <div className="mx-auto max-w-[720px] px-3 py-8 md:py-14">
          <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-text-muted text-center mb-3">
            Homeowners and small business owners
          </p>
          <h1 className="font-display text-4xl md:text-5xl text-text-primary text-center leading-[1.05] tracking-tight">
            What are you building?
          </h1>
          <p className="text-lg text-text-secondary text-center mt-2 max-w-[560px] mx-auto">
            Tell me about your project. Atlas will design, price, and
            check it with you.
          </p>

          <div className="mt-6">
            <ProjectTypePills selected={selected} onSelect={setSelected} />
            <ChatComposer
              value={composer}
              onChange={setComposer}
              onSubmit={onSubmit}
              placeholder="Tell me about the kitchen you’re planning…"
              submitLabel="Start designing"
              autoFocus
            />
            {error ? (
              <p className="mt-1.5 text-sm text-red-400" role="alert">
                {error}
              </p>
            ) : null}
            <ExamplePrompts onPick={setComposer} />
          </div>
        </div>
      </main>
    </div>
  );
}
