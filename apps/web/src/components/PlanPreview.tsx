/**
 * PlanPreview — shows the structured plan steps with risk levels and status.
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
} from "lucide-react";
import type { Plan, PlanStep, StepStatus, RiskLevel } from "../api/types";

interface PlanPreviewProps {
  plan: Plan;
  compact?: boolean;
}

export default function PlanPreview({ plan, compact = false }: PlanPreviewProps) {
  const [expandedStep, setExpandedStep] = useState<string | null>(null);

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

// ── Step Row ──────────────────────────────────────────

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
        <span className="font-mono text-xs t-primary flex-1 truncate">{step.tool}</span>
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
          <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-1.5">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
          {step.result && (
            <div className="mt-2">
              <span className="text-[10px] uppercase tracking-wider t-faint">Result</span>
              <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto mt-0.5 max-h-32 overflow-y-auto">
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify(step.result?.output ?? step.result, null, 2)}
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
