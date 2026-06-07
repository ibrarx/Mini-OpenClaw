# Mini-OpenClaw Project-Description

## Meta data:

* **Title**: Mini-OpenClaw
* **Version**: 0.1.0
* **Group**: Gruppe 09
* **Authors**: 
- Held Johannes (11705340 / e11705340@student.tuwien.ac.at), Ibrahim Ahmad (11826186 / e11826186@student.tuwien.ac.at), Ibrar Muhammad ([STUDENT-ID] / [EMAIL_ADDRESS]), Bourbigua Manal ([STUDENT-ID] / [EMAIL_ADDRESS])
* **Project Status**: Ongoing
* **Course**: 194.211 Applied Generative AI and LLM-based Systems, TU Wien

## 1. Project Overview

Mini-OpenClaw is a lightweight, local-first AI agent designed to convert natural-language requests into safe, auditable tool executions on a local machine. Developed as a course project for "Applied Generative AI" at TU Wien, it emphasizes auditable, inspectable pipelines for agent-based interactions.

Its core philosophy revolves around a "Hybrid Plan → ReAct → Replan" architecture, which allows the LLM to generate a goal checklist, execute actions in a ReAct loop (reason → act → observe), and dynamically replan if progress stalls or goals are skipped.

## 2. Architecture

The project follows a client-server architecture with a clear separation between a FastAPI backend and a React/TypeScript frontend.

*   **Backend (`apps/api/`):**
    *   Built with FastAPI, serving as the main API for agent operations.
    *   **Core Components:** Houses the Orchestrator, Planner, Policy Engine, Executor, Audit Logger, Memory Manager, and Task Scheduler.
    *   **LLM Provider Abstraction:** Supports various LLMs (Anthropic, Google Gemini, Ollama) through a pluggable provider interface.
    *   **Skills (Tools):** A registry of available tools that the agent can execute.
    *   **Memory System:** Manages different types of memory (facts, episodes, summaries, strategies, preferences) with hybrid semantic search.
    *   **Database:** Uses SQLite for persistent storage of runs, memory items, and scheduled tasks.
    *   **Entry Point:** `apps/api/main.py` initializes the FastAPI app, configures CORS, logging, registers routes, and sets up the database and skill registry.

*   **Frontend (`apps/web/`):**
    *   A React application built with TypeScript, providing a user interface for interacting with the agent.
    *   It offers real-time Server-Sent Events (SSE) streaming for run status, plans, and approvals.
    *   Key UI components include ChatPanel, PlanPreview, ExecutionGraph, ApprovalCard, ToolTrace, RunHistory, MemoryBrowser, and SchedulerPage.
    *   **Entry Point:** `apps/web/src/main.tsx` renders the main React application.

## 3. Key Features

Mini-OpenClaw includes a comprehensive set of features designed for robust and transparent agent operation:

*   **Sub-agent Delegation:** Complex tasks can be decomposed and delegated to child runs, each handled by a focused sub-agent.
*   **Confidence-gated Clarification:** The agent can ask clarifying questions when unsure about user intent, pausing execution until a clear response is provided.
*   **Scheduled Tasks:** Supports one-time or recurring tasks via a heap-based scheduler, with options for advance approval or per-run approval.
*   **Hybrid Plan-ReAct with Replanning:** Generates a goal checklist before execution and can dynamically replan if the initial plan goes off-track.
*   **ReAct Loop:** Standard think → act → observe loop for iterative reasoning and real-time adaptation.
*   **Real-time SSE Streaming:** Provides instant updates to the frontend without polling.
*   **User-friendly Status Announcements:** Narrates agent actions in plain language while maintaining full tool traceability.
*   **Hybrid Semantic Memory:** Combines vector similarity and keyword matching for effective memory retrieval across three layers: durable facts, episodic task history, and conversation summaries.
*   **Agent Dreams:** A post-run memory consolidation process that proposes workflow strategies and user preferences for review.
*   **Saga Compensation:** Automatically rolls back previous write operations if a step is rejected.
*   **Budget-aware Planning:** The agent works strategically within an iteration budget, with UI feedback on consumption.
*   **Graceful Max-Iterations Degradation:** Synthesizes an answer from collected evidence if the iteration budget is exhausted.
*   **Error Classification:** Retries transient errors, feeds permanent errors to the LLM, and surfaces side-effect errors to the user.
*   **Self-reflection Quality Gate:** Optional critique step where the agent scores its own final answer and takes corrective action if needed.
*   **Retry Failed Runs:** A one-click option to retry failed or canceled runs.
*   **Execution Graph:** A real-time DAG visualization of run execution flow in the UI.
*   **Run Explanations:** Generates causal narratives for completed runs at various detail levels.
*   **LLM-Provider-Agnostic:** Easily swap between Anthropic, Gemini, or Ollama.
*   **Manifest-driven Tool Extensibility:** New tools can be added without modifying core agent logic.
*   **Multi-layer Security:** Policy engine, command allowlists, and approval gates.
*   **Named Directory Mounts:** Allows the agent to access additional directories beyond the primary workspace with configurable permissions.
*   **Runtime Web Fetch:** `fetch_url` tool retrieves live data from the public web with security guardrails.
*   **Full Audit Trail:** Every decision is logged in an append-only audit table.

