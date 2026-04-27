/**
 * App — root layout with header navigation and page routing.
 * Uses simple tab-based navigation (no react-router needed).
 */

import { useState, useEffect } from "react";
import {
  MessageSquare,
  History,
  Brain,
  Wifi,
  WifiOff,
  Cog,
} from "lucide-react";
import { useSession } from "./hooks/useSession";
import { healthCheck } from "./api/client";
import ChatPage from "./pages/ChatPage";
import HistoryPage from "./pages/HistoryPage";
import MemoryPage from "./pages/MemoryPage";
import Settings from "./components/Settings";

type Page = "chat" | "history" | "memory" | "settings";

function App() {
  const { sessionId, resetSession } = useSession();
  const [page, setPage] = useState<Page>("chat");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

  // Health check on mount
  useEffect(() => {
    healthCheck()
      .then(() => setBackendUp(true))
      .catch(() => setBackendUp(false));
  }, []);

  const navItems: { id: Page; label: string; icon: typeof MessageSquare }[] = [
    { id: "chat", label: "Chat", icon: MessageSquare },
    { id: "history", label: "History", icon: History },
    { id: "memory", label: "Memory", icon: Brain },
    { id: "settings", label: "Settings", icon: Cog },
  ];

  return (
    <div className="h-screen flex flex-col bg-gray-950">
      {/* Header */}
      <header className="flex items-center justify-between px-4 h-12 border-b border-gray-800 bg-gray-950/90 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">🦀</span>
          <h1 className="text-sm font-semibold text-gray-200 tracking-tight">
            Mini-OpenClaw
          </h1>
          <span className="text-[10px] text-gray-600 font-mono hidden sm:inline">
            v0.1.0
          </span>
        </div>

        <nav className="flex items-center gap-0.5">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPage(id)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs transition-colors ${
                page === id
                  ? "bg-gray-800 text-gray-200"
                  : "text-gray-500 hover:text-gray-300 hover:bg-gray-800/50"
              }`}
            >
              <Icon size={14} />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}

          {/* Backend status indicator */}
          <div className="ml-2 pl-2 border-l border-gray-800" title={backendUp ? "Backend connected" : "Backend unreachable"}>
            {backendUp === null ? (
              <div className="w-2 h-2 rounded-full bg-gray-600 animate-pulse" />
            ) : backendUp ? (
              <Wifi size={14} className="text-emerald-500" />
            ) : (
              <WifiOff size={14} className="text-red-500" />
            )}
          </div>
        </nav>
      </header>

      {/* Page content */}
      <main className="flex-1 overflow-hidden">
        {page === "chat" && <ChatPage sessionId={sessionId} />}
        {page === "history" && <HistoryPage sessionId={sessionId} />}
        {page === "memory" && <MemoryPage />}
        {page === "settings" && (
          <div className="h-full overflow-y-auto">
            <Settings sessionId={sessionId} onResetSession={resetSession} />
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
