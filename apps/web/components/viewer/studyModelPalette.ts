/**
 * Study-model palette for the 3D viewer.
 *
 * Values come from research into D5 Render's "Clay Model" and
 * Enscape's "White Mode": warm off-white walls with AO doing the
 * structural reading, cool sky vs. warm sun, subtle vignette, and
 * an off-black outline so edges read without looking cheap.
 *
 * All colors inside the 3D canvas live here; UI chrome outside the
 * canvas uses Atlas's Tailwind tokens (``bg-surface``,
 * ``border-subtle``, ``accent``, ``shadow-glow``). Keeping those
 * worlds separate is deliberate — the warm physical-model scene
 * reads as held inside a cool, architectural-tool frame.
 *
 * When a future session introduces per-element overrides (selected
 * highlight, walk-mode fog, etc.) extend this object rather than
 * inlining new hex codes at call sites.
 */

export const STUDY_MODEL_PALETTE = {
  exteriorWall: { color: "#E8E2D6", roughness: 0.75 },
  interiorWall: { color: "#F2EEE6", roughness: 0.78 },
  floor:        { color: "#C9C2B4", roughness: 0.65 },
  ground:       { color: "#A8A29A", roughness: 0.90 },
  outlineColor: "#2B2723",
  outlineWidth: 1.0,
  creaseColor:  "#3A3630",
  creaseWidth:  0.5,
  aoRadius:     0.12,
  aoIntensity:  0.35,
  sunColor:     "#FFF5E6",
  sunIntensity: 1.4,
  skyColor:     "#E5EEF5",
  skyIntensity: 0.35,
  groundBounceColor: "#1A1A1A",
  vignette: 0.1,
  backgroundClear:   "#0B0D10",
  labelColor:        "#2B2723",
} as const;