## 4. How it Works (Execution Flow)

Every user request initiates a "run." The execution flow involves several key components:

1.  **User Message:** The initial request from the user.
2.  **Orchestrator:** Manages the overall run, coordinating between different components.
3.  **Planner:** In a ReAct step, it reasons about observations and picks the next action (tool call or final answer). It can also generate a goal checklist (`REACT_USE_GOALS=true`).
4.  **Policy Engine:** Validates every proposed action against security policies (safe / approval-required / forbidden).
5.  **Executor:** Executes the validated actions/tools, handles retries for transient errors, and generates observations.
6.  **Memory Manager:** Persists useful context and handles retrieval for the planner.
7.  **Audit Logger:** Records every decision and action in an append-only log.
8.  **Event Emitter:** Pushes real-time status updates via Server-Sent Events (SSE) to connected frontends.
9.  **Loop & Outcome:** The process continues in a ReAct loop until a final answer is generated or the iteration budget is exhausted. Replanning can occur if the goals go off-track.

## 5. Memory System

Mini-OpenClaw features a sophisticated five-layer memory system, underpinned by hybrid semantic search, designed to enable the agent to remember user preferences, learn from past tasks, discover workflow patterns, and build up context over time.

### Memory Types

The system categorizes memory into five distinct types:

*   **Facts:** These are durable user or workspace preferences, typically stored via the `remember_fact` tool. Examples include "User prefers VS Code" or "Project uses PostgreSQL." Facts persist until manually deleted.
*   **Episodes:** Each completed task generates an episode, recording the tools used, the actions taken, and their outcomes. These accumulate indefinitely, providing a historical trace of agent activity.
*   **Summaries:** Automatically generated by an LLM every N runs (configurable via `SUMMARY_INTERVAL`, default: 5), summaries provide compressed overviews of recent interactions. The system retains the `MAX_SUMMARIES` most recent summaries (default: 3).
*   **Strategies:** These represent recurring workflow patterns discovered by the "Agent Dreams" process. Examples include "User typically lists files before reading them" or "User searches for TODOs before writing reports." Strategies must be confirmed by the user before they influence future planning.
*   **Preferences:** Similar to strategies, these are inferred user or project traits (e.g., "User's project uses Python with pytest, source in src/"), also proposed by Agent Dreams and user-confirmed.

### Agent Dreams — Memory Consolidation

"Agent Dreams" is a post-run memory consolidation process inspired by how sleep helps humans consolidate learning. After a configurable number of completed runs (`DREAM_INTERVAL`, default: 5), the agent analyzes its recent episodes to propose higher-level insights: strategies and preferences.

This process involves a **user review flow** for proposed insights:
1.  **Extraction:** The dream cycle extracts candidate strategies and preferences, storing them as `pending_review`.
2.  **Review:** Pending insights appear as interactive cards in the Memory Browser, offering "Accept," "Dismiss," and "Edit & Accept" options.
3.  **Activation:** Accepted insights are promoted to `active` status and are subsequently included in the planner's context for future runs.
4.  **Rejection:** Dismissed insights are marked `rejected` and excluded from future dream proposals.

