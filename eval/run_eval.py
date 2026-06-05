"""
eval/run_eval.py — Capability benchmark harness for the Mini-OpenClaw poster.

Runs the suite (eval/tasks.py) under three configurations that match the
poster's evaluation story, and reports the real numbers two ways:

    Baseline    plan-and-execute, no ReAct loop
    Plan+ReAct  pure ReAct loop, no goals / no replanning
    Full        hybrid goals + replanning + self-reflection

Aggregation:
    * by config      -> the three poster bar charts (success / tools / cost)
    * by capability  -> a matrix showing where each tier actually pays off
                        (recall, search, completeness, multi_step, recovery,
                         cross_file, memory, delegation)

Each (config, task) runs N reps (default 3) in a fully ISOLATED sandbox —
fresh temp workspace + fresh temp SQLite DB per trial — so accumulated
memory never biases later configs. Memory tasks seed a fact via a setup
message in the SAME trial DB, then ask a recall question.

Outputs (eval/results/):
    results.json            raw trials + both aggregations
    summary.csv             one row per config
    capability.csv          success% per capability per config
    poster_snippet.tex      \\addplot lines for the three charts
    capability_matrix.tex   LaTeX tabular: capability x config success%

Run from the REPO ROOT so ``apps.api`` resolves:

    # Windows PowerShell
    $env:LLM_PROVIDER = "anthropic"
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python -m eval.run_eval                         # all configs/tasks, 3 reps
    python -m eval.run_eval --reps 1 --tasks read_version   # cheap smoke test
    python -m eval.run_eval --configs baseline full         # skip the middle
    python -m eval.run_eval --capabilities recovery memory  # focus capabilities

Cost: ~14 tasks x 3 configs x 3 reps ~= 126 runs (memory tasks are 2-turn,
delegation may spawn children). Roughly USD 3-6 on Sonnet; near-free on
gemini-2.5-flash or a local Ollama model. Smoke-test cheap first.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import Settings
from apps.api.database import create_tables
from apps.api.core.orchestrator import Orchestrator
from apps.api.models.run import RunStatus
from apps.api.skills.registry import SkillRegistry

from eval.tasks import TASKS, Task


# ── Fixture workspace (ground truth — keep in sync with eval/tasks.py) ──

FIXTURE_FILES: dict[str, str] = {
    "README.md": (
        "# WeatherBot\n\n"
        "A command-line weather assistant built with Python and FastAPI.\n\n"
        "## Features\n"
        "- Fetch current weather by city name\n"
        "- 5-day forecast with hourly breakdown\n"
        "- Caching layer to reduce API calls\n"
        "- CLI and REST API interfaces\n\n"
        "## Version\n"
        "Current release: 0.3.1\n\n"
        "## Roadmap\n"
        "- Add wind speed and humidity to the forecast display\n"
    ),
    "config.json": (
        '{\n'
        '  "project": "weatherbot",\n'
        '  "version": "0.3.1",\n'
        '  "cache_ttl_seconds": 600,\n'
        '  "default_units": "metric"\n'
        '}\n'
    ),
    # Intentional mismatch vs config.json (cross_file task).
    "package.json": (
        '{\n'
        '  "name": "weatherbot",\n'
        '  "version": "0.2.0"\n'
        '}\n'
    ),
    # Decoy the agent must learn to ignore (recovery task).
    "version.txt": (
        "Deprecated build tag: 9.9.9\n"
        "This is NOT the real version. See config.json for the current release.\n"
    ),
    "src/main.py": (
        "def main():\n"
        "    # TODO: wire up the CLI argument parser\n"
        "    print('weatherbot')\n"
    ),
    "src/utils.py": (
        "def parse_units(value):\n"
        "    # FIXME: handle imperial units properly\n"
        "    return value\n"
    ),
    "src/api.py": (
        "def get_forecast(city):\n"
        "    # TODO: add retry on transient network errors\n"
        "    return {}\n"
    ),
    "tests/test_main.py": (
        "def test_smoke():\n"
        "    # TODO: replace with real assertions\n"
        "    assert True\n"
    ),
    "docs/architecture.md": (
        "# Architecture\n\nWeatherBot splits into a CLI layer and a REST API layer.\n"
    ),
}
# 4 .py files | TODO x3 (main, api, test_main) | FIXME x1 (utils)
# real version 0.3.1 | ttl 600 | package.json 0.2.0 | version.txt decoy 9.9.9


def build_fixture(dest: Path) -> None:
    for rel, content in FIXTURE_FILES.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


# ── Configurations under test ────────────────────────────────────────

CONFIGS: dict[str, dict] = {
    "baseline":   dict(use_react=False),
    "plan_react": dict(use_react=True, react_use_goals=False,
                       react_max_replans=0, react_self_reflect=False),
    "full":       dict(use_react=True, react_use_goals=True,
                       react_max_replans=2, react_self_reflect=True),
}
CONFIG_LABELS = {"baseline": "Baseline", "plan_react": "Plan+ReAct", "full": "Full"}


def make_settings(sandbox: Path, overrides: dict) -> Settings:
    base = dict(
        workspace_root=sandbox / "workspace",
        database_path=sandbox / "eval.db",
        clarification_enabled=False,      # never pause for a human mid-eval
        summary_interval=0,               # no cross-run summaries
        dream_interval=0,                 # no cross-run consolidation
        delegate_approval_required=False, # delegation must not block
        web_fetch_enabled=False,
        react_max_iterations=12,
    )
    base.update(overrides)
    return Settings(**base)


def count_tool_calls(run) -> int:
    obs = [o for o in run.observations if o.tool and o.tool != "final_answer"]
    if obs:
        return len(obs)
    if run.plan and run.plan.steps:
        return sum(1 for s in run.plan.steps if s.tool)
    return 0


async def run_one(task: Task, overrides: dict) -> dict:
    """One isolated trial: optional setup turns, then the measured prompt."""
    sandbox = Path(tempfile.mkdtemp(prefix="moc_eval_"))
    try:
        build_fixture(sandbox / "workspace")
        settings = make_settings(sandbox, overrides)
        await create_tables(settings.resolved_database)

        registry = SkillRegistry()
        registry.discover(settings=settings)
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        # Seed memory / context (not measured for cost or success).
        for msg in task.setup_messages:
            await orch.handle_message(
                session_id="eval", message=msg, workspace_id="default",
                pre_approved_tools=task.pre_approved)
            await orch.wait_pending()

        t0 = time.perf_counter()
        run = await orch.handle_message(
            session_id="eval", message=task.prompt, workspace_id="default",
            pre_approved_tools=task.pre_approved)
        await orch.wait_pending()
        latency = time.perf_counter() - t0

        run = await orch.get_run(run.run_id) or run
        completed = run.status == RunStatus.COMPLETED
        answer = (run.final_response or "").lower()
        try:
            verified = bool(task.verify(answer, settings.resolved_workspace))
        except Exception:
            verified = False

        return {
            "task": task.id, "capability": task.capability,
            "success": completed and verified,
            "completed": completed, "verified": verified,
            "tool_calls": count_tool_calls(run),
            "iterations": run.iterations,
            "cost_usd": round(run.usage.cost_usd, 6),
            "tokens": run.usage.total_tokens,
            "llm_calls": run.usage.llm_calls,
            "has_estimates": run.usage.has_estimates,
            "latency_s": round(latency, 2),
            "status": run.status.value,
        }
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ── aggregation ──────────────────────────────────────────────────────

def _rate(rows: list[dict]) -> float:
    return round(100 * sum(r["success"] for r in rows) / len(rows), 1) if rows else 0.0


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {
        "n_trials": len(rows),
        "success_rate_pct": _rate(rows),
        "avg_tool_calls": round(statistics.mean(r["tool_calls"] for r in rows), 2),
        "avg_iterations": round(statistics.mean(r["iterations"] for r in rows), 2),
        "avg_cost_usd": round(statistics.mean(r["cost_usd"] for r in rows), 5),
        "avg_tokens": round(statistics.mean(r["tokens"] for r in rows)),
        "avg_latency_s": round(statistics.mean(r["latency_s"] for r in rows), 2),
        "any_estimated_cost": any(r["has_estimates"] for r in rows),
    }


def write_poster_snippet(summary: dict[str, dict], out: Path) -> None:
    order = [c for c in ("baseline", "plan_react", "full") if c in summary]
    L = lambda c: CONFIG_LABELS[c]
    succ = " ".join(f"({L(c)},{summary[c]['success_rate_pct']})" for c in order)
    calls = " ".join(f"({L(c)},{summary[c]['avg_tool_calls']})" for c in order)
    scat = " ".join(f"({summary[c]['avg_cost_usd']},{summary[c]['success_rate_pct']})"
                    for c in order)
    out.write_text(
        "% Auto-generated by eval/run_eval.py — paste into \\EvaluationGraphs.\n"
        "% Chart 1 — Erfolgsrate (success %)\n"
        f"\\addplot+[ybar] coordinates {{{succ}}};\n\n"
        "% Chart 2 — Avg. Tool Calls per run\n"
        f"\\addplot+[ybar] coordinates {{{calls}}};\n\n"
        "% Chart 3 — Cost vs Success (x = cost USD, y = success %)\n"
        f"\\addplot+[only marks] coordinates {{{scat}}};\n",
        encoding="utf-8")


def write_capability_matrix(cap_by_config: dict[str, dict[str, float]],
                            configs: list[str], caps: list[str], out: Path) -> None:
    """LaTeX tabular: rows = capability, cols = config, cells = success%."""
    head = " & ".join(["Capability"] + [CONFIG_LABELS[c] for c in configs])
    lines = [
        "% Auto-generated capability matrix — success % per capability per config.",
        "\\begin{tabular}{l" + "r" * len(configs) + "}",
        "\\toprule",
        head + " \\\\",
        "\\midrule",
    ]
    for cap in caps:
        cells = [f"{cap_by_config.get(c, {}).get(cap, float('nan')):.0f}\\%"
                 if cap in cap_by_config.get(c, {}) else "--" for c in configs]
        lines.append(" & ".join([cap.replace("_", "\\_")] + cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser(description="Mini-OpenClaw capability benchmark")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--configs", nargs="*", default=list(CONFIGS), choices=list(CONFIGS))
    ap.add_argument("--tasks", nargs="*", default=None, help="subset of task ids")
    ap.add_argument("--capabilities", nargs="*", default=None,
                    help="subset by capability tag")
    args = ap.parse_args()

    tasks = list(TASKS)
    if args.tasks:
        tasks = [t for t in tasks if t.id in set(args.tasks)]
    if args.capabilities:
        tasks = [t for t in tasks if t.capability in set(args.capabilities)]
    if not tasks:
        print("No matching tasks.", file=sys.stderr); sys.exit(1)

    caps_present = sorted({t.capability for t in tasks})
    results: list[dict] = []
    summary: dict[str, dict] = {}
    cap_by_config: dict[str, dict[str, float]] = {}

    total = len(args.configs) * len(tasks) * args.reps
    done = 0
    print(f"Running {total} trials "
          f"({len(args.configs)} configs x {len(tasks)} tasks x {args.reps} reps)\n")

    for cfg in args.configs:
        cfg_rows: list[dict] = []
        for task in tasks:
            for rep in range(args.reps):
                done += 1
                print(f"[{done}/{total}] {CONFIG_LABELS[cfg]:11}| "
                      f"{task.capability:12}| {task.label}", flush=True)
                row = await run_one(task, CONFIGS[cfg])
                row["config"] = cfg; row["rep"] = rep
                results.append(row); cfg_rows.append(row)
                print(f"          -> {'ok ' if row['success'] else 'MISS'} "
                      f"tools={row['tool_calls']} cost=${row['cost_usd']:.4f} "
                      f"{row['latency_s']}s", flush=True)
        summary[cfg] = aggregate(cfg_rows)
        cap_by_config[cfg] = {
            cap: _rate([r for r in cfg_rows if r["capability"] == cap])
            for cap in caps_present
        }

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(
        {"summary": summary, "capability_by_config": cap_by_config,
         "trials": results}, indent=2), encoding="utf-8")

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["config", "n_trials", "success_rate_pct", "avg_tool_calls",
                    "avg_iterations", "avg_cost_usd", "avg_tokens",
                    "avg_latency_s", "cost_estimated"])
        for cfg in args.configs:
            s = summary[cfg]
            w.writerow([CONFIG_LABELS[cfg], s["n_trials"], s["success_rate_pct"],
                        s["avg_tool_calls"], s["avg_iterations"], s["avg_cost_usd"],
                        s["avg_tokens"], s["avg_latency_s"], s["any_estimated_cost"]])

    with (out_dir / "capability.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["capability"] + [CONFIG_LABELS[c] for c in args.configs])
        for cap in caps_present:
            w.writerow([cap] + [cap_by_config[c][cap] for c in args.configs])

    write_poster_snippet(summary, out_dir / "poster_snippet.tex")
    write_capability_matrix(cap_by_config, args.configs, caps_present,
                            out_dir / "capability_matrix.tex")

    # Printed: by-config table
    print("\n" + "=" * 70)
    print(f"{'Config':12}{'Success%':>10}{'Tools/run':>11}{'Cost/run':>11}{'Tokens':>9}")
    print("-" * 70)
    for cfg in args.configs:
        s = summary[cfg]
        print(f"{CONFIG_LABELS[cfg]:12}{s['success_rate_pct']:>10}"
              f"{s['avg_tool_calls']:>11}{('$'+format(s['avg_cost_usd'],'.4f')):>11}"
              f"{s['avg_tokens']:>9}")
    # Printed: capability matrix
    print("\n" + "-" * 70)
    print(f"{'Capability':14}" + "".join(f"{CONFIG_LABELS[c]:>14}" for c in args.configs))
    print("-" * 70)
    for cap in caps_present:
        print(f"{cap:14}" + "".join(f"{cap_by_config[c][cap]:>13}%" for c in args.configs))
    print("=" * 70)
    if any(summary[c]["any_estimated_cost"] for c in args.configs):
        print("NOTE: some costs are heuristic estimates (provider returned no usage).")
    print(f"\nWrote results.json, summary.csv, capability.csv, poster_snippet.tex, "
          f"capability_matrix.tex to {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
