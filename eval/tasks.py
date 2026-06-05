"""
eval/tasks.py — Capability-oriented benchmark suite for Mini-OpenClaw.

The point of this suite is not to prove the loop runs — it is to show
*where the architecture earns its complexity*. Tasks are grouped by the
capability they exercise, from trivial recall (where even the baseline
should win) up to multi-step completeness, adaptive recovery, cross-file
reasoning, and memory recall (where goals, replanning, reflection, and the
memory system are supposed to pull ahead).

Each task is grounded in a fixed fixture workspace (see eval/run_eval.py
``FIXTURE_FILES``) so success is verified deterministically — no
LLM-as-judge. A trial counts as a success only if:

    run.status == COMPLETED  AND  task.verify(answer_lower, workspace) is True

Verifiers are phrasing-tolerant: they look for the ground-truth value
(a number, a filename, a token) rather than an exact sentence, or check
the workspace state a write was supposed to produce.

Ground truth baked into the fixture (keep in sync with FIXTURE_FILES):
    - exactly 4 Python (.py) files
    - exactly 3 TODO markers   -> src/main.py, src/api.py, tests/test_main.py
    - exactly 1 FIXME marker   -> src/utils.py
    - real version 0.3.1       -> config.json + README ("Current release")
    - cache_ttl_seconds 600    -> config.json
    - package.json version     0.2.0   (intentional mismatch vs config)
    - version.txt              decoy "9.9.9" (must be ignored)
    - 4 features listed under README "## Features"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Task:
    id: str
    capability: str            # recall | search | completeness | multi_step
                               # | recovery | cross_file | memory | delegation
    prompt: str
    label: str = ""
    pre_approved: list[str] = field(default_factory=list)
    # Messages run (in order) in the SAME session/DB before ``prompt``.
    # Used to seed memory so a later question can be answered from recall.
    setup_messages: list[str] = field(default_factory=list)
    # verify(final_response_lower, workspace_path) -> bool
    verify: Callable[[str, Path], bool] = lambda ans, ws: True


# ── verifier helpers ─────────────────────────────────────────────────

def _num(text: str, value: int) -> bool:
    """True if ``value`` appears as a standalone number."""
    return bool(re.search(rf"(?<!\d){value}(?!\d)", text))


def _all(text: str, *needles: str) -> bool:
    return all(n.lower() in text for n in needles)


def _any(text: str, *needles: str) -> bool:
    return any(n.lower() in text for n in needles)


def _file_contains(path: Path, *needles: str) -> bool:
    try:
        body = path.read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return all(n.lower() in body for n in needles)


def _file_equals(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").strip() == expected.strip()
    except OSError:
        return False


# ── the suite ────────────────────────────────────────────────────────

TASKS: list[Task] = [
    # ---- recall / search : the floor (baseline should handle these) ----
    Task(
        id="read_config_ttl", capability="recall",
        label="Read a config value",
        prompt="What is the cache TTL in seconds configured in config.json?",
        verify=lambda a, ws: _num(a, 600),
    ),
    Task(
        id="read_version", capability="recall",
        label="Find the version",
        prompt="What version is this project? Look in config.json.",
        verify=lambda a, ws: "0.3.1" in a,
    ),
    Task(
        id="list_docs", capability="recall",
        label="List the docs dir",
        prompt="List the files inside the docs directory and name them.",
        verify=lambda a, ws: "architecture.md" in a,
    ),
    Task(
        id="count_py_files", capability="search",
        label="Count Python files",
        prompt="How many Python (.py) files are in this project? Search the whole workspace.",
        verify=lambda a, ws: _num(a, 4),
    ),
    Task(
        id="count_todos", capability="search",
        label="Count TODO markers",
        prompt="Search every file and tell me how many TODO markers there are in total.",
        verify=lambda a, ws: _num(a, 3),
    ),

    # ---- completeness : goals + reflection should prevent stopping early ----
    Task(
        id="all_markers", capability="completeness",
        label="Find ALL markers",
        prompt=(
            "Find every TODO and FIXME marker across the entire codebase and "
            "list each one together with the file it is in. List all of them."
        ),
        # All four source files that contain a marker must be named.
        verify=lambda a, ws: _all(a, "main.py", "api.py", "test_main.py", "utils.py"),
    ),
    Task(
        id="per_file_markers", capability="delegation",
        label="Per-file marker report",
        prompt=(
            "For each Python file under the src/ directory, tell me whether it "
            "contains a TODO or a FIXME. Cover every file in src/."
        ),
        pre_approved=["delegate_task"],
        verify=lambda a, ws: _all(a, "main.py", "utils.py", "api.py")
                              and _all(a, "todo", "fixme"),
    ),

    # ---- multi_step : produce a real multi-part deliverable ----
    Task(
        id="report_file", capability="multi_step",
        label="Build a report file",
        prompt=(
            "Create a file named report.txt in the workspace containing four "
            "things: the project name, the project version, the total number "
            "of TODO markers in the codebase, and the name of the file that "
            "contains a FIXME."
        ),
        pre_approved=["write_file"],
        verify=lambda a, ws: _file_contains(
            ws / "report.txt", "weatherbot", "0.3.1", "3", "utils.py"),
    ),
    Task(
        id="summary_write", capability="multi_step",
        label="Write a summary file",
        prompt=(
            "Write a file named summary.md with a one-line description of what "
            "this project is, and include its version number."
        ),
        pre_approved=["write_file"],
        verify=lambda a, ws: _file_contains(ws / "summary.md", "0.3.1")
                              and (ws / "summary.md").exists(),
    ),

    # ---- recovery : the planned-upfront path can't adapt; ReAct can ----
    Task(
        id="settings_recovery", capability="recovery",
        label="Recover from wrong file",
        prompt=(
            "Open settings.json and report the cache TTL in seconds it defines."
        ),
        # settings.json does not exist; the value lives in config.json (600).
        verify=lambda a, ws: _num(a, 600),
    ),
    Task(
        id="version_decoy", capability="recovery",
        label="Ignore a decoy file",
        prompt=(
            "There is a version.txt file but it may be outdated or wrong. What "
            "is this project's real, current version?"
        ),
        verify=lambda a, ws: ("0.3.1" in a) and not _num(a, 9),  # not the 9.9.9 decoy
    ),

    # ---- cross_file : read two sources and compare ----
    Task(
        id="version_mismatch", capability="cross_file",
        label="Cross-check two files",
        prompt=(
            "Does the version in config.json match the version in package.json? "
            "Answer yes or no and state both version numbers."
        ),
        verify=lambda a, ws: _all(a, "0.3.1", "0.2.0")
                              and _any(a, "no", "not", "differ", "mismatch", "don't"),
    ),

    # ---- memory : seed a fact, then require recall on a later turn ----
    Task(
        id="memory_region", capability="memory",
        label="Recall a stored fact",
        prompt="Which region do we deploy to?",
        setup_messages=["Please remember this: our deployment target region is eu-west-2."],
        pre_approved=["remember_fact"],
        verify=lambda a, ws: "eu-west-2" in a,
    ),
    Task(
        id="memory_pytest", capability="memory",
        label="Recall a preference",
        prompt="What testing framework does the team prefer?",
        setup_messages=["Remember that our team prefers pytest over unittest."],
        pre_approved=["remember_fact"],
        verify=lambda a, ws: "pytest" in a,
    ),
]
