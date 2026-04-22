# Atlas — Product Vision (v2.0)

_This is the canonical vision for Atlas. Every future Claude Code session must read this document at session start. If any session's work appears to drift from this vision, pause and ask the human._

## What Atlas is

Atlas is the AI platform that's on your side when you build. You describe what you want — a kitchen renovation, a home addition, a coffee shop fit-out, a garage, a dream home — and Atlas helps you get from vision to buildable, priced, code-checked plans. Without needing an architect. Without getting rolled by a contractor. Without learning CAD.

## Who Atlas is for (V1)

**Primary audience:** Homeowners and small commercial tenants. The people paying for the work, not the people doing the work.

- **Homeowners** planning a kitchen remodel, a bathroom, a home addition, an ADU, a deck, a garage, or a dream home. They have ideas, often a budget, sometimes a lot, rarely any drawings.
- **Retail tenants / small commercial** opening a coffee shop, a boutique, a salon, a small office, a restaurant. They have a space (sqft + address), a business concept, and fear of getting ripped off.

Both groups share a core pain: they're making the biggest financial decision of their year with less information than the contractor they're hiring. Atlas evens the asymmetry.

**Secondary (served indirectly):** Builders and contractors engage with Atlas because homeowners bring Atlas-generated plans to them. Atlas becomes the common ground for the homeowner-contractor conversation.

**Deferred to V2+:** Architects as a primary buyer. Professional practice tools. Enterprise features. Real markets, but not where we start.

## What Atlas does

1. **Listens** — Conversational interface. Users describe what they want in plain language. No technical jargon required.
2. **Designs** — AI generates preliminary floor plans and 3D walkthroughs from the conversation. Iterative refinement continues through chat.
3. **Shows** — Real-time stylized 3D walkthrough for interactive design. On-demand photorealistic AI-generated renders for emotional moments (style switching: modern, farmhouse, traditional, industrial). Homeowners see their kitchen the way it will look, not as a white model.
4. **Grounds** — Uses uploaded photos, existing drawings, or lot address to anchor designs in reality.
5. **Checks** — Looks up local building codes. Flags permit requirements, engineering stamps, inspection milestones. Red-flags cost surprises.
6. **Prices** — Cost ranges from real public bid data, BLS PPI-adjusted, regional multipliers. Line items broken out, honest about uncertainty.
7. **Protects** — Contractor engagement package: bid comparison framework, red-flag questions to ask, typical-quote ranges for the user's region. Atlas is on the user's side, not the contractor's.

"Protects" is the wedge. Nobody else does this. Maket makes pretty plans. Atlas makes sure you don't get screwed.

## Positioning

**"Atlas is on your side when you build."**

Variants:
- For homeowners: "Build your vision without getting rolled."
- For tenants: "Open your business without overpaying for the space."
- For everyone: "The AI platform that's on your side when you build."

## Pricing (V1)

- **Free**: 1 active project, basic conversation, preview-quality output, watermarked plans.
- **Homeowner $29/mo**: Unlimited projects, full code lookup for user's jurisdiction, cost estimation, contractor engagement package, 100 AI renders/mo.
- **Business $79/mo**: Everything above + commercial code checks, ADA compliance, small-commercial cost libraries, tenant fit-out templates, 300 AI renders/mo.
- **Project Pack $99 one-time**: Single project, complete package, no subscription. Low-friction entry for subscription-averse users.

No enterprise tier in V1. Maybe ever.

## What's already built (sessions 1 through 3.5)

Roughly 70% of existing work carries forward with no rewrite:

- **Geometry engine** (atlas-core): Wall/Door/Window/Room data model, polyline geometry, connectivity analysis, 3D reconstruction. Generic — doesn't care whether input came from DXF upload or AI generation.
- **3D viewer** (Model3DCanvas): Three.js orbit viewer with pitch-unified mode (dollhouse ↔ floor plan), room labels, HUD, SSAO/outline post-processing. Works for any Scene3D regardless of origin.
- **DXF extraction pipeline**: Reads DXFs into the data model. Used for the "upload existing plans" path.
- **API scaffolding**: Auth, sessions, rate limiting, error envelopes. Reusable for everything.
- **Demo mode**: Seed script, 4 sample drawings, "Try the demo" login.
- **Test harness safety**: Post-incident sentinel-row protection and DB-name checks.

Roughly 20% gets reframed, not rewritten: the drawings-list page becomes a projects-list page; the QA chat service becomes the conversational design interface; file-centric mental model becomes project-centric.

Roughly 10% gets deleted or deferred: anything over-indexed on architect/analysis workflow (architect-speak HUD chips, some existing chat framings).

## What must be built for V1

Organized by user-visible capability:

1. Marketing landing page ("Atlas is on your side when you build")
2. Conversational front door (post-login homepage is a chat composer)
3. Project-type onboarding flows (kitchen / addition / new construction / retail fit-out / office)
4. AI floor plan generation from natural language
5. Iterative refinement through chat
6. Stylized baseline 3D viewer (replace study-model with warmer, furnishable, illustrated look)
7. AI photorealistic rendering (Stable Diffusion + ControlNet or equivalent, style switching)
8. Code lookup AI agent (per jurisdiction, with user confirmation)
9. Rules engine (10-15 residential/commercial code checks)
10. Compliance report UI
11. Cost estimation (public bid data ingestion, regional adjustment)
12. Contractor engagement package (bid comparison, red-flag questions)
13. Education content (/learn pages, plain-language construction knowledge)
14. Marketing shell (pricing page, demo gallery, testimonials section)

## What Atlas is NOT

- Not an architect's tool. Architects are welcome but not primary.
- Not a CAD replacement. Users wanting CAD precision should use CAD.
- Not a BIM platform. We output plans, not full BIM models.
- Not trying to replace contractors. We help users hire better contractors and know when they're being fair.
- Not photoreal real-time like Enscape/D5. Our photoreal is AI-rendered from the 3D scene, not baked into the renderer.
- Not enterprise software. Solo homeowners and single-location tenants are first-class.

## Rules of engagement for every future session

1. Plain language, not jargon. Read every user-facing string as if your mom were reading it.
2. Homeowner/tenant framing always. "Remodel" not "renovation scope." "Contractor" not "GC." "Permit" not "AHJ submission."
3. Honesty over polish. If the AI isn't sure, say so. If cost data is stale, say so. If code lookup isn't exhaustive, list what was checked.
4. Protect the user. Every major decision surface includes "here's how to tell if you're being taken advantage of."
5. AI as advocate, not assistant. Tone is "I'm looking out for you," not "I'm here to help you."
6. Cheaper than every competitor, period.
7. No v2. Ship the right version the first time.
8. Visual quality is a first-class concern. Homeowners pay for Atlas partly because the renders make them excited about their project.

## Session history reference

Sessions 1 through 3.5 built foundation pieces (geometry, 3D viewer, demo mode, test harness safety) against an earlier vision that has since pivoted. The work is valuable and carries forward. The framing has shifted: we were building for architects analyzing existing drawings; we are now building for homeowners designing new projects. Same infrastructure, different product.

V2.0 was set on 2026-04-22. All prior session plans are superseded by the V1 build sequence that follows this pivot.
