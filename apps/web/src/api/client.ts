/**
 * Typed API client for the Mini-OpenClaw backend.
 * All functions match the endpoints defined in 05-api-spec.md.
 */

import type { Run, MemoryItem, MemoryType, ToolManifest } from "./types";

const API_BASE = "/api";

/** Shared fetch wrapper with error handling. */
async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    let message = `API error ${res.status}`;
    try {
      const parsed = JSON.parse(body);
      message = parsed?.error?.message ?? parsed?.detail ?? message;
    } catch {
      // use status message
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

// ── Chat ──────────────────────────────────────────────

export async function submitChat(
  sessionId: string,
  message: string,
  workspaceId: string = "default"
): Promise<{ run_id: string; status: string }> {
  return apiFetch("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
      workspace_id: workspaceId,
    }),
  });
}

// ── Runs ──────────────────────────────────────────────

export async function getRun(runId: string): Promise<Run> {
  return apiFetch(`/runs/${runId}`);
}

export async function getRuns(
  sessionId: string,
  limit: number = 50
): Promise<Run[]> {
  return apiFetch(`/runs?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`);
}

export async function approveStep(
  runId: string,
  stepId: string
): Promise<void> {
  await apiFetch(`/runs/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({ step_id: stepId, approved: true }),
  });
}

export async function rejectStep(
  runId: string,
  stepId: string
): Promise<void> {
  await apiFetch(`/runs/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({ step_id: stepId, approved: false }),
  });
}

export async function cancelRun(runId: string): Promise<void> {
  await apiFetch(`/runs/${runId}/cancel`, { method: "POST" });
}

// ── Memory ────────────────────────────────────────────

export async function getMemory(
  workspaceId: string = "default",
  type?: MemoryType,
  limit: number = 100
): Promise<MemoryItem[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId, limit: String(limit) });
  if (type) params.set("memory_type", type);
  return apiFetch(`/memory?${params}`);
}

export async function searchMemory(
  query: string,
  type?: MemoryType,
  limit: number = 10
): Promise<MemoryItem[]> {
  return apiFetch("/memory/search", {
    method: "POST",
    body: JSON.stringify({ query, memory_type: type, limit }),
  });
}

export async function deleteMemoryItem(id: string): Promise<void> {
  await apiFetch(`/memory/${id}`, { method: "DELETE" });
}

// ── Tools ─────────────────────────────────────────────

export async function getTools(): Promise<ToolManifest[]> {
  return apiFetch("/tools");
}

// ── Health ────────────────────────────────────────────

export async function healthCheck(): Promise<{ status: string }> {
  return apiFetch("/health");
}
