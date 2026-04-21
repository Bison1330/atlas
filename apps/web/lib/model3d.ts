/**
 * Typed client for GET /drawings/:id/sheets/:id/model3d.
 *
 * Interfaces mirror the Pydantic models in
 * ``atlas_core.reconstruct3d`` (``Scene3D`` / ``BBox3`` / ``WallMesh`` /
 * ``FloorSlab`` / ``Opening``) and
 * ``apps/api/app/routes/model3d`` (``Model3DResponse`` / ``Model3DStats``).
 *
 * The endpoint is Redis-cached for 24h and serves ``ETag`` + ``304
 * Not Modified``, so the browser's default ``fetch`` handles repeat
 * visits for free — no manual ETag threading needed here.
 */

import { API_BASE, ApiClientError, type ApiError } from "./api";

export interface BBox3 {
  min: [number, number, number];
  max: [number, number, number];
}

export interface WallMesh {
  id: string;
  parent_wall_id: string;
  vertices: number[];
  indices: number[];
  room_ids: string[];
}

export interface FloorSlab {
  room_id: string;
  name: string | null;
  vertices: number[];
  indices: number[];
  centroid: [number, number, number];
  area_m2: number;
}

export interface Opening {
  id: string;
  kind: "door" | "window";
  wall_id: string;
  room_ids: string[];
  bbox: BBox3;
  failed: boolean;
}

export interface Scene3D {
  units: "m";
  bbox: BBox3;
  walls: WallMesh[];
  floors: FloorSlab[];
  openings: Opening[];
}

export interface Model3DStats {
  wall_count: number;
  floor_count: number;
  opening_count: number;
  failed_opening_count: number;
  vertex_count: number;
  triangle_count: number;
  generation_ms: number;
  missing_door_width: number;
  missing_window_width: number;
  missing_wall_thickness: number;
  synthesized_insert_bbox: number;
  unhostable_openings: number;
  dropped_elements: number;
}

export interface Model3DResponse {
  drawing_id: string;
  sheet_id: string;
  scene: Scene3D;
  stats: Model3DStats;
}

export async function getModel3D(
  drawingId: string,
  sheetId: string,
  signal?: AbortSignal,
): Promise<Model3DResponse> {
  const res = await fetch(
    `${API_BASE}/drawings/${drawingId}/sheets/${sheetId}/model3d`,
    { credentials: "include", signal },
  );
  if (!res.ok) {
    let body: { error?: ApiError } | ApiError | string;
    try {
      body = await res.json();
    } catch {
      body = res.statusText || "Request failed";
    }
    throw new ApiClientError(res.status, body);
  }
  return res.json();
}
