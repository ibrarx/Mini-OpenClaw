# Screencast Recording Script — Mini-OpenClaw (Group 09)

**Target length:** 3–5 minutes  
**Tool:** OBS Studio, QuickTime, or PowerPoint screen recording  
**Resolution:** 1920×1080 recommended  

---

## Shot 1 — Intro (0:00–0:15)

**Show:** The poster PDF (page 1) or the running UI landing page.  
**Say:**  
> "Mini-OpenClaw is a local-first AI agent that turns plain-language requests into safe, auditable tool executions on your own machine. It's built with FastAPI, React, and supports Anthropic, Gemini, and Ollama as LLM providers."

---

## Shot 2 — Setup demo (0:15–0:45)

**Show:** Terminal + file explorer side by side.

1. Show `.env.example` → copy to `.env` → fill in one API key
2. Run `pip install -r requirements.txt` (show it finishing, or fast-forward)
3. Run `npm install` in `apps/web/` (fast-forward)
4. Start backend: `python -m uvicorn apps.api.main:app --port 8000`
5. Start frontend: `cd apps/web && npm run dev`
6. Show browser loading `localhost:5173`

**Say:**  
> "Setup is straightforward — copy the env file, install dependencies, and start both servers. No Docker, no cloud — everything runs locally."

---

## Shot 3 — Core loop: multi-step request (0:45–1:45)

**Show:** The Chat UI in the browser.

1. Type: *"List all Python files in the workspace, find any with TODO comments, and create a summary file"*
2. Show the plan appearing with step-by-step breakdown
3. Point out the ReAct loop iterations in the execution graph
4. When `write_file` triggers → show the **approval card** appearing
5. Click **Approve**
6. Show the final answer with the created file

**Say:**  
> "Here's a multi-step request. The planner breaks it into individual tool calls. Read operations execute automatically, but writing a file requires explicit approval. The ReAct loop adapts if any step fails."

---

## Shot 4 — Tool showcase (1:45–2:45)

Show 3–4 quick tool demos back to back:

1. **get_datetime:** *"What time is it in Tokyo?"* → instant answer
2. **calculator:** *"Calculate compound interest on $10,000 at 5% for 10 years"* → shows calculation
3. **remember_fact + search_memory:** *"Remember that the project deadline is July 1st"* → then *"When is the project deadline?"* → agent recalls the fact
4. **delegate_task** (if time allows): *"Read all files and generate a project overview, delegating the summary to a sub-agent"* → show child run spawning

**Say:**  
> "The agent has 13 built-in tools plus MCP integration. Here's datetime, calculation, and the memory system — facts persist across sessions."

---

## Shot 5 — Security (2:45–3:15)

1. Type: *"Run rm -rf /"* → show **forbidden** response (policy engine blocks it)
2. Type: *"Create a file called test.txt with hello world"* → show the approval card with the exact args displayed → approve it → file created

**Say:**  
> "The policy engine classifies every action. Dangerous shell commands are outright forbidden. File writes require approval, and the approval is tied to the exact payload — if the args change, the approval is invalidated."

---

## Shot 6 — Memory & Reflection (3:15–3:45)

1. Click **Memory** tab → show facts, episodes, summaries, strategies
2. Show the **Agent Dreams** section if insights have been generated
3. Click **History** tab → show a past run → click into it to show the trace

**Say:**  
> "Everything is auditable. The memory browser shows five layers of context. Agent Dreams consolidate patterns into proposed strategies. Every run is inspectable in the history view."

---

## Shot 7 — Eval results & close (3:45–4:00)

**Show:** The poster page 3 (results section) or the eval harness terminal output.

**Say:**  
> "We evaluated across 14 deterministic tasks. The full hybrid loop achieves 95% success — a significant jump over the 44% baseline — at the cost of more tool calls per run. The eval uses no LLM-as-judge, only deterministic verifiers. Thank you."

---

## Tips
- **Pre-warm the workspace** with a few files and some stored memory so demos are instant
- Use `scripts/seed_demo.py` if available to populate demo data
- Keep the terminal visible for backend logs during tool execution — evaluators like seeing the audit trail
- If a demo stalls (LLM latency), narrate what's happening: "The agent is calling Claude for the next step"
