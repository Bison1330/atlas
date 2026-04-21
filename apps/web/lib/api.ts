/**
 * Typed wrapper around the Atlas HTTP API.
 *
 * Types here intentionally mirror the Pydantic models in
 * `atlas_core.ingest` and `apps/api/app/schemas`. Keep them in sync —
 * they're the contract between the worker, the API, and the UI.
 *
 * M7 auth integration: every browser fetch goes through
 * :func:`fetchApi`, which sets ``credentials: "include"`` so session
 * + CSRF cookies travel on the same origin, and injects the
 * ``X-Atlas-CSRF`` double-submit header on mutations. Server-side
 * fetches (RSC) go through a separate helper in ``api-server.ts``
 * that forwards the incoming request's Cookie header explicitly.
 */

// Same-origin path; Next.js `rewrites()` in next.config.mjs proxies
// /api/* to INTERNAL_API_URL. Behind Caddy in prod, Caddy strips /api
// before forwarding. Either way: the browser sees one origin, and
// cookies Just Work.
export const API_BASE = "/api";

// HTTP methods that require the CSRF double-submit header (matches
// the API's require_csrf dep — GET/HEAD/OPTIONS bypass).
const MUTATING_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

/** Read a browser cookie by name. Client-only — server never has `document`. */
function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

/**
 * Centralized browser fetch wrapper. All client-side API calls should
 * go through this — it handles credentials + CSRF + error coercion
 * uniformly. Server components use `lib/api-server.ts` instead.
 */
export async function fetchApi(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (MUTATING_METHODS.has(method)) {
    const csrf = readCookie("atlas_csrf");
    if (csrf) headers.set("X-Atlas-CSRF", csrf);
  }
  return fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });
}

export type IngestStatus =
  | "queued"
  | "validating"
  | "rasterizing"
  | "tiling"
  | "completed"
  | "failed";

export const TERMINAL_STATUSES: ReadonlySet<IngestStatus> = new Set([
  "completed",
  "failed",
]);

export interface DrawingStatus {
  id: string;
  status: IngestStatus;
  progress_percent: number;
  progress_message: string | null;
  error_code: string | null;
  error_message: string | null;
  page_count: number | null;
}

export interface SheetSummary {
  id: string;
  page_number: number;
  sheet_number: string | null;
  title: string | null;
  discipline: string | null;
  width_px: number | null;
  height_px: number | null;
  dpi: number | null;
  tile_size: number | null;
  max_zoom: number | null;
  preview_s3_key: string | null;
  status: IngestStatus;
  progress_percent: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface DrawingSummary {
  id: string;
  project_name: string | null;
  source_filename: string;
  size_bytes: number;
  content_hash: string;
  page_count: number | null;
  status: IngestStatus;
  progress_percent: number;
  progress_message: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  failed_at: string | null;
  sheets: SheetSummary[];
}

export interface IngestStatusEvent {
  drawing_id: string;
  sheet_id: string | null;
  status: IngestStatus;
  progress_percent: number;
  message: string | null;
  error_code: string | null;
  at: string;
}

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
  request_id?: string;
}

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;

  constructor(status: number, payload: { error?: ApiError } | ApiError | string) {
    let code = "unknown";
    let message = "Unexpected error";
    let requestId: string | undefined;
    if (typeof payload === "string") {
      message = payload;
    } else if ("error" in payload && payload.error) {
      code = payload.error.code;
      message = payload.error.message;
      requestId = payload.error.request_id;
    } else if ("code" in payload) {
      code = payload.code;
      message = payload.message;
      requestId = payload.request_id;
    }
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

async function parseError(res: Response): Promise<ApiClientError> {
  try {
    const body = await res.json();
    return new ApiClientError(res.status, body);
  } catch {
    return new ApiClientError(res.status, res.statusText || "Request failed");
  }
}

/** XHR upload with session + CSRF, mirroring fetchApi behaviour. */
function sendUploadXhr<T>(
  url: string,
  form: FormData,
  opts: { signal?: AbortSignal; onProgress?: (loaded: number, total: number) => void } = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";
    xhr.withCredentials = true;
    const csrf = readCookie("atlas_csrf");
    if (csrf) xhr.setRequestHeader("X-Atlas-CSRF", csrf);
    if (opts.onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) opts.onProgress!(e.loaded, e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as T);
      } else {
        reject(new ApiClientError(xhr.status, xhr.response ?? xhr.statusText));
      }
    };
    xhr.onerror = () => reject(new ApiClientError(0, "Network error"));
    xhr.onabort = () => reject(new ApiClientError(0, "Upload cancelled"));
    if (opts.signal) {
      opts.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(form);
  });
}


