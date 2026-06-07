# CHANGES.md — Feedback and Changes Log

## Feedback Received During Poster Session

| # | Feedback | From | Action Taken | Rationale |
|---|----------|------|--------------|-----------|
| 1 | _"Consider adding..."_ | Peer reviewer | Implemented / Not implemented | _Reason_ |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

## Changes Made After Poster Session

### Change 1: UI content updates — AI disclaimer, mount-aware examples, workspace helper
- **What changed:** Added an always-visible AI disclaimer below the chat input bar. Replaced the five hardcoded empty-state example commands with five workspace-centric base commands plus dynamically generated commands for each configured named mount (fetched from `/api/health`). Added a one-line workspace helper explaining what "the workspace" means. Widened the `healthCheck()` return type in the API client to include mount metadata.
- **Why:** Improve first-time user experience and clarify the agent's operating context. Mount-aware commands prevent "unknown mount alias" errors when mounts are not configured, and surface mount-specific commands when they are.
- **Files affected:** `apps/web/src/components/ChatPanel.tsx`, `apps/web/src/api/client.ts`, `apps/web/src/components/Settings.tsx`, `README.md`, `docs/demo-script.md`, `project_docs/project_status.md`, `CHANGES.md`

### Change 2: [Title]
- **What changed:** _description_
- **Why:** _feedback reference or own improvement_
- **Files affected:** _list_

## Feedback Not Incorporated

| # | Feedback | Reason |
|---|----------|--------|
| 1 | | |
| 2 | | |
