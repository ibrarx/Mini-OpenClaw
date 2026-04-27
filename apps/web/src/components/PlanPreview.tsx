/**
 * PlanPreview — shows the structured plan steps with risk levels and status.
 * Expandable steps to see args and reasoning.
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

  if (plan.task_type === "direct_answer") {
    return null;
  }

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span className="font-medium text-gray-300">
            Plan: {plan.steps.length} step{plan.steps.length !== 1 ? "s" : ""}
          </span>
          <span className="text-gray-600">•</span>
          <span className="capitalize">{plan.task_type.replace(/_/g, " ")}</span>
        </div>
        <ConfidenceBadge value={plan.confidence} />
      </div>

      {/* Reasoning (truncated) */}
      {!compact && plan.reasoning && (
        <p className="text-xs text-gray-500 mb-2.5 leading-relaxed line-clamp-2">
          {plan.reasoning}
        </p>
      )}

      {/* Steps */}
      <div className="space-y-1">
        {plan.steps.map((step, i) => (
          <StepRow
            key={step.step_id}
            step={step}
            index={i}
            expanded={expandedStep === step.step_id}
            onToggle={() =>
              setExpandedStep(
                expandedStep === step.step_id ? null : step.step_id
              )
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
    <div className="rounded-md bg-gray-800/40 border border-gray-700/40">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-gray-800/60 transition-colors rounded-md"
      >
        <StepStatusIcon status={step.status} />
        <span className="text-gray-500 text-xs font-mono w-4">
          {index + 1}
        </span>
        <span className="font-mono text-xs text-gray-200 flex-1 truncate">
          {step.tool}
        </span>
        <RiskBadge level={step.risk_level} />
        {!compact && (
          expanded ? (
            <ChevronDown size={12} className="text-gray-500" />
          ) : (
            <ChevronRight size={12} className="text-gray-500" />
          )
        )}
      </button>

      {expanded && !compact && (
        <div className="px-3 pb-2.5 border-t border-gray-700/30 mt-0.5">
          {step.reasoning && (
            <p className="text-xs text-gray-400 mt-2 mb-1.5">{step.reasoning}</p>
          )}
          <div className="text-xs font-mono bg-gray-900/60 rounded px-2.5 py-1.5 text-gray-400 overflow-x-auto mt-1.5">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
          {step.result && (
            <div className="mt-2">
              <span className="text-[10px] uppercase tracking-wider text-gray-500">
                Result
              </span>
              <div className="text-xs font-mono bg-gray-900/60 rounded px-2.5 py-1.5 text-gray-400 overflow-x-auto mt-0.5 max-h-32 overflow-y-auto">
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
      return <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0" />;
    case "running":
      return <Loader2 size={14} className="text-blue-400 animate-spin flex-shrink-0" />;
    case "awaiting_approval":
      return <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />;
    case "failed":
      return <XCircle size={14} className="text-red-400 flex-shrink-0" />;
    default:
      return <Clock size={14} className="text-gray-500 flex-shrink-0" />;
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
      ? "text-emerald-400"
      : pct >= 50
        ? "text-amber-400"
        : "text-red-400";

  return (
    <span className={`flex items-center gap-1 text-xs ${color}`}>
      <Gauge size={12} />
      {pct}%
    </span>
  );
}
