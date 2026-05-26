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
    return <MessageSquare size={11} className="text-blue-400 flex-shrink-0" />;
  }
  if (kind === "done") {
    return <CheckCircle2 size={11} className="text-emerald-500 flex-shrink-0" />;
  }
  if (kind === "active") {
    return <Loader2 size={11} className="text-blue-400 animate-spin flex-shrink-0" />;
  }
  if (kind === "reflect") {
    return <ScanEye size={11} className="text-violet-400 animate-spin flex-shrink-0" />;
  }
  if (kind === "delegate") {
    return <Users size={11} className="text-purple-400 flex-shrink-0" />;
  }

  switch (status) {
    case "success":
      return <CheckCircle2 size={11} className="text-emerald-500 flex-shrink-0" />;
    case "error":
      return <XCircle size={11} className="text-red-500 flex-shrink-0" />;
    case "denied":
      return <ShieldOff size={11} className="text-amber-500 flex-shrink-0" />;
    case "rejected":
      return <Ban size={11} className="text-red-500 flex-shrink-0" />;
    case "running":
      return <Loader2 size={11} className="text-blue-400 animate-spin flex-shrink-0" />;
    default:
      return <Brain size={11} className="t-faint flex-shrink-0" />;
  }
}

// ── Border / style helpers ───────────────────────────

function getNodeStyle(kind: GraphNodeKind, status: GraphNodeStatus): {
  className: string;
  bg: string;
} {
  const base = "graph-node rounded-md px-2.5 py-1.5 cursor-pointer select-none";

  switch (kind) {
    case "start":
      return {
        className: `${base} border border-blue-500/30 hover:border-blue-500/50`,
        bg: "rgba(37, 99, 235, 0.1)",
      };
    case "done":
      return {
        className: `${base} border border-emerald-500/30 hover:border-emerald-500/50`,
        bg: "rgba(16, 185, 129, 0.1)",
      };
    case "active":
      return {
        className: `${base} border border-blue-500/40 animate-pulse`,
        bg: "rgba(37, 99, 235, 0.06)",
      };
    case "reflect":
      return {
        className: `${base} border border-violet-500/40 animate-pulse`,
        bg: "rgba(139, 92, 246, 0.06)",
      };
    case "delegate":
      return {
        className: `${base} border-2 border-purple-500/40 hover:border-purple-500/60`,
        bg: "rgba(139, 92, 246, 0.06)",
      };
    case "tool":
      switch (status) {
        case "success":
          return {
            className: `${base} border border-emerald-500/30 hover:border-emerald-500/50`,
            bg: "transparent",
          };
        case "error":
          return {
            className: `${base} border border-red-500/30 hover:border-red-500/50`,
            bg: "rgba(239, 68, 68, 0.06)",
          };
        case "denied":
          return {
            className: `${base} border border-amber-500/30 hover:border-amber-500/50`,
            bg: "rgba(245, 158, 11, 0.06)",
          };
        case "rejected":
          return {
            className: `${base} border border-red-500/30 hover:border-red-500/50`,
            bg: "rgba(239, 68, 68, 0.06)",
          };
        case "running":
          return {
            className: `${base} border border-blue-500/30`,
            bg: "rgba(37, 99, 235, 0.06)",
          };
        default:
          return { className: `${base} border border-app`, bg: "transparent" };
      }
    default:
      return { className: `${base} border border-app`, bg: "transparent" };
  }
}

// ── Node component ───────────────────────────────────

function GraphNode({ data }: NodeProps) {
  const { kind, label, sublabel, status, toolName, riskLevel } = data as GraphNodeData;
  const { className, bg } = getNodeStyle(kind, status);

  const riskBadge =
    riskLevel === "medium" ? (
      <span className="badge-medium text-[8px] px-1 py-0 rounded leading-none">med</span>
    ) : riskLevel === "high" ? (
      <span className="badge-high text-[8px] px-1 py-0 rounded leading-none">high</span>
    ) : null;

  return (
    <>
      {/* Target handle (top) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-1.5 !h-1.5 !rounded-full !border-0 !bg-transparent"
      />

      <div className={className} style={{ background: bg, width: 200, height: 46, overflow: "hidden" }}>
        {/* Delegate inner border */}
        {kind === "delegate" && (
          <div className="absolute inset-[3px] rounded border border-purple-500/20 pointer-events-none" />
        )}

        <div className="flex items-center gap-1.5 min-w-0">
          <StatusIcon status={status} kind={kind} />
          <span className="t-primary truncate font-medium text-[10px] flex-1 leading-tight">
            {label}
          </span>
          {riskBadge}
        </div>

        {/* Sublabel: tool name when announcement replaced it */}
        {sublabel && kind === "tool" && toolName && toolName !== label && (
          <div className="mt-0.5 text-[8px] font-mono t-faint truncate">
            {toolName}
          </div>
        )}
        {kind === "start" && (
          <div className="mt-0.5 text-[8px] t-faint">start</div>
        )}
        {kind === "done" && (
          <div className="mt-0.5 text-[8px] t-faint">complete</div>
        )}
        {kind === "active" && (
          <div className="mt-0.5 text-[8px] t-faint">planning next step…</div>
        )}
        {kind === "reflect" && (
          <div className="mt-0.5 text-[8px] text-violet-400/70">checking quality…</div>
        )}
        {kind === "delegate" && (
          <div className="mt-0.5 text-[8px] text-purple-400/70 flex items-center gap-0.5">
            <Users size={7} /> sub-agent
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
