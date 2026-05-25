/**
 * SchedulerPage — View and manage scheduled tasks with run history.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Clock,
  Pause,
  Play,
  Trash2,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Timer,
  Repeat,
  ChevronDown,
  ChevronUp,
  XCircle,
  Loader2,
  Activity,
} from "lucide-react";
import {
  getScheduledTasks,
  pauseTask,
  resumeTask,
  deleteTask,
  getTaskRuns,
  getRun,
  approveStep,
  rejectStep,
} from "../api/client";
import type { ScheduledTask, TaskStatus, Run, RunStatus, PlanStep } from "../api/types";
import ApprovalCard from "../components/ApprovalCard";

/* ── Helpers ───────────────────────────────────────── */

function statusBadge(status: TaskStatus) {
  const map: Record<TaskStatus, { color: string; icon: typeof Clock; label: string }> = {
    active: { color: "text-emerald-400 bg-emerald-400/10", icon: Play, label: "Active" },
    paused: { color: "text-yellow-400 bg-yellow-400/10", icon: Pause, label: "Paused" },
    completed: { color: "text-blue-400 bg-blue-400/10", icon: CheckCircle2, label: "Completed" },
    failed: { color: "text-red-400 bg-red-400/10", icon: AlertCircle, label: "Failed" },
  };
  const cfg = map[status] || map.active;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.color}`}>
      <Icon size={11} />
      {cfg.label}
    </span>
  );
}

function runStatusIcon(status: RunStatus) {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    case "failed":
      return <XCircle size={12} className="text-red-400" />;
    case "cancelled":
      return <XCircle size={12} className="text-yellow-400" />;
    case "running":
    case "reacting":
    case "planning":
    case "reflecting":
      return <Loader2 size={12} className="text-blue-400 animate-spin" />;
    default:
      return <Activity size={12} className="t-faint" />;
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diff = d.getTime() - now;
    if (Math.abs(diff) < 60_000) return diff > 0 ? "in <1m" : "<1m ago";
    const mins = Math.round(diff / 60_000);
    if (Math.abs(mins) < 60) return mins > 0 ? `in ${mins}m` : `${-mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (Math.abs(hrs) < 24) return hrs > 0 ? `in ${hrs}h` : `${-hrs}h ago`;
    const days = Math.round(hrs / 24);
    return days > 0 ? `in ${days}d` : `${-days}d ago`;
  } catch {
    return iso;
  }
}

