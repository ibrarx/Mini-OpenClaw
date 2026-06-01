/**
 * ChatPanel — main chat interface with messages, plans, approvals, and input.
 * Messages state is owned externally (lifted to App) so it survives tab switches.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Loader2, Square, Trash2, RefreshCw, HelpCircle } from "lucide-react";
import MessageBubble from "./MessageBubble";
import PlanPreview from "./PlanPreview";
import ApprovalCard from "./ApprovalCard";
import ToolTrace from "./ToolTrace";
import { submitChat, approveStep, rejectStep, cancelRun, retryRun, clarifyRun } from "../api/client";
import { useRunSSE } from "../hooks/useRunSSE";
import type { ChatMessage, Run, RunStatus } from "../api/types";

interface ChatPanelProps {
  sessionId: string;
  messages: ChatMessage[];
  onMessagesChange: (msgs: ChatMessage[]) => void;
  /** Called whenever a run updates so the sidebar can reflect it. */
  onRunUpdate?: (run: Run | null) => void;
  /** Called when user clicks a graph icon on a completed run message. */
  onSelectRun?: (run: Run) => void;
}

/** Small retry button shown below failed/cancelled run messages. */
function RetryButton({
  runId,
  onRetry,
}: {
  runId: string;
  onRetry: (runId: string) => void;
}) {
  const [retrying, setRetrying] = useState(false);

  const handleClick = async () => {
    setRetrying(true);
    try {
      await onRetry(runId);
    } catch {
      setRetrying(false);
    }
  };

  return (
    <div className="ml-9 mt-1">
      <button
        onClick={handleClick}
        disabled={retrying}
        className="flex items-center gap-1.5 text-xs t-muted hover:t-primary transition-colors px-2 py-1 rounded-md border border-app hover:bg-step-row disabled:opacity-50"
      >
        <RefreshCw size={12} className={retrying ? "animate-spin" : ""} />
        {retrying ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}

export default function ChatPanel({
  sessionId,
  messages,
  onMessagesChange,
  onRunUpdate,
  onSelectRun,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [decidedSteps, setDecidedSteps] = useState<Set<string>>(new Set());

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the active run
  const { run, error: pollError, refresh } = useRunSSE(activeRunId);

  // Notify parent of run updates
  useEffect(() => {
    onRunUpdate?.(run ?? null);
  }, [run, onRunUpdate]);

  // When a run reaches a terminal state, add the final response as a message
  const lastRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (!run) return;

    const terminal: RunStatus[] = ["completed", "failed", "cancelled"];
    if (terminal.includes(run.status) && lastRunRef.current !== run.run_id) {
      lastRunRef.current = run.run_id;

      if (run.final_response) {
        addMessage("assistant", run.final_response, run.run_id, run.status, run);
      } else if (run.plan?.direct_response) {
        addMessage("assistant", run.plan.direct_response, run.run_id, run.status, run);
      } else if (run.status === "failed") {
        addMessage("assistant", "Run failed. Check the trace for details.", run.run_id, run.status, run);
      } else if (run.status === "cancelled") {
        addMessage("assistant", "Run cancelled.", run.run_id, run.status, run);
      }

      setActiveRunId(null);
      setDecidedSteps(new Set());
      // Focus after React re-renders (input is disabled until activeRunId clears)
      setTimeout(() => inputRef.current?.focus(), 50);
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
    runId?: string,
    runStatus?: RunStatus,
    runSnapshot?: Run,
  ) => {
    const msg: ChatMessage = {
      id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      role,
      content,
      timestamp: new Date().toISOString(),
      run_id: runId,
      run_status: runStatus,
      run: runSnapshot,
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

  const handleRetry = useCallback(
    async (runId: string) => {
      try {
        const { run_id } = await retryRun(runId);
        addMessage("system", "Retrying your request...");
        setActiveRunId(run_id);
        setDecidedSteps(new Set());
      } catch (err) {
        addMessage(
          "system",
          `Retry failed: ${err instanceof Error ? err.message : "unknown"}`
        );
      }
    },
    [messages, onMessagesChange]
  );

  const isActive = !!activeRunId;
  const isClarifying = isActive && run?.status === "awaiting_clarification";

  // Derive the user-friendly status line from the latest observation
  const getStatusText = (): string => {
    if (!run) return "";
    if (run.status === "awaiting_clarification") return "Waiting for your answer...";
    if (run.status === "planning") return "Planning...";
    if (run.observations && run.observations.length > 0) {
      const latest = run.observations[run.observations.length - 1];
      if (latest.user_announcement && !latest.result) {
        return latest.user_announcement;
      }
    }
    if (decidedSteps.size > 0) return "Executing approved step...";
    return `Working on it... (step ${run.iterations ?? 0})`;
  };

  const handleClarify = useCallback(
    async (answer: string) => {
      if (!activeRunId || !answer.trim()) return;
      const userMsg: ChatMessage = {
        id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        role: "user",
        content: answer,
        timestamp: new Date().toISOString(),
        run_id: activeRunId,
      };
      onMessagesChange([...messages, userMsg]);
      try {
        await clarifyRun(activeRunId, answer.trim());
        refresh();
      } catch (err) {
        addMessage(
          "system",
          `Clarification failed: ${err instanceof Error ? err.message : "unknown"}`
        );
      }
    },
    [activeRunId, refresh, messages, onMessagesChange]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && !isActive && (
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
          <div key={msg.id}>
            <MessageBubble
              message={msg}
              onGraphClick={
                msg.run && onSelectRun
                  ? () => onSelectRun(msg.run!)
                  : undefined
              }
            />
            {/* Show retry button on assistant messages from failed/cancelled runs */}
            {msg.role === "assistant" &&
              msg.run_id &&
              (msg.run_status === "failed" || msg.run_status === "cancelled") &&
              !isActive && (
                <RetryButton runId={msg.run_id} onRetry={handleRetry} />
              )}
          </div>
        ))}

        {/* Inline run status */}
        {run && isActive && (
          <div className="space-y-2 animate-fade-in">
            {/* Plan preview */}
            {run.plan && run.plan.task_type !== "direct_answer" && (
              <div className="ml-9 card px-3 py-2.5">
                <PlanPreview plan={run.plan} run={run} />
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

            {/* Clarification questions */}
            {isClarifying && run.clarifying_questions && run.clarifying_questions.length > 0 && (
              <div className="ml-9 animate-slide-up rounded-lg border-2 border-blue-500/30 bg-blue-500/5 overflow-hidden">
                <div className="flex items-center gap-2 px-3.5 py-2 bg-blue-500/10 border-b border-blue-500/20">
                  <HelpCircle size={15} className="text-blue-500" />
                  <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                    Clarification Needed
                  </span>
                  {run.clarification_rounds !== undefined && run.clarification_rounds > 0 && (
                    <span className="ml-auto text-xs t-faint">
                      Round {run.clarification_rounds + 1}
                    </span>
                  )}
                </div>
                <div className="px-3.5 py-3 space-y-1.5">
                  {run.clarifying_questions.map((q, i) => (
                    <p key={i} className="text-sm t-secondary leading-relaxed">
                      {run.clarifying_questions.length > 1 && (
                        <span className="t-faint font-mono mr-1.5">{i + 1}.</span>
                      )}
                      {q}
                    </p>
                  ))}
                  <p className="text-xs t-faint mt-2">Type your answer below to continue.</p>
                </div>
              </div>
            )}

            {/* Completed tool traces */}
            {run.plan?.steps
              .filter((s) => s.status === "completed" && s.result)
              .map((step) => (
                <div key={`trace-${step.step_id}`} className="ml-9">
                  <ToolTrace step={step} />
                </div>
              ))}

            {/* Active status indicator — shows user_announcement from latest observation */}
            {(["planning", "running", "reacting"].includes(run.status) || decidedSteps.size > 0) &&
              !["completed", "failed", "cancelled", "awaiting_clarification"].includes(run.status) && (
              <div className="ml-9 flex items-center gap-2 text-xs t-muted">
                <Loader2 size={14} className="animate-spin text-blue-400" />
                <span>{getStatusText()}</span>
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
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                if (isClarifying) {
                  handleClarify(input);
                  setInput("");
                } else {
                  handleSubmit();
                }
              }
            }}
            placeholder={
              isClarifying
                ? "Type your answer..."
                : isActive
                ? "Waiting for run to complete..."
                : "Type a message..."
            }
            disabled={(isActive && !isClarifying) || submitting}
            className="input-field"
          />
          {isActive && !isClarifying ? (
            <button
              onClick={handleCancel}
              className="btn btn-danger flex-shrink-0"
              title="Cancel run"
            >
              <Square size={14} />
            </button>
          ) : isClarifying ? (
            <button
              onClick={() => { handleClarify(input); setInput(""); }}
              disabled={!input.trim()}
              className="btn btn-primary flex-shrink-0"
            >
              <Send size={14} />
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
