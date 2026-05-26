/**
 * ChildRunCard (graph version) — Collapsed sub-agent card shown when
 * a delegate_task node is selected in the execution graph.
 *
 * Reuses the useChildRunSSE hook to stream child run updates in real time.
 * Renders as a compact card with expandable observation list.
 */

import { useState } from "react";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Users,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useChildRunSSE } from "../../hooks/useChildRunSSE";
import type { Observation } from "../../api/types";

interface ChildRunCardProps {
  childRunId: string;
}

export default function ChildRunCard({ childRunId }: ChildRunCardProps) {
  const { childRun } = useChildRunSSE(childRunId);
  const [expanded, setExpanded] = useState(true);

  if (!childRun) {
    return (
      <div className="rounded-lg border border-purple-500/30 bg-purple-600/5 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs text-purple-400">
          <Users size={12} />
          <span>Sub-agent: {childRunId.slice(0, 8)}…</span>
          <Loader2 size={12} className="animate-spin" />
        </div>
      </div>
    );
  }

  const isActive =
    childRun.status === "reacting" || childRun.status === "planning";
  const isDone = ["completed", "failed", "cancelled"].includes(childRun.status);
  const statusColor =
    childRun.status === "completed"
      ? "text-emerald-500"
      : childRun.status === "failed"
        ? "text-red-500"
        : "text-purple-400";

  return (
    <div className="rounded-lg border border-purple-500/30 bg-purple-600/5 overflow-hidden animate-fade-in">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-purple-600/10 transition-colors"
      >
        <Users size={12} className="text-purple-400 flex-shrink-0" />
        <span className="font-medium t-secondary">Sub-agent</span>
        <span className="t-faint">•</span>
        <span className={`font-medium ${statusColor}`}>{childRun.status}</span>
        <span className="t-faint">•</span>
        <span className="t-muted">
          {childRun.iterations}/{childRun.max_iterations}
        </span>
        {isActive && <Loader2 size={10} className="animate-spin text-purple-400" />}
        <span className="ml-auto">
          {expanded ? (
            <ChevronDown size={10} className="t-faint" />
          ) : (
            <ChevronRight size={10} className="t-faint" />
          )}
        </span>
      </button>

      {expanded && (
        <div className="px-3 pb-2.5 border-t border-purple-500/20">
          {/* Task description */}
          <div className="text-[11px] t-muted py-1.5 italic">
            Task: {childRun.user_message}
          </div>

          {/* Observations */}
          <div className="space-y-0.5">
            {childRun.observations.map((obs, i) => (
              <CompactObservation key={obs.step_id + "-" + obs.iteration} obs={obs} index={i} />
            ))}
          </div>

          {/* Active spinner */}
          {isActive && (
            <div className="flex items-center gap-2 text-[11px] t-muted py-1">
              <Loader2 size={10} className="text-purple-400 animate-spin" />
              <span>Thinking…</span>
            </div>
          )}

          {/* Final response */}
          {isDone && childRun.final_response && (
            <div className="text-[11px] t-secondary bg-app-code rounded px-2 py-1 mt-1.5 max-h-16 overflow-y-auto">
              {childRun.final_response.slice(0, 400)}
              {childRun.final_response.length > 400 && "…"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CompactObservation({ obs, index }: { obs: Observation; index: number }) {
  const isFinal = !obs.tool;
  const status = obs.result?.status;

  const icon =
    isFinal || status === "success" ? (
      <CheckCircle2 size={10} className="text-emerald-500 flex-shrink-0" />
    ) : status === "error" ? (
      <XCircle size={10} className="text-red-500 flex-shrink-0" />
    ) : (
      <Loader2 size={10} className="t-faint flex-shrink-0" />
    );

  return (
    <div className="flex items-center gap-1.5 text-[11px] py-0.5">
      {icon}
      <span className="t-faint font-mono w-3">{index + 1}</span>
      <span className="t-secondary truncate flex-1">
        {obs.user_announcement || (isFinal ? "Done" : obs.tool)}
      </span>
      {status === "error" && (
        <span className="text-[9px] text-red-500">error</span>
      )}
    </div>
  );
}
