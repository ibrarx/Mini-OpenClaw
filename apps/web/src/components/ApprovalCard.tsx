/**
 * ApprovalCard — prominent card for steps awaiting user approval.
 * Shows tool name, full arguments, risk level, and approve/reject buttons.
 */

import { useState } from "react";
import { ShieldAlert, Check, X } from "lucide-react";
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

  const handleApprove = async () => {
    setLoading("approve");
    try {
      await onApprove(runId, step.step_id);
    } finally {
      setLoading(null);
    }
  };

  const handleReject = async () => {
    setLoading("reject");
    try {
      await onReject(runId, step.step_id);
    } finally {
      setLoading(null);
    }
  };

  const disabled = loading !== null;

  return (
    <div className="animate-slide-up rounded-lg border-2 border-amber-500/30 bg-amber-500/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3.5 py-2 bg-amber-500/10 border-b border-amber-500/20">
        <ShieldAlert size={15} className="text-amber-400" />
        <span className="text-sm font-medium text-amber-300">
          Approval Required
        </span>
        <div className="ml-auto">
          <RiskBadge level={step.risk_level} />
        </div>
      </div>

      {/* Body */}
      <div className="px-3.5 py-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs text-gray-400">Tool:</span>
          <span className="font-mono text-sm text-gray-200">{step.tool}</span>
        </div>

        {/* Arguments */}
        <div className="text-xs mb-3">
          <span className="text-gray-500 block mb-1">Arguments:</span>
          <div className="font-mono bg-gray-900/80 rounded-md px-2.5 py-2 text-gray-300 overflow-x-auto max-h-40 overflow-y-auto border border-gray-700/40">
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          </div>
        </div>

        {step.reasoning && (
          <p className="text-xs text-gray-400 mb-3 leading-relaxed">
            {step.reasoning}
          </p>
        )}

        {/* Actions */}
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