This design adheres to the "propose → review → approve" philosophy, ensuring the agent never acts on inferred knowledge without user consent. Only insights with an LLM confidence score above `DREAM_CONFIDENCE_THRESHOLD` (default: 0.6) are proposed.

### Hybrid Search (Semantic + Keyword)

Memory retrieval employs a hybrid approach, combining:

*   **70% Vector Similarity:** Text is embedded using the `all-MiniLM-L6-v2` model (a 384-dimensional model running locally on CPU, incurring no API cost). These embeddings are then compared via cosine similarity to find semantically related memories.
*   **30% Keyword Matching:** This component utilizes traditional SQL `LIKE`-based word overlap searches for direct keyword matches.

This hybrid approach ensures that search queries for terms like "what IDE" can successfully retrieve facts such as "User prefers VS Code as their editor," demonstrating effective semantic matching even when lexical overlap is absent. The Memory Browser UI allows users to switch between Hybrid, Keyword, and Vector modes to compare search results.

### How Memory Flows into the Planner

Before every planning or reasoning call, the orchestrator constructs a structured context block for the LLM. This block dynamically integrates relevant information from the memory system:

```
## Known Facts About User
- Preferred editor: VS Code
- Project uses PostgreSQL

## Known Strategies (how the user works)
- User typically lists files before reading them
- User searches for TODOs before writing reports

## Inferred Preferences
- User's project uses Python with pytest, source in src/

## Relevant Past Context
- [2 hours ago] Listed files in workspace — found 12 Python files
- [yesterday] User asked to summarize README.md — created summary.txt

## Conversation Summary
User is working on a thesis project involving NLP. Prefers concise responses.
```

This context is then explicitly injected into the LLM's system prompt with instructions to utilize it. This mechanism prevents the agent from asking questions to which it already knows the answer and allows it to leverage learned strategies and preferences. Only `active` strategies and preferences are included in this context.

## 6. Tooling (Skills)

The agent interacts with the environment through a set of "skills" (tools), managed by a `SkillRegistry`. New tools can be added via a manifest-driven extensibility model.

Currently available tools include:

*   `list_files`: Lists files and directories.
*   `read_file`: Reads content from text files.
*   `write_file`: Creates, overwrites, or appends to files (requires approval).
*   `search_in_files`: Searches for patterns within files.
*   `run_shell_safe`: Executes allowlisted shell commands (requires approval).
*   `remember_fact`: Stores durable facts in memory.
*   `search_memory`: Queries stored memory.
*   `delegate_task`: Spawns sub-agents for independent sub-tasks (requires approval).
*   `fetch_url`: Retrieves content from public URLs with security checks (requires approval).
*   `schedule_task`: Schedules one-time or recurring tasks.
*   `explain_run`: Provides explanations for past runs.

Each tool has a defined risk level, and risky operations require explicit user approval.

## 7. Security Model

Mini-OpenClaw employs a multi-layer security model:

1.  **Registered Tools:** Only tools explicitly registered with valid JSON schemas can be referenced.
2.  **Policy Engine:** Enforces workspace path boundaries, allowlists shell commands, and detects injection attempts.
3.  **Approval Gates:** Risky actions (e.g., `write_file`, `run_shell_safe`, `fetch_url`, `delegate_task`) require explicit user approval.
4.  **Audit Log:** An append-only log records every decision and action for traceability.

Further details are available in `docs/threat-model.md`.

## 8. Frontend

The React/TypeScript frontend provides a rich interactive experience. It visualizes the agent's progress, displays the execution graph, manages scheduled tasks, allows memory browsing, and handles user approvals for agent actions. It connects to the FastAPI backend using Server-Sent Events (SSE) for real-time updates.

### UI content updates
- **AI disclaimer**: A persistent, muted notice below the chat input reminds users that Mini-OpenClaw is AI-powered and that they should review proposed steps before approving.
- **Mount-aware example commands**: The empty-state now shows five workspace-centric base commands plus one additional command per configured named mount (fetched from `/api/health`). Read-only mounts only generate read/summarize commands.
- **Workspace helper line**: A short helper line below "Send a message to get started" explains that "the workspace" is the set of files the agent can read and work on.