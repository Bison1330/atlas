"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, OrbitControls, PerspectiveCamera, Plane } from "@react-three/drei";
import {
  EffectComposer,
  SMAA,
  SSAO,
  ToneMapping,
  Vignette,
} from "@react-three/postprocessing";
import { BlendFunction, ToneMappingMode } from "postprocessing";
import * as THREE from "three";

import type { SheetSummary } from "@/lib/api";
import {
  getModel3D,
  type FloorSlab,
  type Model3DResponse,
  type Scene3D,
  type WallMesh,
} from "@/lib/model3d";
import { STUDY_MODEL_PALETTE as P } from "./studyModelPalette";

interface Props {
  drawingId: string;
  sheet: SheetSummary;
}

type PitchMode = "FLOOR PLAN" | "DOLLHOUSE" | "3D";

/**
 * 3D model viewer for a single extracted sheet.
 *
 * Pitch-unified mode: one 3D canvas where the camera's polar angle
 * continuously blends between dollhouse (shallow pitch) and floor-
 * plan (near-vertical pitch). No separate "floor plan" button —
 * pitching the camera IS the mode switch. Matches the Matterport
 * interaction pattern; the ``modeLabel`` HUD chip names whichever
 * region the current pitch lands in.
 *
 * Materials follow a study-model aesthetic (warm off-white walls,
 * AO-driven structural reading, ACES tonemap, subtle vignette)
 * borrowed from D5 Render's Clay Mode and Enscape's White Mode.
 * Details in ``studyModelPalette.ts``.
 *
 * Session-3 scope: geometry, materials, camera, HUD stats, labels.
 * Walk mode, click-to-inspect, per-story cutaway, camera bookmarks,
 * and narration all land in later sessions.
 */
export function Model3DCanvas({ drawingId, sheet }: Props) {
  const [data, setData] = useState<Model3DResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    getModel3D(drawingId, sheet.id, ctrl.signal)
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        setData(resp);
        // Perf guardrails — session 3 doesn't add LOD/culling, but
        // these logs give us the signal to watch for when it's time.
        const { vertex_count, triangle_count } = resp.stats;
        console.info(
          `[model3d] scene loaded: ${vertex_count} vertices, ${triangle_count} triangles`,
        );
        if (vertex_count > 100_000 || triangle_count > 50_000) {
          console.warn(
            `[model3d] scene exceeds soft perf threshold (${vertex_count}v / ${triangle_count}t). ` +
              `Future work: LOD / frustum culling.`,
          );
        }
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Failed to load 3D scene.");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [drawingId, sheet.id]);

  if (loading) {
    return (
      <ShellContainer>
        <CenteredChip>
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
          <span className="font-mono text-[11px] uppercase tracking-wider">
            computing 3d model
          </span>
        </CenteredChip>
      </ShellContainer>
    );
  }

  if (error) {
    return (
      <ShellContainer>
        <div className="absolute inset-0 flex items-center justify-center p-3 text-center">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/[0.06] p-3">
            <p className="font-mono text-[11px] uppercase tracking-wider text-rose-300">
              viewer error
            </p>
            <p className="mt-1 text-sm text-text-secondary">{error}</p>
          </div>
        </div>
      </ShellContainer>
    );
  }

  if (!data || (data.scene.walls.length === 0 && data.scene.floors.length === 0)) {
    return (
      <ShellContainer>
        <CenteredChip>
          <span className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
            this sheet has no walls to reconstruct
          </span>
        </CenteredChip>
      </ShellContainer>
    );
  }

  return <SceneShell data={data} />;
}

// ---------------------------------------------------------------------------
// Shell container (matches SheetCanvas styling but darker bg for warm scene)
// ---------------------------------------------------------------------------

function ShellContainer({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-border-subtle bg-black/60">
      {children}
    </div>
  );
}

