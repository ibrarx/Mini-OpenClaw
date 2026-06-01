/**
 * UsageDashboard — token usage and cost display (theme-aware).
 *
 * Two modes:
 *  - <RunUsageStrip run={run} />  — compact inline strip for run detail views
 *  - <SessionUsageDashboard sessionId={id} /> — full session rollup panel
 */

import { useState, useEffect } from "react";
import {
  Coins,
  Zap,
  AlertTriangle,
  Loader2,
  RefreshCw,
  BarChart3,
} from "lucide-react";
import { getUsageSummary } from "../api/client";
import type { UsageSummary } from "../api/client";
import type { Run, RunUsage } from "../api/types";

// ── Helpers ───────────────────────────────────────────

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.001) return "<$0.001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(3)}`;
}

// ── Per-run compact strip ─────────────────────────────

interface RunUsageStripProps {
  run: Run;
}

/**
 * Compact one-line usage summary for a single run.
 * Shows total tokens, cost, LLM call count, and estimated badge.
 */
export function RunUsageStrip({ run }: RunUsageStripProps) {
  const u = run.usage;
  if (!u || u.llm_calls === 0) return null;

  const total = u.input_tokens + u.output_tokens;

  return (
    <div className="flex items-center gap-2 text-[10px] t-faint flex-wrap">
      <span className="flex items-center gap-0.5" title="Total tokens">
        <Zap size={10} />
        {fmtTokens(total)} tokens
      </span>
      <span>•</span>
      <span className="flex items-center gap-0.5" title="Estimated cost">
        <Coins size={10} />
        {fmtCost(u.cost_usd)}
      </span>
      <span>•</span>
      <span>{u.llm_calls} LLM call{u.llm_calls !== 1 ? "s" : ""}</span>
      {u.has_estimates && (
        <span
          className="badge bg-amber-500/15 text-amber-600"
          title="Some calls used estimated token counts (char/4 heuristic)"
        >
          <AlertTriangle size={8} className="mr-0.5" />
          estimated
        </span>
      )}
    </div>
  );
}

// ── Per-run phase breakdown bar ───────────────────────

interface PhaseBarProps {
  byPhase: Record<string, number>;
}

const PHASE_COLORS: Record<string, string> = {
  planning: "bg-blue-500",
  react: "bg-emerald-500",
  reflection: "bg-purple-500",
  goals: "bg-cyan-500",
  replan: "bg-amber-500",
  synthesis: "bg-pink-500",
  improve: "bg-indigo-500",
  summary: "bg-gray-500",
};

