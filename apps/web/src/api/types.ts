/**
 * TypeScript interfaces matching the backend Pydantic models exactly.
 * See 05-api-spec.md for the full data model.
 */

export type RunStatus =
  | "idle"
  | "planning"
  | "awaiting_approval"
  | "running"
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

export type MemoryType = "fact" | "episode" | "summary";

export interface Run {
  run_id: string;
  session_id: string;
  status: RunStatus;
  user_message: string;
  plan: Plan | null;
  final_response: string | null;
  created_at: string;
  updated_at: string;
}

export interface Plan {
  task_type: string;
  confidence: number;
  reasoning: string;
  steps: PlanStep[];
  direct_response: string | null;
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
  status: "success" | "error";
  risk_level: RiskLevel;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
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
  created_at: string;
  updated_at: string;
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