function CenteredChip({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="flex items-center gap-2 rounded-md border border-border-subtle bg-bg-surface px-3 py-1.5">
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene shell (Canvas + HUD)
// ---------------------------------------------------------------------------

function SceneShell({ data }: { data: Model3DResponse }) {
  const scene = data.scene;
  const stats = data.stats;

  const bboxCenter = useMemo(
    () => centerOf(scene.bbox.min, scene.bbox.max),
    [scene.bbox],
  );
  const diag = useMemo(
    () => Math.max(1, diagOf(scene.bbox.min, scene.bbox.max)),
    [scene.bbox],
  );

  // Camera defaults: dollhouse-ish view, slightly above horizontal,
  // oriented so the sheet's +Y runs away from the viewer.
  const initialCameraPos = useMemo<[number, number, number]>(
    () => [
      bboxCenter[0] + diag * 0.7,
      bboxCenter[1] - diag * 0.7,
      bboxCenter[2] + diag * 0.5,
    ],
    [bboxCenter, diag],
  );

  const controlsRef = useRef<ControlsLike | null>(null);
  const [pitchDeg, setPitchDeg] = useState(55);

  const resetCamera = useCallback(() => {
    const c = controlsRef.current;
    if (!c) return;
    c.object.position.set(...initialCameraPos);
    c.target.set(...bboxCenter);
    c.update();
  }, [initialCameraPos, bboxCenter]);

  // Keyboard: R resets the camera. V is handled upstream in ViewerView
  // because it switches modes (2D ↔ 3D) — this component never sees it.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName)
      )
        return;
      if (e.key === "r" || e.key === "R") resetCamera();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [resetCamera]);

  const modeLabel: PitchMode =
    pitchDeg > 80 ? "FLOOR PLAN" : pitchDeg < 40 ? "DOLLHOUSE" : "3D";

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-border-subtle bg-black/60">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
        onCreated={({ gl }) => {
          gl.setClearColor(new THREE.Color(P.backgroundClear));
        }}
      >
        <PerspectiveCamera
          makeDefault
          position={initialCameraPos}
          up={[0, 0, 1]}
          fov={50}
          near={Math.max(0.01, diag * 0.002)}
          far={diag * 20}
        />
        <OrbitControls
          ref={(ref) => {
            controlsRef.current = ref as ControlsLike | null;
          }}
          enableDamping
          dampingFactor={0.08}
          target={bboxCenter}
          minDistance={diag * 0.05}
          maxDistance={diag * 3}
          maxPolarAngle={Math.PI * 0.99}
          minPolarAngle={0.05}
          makeDefault
        />
        <PitchReporter controlsRef={controlsRef} onChange={setPitchDeg} />

        <Lighting bboxCenter={bboxCenter} diag={diag} />

        {scene.walls.map((wall) => (
          <WallMeshView key={wall.id} wall={wall} />
        ))}
        {scene.floors.map((floor) => (
          <FloorSlabView key={floor.room_id} floor={floor} />
        ))}

        <Plane
          args={[diag * 6, diag * 6]}
          position={[bboxCenter[0], bboxCenter[1], -0.02]}
          receiveShadow
        >
          <meshStandardMaterial
            color={P.ground.color}
            roughness={P.ground.roughness}
          />
        </Plane>

        <EffectComposer multisampling={0}>
          <SSAO
            radius={P.aoRadius}
            intensity={P.aoIntensity * 10}
            luminanceInfluence={0.3}
            blendFunction={BlendFunction.MULTIPLY}
            worldDistanceThreshold={diag * 0.5}
            worldDistanceFalloff={diag * 0.05}
            worldProximityThreshold={diag * 0.01}
            worldProximityFalloff={diag * 0.001}
          />
          {/* Session 5 will introduce selection outlines via
              @react-three/postprocessing's Outline pass (requires a
              selected-objects list). For this session we rely on
              SSAO + silhouette contrast for edge definition, plus
              SMAA for anti-aliasing. */}
          <SMAA />
          <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
          <Vignette offset={0.5} darkness={P.vignette} eskil={false} />
        </EffectComposer>
      </Canvas>

      {/* Top-left: scene stats */}
      <div className="pointer-events-none absolute left-3 top-3 rounded-md border border-border-subtle bg-bg-surface/90 px-2.5 py-1.5 backdrop-blur">
        <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
          {stats.wall_count} walls · {stats.floor_count} rooms · {stats.opening_count} openings
        </span>
      </div>

      {/* Top-right: mode label + reset */}
      <div className="absolute right-3 top-3 flex items-center gap-1.5">
        <div className="rounded-md border border-border-subtle bg-bg-surface/90 px-2.5 py-1.5 backdrop-blur">
          <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            {modeLabel}
          </span>
        </div>
        <button
          type="button"
          onClick={resetCamera}
          title="Reset camera (R)"
          aria-label="Reset camera"
          className="flex items-center justify-center rounded-md border border-border-subtle bg-bg-surface/90 p-1.5 text-text-muted backdrop-blur transition-colors hover:text-accent"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <path d="M3 4v5h5" />
          </svg>
        </button>
      </div>

      {/* Bottom-left: data-quality chip (only when there's something to show) */}
      {hasQualityStats(stats) && (
        <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-border-subtle bg-bg-surface/90 px-2.5 py-1.5 backdrop-blur">
          <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            defaults applied: {stats.missing_wall_thickness} thickness,{" "}
            {stats.missing_door_width + stats.missing_window_width} widths
            {stats.synthesized_insert_bbox > 0 &&
              ` · ${stats.synthesized_insert_bbox} synth bboxes`}
            {stats.unhostable_openings > 0 &&
              ` · ${stats.unhostable_openings} unhostable`}
            {stats.failed_opening_count > 0 &&
              ` · ${stats.failed_opening_count} failed cuts`}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Lighting({
  bboxCenter,
  diag,
}: {
  bboxCenter: [number, number, number];
  diag: number;
}) {
  const sunPos: [number, number, number] = [
    bboxCenter[0] + diag * 1.2,
    bboxCenter[1] - diag * 0.8,
    bboxCenter[2] + diag * 1.5,
  ];
  // Shadow frustum sized to the scene — undersized causes acne,
  // oversized blows out resolution.
  const frustumHalf = diag * 1.2;
  return (
    <>
      <ambientLight intensity={0.15} />
      <hemisphereLight
        args={[P.skyColor, P.groundBounceColor, P.skyIntensity]}
      />
      <directionalLight
        position={sunPos}
        intensity={P.sunIntensity}
        color={P.sunColor}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-bias={-0.0005}
        shadow-camera-near={0.1}
        shadow-camera-far={diag * 6}
        shadow-camera-left={-frustumHalf}
        shadow-camera-right={frustumHalf}
        shadow-camera-top={frustumHalf}
        shadow-camera-bottom={-frustumHalf}
      />
    </>
  );
}

function WallMeshView({ wall }: { wall: WallMesh }) {
  const geometry = useMemo(() => buildGeometry(wall.vertices, wall.indices), [wall]);
  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial
        color={P.interiorWall.color}
        roughness={P.interiorWall.roughness}
        metalness={0}
      />
    </mesh>
  );
}

function FloorSlabView({ floor }: { floor: FloorSlab }) {
  const geometry = useMemo(
    () => buildGeometry(floor.vertices, floor.indices),
    [floor],
  );
  const label = floor.name ?? "Room";
  return (
    <>
      <mesh geometry={geometry} receiveShadow>
        <meshStandardMaterial
          color={P.floor.color}
          roughness={P.floor.roughness}
          metalness={0}
        />
      </mesh>
      <Html
        position={[floor.centroid[0], floor.centroid[1], floor.centroid[2] + 0.05]}
        center
        occlude
        distanceFactor={12}
        zIndexRange={[0, 0]}
      >
        <div className="pointer-events-none -translate-x-1/2 -translate-y-1/2 whitespace-nowrap">
          <div
            className="text-center font-mono text-[11px] uppercase tracking-wider drop-shadow-sm"
            style={{ color: `${P.labelColor}CC` }}
          >
            {label}
          </div>
          <div
            className="text-center font-mono text-[10px]"
            style={{ color: `${P.labelColor}99` }}
          >
            {floor.area_m2.toFixed(1)} m²
          </div>
        </div>
      </Html>
    </>
  );
}

interface ControlsLike {
  object: THREE.Camera;
  target: THREE.Vector3;
  update(): void;
  getPolarAngle(): number;
}

function PitchReporter({
  controlsRef,
  onChange,
}: {
  controlsRef: React.MutableRefObject<ControlsLike | null>;
  onChange: (deg: number) => void;
}) {
  const lastRef = useRef<number>(-1);
  useFrame(() => {
    const c = controlsRef.current;
    if (!c) return;
    const polar = c.getPolarAngle(); // 0 = top-down, pi/2 = horizon
    // Camera pitch in the user's sense: 90° - polar in degrees
    // (90° = looking straight down / "floor plan", 0° = horizon).
    const pitch = 90 - (polar * 180) / Math.PI;
    if (Math.abs(pitch - lastRef.current) > 1) {
      lastRef.current = pitch;
      onChange(pitch);
    }
  });
  return null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildGeometry(vertices: number[], indices: number[]): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(vertices), 3));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

function centerOf(
  min: [number, number, number],
  max: [number, number, number],
): [number, number, number] {
  return [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
}

function diagOf(
  min: [number, number, number],
  max: [number, number, number],
): number {
  const dx = max[0] - min[0];
  const dy = max[1] - min[1];
  const dz = max[2] - min[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function hasQualityStats(stats: Model3DResponse["stats"]): boolean {
  return (
    stats.missing_door_width > 0 ||
    stats.missing_window_width > 0 ||
    stats.missing_wall_thickness > 0 ||
    stats.synthesized_insert_bbox > 0 ||
    stats.unhostable_openings > 0 ||
    stats.dropped_elements > 0 ||
    stats.failed_opening_count > 0
  );
}

// re-exported to satisfy --isolatedModules in some scenarios; harmless.
export type { Scene3D };