export function PhaseBar({ byPhase }: PhaseBarProps) {
  const entries = Object.entries(byPhase).filter(([, v]) => v > 0);
  if (entries.length === 0) return null;
  const total = entries.reduce((sum, [, v]) => sum + v, 0);

  return (
    <div className="space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden bg-app-code">
        {entries.map(([phase, tokens]) => (
          <div
            key={phase}
            className={`${PHASE_COLORS[phase] || "bg-gray-400"} transition-all`}
            style={{ width: `${(tokens / total) * 100}%` }}
            title={`${phase}: ${fmtTokens(tokens)} tokens`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[9px] t-faint">
        {entries.map(([phase, tokens]) => (
          <span key={phase} className="flex items-center gap-1">
            <span
              className={`w-1.5 h-1.5 rounded-full ${PHASE_COLORS[phase] || "bg-gray-400"}`}
            />
            {phase} ({fmtTokens(tokens)})
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Per-run detail panel ──────────────────────────────

interface RunUsageDetailProps {
  run: Run;
}

export function RunUsageDetail({ run }: RunUsageDetailProps) {
  const u = run.usage;
  if (!u || u.llm_calls === 0) return null;

  return (
    <div className="space-y-2 text-xs">
      <RunUsageStrip run={run} />
      {Object.keys(u.by_phase).length > 0 && (
        <PhaseBar byPhase={u.by_phase} />
      )}
      {Object.keys(u.by_tool).length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] t-faint">
          <span className="t-secondary font-medium">By tool:</span>
          {Object.entries(u.by_tool)
            .sort(([, a], [, b]) => b - a)
            .map(([tool, tokens]) => (
              <span key={tool} className="font-mono">
                {tool}: {fmtTokens(tokens)}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

// ── Session rollup dashboard ──────────────────────────

interface SessionUsageDashboardProps {
  sessionId: string;
}

export default function SessionUsageDashboard({
  sessionId,
}: SessionUsageDashboardProps) {
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await getUsageSummary(sessionId);
      setData(summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load usage");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 t-muted">
        <Loader2 size={18} className="animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-xs">
        <div className="text-red-600 bg-red-500/10 px-3 py-2 rounded border border-red-500/20">
          {error}
        </div>
        <button onClick={fetchData} className="btn btn-ghost mt-2 text-xs">
          <RefreshCw size={12} /> Retry
        </button>
      </div>
    );
  }

  if (!data || data.run_count === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 t-muted gap-2">
        <BarChart3 size={22} className="opacity-40" />
        <p className="text-xs">No usage data yet</p>
      </div>
    );
  }

  const t = data.totals;
  const totalTokens = t.input_tokens + t.output_tokens;
  const models = Object.entries(data.by_model);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium t-secondary flex items-center gap-1.5">
          <BarChart3 size={14} />
          Token Usage &amp; Cost
        </h3>
        <button onClick={fetchData} className="btn btn-ghost text-xs p-1">
          <RefreshCw size={12} />
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatCard label="Total tokens" value={fmtTokens(totalTokens)} />
        <StatCard label="Est. cost" value={fmtCost(t.cost_usd)} />
        <StatCard label="LLM calls" value={String(t.llm_calls)} />
        <StatCard label="Runs" value={String(data.run_count)} />
      </div>

      {data.has_estimates && (
        <div className="flex items-center gap-1.5 text-[10px] text-amber-600 bg-amber-500/10 px-2.5 py-1.5 rounded border border-amber-500/20">
          <AlertTriangle size={12} />
          Some runs used estimated token counts (char/4 heuristic).
          Figures marked "estimated" are approximate.
        </div>
      )}

      {/* Per-model breakdown */}
      {models.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-[11px] font-medium t-secondary">By model</h4>
          <div className="space-y-1">
            {models.map(([model, stats]) => (
              <div
                key={model}
                className="flex items-center gap-2 text-[10px] px-2.5 py-1.5 rounded bg-app-code"
              >
                <span className="font-mono t-primary flex-1 truncate">
                  {model}
                </span>
                <span className="t-faint">
                  {stats.provider && `${stats.provider} · `}
                  {fmtTokens(stats.input_tokens + stats.output_tokens)} tokens
                </span>
                <span className="t-faint">
                  {fmtCost(stats.cost_usd)}
                </span>
                <span className="t-faint">
                  {stats.llm_calls} call{stats.llm_calls !== 1 ? "s" : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Phase breakdown */}
      {Object.keys(data.by_phase).length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-[11px] font-medium t-secondary">
            Tokens by phase
          </h4>
          <PhaseBar byPhase={data.by_phase} />
        </div>
      )}

      {/* Pricing caveat */}
      <p className="text-[9px] t-faint leading-relaxed">
        Estimated costs based on public pricing as of{" "}
        {data.pricing_last_verified}. Verify against your provider's billing
        page for authoritative figures. Local models (Ollama) show $0.00.
      </p>
    </div>
  );
}

// ── Small stat card ───────────────────────────────────

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-app-code px-2.5 py-2 text-center">
      <div className="text-sm font-semibold t-primary">{value}</div>
      <div className="text-[9px] t-faint mt-0.5">{label}</div>
    </div>
  );
}
