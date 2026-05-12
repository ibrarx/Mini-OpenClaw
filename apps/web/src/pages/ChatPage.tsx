/**
 * ChatPage — main layout with chat panel and toggleable sidebar.
 * The sidebar shows the live plan preview and tool traces for the active run.
 */

import { useState, useCallback } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import ChatPanel from "../components/ChatPanel";
import PlanPreview from "../components/PlanPreview";
import ToolTrace from "../components/ToolTrace";
import type { ChatMessage, Run } from "../api/types";

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

  const completedSteps =
    activeRun?.plan?.steps.filter((s) => s.status === "completed" && s.result) ?? [];

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

      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-80 border-l border-app bg-app-secondary flex flex-col overflow-y-auto animate-slide-in-right flex-shrink-0">
          {activeRun?.plan && activeRun.plan.task_type !== "direct_answer" ? (
            <div className="p-3 space-y-4">
              {/* Plan */}
              <div>
                <h3 className="text-xs font-medium t-muted uppercase tracking-wider mb-2">
                  Plan Preview
                </h3>
                <PlanPreview plan={activeRun.plan} run={activeRun} />
              </div>

              {/* Tool traces */}
              {completedSteps.length > 0 && (
                <div>
                  <h3 className="text-xs font-medium t-muted uppercase tracking-wider mb-2">
                    Tool Traces
                  </h3>
                  <div className="space-y-1.5">
                    {completedSteps.map((step) => (
                      <ToolTrace key={step.step_id} step={step} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full t-faint gap-2 p-6">
              <PanelRightOpen size={24} className="opacity-30" />
              <p className="text-xs text-center">
                Plan details will appear here when a run is active
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
