/**
 * ExecutionGraph — Pure CSS/HTML DAG visualization of a run's execution.
 *
 * No external graph library. Renders as a vertical flex column with
 * themed node cards and SVG edge lines. Scrolls naturally with the
 * sidebar. Supports:
 *   - Node types: start, tool, delegate, active, done, reflect
 *   - Edge types: normal (solid), error (dashed red), delegate (dotted purple)
 *   - Edge draw-in animation via stroke-dashoffset
 *   - Click popover with pin mode for node details
 *   - Collapsed child run card for delegate_task nodes
 *   - Fade-in animation for new nodes
 */

import { useState, useCallback, useRef, useEffect } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  ShieldOff,
  Ban,
  Users,
  Brain,
  ScanEye,
  MessageSquare,
  Clock,
  Pin,
  PinOff,
  X,
} from "lucide-react";
import { useChildRunSSE } from "../hooks/useChildRunSSE";
import type { Run, Observation } from "../api/types";

// ── Types ────────────────────────────────────────────

type NodeStatus = "success" | "error" | "denied" | "rejected" | "running" | "pending";
type NodeKind = "start" | "tool" | "delegate" | "active" | "done" | "reflect";

interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  sublabel: string;
  status: NodeStatus;
  toolName?: string;
  riskLevel?: string;
  observation?: Observation;
  childRunId?: string;
}

interface GraphEdge {
  id: string;
  type: "normal" | "error" | "delegate";
}

// ── Build graph data from run ────────────────────────

function buildGraphData(run: Run): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  // Start node
  nodes.push({
    id: "start",
    kind: "start",
    label: run.user_message.length > 50
      ? run.user_message.slice(0, 50) + "…"
      : run.user_message,
    sublabel: "start",
    status: "success",
  });

  for (let i = 0; i < run.observations.length; i++) {
    const obs = run.observations[i];
    const isFinalAnswer = !obs.tool;
    const isDelegate = obs.tool === "delegate_task";
    const resultStatus = obs.result?.status;
    const childRunId =
      isDelegate && obs.result?.output?.child_run_id
        ? (obs.result.output.child_run_id as string)
        : undefined;

    const status: NodeStatus = isFinalAnswer
      ? "success"
      : resultStatus === "success" ? "success"
      : resultStatus === "error" ? "error"
      : resultStatus === "denied" ? "denied"
      : resultStatus === "rejected" ? "rejected"
      : obs.result ? "error"
      : "running";

    const kind: NodeKind = isFinalAnswer ? "done"
      : isDelegate ? "delegate"
      : "tool";

    const label = obs.user_announcement
      ? obs.user_announcement.length > 50
        ? obs.user_announcement.slice(0, 50) + "…"
        : obs.user_announcement
      : isFinalAnswer ? "Answer"
      : obs.tool || "Unknown";

    nodes.push({
      id: `obs_${i}`,
      kind,
      label,
      sublabel: isFinalAnswer ? "complete" : obs.tool || "",
      status,
      toolName: obs.tool || undefined,
      riskLevel: obs.result?.risk_level,
      observation: obs,
      childRunId,
    });

    // Edge type
    const edgeType: GraphEdge["type"] =
      resultStatus === "error" ? "error" : isDelegate ? "delegate" : "normal";
    edges.push({ id: `e_${i}`, type: edgeType });
  }

  // Active node if still running
  const isActive = run.status === "reacting" || run.status === "planning";
  const isReflecting = run.status === "reflecting";
  if (isActive || isReflecting) {
    nodes.push({
      id: "active",
      kind: isReflecting ? "reflect" : "active",
      label: isReflecting ? "Reviewing…" : "Thinking…",
      sublabel: isReflecting ? "self-reflection" : "planning",
      status: "running",
    });
    edges.push({ id: "e_active", type: "normal" });
  }

  return { nodes, edges };
}

// ── Edge SVG ─────────────────────────────────────────

