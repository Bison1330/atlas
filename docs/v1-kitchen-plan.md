# Atlas V1 — Kitchen Design System: Technical Plan

## 0. Status and scope

This plan governs the build of Atlas's V1 AI-driven kitchen design system. It supersedes any prior session plan. Every future Claude Code session reads `docs/product-vision.md` first and this document second. Any work that appears to drift from either document pauses and asks the human.

**In scope:** residential kitchen remodels and new kitchen designs, single-family residential (not multifamily or commercial). North American market — IRC-based codes, NKBA design standards, imperial units as primary with metric available.

**Out of scope for V1:** bathrooms, whole-house designs, additions, new construction, commercial kitchens, retail fit-outs. These come in V2+ after kitchens are genuinely best-in-class.

**Acceptance for V1:** A user types "I want to redo my kitchen" into the Atlas homepage, answers a series of clarifying questions, and within five minutes has (a) three candidate floor plans that would pass plan review in their jurisdiction, (b) realistic cost estimates broken down by line item, (c) an AI photoreal render of the kitchen they selected, and (d) a contractor engagement package telling them what a fair bid looks like and how to spot a bad one.

Enterprise-grade means: the output is consistently good (not occasionally good); every plan shown is validated (never shown a broken plan); costs reflect real regional data; code citations are verifiable; the system honestly reports uncertainty where it exists.

## 1. Principles

1.1 **Never show invalid output.** Showing a broken plan is worse than showing no plan — it destroys trust, and trust is our wedge.

1.2 **Speed matters, but correctness matters more.** Users can wait 30 seconds for a beautiful, correct kitchen. They will not forgive a wrong one delivered in 5.

1.3 **Honesty over polish.** When the system is uncertain, surface that honestly. Users don't trust products that overclaim.

1.4 **Every capability serves the homeowner, not the architect.** NKBA/IRC terminology is used internally but translated for output.

1.5 **The protection layer is a first-class feature, not a sidecar.** It ships with the first kitchen.

1.6 **Build in layers, validate each.** Each of the nine sessions below produces something independently testable.

## 2. System architecture

Six subsystems in a pipeline:

1. **Intake** — LLM interviews user, produces structured brief
2. **Constraint compilation** — brief + jurisdiction → machine-readable ConstraintSet
3. **Generation** — constraint-satisfaction optimizer produces N candidate layouts
4. **Validation** — every layout checked against geometry, code, ergonomic rules
5. **Ranking** — LLM scores survivors, selects top 3 with explanations
6. **Presentation** — 2D plans + 3D walkthrough + AI photoreal renders + contractor package

Plus a **Refinement** loop: natural-language edits apply a delta and re-run the pipeline.

### Subsystem details

**Intake**: Claude Opus for the interview (quality matters). Multi-turn conversation producing a structured `KitchenBrief`. Persists to DB after each exchange so users can pause/resume.

**Constraint compilation**: three categories — code (IRC + jurisdiction amendments, cited), ergonomic (NKBA guidelines, cited), user-specific (derived from brief). Jurisdiction lookup via LLM with web access; cached per project.

**Generation**: constraint programming, not raw LLM generation. Grid-based layout solver (3-inch grid) with hard constraints (ConstraintSet) and soft preferences (style). Multiple seeds produce diversity. Target: 20-50 candidates per generation run. Likely OR-Tools or equivalent; committed in session 0.

**Validation**: four validator categories run in order — geometric, code, ergonomic, remodel feasibility. Failed layouts are discarded or returned to generator with failure reasons. Users never see invalid output.

**Ranking**: Claude Opus reads survivors, cross-references user preferences, produces top 3 with plain-English tradeoff summaries.

**Presentation**: four outputs per layout — annotated 2D plan, 3D walkthrough (existing Model3DCanvas), AI photoreal render (Stable Diffusion or Flux + ControlNet), contractor engagement package.

**Refinement**: Claude interprets the delta; small changes edit locally, structural changes regenerate. Every refinement re-runs validation.

## 3. Data model additions

New domain objects (full schema committed in session 0):
- `Project` — reuses existing scaffold
- `KitchenBrief` — structured intake output
- `ConstraintSet` — compiled constraints
- `LayoutCandidate` — generated option with validation state and ranking score
- `Jurisdiction` — cached code edition + amendments per locale
- `RenderRequest` / `RenderOutput` — AI photoreal tracking
- `CostEstimate` — line items and ranges
- `ContractorPackage` — protection deliverable

## 4. Frontend experience

