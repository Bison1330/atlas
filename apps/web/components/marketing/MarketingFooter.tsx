import Link from "next/link";

import { Logo } from "@/components/Logo";

import { DemoCTA } from "./DemoCTA";


interface FooterLinkItem {
  label: string;
  href?: string;
  demo?: boolean;
}

interface Column {
  heading: string;
  links: FooterLinkItem[];
}

const COLUMNS: Column[] = [
  {
    heading: "Product",
    links: [
      { label: "Demo", demo: true },
      { label: "Pricing", href: "/pricing" },
      { label: "Roadmap", href: "/roadmap" },
    ],
  },
  {
    heading: "Learn",
    links: [
      { label: "Guides", href: "/learn/guides" },
      { label: "FAQ", href: "/learn/faq" },
      { label: "Codes by city", href: "/learn/codes" },
      { label: "Contractor guide", href: "/learn/contractor" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "/about" },
      { label: "Contact", href: "/contact" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Terms", href: "/terms" },
      { label: "Privacy", href: "/privacy" },
    ],
  },
];


export function MarketingFooter() {
  return (
    <footer className="border-t border-border-subtle bg-bg-base">
      <div className="mx-auto max-w-[1200px] px-3 py-8 md:py-10">
        <div className="grid grid-cols-2 md:grid-cols-[1.3fr_repeat(4,_1fr)] gap-4 md:gap-6">
          <div className="col-span-2 md:col-span-1">
            <Logo />
            <p className="mt-2 text-sm text-text-secondary max-w-[280px]">
              The AI platform that’s on your side when you build.
            </p>
            <p className="mt-2 text-xs text-text-muted">
              © 2026 Atlas
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <h3 className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
                {col.heading}
              </h3>
              <ul className="mt-1.5 space-y-1">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {link.demo ? (
                      <DemoCTA variant="nav" size="sm">Demo</DemoCTA>
                    ) : (
                      <Link
                        href={link.href ?? "#"}
                        className="text-sm text-text-secondary hover:text-text-primary"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </footer>
  );
}
