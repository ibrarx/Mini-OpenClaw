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
  Target,
  SkipForward,
  RefreshCw,
} from "lucide-react";
import type { Plan, PlanStep, StepStatus, RiskLevel, Observation, Run, Goal, GoalStatus } from "../api/types";

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

// ── Step Row (legacy plan-and-execute) ────────────────

interface StepRowProps {
  step: PlanStep;
  index: number;
  expanded: boolean;
  onToggle: () => void;
  compact: boolean;
}

function StepRow({ step, index, expanded, onToggle, compact }: StepRowProps) {
  return (
    <div className="rounded-md bg-step-row border border-app">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-sm bg-step-row-hover transition-colors rounded-md"
      >
        <StepStatusIcon status={step.status} />
        <span className="t-faint text-xs font-mono w-4">{index + 1}</span>
        <span className="font-mono text-xs t-primary flex-1 truncate">
          {step.tool}
        </span>
        <RiskBadge level={step.risk_level} />
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
          {step.reasoning && (
            <p className="text-xs t-muted mt-2 mb-1.5">{step.reasoning}</p>
          )}
          {step.args && Object.keys(step.args).length > 0 && (
            <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-1.5">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(step.args, null, 2)}
              </pre>
            </div>
          )}
          {step.result && (
            <div className="mt-2">
              <span className="text-[10px] uppercase tracking-wider t-faint">Result</span>
              <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-0.5 max-h-32 overflow-y-auto">
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify(
                    step.result.status === "success" ? step.result.output : step.result.error,
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
  const goals = run.plan?.goals ?? [];
  const replanCount = run.plan?.replan_count ?? 0;

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
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

      {/* Budget progress bar */}
      <BudgetBar iterations={run.iterations} maxIterations={run.max_iterations} isActive={isActive} />

      {/* Context window usage bar */}
      <ContextBar run={run} />

      {/* Goal checklist */}
      {goals.length > 0 && (
        <GoalChecklist goals={goals} replanCount={replanCount} compact={compact} />
      )}

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

// ── Budget Progress Bar ──────────────────────────────

interface BudgetBarProps {
  iterations: number;
  maxIterations: number;
  isActive: boolean;
}

function BudgetBar({ iterations, maxIterations, isActive }: BudgetBarProps) {
  if (maxIterations <= 0) return null;

  const used = iterations;
  const remaining = maxIterations - used;
  const pct = Math.round((used / maxIterations) * 100);
  const pctLeft = 100 - pct;

  // Color thresholds: green < 50%, amber 50-70%, red > 70%
  const barColor =
    pct <= 50
      ? "bg-emerald-500"
      : pct <= 70
        ? "bg-amber-500"
        : "bg-red-500";

  // Warn threshold: 30% of max (matches backend default)
  const warnThreshold = Math.max(1, Math.floor(maxIterations * 0.3));
  const isLow = remaining <= warnThreshold && remaining > 0;

  // Show inner label only when the filled portion is wide enough (≥ 35%)
  const showUsedLabel = pct >= 35;
  // Show right label only when unfilled portion is wide enough (≥ 20%)
  const showLeftLabel = pctLeft >= 20;

  return (
    <div className="mb-2">
      {/* A1: "Iteration budget" label left of bar */}
      <div className="flex items-center gap-2.5">
        <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">
          Iteration budget
        </span>
        <div className="relative flex-1 h-7 rounded-lg bg-gray-100 dark:bg-gray-800 overflow-hidden border border-gray-200 dark:border-gray-700">
          <div
            className={`absolute inset-y-0 left-0 rounded-l-lg transition-all duration-500 ease-out ${barColor} ${
              isActive ? "animate-pulse" : ""
            }`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
          {/* "X% used" on filled portion */}
          {showUsedLabel && (
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[11px] font-medium text-white whitespace-nowrap">
              {pct}% used
            </span>
          )}
          {/* "Y% left" on empty portion */}
          {showLeftLabel && remaining > 0 && (
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">
              {pctLeft}% left
            </span>
          )}
          {/* Fallback: when both sides too narrow */}
          {!showUsedLabel && !showLeftLabel && (
            <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-[11px] font-medium text-gray-600 dark:text-gray-300 whitespace-nowrap">
              {pct}% used · {pctLeft}% left
            </span>
          )}
        </div>
      </div>
      {/* Low budget warning below the bar */}
      {isLow && remaining > 0 && (
        <div className="flex items-center gap-1 mt-1">
          <span className="text-[10px] font-medium text-red-600 dark:text-red-400 flex items-center gap-0.5">
            <AlertTriangle size={10} />
            Low budget
          </span>
        </div>
      )}
    </div>
  );
}

// ── Context Window Bar ───────────────────────────────

function ContextBar({ run }: { run: Run }) {
  if (!run.context_window || run.context_window === 0) return null;

  // Sum token estimates from all observations
  const tokensUsed = run.observations.reduce((sum, obs) => sum + (obs.token_estimate || 0), 0);
  if (tokensUsed === 0) return null;

  const pct = Math.round((tokensUsed / run.context_window) * 100);
  const barColor = pct <= 50 ? "bg-blue-500" : pct <= 75 ? "bg-amber-500" : "bg-red-500";

  // Format numbers: 8192 → "8K", 200000 → "200K"
  const fmt = (n: number) => n >= 1000 ? `${Math.round(n / 1000)}K` : `${n}`;

  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap">
        Context window
      </span>
      <div className="relative flex-1 h-4 rounded bg-gray-100 dark:bg-gray-800 overflow-hidden border border-gray-200 dark:border-gray-700">
        <div className={`absolute inset-y-0 left-0 rounded-l transition-all duration-500 ${barColor}`}
             style={{ width: `${Math.min(pct, 100)}%` }} />
        <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-gray-600 dark:text-gray-300">
          ~{fmt(tokensUsed)} / {fmt(run.context_window)} tokens
        </span>
      </div>
    </div>
  );
}

// ── Goal Checklist ────────────────────────────────────

interface GoalChecklistProps {
  goals: Goal[];
  replanCount: number;
  compact: boolean;
}

function GoalChecklist({ goals, replanCount, compact }: GoalChecklistProps) {
  const done = goals.filter((g) => g.status === "done").length;
  const total = goals.length;

  return (
    <div className="mb-2 rounded-md bg-step-row border border-app px-2.5 py-2">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 text-xs font-medium t-secondary">
          <Target size={12} className="text-purple-500" />
          Goals: {done}/{total}
        </div>
        {replanCount > 0 && (
          <span className="flex items-center gap-1 text-[10px] t-muted">
            <RefreshCw size={10} />
            {replanCount} replan{replanCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      {!compact && (
        <div className="space-y-0.5">
          {goals.map((goal) => (
            <GoalRow key={goal.goal_id} goal={goal} />
          ))}
        </div>
      )}
    </div>
  );
}

function GoalRow({ goal }: { goal: Goal }) {
  return (
    <div className="flex items-center gap-1.5 text-xs py-0.5">
      <GoalStatusIcon status={goal.status} />
      <span
        className={
          goal.status === "done"
            ? "t-muted line-through"
            : goal.status === "skipped"
              ? "t-faint line-through"
              : goal.status === "in_progress"
                ? "t-primary"
                : "t-secondary"
        }
      >
        {goal.description}
      </span>
      <span className="text-[10px] font-mono t-faint ml-auto flex-shrink-0">
        {goal.goal_id}
      </span>
    </div>
  );
}

function GoalStatusIcon({ status }: { status: GoalStatus }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />;
    case "in_progress":
      return <Loader2 size={12} className="text-blue-500 animate-spin flex-shrink-0" />;
    case "skipped":
      return <SkipForward size={12} className="text-amber-500 flex-shrink-0" />;
    default:
      return <Clock size={12} className="t-faint flex-shrink-0" />;
  }
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
  const hasAnnouncement = !!obs.user_announcement && !isFinalAnswer;

  return (
    <div className="rounded-md bg-step-row border border-app">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-sm bg-step-row-hover transition-colors rounded-md"
      >
        <ObservationStatusIcon status={status} isFinalAnswer={isFinalAnswer} />
        <span className="t-faint text-xs font-mono w-4">{index + 1}</span>
        <span className="text-xs t-primary flex-1 truncate">
          {hasAnnouncement ? obs.user_announcement : (isFinalAnswer ? "Done" : obs.tool)}
        </span>
        {/* Always show tool name badge when announcement replaces it */}
        {hasAnnouncement && obs.tool && (
          <span className="text-[10px] font-mono t-faint bg-app-code rounded px-1.5 py-0.5 flex-shrink-0">
            {obs.tool}
          </span>
        )}
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
          {obs.user_announcement && (
            <p className="text-xs t-secondary mt-2 mb-1">{obs.user_announcement}</p>
          )}
          {obs.reasoning && (
            <p className="text-xs t-muted mt-1 mb-1.5 italic">
              Trace: {obs.reasoning}
            </p>
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
