/**
 * ExplainPanel — Expandable panel showing a causal explanation of an agent run.
 *
 * Fetches the explanation on demand when the user clicks "Explain this run".
 * Renders the markdown explanation with detail-level selector.
 */

import { useState, useCallback } from "react";
import { Lightbulb, Loader2, ChevronDown, ChevronRight, AlertCircle } from "lucide-react";
import { explainRun } from "../api/client";
import type { ExplainDetailLevel } from "../api/client";

interface ExplainPanelProps {
  runId: string;
  /** Compact mode shows just the button inline; full mode shows button + panel. */
  compact?: boolean;
}

export default function ExplainPanel({ runId, compact = false }: ExplainPanelProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [detailLevel, setDetailLevel] = useState<ExplainDetailLevel>("summary");

  const fetchExplanation = useCallback(
    async (level: ExplainDetailLevel) => {
      setLoading(true);
      setError(null);
      try {
        const result = await explainRun(runId, level);
        setExplanation(result.output?.explanation ?? "No explanation available.");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load explanation");
      } finally {
        setLoading(false);
      }
    },
    [runId]
  );

  const handleToggle = useCallback(() => {
    const next = !open;
    setOpen(next);
    if (next && !explanation && !loading) {
      fetchExplanation(detailLevel);
    }
  }, [open, explanation, loading, detailLevel, fetchExplanation]);

  const handleDetailChange = useCallback(
    (level: ExplainDetailLevel) => {
      setDetailLevel(level);
      fetchExplanation(level);
    },
    [fetchExplanation]
  );

  // Compact: just a small icon button
  if (compact) {
    return (
      <button
        onClick={handleToggle}
        className="p-1 rounded t-faint hover:text-amber-500 transition-colors"
        title="Explain this run"
      >
        <Lightbulb size={14} />
      </button>
    );
  }

  return (
    <div className="mt-2">
      {/* Toggle button */}
      <button
        onClick={handleToggle}
        className="flex items-center gap-1.5 text-xs t-muted hover:text-amber-500 transition-colors"
      >
        {loading ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Lightbulb size={12} />
        )}
        <span>Explain this run</span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {/* Explanation panel */}
      {open && (
        <div className="mt-2 border border-app rounded-md bg-app-secondary overflow-hidden">
          {/* Detail level selector */}
          <div className="flex items-center gap-1 px-3 py-1.5 border-b border-app bg-app-code">
            <span className="text-[10px] t-faint uppercase tracking-wider mr-1">
              Detail:
            </span>
            {(["summary", "detailed", "debug"] as ExplainDetailLevel[]).map(
              (level) => (
                <button
                  key={level}
                  onClick={() => handleDetailChange(level)}
                  disabled={loading}
                  className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                    detailLevel === level
                      ? "bg-amber-500/20 text-amber-600 font-medium"
                      : "t-faint hover:t-muted"
                  }`}
                >
                  {level}
                </button>
              )
            )}
          </div>

          {/* Content */}
          <div className="px-3 py-2.5 max-h-[400px] overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center py-6 t-muted">
                <Loader2 size={16} className="animate-spin" />
                <span className="ml-2 text-xs">Generating explanation…</span>
              </div>
            )}

            {error && (
              <div className="flex items-start gap-2 text-xs text-red-500 bg-red-500/10 px-2.5 py-2 rounded">
                <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {!loading && !error && explanation && (
              <div className="explain-content text-xs t-secondary leading-relaxed space-y-2">
                <MarkdownRenderer content={explanation} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Simple markdown renderer for the explanation output.
 * Handles headers, bold, code, lists, and horizontal rules.
 */
function MarkdownRenderer({ content }: { content: string }) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    key++;

    // H2
    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={key} className="text-[11px] font-semibold t-primary mt-3 mb-1 first:mt-0">
          {line.slice(3)}
        </h3>
      );
      continue;
    }

    // H3
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={key} className="text-[11px] font-medium t-primary mt-2 mb-0.5">
          {line.slice(4)}
        </h4>
      );
      continue;
    }

    // List item
    if (line.startsWith("- ") || line.startsWith("  - ")) {
      const indent = line.startsWith("  - ");
      const text = line.replace(/^(\s*- )/, "");
      elements.push(
        <div key={key} className={`flex gap-1 ${indent ? "ml-3" : ""}`}>
          <span className="t-faint flex-shrink-0">•</span>
          <span><InlineMarkdown text={text} /></span>
        </div>
      );
      continue;
    }

    // Code block markers
    if (line.startsWith("```")) {
      continue; // skip, handled inline
    }

    // Empty line → spacer
    if (line.trim() === "") {
      elements.push(<div key={key} className="h-1" />);
      continue;
    }

    // Italic line (starts with *)
    if (line.startsWith("*") && line.endsWith("*") && !line.startsWith("**")) {
      elements.push(
        <p key={key} className="italic t-faint">
          {line.slice(1, -1)}
        </p>
      );
      continue;
    }

    // Normal paragraph
    elements.push(
      <p key={key}>
        <InlineMarkdown text={line} />
      </p>
    );
  }

  return <>{elements}</>;
}

/** Render inline markdown: **bold**, `code`, and emojis. */
function InlineMarkdown({ text }: { text: string }) {
  // Split on bold and code markers
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    key++;

    // Bold
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    // Code
    const codeMatch = remaining.match(/`([^`]+)`/);

    // Find the earliest match
    const boldIdx = boldMatch?.index ?? Infinity;
    const codeIdx = codeMatch?.index ?? Infinity;

    if (boldIdx === Infinity && codeIdx === Infinity) {
      // No more matches
      parts.push(<span key={key}>{remaining}</span>);
      break;
    }

    if (boldIdx <= codeIdx && boldMatch) {
      // Bold comes first
      if (boldIdx > 0) {
        parts.push(<span key={key}>{remaining.slice(0, boldIdx)}</span>);
        key++;
      }
      parts.push(
        <strong key={key} className="font-medium t-primary">
          {boldMatch[1]}
        </strong>
      );
      remaining = remaining.slice(boldIdx + boldMatch[0].length);
    } else if (codeMatch) {
      // Code comes first
      if (codeIdx > 0) {
        parts.push(<span key={key}>{remaining.slice(0, codeIdx)}</span>);
        key++;
      }
      parts.push(
        <code key={key} className="bg-app-code px-1 py-0.5 rounded text-[10px] font-mono">
          {codeMatch[1]}
        </code>
      );
      remaining = remaining.slice(codeIdx + codeMatch[0].length);
    }
  }

  return <>{parts}</>;
}
