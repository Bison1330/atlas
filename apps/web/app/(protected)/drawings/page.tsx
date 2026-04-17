import Link from "next/link";

import { DrawingRow } from "@/components/drawings/DrawingRow";
import { EmptyState } from "@/components/drawings/EmptyState";
import { listDrawingsServer } from "@/lib/api-server";


export const metadata = {
  title: "Drawings · Atlas",
};


export default async function DrawingsPage() {
  const data = await listDrawingsServer();
  // The (protected) layout already validates auth; a null here would
  // mean the layout let us through but the session dropped mid-render.
  // Treat as empty rather than crash — the middleware will catch the
  // next request.
  const drawings = data?.drawings ?? [];

  return (
    <main className="min-h-screen bg-bg-base bg-grid-fade px-2 py-6">
      <div className="mx-auto max-w-[960px]">
        <header className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-3xl font-semibold text-text-primary">
              Drawings
            </h1>
            <p className="text-sm text-text-secondary mt-0.5">
              {drawings.length === 0
                ? "Nothing here yet."
                : `${drawings.length} ${drawings.length === 1 ? "drawing" : "drawings"}`}
            </p>
          </div>
          <Link
            href="/upload"
            className="inline-flex items-center gap-1 rounded bg-accent hover:bg-accent-dim text-white font-medium px-2 py-1 text-sm transition-colors"
          >
            Upload
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M12 5v14M5 12l7-7 7 7"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
        </header>

        {drawings.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="list-none">
            {drawings.map((d) => (
              <li key={d.id}>
                <DrawingRow drawing={d} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
