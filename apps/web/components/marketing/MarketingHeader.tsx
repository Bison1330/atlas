"use client";

import Link from "next/link";
import { useState } from "react";

import { Logo } from "@/components/Logo";

import { DemoCTA } from "./DemoCTA";

// Center nav items. "Demo" scrolls to the in-page narrative section
// (#product). The explicit Try-the-demo button on the right is the
// actual entry into the app — keeping nav links as nav links and the
// CTA as a CTA reads more like a marketing site than a single action.
const NAV = [
  { label: "Product", href: "#product" },
  { label: "Pricing", href: "/pricing" },
  { label: "Learn", href: "/learn" },
  { label: "Demo", href: "#product" },
];

/**
 * Marketing header used on unauthenticated surfaces (/, /pricing).
 *
 * Kept deliberately separate from AppHeader (in-app chrome) — the
 * two have different jobs: AppHeader is workspace navigation, this
 * is a sales surface.
 */
export function MarketingHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-border-subtle bg-bg-base/80 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1200px] items-center justify-between px-3">
        <Link href="/" aria-label="Atlas home" className="shrink-0">
          <Logo />
        </Link>

        <nav className="hidden md:flex items-center gap-3 text-sm text-text-secondary">
          {NAV.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="rounded-md px-1 py-0.5 hover:text-text-primary"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="hidden md:flex items-center gap-2">
          <Link
            href="/login"
            className="text-sm text-text-secondary hover:text-text-primary px-1 py-0.5"
          >
            Sign in
          </Link>
          <DemoCTA variant="primary" size="sm" />
        </div>

        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="md:hidden inline-flex h-5 w-5 items-center justify-center rounded text-text-secondary hover:text-text-primary"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 18 18"
            fill="none"
            aria-hidden
          >
            {open ? (
              <path
                d="M4 4l10 10M14 4L4 14"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            ) : (
              <>
                <path d="M3 5h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                <path d="M3 9h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                <path d="M3 13h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </>
            )}
          </svg>
        </button>
      </div>

      {open ? (
        <div className="md:hidden border-t border-border-subtle bg-bg-base/95 backdrop-blur">
          <div className="mx-auto max-w-[1200px] px-3 py-2 flex flex-col gap-1">
            {NAV.map((item) => (
              <Link
                key={item.label}
                href={item.href}
                onClick={() => setOpen(false)}
                className="rounded-md px-1 py-1 text-sm text-text-secondary hover:bg-bg-surface hover:text-text-primary"
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-1 border-t border-border-subtle pt-2 flex items-center gap-2">
              <Link
                href="/login"
                onClick={() => setOpen(false)}
                className="text-sm text-text-secondary hover:text-text-primary px-1 py-1"
              >
                Sign in
              </Link>
              <DemoCTA variant="primary" size="sm" />
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
