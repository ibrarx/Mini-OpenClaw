"""
tests/eval/tasks.py — Unified capability-oriented benchmark and regression suite.
Defines all 29 tasks (14 evaluation tasks + 15 integration test harness scenarios)
with deterministic Python-based verification functions and a combined workspace seeder.
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


# ── Fixture workspace (ground truth) ──────────────────────────────────

FIXTURE_FILES: dict[str, str] = {
    # ---- 1. eval suite mock files ----
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
    "package.json": (
        '{\n'
        '  "name": "weatherbot",\n'
        '  "version": "0.2.0"\n'
        '}\n'
    ),
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

    # ---- 2. llm_harness_test suite mock files ----
    "docs/umsatz_q3_2025.csv": (
        "datum,umsatz,waehrung\n"
        "2025-07-01,15000,EUR\n"
        "2025-08-01,18000,EUR\n"
        "2025-09-01,22000,EUR\n"
    ),
    "src/backend/auth_service.py": (
        "# Authentication Service\n"
        "def authenticate_user(username, password):\n"
        "    return True\n"
    ),
    "src/backend/user_auth.py": (
        "# User Auth helper\n"
        "class UserAuthenticator:\n"
        "    pass\n"
    ),
    "src/backend/main.py": (
        "# Main entry\n"
        "print('Hello')\n"
    ),
    "config/app_config.yaml": (
        "app:\n"
        "  name: TestApp\n"
        "  version: 0.3.1\n"
        "database:\n"
        "  host: localhost\n"
        "  port: 5432\n"
    ),
    "logs/error.log": (
        "\n".join([f"2026-06-08 12:00:{i:02d} [ERROR] Database connection failed check {i}" for i in range(1, 26)]) + "\n"
    ),
    "data/contacts.txt": (
        "John Doe - john.doe@example.com\n"
        "Jane Smith: jane.smith@work.org\n"
        "Support Team <support@company.com>\n"
        "Invalid email info@site\n"
    ),
    ".env.production": (
        "PORT=8080\n"
        "STRIPE_API_KEY=sk_live_stripe_key_12345\n"
        "DB_USER=prod_user\n"
    ),
    "requirements.txt": (
        "numpy>=1.24.0\n"
        "pandas==2.1.0\n"
        "requests>=2.31.0\n"
    ),
    "report.csv": (
        "id,name,value\n"
        "1,Alpha,100\n"
        "2,Beta,200\n"
        "3,Gamma,300\n"
        "4,Delta,400\n"
        "5,Epsilon,500\n"
    ),
    "data/info.txt": "info text",
    "data/notes.txt": "notes text",
    "tax_calculator.py": (
        "def calculate_tax(amount):\n"
        "    tax_rate = 19\n"
        "    return amount * (tax_rate / 100)\n"
    ),
    "config/database_configuration.json": (
        "{\n"
        "  \"db_type\": \"sqlite\",\n"
        "  \"file_path\": \"./test.db\"\n"
        "}\n"
    ),
    "run_analytics.py": (
        "try:\n"
        "    import cowsay\n"
        "    print('cowsay imported successfully!')\n"
        "except ImportError:\n"
        "    import sys\n"
        "    print(\"ImportError: No module named 'cowsay'\", file=sys.stderr)\n"
        "    sys.exit(1)\n"
    ),
    "math_ops.py": (
        "def add(a, b):\n"
        "    return a + b\n"
    )
}


def build_fixture(dest: Path, setup_git: bool = False) -> None:
    # 1. Write the combined mock files
    for rel, content in FIXTURE_FILES.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # 2. Setup git repository for the git-specific tasks
    if setup_git:
        import subprocess
        try:
            subprocess.run(["git", "init"], cwd=str(dest), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.name", "Test Author"], cwd=str(dest), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "author@test.com"], cwd=str(dest), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            dummy_file = dest / "git_init_dummy.txt"
            dummy_file.write_text("git dummy content")
            subprocess.run(["git", "add", "git_init_dummy.txt"], cwd=str(dest), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-m", "Initial commit for test"], cwd=str(dest), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print(f"Warning: git setup failed: {exc}")


# ── the combined suite ────────────────────────────────────────────────

TASKS: list[Task] = [
    # ==== 1. ORIGINAL EVAL TASKS ====
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
        verify=lambda a, ws: _num(a, 10),
    ),
    Task(
        id="count_todos", capability="search",
        label="Count TODO markers",
        prompt="Search every file and tell me how many TODO markers there are in total.",
        verify=lambda a, ws: _num(a, 3) or "three" in a,
    ),
    Task(
        id="all_markers", capability="completeness",
        label="Find ALL markers",
        prompt=(
            "Find every TODO and FIXME marker across the entire codebase and "
            "list each one together with the file it is in. List all of them."
        ),
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
    Task(
        id="settings_recovery", capability="recovery",
        label="Recover from wrong file",
        prompt=(
            "Open settings.json and report the cache TTL in seconds it defines."
        ),
        verify=lambda a, ws: _num(a, 600),
    ),
    Task(
        id="version_decoy", capability="recovery",
        label="Ignore a decoy file",
        prompt=(
            "There is a version.txt file but it may be outdated or wrong. What "
            "is this project's real, current version?"
        ),
        verify=lambda a, ws: ("0.3.1" in a) and not _num(a, 9),
    ),
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

    # ==== 2. CONVERTED LLM HARNESS TESTS ====
    Task(
        id="find_file_1", capability="recall",
        label="Locate sales file",
        prompt="Search for the sales file for Q3 2025 in the docs folder.",
        verify=lambda a, ws: "umsatz_q3_2025.csv" in a,
    ),
    Task(
        id="find_file_2", capability="search",
        label="Find backend auth files",
        prompt="Find all Python files in the src/backend directory that have auth in their name.",
        pre_approved=["run_shell_safe"],
        verify=lambda a, ws: _all(a, "auth_service.py", "user_auth.py"),
    ),
    Task(
        id="read_file_1", capability="recall",
        label="Read yaml settings",
        prompt="Read the contents of the config/app_config.yaml file and print it.",
        verify=lambda a, ws: _all(a, "app:", "database:"),
    ),
    Task(
        id="read_file_2", capability="recall",
        label="Read last error lines",
        prompt="Look into the logs/error.log file and show me the last 20 lines.",
        verify=lambda a, ws: _any(a, "error", "failed", "connection"),
    ),
    Task(
        id="extract_info_1", capability="recall",
        label="Extract email list",
        prompt="Extract all email addresses from the data/contacts.txt file.",
        verify=lambda a, ws: _all(a, "john.doe@example.com", "jane.smith@work.org", "support@company.com"),
    ),
    Task(
        id="extract_info_2", capability="search",
        label="Find Stripe API key",
        prompt="Find the API key for Stripe in the environment variable files.",
        verify=lambda a, ws: "sk_live_stripe_key_12345" in a,
    ),
    Task(
        id="extract_info_3", capability="recall",
        label="Check numpy version",
        prompt="Which version of 'numpy' is required in requirements.txt?",
        verify=lambda a, ws: "1.24.0" in a,
    ),
    Task(
        id="multi_step_1", capability="multi_step",
        label="Find and count report rows",
        prompt="Find the file 'report.csv' in the root directory, read it, and count the number of lines.",
        verify=lambda a, ws: _any(a, "6", "six", "sechs"),
    ),
    Task(
        id="multi_step_2", capability="multi_step",
        label="Backup and zip files",
        prompt="Create a new folder 'backup', copy all .txt files from 'data' there, and zip the folder.",
        pre_approved=["run_shell_safe"],
        verify=lambda a, ws: (ws / "backup.zip").exists(),
    ),
    Task(
        id="multi_step_3", capability="multi_step",
        label="Git last commit author",
        prompt="Find out who made the last commit in the Git repository and write the name into author.txt.",
        pre_approved=["run_shell_safe", "write_file"],
        verify=lambda a, ws: _file_contains(ws / "author.txt", "Test Author"),
    ),
    Task(
        id="tool_chaining_1", capability="multi_step",
        label="Update tax rate",
        prompt="Search for the function 'calculate_tax' in the project, read the corresponding file, and change the tax rate from 19 to 20.",
        pre_approved=["search_in_files", "read_file", "write_file"],
        verify=lambda a, ws: _file_contains(ws / "tax_calculator.py", "20"),
    ),
    Task(
        id="tool_chaining_2", capability="delegation",
        label="Check and restart server",
        prompt="Check the status of the webserver (curl); if it does not respond, restart the service (systemctl) and check again.",
        pre_approved=["run_shell_safe"],
        verify=lambda a, ws: _any(a, "started", "running", "200 ok"),
    ),
    Task(
        id="error_correction_1", capability="recovery",
        label="Recover database configuration",
        prompt="Read the file config/db_config.json. If the file does not exist, search the entire project for a file with a similar name and read it.",
        verify=lambda a, ws: _all(a, "sqlite", "test.db"),
    ),
    Task(
        id="error_correction_2", capability="recovery",
        label="Fix analytics import error",
        prompt="Execute the script 'run_analytics.py'. If it fails due to a missing module, install the module via pip and run it again. Report the exact output of the successful execution.",
        pre_approved=["run_shell_safe"],
        verify=lambda a, ws: "cowsay imported successfully" in a,
    ),
    Task(
        id="error_correction_3", capability="recovery",
        label="Correct failing test case",
        prompt="Write a test for the 'add' function. Run pytest, and if the test fails, correct the test code until it passes.",
        pre_approved=["write_file", "run_shell_safe"],
        verify=lambda a, ws: _any(a, "passed", "pytest"),
    ),
]
