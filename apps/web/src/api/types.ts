// TypeScript interfaces matching backend models.
// See 05-api-spec.md for full data model.

export interface Run {
  run_id: string;
  session_id: string;
  status: string;
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
}

export interface PlanStep {
  step_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk_level: string;
  status: string;
  result?: Record<string, unknown>;
}

export interface MemoryItem {
  id: string;
  workspace_id: string;
  memory_type: "fact" | "episode" | "summary";
  content: string;
  summary: string | null;
  source: string | null;
  confidence: number;
  visibility: string;
  created_at: string;
  updated_at: string;
}
