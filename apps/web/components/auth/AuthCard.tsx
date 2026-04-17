import type { ReactNode } from "react";

/**
 * Centered card shell used by /login and /register. Keeps the two
 * pages visually identical so the experience of "register" vs "log
 * in" is just a tab switch, not a design change.
 */
export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main className="min-h-screen bg-bg-base bg-grid-fade flex items-center justify-center px-2 py-8">
      <div className="w-full max-w-[420px] rounded-lg border border-border-subtle bg-bg-surface shadow-elevated p-4">
        <h1 className="text-2xl font-semibold text-text-primary">{title}</h1>
        {subtitle ? (
          <p className="text-sm text-text-secondary mt-1">{subtitle}</p>
        ) : null}
        <div className="mt-3">{children}</div>
        {footer ? (
          <div className="mt-3 pt-3 border-t border-border-subtle text-sm text-text-muted">
            {footer}
          </div>
        ) : null}
      </div>
    </main>
  );
}
