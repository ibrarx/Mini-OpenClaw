/**
 * ChatPanel — main chat interface with messages, plans, approvals, and input.
 * Messages state is owned externally (lifted to App) so it survives tab switches.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Loader2, Square, Trash2 } from "lucide-react";
import MessageBubble from "./MessageBubble";
import PlanPreview from "./PlanPreview";
import ApprovalCard from "./ApprovalCard";
import ToolTrace from "./ToolTrace";
import { submitChat, approveStep, rejectStep, cancelRun } from "../api/client";
import { useRunPolling } from "../hooks/useRunPolling";
import type { ChatMessage, Run, RunStatus } from "../api/types";

interface ChatPanelProps {
  sessionId: string;
  messages: ChatMessage[];
  onMessagesChange: (msgs: ChatMessage[]) => void;
  /** Called whenever a run updates so the sidebar can reflect it. */
  onRunUpdate?: (run: Run | null) => void;
}

export default function ChatPanel({
  sessionId,
  messages,
  onMessagesChange,
  onRunUpdate,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [decidedSteps, setDecidedSteps] = useState<Set<string>>(new Set());

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the active run
  const { run, error: pollError, refresh } = useRunPolling(activeRunId);

  // Notify parent of run updates
  useEffect(() => {
    onRunUpdate?.(run ?? null);
  }, [run, onRunUpdate]);

  // When a run completes, add the final response as a message
  const lastRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (!run) return;

    const terminal: RunStatus[] = ["completed", "failed", "cancelled"];
    if (terminal.includes(run.status) && lastRunRef.current !== run.run_id) {
      lastRunRef.current = run.run_id;

      if (run.final_response) {
        addMessage("assistant", run.final_response, run.run_id);
      } else if (run.plan?.direct_response) {
        addMessage("assistant", run.plan.direct_response, run.run_id);
      } else if (run.status === "failed") {
        addMessage("system", "Run failed. Check the trace for details.");
      } else if (run.status === "cancelled") {
        addMessage("system", "Run cancelled.");
      }

      setActiveRunId(null);
      setDecidedSteps(new Set());
    }
  }, [run]);

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, run]);

  const addMessage = (
    role: ChatMessage["role"],
    content: string,
    runId?: string
  ) => {
    const msg: ChatMessage = {
      id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      role,
      content,
      timestamp: new Date().toISOString(),
      run_id: runId,
    };
    onMessagesChange([...messages, msg]);
  };

  const handleClearChat = () => {
    onMessagesChange([]);
    lastRunRef.current = null;
    setActiveRunId(null);
    setDecidedSteps(new Set());
    inputRef.current?.focus();
  };

  const handleSubmit = async () => {
    const text = input.trim();
    if (!text || submitting || activeRunId) return;

    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    const withUser = [...messages, userMsg];
    onMessagesChange(withUser);
    setInput("");
    setSubmitting(true);
    setDecidedSteps(new Set());

    try {
      const { run_id } = await submitChat(sessionId, text);
      setActiveRunId(run_id);
      // Append "Planning..." system message after user message
      onMessagesChange([
        ...withUser,
        {
          id: `msg_${Date.now()}_sys`,
          role: "system",
          content: "Planning...",
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      addMessage(
        "system",
        `Error: ${err instanceof Error ? err.message : "Failed to submit"}`
      );
    } finally {
      setSubmitting(false);
      inputRef.current?.focus();
    }
  };

  const handleApprove = useCallback(
    async (runId: string, stepId: string) => {
      try {
        await approveStep(runId, stepId);
        setDecidedSteps((prev) => new Set(prev).add(stepId));
        addMessage("system", `Step approved`);
        refresh();
      } catch (err) {
        addMessage(
          "system",
          `Approval failed: ${err instanceof Error ? err.message : "unknown"}`
        );
      }
    },
    [refresh, messages, onMessagesChange]
  );

  const handleReject = useCallback(
    async (runId: string, stepId: string) => {
      try {
        await rejectStep(runId, stepId);
        setDecidedSteps((prev) => new Set(prev).add(stepId));
        addMessage("system", `Step rejected`);
        refresh();
      } catch (err) {
        addMessage(
          "system",
          `Rejection failed: ${err instanceof Error ? err.message : "unknown"}`
        );
      }
    },
    [refresh, messages, onMessagesChange]
  );

  const handleCancel = async () => {
    if (activeRunId) {
      try {
        await cancelRun(activeRunId);
        refresh();
      } catch {
        // ignore
      }
    }
  };

  const isActive = !!activeRunId;

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full t-muted gap-3">
            <div className="text-5xl mb-1 opacity-30">🦀</div>
            <p className="text-sm t-secondary">Send a message to get started</p>
            <div className="flex flex-col gap-1.5 mt-1">
              {[
                "List files in the workspace",
                "Read the README and summarize it",
                "Search for TODO in all files",
                "Remember that I prefer dark mode",
                "Create a file called notes.txt with hello world",
              ].map((cmd) => (
                <button
                  key={cmd}
                  onClick={() => {
                    setInput(cmd);
                    inputRef.current?.focus();
                  }}
                  className="text-xs t-faint hover:text-blue-400 hover:bg-blue-500/5 px-3 py-1.5 rounded-md border border-transparent hover:border-blue-500/20 transition-all text-left"
                >
                  <span className="t-faint mr-1.5">Try:</span>
                  &quot;{cmd}&quot;
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Inline run status */}
        {run && isActive && (
          <div className="space-y-2 animate-fade-in">
            {/* Plan preview */}
            {run.plan && run.plan.task_type !== "direct_answer" && (
              <div className="ml-9 card px-3 py-2.5">
                <PlanPreview plan={run.plan} />
              </div>
            )}

            {/* Approval cards — exclude steps that have already been decided locally */}
            {run.plan?.steps
              .filter((s) => s.status === "awaiting_approval" && !decidedSteps.has(s.step_id))
              .map((step) => (
                <div key={step.step_id} className="ml-9">
                  <ApprovalCard
                    step={step}
                    runId={run.run_id}
                    onApprove={handleApprove}
                    onReject={handleReject}
                  />
                </div>
              ))}

            {/* Completed tool traces */}
            {run.plan?.steps
              .filter((s) => s.status === "completed" && s.result)
              .map((step) => (
                <div key={`trace-${step.step_id}`} className="ml-9">
                  <ToolTrace step={step} />
                </div>
              ))}

            {/* Active status indicator */}
            {(["planning", "running"].includes(run.status) || decidedSteps.size > 0) &&
              !["completed", "failed", "cancelled"].includes(run.status) && (
              <div className="ml-9 flex items-center gap-2 text-xs text-gray-400">
                <Loader2 size={14} className="animate-spin text-blue-400" />
                <span>
                  {run.status === "planning"
                    ? "Creating plan..."
                    : decidedSteps.size > 0
                    ? "Executing approved step..."
                    : "Executing..."}
                </span>
              </div>
            )}
          </div>
        )}

        {pollError && (
          <div className="ml-9 text-xs text-red-400 bg-red-500/10 px-3 py-1.5 rounded border border-red-500/20">
            Polling error: {pollError}
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="border-t border-app px-4 py-3 bg-app-input-bar backdrop-blur-sm">
        <div className="flex items-center gap-2">
          {/* Clear chat button — only visible when there are messages */}
          {messages.length > 0 && !isActive && (
            <button
              onClick={handleClearChat}
              className="btn btn-ghost flex-shrink-0 p-1.5 t-faint hover:text-red-400"
              title="Clear chat"
            >
              <Trash2 size={14} />
            </button>
          )}
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSubmit()}
            placeholder={isActive ? "Waiting for run to complete..." : "Type a message..."}
            disabled={isActive || submitting}
            className="input-field"
          />
          {isActive ? (
            <button
              onClick={handleCancel}
              className="btn btn-danger flex-shrink-0"
              title="Cancel run"
            >
              <Square size={14} />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!input.trim() || submitting}
              className="btn btn-primary flex-shrink-0"
            >
              {submitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Send size={14} />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
