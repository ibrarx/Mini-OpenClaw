/**
 * MemoryBrowser — browse, search, and delete memory items (theme-aware).
 */

import { useState, useEffect, useCallback } from "react";
import {
  Search,
  Trash2,
  Loader2,
  Brain,
  BookOpen,
  FileText,
  RefreshCw,
  Layers,
} from "lucide-react";
import { getMemory, searchMemory, deleteMemoryItem } from "../api/client";
import type { MemoryItem, MemoryType } from "../api/types";

interface MemoryBrowserProps {
  workspaceId?: string;
}

const TYPE_TABS: { label: string; value: MemoryType | "all"; icon: typeof Brain }[] = [
  { label: "All", value: "all", icon: Layers },
  { label: "Facts", value: "fact", icon: Brain },
  { label: "Episodes", value: "episode", icon: BookOpen },
  { label: "Summaries", value: "summary", icon: FileText },
];

export default function MemoryBrowser({ workspaceId = "default" }: MemoryBrowserProps) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<MemoryType | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const type = activeTab === "all" ? undefined : activeTab;
      const data = await getMemory(workspaceId, type);
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load memory");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, activeTab]);

  useEffect(() => {
    if (!searchQuery) fetchItems();
  }, [fetchItems, searchQuery]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      fetchItems();
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const type = activeTab === "all" ? undefined : activeTab;
      const data = await searchMemory(searchQuery.trim(), type);
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMemoryItem(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  return (
    <div className="p-4 h-full flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium t-secondary">Memory Browser</h2>
        <button onClick={fetchItems} className="btn btn-ghost text-xs p-1">
          <RefreshCw size={12} />
        </button>
      </div>

      {/* Search */}
      <div className="flex gap-2 mb-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 t-faint" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search memory..."
            className="input-field pl-8 text-xs"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={searching}
          className="btn btn-primary text-xs"
        >
          {searching ? <Loader2 size={12} className="animate-spin" /> : "Search"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-3">
        {TYPE_TABS.map(({ label, value, icon: Icon }) => (
          <button
            key={value}
            onClick={() => setActiveTab(value)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs transition-colors ${
              activeTab === value
                ? "bg-tab-active t-primary"
                : "t-faint hover:t-secondary"
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto space-y-2">
        {loading && (
          <div className="flex items-center justify-center py-12 t-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-500/10 px-3 py-2 rounded border border-red-500/20">
            {error}
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 t-muted gap-2">
            <Brain size={24} className="opacity-40" />
            <p className="text-sm">No memories found</p>
          </div>
        )}

        {items.map((item) => (
          <MemoryCard key={item.id} item={item} onDelete={handleDelete} />
        ))}
      </div>

      {!loading && items.length > 0 && (
        <div className="mt-2 pt-2 border-t border-app text-[10px] t-faint">
          {items.length} item{items.length !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}

function MemoryCard({ item, onDelete }: { item: MemoryItem; onDelete: (id: string) => void }) {
  const typeColor: Record<string, string> = {
    fact: "border-l-blue-500",
    episode: "border-l-purple-500",
    summary: "border-l-teal-500",
  };

  return (
    <div
      className={`card border-l-2 ${typeColor[item.memory_type] ?? "border-l-gray-400"} p-3 animate-fade-in`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="badge bg-badge-type t-muted text-[10px]">
              {item.memory_type}
            </span>
            <ConfidenceDot confidence={item.confidence} />
          </div>
          <p className="text-sm t-primary leading-relaxed">{item.content}</p>
          {item.summary && item.summary !== item.content && (
            <p className="text-xs t-muted mt-1 italic">{item.summary}</p>
          )}
          <div className="flex items-center gap-2 mt-1.5 text-[10px] t-faint">
            {item.source && <span>Source: {item.source}</span>}
            <span>{formatDate(item.created_at)}</span>
          </div>
        </div>
        <button
          onClick={() => onDelete(item.id)}
          className="p-1 rounded hover:bg-red-500/10 t-faint hover:text-red-500 transition-colors flex-shrink-0"
          title="Delete"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}

function ConfidenceDot({ confidence }: { confidence: number }) {
  const color =
    confidence >= 0.8
      ? "bg-emerald-500"
      : confidence >= 0.5
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <span
      className={`w-1.5 h-1.5 rounded-full ${color}`}
      title={`Confidence: ${Math.round(confidence * 100)}%`}
    />
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}
