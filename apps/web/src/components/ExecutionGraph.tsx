/**
 * ExecutionGraph — Real-time DAG visualization of a run's execution.
 *
 * Uses @xyflow/react for pan/zoom/viewport with fully custom node and edge
 * rendering that matches the Mini-OpenClaw theme (CSS variables, thin borders,
 * compact text). Converts run observations into a directed acyclic graph.
 *
 * Layout: top-to-bottom linear flow; delegation branches right.
 * Nodes: custom themed components (start, tool, delegate, active, done).
 * Edges: animated stroke-dashoffset draw-in, dashed for errors/delegation.
 * Detail: click-popover shows tool args, result, reasoning.
 */

import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  Position,
  MarkerType,
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Run, Observation } from "../api/types";
import GraphNodeComponent from "./graph/GraphNode";
import AnimatedEdge from "./graph/AnimatedEdge";
import NodePopover from "./graph/NodePopover";
import ChildRunCard from "./graph/ChildRunCard";

// ── Layout constants ─────────────────────────────────
// React Flow needs explicit width/height on nodes for proper fitView.
// The actual rendered node is 200px wide × ~48px tall (padding + 2 lines).
const NODE_W = 200;
const NODE_H = 48;
const GAP_Y = 40;   // gap between bottom of one node and top of next
const START_X = 0;
const START_Y = 0;

// ── Types ────────────────────────────────────────────

export type GraphNodeStatus =
  | "success"
  | "error"
  | "denied"
  | "rejected"
  | "running"
  | "pending";

export type GraphNodeKind =
  | "start"
  | "tool"
  | "delegate"
  | "active"
  | "done"
  | "reflect";

export interface GraphNodeData {
  kind: GraphNodeKind;
  label: string;
  sublabel: string;
  status: GraphNodeStatus;
  toolName?: string;
  riskLevel?: string;
  observation?: Observation;
  childRunId?: string;
  [key: string]: unknown;
}

// Register custom node and edge types (stable reference)
const nodeTypes: NodeTypes = { graphNode: GraphNodeComponent };
const edgeTypes: EdgeTypes = { animated: AnimatedEdge };

// ── Graph builder ────────────────────────────────────

function buildGraph(run: Run): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const nodes: Node<GraphNodeData>[] = [];
  const edges: Edge[] = [];

  // Start node
  nodes.push({
    id: "start",
    type: "graphNode",
    position: { x: START_X, y: START_Y },
    width: NODE_W,
    height: NODE_H,
    measured: { width: NODE_W, height: NODE_H },
    style: { width: NODE_W, height: NODE_H },
    data: {
      kind: "start",
      label: run.user_message.length > 40
        ? run.user_message.slice(0, 40) + "…"
        : run.user_message,
      sublabel: "User request",
      status: "success",
    },
    sourcePosition: Position.Bottom,
    targetPosition: Position.Top,
  });

  let prevId = "start";
  let mainY = START_Y + NODE_H + GAP_Y;

  for (let i = 0; i < run.observations.length; i++) {
    const obs = run.observations[i];
    const nodeId = `obs_${i}`;
    const isFinalAnswer = !obs.tool;
    const isDelegate = obs.tool === "delegate_task";
    const status = obs.result?.status as GraphNodeStatus | undefined;
    const childRunId =
      isDelegate && obs.result?.output?.child_run_id
        ? (obs.result.output.child_run_id as string)
        : undefined;

    const resolvedStatus: GraphNodeStatus = isFinalAnswer
      ? "success"
      : status === "success"
        ? "success"
        : status === "error"
          ? "error"
          : status === "denied"
            ? "denied"
            : status === "rejected"
              ? "rejected"
              : obs.result
                ? "error"
                : "running";

    const kind: GraphNodeKind = isFinalAnswer
      ? "done"
      : isDelegate
        ? "delegate"
        : "tool";

    const label = obs.user_announcement
      ? obs.user_announcement.length > 35
        ? obs.user_announcement.slice(0, 35) + "…"
        : obs.user_announcement
      : isFinalAnswer
        ? "Answer"
        : obs.tool || "Unknown";

    nodes.push({
      id: nodeId,
      type: "graphNode",
      position: { x: START_X, y: mainY },
      width: NODE_W,
      height: NODE_H,
      measured: { width: NODE_W, height: NODE_H },
      style: { width: NODE_W, height: NODE_H },
      data: {
        kind,
        label,
        sublabel: isFinalAnswer ? "final" : obs.tool || "",
        status: resolvedStatus,
        toolName: obs.tool || undefined,
        riskLevel: obs.result?.risk_level,
        observation: obs,
        childRunId,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    });

    // Edge from previous node
    const edgeType =
      status === "error" ? "error" : isDelegate ? "delegate" : "normal";

    edges.push({
      id: `e_${prevId}_${nodeId}`,
      source: prevId,
      target: nodeId,
      type: "animated",
      animated: false,
      data: { edgeType },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 12,
        height: 12,
        color:
          edgeType === "error"
            ? "#ef4444"
            : edgeType === "delegate"
              ? "#7c3aed"
              : "var(--text-faint)",
      },
    });

    prevId = nodeId;
    mainY += NODE_H + GAP_Y;
  }

  // If the run is still active, add an "active" thinking node
  const isActive = run.status === "reacting" || run.status === "planning";
  const isReflecting = run.status === "reflecting";

  if (isActive || isReflecting) {
    const activeId = "active_node";
    nodes.push({
      id: activeId,
      type: "graphNode",
      position: { x: START_X, y: mainY },
      width: NODE_W,
      height: NODE_H,
      measured: { width: NODE_W, height: NODE_H },
      style: { width: NODE_W, height: NODE_H },
      data: {
        kind: isReflecting ? "reflect" : "active",
        label: isReflecting ? "Reviewing…" : "Thinking…",
        sublabel: isReflecting ? "self-reflection" : "planning",
        status: "running",
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    });

    edges.push({
      id: `e_${prevId}_${activeId}`,
      source: prevId,
      target: activeId,
      type: "animated",
      animated: false,
      data: { edgeType: "normal" },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 12,
        height: 12,
        color: "var(--text-faint)",
      },
    });
  }

  return { nodes, edges };
}

