/**
 * Mock chat exchange shown in the scroll narrative "Describe it"
 * step. Static SVG/HTML — no real chat wiring. User-styled bubble
 * on the right, Atlas reply on the left.
 */
export function ChatMockup() {
  return (
    <div className="relative w-full max-w-[460px] rounded-xl border border-border-subtle bg-bg-surface p-3 shadow-elevated">
      <div className="mb-2 flex items-center gap-1 border-b border-border-subtle pb-2">
        <span className="h-1.5 w-1.5 rounded-full bg-red-400/70" aria-hidden />
        <span className="h-1.5 w-1.5 rounded-full bg-yellow-400/70" aria-hidden />
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400/70" aria-hidden />
        <span className="ml-1 font-mono text-[10px] uppercase tracking-wider text-text-muted">
          Atlas chat
        </span>
      </div>

      <div className="space-y-2">
        <div className="flex justify-end">
          <div
            className="max-w-[85%] rounded-2xl rounded-br-sm px-2 py-1 text-sm"
            style={{ backgroundColor: "#F2EEE6", color: "#2B2723" }}
          >
            I want to open up my kitchen to the living room and add an island.
          </div>
        </div>

        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-bg-elevated px-2 py-1 text-sm text-text-primary">
            Nice. Do you know if the wall between them is load-bearing?
            Happy to work through it either way — just affects the
            cost and permit path.
          </div>
        </div>

        <div className="flex justify-start items-center gap-1 text-text-muted text-xs">
          <span className="flex gap-0.5">
            <span className="h-1 w-1 rounded-full bg-text-muted animate-pulse" />
            <span className="h-1 w-1 rounded-full bg-text-muted animate-pulse [animation-delay:150ms]" />
            <span className="h-1 w-1 rounded-full bg-text-muted animate-pulse [animation-delay:300ms]" />
          </span>
        </div>
      </div>
    </div>
  );
}
