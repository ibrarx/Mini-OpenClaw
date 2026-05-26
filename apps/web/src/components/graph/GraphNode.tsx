/**
 * GraphNode — Custom React Flow node component for the execution graph.
 *
 * IMPORTANT: The outermost element returned by this component IS what
 * React Flow's ResizeObserver measures. We render a single wrapper div
 * with explicit width/height so the measurement is always correct.
 * Handles are positioned absolutely inside it.
 */

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
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
} from "lucide-react";
import type { GraphNodeData, GraphNodeStatus, GraphNodeKind } from "../ExecutionGraph";

function StatusIcon({ status, kind }: { status: GraphNodeStatus; kind: GraphNodeKind }) {
  const size = 11;
  if (kind === "start") return <MessageSquare size={size} className="text-blue-400 flex-shrink-0" />;
  if (kind === "done") return <CheckCircle2 size={size} className="text-emerald-500 flex-shrink-0" />;
  if (kind === "active") return <Loader2 size={size} className="text-blue-400 animate-spin flex-shrink-0" />;
  if (kind === "reflect") return <ScanEye size={size} className="text-violet-400 animate-spin flex-shrink-0" />;
  if (kind === "delegate") return <Users size={size} className="text-purple-400 flex-shrink-0" />;
  switch (status) {
    case "success": return <CheckCircle2 size={size} className="text-emerald-500 flex-shrink-0" />;
    case "error": return <XCircle size={size} className="text-red-500 flex-shrink-0" />;
    case "denied": return <ShieldOff size={size} className="text-amber-500 flex-shrink-0" />;
    case "rejected": return <Ban size={size} className="text-red-500 flex-shrink-0" />;
    case "running": return <Loader2 size={size} className="text-blue-400 animate-spin flex-shrink-0" />;
    default: return <Brain size={size} className="t-faint flex-shrink-0" />;
  }
}

function getBorderClass(kind: GraphNodeKind, status: GraphNodeStatus): string {
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

function getBgColor(kind: GraphNodeKind, status: GraphNodeStatus): string {
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

function getSublabel(kind: GraphNodeKind, toolName?: string, label?: string): string | null {
  switch (kind) {
    case "start": return "start";
    case "done": return "complete";
    case "active": return "planning next step…";
    case "reflect": return "checking quality…";
    case "delegate": return "sub-agent";
    case "tool": return toolName && toolName !== label ? toolName : null;
    default: return null;
  }
}

function GraphNode({ data }: NodeProps) {
  const { kind, label, status, toolName, riskLevel } = data as GraphNodeData;

  const borderClass = getBorderClass(kind, status);
  const bg = getBgColor(kind, status);
  const sublabel = getSublabel(kind, toolName, label);

  const riskBadge =
    riskLevel === "medium" ? (
      <span className="badge-medium text-[8px] px-1 py-0 rounded leading-none">med</span>
    ) : riskLevel === "high" ? (
      <span className="badge-high text-[8px] px-1 py-0 rounded leading-none">high</span>
    ) : null;

  return (
    <div
      className={`rounded-md px-2.5 py-1.5 cursor-pointer select-none relative ${borderClass}`}
      style={{ background: bg, width: 200, minHeight: 36 }}
    >
      {/* Handles — positioned by React Flow via position: absolute */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-1 !h-1 !rounded-full !border-0 !bg-transparent !top-0"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-1 !h-1 !rounded-full !border-0 !bg-transparent !bottom-0"
      />

      {/* Delegate double-border */}
      {kind === "delegate" && (
        <div className="absolute inset-[3px] rounded border border-purple-500/20 pointer-events-none" />
      )}

      {/* Content */}
      <div className="flex items-center gap-1.5 min-w-0">
        <StatusIcon status={status} kind={kind} />
        <span className="t-primary truncate font-medium text-[10px] flex-1 leading-tight">
          {label}
        </span>
        {riskBadge}
      </div>

      {sublabel && (
        <div className={`mt-0.5 text-[8px] truncate ${
          kind === "reflect" ? "text-violet-400/70" :
          kind === "delegate" ? "text-purple-400/70" :
          "t-faint"
        } ${kind === "tool" ? "font-mono" : ""}`}>
          {kind === "delegate" && <Users size={7} className="inline mr-0.5" />}
          {sublabel}
        </div>
      )}
    </div>
  );
}

export default memo(GraphNode);