function EdgeLine({ edge, index }: { edge: GraphEdge; index: number }) {
  const color =
    edge.type === "error" ? "#ef4444"
    : edge.type === "delegate" ? "#7c3aed"
    : "var(--text-faint)";

  const dashArray =
    edge.type === "error" ? "6 4"
    : edge.type === "delegate" ? "3 3"
    : "none";

  return (
    <div className="flex justify-center" style={{ height: 32 }}>
      <svg width="2" height="32" className="overflow-visible">
        <line
          x1="1" y1="0" x2="1" y2="32"
          stroke={color}
          strokeWidth={edge.type === "error" ? 1.5 : 1}
          strokeDasharray={dashArray}
          strokeLinecap="round"
          style={{
            strokeDashoffset: 0,
            animation: `edgeDrawIn 0.4s ease-out ${index * 0.1}s both`,
          }}
        />
        {/* Arrow head */}
        <polygon
          points="-3,26 1,32 5,26"
          fill={color}
          style={{ opacity: 0.6 }}
        />
      </svg>
    </div>
  );
}

// ── Node card ────────────────────────────────────────

function NodeCard({
  node,
  index,
  isSelected,
  onClick,
}: {
  node: GraphNode;
  index: number;
  isSelected: boolean;
  onClick: () => void;
}) {
  const borderClass = getBorderClass(node.kind, node.status);
  const bg = getBgColor(node.kind, node.status);

  const riskBadge =
    node.riskLevel === "medium" ? (
      <span className="badge-medium text-[8px] px-1 py-0 rounded leading-none">med</span>
    ) : node.riskLevel === "high" ? (
      <span className="badge-high text-[8px] px-1 py-0 rounded leading-none">high</span>
    ) : null;

  const sublabel =
    node.kind === "tool" && node.toolName && node.toolName !== node.label
      ? node.toolName
      : node.kind === "start" ? "start"
      : node.kind === "done" ? "complete"
      : node.kind === "active" ? "planning next step…"
      : node.kind === "reflect" ? "checking quality…"
      : node.kind === "delegate" ? "sub-agent"
      : null;

  return (
    <button
      onClick={onClick}
      className={`
        w-full rounded-md px-3 py-2 cursor-pointer select-none relative text-left
        transition-all duration-200 ${borderClass}
        ${isSelected ? "ring-1 ring-blue-500/50" : ""}
      `}
      style={{
        background: bg,
        animationDelay: `${index * 0.08}s`,
      }}
    >
      {/* Delegate double border */}
      {node.kind === "delegate" && (
        <div className="absolute inset-[3px] rounded border border-purple-500/20 pointer-events-none" />
      )}

      <div className="flex items-center gap-1.5 min-w-0">
        <StatusIcon kind={node.kind} status={node.status} />
        <span className="t-primary truncate font-medium text-[11px] flex-1 leading-tight">
          {node.label}
        </span>
        {riskBadge}
      </div>

      {sublabel && (
        <div className={`mt-0.5 text-[9px] truncate ${
          node.kind === "reflect" ? "text-violet-400/70"
          : node.kind === "delegate" ? "text-purple-400/70"
          : "t-faint"
        } ${node.kind === "tool" ? "font-mono" : ""}`}>
          {node.kind === "delegate" && <Users size={8} className="inline mr-0.5" />}
          {sublabel}
        </div>
      )}
    </button>
  );
}

// ── Node popover ─────────────────────────────────────

