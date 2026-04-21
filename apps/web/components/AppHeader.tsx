import Link from "next/link";
import { Logo } from "./Logo";

export function AppHeader({ trail }: { trail?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border-subtle bg-bg-base/80 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1200px] items-center justify-between px-3">
        <div className="flex items-center gap-2">
          <Link href="/" aria-label="Atlas home">
            <Logo />
          </Link>
          {trail && (
            <>
              <span className="text-text-muted" aria-hidden>
                /
              </span>
              <div className="font-mono text-xs text-text-secondary">{trail}</div>
            </>
          )}
        </div>
        <nav className="flex items-center gap-2 text-sm text-text-secondary">
          <Link
            href="/drawings"
            className="hidden rounded-md px-2 py-1 hover:text-text-primary sm:inline-block"
          >
            Drawings
          </Link>
          <Link
            href="/projects"
            className="hidden rounded-md px-2 py-1 hover:text-text-primary sm:inline-block"
          >
            Projects
          </Link>
          <Link
            href="/upload"
            className="rounded-md border border-border-subtle px-2 py-1 hover:border-text-muted hover:text-text-primary"
          >
            New ingest
          </Link>
        </nav>
      </div>
    </header>
  );
}
