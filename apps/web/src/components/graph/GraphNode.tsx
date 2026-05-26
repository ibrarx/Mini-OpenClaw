/**
 * GraphNode — Custom React Flow node component for the execution graph.
 *
 * Renders themed nodes matching Mini-OpenClaw's CSS variable system.
 * Node kinds: start, tool, delegate, active, done, reflect.
 * Supports status badges, risk levels, pulse animation for active nodes,
 * and double-border for delegate nodes.
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

// ── Status icon ──────────────────────────────────────

function StatusIcon({ status, kind }: { status: GraphNodeStatus; kind: GraphNodeKind }) {
  if (kind === "start") {
    return <MessageSquare size={12} className="text-blue-400 flex-shrink-0" />;
  }
  if (kind === "done") {
    return <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />;
  }
  if (kind === "active") {
    return <Loader2 size={12} className="text-blue-400 animate-spin flex-shrink-0" />;
  }
  if (kind === "reflect") {
    return <ScanEye size={12} className="text-violet-400 animate-spin flex-shrink-0" />;
  }
  if (kind === "delegate") {
    return <Users size={12} className="text-purple-400 flex-shrink-0" />;
  }

  switch (status) {
    case "success":
      return <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />;
    case "error":
      return <XCircle size={12} className="text-red-500 flex-shrink-0" />;
    case "denied":
      return <ShieldOff size={12} className="text-amber-500 flex-shrink-0" />;
    case "rejected":
      return <Ban size={12} className="text-red-500 flex-shrink-0" />;
    case "running":
      return <Loader2 size={12} className="text-blue-400 animate-spin flex-shrink-0" />;
    default:
      return <Brain size={12} className="t-faint flex-shrink-0" />;
  }
}

// ── Border / style helpers ───────────────────────────

function getNodeClasses(kind: GraphNodeKind, status: GraphNodeStatus): string {
  const base =
    "rounded-lg px-3 py-2 text-xs transition-all duration-200 cursor-pointer select-none min-w-[140px] max-w-[180px]";

  switch (kind) {
    case "start":
      return `${base} bg-blue-600/10 border border-blue-500/30 hover:border-blue-500/50`;
    case "done":
      return `${base} bg-emerald-600/10 border border-emerald-500/30 hover:border-emerald-500/50`;
    case "active":
      return `${base} bg-blue-600/5 border border-blue-500/40 animate-pulse`;
    case "reflect":
      return `${base} bg-violet-600/5 border border-violet-500/40 animate-pulse`;
    case "delegate":
      return `${base} bg-purple-600/5 border-2 border-purple-500/40 hover:border-purple-500/60`;
    case "tool":
      switch (status) {
        case "success":
          return `${base} border border-emerald-500/30 hover:border-emerald-500/50`;
        case "error":
          return `${base} border border-red-500/30 hover:border-red-500/50 bg-red-600/5`;
        case "denied":
          return `${base} border border-amber-500/30 hover:border-amber-500/50 bg-amber-600/5`;
        case "rejected":
          return `${base} border border-red-500/30 hover:border-red-500/50 bg-red-600/5`;
        case "running":
          return `${base} border border-blue-500/30 bg-blue-600/5`;
        default:
          return `${base} border border-app`;
      }
    default:
      return `${base} border border-app`;
  }
}

// ── Node component ───────────────────────────────────

function GraphNode({ data }: NodeProps) {
  const { kind, label, sublabel, status, toolName, riskLevel } = data as GraphNodeData;

  const riskBadge =
    riskLevel === "medium" ? (
      <span className="badge-medium text-[9px] px-1 py-0 rounded">med</span>
    ) : riskLevel === "high" ? (
      <span className="badge-high text-[9px] px-1 py-0 rounded">high</span>
    ) : null;

  return (
    <>
      {/* Target handle (top) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-1.5 !h-1.5 !rounded-full !border-0 !bg-transparent"
      />

      <div className={getNodeClasses(kind, status)} style={{ background: undefined }}>
        {/* Delegate inner border */}
        {kind === "delegate" && (
          <div className="absolute inset-[3px] rounded-md border border-purple-500/20 pointer-events-none" />
        )}

        <div className="flex items-center gap-1.5">
          <StatusIcon status={status} kind={kind} />
          <span className="t-primary truncate font-medium text-[11px] flex-1 leading-tight">
            {label}
          </span>
          {riskBadge}
        </div>

        {/* Sublabel: tool name or status */}
        {sublabel && kind === "tool" && toolName && toolName !== label && (
          <div className="mt-0.5 text-[9px] font-mono t-faint truncate">
            {toolName}
          </div>
        )}
        {kind === "start" && (
          <div className="mt-0.5 text-[9px] t-faint">start</div>
        )}
        {kind === "active" && (
          <div className="mt-0.5 text-[9px] t-faint">planning next step…</div>
        )}
        {kind === "reflect" && (
          <div className="mt-0.5 text-[9px] text-violet-400/70">checking quality…</div>
        )}
        {kind === "delegate" && (
          <div className="mt-0.5 text-[9px] text-purple-400/70 flex items-center gap-0.5">
            <Users size={8} /> sub-agent
          </div>
        )}
      </div>

      {/* Source handle (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-1.5 !h-1.5 !rounded-full !border-0 !bg-transparent"
      />
    </>
  );
}

export default memo(GraphNode);
