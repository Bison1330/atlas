/**
 * Typed wrapper around the Atlas HTTP API.
 *
 * Types here intentionally mirror the Pydantic models in
 * `atlas_core.ingest` and `apps/api/app/schemas`. Keep them in sync —
 * they're the contract between the worker, the API, and the UI.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export async function uploadDrawing(
  file: File,
  opts: { projectName?: string; signal?: AbortSignal; onProgress?: (loaded: number, total: number) => void } = {},
): Promise<DrawingSummary> {
  // We use XMLHttpRequest (not fetch) because progress events on
  // request bodies aren't yet portable across all browsers via the
  // streams API. XHR's upload.onprogress is universal and gives us
  // the bytes-transferred number we need for the upload UI.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    if (opts.projectName) form.append("project_name", opts.projectName);

    xhr.open("POST", `${API_BASE}/drawings/upload`);
    xhr.responseType = "json";
    if (opts.onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) opts.onProgress!(e.loaded, e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as DrawingSummary);
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

export async function getDrawingStatus(id: string, signal?: AbortSignal): Promise<DrawingStatus> {
  const res = await fetch(`${API_BASE}/drawings/${id}/status`, { signal });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function getDrawing(id: string, signal?: AbortSignal): Promise<DrawingSummary> {
  const res = await fetch(`${API_BASE}/drawings/${id}`, { signal });
  if (!res.ok && res.status !== 202) throw await parseError(res);
  return res.json();
}

export function previewUrl(drawingId: string, sheetId: string): string {
  return `${API_BASE}/drawings/${drawingId}/sheets/${sheetId}/preview.webp`;
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
