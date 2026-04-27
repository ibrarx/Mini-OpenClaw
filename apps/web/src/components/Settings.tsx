/**
 * Settings panel — workspace config, API status, registered tools, memory stats.
 */

import { useState, useEffect } from "react";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Wrench,
  RefreshCw,
} from "lucide-react";
import { getTools, healthCheck, getMemory } from "../api/client";
import { RiskBadge } from "./PlanPreview";
import type { ToolManifest } from "../api/types";

interface SettingsProps {
  sessionId: string;
  onResetSession: () => void;
}

export default function Settings({ sessionId, onResetSession }: SettingsProps) {
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [memoryCounts, setMemoryCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [h, t, m] = await Promise.allSettled([
        healthCheck(),
        getTools(),
        getMemory(),
      ]);
      setHealthy(h.status === "fulfilled" && h.value.status === "ok");
      setTools(t.status === "fulfilled" ? t.value : []);

      if (m.status === "fulfilled") {
        const counts: Record<string, number> = {};
        for (const item of m.value) {
          counts[item.memory_type] = (counts[item.memory_type] ?? 0) + 1;
        }
        setMemoryCounts(counts);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-300">Settings</h2>
        <button onClick={fetchAll} className="btn btn-ghost text-xs p-1">
          <RefreshCw size={12} />
        </button>
      </div>

      {/* Backend status */}
      <Section title="Backend">
        <div className="flex items-center gap-2 text-sm">
          {healthy ? (
            <>
              <CheckCircle2 size={14} className="text-emerald-400" />
              <span className="text-gray-300">Connected</span>
            </>
          ) : (
            <>
              <XCircle size={14} className="text-red-400" />
              <span className="text-red-300">Unreachable</span>
            </>
          )}
          <span className="text-gray-600 text-xs ml-auto">localhost:8000</span>
        </div>
      </Section>

      {/* Session */}
      <Section title="Session">
        <div className="flex items-center gap-2">
          <code className="text-xs font-mono text-gray-400 bg-gray-900/60 px-2 py-0.5 rounded flex-1 truncate">
            {sessionId}
          </code>
          <button onClick={onResetSession} className="btn btn-ghost text-xs">
            Reset
          </button>
        </div>
      </Section>

      {/* Registered tools */}
      <Section title={`Tools (${tools.length})`}>
        {tools.length === 0 ? (
          <p className="text-xs text-gray-500 italic">No tools registered</p>
        ) : (
          <div className="space-y-1">
            {tools.map((tool) => (
              <div
                key={tool.name}
                className="flex items-center gap-2 px-2 py-1.5 rounded bg-gray-800/40 border border-gray-700/30"
              >
                <Wrench size={12} className="text-gray-500 flex-shrink-0" />
                <span className="font-mono text-xs text-gray-300 flex-1">
                  {tool.name}
                </span>
                <RiskBadge level={tool.risk_level} />
                {tool.approval_required && (
                  <span className="text-[10px] text-amber-400">🔒</span>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Memory stats */}
      <Section title="Memory">
        <div className="grid grid-cols-3 gap-2 text-center">
          {(["fact", "episode", "summary"] as const).map((type) => (
            <div
              key={type}
              className="card px-2 py-2"
            >
              <div className="text-lg font-semibold text-gray-200">
                {memoryCounts[type] ?? 0}
              </div>
              <div className="text-[10px] text-gray-500 capitalize">{type}s</div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}