function NodePopover({
  node,
  onClose,
  pinned,
  onTogglePin,
}: {
  node: GraphNode;
  onClose: () => void;
  pinned: boolean;
  onTogglePin: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const obs = node.observation;

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // For start node without observation
  if (!obs && node.kind === "start") {
    return (
      <div ref={ref} className="mt-1 animate-fade-in">
        <div className="rounded-lg border border-app bg-step-row p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium t-primary">User request</span>
            <PopoverActions pinned={pinned} onTogglePin={onTogglePin} onClose={onClose} />
          </div>
          <p className="text-[11px] t-secondary leading-relaxed">{node.label}</p>
        </div>
      </div>
    );
  }

  if (!obs) return null;

  const status = obs.result?.status;
  const duration =
    obs.result?.started_at && obs.result?.finished_at
      ? Math.round(
          new Date(obs.result.finished_at).getTime() -
          new Date(obs.result.started_at).getTime(),
        )
      : null;

  return (
    <div ref={ref} className="mt-1 animate-fade-in">
      <div className="rounded-lg border border-app bg-step-row overflow-hidden">
        {/* Header */}
        <div className="px-3 py-1.5 border-b border-app flex items-center gap-2">
          <StatusBadge status={status} />
          <span className="text-xs font-medium t-primary truncate flex-1">
            {obs.tool || "Answer"}
          </span>
          {duration !== null && (
            <span className="text-[10px] t-faint flex items-center gap-0.5">
              <Clock size={9} /> {duration}ms
            </span>
          )}
          <PopoverActions pinned={pinned} onTogglePin={onTogglePin} onClose={onClose} />
        </div>

        {/* Body */}
        <div className="p-3 space-y-2 max-h-[200px] overflow-y-auto">
          {obs.user_announcement && (
            <div>
              <Label>Announcement</Label>
              <p className="text-[11px] t-secondary leading-relaxed">{obs.user_announcement}</p>
            </div>
          )}
          {obs.reasoning && (
            <div>
              <Label>Reasoning</Label>
              <p className="text-[11px] t-muted leading-relaxed italic">{obs.reasoning}</p>
            </div>
          )}
          {obs.args && Object.keys(obs.args).length > 0 && (
            <div>
              <Label>Arguments</Label>
              <pre className="text-[10px] font-mono bg-app-code t-code rounded px-2 py-1.5 whitespace-pre-wrap max-h-[60px] overflow-y-auto">
                {JSON.stringify(obs.args, null, 2)}
              </pre>
            </div>
          )}
          {obs.result && (
            <div>
              <Label>Result</Label>
              <pre className={`text-[10px] font-mono bg-app-code rounded px-2 py-1.5 whitespace-pre-wrap max-h-[60px] overflow-y-auto ${
                status === "success" ? "text-emerald-500" : "text-red-400"
              }`}>
                {JSON.stringify(
                  status === "success" ? obs.result.output : obs.result.error,
                  null, 2,
                )}
              </pre>
            </div>
          )}
        </div>

        {pinned && (
          <div className="px-3 py-1 border-t border-app text-[9px] t-faint text-center">
            Pinned — click other nodes to compare
          </div>
        )}
      </div>
    </div>
  );
}

// ── Child run card ───────────────────────────────────

function ChildRunCardInline({ childRunId }: { childRunId: string }) {
  const { childRun } = useChildRunSSE(childRunId);
  const [expanded, setExpanded] = useState(true);

  if (!childRun) {
    return (
      <div className="mt-1 rounded-lg border border-purple-500/30 bg-purple-600/5 p-2.5 animate-fade-in">
        <div className="flex items-center gap-2 text-xs text-purple-400">
          <Users size={12} />
          <span>Sub-agent: {childRunId.slice(0, 8)}…</span>
          <Loader2 size={12} className="animate-spin" />
        </div>
      </div>
    );
  }

  const isActive = childRun.status === "reacting" || childRun.status === "planning";
  const isDone = ["completed", "failed", "cancelled"].includes(childRun.status);
  const statusColor =
    childRun.status === "completed" ? "text-emerald-500"
    : childRun.status === "failed" ? "text-red-500"
    : "text-purple-400";

  return (
    <div className="mt-1 rounded-lg border border-purple-500/30 bg-purple-600/5 overflow-hidden animate-fade-in">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-left hover:bg-purple-600/10 transition-colors"
      >
        <Users size={11} className="text-purple-400 flex-shrink-0" />
        <span className="font-medium t-secondary">Sub-agent</span>
        <span className="t-faint">·</span>
        <span className={`font-medium ${statusColor}`}>{childRun.status}</span>
        <span className="t-faint">·</span>
        <span className="t-muted">{childRun.iterations}/{childRun.max_iterations}</span>
        {isActive && <Loader2 size={10} className="animate-spin text-purple-400" />}
      </button>

      {expanded && (
        <div className="px-2.5 pb-2 border-t border-purple-500/20">
          <div className="text-[10px] t-muted py-1.5 italic">Task: {childRun.user_message}</div>
          <div className="space-y-0.5">
            {childRun.observations.map((obs, i) => {
              const isFinal = !obs.tool;
              const st = obs.result?.status;
              return (
                <div key={obs.step_id + "-" + obs.iteration} className="flex items-center gap-1.5 text-[10px] py-0.5">
                  {isFinal || st === "success"
                    ? <CheckCircle2 size={9} className="text-emerald-500 flex-shrink-0" />
                    : st === "error"
                    ? <XCircle size={9} className="text-red-500 flex-shrink-0" />
                    : <Loader2 size={9} className="t-faint flex-shrink-0" />
                  }
                  <span className="t-faint font-mono w-3">{i + 1}</span>
                  <span className="t-secondary truncate flex-1">
                    {obs.user_announcement || (isFinal ? "Done" : obs.tool)}
                  </span>
                </div>
              );
            })}
          </div>
          {isDone && childRun.final_response && (
            <div className="text-[10px] t-secondary bg-app-code rounded px-2 py-1 mt-1.5 max-h-12 overflow-y-auto">
              {childRun.final_response.slice(0, 300)}
              {childRun.final_response.length > 300 && "…"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────

interface ExecutionGraphProps {
  run: Run;
}

export default function ExecutionGraph({ run }: ExecutionGraphProps) {
  const { nodes, edges } = buildGraphData(run);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pinned, setPinned] = useState(false);
  const nodeRefs = useRef<Map<string, HTMLElement>>(new Map());

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null;

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedId((prev) => {
      if (prev === nodeId && !pinned) return null;
      return nodeId;
    });
  }, [pinned]);

  const handleClose = useCallback(() => {
    setSelectedId(null);
    setPinned(false);
  }, []);

  const handleTogglePin = useCallback(() => {
    setPinned((p) => !p);
  }, []);

  // Click outside to dismiss (unless pinned)
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (pinned) return;
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setSelectedId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [pinned]);

  return (
    <div ref={containerRef} className="flex flex-col items-center gap-0 p-4 pb-8">
      {nodes.map((node, i) => (
        <div key={node.id} className="w-full max-w-[240px] flex flex-col items-center">
          {/* Edge line (before every node except the first) */}
          {i > 0 && edges[i - 1] && (
            <EdgeLine edge={edges[i - 1]} index={i} />
          )}

          {/* Node card */}
          <div
            ref={(el) => { if (el) nodeRefs.current.set(node.id, el); }}
            className="w-full animate-fade-in"
            style={{ animationDelay: `${i * 0.08}s` }}
          >
            <NodeCard
              node={node}
              index={i}
              isSelected={selectedId === node.id}
              onClick={() => handleNodeClick(node.id)}
            />
          </div>

          {/* Popover (below the selected node) */}
          {selectedId === node.id && selectedNode && (
            <div className="w-full">
              <NodePopover
                node={selectedNode}
                onClose={handleClose}
                pinned={pinned}
                onTogglePin={handleTogglePin}
              />

              {/* Child run card for delegates */}
              {selectedNode.childRunId && (
                <ChildRunCardInline childRunId={selectedNode.childRunId} />
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────

function StatusIcon({ kind, status }: { kind: NodeKind; status: NodeStatus }) {
  const s = 12;
  if (kind === "start") return <MessageSquare size={s} className="text-blue-400 flex-shrink-0" />;
  if (kind === "done") return <CheckCircle2 size={s} className="text-emerald-500 flex-shrink-0" />;
  if (kind === "active") return <Loader2 size={s} className="text-blue-400 animate-spin flex-shrink-0" />;
  if (kind === "reflect") return <ScanEye size={s} className="text-violet-400 animate-spin flex-shrink-0" />;
  if (kind === "delegate") return <Users size={s} className="text-purple-400 flex-shrink-0" />;
  switch (status) {
    case "success": return <CheckCircle2 size={s} className="text-emerald-500 flex-shrink-0" />;
    case "error": return <XCircle size={s} className="text-red-500 flex-shrink-0" />;
    case "denied": return <ShieldOff size={s} className="text-amber-500 flex-shrink-0" />;
    case "rejected": return <Ban size={s} className="text-red-500 flex-shrink-0" />;
    case "running": return <Loader2 size={s} className="text-blue-400 animate-spin flex-shrink-0" />;
    default: return <Brain size={s} className="t-faint flex-shrink-0" />;
  }
}

function getBorderClass(kind: NodeKind, status: NodeStatus): string {
  switch (kind) {
    case "start": return "border border-blue-500/30 hover:border-blue-500/50";
    case "done": return "border border-emerald-500/30 hover:border-emerald-500/50";
    case "active": return "border border-blue-500/40 animate-pulse";
    case "reflect": return "border border-violet-500/40 animate-pulse";
    case "delegate": return "border-2 border-purple-500/40 hover:border-purple-500/60";
    case "tool":
      switch (status) {
        case "success": return "border border-emerald-500/30 hover:border-emerald-500/50";
        case "error": return "border border-red-500/30 hover:border-red-500/50";
        case "denied": return "border border-amber-500/30 hover:border-amber-500/50";
        case "rejected": return "border border-red-500/30 hover:border-red-500/50";
        case "running": return "border border-blue-500/30";
        default: return "border border-app";
      }
    default: return "border border-app";
  }
}

function getBgColor(kind: NodeKind, status: NodeStatus): string {
  switch (kind) {
    case "start": return "rgba(37, 99, 235, 0.1)";
    case "done": return "rgba(16, 185, 129, 0.1)";
    case "active": return "rgba(37, 99, 235, 0.06)";
    case "reflect": return "rgba(139, 92, 246, 0.06)";
    case "delegate": return "rgba(139, 92, 246, 0.06)";
    case "tool":
      if (status === "error" || status === "rejected") return "rgba(239, 68, 68, 0.06)";
      if (status === "denied") return "rgba(245, 158, 11, 0.06)";
      if (status === "running") return "rgba(37, 99, 235, 0.06)";
      return "transparent";
    default: return "transparent";
  }
}

function StatusBadge({ status }: { status?: string }) {
  switch (status) {
    case "success":
      return <span className="flex items-center gap-0.5 text-[10px] text-emerald-500"><CheckCircle2 size={10} /> success</span>;
    case "error":
      return <span className="flex items-center gap-0.5 text-[10px] text-red-500"><XCircle size={10} /> error</span>;
    case "denied":
      return <span className="flex items-center gap-0.5 text-[10px] text-amber-500"><ShieldOff size={10} /> denied</span>;
    case "rejected":
      return <span className="flex items-center gap-0.5 text-[10px] text-red-500"><Ban size={10} /> rejected</span>;
    default:
      return <span className="flex items-center gap-0.5 text-[10px] t-faint"><Clock size={10} /> pending</span>;
  }
}

function PopoverActions({ pinned, onTogglePin, onClose }: { pinned: boolean; onTogglePin: () => void; onClose: () => void }) {
  return (
    <div className="flex items-center gap-0.5 ml-1 flex-shrink-0">
      <button
        onClick={(e) => { e.stopPropagation(); onTogglePin(); }}
        className={`p-0.5 rounded transition-colors ${pinned ? "text-blue-400 hover:text-blue-300" : "t-faint hover:t-muted"}`}
        title={pinned ? "Unpin" : "Pin (stay open)"}
      >
        {pinned ? <PinOff size={10} /> : <Pin size={10} />}
      </button>
      <button
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        className="p-0.5 rounded t-faint hover:text-red-400 transition-colors"
        title="Close"
      >
        <X size={10} />
      </button>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="block text-[9px] uppercase tracking-wider t-faint mb-0.5">{children}</span>;
}
