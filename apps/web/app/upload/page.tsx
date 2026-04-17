"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { DropZone } from "@/components/upload/DropZone";

export default function UploadPage() {
  const router = useRouter();
  const [projectName, setProjectName] = useState("");

  const onUploaded = useCallback(
    (drawingId: string) => {
      router.push(`/drawings/${drawingId}`);
    },
    [router],
  );

  return (
    <div className="min-h-screen">
      <AppHeader trail="upload" />

      <main className="mx-auto max-w-[820px] px-3 py-8">
        <header className="mb-5">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-text-muted">
            Step 1 — ingest
          </p>
          <h1 className="mt-1 text-3xl font-medium tracking-tight text-text-primary">
            Upload a drawing set
          </h1>
          <p className="mt-1 text-text-secondary">
            Atlas will validate the PDF, render every sheet at 300 DPI, and
            generate a tile pyramid for fluid pan and zoom in the viewer.
          </p>
        </header>

        <section className="rounded-xl border border-border-subtle bg-bg-surface/40 p-4">
          <label className="mb-3 block">
            <span className="block text-xs font-medium uppercase tracking-wider text-text-muted">
              Project name <span className="font-normal normal-case text-text-muted">(optional)</span>
            </span>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. 4th & Pine — IFC set"
              className="mt-1 w-full rounded-md border border-border-subtle bg-bg-base px-2 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          </label>

          <DropZone
            projectName={projectName.trim() || undefined}
            onUploaded={onUploaded}
          />
        </section>

        <section className="mt-6 grid gap-3 md:grid-cols-3">
          <Tip
            num="01"
            title="Validate"
            body="We confirm the file is a real PDF, isn't password-protected, and has at least one page."
          />
          <Tip
            num="02"
            title="Rasterize"
            body="Every page is rendered to pixels at 300 DPI — sharp at maximum zoom without bloating storage."
          />
          <Tip
            num="03"
            title="Tile"
            body="Each rendered sheet is sliced into a WebP pyramid so the viewer streams only what's on screen."
          />
        </section>
      </main>
    </div>
  );
}

function Tip({ num, title, body }: { num: string; title: string; body: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-surface/40 p-3">
      <p className="font-mono text-xs text-accent">{num}</p>
      <h3 className="mt-1 text-sm font-medium text-text-primary">{title}</h3>
      <p className="mt-0.5 text-xs leading-relaxed text-text-muted">{body}</p>
    </div>
  );
}
