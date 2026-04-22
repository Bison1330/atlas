/**
 * Single-sentence trust line between the pricing strip and the final
 * CTA. Small, muted, centered. Data-handling promises should match
 * whatever the privacy policy actually says once we write it.
 */
export function TrustLine() {
  return (
    <section className="mx-auto max-w-[1200px] px-3 pb-6">
      <p className="text-center text-sm text-text-muted">
        Your project details stay yours. We don’t sell your data.
        Hosted in the US. Encryption in transit and at rest.
      </p>
    </section>
  );
}
