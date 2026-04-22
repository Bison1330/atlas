"use client";

/**
 * Real-time structured-brief sidebar shown next to the conversation.
 *
 * Reads the Atlas-extracted fields from the intake turn responses
 * (stored on the brief's ``extracted_fields`` JSONB) and groups them
 * into four sections: Project scope, Current space, What you want,
 * Constraints. Missing fields render as grey placeholders with an
 * em dash so the shape of the brief is visible from turn 1.
 *
 * The field-label mapping below mirrors the schema enumerated in the
 * intake system prompt — if that prompt adds or renames a required
 * field, update the corresponding entry here.
 */

type Fields = Record<string, unknown>;


interface FieldDef {
  key: string;
  label: string;
  // Optional formatter for complex nested values.
  format?: (value: unknown) => string | null;
}


const SECTIONS: Array<{ heading: string; fields: FieldDef[] }> = [
  {
    heading: "Project scope",
    fields: [
      { key: "scope_type", label: "Type" },
      { key: "kitchen_layout_goal", label: "Layout goal" },
      { key: "primary_purpose", label: "Primary use" },
    ],
  },
  {
    heading: "Current space",
    fields: [
      {
        key: "approximate_dimensions",
        label: "Dimensions",
        format: (v) => {
          if (!v || typeof v !== "object") return null;
          const d = v as Record<string, unknown>;
          const w = d.width_ft ?? d.width;
          const l = d.length_ft ?? d.length;
          if (w == null && l == null) return null;
          return `${w ?? "?"} ft × ${l ?? "?"} ft`;
        },
      },
      { key: "existing_features_to_keep", label: "Keep" },
      { key: "existing_features_to_change", label: "Change" },
      { key: "load_bearing_walls_known", label: "Load-bearing walls" },
      { key: "plumbing_locations_known", label: "Plumbing" },
    ],
  },
  {
    heading: "What you want",
    fields: [
      { key: "style_direction", label: "Style" },
      {
        key: "must_have_features",
        label: "Must-haves",
        format: formatList,
      },
      {
        key: "dealbreakers",
        label: "Dealbreakers",
        format: formatList,
      },
      {
        key: "appliance_priorities",
        label: "Appliance priorities",
        format: formatList,
      },
      {
        key: "budget_range",
        label: "Budget",
        format: (v) => {
          if (!v || typeof v !== "object") return null;
          const r = v as Record<string, unknown>;
          const lo = r.low_usd ?? r.low;
          const hi = r.high_usd ?? r.high;
          if (lo == null && hi == null) return null;
          const fmt = (n: unknown) =>
            typeof n === "number" ? `$${n.toLocaleString()}` : "?";
          return `${fmt(lo)} – ${fmt(hi)}`;
        },
      },
    ],
  },
  {
    heading: "Constraints",
    fields: [
      { key: "location_address_or_zip", label: "Location" },
      { key: "timeline", label: "Timeline" },
      { key: "hoa_or_historic_district", label: "HOA / historic" },
      { key: "accessibility_needs", label: "Accessibility" },
    ],
  },
];


function formatList(v: unknown): string | null {
  if (Array.isArray(v) && v.length > 0) {
    return v
      .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
      .join(", ");
  }
  return null;
}


function formatValue(v: unknown): string | null {
  if (v == null || v === "") return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return formatList(v);
  if (typeof v === "object") return JSON.stringify(v);
  return null;
}


export function BriefSidebar({
  extractedFields,
  isComplete,
}: {
  extractedFields: Fields;
  isComplete: boolean;
}) {
  return (
    <aside className="rounded-xl border border-border-subtle bg-bg-surface">
      <header className="border-b border-border-subtle px-2 py-1.5">
        <p className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
          Live brief
        </p>
        <h2 className="text-sm font-semibold text-text-primary mt-0.5">
          What Atlas knows about your kitchen
        </h2>
      </header>

      <div className="px-2 py-2 space-y-3">
        {SECTIONS.map((section) => (
          <section key={section.heading}>
            <h3 className="font-mono text-[10px] uppercase tracking-wider text-text-muted mb-1">
              {section.heading}
            </h3>
            <dl className="space-y-0.5">
              {section.fields.map((f) => {
                const raw = extractedFields[f.key];
                const display = f.format
                  ? f.format(raw)
                  : formatValue(raw);
                const populated = display != null;
                return (
                  <div
                    key={f.key}
                    className="grid grid-cols-[110px_1fr] gap-1.5 items-baseline"
                  >
                    <dt className="text-[11px] text-text-muted truncate">
                      {f.label}
                    </dt>
                    <dd
                      className={[
                        "text-sm truncate transition-colors duration-300",
                        populated
                          ? "text-text-primary"
                          : "text-text-muted/50",
                      ].join(" ")}
                      title={populated ? display ?? "" : undefined}
                    >
                      {populated ? display : "—"}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ))}

        {isComplete && (
          <div
            className="mt-2 rounded-lg border border-emerald-500/40 bg-emerald-500/[0.06] px-2 py-1.5"
            aria-live="polite"
          >
            <p className="font-mono text-[10px] uppercase tracking-wider text-emerald-400">
              Brief complete
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Generation is queued up for a later session.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
