/**
 * NodePopover — Floating detail card for a selected graph node.
 *
 * Appears near the clicked node, shows tool args, result, reasoning,
 * and timing. Supports pin mode: when pinned, clicking another node
 * or the pane won't dismiss this popover — only the unpin button or
 * Escape will.
 *
 * Matches Mini-OpenClaw theme with CSS variables.
 */

import { useRef, useEffect } from "react";
import {
  CheckCircle2,
  XCircle,
  Clock,
  ShieldOff,
  Ban,
  Pin,
  PinOff,
  X,
} from "lucide-react";
import type { Node } from "@xyflow/react";
import type { GraphNodeData } from "../ExecutionGraph";

interface NodePopoverProps {
  node: Node<GraphNodeData>;
  position: { x: number; y: number };
  onClose: () => void;
  /** Whether the popover is pinned (immune to pane clicks). */
  pinned?: boolean;
  /** Toggle pin state. */
  onTogglePin?: () => void;
}

export default function NodePopover({
  node,
  position,
  onClose,
  pinned = false,
  onTogglePin,
}: NodePopoverProps) {
  const ref = useRef<HTMLDivElement>(null);
  const data = node.data;
  const obs = data.observation;

  // Clamp position so popover stays inside the container
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const parent = el.parentElement;
    if (!parent) return;

    const pRect = parent.getBoundingClientRect();
    const eRect = el.getBoundingClientRect();

    let x = position.x;
    let y = position.y;

    // Don't overflow right
    if (x + eRect.width > pRect.width) {
      x = position.x - eRect.width - 16;
    }
    // Don't overflow bottom
    if (y + eRect.height > pRect.height) {
      y = pRect.height - eRect.height - 8;
    }
    // Don't go negative
    if (x < 0) x = 8;
    if (y < 0) y = 8;

    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
  }, [position]);

  // Close on Escape (always works, even when pinned)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!obs && data.kind === "start") {
    return (
      <div
        ref={ref}
        className="absolute z-30 animate-fade-in"
        style={{ left: position.x, top: position.y, pointerEvents: "auto" }}
      >
        <div className="rounded-lg border border-app bg-app-secondary shadow-lg p-3 max-w-[240px]">
          <div className="flex items-center justify-between mb-1">
            <div className="text-xs font-medium t-primary">User request</div>
            <PopoverActions
              pinned={pinned}
              onTogglePin={onTogglePin}
              onClose={onClose}
            />
          </div>
          <p className="text-[11px] t-secondary leading-relaxed">
            {node.data.label}
          </p>
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
    <div
      ref={ref}
      className="absolute z-30 animate-fade-in"
      style={{
        left: position.x,
        top: position.y,
        pointerEvents: "auto",
        maxWidth: "260px",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="rounded-lg border border-app bg-app-secondary shadow-lg overflow-hidden">
        {/* Header */}
        <div className="px-3 py-2 border-b border-app flex items-center gap-2">
          <StatusBadge status={status} />
          <span className="text-xs font-medium t-primary truncate flex-1">
            {obs.tool || "Answer"}
          </span>
          {duration !== null && (
            <span className="text-[10px] t-faint flex items-center gap-0.5">
              <Clock size={9} />
              {duration}ms
            </span>
          )}
          <PopoverActions
            pinned={pinned}
            onTogglePin={onTogglePin}
            onClose={onClose}
          />
        </div>

        {/* Body */}
        <div className="p-3 space-y-2 max-h-[260px] overflow-y-auto">
          {/* User announcement */}
          {obs.user_announcement && (
            <div>
              <Label>Announcement</Label>
              <p className="text-[11px] t-secondary leading-relaxed">
                {obs.user_announcement}
              </p>
            </div>
          )}

          {/* Reasoning */}
          {obs.reasoning && (
            <div>
              <Label>Reasoning</Label>
              <p className="text-[11px] t-muted leading-relaxed italic">
                {obs.reasoning}
              </p>
            </div>
          )}

          {/* Args */}
          {obs.args && Object.keys(obs.args).length > 0 && (
            <div>
              <Label>Arguments</Label>
              <pre className="text-[10px] font-mono bg-app-code t-code rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap max-h-[80px] overflow-y-auto">
                {JSON.stringify(obs.args, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {obs.result && (
            <div>
              <Label>Result</Label>
              <pre
                className={`text-[10px] font-mono bg-app-code rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap max-h-[80px] overflow-y-auto ${
                  status === "success" ? "text-emerald-500" : "text-red-400"
                }`}
              >
                {JSON.stringify(
                  status === "success"
                    ? obs.result.output
                    : obs.result.error,
                  null,
                  2,
                )}
              </pre>
            </div>
          )}
        </div>

        {/* Pin indicator */}
        {pinned && (
          <div className="px-3 py-1 border-t border-app text-[9px] t-faint text-center">
            Pinned — click other nodes to compare
          </div>
        )}
      </div>
    </div>
  );
}

/** Pin / close button group in the popover header. */
function PopoverActions({
  pinned,
  onTogglePin,
  onClose,
}: {
  pinned: boolean;
  onTogglePin?: () => void;
  onClose: () => void;
}) {
  return (
    <div className="flex items-center gap-0.5 ml-1 flex-shrink-0">
      {onTogglePin && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onTogglePin();
          }}
          className={`p-0.5 rounded transition-colors ${
            pinned
              ? "text-blue-400 hover:text-blue-300"
              : "t-faint hover:t-muted"
          }`}
          title={pinned ? "Unpin popover" : "Pin popover (stay open)"}
        >
          {pinned ? <PinOff size={10} /> : <Pin size={10} />}
        </button>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        className="p-0.5 rounded t-faint hover:text-red-400 transition-colors"
        title="Close"
      >
        <X size={10} />
      </button>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="block text-[9px] uppercase tracking-wider t-faint mb-0.5">
      {children}
    </span>
  );
}

function StatusBadge({ status }: { status?: string }) {
  switch (status) {
    case "success":
      return (
        <span className="flex items-center gap-0.5 text-[10px] text-emerald-500">
          <CheckCircle2 size={10} /> success
        </span>
      );
    case "error":
      return (
        <span className="flex items-center gap-0.5 text-[10px] text-red-500">
          <XCircle size={10} /> error
        </span>
      );
    case "denied":
      return (
        <span className="flex items-center gap-0.5 text-[10px] text-amber-500">
          <ShieldOff size={10} /> denied
        </span>
      );
    case "rejected":
      return (
        <span className="flex items-center gap-0.5 text-[10px] text-red-500">
          <Ban size={10} /> rejected
        </span>
      );
    default:
      return (
        <span className="flex items-center gap-0.5 text-[10px] t-faint">
          <Clock size={10} /> pending
        </span>
      );
  }
}
