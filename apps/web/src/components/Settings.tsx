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
  HelpCircle,
  Plug,
} from "lucide-react";
import { getTools, healthCheck, getMemory, getClarificationSettings, updateClarificationSettings } from "../api/client";
import type { ClarificationSettings } from "../api/client";
import { RiskBadge } from "./PlanPreview";
import SessionUsageDashboard from "./UsageDashboard";
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
  const [clarification, setClarification] = useState<ClarificationSettings | null>(null);
  const { theme, setTheme } = useTheme();

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [h, t, m, c] = await Promise.allSettled([
        healthCheck(),
        getTools(),
        getMemory(),
        getClarificationSettings(),
      ]);
      if (h.status === "fulfilled") {
        const data = h.value;
        setHealthy(data.status === "ok");
        if (data.mounts) {
          setMounts(data.mounts);
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

      if (c.status === "fulfilled") {
        setClarification(c.value);
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

      {/* Clarification gate */}
      {clarification && (
        <Section title="Clarification Gate">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <HelpCircle size={13} className="text-blue-400" />
                <span className="text-xs t-secondary">Ask before acting on vague requests</span>
              </div>
              <button
                onClick={async () => {
                  const updated = await updateClarificationSettings({
                    enabled: !clarification.enabled,
                  });
                  setClarification(updated);
                }}
                className={`relative w-9 h-5 rounded-full transition-colors ${
                  clarification.enabled ? "bg-blue-500" : "bg-gray-500/40"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                    clarification.enabled ? "translate-x-4" : ""
                  }`}
                />
              </button>
            </div>

            {clarification.enabled && (
              <>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] t-faint">Confidence threshold</span>
                    <span className="text-[10px] font-mono t-muted">
                      {clarification.threshold.toFixed(2)}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={clarification.threshold}
                    onChange={async (e) => {
                      const val = parseFloat(e.target.value);
                      setClarification({ ...clarification, threshold: val });
                      await updateClarificationSettings({ threshold: val });
                    }}
                    className="w-full h-1.5 rounded-full appearance-none bg-gray-500/30 accent-blue-500"
                  />
                  <div className="flex justify-between text-[9px] t-faint mt-0.5">
                    <span>Confident (rarely asks)</span>
                    <span>Cautious (asks often)</span>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-[10px] t-faint">Max rounds</span>
                  <div className="flex items-center gap-1.5">
                    {[1, 2, 3].map((n) => (
                      <button
                        key={n}
                        onClick={async () => {
                          const updated = await updateClarificationSettings({ max_rounds: n });
                          setClarification(updated);
                        }}
                        className={`w-6 h-6 rounded text-[10px] font-mono transition-all ${
                          clarification.max_rounds === n
                            ? "bg-blue-500/20 text-blue-400 border border-blue-500/40"
                            : "bg-app-secondary t-muted border border-app hover:t-secondary"
                        }`}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}

            <p className="text-[10px] t-faint leading-relaxed">
              When enabled, the agent asks clarifying questions if its confidence
              is below the threshold. Changes apply immediately but reset on restart.
            </p>
          </div>
        </Section>
      )}

      {/* Directories */}
      <Section title="Directories">
        <div className="space-y-2">
          {/* Primary workspace — prominent */}
          <div className="card px-3 py-2.5 border-blue-500/30">
            <div className="flex items-center gap-2">
              <FolderOpen size={14} className="text-blue-400 flex-shrink-0" />
              <span className="text-xs font-medium t-secondary flex-1">
                Primary workspace
              </span>
              <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
                read &amp; write
              </span>
            </div>
            <code className="block font-mono text-[10px] t-muted mt-1.5 ml-[22px] break-all leading-relaxed">
              ./workspace
            </code>
          </div>

          {/* Mounts */}
          {mounts.length === 0 ? (
            <p className="text-xs t-faint italic px-1">
              No extra mounts. Set WORKSPACE_MOUNTS in .env to add directories.
            </p>
          ) : (
            <>
              <div className="text-[10px] t-faint uppercase tracking-wider mt-1 mb-0.5 px-1">
                Mounted directories
              </div>
              {mounts.map((m) => (
                <div key={m.name} className="card px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <FolderOpen size={13} className="t-muted flex-shrink-0" />
                    <span className="font-mono text-xs t-secondary font-medium">
                      {m.name}:
                    </span>
                    <span className="flex-1" />
                    {m.read_only ? (
                      <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium">
                        <Lock size={9} />
                        read-only
                      </span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
                        read &amp; write
                      </span>
                    )}
                    {!m.exists && (
                      <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 font-medium">
                        <XCircle size={9} />
                        missing
                      </span>
                    )}
                  </div>
                  <code className="block font-mono text-[10px] t-muted mt-1.5 ml-[21px] break-all leading-relaxed">
                    {m.path}
                  </code>
                </div>
              ))}
            </>
          )}
        </div>
      </Section>

      {/* Registered tools */}
      <ToolsSection tools={tools} />

      {/* Memory stats */}
      <Section title="Memory">
        <div className="grid grid-cols-5 gap-2 text-center">
          {(["fact", "episode", "summary", "strategy", "preference"] as const).map((type) => (
            <div key={type} className="card px-2 py-2">
              <div className="text-lg font-semibold t-primary">
                {memoryCounts[type] ?? 0}
              </div>
              <div className="text-[10px] t-muted capitalize">{type === "strategy" ? "strategies" : `${type}s`}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* Usage dashboard */}
      <Section title="Usage">
        <SessionUsageDashboard sessionId={sessionId} />
      </Section>
    </div>
  );
}

// ── Tools Section (Native + MCP grouped) ─────────────

/** Parse MCP tool name: mcp__{server}__{tool} → { server, tool } */
function parseMcpName(name: string): { server: string; tool: string } | null {
  const match = name.match(/^mcp__([A-Za-z0-9_]+)__(.+)$/);
  return match ? { server: match[1], tool: match[2] } : null;
}

interface McpServerGroup {
  name: string;
  tools: ToolManifest[];
}

function ToolsSection({ tools }: { tools: ToolManifest[] }) {
  const [nativeExpanded, setNativeExpanded] = useState(false);
  const [mcpExpanded, setMcpExpanded] = useState(true);

  const nativeTools = tools.filter((t) => !t.name.startsWith("mcp__"));
  const mcpTools = tools.filter((t) => t.name.startsWith("mcp__"));

  // Group MCP tools by server
  const mcpServers: McpServerGroup[] = [];
  const serverMap = new Map<string, ToolManifest[]>();
  for (const tool of mcpTools) {
    const parsed = parseMcpName(tool.name);
    if (!parsed) continue;
    const list = serverMap.get(parsed.server) ?? [];
    list.push(tool);
    serverMap.set(parsed.server, list);
  }
  for (const [name, serverTools] of serverMap) {
    mcpServers.push({ name, tools: serverTools });
  }

  return (
    <Section title={`Tools (${tools.length})`}>
      <div className="space-y-2">
        {/* Native tools accordion */}
        <div className="card overflow-hidden">
          <button
            onClick={() => setNativeExpanded(!nativeExpanded)}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:opacity-80 transition-colors"
          >
            <Wrench size={14} className="t-muted flex-shrink-0" />
            <span className="text-xs font-medium t-secondary flex-1">
              Native tools
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-app-secondary t-muted font-medium">
              {nativeTools.length}
            </span>
            {nativeExpanded ? (
              <ChevronDown size={13} className="t-faint flex-shrink-0" />
            ) : (
              <ChevronRight size={13} className="t-faint flex-shrink-0" />
            )}
          </button>
          {nativeExpanded && (
            <div className="px-2 pb-2 space-y-1 border-t border-app pt-1.5">
              {nativeTools.map((tool) => (
                <ToolRow key={tool.name} tool={tool} />
              ))}
            </div>
          )}
        </div>

        {/* MCP servers accordion */}
        {mcpServers.length > 0 && (
          <div className="card overflow-hidden">
            <button
              onClick={() => setMcpExpanded(!mcpExpanded)}
              className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:opacity-80 transition-colors"
            >
              <Plug size={14} className="t-muted flex-shrink-0" />
              <span className="text-xs font-medium t-secondary flex-1">
                MCP servers
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium">
                {mcpServers.length} connected
              </span>
              {mcpExpanded ? (
                <ChevronDown size={13} className="t-faint flex-shrink-0" />
              ) : (
                <ChevronRight size={13} className="t-faint flex-shrink-0" />
              )}
            </button>
            {mcpExpanded && (
              <div className="px-2 pb-2 space-y-1.5 border-t border-app pt-1.5">
                {mcpServers.map((server) => (
                  <McpServerBlock key={server.name} server={server} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* No MCP hint when there are none */}
        {mcpServers.length === 0 && (
          <p className="text-[10px] t-faint italic px-1">
            No MCP servers connected. Set MCP_CLIENT_ENABLED=true and MCP_SERVERS in .env to add external tool servers.
          </p>
        )}
      </div>
    </Section>
  );
}

// ── MCP Server Block ─────────────────────────────────

function McpServerBlock({ server }: { server: McpServerGroup }) {
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const SHOW_LIMIT = 3;
  const allApproval = server.tools.every((t) => t.approval_required);
  const visibleTools = showAll ? server.tools : server.tools.slice(0, SHOW_LIMIT);

  return (
    <div className="rounded-lg bg-app-secondary px-3 py-2.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 text-left"
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" />
        <span className="text-xs font-medium t-secondary flex-1">
          {server.name}
        </span>
        <span className="text-[10px] t-faint">
          {server.tools.length} tools
        </span>
        {expanded ? (
          <ChevronDown size={12} className="t-faint flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="t-faint flex-shrink-0" />
        )}
      </button>

      {!expanded && (
        <p className="text-[10px] t-faint mt-1 ml-4">
          {allApproval ? "All require approval" : "Mixed approval"} · high risk
        </p>
      )}

      {expanded && (
        <div className="mt-1.5 space-y-0.5">
          {visibleTools.map((tool) => {
            const parsed = parseMcpName(tool.name);
            return (
              <div
                key={tool.name}
                className="flex items-center gap-2 px-2 py-1.5 rounded bg-app border border-app"
              >
                <span className="font-mono text-[11px] t-secondary flex-1 truncate">
                  {parsed?.tool ?? tool.name}
                </span>
                <RiskBadge level={tool.risk_level} />
                {tool.approval_required && (
                  <ShieldCheck size={11} className="text-amber-400 flex-shrink-0" />
                )}
              </div>
            );
          })}
          {server.tools.length > SHOW_LIMIT && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-[10px] text-blue-400 hover:text-blue-300 px-2 pt-1 transition-colors"
            >
              {showAll
                ? "Show less"
                : `+ ${server.tools.length - SHOW_LIMIT} more tools`}
            </button>
          )}
        </div>
      )}
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
