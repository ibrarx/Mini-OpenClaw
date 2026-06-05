# Mini-OpenClaw — Evaluation Harness

This folder benchmarks the agent so we can put **real numbers** on the poster
instead of mock data. It runs a fixed set of tasks under three agent
configurations and reports two things:

1. **By configuration** — how Baseline vs Plan+ReAct vs the Full pipeline
   compare on success rate, tool calls, and cost. (These feed the poster's
   three bar/scatter charts.)
2. **By capability** — *where* each architectural layer actually earns its
   keep (recall, search, completeness, recovery, cross-file reasoning,
   memory, delegation). This becomes a capability matrix on the poster.

Everything is grounded in a fixed fixture workspace, so success is checked
**deterministically** — no "ask an LLM if the answer looks good." A trial
passes only if the run completes *and* the answer (or the file it was asked
to write) matches known ground truth.

---

## TL;DR

```powershell
# from the REPO ROOT, with a working .env (provider + API key):
python -m eval.run_eval --reps 1 --tasks read_version   # ~30s smoke test
python -m eval.run_eval                                  # full run
```

Then send back the two CSVs from `eval/results/` (`summary.csv` and
`capability.csv`). That's all I need to put the numbers on the poster.

---

## What gets tested

### The three configurations

| Config | What it is | Toggles |
|---|---|---|
| **Baseline** | Plan everything up front, then execute. No mid-run adaptation. | `use_react=False` |
| **Plan+ReAct** | Iterative think→act→observe loop. No goals, no replanning. | `use_react=True`, goals off, replans 0 |
| **Full** | Hybrid goals + replanning + self-reflection. | `use_react=True`, goals on, replans 2, reflect on |

You don't set these manually — the harness applies them per run.

### The capabilities (14 tasks)

- **recall / search** — basic reads and counts. The floor; even Baseline
  should pass these.
- **completeness** — find *every* TODO/FIXME without stopping early.
- **multi_step** — produce a multi-part deliverable file.
- **recovery** — the obvious file (`settings.json`) doesn't exist, and a decoy
  `version.txt` lies about the version. The agent has to adapt.
- **cross_file** — two files disagree about the version; spot the mismatch.
- **memory** — a fact is stored on one turn and must be recalled on a later
  turn.
- **delegation** — a per-file report the agent may split across sub-agents.

---

## Prerequisites

You need a working Mini-OpenClaw setup. If you can already run the project,
you're done — skip to **How to run**. Otherwise, from the repo root:

```powershell
# 1. Install Python dependencies (same ones the project uses)
pip install -r requirements.txt

# 2. Create your .env from the template and add an API key
copy .env.example .env        # macOS/Linux: cp .env.example .env
#   then edit .env:  set LLM_PROVIDER and the matching key
```

- **Python 3.11+** (same as the main project).
- **A provider + key.** Anthropic or Gemini both work. Or run it **free**
  on a local Ollama model (see below).
- **First run downloads a small embedding model** (`all-MiniLM-L6-v2`,
  ~90 MB) for the memory system. One-time, then cached.

> The harness reads your provider and API key from `.env` automatically.
> You only need the `$env:` commands below if you want to override the
> provider for a single run (e.g. to use the free local model).

---

## How to run

**Always run from the repository root** (not from inside `eval/`), so the
`apps.api` imports resolve:

```powershell
python -m eval.run_eval
```

### Recommended first step — a cheap smoke test

Confirm your provider is wired up before spending budget on the full run:

```powershell
python -m eval.run_eval --reps 1 --tasks read_version
```

If that prints `-> ok ...` you're good. If it errors, see **Troubleshooting**.

### Full run

```powershell
python -m eval.run_eval
```

Defaults: all 3 configs × 14 tasks × 3 reps. The repetitions average out
the natural run-to-run variance of the LLM.

### Useful options

