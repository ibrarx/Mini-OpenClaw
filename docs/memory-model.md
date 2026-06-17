# Memory Model

The memory system is fast to retrieve, human-readable, and auditable. **SQLite**
is the primary store; `scripts/export_memory.py` dumps every table to formatted
JSON for direct inspection.

For the broader narrative see the root [`README.md`](../README.md). The schema is
defined in `apps/api/models/memory_item.py` and the retrieval logic in
`apps/api/memory/`.

## Five memory layers

`MemoryType` (`apps/api/models/memory_item.py`) defines five kinds of memory:

| Layer | Purpose |
|-------|---------|
| `fact` | Durable facts about the user, workspace, or environment (editable, inspectable). |
| `episode` | Completed tasks — plans, actions, and outcomes (audit trail, repeat tasks). |
| `summary` | Rolling conversation summaries that keep the active thread coherent. |
| `strategy` | Reusable approaches distilled from past runs (proposed by the dream cycle). |
| `preference` | Inferred user/project traits (e.g. "prefers concise output"). |

`fact`, `episode`, and `summary` are the durable foundation; `strategy` and
`preference` are higher-level, dream-derived layers.

## Hybrid retrieval

Retrieval blends **vector similarity (~70%)** using a local sentence-transformer
(`all-MiniLM-L6-v2`, $0, no API key) with **keyword matching (~30%)**, then filters
by workspace and visibility and ranks by relevance, recency, and confidence. The
resulting context bundle is injected into the planner on each call.
(`apps/api/memory/retrieval.py`, `embeddings.py`, `vector_store.py`.)

## Agent Dreams (consolidation)

The dream cycle (`apps/api/memory/dreamer.py`) periodically consolidates episodes
into proposed `strategy`/`preference` insights under a **propose → review →
approve** flow — the agent never acts on inferred knowledge without explicit user
consent. Pending insights surface via `GET /api/memory/pending` and are
accepted/rejected via `POST /api/memory/{id}/review`.

## Schema (`memory_items`)

Each item stores: `id`, `workspace_id`, `memory_type`, `content`, `summary`,
`source`, `confidence` (0–1), `visibility` (`system` / `user_visible` /
`restricted`), `status`, `created_at`, `updated_at`, and `run_id`. Every write
records provenance so the system can always explain why it relied on a memory.

## Write & audit rules

Store only useful, durable information; never persist raw secrets or every
transient tool output; summarize long exchanges instead of copying transcripts.
Every memory write logs its trigger, type, source, run id, author
(`system`/`user`/`agent`), and timestamp.

## JSON export

`python scripts/export_memory.py` writes `exports/facts.json`,
`episodes.json`, `summaries.json`, and `audit_log.json` — formatted,
human-readable files for evaluators who prefer to inspect memory without the UI.
