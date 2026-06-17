# Mini-OpenClaw Demo Script

**Target duration:** 5–8 minutes
**Format:** Screencast with voiceover

---

## Intro (30 seconds)

> "This is Mini-OpenClaw, a lightweight AI agent for local task execution. It takes natural-language instructions, creates a structured plan, validates each step against a security policy, and executes approved actions — all visible and auditable."

- Show the web UI with the chat panel open
- Briefly point out the sidebar navigation: Chat, History, Memory, Scheduler

---

## Architecture Overview (45 seconds)

> "Here's how it works. Natural language goes in. The active LLM provider — Claude, Gemini, or a local Ollama model — proposes one step at a time as structured JSON, using only registered tools. The policy engine classifies each step as safe, approval-required, or forbidden; the executor runs it; and the observation feeds back so the agent can continue, adapt, or replan. That's the hybrid Plan → ReAct → Replan loop. Every decision is logged."

- Show the architecture diagram (from the poster or docs/architecture.md)
- Highlight: planner → policy → executor → observation loop, with memory and audit around it

---

## Demo 1: Simple Question — No Tools (30 seconds)

**Type:** `What is a README file?`

> "For simple questions, the planner recognizes no tools are needed and responds directly."

- Show the plan preview with `task_type: direct_answer`
- Show the response in the chat

---

## Demo 2: Safe Tool — Auto-execution (1 minute)

**Type:** `What's in the workspace? Give me an overview`

> "When tools are needed, the planner creates a step-by-step plan. Here it selected `list_files`, which is classified as safe — so it auto-executes without needing approval."

- Show the plan preview with the `list_files` step
- Show the tool trace with execution results
- Point out the risk level badge: "Safe"

---

## Demo 3: Approval Flow (1.5 minutes)

**Type:** `Create a file called notes.txt with a summary of the project`

> "Now watch what happens with a write operation. The planner proposes `write_file`, but the policy engine flags it as approval-required because it modifies the filesystem."

- Show the plan preview with `write_file` step
- Show the approval card: tool name, arguments, risk level
- Point out that the exact content to be written is visible
- Click **Approve**

> "After approval, the tool executes and confirms the file was created. If I had rejected it, the run would have been cancelled — no file written."

- Show the success confirmation in chat

---

## Demo 4: Multi-step Plan (1 minute)

**Type:** `Read the README and search for any TODO items`

> "The planner can also create multi-step plans. Here it first reads the README file, then searches for TODO patterns — each step executes in sequence."

- Show the two-step plan in the plan preview
- Show each step completing one after the other
- Show the combined results

---

## Demo 5: Security Block (30 seconds)

**Type:** `Read the file /etc/passwd` (or `C:\Windows\System32\config\SAM` on Windows)

> "Security is enforced at every level. The policy engine detects this path is outside the workspace boundary and blocks the action immediately — the tool never executes."

- Show the policy denial in the plan / error display
- Point out the error code: `POLICY_DENIED`

---

## Demo 6: Memory System (1 minute)

**Type:** `Remember that this project uses FastAPI`

> "The agent can store durable facts in memory. This gets persisted in SQLite with provenance metadata."

- Show the confirmation in chat
- Switch to **Memory Browser** tab
- Show the stored fact with its source, confidence, and timestamp

> "These facts can be recalled in future conversations to give the agent context."

- Optionally: type a follow-up like `What do you know about this project?` to show retrieval

---

## Demo 7: Extensibility (45 seconds)

> "Adding a new tool requires zero changes to the core agent. You create a Python file implementing the BaseTool interface, define a manifest with schemas and risk level, and drop it into the skills directory."

- Open `apps/api/skills/list_files.py` briefly to show the structure
- Navigate to `http://localhost:8000/api/tools` in the browser
- Show all 13 registered tools in the JSON response

> "The skill registry auto-discovers tools at startup. The planner sees them automatically."

---

## Wrap-up (30 seconds)

> "To recap: Mini-OpenClaw demonstrates four core capabilities — intent-to-tool routing via a structured planner, auditable human-readable memory, manifest-driven extensibility, and safe local execution with policy enforcement and approval gates. Every decision in the pipeline is logged and inspectable."

> "Thanks for watching."

---

## Notes for Recording

- Use a clean workspace (run `python scripts/seed_demo.py` beforehand)
- Start with a fresh database so the memory browser starts empty
- Keep browser dev tools closed unless demonstrating audit logs
- Use a readable font size / zoom level
- Test all demo commands before recording to ensure they work
