/**
 * App — root layout with header navigation, theme support, and page routing.
 */

import { useState, useEffect, createContext, useContext, useCallback } from "react";
import {
  MessageSquare,
  History,
  Brain,
  Wifi,
  WifiOff,
  Cog,
  Clock,
} from "lucide-react";
import { useSession } from "./hooks/useSession";
import { healthCheck, getScheduledTasks } from "./api/client";
import ChatPage from "./pages/ChatPage";
import HistoryPage from "./pages/HistoryPage";
import MemoryPage from "./pages/MemoryPage";
import SchedulerPage from "./pages/SchedulerPage";
import Settings from "./components/Settings";
import type { ChatMessage } from "./api/types";

// ── Theme ─────────────────────────────────────────────

export type ThemeMode = "light" | "dark" | "system";

interface ThemeContextValue {
  theme: ThemeMode;
  setTheme: (t: ThemeMode) => void;
  resolved: "light" | "dark";
}

export const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  setTheme: () => {},
  resolved: "dark",
});

export const useTheme = () => useContext(ThemeContext);

const THEME_KEY = "mini-openclaw-theme";

function resolveTheme(mode: ThemeMode): "light" | "dark" {
  if (mode === "system") {
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }
  return mode;
}

function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(() => {
    return (localStorage.getItem(THEME_KEY) as ThemeMode) || "dark";
  });
  const [resolved, setResolved] = useState<"light" | "dark">(() =>
    resolveTheme(theme)
  );

  const setTheme = useCallback((t: ThemeMode) => {
    localStorage.setItem(THEME_KEY, t);
    setThemeState(t);
  }, []);

  // Recompute on theme change or system preference change
  useEffect(() => {
    const r = resolveTheme(theme);
    setResolved(r);

    const root = document.documentElement;
    if (r === "light") {
      root.classList.add("theme-light");
    } else {
      root.classList.remove("theme-light");
    }

    // Listen for system changes when in system mode
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: light)");
      const handler = () => {
        const nr = resolveTheme("system");
        setResolved(nr);
        if (nr === "light") root.classList.add("theme-light");
        else root.classList.remove("theme-light");
      };
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, resolved }}>
      {children}
    </ThemeContext.Provider>
  );
}

// ── App ───────────────────────────────────────────────

type Page = "chat" | "history" | "memory" | "scheduler" | "settings";

function AppContent() {
  const { sessionId, resetSession } = useSession();
  const [page, setPage] = useState<Page>("chat");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  // Track the last run_count the user has "seen" per task
  const [seenRunCounts, setSeenRunCounts] = useState<Record<string, number>>({});
  const [schedulerBadge, setSchedulerBadge] = useState(0);

  useEffect(() => {
    const check = () =>
      healthCheck()
        .then(() => setBackendUp(true))
        .catch(() => setBackendUp(false));
    check();
    const id = setInterval(check, 10_000);
    return () => clearInterval(id);
  }, []);

  // Poll scheduler for new runs (badge = unseen run count)
  useEffect(() => {
    const poll = () =>
      getScheduledTasks()
        .then((tasks) => {
          // If user is on the scheduler page, mark all as seen
          if (page === "scheduler") {
            const counts: Record<string, number> = {};
            for (const t of tasks) counts[t.id] = t.run_count;
            setSeenRunCounts(counts);
            setSchedulerBadge(0);
            return;
          }
          // Count new runs since last seen
          let unseen = 0;
          for (const t of tasks) {
            const seen = seenRunCounts[t.id] ?? 0;
            if (t.run_count > seen) unseen += t.run_count - seen;
          }
          setSchedulerBadge(unseen);
        })
        .catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, [page, seenRunCounts]);

  const navItems: { id: Page; label: string; icon: typeof MessageSquare }[] = [
    { id: "chat", label: "Chat", icon: MessageSquare },
    { id: "history", label: "History", icon: History },
    { id: "memory", label: "Memory", icon: Brain },
    { id: "scheduler", label: "Scheduler", icon: Clock },
    { id: "settings", label: "Settings", icon: Cog },
  ];

  return (
    <div className="h-screen flex flex-col bg-app">
      {/* Header */}
      <header className="flex items-center justify-between px-4 h-12 border-b border-app bg-app-header backdrop-blur-sm flex-shrink-0">
        <button
          onClick={() => setPage("chat")}
          className="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
        >
          <span className="text-4xl leading-none">🦀</span>
          <h1 className="text-sm font-semibold t-primary tracking-tight">
            Mini-OpenClaw
          </h1>
          <span className="text-[10px] t-faint font-mono hidden sm:inline">
            v0.1.0
          </span>
        </button>

        <nav className="flex items-center gap-0.5">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPage(id)}
              className={`relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs transition-colors ${
                page === id
                  ? "bg-blue-600/15 text-blue-400"
                  : "t-muted hover:t-secondary"
              }`}
            >
              <Icon size={14} />
              <span className="hidden sm:inline">{label}</span>
              {id === "scheduler" && schedulerBadge > 0 && (
                <span className="absolute -top-1 -right-1.5 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-emerald-500 text-[8px] font-bold text-white animate-pulse">
                  {schedulerBadge > 99 ? "99+" : schedulerBadge}
                </span>
              )}
            </button>
          ))}

          {/* Backend status indicator */}
          <div
            className="ml-2 pl-2 border-l border-app"
            title={backendUp ? "Backend connected" : "Backend unreachable"}
          >
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
        {page === "chat" && (
          <ChatPage
            sessionId={sessionId}
            messages={chatMessages}
            onMessagesChange={setChatMessages}
          />
        )}
        {page === "history" && <HistoryPage sessionId={sessionId} />}
        {page === "memory" && <MemoryPage />}
        {page === "scheduler" && <SchedulerPage />}
        {page === "settings" && (
          <div className="h-full overflow-y-auto">
            <Settings sessionId={sessionId} onResetSession={resetSession} />
          </div>
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}

export default App;
