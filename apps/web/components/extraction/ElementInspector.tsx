"use client";

import { useState } from "react";
import { ElementDetail } from "@/lib/api";
import { styleFor } from "./elementColors";

interface Props {
  element: ElementDetail | null;
}

/**
 * Side panel for the selected element.
 *
 * Progressive disclosure (UX research D-04 + decisions): the
 * primary identification (kind, IFC type, NCS classification,
 * confidence) is always visible. Heavier blocks — full IFC
 * property sets, raw geometry, kind-specific attrs — collapse by
 * default and expand on click.
 */
export function ElementInspector({ element }: Props) {
  if (!element) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border-subtle bg-bg-surface/40 p-4">
        <p className="text-center text-sm text-text-muted">
          Select an element to inspect.
        </p>
      </div>
    );
  }

  const sty = styleFor(element.kind);
  const psets = Object.entries(element.ifc_properties ?? {});
  const attrs = Object.entries(element.attrs ?? {});
  const geomKind = (element.geometry?.kind as string | undefined) ?? "—";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-bg-surface">
      <div className="border-b border-border-subtle px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: sty.stroke }}
          />
          <p className={`text-xs font-medium uppercase tracking-wider ${sty.textClass}`}>
            {sty.label.replace(/s$/, "")}
          </p>
        </div>
        <p className="mt-1 truncate font-mono text-sm text-text-primary">
          {element.name ?? element.number ?? element.ncs_layer ?? element.id.slice(0, 8)}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 text-sm">
        <DefList>
          <Row label="ID" mono>
            {element.id.slice(0, 8)}…
          </Row>
          <Row label="IFC type" mono>
            {element.ifc_type ?? "—"}
          </Row>
          <Row label="NCS layer" mono>
            {element.ncs_layer ?? "—"}
          </Row>
          {element.ncs_major_group && (
            <Row label="NCS major" mono>
              {element.ncs_major_group}
              {element.ncs_minor_group ? ` / ${element.ncs_minor_group}` : ""}
            </Row>
          )}
          <Row label="Confidence">
            {element.confidence == null
              ? "deterministic"
              : `${Math.round(element.confidence * 100)}%`}
          </Row>
          {element.host_element_id && (
            <Row label="Hosted in" mono>
              {element.host_element_id.slice(0, 8)}…
            </Row>
          )}
          {element.bbox && (
            <Row label="Bbox" mono>
              {bboxLabel(element.bbox)}
            </Row>
          )}
        </DefList>

        <Disclosure
          title={`IFC properties (${psets.length})`}
          disabled={psets.length === 0}
        >
          {psets.map(([pset, fields]) => (
            <div key={pset} className="mb-2">
              <p className="font-mono text-[11px] font-medium text-accent">
                {pset}
              </p>
              <DefList>
                {Object.entries(fields).map(([k, v]) => (
                  <Row key={k} label={k} mono>
                    {String(v)}
                  </Row>
                ))}
              </DefList>
            </div>
          ))}
        </Disclosure>

        <Disclosure title={`Geometry · ${geomKind}`}>
          <pre className="overflow-x-auto rounded bg-bg-elevated p-2 font-mono text-[10px] text-text-secondary">
            {JSON.stringify(element.geometry, null, 2)}
          </pre>
        </Disclosure>

        <Disclosure
          title={`Attributes (${attrs.length})`}
          disabled={attrs.length === 0}
        >
          <DefList>
            {attrs.map(([k, v]) => (
              <Row key={k} label={k} mono>
                {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </Row>
            ))}
          </DefList>
        </Disclosure>
      </div>
    </div>
  );
}

function bboxLabel(b: { minx: number; miny: number; maxx: number; maxy: number }): string {
  return `${b.minx.toFixed(1)}, ${b.miny.toFixed(1)} → ${b.maxx.toFixed(1)}, ${b.maxy.toFixed(1)}`;
}

function DefList({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1.5">{children}</dl>;
}

function Row({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <>
      <dt className="text-[11px] uppercase tracking-wider text-text-muted">{label}</dt>
      <dd className={mono ? "font-mono text-[12px] text-text-primary" : "text-[12px] text-text-primary"}>
        {children}
      </dd>
    </>
  );
}

function Disclosure({
  title,
  children,
  disabled = false,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  disabled?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-3 border-t border-border-subtle pt-3">
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className={[
          "flex w-full items-center justify-between text-left text-xs font-medium uppercase tracking-wider",
          disabled ? "cursor-default text-text-muted" : "text-text-secondary hover:text-text-primary",
        ].join(" ")}
      >
        <span>{title}</span>
        {!disabled && (
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden
            className={`transition-transform ${open ? "rotate-90" : ""}`}
          >
            <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        )}
      </button>
      {open && !disabled && <div className="mt-2">{children}</div>}
    </div>
  );
}
