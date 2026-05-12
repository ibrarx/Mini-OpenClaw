/**
 * Poll GET /api/runs/{run_id} while a run is active.
 * Stops when status becomes completed, failed, or cancelled.
 * Tolerates transient fetch failures — only shows error after 3 consecutive failures.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { getRun } from "../api/client";
import type { Run, RunStatus } from "../api/types";

const ACTIVE_STATUSES: Set<RunStatus> = new Set([
  "planning",
  "running",
  "reacting",
  "awaiting_approval",
]);

const POLL_INTERVAL_MS = 1500;
const ERROR_THRESHOLD = 3;

export function useRunPolling(runId: string | null) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failCountRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const fetchRun = useCallback(async (id: string) => {
    try {
      const data = await getRun(id);
      setRun(data);
      setError(null);
      failCountRef.current = 0;

      // Stop polling if the run reached a terminal state
      if (!ACTIVE_STATUSES.has(data.status)) {
        stopPolling();
      }
    } catch (err) {
      failCountRef.current += 1;
      // Only show error after several consecutive failures
      if (failCountRef.current >= ERROR_THRESHOLD) {
        setError(err instanceof Error ? err.message : "Failed to fetch run");
      }
    }
  }, [stopPolling]);

  useEffect(() => {
    if (!runId) {
      setRun(null);
      setError(null);
      failCountRef.current = 0;
      stopPolling();
      return;
    }

    // Immediate first fetch
    fetchRun(runId);

    // Start polling
    timerRef.current = setInterval(() => fetchRun(runId), POLL_INTERVAL_MS);

    return stopPolling;
  }, [runId, fetchRun, stopPolling]);

  /** Force a single refresh (e.g. after approving a step). */
  const refresh = useCallback(() => {
    if (runId) fetchRun(runId);
  }, [runId, fetchRun]);

  return { run, error, refresh };
}
