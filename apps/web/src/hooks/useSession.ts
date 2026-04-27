/**
 * Session management hook.
 * Generates a session_id and persists it in localStorage.
 */

import { useState } from "react";

function generateSessionId(): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).substring(2, 8);
  return `sess_${ts}_${rand}`;
}

const STORAGE_KEY = "mini-openclaw-session-id";

export function useSession() {
  const [sessionId] = useState<string>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    const id = generateSessionId();
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  });

  const resetSession = () => {
    const id = generateSessionId();
    localStorage.setItem(STORAGE_KEY, id);
    window.location.reload();
  };

  return { sessionId, resetSession };
}