function intervalLabel(seconds: number | null): string {
  if (!seconds) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

/** Truncate text with ellipsis. */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

/* ── Inflight Approval Card ─────────────────────────── */

function InflightApproval({ runId, onDecided }: { runId: string; onDecided: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const [pendingStep, setPendingStep] = useState<PlanStep | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      getRun(runId)
        .then((r) => {
          if (cancelled) return;
          setRun(r);
          if (r.status === "awaiting_approval" && r.plan?.steps) {
            const step = r.plan.steps.find((s) => s.status === "awaiting_approval");
            setPendingStep(step ?? null);
          } else {
            setPendingStep(null);
          }
        })
        .catch(() => {});
    poll();
    const id = setInterval(poll, 3_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId]);

  if (!pendingStep || !run) return null;

  return (
    <div className="mt-2">
      <ApprovalCard
        step={pendingStep}
        runId={runId}
        onApprove={async (rid, sid) => {
          await approveStep(rid, sid);
          onDecided();
        }}
        onReject={async (rid, sid) => {
          await rejectStep(rid, sid);
          onDecided();
        }}
      />
    </div>
  );
}

/* ── Run History Panel ─────────────────────────────── */

function TaskRunHistory({ taskId }: { taskId: string }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [limit, setLimit] = useState(5);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getTaskRuns(taskId, limit)
      .then((data) => { if (!cancelled) setRuns(data); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId, limit]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-[11px] t-faint">
        <Loader2 size={11} className="animate-spin" /> Loading runs…
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="py-2 text-[11px] t-faint">
        No runs yet — waiting for first execution.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] t-faint">{runs.length} run{runs.length !== 1 ? "s" : ""} shown</span>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="text-[11px] t-muted bg-transparent border border-app rounded px-1.5 py-0.5 focus:outline-none focus:border-blue-500"
        >
          {[5, 10, 25, 50].map((n) => (
            <option key={n} value={n}>Last {n}</option>
          ))}
        </select>
      </div>
      {runs.map((run) => {
        const isExpanded = expandedRun === run.run_id;
        const response = run.final_response || "(no response)";
        return (
          <div key={run.run_id} className="rounded border border-app bg-app/50">
            <button
              onClick={() => setExpandedRun(isExpanded ? null : run.run_id)}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] hover:bg-app-hover/30 transition-colors"
            >
              {runStatusIcon(run.status)}
              <span className="t-muted flex-1 min-w-0 truncate">
                {truncate(response.replace(/\*\*/g, "").replace(/\n/g, " "), 80)}
              </span>
              <span className="t-faint whitespace-nowrap">
                {relativeTime(run.created_at)}
              </span>
              {isExpanded ? <ChevronUp size={11} className="t-faint" /> : <ChevronDown size={11} className="t-faint" />}
            </button>
            {isExpanded && (
              <div className="px-2.5 pb-2.5 border-t border-app">
                <div className="mt-2 text-[11px] t-secondary whitespace-pre-wrap break-words max-h-48 overflow-y-auto leading-relaxed">
                  {response}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] t-faint">
                  <span>Status: {run.status}</span>
                  <span>Steps: {run.plan?.steps?.length ?? 0}</span>
                  <span>Iterations: {run.iterations}/{run.max_iterations}</span>
                  <span>{formatTime(run.created_at)}</span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────── */

export default function SchedulerPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [expandedTask, setExpandedTask] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      setError(null);
      const data = await getScheduledTasks();
      setTasks(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5_000); // 5s refresh
    return () => clearInterval(interval);
  }, [fetchTasks]);

  const handlePause = async (taskId: string) => {
    setActionLoading(taskId);
    try {
      const updated = await pauseTask(taskId);
      setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to pause task");
    } finally {
      setActionLoading(null);
    }
  };

  const handleResume = async (taskId: string) => {
    setActionLoading(taskId);
    try {
      const updated = await resumeTask(taskId);
      setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to resume task");
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (taskId: string) => {
    if (!confirm("Delete this scheduled task? This cannot be undone.")) return;
    setActionLoading(taskId);
    try {
      await deleteTask(taskId);
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete task");
    } finally {
      setActionLoading(null);
    }
  };

  // Count tasks that ran in the last 2 minutes (for parent badge)
  const recentlyFired = tasks.filter((t) => {
    if (!t.last_run_at) return false;
    return Date.now() - new Date(t.last_run_at).getTime() < 120_000;
  }).length;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-app">
        <div className="flex items-center gap-2">
          <Clock size={16} className="t-muted" />
          <h2 className="text-sm font-semibold t-primary">Scheduled Tasks</h2>
          <span className="text-[11px] t-faint">
            {tasks.length} task{tasks.length !== 1 ? "s" : ""}
          </span>
          {recentlyFired > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium text-emerald-400 bg-emerald-400/10 animate-pulse">
              <Activity size={10} />
              {recentlyFired} ran recently
            </span>
          )}
        </div>
        <button
          onClick={fetchTasks}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs t-muted hover:t-secondary transition-colors"
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mt-3 px-3 py-2 rounded-md bg-red-500/10 text-red-400 text-xs flex items-center gap-2">
          <AlertCircle size={13} />
          {error}
          <button onClick={() => setError(null)} className="ml-auto hover:text-red-300">✕</button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && tasks.length === 0 ? (
          <div className="flex items-center justify-center h-32 t-faint text-sm">
            Loading scheduled tasks…
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 gap-3">
            <Clock size={32} className="t-faint" />
            <p className="t-muted text-sm">No scheduled tasks yet.</p>
            <p className="t-faint text-xs max-w-xs text-center">
              Ask the agent to schedule something.
              <br />
              Try:{" "}
              <span className="font-mono text-blue-400/70">
                "Every 2 minutes, list all files in the workspace and tell me the total count"
              </span>
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => {
              const isExpanded = expandedTask === task.id;
              return (
                <div
                  key={task.id}
                  className="rounded-lg border border-app bg-app-surface transition-colors"
                >
                  {/* Card header — clickable to expand */}
                  <div className="p-3">
                    {/* Top row: message + status */}
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm t-primary" title={task.message}>
                          {task.message}
                        </p>
                      </div>
                      {statusBadge(task.status)}
                    </div>

                    {/* Meta row */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] t-faint">
                      <span className="flex items-center gap-1">
                        {task.schedule_type === "interval" ? <Repeat size={11} /> : <Timer size={11} />}
                        {task.schedule_type === "interval"
                          ? `Every ${intervalLabel(task.interval_seconds)}`
                          : "One-time"}
                      </span>

                      {task.status === "active" && (
                        <span title={formatTime(task.next_run_at)}>
                          Next: {relativeTime(task.next_run_at)}
                        </span>
                      )}

                      <span>
                        Runs: {task.run_count}
                        {task.max_runs > 0 ? `/${task.max_runs}` : ""}
                      </span>

                      {/* In-flight indicator */}
                      {task.inflight_run_id && (
                        <span className="flex items-center gap-1 text-blue-400">
                          <Loader2 size={11} className="animate-spin" />
                          Running…
                        </span>
                      )}

                      {task.last_run_at && (
                        <span title={formatTime(task.last_run_at)}>
                          Last: {relativeTime(task.last_run_at)}
                        </span>
                      )}

                      <span title={formatTime(task.created_at)}>
                        Created: {formatTime(task.created_at)}
                      </span>
                    </div>

                    {/* Pre-approved tools */}
                    {task.pre_approved_tools.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="t-faint">Pre-approved:</span>
                        {task.pre_approved_tools.map((tool) => (
                          <span
                            key={tool}
                            className="px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-400 font-mono"
                          >
                            {tool}
                          </span>
                        ))}
                        {task.schedule_type === "interval" && (
                          <span className={task.approve_all_runs ? "text-emerald-400" : "text-yellow-400"}>
                            ({task.approve_all_runs ? "all runs" : "first run only"})
                          </span>
                        )}
                      </div>
                    )}

                    {/* Error */}
                    {task.error && (
                      <div className="mt-2 px-2 py-1.5 rounded bg-red-500/10 text-red-400 text-[11px] truncate" title={task.error}>
                        {task.error}
                      </div>
                    )}

                    {/* Inflight approval card */}
                    {task.inflight_run_id && (
                      <InflightApproval
                        runId={task.inflight_run_id}
                        onDecided={fetchTasks}
                      />
                    )}

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-app">
                      {task.status === "active" && (
                        <button
                          onClick={() => handlePause(task.id)}
                          disabled={actionLoading === task.id}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] t-muted hover:text-yellow-400 hover:bg-yellow-400/10 transition-colors disabled:opacity-50"
                        >
                          <Pause size={11} /> Pause
                        </button>
                      )}
                      {task.status === "paused" && (
                        <button
                          onClick={() => handleResume(task.id)}
                          disabled={actionLoading === task.id}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] t-muted hover:text-emerald-400 hover:bg-emerald-400/10 transition-colors disabled:opacity-50"
                        >
                          <Play size={11} /> Resume
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(task.id)}
                        disabled={actionLoading === task.id}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[11px] t-muted hover:text-red-400 hover:bg-red-400/10 transition-colors disabled:opacity-50"
                      >
                        <Trash2 size={11} /> Delete
                      </button>

                      {/* Expand run history */}
                      {task.run_count > 0 && (
                        <button
                          onClick={() => setExpandedTask(isExpanded ? null : task.id)}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] t-muted hover:text-blue-400 hover:bg-blue-400/10 transition-colors ml-auto"
                        >
                          <Activity size={11} />
                          {isExpanded ? "Hide" : "View"} runs
                          {isExpanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded run history */}
                  {isExpanded && (
                    <div className="px-3 pb-3 border-t border-app">
                      <div className="mt-2">
                        <TaskRunHistory taskId={task.id} />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
