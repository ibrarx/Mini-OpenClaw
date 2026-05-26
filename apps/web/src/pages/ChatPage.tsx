/**
 * ChatPage — main layout with chat panel and toggleable sidebar.
 *
 * The sidebar shows the execution graph when a run is active, replacing
 * the old redundant PlanPreview + ToolTraces panel. The inline PlanPreview
 * in the chat area remains as the timeline view.
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

  const handleRunUpdate = useCallback((run: Run | null) => {
    setActiveRun(run);
  }, []);

  const hasGraph =
    activeRun?.plan &&
    activeRun.plan.task_type !== "direct_answer" &&
    (activeRun.observations.length > 0 ||
      activeRun.status === "planning" ||
      activeRun.status === "reacting");

  return (
    <div className="flex h-full">
      {/* Chat panel */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel
          sessionId={sessionId}
          messages={messages}
          onMessagesChange={onMessagesChange}
          onRunUpdate={handleRunUpdate}
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
          {hasGraph && activeRun ? (
            <>
              {/* Header */}
              <div className="px-3 py-2 border-b border-app flex items-center gap-2 flex-shrink-0">
                <GitBranch size={12} className="text-blue-400" />
                <h3 className="text-xs font-medium t-muted uppercase tracking-wider">
                  Execution graph
                </h3>
                <span className="text-[10px] t-faint ml-auto">
                  {activeRun.observations.length} step{activeRun.observations.length !== 1 ? "s" : ""}
                </span>
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
                  <ExecutionGraph run={activeRun} />
                </Suspense>
              </div>

              {/* Footer hint */}
              <div className="px-3 py-1.5 border-t border-app text-[10px] t-faint text-center flex-shrink-0">
                Click a node for details · Scroll to zoom · Drag to pan
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full t-faint gap-2 p-6">
              <GitBranch size={24} className="opacity-30" />
              <p className="text-xs text-center">
                Execution graph will appear here when a run is active
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