**Homepage after sign-in**: centered chat composer with project-type pills above. Only "Kitchen" active for V1; others show "Coming soon." Example prompts link below composer.

**Intake flow**: conversation flows like a messaging app. Sidebar fills in structured brief fields in real time. When brief is complete, generation begins.

**Results view**: three candidate cards showing 2D plan thumbnail, cost range, one-sentence tradeoff summary. Click to expand. Full detail view has side-by-side 2D plan and 3D walkthrough, tabs for Costs / Code / Contractor package, "Refine with chat" input at bottom.

**Render generation**: modal with style + angle pickers, 15-30s wait, saved to project.

**Design direction**: warm study-model 3D, stylized editorial-line-art 2D plans, dark Atlas UI chrome, crown-jewel AI photoreal renders.

## 5. Session sequence

- **Session 0** — Research + architecture commitment (1 session)
- **Session 1** — Chat homepage + intake, kitchen path only (1 session)
- **Session 2** — Constraint library + jurisdiction lookup (1 session)
- **Session 3a** — Generation engine: solver (1 session)
- **Session 3b** — Generation engine: integration with intake (1 session)
- **Session 4** — Validation pipeline (1 session)
- **Session 5** — Ranking + top-3 surfacing (1 session)
- **Session 6** — 2D plan rendering (1 session)
- **Session 7** — AI photoreal rendering (1 session)
- **Session 8** — Contractor package + cost estimation (1 session)
- **Session 9** — Refinement loop (1 session)

Total: 11 sessions. At current cadence, 8-14 weeks.

Each session produces an incrementally-better product users can try. After session 1 users can talk to Atlas about kitchens; after session 5 they see three candidate plans; after session 7 they see photoreal renders; after session 9 they can iterate.

### Session acceptance criteria

**S0**: architecture doc committed; every subsystem has a named implementation approach; library choices evaluated against alternatives.

**S1**: any kitchen scenario produces a well-structured brief; Atlas asks good clarifying questions; all required fields populated before proceeding.

**S2**: given any US address, Atlas returns an accurate ConstraintSet with every constraint cited.

**S3a+b**: given a KitchenBrief, system produces 20-50 candidate layouts; manual spot-check shows they're kitchen-shaped with no gross violations.

**S4**: on 10 test briefs, generation+validation produces 3+ survivors each; manual review confirms survivors pass code and ergonomic rules.

**S5**: ranking produces stable, defensible top-3 with tradeoffs a human architect would agree with.

**S6**: 2D plan output is something a homeowner would save to PDF and share with a contractor.

**S7**: photoreal render in <30s that clearly depicts the layout in chosen style; first reaction is "this is my kitchen."

**S8**: cost estimates with visible methodology; contractor package would materially help a homeowner hire better.

**S9**: 5+ refinement cycles without quality degradation.

## 6. Risk register

1. **Generation quality below competitors** — mitigate via S0 benchmarks; don't ship until matched.
2. **Code lookup wrong for some jurisdictions** — transparency layer, honest "please verify" messaging for edge cases.
3. **AI costs eat margins** — target under $2 per full design cycle; monitor from day 1.
4. **Render quality inconsistent** — quality gate in S7; re-roll automatically.
5. **Scope creep to other project types** — this plan document; every session checks against it.
6. **Constraint solver insufficient** — S0 research validates; fallbacks on the table.

## 7. Measurement targets

- Generation success rate: >95% of briefs produce 3+ valid candidates
- Code compliance accuracy: zero false-passes on 50 manually reviewed outputs
- User completion rate (demo): >70% from start to render
- Render quality: pass by 2/3 evaluators on 100-render sample
- Cost estimate accuracy: within ±20% on 10+ real kitchens
- Refinement convergence: 5+ cycles without degradation

## 8. Related work that stays alive

The 3D viewer (Model3DCanvas), DXF extraction pipeline, demo account, auth system, test harness safety — all continue to matter. Extraction becomes the "I already have drawings, analyze them" path for remodel users with existing DXFs. The 3D viewer is the rendering surface for every generated layout.

## 9. Open questions for session 0

1. Which constraint programming library (OR-Tools, MiniZinc, Z3, custom)?
2. Which AI rendering provider (SD via Replicate, SD self-hosted, Flux via Fal, Firefly)?
3. Which jurisdictions prioritize for detailed code coverage (starting hypothesis: Chicago suburbs + top-20 US metro areas)?

## 10. Out of scope for this plan

Marketing iterations, pricing/billing, sales, V2+ project types, enterprise/team features, mobile app. All real, all important, all separate from this document.
