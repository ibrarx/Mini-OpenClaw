# Mini-OpenClaw — Unified Test & Evaluation Harness

This folder combines both developer correctness regression tests (previously `tests/llm_harness_test/`) and the scientific poster benchmarks (previously `eval/`) into a single consolidated directory under `tests/eval/`.

## Structure

* **`tasks.py`**: Programmatically defines all 29 tasks (14 evaluation tasks + 15 regression tasks) with unique IDs, capability categories, prompts, pre-approved tool manifests, and deterministic Python verifiers.
* **`mocks.py`**: A shared testing utility containing safe shell execution mocking (`RunShellSafeTool`) and Gemini JSON generation monkey-patches to prevent model escaping syntax issues (`\'` parsing errors).
* **`run_suite.py`**: Unified suite runner script.

---

## How to Run

Run the suite from the repository root:

### Mode A: Verification (Fast Developer Regression Check)
Verify that all 29 tasks complete successfully against the default active configuration:
```bash
PYTHONPATH=. python tests/eval/run_suite.py --mode verify
```
* Runs each task once.
* Verifies both orchestrator execution success and response accuracy via the python verifiers.
* **Exit code**: Returns `0` on success, or `1` on any failure (suitable for CI/CD pipelines and git pre-commit hooks).

### Mode B: Benchmarking (Poster / Evaluation Stats)
Benchmark different agent configurations sequentially and generate metrics:
```bash
PYTHONPATH=. python tests/eval/run_suite.py --mode benchmark --reps 3
```
* Runs the tasks across three agent configuration tiers (see [Agent Configurations](#agent-configurations) below):
  * **Baseline** (`use_react=False`)
  * **Plan+ReAct** (`use_react=True` but no goals/reflection)
  * **Full** (hybrid ReAct with goal tracking, replanning, and self-reflection)
* Outputs summary CSV tables, raw results, and LaTeX charts (`\addplot` bar charts coordinates and capability tabular matrix) to `tests/eval/results/`.

---

## Filters

You can filter which tasks to run using `--tasks` or `--capabilities`:
```bash
# Smoke test a single task
PYTHONPATH=. python tests/eval/run_suite.py --mode verify --tasks read_version

# Verify only memory and recovery capabilities
PYTHONPATH=. python tests/eval/run_suite.py --mode verify --capabilities memory recovery

# Run benchmark for just the full configuration
PYTHONPATH=. python tests/eval/run_suite.py --mode benchmark --configs full --reps 1
```

---

## Agent Configurations

The benchmark compares the following agent execution paradigms implemented in the orchestrator:

* **Baseline (`use_react=False`)**:
  * **Pathway**: Uses the legacy upfront plan-and-execute pathway (`_plan_and_execute` in [orchestrator.py](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/apps/api/core/orchestrator.py#L1621-L1660)).
  * **Mechanism**: Generates a complete sequence of planned step actions and tools at the start of execution. It executes these steps sequentially.
  * **Limitations**: Highly rigid; cannot dynamically adapt to unexpected tool failures, changing workspace states, or intermediate discovery results.

* **Plan+ReAct (`use_react=True`, without advanced features)**:
  * **Pathway**: Iterative **Reasoning and Acting (ReAct)** loop (`_react_loop` in [orchestrator.py](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/apps/api/core/orchestrator.py#L441-L450)).
  * **Mechanism**: Runs a dynamic **think &rarr; act &rarr; observe** loop. The agent evaluates the outcome of each tool execution before selecting the next action.
  * **Settings**: `react_use_goals=False`, `react_max_replans=0`, and `react_self_reflect=False`.
  * **Limitations**: Lacks explicit milestone/goal tracking or structured progress checklists.

* **Full (`use_react=True`, with advanced features)**:
  * **Pathway**: Enhanced ReAct loop with goal tracking, self-reflection, and replanning.
  * **Mechanism**:
    * **Goal Checklists**: Dynamically plans and tracks progress via explicit sub-goals (`react_use_goals=True`).
    * **Dynamic Replanning**: Allows the agent to pause, revise, and re-architect its goals up to 2 times mid-execution (`react_max_replans=2`) when encountering errors.
    * **Self-Reflection**: Prompts the LLM to verify if its final solution matches the original requirements before terminating (`react_self_reflect=True`).

---

## Execution Policies & Assumptions

To ensure deterministic, safe, and fast test execution in a non-interactive environment, the evaluation suite relies on the following configured behaviors and mocked conditions:

1. **Trial-Level Timeout Limit (`90s`)**:
   To prevent the orchestrator or agent config from stalling indefinitely (e.g. loops on hard reasoning paths or failing tools), each trial is executed with a hard **90-second timeout** in [run_suite.py](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/tests/eval/run_suite.py) via `asyncio.wait_for`. Timed-out runs are recorded as `TIMEOUT`, failed, and skipped to allow subsequent runs to proceed.

2. **Automatic Tool Approvals**:
   Normally, high-risk tools (like shell execution) pause execution to wait for user confirmation. To support non-interactive benchmark runs, [mocks.py](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/tests/eval/mocks.py) monkey-patches [PolicyEngine.classify_tool](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/apps/api/core/policy.py#L125-L133) to automatically classify every tool call as `"safe"` and auto-approved, bypassing prompt blocks.

3. **Recursive Search Walk Depth (`5`)**:
   By default, the recursive file-listing operation performed by [ListFilesTool](file:///Users/johannes/VSCodeProjects/Mini-OpenClaw/apps/api/skills/list_files.py) walks to a maximum directory depth of `5` levels. This ensures nested files (such as `src/backend/auth_service.py`) are successfully found in the sandbox environment without exceeding ordinary tool limits or getting trapped in extremely deep recursive directories.


