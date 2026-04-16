export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-1 ${className}`}>
      <svg
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden
      >
        <path
          d="M3 20L12 4L21 20H18L12 9.5L6 20H3Z"
          stroke="#3DDC84"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path d="M8.25 15.5H15.75" stroke="#3DDC84" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="font-mono text-sm tracking-[0.2em] text-text-primary uppercase">
        Atlas
      </span>
    </div>
  );
}
