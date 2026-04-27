/**
 * RunHistory — shows a list of past runs from GET /api/runs.
 */

import { useState, useEffect } from "react";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  RefreshCw,
} from "lucide-react";
import { getRuns } from "../api/client";
import PlanPreview from "./PlanPreview";
import type { Run, RunStatus } from "../api/types";

interface RunHistoryProps {
  sessionId: string;
}

export default function RunHistory({ sessionId }: RunHistoryProps) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const fetchRuns = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getRuns(sessionId);
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="text-sm text-red-400 bg-red-500/10 px-3 py-2 rounded border border-red-500/20">
          {error}
        </div>
        <button onClick={fetchRuns} className="btn btn-ghost mt-2 text-xs">
          <RefreshCw size={12} /> Retry
        </button>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-500 gap-2">
        <Clock size={24} className="opacity-40" />
        <p className="text-sm">No runs yet</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-300">Run History</h2>
        <button onClick={fetchRuns} className="btn btn-ghost text-xs p-1">
          <RefreshCw size={12} />
        </button>
      </div>
      <div className="space-y-1.5">
        {runs.map((run) => (
          <RunRow
            key={run.run_id}
            run={run}
            expanded={expandedRun === run.run_id}
            onToggle={() =>
              setExpandedRun(
                expandedRun === run.run_id ? null : run.run_id
              )
            }
          />
        ))}
      </div>
    </div>
  );
}

// ── Run Row ───────────────────────────────────────────

interface RunRowProps {
  run: Run;
  expanded: boolean;
  onToggle: () => void;
}

function RunRow({ run, expanded, onToggle }: RunRowProps) {
  const stepCount = run.plan?.steps.length ?? 0;

  return (
    <div className="card overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-gray-800/50 transition-colors"
      >
        <RunStatusIcon status={run.status} />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-200 truncate">{run.user_message}</p>
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
            <span>{formatTimestamp(run.created_at)}</span>
            {stepCount > 0 && (
              <>
                <span>•</span>
                <span>{stepCount} step{stepCount !== 1 ? "s" : ""}</span>
              </>
            )}
          </div>
        </div>
        <StatusBadge status={run.status} />
        {expanded ? (
          <ChevronDown size={14} className="text-gray-500 flex-shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-gray-500 flex-shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-gray-800 px-3 py-2.5 bg-gray-900/40">
          {run.plan && (
            <PlanPreview plan={run.plan} compact />
          )}
          {run.final_response && (
            <div className="mt-2 text-xs text-gray-400 bg-gray-900/60 rounded px-2.5 py-2 leading-relaxed">
              {run.final_response}
            </div>
          )}
          {!run.plan && !run.final_response && (
            <p className="text-xs text-gray-500 italic">No plan data</p>
          )}
        </div>
      )}
    </div>
  );
}

function RunStatusIcon({ status }: { status: RunStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={16} className="text-emerald-400 flex-shrink-0" />;
    case "failed":
      return <XCircle size={16} className="text-red-400 flex-shrink-0" />;
    case "cancelled":
      return <XCircle size={16} className="text-gray-400 flex-shrink-0" />;
    case "awaiting_approval":
      return <AlertTriangle size={16} className="text-amber-400 flex-shrink-0" />;
    case "planning":
    case "running":
      return <Loader2 size={16} className="text-blue-400 animate-spin flex-shrink-0" />;
    default:
      return <Clock size={16} className="text-gray-500 flex-shrink-0" />;
  }
}

function StatusBadge({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    idle: "bg-gray-700/50 text-gray-400",
    planning: "bg-blue-500/15 text-blue-400",
    running: "bg-blue-500/15 text-blue-400",
    awaiting_approval: "bg-amber-500/15 text-amber-400",
    completed: "bg-emerald-500/15 text-emerald-400",
    failed: "bg-red-500/15 text-red-400",
    cancelled: "bg-gray-600/30 text-gray-400",
  };

  return (
    <span className={`badge ${map[status] ?? ""}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}
