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
  ScanEye,
  Users,
} from "lucide-react";
import { useChildRunSSE } from "../hooks/useChildRunSSE";
import type { Plan, PlanStep, StepStatus, RiskLevel, Observation, Run, Goal, GoalStatus, ReflectionResult } from "../api/types";

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
  const isReflecting = run.status === "reflecting";
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
          {isReflecting && (
            <span className="flex items-center gap-1 text-violet-500">
              <Loader2 size={12} className="animate-spin" />
              Reviewing…
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

      {/* Self-reflection: live spinner while reviewing */}
      {isReflecting && (
        <div className="mt-1.5 rounded-md bg-violet-50 dark:bg-violet-950/20 border border-violet-200 dark:border-violet-800 px-2.5 py-1 flex items-center gap-2 text-xs text-violet-700 dark:text-violet-400 animate-fade-in">
          <ScanEye size={14} className="flex-shrink-0" />
          <span>Reviewing answer quality…</span>
          <Loader2 size={12} className="animate-spin ml-auto" />
        </div>
      )}

      {/* Self-reflection result badge */}
      {run.reflection && <ReflectionBadge reflection={run.reflection} />}
    </div>
  );
}

// ── Shared label width for bar alignment ─────────────
const BAR_LABEL = "w-[170px] shrink-0 text-[11px] font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap truncate";
const BAR_HEIGHT = "h-4";
const BAR_OUTER = `relative flex-1 ${BAR_HEIGHT} rounded bg-gray-100 dark:bg-gray-800 overflow-hidden border border-gray-200 dark:border-gray-700`;

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

  return (
    <div className="mb-1.5">
      <div className="flex items-center gap-2">
        <span className={BAR_LABEL}>Iteration budget</span>
        <div className={BAR_OUTER}>
          <div
            className={`absolute inset-y-0 left-0 rounded-l transition-all duration-500 ease-out ${barColor} ${
              isActive ? "animate-pulse" : ""
            }`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
          <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-gray-600 dark:text-gray-300 whitespace-nowrap">
            {used} / {maxIterations} — {pct}% used
          </span>
        </div>
      </div>
      {isLow && remaining > 0 && (
        <div className="flex items-center gap-1 mt-0.5 ml-[178px]">
          <span className="text-[10px] font-medium text-red-600 dark:text-red-400 flex items-center gap-0.5">
            <AlertTriangle size={10} />
            Low budget — {remaining} step{remaining !== 1 ? "s" : ""} left
          </span>
        </div>
      )}
    </div>
  );
}

// ── Context Window Bar ───────────────────────────────

