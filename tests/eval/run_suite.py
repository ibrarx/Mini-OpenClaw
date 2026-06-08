"""
tests/eval/run_suite.py — Consolidated test and evaluation runner.

Supports two modes:
  1. Verify (CI/CD / Developer check):
     python -m tests.eval.run_suite --mode verify
     Runs all tasks once, verifying both completion and correctness.
     Exits with status 0 on success, or 1 on any failure.
     
  2. Benchmark (Research / Poster stats):
     python -m tests.eval.run_suite --mode benchmark --reps 3
     Runs sequential benchmarks across Baseline, Plan+ReAct, and Full tiers.
     Generates summary reports and LaTeX charts in tests/eval/results/.
"""
from __future__ import annotations

import os
import sys
import time
import json
import csv
import shutil
import argparse
import asyncio
import tempfile
import statistics
from pathlib import Path
from datetime import datetime

# Disable HuggingFace online validation checks and warning noises
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Resolve repo root and insert to sys.path
script_path = Path(__file__).resolve()
project_root = script_path.parents[2]
sys.path.insert(0, str(project_root))

from apps.api.config import get_settings, Settings
from apps.api.database import create_tables
from apps.api.core.orchestrator import Orchestrator
from apps.api.models.run import RunStatus
from apps.api.skills.registry import SkillRegistry

from tests.eval.tasks import TASKS, Task, build_fixture
import tests.eval.mocks as mocks

# Apply safe monkey-patches globally
mocks.apply_monkey_patches()


# ── Benchmark Configs ────────────────────────────────────────────────

CONFIGS: dict[str, dict] = {
    "baseline":   dict(use_react=False),
    "plan_react": dict(use_react=True, react_use_goals=False,
                       react_max_replans=0, react_self_reflect=False),
    "full":       dict(use_react=True, react_use_goals=True,
                       react_max_replans=2, react_self_reflect=True),
}
CONFIG_LABELS = {"baseline": "Baseline", "plan_react": "Plan+ReAct", "full": "Full"}

ESTIMATES = {
    "recall": "10s",
    "search": "20s",
    "completeness": "25s",
    "delegation": "25s",
    "multi_step": "30s",
    "recovery": "35s",
    "cross_file": "20s",
    "memory": "10s"
}


def make_settings(sandbox: Path, overrides: dict) -> Settings:
    # Build settings using values from apps.api.config.get_settings()
    active_settings = get_settings()
    
    settings_dict = active_settings.model_dump()
    settings_dict.update({
        "workspace_root": sandbox / "workspace",
        "database_path": sandbox / "eval.db",
        "clarification_enabled": False,       # never pause for user input during trials
        "summary_interval": 0,                # isolate memory
        "dream_interval": 0,
        "delegate_approval_required": False,  # non-interactive
        "web_fetch_enabled": False,
        "react_max_iterations": 12,
    })
    settings_dict.update(overrides)
    return Settings(**settings_dict)


def count_tool_calls(run) -> int:
    obs = [o for o in run.observations if o.tool and o.tool != "final_answer"]
    if obs:
        return len(obs)
    if run.plan and run.plan.steps:
        return sum(1 for s in run.plan.steps if s.tool)
    return 0


