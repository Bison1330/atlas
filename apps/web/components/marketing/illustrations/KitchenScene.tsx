/**
 * Stylized SVG illustration of a kitchen interior. Flat, warm —
 * cabinets, island, window, pendant lights. Palette is a subset of
 * STUDY_MODEL_PALETTE so the marketing illustration reads of-a-piece
 * with the real 3D viewer later in the narrative.
 */
export function KitchenScene() {
  return (
    <div className="relative w-full max-w-[460px] overflow-hidden rounded-xl border border-border-subtle shadow-elevated">
      <svg
        viewBox="0 0 460 280"
        className="block w-full h-auto"
        role="img"
        aria-label="Stylized illustration of a warm kitchen with island and pendant lights"
      >
        {/* Warm wall + floor backdrop */}
        <rect x="0" y="0" width="460" height="180" fill="#F2EEE6" />
        <rect x="0" y="180" width="460" height="100" fill="#C9C2B4" />

        {/* Sun spill from the right window */}
        <path
          d="M460 0 L460 280 L260 280 Z"
          fill="#FFF5E6"
          opacity="0.55"
        />

        {/* Window */}
        <rect x="320" y="30" width="110" height="110" fill="#E5EEF5" stroke="#2B2723" strokeWidth="1.5" />
        <line x1="375" y1="30" x2="375" y2="140" stroke="#2B2723" strokeWidth="1" />
        <line x1="320" y1="85" x2="430" y2="85" stroke="#2B2723" strokeWidth="1" />

        {/* Left wall-mounted upper cabinets */}
        <rect x="20" y="40" width="220" height="50" fill="#E8E2D6" stroke="#2B2723" strokeWidth="1.2" />
        <line x1="95" y1="40" x2="95" y2="90" stroke="#2B2723" strokeWidth="0.8" />
        <line x1="170" y1="40" x2="170" y2="90" stroke="#2B2723" strokeWidth="0.8" />

        {/* Left base cabinets + counter */}
        <rect x="20" y="155" width="260" height="25" fill="#A8A29A" stroke="#2B2723" strokeWidth="1.2" />
        <rect x="20" y="180" width="260" height="60" fill="#E8E2D6" stroke="#2B2723" strokeWidth="1.2" />
        <line x1="95" y1="180" x2="95" y2="240" stroke="#2B2723" strokeWidth="0.8" />
        <line x1="170" y1="180" x2="170" y2="240" stroke="#2B2723" strokeWidth="0.8" />
        <line x1="240" y1="180" x2="240" y2="240" stroke="#2B2723" strokeWidth="0.8" />

        {/* Range in counter */}
        <rect x="130" y="142" width="40" height="13" fill="#2B2723" />
        <circle cx="140" cy="148" r="2" fill="#A8A29A" />
        <circle cx="150" cy="148" r="2" fill="#A8A29A" />
        <circle cx="160" cy="148" r="2" fill="#A8A29A" />

        {/* Sink */}
        <rect x="210" y="155" width="50" height="22" fill="#E5EEF5" stroke="#2B2723" strokeWidth="1" />

        {/* Island */}
        <rect x="150" y="210" width="180" height="30" fill="#C9C2B4" stroke="#2B2723" strokeWidth="1.2" />
        <rect x="155" y="240" width="170" height="30" fill="#E8E2D6" stroke="#2B2723" strokeWidth="1.2" />

        {/* Pendant lights over the island */}
        <line x1="200" y1="0" x2="200" y2="95" stroke="#2B2723" strokeWidth="0.8" />
        <line x1="240" y1="0" x2="240" y2="95" stroke="#2B2723" strokeWidth="0.8" />
        <line x1="280" y1="0" x2="280" y2="95" stroke="#2B2723" strokeWidth="0.8" />
        <ellipse cx="200" cy="100" rx="9" ry="12" fill="#FFF5E6" stroke="#2B2723" strokeWidth="1" />
        <ellipse cx="240" cy="100" rx="9" ry="12" fill="#FFF5E6" stroke="#2B2723" strokeWidth="1" />
        <ellipse cx="280" cy="100" rx="9" ry="12" fill="#FFF5E6" stroke="#2B2723" strokeWidth="1" />

        {/* Small plant */}
        <rect x="50" y="135" width="18" height="20" fill="#C9C2B4" stroke="#2B2723" strokeWidth="0.8" />
        <path
          d="M52 135 C55 115, 60 118, 63 128 M58 135 C56 120, 62 122, 66 132"
          fill="none"
          stroke="#4B7A4A"
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* Stools at the island */}
        <rect x="170" y="240" width="10" height="35" fill="#2B2723" />
        <rect x="215" y="240" width="10" height="35" fill="#2B2723" />
        <rect x="260" y="240" width="10" height="35" fill="#2B2723" />
      </svg>
    </div>
  );
}
