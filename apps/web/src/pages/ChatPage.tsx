/**
 * ChatPage — main layout with chat panel and toggleable sidebar.
 *
 * The sidebar shows the execution graph:
 * - During an active run: shows the live graph (real-time updates)
 * - After a run completes: clicking the graph icon on a message loads
 *   that run's graph in the sidebar (Option A: click message to load)
 */

import { useState, useCallback, lazy, Suspense } from "react";
import { PanelRightClose, PanelRightOpen, GitBranch, Loader2 } from "lucide-react";
import ChatPanel from "../components/ChatPanel";
import type { ChatMessage, Run } from "../api/types";

// Lazy-load the graph component (it pulls in @xyflow/react)
const ExecutionGraph = lazy(() => import("../components/ExecutionGraph"));

interface ChatPageProps {
  sessionId: string;
  messages: ChatMessage[];
  onMessagesChange: (msgs: ChatMessage[]) => void;
}

export default function ChatPage({ sessionId, messages, onMessagesChange }: ChatPageProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  /** Run selected by clicking a completed message's graph icon. */
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);

  const handleRunUpdate = useCallback((run: Run | null) => {
    setActiveRun(run);
    // Clear selected run when a new active run starts
    if (run && ["planning", "reacting", "running"].includes(run.status)) {
      setSelectedRun(null);
    }
  }, []);

  const handleSelectRun = useCallback((run: Run) => {
    setSelectedRun((prev) => (prev?.run_id === run.run_id ? null : run));
  }, []);

  // Active run takes priority; otherwise show the selected past run
  const isLive =
    activeRun?.plan &&
    activeRun.plan.task_type !== "direct_answer" &&
    (activeRun.observations.length > 0 ||
      activeRun.status === "planning" ||
      activeRun.status === "reacting");

  const graphRun = isLive ? activeRun : selectedRun;
  const graphLabel = isLive
    ? "Live"
    : selectedRun
      ? selectedRun.user_message.length > 28
        ? selectedRun.user_message.slice(0, 28) + "…"
        : selectedRun.user_message
      : null;

  return (
    <div className="flex h-full">
      {/* Chat panel */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel
          sessionId={sessionId}
          messages={messages}
          onMessagesChange={onMessagesChange}
          onRunUpdate={handleRunUpdate}
          onSelectRun={handleSelectRun}
        />
      </div>

      {/* Sidebar toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="self-start mt-3 mr-1 p-1.5 rounded-md hover:opacity-80 t-muted transition-colors z-10"
        title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
      >
        {sidebarOpen ? (
          <PanelRightClose size={16} />
        ) : (
          <PanelRightOpen size={16} />
        )}
      </button>

      {/* Sidebar — execution graph or empty state */}
      {sidebarOpen && (
        <div className="w-80 border-l border-app bg-app-secondary flex flex-col animate-slide-in-right flex-shrink-0 overflow-hidden">
          {graphRun ? (
            <>
              {/* Header */}
              <div className="px-3 py-2 border-b border-app flex items-center gap-2 flex-shrink-0">
                <GitBranch size={12} className={isLive ? "text-blue-400" : "t-muted"} />
                <h3 className="text-xs font-medium t-muted uppercase tracking-wider">
                  Execution graph
                </h3>
                {graphLabel && (
                  <span className={`text-[10px] ml-auto truncate max-w-[120px] ${
                    isLive ? "text-blue-400" : "t-faint"
                  }`}>
                    {graphLabel}
                  </span>
                )}
              </div>

              {/* Graph canvas */}
              <div className="flex-1 min-h-0">
                <Suspense
                  fallback={
                    <div className="flex items-center justify-center h-full t-faint gap-2">
                      <Loader2 size={14} className="animate-spin" />
                      <span className="text-xs">Loading graph…</span>
                    </div>
                  }
                >
                  <ExecutionGraph key={graphRun.run_id} run={graphRun} />
                </Suspense>
              </div>

              {/* Footer */}
              <div className="px-3 py-1.5 border-t border-app flex items-center flex-shrink-0">
                <span className="text-[10px] t-faint flex-1 text-center">
                  Click a node for details · Scroll to zoom · Drag to pan
                </span>
                {!isLive && selectedRun && (
                  <button
                    onClick={() => setSelectedRun(null)}
                    className="text-[10px] t-faint hover:text-red-400 transition-colors ml-1"
                    title="Close graph"
                  >
                    ✕
                  </button>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full t-faint gap-2 p-6">
              <GitBranch size={24} className="opacity-30" />
              <p className="text-xs text-center leading-relaxed">
                Execution graph will appear here during active runs
              </p>
              <p className="text-[10px] text-center t-faint">
                Click <GitBranch size={9} className="inline" /> on any message to view its graph
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
