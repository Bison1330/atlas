import Link from "next/link";
import { Logo } from "./Logo";

export function Nav() {
  return (
    <header className="border-b border-border-subtle bg-bg-base/80 backdrop-blur-md sticky top-0 z-20">
      <nav className="mx-auto flex max-w-[1200px] items-center justify-between px-3 py-2">
        <Link href="/" className="transition-opacity hover:opacity-80">
          <Logo />
        </Link>
        <div className="hidden items-center gap-4 md:flex">
          <a
            href="#capabilities"
            className="text-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            Capabilities
          </a>
          <a
            href="#approach"
            className="text-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            Approach
          </a>
          <a
            href="#status"
            className="text-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            Status
          </a>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-1 rounded border border-border-subtle bg-bg-surface px-2 py-0.5 font-mono text-xs text-text-secondary md:inline-flex">
            <span className="h-1 w-1 rounded-full bg-accent animate-pulse" />
            M8 · live
          </span>
          <Link
            href="/login"
            className="hidden md:inline-block text-sm text-text-secondary transition-colors hover:text-text-primary"
          >
            Sign in
          </Link>
          <Link
            href="/drawings"
            className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-medium text-bg-base transition-colors hover:bg-accent-dim"
          >
            Open app
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M5 12h14M13 6l6 6-6 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
        </div>
      </nav>
    </header>
  );
}