async def run_one(task: Task, overrides: dict) -> dict:
    """Run one isolated trial sandbox."""
    sandbox = Path(tempfile.mkdtemp(prefix="moc_eval_"))
    
    # Reset mock states before trial
    mocks.reset_mock_states()
    
    t_start = time.perf_counter()
    try:
        setup_git = (task.id == "multi_step_3" or "git" in task.prompt.lower())
        build_fixture(sandbox / "workspace", setup_git=setup_git)
        settings = make_settings(sandbox, overrides)
        await create_tables(settings.resolved_database)

        registry = SkillRegistry()
        registry.discover(settings=settings)
        
        orch = Orchestrator(settings, registry)
        await orch.initialize_memory()

        all_tool_names = [t.name for t in registry.list_tools()]

        # Seed memory / context (not measured for cost or latency)
        for msg in task.setup_messages:
            await orch.handle_message(
                session_id="eval", message=msg, workspace_id="default",
                pre_approved_tools=all_tool_names)
            await orch.wait_pending()

        t0 = time.perf_counter()
        trial_timeout = 90.0
        
        async def execute_task():
            r = await orch.handle_message(
                session_id="eval", message=task.prompt, workspace_id="default",
                pre_approved_tools=all_tool_names)
            await orch.wait_pending()
            return r
            
        try:
            run = await asyncio.wait_for(execute_task(), timeout=trial_timeout)
            latency = time.perf_counter() - t0
            run = await orch.get_run(run.run_id) or run
            completed = run.status == RunStatus.COMPLETED
            answer = (run.final_response or "").lower()
        except asyncio.TimeoutError:
            latency = time.perf_counter() - t0
            return {
                "task": task.id,
                "capability": task.capability,
                "success": False,
                "completed": False,
                "verified": False,
                "tool_calls": 0,
                "iterations": 0,
                "cost_usd": 0.0,
                "tokens": 0,
                "llm_calls": 0,
                "has_estimates": False,
                "latency_s": round(latency, 2),
                "status": "TIMEOUT",
                "error": f"Task execution timed out after {trial_timeout}s",
                "tools_used": [],
                "final_response": "Task execution timed out.",
                "history": [],
                "reflection": None,
            }
        
        try:
            verified = bool(task.verify(answer, settings.resolved_workspace))
        except Exception:
            verified = False

        tools_used = [o.tool for o in run.observations if o.tool is not None]
        
        history = []
        for obs in run.observations:
            step = {
                "iteration": obs.iteration,
                "thought": obs.reasoning,
                "tool": obs.tool,
                "args": obs.args,
            }
            if obs.result:
                step["result_status"] = obs.result.status
                step["result_output"] = obs.result.output
                step["result_error"] = obs.result.error
            history.append(step)

        reflection_details = None
        if run.reflection:
            reflection_details = {
                "overall_score": run.reflection.overall_score,
                "completeness": run.reflection.completeness,
                "accuracy": run.reflection.accuracy,
                "clarity": run.reflection.clarity,
                "issues": run.reflection.issues,
                "suggestion": run.reflection.suggestion,
                "improved": run.reflection.improved,
            }

        return {
            "task": task.id,
            "capability": task.capability,
            "success": completed and verified,
            "completed": completed,
            "verified": verified,
            "tool_calls": count_tool_calls(run),
            "iterations": run.iterations,
            "cost_usd": round(run.usage.cost_usd, 6),
            "tokens": run.usage.total_tokens,
            "llm_calls": run.usage.llm_calls,
            "has_estimates": run.usage.has_estimates,
            "latency_s": round(latency, 2),
            "status": run.status.value,
            "tools_used": tools_used,
            "final_response": run.final_response,
            "history": history,
            "reflection": reflection_details,
        }
    except Exception as e:
        latency = time.perf_counter() - t_start
        import traceback
        traceback.print_exc()
        return {
            "task": task.id,
            "capability": task.capability,
            "success": False,
            "completed": False,
            "verified": False,
            "tool_calls": 0,
            "iterations": 0,
            "cost_usd": 0.0,
            "tokens": 0,
            "llm_calls": 0,
            "has_estimates": False,
            "latency_s": round(latency, 2),
            "status": "CRASHED",
            "error": str(e),
            "tools_used": [],
            "final_response": "",
            "history": [],
            "reflection": None,
        }
    finally:
        # Client teardown to prevent RuntimeError: Event loop is closed during GC
        if 'orch' in locals() and orch:
            if hasattr(orch, "_planner") and orch._planner and hasattr(orch._planner, "_provider") and orch._planner._provider:
                provider = orch._planner._provider
                if hasattr(provider, "_client") and provider._client:
                    client = provider._client
                    if hasattr(client, "aclose") and callable(client.aclose):
                        try:
                            import inspect
                            if inspect.iscoroutinefunction(client.aclose):
                                await client.aclose()
                            else:
                                client.aclose()
                        except Exception:
                            pass
            if hasattr(orch, "_embedder") and orch._embedder:
                embedder = orch._embedder
                if hasattr(embedder, "_provider") and embedder._provider:
                    provider = embedder._provider
                    if hasattr(provider, "_client") and provider._client:
                        client = provider._client
                        if hasattr(client, "aclose") and callable(client.aclose):
                            try:
                                import inspect
                                if inspect.iscoroutinefunction(client.aclose):
                                    await client.aclose()
                                else:
                                    client.aclose()
                            except Exception:
                                pass
                                
        shutil.rmtree(sandbox, ignore_errors=True)


