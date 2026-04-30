/**
 * ToolTrace — compact expandable tool execution result display (theme-aware).
 */

import { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Terminal,
  Clock,
} from "lucide-react";
import type { PlanStep } from "../api/types";

interface ToolTraceProps {
  step: PlanStep;
}

export default function ToolTrace({ step }: ToolTraceProps) {
  const [expanded, setExpanded] = useState(false);

  if (!step.result) return null;

  const result = step.result;
  const isSuccess = result.status === "success";
  const duration = computeDuration(result.started_at, result.finished_at);
  const preview = getOutputPreview(result.output);

  return (
    <div className="animate-fade-in rounded-md bg-step-row border border-app overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-xs bg-step-row-hover transition-colors"
      >
        {isSuccess ? (
          <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0" />
        ) : (
          <XCircle size={13} className="text-red-500 flex-shrink-0" />
        )}
        <Terminal size={12} className="t-faint flex-shrink-0" />
        <span className="font-mono t-secondary">{step.tool}</span>
        <span className="t-faint flex-1 truncate ml-1">{preview}</span>
        {duration && (
          <span className="flex items-center gap-0.5 t-faint flex-shrink-0">
            <Clock size={10} />
            {duration}
          </span>
        )}
        {expanded ? (
          <ChevronDown size={12} className="t-faint flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="t-faint flex-shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-app px-2.5 py-2">
          {result.error && (
            <div className="mb-2 px-2 py-1 rounded bg-red-500/10 border border-red-500/20 text-xs text-red-600">
              {result.error}
            </div>
          )}
          {result.output && (
            <div className="text-xs font-mono bg-app-code rounded px-2.5 py-1.5 t-code overflow-x-auto max-h-48 overflow-y-auto">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(result.output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function computeDuration(start: string, end: string): string | null {
  try {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  } catch {
    return null;
  }
}

function getOutputPreview(output: Record<string, unknown> | null): string {
  if (!output) return "no output";
  if ("entries" in output && Array.isArray(output.entries))
    return `→ ${output.entries.length} entries`;
  if ("content" in output && typeof output.content === "string") {
    const len = (output.content as string).length;
    return len > 1024 ? `→ ${(len / 1024).toFixed(1)}KB` : `→ ${len} chars`;
  }
  if ("matches" in output && Array.isArray(output.matches))
    return `→ ${output.matches.length} matches`;
  const str = JSON.stringify(output);
  return str.length > 60 ? `→ ${(str.length / 1024).toFixed(1)}KB` : `→ ${str.substring(0, 50)}`;
}