// ── Viewport auto-fit ────────────────────────────────

function AutoFit({ nodeCount }: { nodeCount: number }) {
  const { fitView } = useReactFlow();
  const prevCount = useRef(nodeCount);
  const initialFit = useRef(false);

  // Fit on initial render
  useEffect(() => {
    if (!initialFit.current) {
      initialFit.current = true;
      const t = setTimeout(() => fitView({ padding: 0.4, duration: 200 }), 100);
      return () => clearTimeout(t);
    }
  }, [fitView]);

  // Fit when nodes change
  useEffect(() => {
    if (nodeCount !== prevCount.current) {
      prevCount.current = nodeCount;
      const t = setTimeout(() => fitView({ padding: 0.4, duration: 300 }), 50);
      return () => clearTimeout(t);
    }
  }, [nodeCount, fitView]);

  return null;
}

// ── Main component ───────────────────────────────────

interface ExecutionGraphProps {
  run: Run;
}

function ExecutionGraphInner({ run }: ExecutionGraphProps) {
  const { nodes, edges } = useMemo(() => buildGraph(run), [run]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [popoverPos, setPopoverPos] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [pinned, setPinned] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Find the selected node's data for the popover
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId),
    [nodes, selectedNodeId],
  );

  const positionPopover = useCallback(
    (nodeId: string) => {
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const nodeEl = container.querySelector(
        `[data-id="${nodeId}"]`,
      ) as HTMLElement | null;
      if (nodeEl) {
        const nodeRect = nodeEl.getBoundingClientRect();
        setPopoverPos({
          x: nodeRect.right - rect.left + 8,
          y: nodeRect.top - rect.top,
        });
      }
    },
    [],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node<GraphNodeData>) => {
      // If clicking the same node, toggle off (unless pinned)
      if (selectedNodeId === node.id && !pinned) {
        setSelectedNodeId(null);
        setPopoverPos(null);
        return;
      }

      setSelectedNodeId(node.id);
      positionPopover(node.id);
    },
    [selectedNodeId, pinned, positionPopover],
  );

  const onPaneClick = useCallback(() => {
    // Don't dismiss when pinned
    if (pinned) return;
    setSelectedNodeId(null);
    setPopoverPos(null);
  }, [pinned]);

  const handleClosePopover = useCallback(() => {
    setSelectedNodeId(null);
    setPopoverPos(null);
    setPinned(false);
  }, []);

  const handleTogglePin = useCallback(() => {
    setPinned((p) => !p);
  }, []);

  // Check if the selected node is a delegate with child run
  const childRunId = selectedNode?.data?.childRunId;

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        fitView
        fitViewOptions={{ padding: 0.4, minZoom: 0.5, maxZoom: 1.5 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnScroll
        zoomOnScroll
        defaultEdgeOptions={{ type: "animated" }}
        className="execution-graph"
      >
        <Background gap={20} size={0.5} color="var(--text-faint)" style={{ opacity: 0.1 }} />
        <Controls
          showInteractive={false}
          showFitView={true}
          showZoom={true}
          position="bottom-right"
          style={{
            borderRadius: "6px",
            border: "0.5px solid var(--border-primary)",
            overflow: "hidden",
          }}
        />
        <AutoFit nodeCount={nodes.length} />
      </ReactFlow>

      {/* Click popover */}
      {selectedNode && popoverPos && (
        <NodePopover
          node={selectedNode}
          position={popoverPos}
          onClose={handleClosePopover}
          pinned={pinned}
          onTogglePin={handleTogglePin}
        />
      )}

      {/* Expanded child run card for delegates */}
      {childRunId && selectedNodeId && (
        <div
          className="absolute bottom-2 left-2 right-2 z-20 max-h-[40%] overflow-y-auto"
          style={{ pointerEvents: "auto" }}
        >
          <ChildRunCard childRunId={childRunId} />
        </div>
      )}
    </div>
  );
}

export default function ExecutionGraph({ run }: ExecutionGraphProps) {
  return (
    <ReactFlowProvider>
      <ExecutionGraphInner run={run} />
    </ReactFlowProvider>
  );
}
