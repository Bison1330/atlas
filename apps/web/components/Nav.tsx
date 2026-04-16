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
        <span className="inline-flex items-center gap-1 rounded border border-border-subtle bg-bg-surface px-2 py-0.5 font-mono text-xs text-text-secondary">
          <span className="h-1 w-1 rounded-full bg-accent animate-pulse" />
          M0 · Foundation
        </span>
      </nav>
    </header>
  );
}
