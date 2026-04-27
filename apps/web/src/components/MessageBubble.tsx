/**
 * MessageBubble — renders a single chat message.
 * User messages: right-aligned with accent. Assistant: left-aligned. System: centered/muted.
 */

import { Bot, User, Info } from "lucide-react";
import type { ChatMessage } from "../api/types";

interface MessageBubbleProps {
  message: ChatMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const { role, content, timestamp } = message;

  if (role === "system") {
    return (
      <div className="flex justify-center my-2 animate-fade-in">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-800/60 border border-gray-700/50 text-xs text-gray-400">
          <Info size={12} />
          <span>{content}</span>
        </div>
      </div>
    );
  }

  const isUser = role === "user";

  return (
    <div
      className={`flex gap-2.5 animate-slide-up ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5 ${
          isUser
            ? "bg-blue-600/20 text-blue-400"
            : "bg-emerald-600/20 text-emerald-400"
        }`}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[75%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600/15 border border-blue-500/20 text-gray-100"
            : "bg-gray-800/80 border border-gray-700/50 text-gray-200"
        }`}
      >
        <div className="whitespace-pre-wrap break-words">{content}</div>
        <div
          className={`text-[10px] mt-1.5 ${
            isUser ? "text-blue-400/50 text-right" : "text-gray-500"
          }`}
        >
          {formatTime(timestamp)}
        </div>
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}
