import Link from "next/link";

import { LogoutButton } from "@/components/auth/LogoutButton";
import { authMeOrNull } from "@/lib/api-server";


export const metadata = {
  title: "Account · Atlas",
};


export default async function MePage() {
  // Layout already validated; this is defence-in-depth + the user
  // row for display. If the session vanishes between the layout and
  // here (pathological race), authMeOrNull returns null and we just
  // surface "signed out" rather than crash.
  const user = await authMeOrNull();

  return (
    <main className="min-h-screen bg-bg-base bg-grid-fade px-2 py-6">
      <div className="mx-auto max-w-[720px]">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-3xl font-semibold text-text-primary">Account</h1>
          <LogoutButton />
        </div>

        {user ? (
          <div className="rounded-lg border border-border-subtle bg-bg-surface p-3">
            <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-text-muted">Email</dt>
              <dd className="text-text-primary font-mono">{user.email}</dd>

              <dt className="text-text-muted">Display name</dt>
              <dd className="text-text-primary">
                {user.display_name ?? (
                  <span className="text-text-muted italic">(not set)</span>
                )}
              </dd>

              <dt className="text-text-muted">Email verified</dt>
              <dd className="text-text-primary">
                {user.email_verified ? "Yes" : (
                  <span className="text-text-muted">
                    No — verification flow ships with M7.1.
                  </span>
                )}
              </dd>

              <dt className="text-text-muted">Last login</dt>
              <dd className="text-text-primary font-mono text-xs">
                {user.last_login_at ?? "—"}
              </dd>

              <dt className="text-text-muted">User ID</dt>
              <dd className="text-text-muted font-mono text-xs">{user.id}</dd>
            </dl>
          </div>
        ) : (
          <p className="text-text-secondary">You are signed out.</p>
        )}

        <div className="mt-4 space-y-1">
          <h2 className="text-lg text-text-primary font-semibold">
            What&apos;s next
          </h2>
          <ul className="text-sm text-text-secondary space-y-0.5 list-disc list-inside">
            <li>
              <Link href="/drawings" className="text-accent hover:underline">
                Drawings
              </Link>{" "}
              — upload a PDF plan set and browse sheets.
            </li>
            <li>
              Project collaboration, annotation tools, and natural-language
              Q&amp;A are available via the API; UI follow-ups land in later
              slices (see{" "}
              <code className="text-text-muted">
                docs/research/atlas-web-m7-auth-ui.md
              </code>
              ).
            </li>
          </ul>
        </div>
      </div>
    </main>
  );
}