# ── Aggregation and Reports ──────────────────────────────────────────

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
        "% Auto-generated by tests/eval/run_suite.py — paste into \\EvaluationGraphs.\n"
        "% Chart 1 — Erfolgsrate (success %)\n"
        f"\\addplot+[ybar] coordinates {{{succ}}};\n\n"
        "% Chart 2 — Avg. Tool Calls per run\n"
        f"\\addplot+[ybar] coordinates {{{calls}}};\n\n"
        "% Chart 3 — Cost vs Success (x = cost USD, y = success %)\n"
        f"\\addplot+[only marks] coordinates {{{scat}}};\n",
        encoding="utf-8")


def write_capability_matrix(cap_by_config: dict[str, dict[str, float]],
                             configs: list[str], caps: list[str], out: Path) -> None:
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


# ── Run Modes ────────────────────────────────────────────────────────

async def run_verify(tasks: list[Task]) -> int:
    print(f"==================================================")
    print(f"  Running Unified MOC Suite: VERIFY MODE")
    print(f"==================================================\n")
    print(f"Executing {len(tasks)} tasks against default config...\n")
    
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = out_dir / f"verify_run_{timestamp}.json"
    latest_file = out_dir / "verify_run_latest.json"
    
    model_name = "default-model"
    try:
        model_name = get_settings().active_provider_model
    except Exception:
        pass

    results = []
    failures = []
    total = len(tasks)
    successful = 0
    
    for idx, task in enumerate(tasks, 1):
        est = ESTIMATES.get(task.capability, "20s")
        print(f"[{idx}/{total}] Running: {task.capability:12}| {task.label} (est. {est}, timeout 90s)")
        
        start_time = time.time()
        res = await run_one(task, {})
        end_time = time.time()
        
        duration = round(end_time - start_time, 2)
        
        run_record = {
            "task_id": task.id,
            "capability": task.capability,
            "prompt": task.prompt,
            "success": res["success"],
            "completed": res["completed"],
            "verified": res["verified"],
            "steps": res["tool_calls"],
            "iterations": res["iterations"],
            "duration_seconds": duration,
            "cost_usd": res["cost_usd"],
            "tokens": res["tokens"],
            "llm_calls": res["llm_calls"],
            "status": res["status"],
            "tools_used": res.get("tools_used", []),
            "final_response": res.get("final_response", ""),
            "history": res.get("history", []),
            "reflection": res.get("reflection", None),
            "error": res.get("error", None)
        }
        results.append(run_record)
        
        if res["success"]:
            successful += 1
            print(f"          -> SUCCESS (tools={res['tool_calls']}, latency={res['latency_s']}s)\n")
        else:
            failures.append(task)
            print(f"          -> FAILED! completed={res['completed']}, verified={res['verified']}\n")
            
        # Write incrementally
        summary = {
            "timestamp": timestamp,
            "model": model_name,
            "mode": "verify",
            "total_tests": total,
            "completed_so_far": len(results),
            "successful": successful,
            "success_rate": round(successful / len(results) * 100, 2) if results else 0.0,
            "results": results
        }
        
        for filepath in (results_file, latest_file):
            try:
                filepath.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                print(f"Warning: failed to write incremental verify results: {e}")
            
    print("==================================================")
    if not failures:
        print("Verification Successful! All tests passed cleanly.")
        print("==================================================")
        return 0
    else:
        print(f"Verification Failed! {len(failures)}/{total} tasks failed.")
        print(f"Failed task IDs: {[t.id for t in failures]}")
        print("==================================================")
        return 1


