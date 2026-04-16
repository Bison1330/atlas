import { Logo } from "./Logo";

export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="bg-bg-base">
      <div className="mx-auto flex max-w-[1200px] flex-col gap-2 px-3 py-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <Logo />
          <span className="text-xs text-text-muted">
            © {year} · Architecture that checks itself.
          </span>
        </div>
        <div className="font-mono text-xs text-text-muted">
          atlas · v0.1.0 · built on postgres · redis · s3
        </div>
      </div>
    </footer>
  );
}
