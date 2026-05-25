/**
 * SchedulerPage — View and manage scheduled tasks.
 *
 * Shows a table of all scheduled tasks with status, timing info,
 * and action buttons for pause/resume/delete.
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
} from "lucide-react";
import {
  getScheduledTasks,
  pauseTask,
  resumeTask,
  deleteTask,
} from "../api/client";
import type { ScheduledTask, TaskStatus } from "../api/types";

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

export default function SchedulerPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

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
    // Auto-refresh every 10s
    const interval = setInterval(fetchTasks, 10_000);
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
              Ask the agent to schedule something — try{" "}
              <span className="font-mono text-blue-400/70">
                "check my workspace for new files every 5 minutes"
              </span>
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task) => (
              <div
                key={task.id}
                className="rounded-lg border border-app bg-app-surface p-3 transition-colors hover:border-app-hover"
              >
                {/* Top row: message + status */}
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm t-primary truncate" title={task.message}>
                      {task.message}
                    </p>
                  </div>
                  {statusBadge(task.status)}
                </div>

                {/* Meta row */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] t-faint">
                  {/* Type */}
                  <span className="flex items-center gap-1">
                    {task.schedule_type === "interval" ? (
                      <Repeat size={11} />
                    ) : (
                      <Timer size={11} />
                    )}
                    {task.schedule_type === "interval"
                      ? `Every ${intervalLabel(task.interval_seconds)}`
                      : "One-time"}
                  </span>

                  {/* Next run */}
                  {task.status === "active" && (
                    <span title={formatTime(task.next_run_at)}>
                      Next: {relativeTime(task.next_run_at)}
                    </span>
                  )}

                  {/* Run count */}
                  <span>
                    Runs: {task.run_count}
                    {task.max_runs > 0 ? `/${task.max_runs}` : ""}
                  </span>

                  {/* Last run */}
                  {task.last_run_at && (
                    <span title={formatTime(task.last_run_at)}>
                      Last: {relativeTime(task.last_run_at)}
                    </span>
                  )}

                  {/* Created */}
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
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
