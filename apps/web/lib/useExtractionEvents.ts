/**
 * Live event feed for a single extraction run.
 *
 * Subscribes to ``/ws/drawings/{drawingId}`` (the same channel that
 * carries ingest events) and filters for ``extraction.*`` event
 * types matching the given ``sourceId``. Two reasons this isn't
 * folded into ``useDrawingProgress``:
 *
 * - ``useDrawingProgress`` tears the connection down once the ingest
 *   reaches a terminal status. Extraction can begin long after — we
 *   don't want a closed socket then.
 * - Different payload shape (extraction events are bare dicts with a
 *   ``type`` discriminator; ingest events are typed
 *   ``IngestStatusEvent`` payloads). Mixing them in one hook adds
 *   variance with little reuse.
 *
 * Re-uses the same exponential-backoff reconnection logic as the
 * ingest hook. Closes the connection cleanly once the latest
 * extraction event for ``sourceId`` is terminal.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, EXTRACTION_TERMINAL, ExtractionStatus } from "./api";

export interface ExtractionEvent {
  type: string;
  drawing_id: string;
  source_id: string;
  // Optional payload fields; presence depends on the event type.
  producer?: string;
  elements_so_far?: number;
  summary?: Record<string, unknown>;
  duration_seconds?: number;
  error_code?: string;
  error_message?: string;
  filename?: string;
  size_bytes?: number;
  at?: string;
  receivedAt: number; // local-time tracking for the UI list
}

type ServerMessage =
  | { type: "snapshot"; event: Record<string, unknown> }
  | { type: "event"; event: Record<string, unknown> }
  | { type: "ping"; at: string };

export type ConnectionState =
  | { kind: "connecting"; attempt: number }
  | { kind: "open" }
  | { kind: "reconnecting"; attempt: number; nextRetryMs: number }
  | { kind: "closed"; reason: string }
  | { kind: "done" };

export interface ExtractionEventsState {
  events: ExtractionEvent[];
  status: ExtractionStatus | null;
  connection: ConnectionState;
}

const MAX_LOG = 200;
const MAX_BACKOFF_MS = 15_000;

function wsUrl(drawingId: string): string {
  const u = new URL(`/ws/drawings/${drawingId}`, API_BASE);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  return u.toString();
}

function backoffMs(attempt: number): number {
  const base = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt);
  const jitter = base * (0.75 + Math.random() * 0.5);
  return Math.round(jitter);
}

/** Map ``extraction.*`` event type → ExtractionStatus. */
function statusFromEventType(type: string): ExtractionStatus | null {
  switch (type) {
    case "extraction.queued":
      return "queued";
    case "extraction.started":
    case "extraction.progress":
      return "running";
    case "extraction.completed":
      return "completed";
    case "extraction.failed":
      return "failed";
    default:
      return null;
  }
}

export function useExtractionEvents(
  drawingId: string,
  sourceId: string | null,
): ExtractionEventsState {
  const [events, setEvents] = useState<ExtractionEvent[]>([]);
  const [status, setStatus] = useState<ExtractionStatus | null>(null);
  const [connection, setConnection] = useState<ConnectionState>({
    kind: "connecting",
    attempt: 0,
  });

  const lastStatusRef = useRef<ExtractionStatus | null>(null);

  useEffect(() => {
    if (!sourceId) return;

    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      if (
        lastStatusRef.current &&
        EXTRACTION_TERMINAL.has(lastStatusRef.current)
      ) {
        setConnection({ kind: "done" });
        return;
      }
      setConnection({ kind: "connecting", attempt });

      try {
        socket = new WebSocket(wsUrl(drawingId));
      } catch (err) {
        scheduleRetry(`Could not open WebSocket: ${(err as Error).message}`);
        return;
      }

      socket.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setConnection({ kind: "open" });
      };

      socket.onmessage = (e) => {
        if (cancelled) return;
        let msg: ServerMessage;
        try {
          msg = JSON.parse(e.data) as ServerMessage;
        } catch {
          return;
        }
        if (msg.type === "ping") return;
        const payload = msg.event;
        if (!payload || typeof payload !== "object") return;
        const eventType = (payload as { type?: string }).type;
        // Filter to extraction events for OUR source.
        if (!eventType || !eventType.startsWith("extraction.")) return;
        if (
          (payload as { source_id?: string }).source_id &&
          (payload as { source_id?: string }).source_id !== sourceId
        ) {
          return;
        }

        const event: ExtractionEvent = {
          ...(payload as unknown as ExtractionEvent),
          receivedAt: Date.now(),
        };

        const newStatus = statusFromEventType(eventType);
        if (newStatus) {
          lastStatusRef.current = newStatus;
          setStatus(newStatus);
        }

        setEvents((prev) => {
          const next = prev.concat(event);
          return next.length > MAX_LOG ? next.slice(-MAX_LOG) : next;
        });

        if (newStatus && EXTRACTION_TERMINAL.has(newStatus)) {
          setConnection({ kind: "done" });
        }
      };

      socket.onclose = (e) => {
        if (cancelled) return;
        if (
          lastStatusRef.current &&
          EXTRACTION_TERMINAL.has(lastStatusRef.current)
        ) {
          setConnection({ kind: "done" });
          return;
        }
        if (e.code === 4004) {
          setConnection({ kind: "closed", reason: "Drawing not found" });
          return;
        }
        scheduleRetry(`Connection closed (${e.code})`);
      };

      socket.onerror = () => {
        // onclose follows; handle retry there.
      };
    };

    const scheduleRetry = (reason: string) => {
      if (cancelled) return;
      attempt += 1;
      const wait = backoffMs(attempt);
      setConnection({ kind: "reconnecting", attempt, nextRetryMs: wait });
      retryTimer = setTimeout(connect, wait);
      // eslint-disable-next-line no-console
      console.warn(
        `[atlas] extraction ws ${drawingId}/${sourceId}: ${reason} — retry in ${wait}ms`,
      );
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (socket) {
        socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
        if (
          socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING
        ) {
          socket.close();
        }
      }
    };
  }, [drawingId, sourceId]);

  return { events, status, connection };
}