export async function uploadDrawing(
  file: File,
  opts: { projectName?: string; signal?: AbortSignal; onProgress?: (loaded: number, total: number) => void } = {},
): Promise<DrawingSummary> {
  // XHR (not fetch) because request-body progress events aren't yet
  // portable across browsers via the streams API. XHR's upload.onprogress
  // gives us the bytes-transferred number for the upload UI.
  const form = new FormData();
  form.append("file", file);
  if (opts.projectName) form.append("project_name", opts.projectName);
  return sendUploadXhr<DrawingSummary>(
    `${API_BASE}/drawings/upload`,
    form,
    opts,
  );
}

export async function getDrawingStatus(id: string, signal?: AbortSignal): Promise<DrawingStatus> {
  const res = await fetchApi(`/drawings/${id}/status`, { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getDrawing(id: string, signal?: AbortSignal): Promise<DrawingSummary> {
  const res = await fetchApi(`/drawings/${id}`, { signal });
  if (!res.ok && res.status !== 202) throw await parseError(res);
  return res.json();
}


export interface DrawingListItem {
  id: string;
  source_filename: string;
  project_name: string | null;
  project_id: string | null;
  is_owner: boolean;
  status: IngestStatus;
  progress_percent: number;
  page_count: number | null;
  size_bytes: number;
  created_at: string;
  updated_at: string;
}


export interface DrawingListResponse {
  count: number;
  drawings: DrawingListItem[];
}


export async function listDrawings(signal?: AbortSignal): Promise<DrawingListResponse> {
  const res = await fetchApi("/drawings", { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export function previewUrl(drawingId: string, sheetId: string): string {
  return `${API_BASE}/drawings/${drawingId}/sheets/${sheetId}/preview.webp`;
}

/** Whether a sheet carries the full set of metadata required by the
 * deep-zoom tile viewer. DXF-sourced drawings skip the rasterize +
 * tile pipeline, so ``width_px / height_px / max_zoom / tile_size``
 * are all NULL. Use this to pick the default viewer mode and gate
 * the 2D pill — attempting to open OpenSeadragon against a
 * tile-less sheet is what produced the "VIEWER ERROR" the external
 * review flagged. */
export function sheetHas2DTiles(sheet: SheetSummary): boolean {
  return (
    sheet.width_px != null &&
    sheet.height_px != null &&
    sheet.max_zoom != null &&
    sheet.tile_size != null
  );
}

export function tileUrl(
  drawingId: string,
  sheetId: string,
  zoom: number,
  col: number,
  row: number,
): string {
  return `${API_BASE}/drawings/${drawingId}/sheets/${sheetId}/tiles/${zoom}/${col}/${row}.webp`;
}

// ---------- M2: extractions + elements ----------

export type ExtractionStatus = "queued" | "running" | "completed" | "failed";

export const EXTRACTION_TERMINAL: ReadonlySet<ExtractionStatus> = new Set([
  "completed",
  "failed",
]);

export interface ExtractionRunSummary {
  id: string;
  drawing_id: string;
  source_kind: string;
  producer_name: string;
  producer_version: string;
  status: ExtractionStatus;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  params: Record<string, unknown>;
  summary: Record<string, unknown>;
}

export interface ElementSummary {
  id: string;
  sheet_id: string;
  source_id: string;
  kind: string;
  name: string | null;
  number: string | null;
  confidence: number | null;
  ifc_type: string | null;
  ncs_layer: string | null;
  ncs_major_group: string | null;
  ncs_minor_group: string | null;
  bbox: { minx: number; miny: number; maxx: number; maxy: number } | null;
  host_element_id: string | null;
}

export interface ElementDetail extends ElementSummary {
  geometry: Record<string, unknown>;
  attrs: Record<string, unknown>;
  ifc_properties: Record<string, Record<string, unknown>>;
}

export async function uploadDxf(
  drawingId: string,
  file: File,
  opts: {
    signal?: AbortSignal;
    onProgress?: (loaded: number, total: number) => void;
  } = {},
): Promise<ExtractionRunSummary> {
  const form = new FormData();
  form.append("file", file);
  return sendUploadXhr<ExtractionRunSummary>(
    `${API_BASE}/drawings/${drawingId}/extract`,
    form,
    opts,
  );
}

export async function getExtractions(
  drawingId: string,
  signal?: AbortSignal,
): Promise<{ drawing_id: string; count: number; extractions: ExtractionRunSummary[] }> {
  const res = await fetchApi(`/drawings/${drawingId}/extractions`, { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export interface GetElementsOpts {
  source_id?: string;
  kind?: string[];
  ncs_major_group?: string[];
  include?: ("geometry")[];
  limit?: number;
  signal?: AbortSignal;
}

export async function getElements(
  drawingId: string,
  opts: GetElementsOpts = {},
): Promise<{
  drawing_id: string;
  count: number;
  elements: (ElementSummary | ElementDetail)[];
}> {
  const params = new URLSearchParams();
  if (opts.source_id) params.append("source_id", opts.source_id);
  for (const k of opts.kind ?? []) params.append("kind", k);
  for (const g of opts.ncs_major_group ?? []) params.append("ncs_major_group", g);
  for (const i of opts.include ?? []) params.append("include", i);
  if (opts.limit != null) params.append("limit", String(opts.limit));
  const q = params.toString();
  const url = `/drawings/${drawingId}/elements${q ? `?${q}` : ""}`;
  const res = await fetchApi(url, { signal: opts.signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// ---------- M3: takeoffs ----------

export interface TakeoffSubcategory {
  label: string;
  count: number;
  linear_units: number | null;
  area_units: number | null;
}

export interface TakeoffCategory {
  kind: string;
  label: string;
  count: number;
  total_linear_units: number | null;
  total_area_units: number | null;
  subcategories: TakeoffSubcategory[];
}

export interface TakeoffUnits {
  linear: string;
  area: string;
  note: string;
}

export interface TakeoffReport {
  drawing_id: string;
  source_id: string | null;
  generated_at: string;
  total_elements: number;
  kinds_present: string[];
  categories: TakeoffCategory[];
  units: TakeoffUnits;
}

export async function getTakeoffs(
  drawingId: string,
  opts: { source_id?: string; signal?: AbortSignal } = {},
): Promise<TakeoffReport> {
  const params = new URLSearchParams();
  if (opts.source_id) params.append("source_id", opts.source_id);
  const q = params.toString();
  const url = `/drawings/${drawingId}/takeoffs${q ? `?${q}` : ""}`;
  const res = await fetchApi(url, { signal: opts.signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


// ---------- M5: Q&A ----------


export type AnswerBucket =
  | "count"
  | "quantity"
  | "rank"
  | "adjacency"
  | "lookup"
  | "unsupported";


export type AnswerCertainty = "high" | "medium" | "low";


export interface AskCitation {
  element_id: string;
  sheet_id: string;
  kind: string;
  ncs_layer: string | null;
  bbox: { minx: number; miny: number; maxx: number; maxy: number } | null;
  display_label: string;
}


export interface AskResponse {
  answer: string;
  answer_type: AnswerBucket;
  citations: AskCitation[];
  query_interpretation: {
    bucket: string;
    filter: Record<string, unknown>;
    unsupported_reason: string | null;
    suggested_phrasing: string | null;
  };
  confidence: {
    extraction_min: number | null;
    answer_certainty: AnswerCertainty;
  };
  meta: {
    source_id: string | null;
    extraction_status: string;
    interpreter_model: string | null;
  };
}


export async function askDrawing(
  drawingId: string,
  question: string,
  opts: { signal?: AbortSignal } = {},
): Promise<AskResponse> {
  const res = await fetchApi(`/drawings/${drawingId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal: opts.signal,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


// ---------- M8: projects ----------


export interface ProjectSummary {
  id: string;
  name: string;
  description: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}


export interface ProjectMember {
  user_id: string;
  email: string;
  display_name: string | null;
  joined_at: string;
}


export interface ProjectDetail extends ProjectSummary {
  member_count: number;
  drawing_count: number;
  members: ProjectMember[];
  warnings: { flat_membership: boolean };
}


export interface ProjectListResponse {
  projects: ProjectSummary[];
}


export async function listProjects(signal?: AbortSignal): Promise<ProjectListResponse> {
  const res = await fetchApi("/projects", { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function createProject(
  body: { name: string; description?: string },
  signal?: AbortSignal,
): Promise<ProjectDetail> {
  const res = await fetchApi("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function getProject(
  id: string,
  signal?: AbortSignal,
): Promise<ProjectDetail> {
  const res = await fetchApi(`/projects/${id}`, { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function assignDrawingToProject(
  drawingId: string,
  projectId: string | null,
  signal?: AbortSignal,
): Promise<{ drawing_id: string; project_id: string | null }> {
  const res = await fetchApi(`/drawings/${drawingId}/project`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


// ---------- M7: auth ----------


export interface AuthUser {
  id: string;
  email: string;
  email_verified: boolean;
  display_name: string | null;
  is_active: boolean;
  is_demo: boolean;
  last_login_at: string | null;
}


export async function authRegister(
  body: { email: string; password: string; display_name?: string },
  signal?: AbortSignal,
): Promise<AuthUser> {
  const res = await fetchApi("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function authLogin(
  body: { email: string; password: string },
  signal?: AbortSignal,
): Promise<AuthUser> {
  const res = await fetchApi("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function authLogout(signal?: AbortSignal): Promise<void> {
  const res = await fetchApi("/auth/logout", { method: "POST", signal });
  if (!res.ok) throw await parseError(res);
}


/** Start a session for the shared demo account. No credentials required;
 * server-side the endpoint only grants access when the single allow-listed
 * demo user exists with ``is_demo=true``. */
export async function authDemoLogin(signal?: AbortSignal): Promise<AuthUser> {
  const res = await fetchApi("/auth/demo-login", { method: "POST", signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}


export async function authMe(signal?: AbortSignal): Promise<AuthUser> {
  const res = await fetchApi("/auth/me", { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}
