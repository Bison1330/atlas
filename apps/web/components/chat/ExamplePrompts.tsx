/**
 * Empty state — tells first-time users what shape of question works.
 *
 * Five examples, one per supported answer bucket (count, quantity,
 * rank, adjacency, lookup). Clicking pre-fills the input without
 * auto-submitting so users can edit before sending.
 */

const EXAMPLES: { question: string; bucket: string }[] = [
  { question: "How many exterior doors are there?", bucket: "count" },
  { question: "What is the total wall length?", bucket: "quantity" },
  { question: "Which is the largest room?", bucket: "rank" },
  { question: "Is room 1 connected to room 2?", bucket: "adjacency" },
  { question: "What is the area of room 1?", bucket: "lookup" },
];


export function ExamplePrompts({
  onPick,
}: {
  onPick: (text: string) => void;
}) {
  return (
    <div className="p-1.5">
      <h2 className="text-sm font-medium text-text-primary">
        Ask about this drawing.
      </h2>
      <p className="text-xs text-text-secondary mt-0.5">
        Try questions like:
      </p>
      <ul className="mt-1 space-y-0.5">
        {EXAMPLES.map((e) => (
          <li key={e.question}>
            <button
              type="button"
              onClick={() => onPick(e.question)}
              className="w-full text-left rounded border border-border-subtle bg-bg-surface hover:border-accent/40 hover:bg-bg-elevated transition-colors px-1 py-0.5 text-xs text-text-secondary"
            >
              <span className="text-text-primary">{e.question}</span>{" "}
              <span className="font-mono text-text-muted">({e.bucket})</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-text-muted mt-1">
        Answers are grounded in the extracted elements.
      </p>
    </div>
  );
}
