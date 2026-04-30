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
} from "lucide-react";
import { useSession } from "./hooks/useSession";
import { healthCheck } from "./api/client";
import ChatPage from "./pages/ChatPage";
import HistoryPage from "./pages/HistoryPage";
import MemoryPage from "./pages/MemoryPage";
import Settings from "./components/Settings";

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

type Page = "chat" | "history" | "memory" | "settings";

function AppContent() {
  const { sessionId, resetSession } = useSession();
  const [page, setPage] = useState<Page>("chat");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

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
    <div className="h-screen flex flex-col bg-app">
      {/* Header */}
      <header className="flex items-center justify-between px-4 h-12 border-b border-app bg-app-header backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl leading-none">🦀</span>
          <h1 className="text-sm font-semibold t-primary tracking-tight">
            Mini-OpenClaw
          </h1>
          <span className="text-[10px] t-faint font-mono hidden sm:inline">
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
                  ? "bg-blue-600/15 text-blue-400"
                  : "t-muted hover:t-secondary"
              }`}
            >
              <Icon size={14} />
              <span className="hidden sm:inline">{label}</span>
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

function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}

export default App;
