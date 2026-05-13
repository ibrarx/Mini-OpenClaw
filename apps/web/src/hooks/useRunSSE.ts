/**
 * useRunSSE — Subscribe to run updates via Server-Sent Events.
 * Replaces useRunPolling with real-time streaming from GET /api/runs/{id}/stream.
 *
 * Falls back to a single GET fetch after 3 reconnection failures.
 * Provides the same { run, error, refresh } interface as the old polling hook.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { getRun } from "../api/client";
import type { Run, RunStatus } from "../api/types";

const TERMINAL_STATUSES: Set<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

export function useRunSSE(runId: string | null) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const runIdRef = useRef(runId);

  // Keep runId ref in sync for use in callbacks
  runIdRef.current = runId;

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  /** Fetch run state via REST (used for refresh and fallback). */
  const fetchRun = useCallback(async (id: string) => {
    try {
      const data = await getRun(id);
      setRun(data);
      setError(null);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch run");
      return null;
    }
  }, []);

  const connectSSE = useCallback(
    (id: string) => {
      closeEventSource();

      const es = new EventSource(`/api/runs/${id}/stream`);
      eventSourceRef.current = es;

      const handleEvent = (e: MessageEvent) => {
        // If the runId changed while we were connected, ignore stale events
        if (runIdRef.current !== id) {
          es.close();
          return;
        }

        try {
          const data: Run = JSON.parse(e.data);
          setRun(data);
          setError(null);
          retryCountRef.current = 0;

          // Close EventSource on terminal states
          if (TERMINAL_STATUSES.has(data.status)) {
            es.close();
            eventSourceRef.current = null;
          }
        } catch {
          // Ignore parse errors
        }
      };

      // Listen for all named events from the backend
      const eventTypes = [
        "initial",
        "run_created",
        "planning_started",
        "plan_ready",
        "approval_requested",
        "step_completed",
        "run_completed",
        "run_failed",
        "run_cancelled",
        "error",
      ];

      for (const type of eventTypes) {
        es.addEventListener(type, handleEvent);
      }

      // Also handle unnamed "message" events (fallback)
      es.onmessage = handleEvent;

      es.onerror = () => {
        // EventSource auto-reconnects on error, but we want to limit retries
        if (runIdRef.current !== id) {
          es.close();
          eventSourceRef.current = null;
          return;
        }

        retryCountRef.current += 1;

        if (retryCountRef.current >= MAX_RETRIES) {
          es.close();
          eventSourceRef.current = null;
          // Fall back to a single REST fetch
          fetchRun(id).then((data) => {
            if (
              data &&
              !TERMINAL_STATUSES.has(data.status) &&
              runIdRef.current === id
            ) {
              // If still active, try reconnecting after a delay
              setTimeout(() => {
                if (runIdRef.current === id) {
                  retryCountRef.current = 0;
                  connectSSE(id);
                }
              }, RETRY_DELAY_MS * 2);
            }
          });
        }
      };
    },
    [closeEventSource, fetchRun]
  );

  useEffect(() => {
    if (!runId) {
      setRun(null);
      setError(null);
      retryCountRef.current = 0;
      closeEventSource();
      return;
    }

    retryCountRef.current = 0;
    connectSSE(runId);

    return () => {
      closeEventSource();
    };
  }, [runId, connectSSE, closeEventSource]);

  /** Force a single REST refresh (e.g. after approving a step). */
  const refresh = useCallback(() => {
    if (runId) fetchRun(runId);
  }, [runId, fetchRun]);

  return { run, error, refresh };
}
