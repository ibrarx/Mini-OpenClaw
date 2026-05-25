/**
 * TypeScript interfaces matching the backend Pydantic models exactly.
 * See 05-api-spec.md for the full data model.
 */

export type RunStatus =
  | "idle"
  | "planning"
  | "awaiting_approval"
  | "running"
  | "reacting"
  | "reflecting"
  | "completed"
  | "failed"
  | "cancelled";

export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "awaiting_approval";

export type RiskLevel = "safe" | "medium" | "high";

export type MemoryType = "fact" | "episode" | "summary" | "strategy" | "preference";

export type MemoryStatus = "active" | "pending_review" | "rejected";

export interface ReflectionResult {
  overall_score: number;
  completeness: number;
  accuracy: number;
  clarity: number;
  issues: string[];
  suggestion: string;
  improved: boolean;
  attempt: number;
}

export interface Run {
  run_id: string;
  session_id: string;
  status: RunStatus;
  user_message: string;
  plan: Plan | null;
  final_response: string | null;
  created_at: string;
  updated_at: string;
  iterations: number;
  max_iterations: number;
  observations: Observation[];
  context_window?: number;
  model_name?: string;
  reflection?: ReflectionResult | null;
  parent_run_id?: string | null;
  depth?: number;
}

export interface Observation {
  step_id: string;
  iteration: number;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  reasoning?: string;
  user_announcement?: string;
  result?: ToolResult | null;
  timestamp: string;
  token_estimate?: number;
  compression_level?: string;
}

export type GoalStatus = "pending" | "in_progress" | "done" | "skipped";

export interface Goal {
  goal_id: string;
  description: string;
  status: GoalStatus;
}

export interface Plan {
  task_type: string;
  confidence: number;
  reasoning: string;
  steps: PlanStep[];
  direct_response: string | null;
  goals: Goal[];
  replan_count: number;
}

export interface PlanStep {
  step_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk_level: RiskLevel;
  status: StepStatus;
  result?: ToolResult;
  reasoning?: string;
}

export interface ToolResult {
  tool_name: string;
  status: "success" | "error" | "denied" | "rejected";
  risk_level: RiskLevel;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  error_kind: "transient" | "permanent" | "side_effect" | null;
  started_at: string;
  finished_at: string;
  artifacts?: string[];
}

export interface MemoryItem {
  id: string;
  workspace_id: string;
  memory_type: MemoryType;
  content: string;
  summary: string | null;
  source: string | null;
  confidence: number;
  visibility: string;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  /** Similarity score from search (0-1). Only present in search results. */
  score?: number;
}

export interface ToolManifest {
  name: string;
  description: string;
  risk_level: RiskLevel;
  approval_required: boolean;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
}

/** Chat message as rendered in the UI (not a backend model). */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  run_id?: string;
  /** Terminal status of the associated run (e.g. "completed", "failed"). */
  run_status?: RunStatus;
  /** Embedded run data for inline plan/approval rendering. */
  run?: Run;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// ── Scheduler ─────────────────────────────────────────

export type ScheduleType = "once" | "interval";
export type TaskStatus = "active" | "paused" | "completed" | "failed";

export interface ScheduledTask {
  id: string;
  workspace_id: string;
  session_id: string;
  message: string;
  schedule_type: ScheduleType;
  run_at: string | null;
  interval_seconds: number | null;
  last_run_at: string | null;
  next_run_at: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  run_count: number;
  max_runs: number;
  last_run_id: string | null;
  error: string | null;
  pre_approved_tools: string[];
  approve_all_runs: boolean;
}
