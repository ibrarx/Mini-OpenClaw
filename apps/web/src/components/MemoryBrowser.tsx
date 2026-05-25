/**
 * MemoryBrowser — browse, search (hybrid/keyword/vector), and test memory.
 *
 * Features:
 *  - Tab filter: All / Facts / Episodes / Summaries / Strategies / Preferences
 *  - Search mode toggle: Hybrid (default) / Keyword / Vector
 *  - Similarity scores next to search results
 *  - "Test Memory" mode: see what the planner would receive for a query
 *  - Delete individual items
 *  - Agent Dreams: trigger dream cycle, review pending insights
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
  Zap,
  Type,
  Cpu,
  Lightbulb,
  Heart,
  Sparkles,
  Check,
  X,
  Pencil,
} from "lucide-react";
import {
  getMemory,
  searchMemory,
  deleteMemoryItem,
  triggerDream,
  getPendingInsights,
  reviewInsight,
} from "../api/client";
import type { MemoryItem, MemoryType } from "../api/types";
import type { SearchMode } from "../api/client";

interface MemoryBrowserProps {
  workspaceId?: string;
}

const TYPE_TABS: { label: string; value: MemoryType | "all"; icon: typeof Brain }[] = [
  { label: "All", value: "all", icon: Layers },
  { label: "Facts", value: "fact", icon: Brain },
  { label: "Episodes", value: "episode", icon: BookOpen },
  { label: "Summaries", value: "summary", icon: FileText },
  { label: "Strategies", value: "strategy", icon: Lightbulb },
  { label: "Preferences", value: "preference", icon: Heart },
];

const SEARCH_MODES: { label: string; value: SearchMode; icon: typeof Zap; tip: string }[] = [
  { label: "Hybrid", value: "hybrid", icon: Zap, tip: "70% semantic + 30% keyword" },
  { label: "Keyword", value: "keyword", icon: Type, tip: "Exact word matching" },
  { label: "Vector", value: "vector", icon: Cpu, tip: "Semantic similarity only" },
];

export default function MemoryBrowser({ workspaceId = "default" }: MemoryBrowserProps) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<MemoryType | "all">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchMode, setSearchMode] = useState<SearchMode>("hybrid");
  const [isSearchResult, setIsSearchResult] = useState(false);

  // Dream state
  const [pendingInsights, setPendingInsights] = useState<MemoryItem[]>([]);
  const [dreaming, setDreaming] = useState(false);
  const [dreamResult, setDreamResult] = useState<string | null>(null);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    setIsSearchResult(false);
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

  const fetchPending = useCallback(async () => {
    try {
      const data = await getPendingInsights(workspaceId);
      setPendingInsights(data);
    } catch {
      // Non-critical, silently ignore
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!searchQuery) fetchItems();
  }, [fetchItems, searchQuery]);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      fetchItems();
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const type = activeTab === "all" ? undefined : activeTab;
      const data = await searchMemory(searchQuery.trim(), type, 20, searchMode);
      setItems(data);
      setIsSearchResult(true);
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

  const handleDream = async () => {
    setDreaming(true);
    setDreamResult(null);
    try {
      const result = await triggerDream(workspaceId);
      if (result.skipped) {
        setDreamResult(`Skipped: ${result.skipped}`);
      } else if (result.error) {
        setDreamResult(`Error: ${result.error}`);
      } else {
        setDreamResult(
          `Proposed ${result.strategies} strategies and ${result.preferences} preferences`
        );
        fetchPending();
      }
    } catch (err) {
      setDreamResult(err instanceof Error ? err.message : "Dream failed");
    } finally {
      setDreaming(false);
    }
  };

  const handleReview = async (id: string, accepted: boolean, editedContent?: string) => {
    try {
      await reviewInsight(id, accepted, editedContent);
      setPendingInsights((prev) => prev.filter((item) => item.id !== id));
      if (accepted) {
        // Refresh main list to show newly active item
        fetchItems();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    }
  };

  const clearSearch = () => {
    setSearchQuery("");
    setIsSearchResult(false);
  };

  return (
    <div className="p-4 h-full flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium t-secondary">Memory Browser</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={handleDream}
            disabled={dreaming}
            className="btn btn-ghost text-xs p-1 flex items-center gap-1"
            title="Trigger Agent Dream — analyse recent runs for patterns"
          >
            {dreaming ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Sparkles size={12} />
            )}
            <span className="hidden sm:inline">Dream</span>
          </button>
          <button onClick={() => { fetchItems(); fetchPending(); }} className="btn btn-ghost text-xs p-1" title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Dream result banner */}
      {dreamResult && (
        <div className="text-xs px-3 py-1.5 rounded mb-2 bg-purple-500/10 text-purple-600 border border-purple-500/20 flex items-center justify-between">
          <span>🧠 {dreamResult}</span>
          <button onClick={() => setDreamResult(null)} className="ml-2 hover:text-purple-800">
            <X size={10} />
          </button>
        </div>
      )}

      {/* Pending insights review */}
      {pendingInsights.length > 0 && (
        <div className="mb-3 space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-purple-600">
            <Sparkles size={12} />
            <span>{pendingInsights.length} insight{pendingInsights.length !== 1 ? "s" : ""} to review</span>
          </div>
          {pendingInsights.map((item) => (
            <InsightReviewCard
              key={item.id}
              item={item}
              onReview={handleReview}
            />
          ))}
        </div>
      )}

      {/* Search bar */}
      <div className="flex gap-2 mb-2">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 t-faint" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search memory (try semantic queries!)..."
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

      {/* Search mode selector */}
      <div className="flex items-center gap-2 mb-3">
        <div className="flex gap-0.5 bg-surface rounded-md p-0.5">
          {SEARCH_MODES.map(({ label, value, icon: Icon, tip }) => (
            <button
              key={value}
              onClick={() => setSearchMode(value)}
              title={tip}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors ${
                searchMode === value
                  ? "bg-tab-active t-primary font-medium"
                  : "t-faint hover:t-secondary"
              }`}
            >
              <Icon size={10} />
              {label}
            </button>
          ))}
        </div>
        {isSearchResult && (
          <button onClick={clearSearch} className="text-[10px] t-faint hover:t-secondary underline">
            Clear search
          </button>
        )}
      </div>

      {/* Type tabs */}
      <div className="flex gap-1 mb-3 flex-wrap">
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
            <p className="text-sm">
              {isSearchResult ? "No matching memories found" : "No memories yet"}
            </p>
            {!isSearchResult && activeTab === "summary" && (
              <p className="text-xs t-faint text-center max-w-xs">
                Summaries are auto-generated after every 5 completed tasks.
                Use the chat to run a few tasks first!
              </p>
            )}
            {!isSearchResult && (activeTab === "strategy" || activeTab === "preference") && (
              <p className="text-xs t-faint text-center max-w-xs">
                {activeTab === "strategy" ? "Strategies" : "Preferences"} are discovered
                by Agent Dreams after enough completed tasks. Click the ✨ Dream button
                or let them generate automatically.
              </p>
            )}
          </div>
        )}

        {items.map((item) => (
          <MemoryCard
            key={item.id}
            item={item}
            onDelete={handleDelete}
            showScore={isSearchResult}
          />
        ))}
      </div>

      {!loading && items.length > 0 && (
        <div className="mt-2 pt-2 border-t border-app text-[10px] t-faint flex justify-between">
          <span>
            {items.length} item{items.length !== 1 ? "s" : ""}
            {isSearchResult ? ` (${searchMode} search)` : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/** Card for reviewing a pending dream insight. */
function InsightReviewCard({
  item,
  onReview,
}: {
  item: MemoryItem;
  onReview: (id: string, accepted: boolean, editedContent?: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(item.content);

  const typeIcon = item.memory_type === "strategy" ? Lightbulb : Heart;
  const TypeIcon = typeIcon;
  const typeColor =
    item.memory_type === "strategy"
      ? "border-purple-500 bg-purple-500/5"
      : "border-pink-500 bg-pink-500/5";

  return (
    <div className={`card border-l-2 ${typeColor} p-3 animate-fade-in`}>
      <div className="flex items-start gap-2">
        <TypeIcon size={14} className="mt-0.5 flex-shrink-0 text-purple-500" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="badge bg-purple-500/20 text-purple-600 text-[10px]">
              {item.memory_type} suggestion
            </span>
            <ConfidenceDot confidence={item.confidence} />
          </div>
          {editing ? (
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              className="input-field text-sm w-full resize-none"
              rows={2}
            />
          ) : (
            <p className="text-sm t-primary leading-relaxed">{item.content}</p>
          )}
          <div className="flex items-center gap-1.5 mt-2">
            <button
              onClick={() => onReview(item.id, true, editing ? editText : undefined)}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-600 hover:bg-emerald-500/30 transition-colors"
              title="Accept this insight"
            >
              <Check size={10} /> Accept
            </button>
            <button
              onClick={() => onReview(item.id, false)}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-red-500/20 text-red-600 hover:bg-red-500/30 transition-colors"
              title="Dismiss this insight"
            >
              <X size={10} /> Dismiss
            </button>
            <button
              onClick={() => setEditing(!editing)}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-600 hover:bg-amber-500/30 transition-colors"
              title="Edit before accepting"
            >
              <Pencil size={10} /> {editing ? "Cancel" : "Edit"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MemoryCard({
  item,
  onDelete,
  showScore,
}: {
  item: MemoryItem;
  onDelete: (id: string) => void;
  showScore: boolean;
}) {
  const typeColor: Record<string, string> = {
    fact: "border-l-blue-500",
    episode: "border-l-purple-500",
    summary: "border-l-teal-500",
    strategy: "border-l-violet-500",
    preference: "border-l-pink-500",
  };

  const statusBadge = item.status === "pending_review" ? (
    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-600">
      pending review
    </span>
  ) : item.status === "rejected" ? (
    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/10 text-red-500">
      rejected
    </span>
  ) : null;

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
            {statusBadge}
            {showScore && item.score !== undefined && item.score > 0 && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 font-mono"
                title={`Search relevance: ${(item.score * 100).toFixed(1)}%`}
              >
                {(item.score * 100).toFixed(0)}% match
              </span>
            )}
          </div>
          <p className="text-sm t-primary leading-relaxed whitespace-pre-line">{item.content}</p>
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
