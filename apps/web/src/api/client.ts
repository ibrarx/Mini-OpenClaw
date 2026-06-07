/**
 * Typed API client for the Mini-OpenClaw backend.
 * All functions match the endpoints defined in 05-api-spec.md.
 */

import type { Run, MemoryItem, MemoryType, ToolManifest, ScheduledTask } from "./types";

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

/** Retry a failed or cancelled run by re-submitting its original message. */
export async function retryRun(
  runId: string
): Promise<{ run_id: string; status: string }> {
  return apiFetch(`/chat/retry/${runId}`, { method: "POST" });
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

/** Submit a clarification answer for a run awaiting clarification. */
export async function clarifyRun(
  runId: string,
  answer: string
): Promise<Run> {
  return apiFetch(`/runs/${runId}/clarify`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  });
}

// ── Clarification Settings ───────────────────────────

export interface ClarificationSettings {
  enabled: boolean;
  threshold: number;
  max_rounds: number;
}

export async function getClarificationSettings(): Promise<ClarificationSettings> {
  return apiFetch("/settings/clarification");
}

export async function updateClarificationSettings(
  updates: Partial<ClarificationSettings>
): Promise<ClarificationSettings> {
  return apiFetch("/settings/clarification", {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export type ExplainDetailLevel = "summary" | "detailed" | "debug";

export interface ExplainResult {
  tool_name: string;
  status: string;
  output: {
    run_id: string;
    detail_level: ExplainDetailLevel;
    status: string;
    explanation: string;
  } | null;
  error: string | null;
}

export async function explainRun(
  runId: string,
  detailLevel: ExplainDetailLevel = "summary"
): Promise<ExplainResult> {
  return apiFetch(
    `/runs/${runId}/explain?detail_level=${encodeURIComponent(detailLevel)}`
  );
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

export type SearchMode = "hybrid" | "keyword" | "vector";

export async function searchMemory(
  query: string,
  type?: MemoryType,
  limit: number = 10,
  searchMode: SearchMode = "hybrid"
): Promise<MemoryItem[]> {
  return apiFetch("/memory/search", {
    method: "POST",
    body: JSON.stringify({ query, memory_type: type, limit, search_mode: searchMode }),
  });
}

export async function deleteMemoryItem(id: string): Promise<void> {
  await apiFetch(`/memory/${id}`, { method: "DELETE" });
}

/** Trigger a dream cycle to extract strategies and preferences. */
export async function triggerDream(
  workspaceId: string = "default"
): Promise<{ strategies: number; preferences: number; skipped?: string; error?: string }> {
  return apiFetch(`/memory/dream?workspace_id=${encodeURIComponent(workspaceId)}`, {
    method: "POST",
  });
}

/** Get pending dream insights awaiting user review. */
export async function getPendingInsights(
  workspaceId: string = "default"
): Promise<MemoryItem[]> {
  return apiFetch(`/memory/pending?workspace_id=${encodeURIComponent(workspaceId)}`);
}

/** Accept or reject a pending dream insight. */
export async function reviewInsight(
  itemId: string,
  accepted: boolean,
  editedContent?: string
): Promise<MemoryItem> {
  return apiFetch(`/memory/${itemId}/review`, {
    method: "POST",
    body: JSON.stringify({ accepted, edited_content: editedContent }),
  });
}

// ── Tools ─────────────────────────────────────────────

export async function getTools(): Promise<ToolManifest[]> {
  return apiFetch("/tools");
}

// ── Health ────────────────────────────────────────────

export interface MountInfo {
  name: string;
  path: string;
  read_only: boolean;
  exists: boolean;
}

export interface HealthResponse {
  status: string;
  mounts?: MountInfo[];
}

export async function healthCheck(): Promise<HealthResponse> {
  return apiFetch("/health");
}

// ── Usage ─────────────────────────────────────────────

export interface UsageSummary {
  session_id: string | null;
  run_count: number;
  totals: {
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    cost_usd: number;
    llm_calls: number;
  };
  by_model: Record<
    string,
    {
      input_tokens: number;
      output_tokens: number;
      cost_usd: number;
      llm_calls: number;
      provider: string;
    }
  >;
  by_phase: Record<string, number>;
  has_estimates: boolean;
  pricing_last_verified: string;
}

export async function getUsageSummary(
  sessionId?: string
): Promise<UsageSummary> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const qs = params.toString();
  return apiFetch(`/usage/summary${qs ? `?${qs}` : ""}`);
}

// ── Scheduler ────────────────────────────────────────

export async function getScheduledTasks(
  workspaceId?: string,
  status?: string
): Promise<ScheduledTask[]> {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return apiFetch(`/tasks${qs ? `?${qs}` : ""}`);
}

export async function getScheduledTask(taskId: string): Promise<ScheduledTask> {
  return apiFetch(`/tasks/${taskId}`);
}

export async function pauseTask(taskId: string): Promise<ScheduledTask> {
  return apiFetch(`/tasks/${taskId}/pause`, { method: "POST" });
}

export async function resumeTask(taskId: string): Promise<ScheduledTask> {
  return apiFetch(`/tasks/${taskId}/resume`, { method: "POST" });
}

export async function deleteTask(taskId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/tasks/${taskId}`, { method: "DELETE" });
}

export async function getTaskRuns(taskId: string, limit: number = 5): Promise<Run[]> {
  return apiFetch(`/tasks/${taskId}/runs?limit=${limit}`);
}