def write_benchmark_reports(results: list[dict], selected_configs: list[str], caps_present: list[str], out_dir: Path) -> tuple[dict, dict]:
    summary = {}
    cap_by_config = {}
    
    active_configs = [c for c in selected_configs if any(r["config"] == c for r in results)]
    if not active_configs:
        return summary, cap_by_config
        
    for cfg in active_configs:
        cfg_rows = [r for r in results if r["config"] == cfg]
        summary[cfg] = aggregate(cfg_rows)
        cap_by_config[cfg] = {
            cap: _rate([r for r in cfg_rows if r["capability"] == cap])
            for cap in caps_present
        }
        
    # Write summary CSV
    try:
        with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["config", "n_trials", "success_rate_pct", "avg_tool_calls",
                        "avg_iterations", "avg_cost_usd", "avg_tokens",
                        "avg_latency_s", "cost_estimated"])
            for cfg in active_configs:
                s = summary[cfg]
                w.writerow([CONFIG_LABELS[cfg], s["n_trials"], s["success_rate_pct"],
                            s["avg_tool_calls"], s["avg_iterations"], s["avg_cost_usd"],
                            s["avg_tokens"], s["avg_latency_s"], s["any_estimated_cost"]])
    except Exception as e:
        print(f"Warning: failed to write summary.csv: {e}")

    # Write capability CSV
    try:
        with (out_dir / "capability.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["capability"] + [CONFIG_LABELS[c] for c in active_configs])
            for cap in caps_present:
                row = [cap]
                for c in active_configs:
                    row.append(cap_by_config[c].get(cap, 0.0))
                w.writerow(row)
    except Exception as e:
        print(f"Warning: failed to write capability.csv: {e}")

    try:
        write_poster_snippet(summary, out_dir / "poster_snippet.tex")
    except Exception as e:
        print(f"Warning: failed to write poster_snippet.tex: {e}")
        
    try:
        write_capability_matrix(cap_by_config, active_configs, caps_present, out_dir / "capability_matrix.tex")
    except Exception as e:
        print(f"Warning: failed to write capability_matrix.tex: {e}")
        
    return summary, cap_by_config


async def run_benchmark(tasks: list[Task], selected_configs: list[str], reps: int) -> int:
    print(f"==================================================")
    print(f"  Running Unified MOC Suite: BENCHMARK MODE")
    print(f"==================================================\n")
    total_trials = len(selected_configs) * len(tasks) * reps
    print(f"Running {total_trials} trials ({len(selected_configs)} configs x {len(tasks)} tasks x {reps} reps)\n")
    
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = out_dir / f"benchmark_run_{timestamp}.json"
    latest_file = out_dir / "benchmark_run_latest.json"
    
    model_name = "default-model"
    try:
        model_name = get_settings().active_provider_model
    except Exception:
        pass
        
    caps_present = sorted({t.capability for t in tasks})
    results: list[dict] = []
    
    done = 0
    for cfg in selected_configs:
        for task in tasks:
            for rep in range(reps):
                done += 1
                est = ESTIMATES.get(task.capability, "20s")
                print(f"[{done}/{total_trials}] {CONFIG_LABELS[cfg]:11}| {task.capability:12}| {task.label} (est. {est}, timeout 90s)", flush=True)
                
                start_time = time.time()
                row = await run_one(task, CONFIGS[cfg])
                end_time = time.time()
                
                row["config"] = cfg
                row["rep"] = rep
                row["duration_seconds"] = round(end_time - start_time, 2)
                results.append(row)
                
                print(f"          -> {'ok ' if row['success'] else 'MISS'} "
                      f"tools={row['tool_calls']} cost=${row['cost_usd']:.4f} "
                      f"{row['latency_s']}s", flush=True)
                
                # Calculate intermediate summary
                current_summary = {}
                current_cap_by_config = {}
                for c in selected_configs:
                    c_rows = [r for r in results if r["config"] == c]
                    if c_rows:
                        current_summary[c] = aggregate(c_rows)
                        current_cap_by_config[c] = {
                            cap: _rate([r for r in c_rows if r["capability"] == cap])
                            for cap in caps_present
                        }
                        
                # Write incrementally
                data = {
                    "timestamp": timestamp,
                    "model": model_name,
                    "mode": "benchmark",
                    "total_trials": total_trials,
                    "completed_so_far": done,
                    "summary": current_summary,
                    "capability_by_config": current_cap_by_config,
                    "trials": results
                }
                
                for filepath in (results_file, latest_file):
                    try:
                        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception as e:
                        print(f"Warning: failed to write incremental benchmark results: {e}")
                
                # Write incremental summary reports (CSV/LaTeX)
                write_benchmark_reports(results, selected_configs, caps_present, out_dir)

    # Write final aggregates and matrices (CSV/LaTeX)
    summary, cap_by_config = write_benchmark_reports(results, selected_configs, caps_present, out_dir)

    # Output benchmark summary tables to console
    print("\n" + "=" * 70)
    print(f"{'Config':12}{'Success%':>10}{'Tools/run':>11}{'Cost/run':>11}{'Tokens':>9}")
    print("-" * 70)
    for cfg in selected_configs:
        s = summary.get(cfg)
        if s:
            print(f"{CONFIG_LABELS[cfg]:12}{s['success_rate_pct']:>10}"
                  f"{s['avg_tool_calls']:>11}{('$'+format(s['avg_cost_usd'],'.4f')):>11}"
                  f"{s['avg_tokens']:>9}")
              
    print("\n" + "-" * 70)
    print(f"{'Capability':14}" + "".join(f"{CONFIG_LABELS[c]:>14}" for c in selected_configs))
    print("-" * 70)
    for cap in caps_present:
        row_str = f"{cap:14}"
        for c in selected_configs:
            val = cap_by_config.get(c, {}).get(cap)
            if val is not None:
                row_str += f"{val:>13}%"
            else:
                row_str += f"{'--':>14}"
        print(row_str)
    print("=" * 70)
    
    print(f"\nWrote benchmark results files to {out_dir}")
    return 0


# ── Main Entry ───────────────────────────────────────────────────────

async def main() -> None:
    ap = argparse.ArgumentParser(description="Unified Mini-OpenClaw suite")
    ap.add_argument("--mode", type=str, default="verify", choices=["verify", "benchmark"])
    ap.add_argument("--reps", type=int, default=None, help="reps count (default: verify=1, benchmark=3)")
    ap.add_argument("--configs", nargs="*", default=list(CONFIGS), choices=list(CONFIGS))
    ap.add_argument("--tasks", nargs="*", default=None, help="subset of task IDs")
    ap.add_argument("--capabilities", nargs="*", default=None, help="subset of capability tags")
    args = ap.parse_args()

    # Filter tasks
    tasks = list(TASKS)
    if args.tasks:
        tasks = [t for t in tasks if t.id in set(args.tasks)]
    if args.capabilities:
        tasks = [t for t in tasks if t.capability in set(args.capabilities)]
        
    if not tasks:
        print("Error: No tasks matched filters.", file=sys.stderr)
        sys.exit(1)
        
    # Execute according to mode
    if args.mode == "verify":
        reps = args.reps if args.reps is not None else 1
        # In verify mode we run the tasks once
        code = await run_verify(tasks)
        sys.exit(code)
    else:
        reps = args.reps if args.reps is not None else 3
        code = await run_benchmark(tasks, args.configs, reps)
        sys.exit(code)


if __name__ == "__main__":
    asyncio.run(main())