| Command | What it does |
|---|---|
| `--reps 5` | More repetitions = less noise (and more cost). |
| `--configs baseline full` | Run a subset of configs. |
| `--tasks read_version count_todos` | Run only specific task IDs. |
| `--capabilities recovery memory` | Run only tasks of certain capabilities. |

### Choosing a provider for one run

```powershell
# Gemini (fast + cheap)
$env:LLM_PROVIDER = "gemini"; $env:GEMINI_API_KEY = "..."
python -m eval.run_eval

# Local + FREE via Ollama (install from ollama.ai, then: ollama pull llama3.2)
$env:LLM_PROVIDER = "ollama"
python -m eval.run_eval
```

On macOS/Linux use `export LLM_PROVIDER=gemini` instead of `$env:`.

---

## Cost

The full run is roughly **126 trials** (memory tasks take two turns;
delegation may spawn sub-agents). Approximate total cost:

| Provider | Rough cost for a full run |
|---|---|
| Claude Sonnet | **~$3–6** |
| Gemini 2.5 Flash | a few cents |
| Ollama (local) | **free** |

To keep it cheap: smoke-test first, use `--capabilities` / `--tasks` to run
only the slices you care about, or run the whole thing on Gemini Flash or
Ollama. Local-model success rates will be lower, but the *relative* ranking
of the three configs still tells the story.

---

## Outputs

Everything lands in `eval/results/`:

| File | Use |
|---|---|
| `summary.csv` | One row per config — **send this back.** |
| `capability.csv` | Success % per capability per config — **send this back.** |
| `results.json` | Every individual trial (for digging into misses). |
| `poster_snippet.tex` | `\addplot` lines that drop straight into the poster charts. |
| `capability_matrix.tex` | A ready LaTeX table of the capability matrix. |

The script also prints both tables to the console at the end, so you can
just copy-paste that if it's easier.

**What to send back:** `summary.csv` + `capability.csv` (or a screenshot of
the printed tables). That's enough to finalize the poster.

---

## How to read the results

- **Baseline should win the easy tasks and lose the hard ones.** If every
  config scores the same, the tasks aren't separating the configs — tell me
  and I'll harden them.
- **Full should lead on completeness, recovery, and cross_file**, because
  that's exactly what goals/replanning/reflection are for. It should also
  cost more per run — that trade-off is the point of the cost chart.
- **Memory tasks** should pass across all configs (memory is independent of
  the loop type). They're there to show the feature *works*, not to separate
  configs.
- **Delegation is opportunistic** — the agent decides whether to split the
  work, so that row reflects the outcome, not a guarantee that sub-agents
  fired.

Each trial runs in a throwaway temp workspace and a throwaway SQLite DB, so
runs never contaminate each other and **nothing touches your real project
data or `mini_openclaw.db`.**

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'apps'`**
You're not in the repo root. `cd` to the top of the project and run
`python -m eval.run_eval` from there.

**`ModuleNotFoundError: No module named 'aiosqlite'` (or pydantic, etc.)**
Dependencies aren't installed: `pip install -r requirements.txt`.

**"LLM provider not configured" in the output**
No key found. Check `.env` has `LLM_PROVIDER` and the matching
`ANTHROPIC_API_KEY` / `GEMINI_API_KEY`, or set them with `$env:` for the run.

**First run is slow / seems to hang at startup**
It's downloading the ~90 MB embedding model once. Let it finish; later runs
are fast.

**A whole capability scores 0%**
Could be a real finding, or the provider is struggling (common on small
local models). Re-run that slice with `--capabilities <name> --reps 1` and
look at `results.json` to see the actual answers.

---

## Files in this folder

- `run_eval.py` — the harness: fixtures, the three configs, the runner,
  aggregation, and the output writers.
- `tasks.py` — the task suite and their deterministic verifiers. Edit here
  to add or tweak tasks.
- `__init__.py` — marks the folder as a package.
- `results/` — created on first run (git-ignore if you don't want it tracked).
