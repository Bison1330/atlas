"use client";

// TODO(v2): this form is a bare name + description create dialog,
// fine for the pre-pivot "group drawings" model but wrong for V2.0.
// V2 project creation needs:
//   - Project-type picker (kitchen remodel / bathroom / addition /
//     ADU / deck / garage / new home / coffee shop / retail / salon /
//     small office) — drives onboarding flow and default prompts.
//   - Optional "Grounds" inputs: address, lot size, existing-sqft,
//     photos, or an uploaded drawing.
//   - A conversational entry path — in V2 the primary way to start a
//     project is the post-login chat composer, not a form. This
//     form is a secondary "create blank project" path.

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { ApiClientError, createProject } from "@/lib/api";


/**
 * Inline create-project form. Expand/collapse from a small button
 * so the empty list still shows a primary CTA but an existing list
 * isn't dominated by a form.
 *
 * After create: router.refresh() re-renders the server component
 * above so the new project appears without a full navigation.
 */
export function CreateProjectForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createProject({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      setOpen(false);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Could not create project.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded bg-accent hover:bg-accent-dim text-white font-medium px-2 py-1 text-sm transition-colors"
      >
        New project
      </button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded border border-border-subtle bg-bg-surface p-2 mb-3 space-y-2"
    >
      <div>
        <label
          htmlFor="project-name"
          className="block text-xs text-text-muted mb-0.5"
        >
          Name
        </label>
        <input
          id="project-name"
          type="text"
          required
          autoFocus
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={submitting}
          className="w-full rounded bg-bg-elevated border border-border-subtle text-text-primary px-1 py-0.5 text-sm focus:outline-none focus:border-accent"
        />
      </div>
      <div>
        <label
          htmlFor="project-description"
          className="block text-xs text-text-muted mb-0.5"
        >
          Description <span className="text-text-muted">(optional)</span>
        </label>
        <textarea
          id="project-description"
          rows={2}
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={submitting}
          className="w-full rounded bg-bg-elevated border border-border-subtle text-text-primary px-1 py-0.5 text-sm focus:outline-none focus:border-accent resize-none"
        />
      </div>
      {error ? (
        <div className="text-xs text-red-400" role="alert">
          {error}
        </div>
      ) : null}
      <div className="flex items-center justify-end gap-1">
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
          disabled={submitting}
          className="text-sm text-text-secondary hover:text-text-primary px-2 py-0.5"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="rounded bg-accent hover:bg-accent-dim disabled:bg-bg-elevated disabled:text-text-muted text-white font-medium px-2 py-0.5 text-sm transition-colors"
        >
          {submitting ? "Creating…" : "Create"}
        </button>
      </div>
    </form>
  );
}