function ContextBar({ run }: { run: Run }) {
  if (!run.context_window || run.context_window === 0) return null;

  // Use the latest (max) token estimate — each observation stores the cumulative prompt size
  const tokensUsed = Math.max(...run.observations.map((obs) => obs.token_estimate || 0), 0);
  if (tokensUsed === 0) return null;

  // Cap percentage at 100 for display, but track overflow
  const rawPct = Math.round((tokensUsed / run.context_window) * 100);
  const pct = Math.min(rawPct, 100);
  const isOverflow = rawPct > 100;

  // Color thresholds: blue < 50%, amber 50-75%, red > 75% or overflow
  const barColor =
    isOverflow || pct > 75
      ? "bg-red-500"
      : pct <= 50
        ? "bg-blue-500"
        : "bg-amber-500";

  const isActive = run.status === "reacting";

  // Format numbers: 8192 → "8K", 200000 → "200K"
  const fmt = (n: number) => n >= 1000 ? `${Math.round(n / 1000)}K` : `${n}`;

  // Build label: "Context (model)" — short and clean
  const modelShort = run.model_name
    ? run.model_name.replace(/-\d{8}$/, "")  // strip date suffix like -20250514
    : "";
  const label = modelShort ? `Context (${modelShort})` : "Context window";

  // Get the latest compression level from the most recent observation that has one
  const latestCompression = [...run.observations]
    .reverse()
    .find((obs) => obs.compression_level && obs.compression_level !== "none")
    ?.compression_level || "none";

  return (
    <div className="mb-1.5">
      <div className="flex items-center gap-2">
        <span className={BAR_LABEL}>{label}</span>
        <div className={BAR_OUTER}>
          <div
            className={`absolute inset-y-0 left-0 rounded-l transition-all duration-500 ease-out ${barColor} ${
              isActive ? "animate-pulse" : ""
            }`}
            style={{ width: `${pct}%` }}
          />
          <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-gray-600 dark:text-gray-300 whitespace-nowrap">
            ~{fmt(tokensUsed)} / {fmt(run.context_window)} tokens{isOverflow ? " ⚠ overflow" : ""}
          </span>
        </div>
      </div>
      {/* Subtitle: only appears when compression is active */}
      {latestCompression === "partial" && !isOverflow && (
        <div className="flex items-center gap-1.5 mt-0.5 ml-[178px] px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 w-fit">
          <AlertTriangle size={10} className="text-amber-600 dark:text-amber-400 shrink-0" />
          <span className="text-[10px] font-medium text-amber-700 dark:text-amber-400">
            Older steps summarized to save context
          </span>
        </div>
      )}
      {latestCompression === "aggressive" && !isOverflow && (
        <div className="flex items-center gap-1.5 mt-0.5 ml-[178px] px-2 py-0.5 rounded bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 w-fit">
          <AlertTriangle size={10} className="text-red-600 dark:text-red-400 shrink-0" />
          <span className="text-[10px] font-medium text-red-700 dark:text-red-400">
            Only last 2 steps in full detail — earlier steps heavily compressed
          </span>
        </div>
      )}
      {isOverflow && (
        <div className="flex items-center gap-1.5 mt-0.5 ml-[178px] px-2 py-0.5 rounded bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 w-fit">
          <AlertTriangle size={10} className="text-red-600 dark:text-red-400 shrink-0" />
          <span className="text-[10px] font-medium text-red-700 dark:text-red-400">
            Context window exceeded — output quality may degrade
          </span>
        </div>
      )}
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
        {/* Sub-agent indicator for delegate_task */}
        {obs.tool === "delegate_task" && obs.result?.output?.child_run_id && (
          <span className="text-[10px] font-medium text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/20 rounded px-1.5 py-0.5 flex items-center gap-1 flex-shrink-0">
            <Users size={10} /> sub-agent
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
          {/* Inline child run for delegate_task */}
          {obs.tool === "delegate_task" && obs.result?.output?.child_run_id && (
            <ChildRunCard childRunId={obs.result.output.child_run_id as string} />
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

function ReflectionBadge({ reflection }: { reflection: ReflectionResult }) {
  const [expanded, setExpanded] = useState(false);
  const score = Math.round(reflection.overall_score * 100);
  const color = score >= 80 ? "text-emerald-600" : score >= 60 ? "text-amber-600" : "text-red-600";
  const bgColor = score >= 80 ? "bg-emerald-50 dark:bg-emerald-950/20" : score >= 60 ? "bg-amber-50 dark:bg-amber-950/20" : "bg-red-50 dark:bg-red-950/20";
  const borderColor = score >= 80 ? "border-emerald-200 dark:border-emerald-800" : score >= 60 ? "border-amber-200 dark:border-amber-800" : "border-red-200 dark:border-red-800";

  const scores = [
    { label: "Completeness", value: reflection.completeness },
    { label: "Accuracy", value: reflection.accuracy },
    { label: "Clarity", value: reflection.clarity },
  ];

  return (
    <div className={`mt-1.5 rounded-md px-2.5 py-1 ${bgColor} border ${borderColor} animate-fade-in`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 text-xs text-left"
      >
        <ScanEye size={13} className={color} />
        <span className="font-medium t-secondary">Self-check:</span>
        <span className={`font-medium ${color}`}>{score}%</span>
        {reflection.improved && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400 font-medium">
            answer improved
          </span>
        )}
        <span className="ml-auto">
          {expanded ? (
            <ChevronDown size={12} className="t-faint" />
          ) : (
            <ChevronRight size={12} className="t-faint" />
          )}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5">
          {/* Score breakdown */}
          <div className="flex gap-3">
            {scores.map((s) => {
              const pct = Math.round(s.value * 100);
              const barColor = pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-amber-500" : "bg-red-500";
              return (
                <div key={s.label} className="flex-1 min-w-0">
                  <div className="flex items-center justify-between text-[10px] mb-0.5">
                    <span className="t-muted">{s.label}</span>
                    <span className="t-secondary font-medium">{pct}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${barColor} transition-all duration-500`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Issues */}
          {reflection.issues.length > 0 && (
            <div className="mt-1">
              <span className="text-[10px] uppercase tracking-wider t-faint">Issues found</span>
              <div className="mt-0.5 text-[11px] t-muted">
                {reflection.issues.map((issue, i) => (
                  <div key={i} className="flex items-start gap-1 py-0.5">
                    <span className="t-faint mt-0.5">•</span>
                    <span>{issue}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggestion */}
          {reflection.suggestion && (
            <div className="text-[11px] t-muted italic">
              Suggestion: {reflection.suggestion}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Child Run Card (sub-agent delegation, SSE-streamed) ──────────

function ChildRunCard({ childRunId }: { childRunId: string }) {
  const { childRun } = useChildRunSSE(childRunId);
  const [expanded, setExpanded] = useState(true);

  if (!childRun) {
    return (
      <div className="mt-2 ml-2 pl-3 border-l-2 border-purple-300 dark:border-purple-700">
        <div className="flex items-center gap-2 text-xs t-muted py-1">
          <Users size={12} className="text-purple-500" />
          <span>Sub-agent: {childRunId}</span>
          <Loader2 size={12} className="animate-spin text-purple-500" />
        </div>
      </div>
    );
  }

  const isActive = childRun.status === "reacting" || childRun.status === "planning";
  const isDone = ["completed", "failed", "cancelled"].includes(childRun.status);
  const statusColor = childRun.status === "completed"
    ? "text-emerald-500"
    : childRun.status === "failed"
      ? "text-red-500"
      : "text-purple-500";

  return (
    <div className="mt-2 ml-2 pl-3 border-l-2 border-purple-300 dark:border-purple-700 animate-fade-in">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 text-xs text-left py-1"
      >
        <Users size={12} className="text-purple-500 flex-shrink-0" />
        <span className="font-medium t-secondary">Sub-agent</span>
        <span className="t-faint">•</span>
        <span className={`font-medium ${statusColor}`}>{childRun.status}</span>
        <span className="t-faint">•</span>
        <span className="t-muted">{childRun.iterations}/{childRun.max_iterations} iterations</span>
        {isActive && <Loader2 size={10} className="animate-spin text-purple-500" />}
        <span className="ml-auto">
          {expanded ? <ChevronDown size={10} className="t-faint" /> : <ChevronRight size={10} className="t-faint" />}
        </span>
      </button>

      {expanded && (
        <div className="space-y-0.5 mt-1 mb-1">
          {/* Child task description */}
          <div className="text-[11px] t-muted mb-1 italic">
            Task: {childRun.user_message}
          </div>

          {/* Child observations */}
          {childRun.observations.map((obs, i) => (
            <ChildObservationRow key={obs.step_id + "-" + obs.iteration} obs={obs} index={i} />
          ))}

          {/* Active spinner */}
          {isActive && (
            <div className="flex items-center gap-2 text-[11px] t-muted py-0.5">
              <Loader2 size={10} className="text-purple-500 animate-spin" />
              <span>
                {childRun.observations.length > 0 &&
                 childRun.observations[childRun.observations.length - 1].user_announcement &&
                 !childRun.observations[childRun.observations.length - 1].result
                  ? childRun.observations[childRun.observations.length - 1].user_announcement
                  : "Thinking…"}
              </span>
            </div>
          )}

          {/* Final response */}
          {isDone && childRun.final_response && (
            <div className="text-[11px] t-secondary bg-app-code rounded px-2 py-1 mt-1 max-h-20 overflow-y-auto">
              {childRun.final_response.slice(0, 500)}
              {childRun.final_response.length > 500 && "…"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Compact observation row for child runs — no expand, minimal chrome. */
function ChildObservationRow({ obs, index }: { obs: Observation; index: number }) {
  const isFinalAnswer = !obs.tool;
  const status = obs.result?.status;

  return (
    <div className="flex items-center gap-1.5 text-[11px] py-0.5">
      <ObservationStatusIcon status={status} isFinalAnswer={isFinalAnswer} />
      <span className="t-faint font-mono w-3">{index + 1}</span>
      <span className="t-secondary truncate flex-1">
        {obs.user_announcement || (isFinalAnswer ? "Done" : obs.tool)}
      </span>
      {obs.tool && obs.user_announcement && (
        <span className="text-[9px] font-mono t-faint bg-app-code rounded px-1 py-0.5 flex-shrink-0">
          {obs.tool}
        </span>
      )}
      {status === "error" && (
        <span className="text-[9px] text-red-500">error</span>
      )}
    </div>
  );
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
