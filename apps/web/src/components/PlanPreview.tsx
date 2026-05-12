/**
 * PlanPreview — shows structured plan steps (legacy) or ReAct observations.
 * Theme-aware: uses CSS variable classes instead of hardcoded gray-*.
 */

import { useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Clock,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronRight,
  Gauge,
  Brain,
  ShieldOff,
  Ban,
} from "lucide-react";
import type { Plan, PlanStep, StepStatus, RiskLevel, Observation, Run } from "../api/types";

interface PlanPreviewProps {
  plan: Plan;
  compact?: boolean;
  /** Pass the full Run to enable ReAct observation rendering. */
  run?: Run;
}

export default function PlanPreview({ plan, compact = false, run }: PlanPreviewProps) {
  const [expandedStep, setExpandedStep] = useState<string | null>(null);

  // ReAct mode: render observations timeline
  if (run && run.observations && run.observations.length > 0) {
    return (
      <ReactTimeline
        run={run}
        expandedStep={expandedStep}
        onToggleStep={(id) => setExpandedStep(expandedStep === id ? null : id)}
        compact={compact}
      />
    );
  }

  if (plan.task_type === "direct_answer") return null;

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs t-muted">
          <span className="font-medium t-secondary">
            Plan: {plan.steps.length} step{plan.steps.length !== 1 ? "s" : ""}
          </span>
          <span className="t-faint">•</span>
          <span className="capitalize">{plan.task_type.replace(/_/g, " ")}</span>
        </div>
        <ConfidenceBadge value={plan.confidence} />
      </div>

      {!compact && plan.reasoning && (
        <p className="text-xs t-muted mb-2.5 leading-relaxed line-clamp-2">
          {plan.reasoning}
        </p>
      )}

      <div className="space-y-1">
        {plan.steps.map((step, i) => (
          <StepRow
            key={step.step_id}
            step={step}
            index={i}
            expanded={expandedStep === step.step_id}
            onToggle={() =>
              setExpandedStep(expandedStep === step.step_id ? null : step.step_id)
            }
            compact={compact}
          />
        ))}
      </div>
    </div>
  );
}

// ── ReAct Timeline ────────────────────────────────────

interface ReactTimelineProps {
  run: Run;
  expandedStep: string | null;
  onToggleStep: (id: string) => void;
  compact: boolean;
}

function ReactTimeline({ run, expandedStep, onToggleStep, compact }: ReactTimelineProps) {
  const isActive = run.status === "reacting";
  const maxReached = run.status === "failed" && run.iterations >= run.max_iterations;

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs t-muted">
          <Brain size={14} className="text-purple-500" />
          <span className="font-medium t-secondary">
            ReAct: {run.iterations} / {run.max_iterations} iterations
          </span>
          {isActive && (
            <span className="flex items-center gap-1 text-blue-500">
              <Loader2 size={12} className="animate-spin" />
              Thinking…
            </span>
          )}
        </div>
      </div>

      {maxReached && (
        <div className="mb-2 px-2.5 py-1.5 rounded-md bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-400 flex items-center gap-1.5">
          <AlertTriangle size={12} />
          Max iterations reached. Task partially completed.
        </div>
      )}

      <div className="space-y-1">
        {run.observations.map((obs, i) => (
          <ObservationRow
            key={obs.step_id + "-" + obs.iteration}
            obs={obs}
            index={i}
            expanded={expandedStep === obs.step_id}
            onToggle={() => onToggleStep(obs.step_id)}
            compact={compact}
          />
        ))}
        {isActive && (
          <div className="rounded-md bg-step-row border border-app px-2.5 py-1.5 flex items-center gap-2 text-xs t-muted">
            <Loader2 size={14} className="text-blue-500 animate-spin" />
            <span>Thinking…</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Observation Row ───────────────────────────────────

interface ObservationRowProps {
  obs: Observation;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  compact: boolean;
}

function ObservationRow({ obs, index, expanded, onToggle, compact }: ObservationRowProps) {
  const isFinalAnswer = !obs.tool;
  const status = obs.result?.status;

  return (
    <div className="rounded-md bg-step-row border border-app">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-sm bg-step-row-hover transition-colors rounded-md"
      >
        <ObservationStatusIcon status={status} isFinalAnswer={isFinalAnswer} />
        <span className="t-faint text-xs font-mono w-4">{index + 1}</span>
        <span className="font-mono text-xs t-primary flex-1 truncate">
          {isFinalAnswer ? "final_answer" : obs.tool}
        </span>
        {status === "denied" && (
          <span className="badge badge-medium flex items-center gap-0.5">
            <ShieldOff size={10} /> denied
          </span>
        )}
        {status === "rejected" && (
          <span className="badge badge-high flex items-center gap-0.5">
            <Ban size={10} /> rejected
          </span>
        )}
        {!compact && (
          expanded ? (
            <ChevronDown size={12} className="t-faint" />
          ) : (
            <ChevronRight size={12} className="t-faint" />
          )
        )}
      </button>

      {expanded && !compact && (
        <div className="px-3 pb-2.5 border-t border-app mt-0.5">
          {obs.reasoning && (
            <p className="text-xs t-muted mt-2 mb-1.5">{obs.reasoning}</p>
          )}
          {obs.args && (
            <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-1.5">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(obs.args, null, 2)}
              </pre>
            </div>
          )}
          {obs.result && (
            <div className="mt-2">
              <span className="text-[10px] uppercase tracking-wider t-faint">Result</span>
              <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-0.5 max-h-32 overflow-y-auto">
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify(
                    obs.result.status === "success" ? obs.result.output : obs.result.error,
                    null, 2,
                  )}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────

function ObservationStatusIcon({
  status,
  isFinalAnswer,
}: {
  status?: string;
  isFinalAnswer: boolean;
}) {
  if (isFinalAnswer) {
    return <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />;
  }
  switch (status) {
    case "success":
      return <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />;
    case "error":
      return <XCircle size={14} className="text-red-500 flex-shrink-0" />;
    case "denied":
      return <ShieldOff size={14} className="text-amber-500 flex-shrink-0" />;
    case "rejected":
      return <Ban size={14} className="text-red-500 flex-shrink-0" />;
    default:
      return <Clock size={14} className="t-faint flex-shrink-0" />;
  }
}

function StepStatusIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />;
    case "running":
      return <Loader2 size={14} className="text-blue-500 animate-spin flex-shrink-0" />;
    case "awaiting_approval":
      return <AlertTriangle size={14} className="text-amber-500 flex-shrink-0" />;
    case "failed":
      return <XCircle size={14} className="text-red-500 flex-shrink-0" />;
    default:
      return <Clock size={14} className="t-faint flex-shrink-0" />;
  }
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  const cls =
    level === "safe"
      ? "badge-safe"
      : level === "medium"
        ? "badge-medium"
        : "badge-high";
  return <span className={`badge ${cls}`}>{level}</span>;
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80
      ? "text-emerald-600"
      : pct >= 50
        ? "text-amber-600"
        : "text-red-600";
  return (
    <span className={`flex items-center gap-1 text-xs ${color}`}>
      <Gauge size={12} />
      {pct}%
    </span>
  );
}
