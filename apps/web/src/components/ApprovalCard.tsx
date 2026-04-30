/**
 * ApprovalCard — prominent card for steps awaiting user approval (theme-aware).
 */

import { useState } from "react";
import { ShieldAlert, Check, X, Loader2 } from "lucide-react";
import { RiskBadge } from "./PlanPreview";
import type { PlanStep } from "../api/types";

interface ApprovalCardProps {
  step: PlanStep;
  runId: string;
  onApprove: (runId: string, stepId: string) => Promise<void>;
  onReject: (runId: string, stepId: string) => Promise<void>;
}

export default function ApprovalCard({
  step,
  runId,
  onApprove,
  onReject,
}: ApprovalCardProps) {
  const [loading, setLoading] = useState<"approve" | "reject" | null>(null);
  const [decided, setDecided] = useState<"approved" | "rejected" | null>(null);

  const handleApprove = async () => {
    if (decided) return;
    setLoading("approve");
    try {
      await onApprove(runId, step.step_id);
      setDecided("approved");
    } catch {
      setLoading(null);
    }
  };

  const handleReject = async () => {
    if (decided) return;
    setLoading("reject");
    try {
      await onReject(runId, step.step_id);
      setDecided("rejected");
    } catch {
      setLoading(null);
    }
  };

  const disabled = loading !== null || decided !== null;

  if (decided) {
    return (
      <div className="rounded-lg border border-app bg-step-row px-3.5 py-2.5 flex items-center gap-2">
        {decided === "approved" ? (
          <>
            <Check size={14} className="text-emerald-500" />
            <span className="text-sm text-emerald-600">
              Step approved — executing...
            </span>
            <Loader2 size={14} className="animate-spin t-faint ml-auto" />
          </>
        ) : (
          <>
            <X size={14} className="text-red-500" />
            <span className="text-sm text-red-600">Step rejected</span>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="animate-slide-up rounded-lg border-2 border-amber-500/30 bg-amber-500/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3.5 py-2 bg-amber-500/10 border-b border-amber-500/20">
        <ShieldAlert size={15} className="text-amber-500" />
        <span className="text-sm font-medium text-amber-700 dark:text-amber-300">
          Approval Required
        </span>
        <div className="ml-auto">
          <RiskBadge level={step.risk_level} />
        </div>
      </div>

      {/* Body */}
      <div className="px-3.5 py-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs t-muted">Tool:</span>
          <span className="font-mono text-sm t-primary">{step.tool}</span>
        </div>

        <div className="text-xs mb-3">
          <span className="t-faint block mb-1">Arguments:</span>
          <div className="font-mono bg-app-code rounded-md px-2.5 py-2 t-code overflow-x-auto max-h-40 overflow-y-auto border border-app">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
        </div>

        {step.reasoning && (
          <p className="text-xs t-muted mb-3 leading-relaxed">
            {step.reasoning}
          </p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={handleApprove}
            disabled={disabled}
            className="btn btn-approve flex-1"
          >
            {loading === "approve" ? (
              <span className="dot-pulse"><span /><span /><span /></span>
            ) : (
              <>
                <Check size={14} />
                Approve
              </>
            )}
          </button>
          <button
            onClick={handleReject}
            disabled={disabled}
            className="btn btn-danger flex-1"
          >
            {loading === "reject" ? (
              <span className="dot-pulse"><span /><span /><span /></span>
            ) : (
              <>
                <X size={14} />
                Reject
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
