# atlas-web

Next.js 15 App Router frontend for Atlas.

## Design system

All tokens live in `tailwind.config.ts` — the source of truth for colors, type scale, spacing (8px grid), and radii.

```
bg.base      #0B0D10
bg.surface   #12151A
bg.elevated  #1A1E24
border.sub   #242A32
text.primary #F2F4F7
text.secondary #B4BCC8
text.muted   #7A8494
accent       #3B82F6
```

Fonts: Inter (sans) + JetBrains Mono (mono) via `next/font/google`.

## Scripts

```bash
npm run dev        # local dev on :3000
npm run build      # production build
npm start          # run production build
npm run typecheck  # tsc --noEmit
```
