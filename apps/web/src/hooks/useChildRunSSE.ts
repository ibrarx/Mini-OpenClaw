/**
 * useChildRunSSE — Subscribe to a child run's updates via SSE.
 * Reuses the same /api/runs/{id}/stream endpoint as the parent.
 * Activates only when a child_run_id is provided, auto-closes on terminal state.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { getRun } from "../api/client";
import type { Run, RunStatus } from "../api/types";

const TERMINAL_STATUSES: Set<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export function useChildRunSSE(childRunId: string | null) {
  const [childRun, setChildRun] = useState<Run | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const idRef = useRef(childRunId);
  idRef.current = childRunId;

  const close = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!childRunId) {
      setChildRun(null);
      close();
      return;
    }

    close();

    const es = new EventSource(`/api/runs/${childRunId}/stream`);
    eventSourceRef.current = es;

    const handleEvent = (e: MessageEvent) => {
      if (idRef.current !== childRunId) {
        es.close();
        return;
      }
      try {
        const data: Run = JSON.parse(e.data);
        setChildRun(data);
        if (TERMINAL_STATUSES.has(data.status)) {
          es.close();
          eventSourceRef.current = null;
        }
      } catch {
        // ignore parse errors
      }
    };

    const eventTypes = [
      "initial",
      "run_created",
      "planning_started",
      "plan_ready",
      "approval_requested",
      "step_announced",
      "step_completed",
      "reflection_started",
      "reflection_completed",
      "run_completed",
      "run_failed",
      "run_cancelled",
      "error",
    ];

    for (const type of eventTypes) {
      es.addEventListener(type, handleEvent);
    }
    es.onmessage = handleEvent;

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      // Fallback: single REST fetch
      if (idRef.current === childRunId) {
        getRun(childRunId)
          .then((data) => setChildRun(data))
          .catch(() => {});
      }
    };

    // Safety net REST fetch
    const timer = setTimeout(async () => {
      if (idRef.current === childRunId && eventSourceRef.current === es) {
        const data = await getRun(childRunId).catch(() => null);
        if (data) {
          setChildRun(data);
          if (TERMINAL_STATUSES.has(data.status)) {
            es.close();
            eventSourceRef.current = null;
          }
        }
      }
    }, 2000);

    return () => {
      clearTimeout(timer);
      close();
    };
  }, [childRunId, close]);

  return { childRun };
}
