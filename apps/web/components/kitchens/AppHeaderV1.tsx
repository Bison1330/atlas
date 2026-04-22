import Link from "next/link";

import { Logo } from "@/components/Logo";
import { LogoutButton } from "@/components/auth/LogoutButton";


/**
 * Slim authenticated-app header for V1 surfaces under /app.
 *
 * Deliberately separate from the pre-v1 ``AppHeader`` — that one
 * carries /drawings, /projects, /upload nav items which are the old
 * architect-analytical mental model. V1 is project-centric; the
 * primary way into work is the composer on /app, not a top-level
 * nav bar of legacy surfaces.
 */
export function AppHeaderV1({ trail }: { trail?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border-subtle bg-bg-base/80 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1200px] items-center justify-between px-3">
        <div className="flex items-center gap-2 min-w-0">
          <Link href="/app" aria-label="Atlas home" className="shrink-0">
            <Logo />
          </Link>
          {trail && (
            <>
              <span className="text-text-muted shrink-0" aria-hidden>/</span>
              <div className="font-mono text-xs text-text-secondary truncate">
                {trail}
              </div>
            </>
          )}
        </div>
        <nav className="flex items-center gap-2">
          <Link
            href="/me"
            className="hidden sm:inline-block text-sm text-text-secondary hover:text-text-primary px-1 py-0.5"
          >
            Account
          </Link>
          <LogoutButton />
        </nav>
      </div>
    </header>
  );
}
