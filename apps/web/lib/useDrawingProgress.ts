/**
 * Live progress feed for a single drawing.
 *
 * Subscribes to the API's WebSocket endpoint at `/ws/drawings/{id}`,
 * which emits messages of three shapes:
 *
 *   { type: "snapshot", event: IngestStatusEvent }   // sent once on connect
 *   { type: "event",    event: IngestStatusEvent }   // every state change
 *   { type: "ping",     at: ISO8601 }                // ~every 20s
 *
 * The hook surfaces:
 *   - the most recent IngestStatusEvent (the "current" snapshot),
 *   - a bounded log of all events for the live event stream,
 *   - a connection state with retry attempts (so the UI can say
 *     "reconnecting…" instead of silently freezing).
 *
 * Reconnection is exponential backoff with jitter, capped at 15s.
 * The hook stops trying once a terminal status (`completed`/`failed`)
 * is reached — there's nothing more to listen for.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, IngestStatusEvent, TERMINAL_STATUSES } from "./api";

type ServerMessage =
  | { type: "snapshot"; event: IngestStatusEvent }
  | { type: "event"; event: IngestStatusEvent }
  | { type: "ping"; at: string };

export type ConnectionState =
  | { kind: "connecting"; attempt: number }
  | { kind: "open" }
  | { kind: "reconnecting"; attempt: number; nextRetryMs: number }
  | { kind: "closed"; reason: string }
  | { kind: "done" };

export interface DrawingProgressState {
  current: IngestStatusEvent | null;
  events: IngestStatusEvent[];
  connection: ConnectionState;
}

const MAX_LOG = 200;
const MAX_BACKOFF_MS = 15_000;

function wsUrl(drawingId: string): string {
  // Same origin as the HTTP API, just swapped scheme.
  const u = new URL(`/ws/drawings/${drawingId}`, API_BASE);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  return u.toString();
}

function backoffMs(attempt: number): number {
  // 500ms, 1s, 2s, 4s, ... capped at 15s; ±25% jitter.
  const base = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt);
  const jitter = base * (0.75 + Math.random() * 0.5);
  return Math.round(jitter);
}

export function useDrawingProgress(drawingId: string): DrawingProgressState {
  const [current, setCurrent] = useState<IngestStatusEvent | null>(null);
  const [events, setEvents] = useState<IngestStatusEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>({
    kind: "connecting",
    attempt: 0,
  });

  // Keep a ref to the most recent status so the connect loop can
  // bail out as soon as we hit a terminal state.
  const lastStatusRef = useRef<IngestStatusEvent | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      if (
        lastStatusRef.current &&
        TERMINAL_STATUSES.has(lastStatusRef.current.status)
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
        const event = msg.event;
        lastStatusRef.current = event;
        setCurrent(event);
        setEvents((prev) => {
          const next = prev.concat(event);
          return next.length > MAX_LOG ? next.slice(-MAX_LOG) : next;
        });
        if (TERMINAL_STATUSES.has(event.status)) {
          // Server will close after the terminal event flushes — but
          // we mark "done" eagerly so the UI can stop showing "live".
          setConnection({ kind: "done" });
        }
      };

      socket.onclose = (e) => {
        if (cancelled) return;
        if (
          lastStatusRef.current &&
          TERMINAL_STATUSES.has(lastStatusRef.current.status)
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
        // onerror precedes onclose; let onclose handle the retry.
      };
    };

    const scheduleRetry = (reason: string) => {
      if (cancelled) return;
      attempt += 1;
      const wait = backoffMs(attempt);
      setConnection({ kind: "reconnecting", attempt, nextRetryMs: wait });
      retryTimer = setTimeout(connect, wait);
      // eslint-disable-next-line no-console
      console.warn(`[atlas] ws ${drawingId}: ${reason} — retry in ${wait}ms`);
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (socket) {
        socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
          socket.close();
        }
      }
    };
  }, [drawingId]);

  return { current, events, connection };
}
