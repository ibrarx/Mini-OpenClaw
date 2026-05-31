/**
 * Settings panel — appearance (theme), backend status, tools with descriptions, memory stats.
 */

import { useState, useEffect } from "react";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Wrench,
  RefreshCw,
  Sun,
  Moon,
  Monitor,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  FolderOpen,
  Lock,
} from "lucide-react";
import { getTools, healthCheck, getMemory } from "../api/client";
import { RiskBadge } from "./PlanPreview";
import { useTheme } from "../App";
import type { ThemeMode } from "../App";
import type { ToolManifest } from "../api/types";

interface SettingsProps {
  sessionId: string;
  onResetSession: () => void;
}

const THEME_OPTIONS: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export default function Settings({ sessionId, onResetSession }: SettingsProps) {
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [memoryCounts, setMemoryCounts] = useState<Record<string, number>>({});
  const [mounts, setMounts] = useState<
    { name: string; path: string; read_only: boolean; exists: boolean }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const { theme, setTheme } = useTheme();

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [h, t, m] = await Promise.allSettled([
        healthCheck(),
        getTools(),
        getMemory(),
      ]);
      if (h.status === "fulfilled") {
        const data = h.value as Record<string, unknown>;
        setHealthy(data.status === "ok");
        if (Array.isArray(data.mounts)) {
          setMounts(
            data.mounts as {
              name: string;
              path: string;
              read_only: boolean;
              exists: boolean;
            }[],
          );
        }
      } else {
        setHealthy(false);
      }
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
      <div className="flex items-center justify-center py-12 t-muted">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-4 space-y-5 max-w-2xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium t-secondary">Settings</h2>
        <button onClick={fetchAll} className="btn btn-ghost text-xs p-1">
          <RefreshCw size={12} />
        </button>
      </div>

      {/* Appearance */}
      <Section title="Appearance">
        <div className="flex gap-2">
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => setTheme(value)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all flex-1 justify-center ${
                theme === value
                  ? "border-blue-500 bg-blue-500/10 text-blue-400"
                  : "border-app-secondary t-muted hover:t-secondary"
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>
      </Section>

      {/* Backend status */}
      <Section title="Backend">
        <div className="flex items-center gap-2 text-sm">
          {healthy ? (
            <>
              <CheckCircle2 size={14} className="text-emerald-400" />
              <span className="t-secondary">Connected</span>
            </>
          ) : (
            <>
              <XCircle size={14} className="text-red-400" />
              <span className="text-red-400">Unreachable</span>
            </>
          )}
          <span className="text-xs t-faint ml-auto">localhost:8000</span>
        </div>
      </Section>

      {/* Session */}
      <Section title="Session">
        <div className="flex items-center gap-2">
          <code className="text-xs font-mono t-muted bg-app-secondary px-2 py-0.5 rounded flex-1 truncate">
            {sessionId}
          </code>
          <button onClick={onResetSession} className="btn btn-ghost text-xs">
            Reset
          </button>
        </div>
      </Section>

      {/* Directories */}
      <Section title="Directories">
        <div className="space-y-1.5">
          <div className="card px-2.5 py-2 flex items-center gap-2">
            <FolderOpen size={12} className="t-muted flex-shrink-0" />
            <span className="text-xs t-muted">Primary</span>
            <code className="font-mono text-xs t-secondary flex-1 truncate ml-1">
              workspace
            </code>
          </div>
          {mounts.length === 0 ? (
            <p className="text-xs t-faint italic px-1">
              No extra mounts configured. Set WORKSPACE_MOUNTS in .env to add
              directories.
            </p>
          ) : (
            mounts.map((m) => (
              <div
                key={m.name}
                className="card px-2.5 py-2 flex items-center gap-2"
              >
                <FolderOpen size={12} className="t-muted flex-shrink-0" />
                <span className="font-mono text-xs t-secondary">
                  {m.name}:
                </span>
                <code className="font-mono text-[10px] t-muted flex-1 truncate">
                  {m.path}
                </code>
                {m.read_only && (
                  <Lock size={10} className="text-amber-400 flex-shrink-0" />
                )}
                {!m.exists && (
                  <XCircle size={10} className="text-red-400 flex-shrink-0" />
                )}
              </div>
            ))
          )}
        </div>
      </Section>

      {/* Registered tools */}
      <Section title={`Tools (${tools.length})`}>
        {tools.length === 0 ? (
          <p className="text-xs t-muted italic">No tools registered</p>
        ) : (
          <div className="space-y-1.5">
            {tools.map((tool) => (
              <ToolRow key={tool.name} tool={tool} />
            ))}
          </div>
        )}
      </Section>

      {/* Memory stats */}
      <Section title="Memory">
        <div className="grid grid-cols-3 gap-2 text-center">
          {(["fact", "episode", "summary"] as const).map((type) => (
            <div key={type} className="card px-2 py-2">
              <div className="text-lg font-semibold t-primary">
                {memoryCounts[type] ?? 0}
              </div>
              <div className="text-[10px] t-muted capitalize">{type}s</div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

// ── Tool Row (expandable with description) ────────────

function ToolRow({ tool }: { tool: ToolManifest }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-2 text-left hover:opacity-80 transition-colors"
      >
        <Wrench size={12} className="t-muted flex-shrink-0" />
        <span className="font-mono text-xs t-secondary flex-1">
          {tool.name}
        </span>
        <RiskBadge level={tool.risk_level} />
        {tool.approval_required && (
          <ShieldCheck size={12} className="text-amber-400 flex-shrink-0" />
        )}
        {expanded ? (
          <ChevronDown size={12} className="t-faint flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="t-faint flex-shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="px-2.5 pb-2.5 border-t border-app">
          <p className="text-xs t-muted leading-relaxed mt-2">
            {tool.description || "No description available."}
          </p>
          <div className="flex items-center gap-3 mt-2 text-[10px] t-faint">
            <span>
              Risk: <span className="t-muted">{tool.risk_level}</span>
            </span>
            <span>
              Approval:{" "}
              <span className="t-muted">
                {tool.approval_required ? "required" : "not required"}
              </span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Section ───────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-xs font-medium t-faint uppercase tracking-wider mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}
