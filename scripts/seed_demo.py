"""
Set up a demo workspace for evaluator use.

Creates a realistic small project workspace with enough depth and variety to
exercise every V1 tool meaningfully:

  list_files     — nested dirs (3 levels), mixed file types
  read_file      — multiple text files, batch-read friendly sizes
  write_file     — evaluator can test creating/appending (not seeded)
  search_in_files — TODO/FIXME/BUG markers scattered across files
  run_shell_safe — files to cat, grep, find across nested dirs
  remember_fact  — pre-populated facts for memory browser demo
  search_memory  — enough items to demo keyword + semantic search

Pre-populates memory with facts and episodes so the memory browser is
non-empty on first launch. Idempotent: clears old seed data before
re-creating it.

Usage:
    python scripts/seed_demo.py                # normal run
    python scripts/seed_demo.py --clean        # remove workspace + seed memory, then recreate
    python scripts/seed_demo.py --clean-all    # full reset: workspace + ALL memory + database
"""
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.config import get_settings
from apps.api.database import create_tables, get_connection
from apps.api.memory.manager import MemoryManager


# ── File content ──────────────────────────────────────────────────────────

FILES: dict[str, str] = {
    "README.md": (
        "# WeatherBot\n\n"
        "A command-line weather assistant built with Python and FastAPI.\n\n"
        "## Features\n"
        "- Fetch current weather by city name\n"
        "- 5-day forecast with hourly breakdown\n"
        "- Caching layer to reduce API calls\n"
        "- CLI and REST API interfaces\n\n"
        "## Quick start\n"
        "```bash\n"
        "pip install -r requirements.txt\n"
        "python -m weatherbot.cli London\n"
        "```\n\n"
        "## Architecture\n"
        "See `docs/architecture.md` for the full design.\n\n"
        "## TODO\n"
        "- [ ] Add wind speed and humidity to the forecast display\n"
        "- [ ] Support geocoding so users can search by address\n"
        "- [ ] Add rate limiting to the REST API\n"
    ),

    "requirements.txt": (
        "fastapi>=0.110.0\n"
        "uvicorn>=0.27.0\n"
        "httpx>=0.27.0\n"
        "click>=8.1.0\n"
        "pydantic>=2.6.0\n"
        "python-dotenv>=1.0.0\n"
        "diskcache>=5.6.0\n"
    ),

    "config.json": (
        '{\n'
        '  "project": "weatherbot",\n'
        '  "version": "0.3.1",\n'
        '  "api_base_url": "https://api.openweathermap.org/data/2.5",\n'
        '  "cache_ttl_seconds": 600,\n'
        '  "default_units": "metric",\n'
        '  "log_level": "INFO"\n'
        '}\n'
    ),

    "notes.txt": (
        "=== Project notes ===\n\n"
        "TODO: Review the caching strategy — TTL might be too aggressive\n"
        "TODO: Write integration tests for the forecast endpoint\n"
        "TODO: Add retry logic for transient API failures\n"
        "DONE: Set up project structure\n"
        "DONE: Implement CLI interface\n"
        "DONE: Add basic error handling\n"
        "FIXME: The temperature rounding loses precision for Fahrenheit\n"
        "BUG: Forecast endpoint returns 500 when city name contains unicode\n"
    ),

    # ── src/ ──

    "src/__init__.py": '"""WeatherBot source package."""\n',

    "src/main.py": (
        '"""Application entry point for the WeatherBot REST API."""\n\n'
        "from fastapi import FastAPI\n"
        "from .routes import router\n"
        "from .cache import init_cache\n\n"
        "app = FastAPI(title=\"WeatherBot\", version=\"0.3.1\")\n"
        "app.include_router(router, prefix=\"/api\")\n\n\n"
        "@app.on_event(\"startup\")\n"
        "async def startup() -> None:\n"
        "    init_cache()\n"
        '    # TODO: Add health check endpoint\n\n\n'
        "@app.on_event(\"shutdown\")\n"
        "async def shutdown() -> None:\n"
        '    # TODO: Flush pending cache writes on shutdown\n'
        "    pass\n"
    ),

    "src/routes.py": (
        '"""REST API routes for weather queries."""\n\n'
        "from fastapi import APIRouter, HTTPException\n"
        "from .weather import get_current, get_forecast\n\n"
        "router = APIRouter()\n\n\n"
        "@router.get(\"/weather/{city}\")\n"
        "async def current_weather(city: str) -> dict:\n"
        '    """Return current weather for a city."""\n'
        "    data = await get_current(city)\n"
        "    if data is None:\n"
        "        raise HTTPException(status_code=404, detail=f\"City '{city}' not found\")\n"
        "    return data\n\n\n"
        "@router.get(\"/forecast/{city}\")\n"
        "async def forecast(city: str, days: int = 5) -> dict:\n"
        '    """Return multi-day forecast for a city.\n\n'
        "    FIXME: days parameter is not validated — negative values crash\n"
        '    """\n'
        "    data = await get_forecast(city, days)\n"
        "    if data is None:\n"
        "        raise HTTPException(status_code=404, detail=f\"City '{city}' not found\")\n"
        "    return data\n"
    ),

    "src/weather.py": (
        '"""Core weather service — fetches data from OpenWeatherMap."""\n\n'
        "import json\n"
        "from pathlib import Path\n\n"
        "import httpx\n\n"
        "from .cache import get_cached, set_cached\n\n"
        "CONFIG = json.loads((Path(__file__).parent.parent / \"config.json\").read_text())\n"
        "BASE_URL = CONFIG[\"api_base_url\"]\n"
        "UNITS = CONFIG[\"default_units\"]\n\n\n"
        "async def get_current(city: str) -> dict | None:\n"
        '    """Fetch current weather, with cache.\n\n'
        "    TODO: Add support for coordinates (lat/lon) as alternative to city name\n"
        '    """\n'
        "    cached = get_cached(f\"current:{city}\")\n"
        "    if cached:\n"
        "        return cached\n"
        "    async with httpx.AsyncClient() as client:\n"
        "        resp = await client.get(f\"{BASE_URL}/weather\", params={\"q\": city, \"units\": UNITS})\n"
        "        if resp.status_code == 404:\n"
        "            return None\n"
        "        resp.raise_for_status()\n"
        "        data = resp.json()\n"
        "    set_cached(f\"current:{city}\", data)\n"
        "    return data\n\n\n"
        "async def get_forecast(city: str, days: int = 5) -> dict | None:\n"
        '    """Fetch multi-day forecast.\n\n'
        "    BUG: When days > 7 the API returns partial data but we don't detect it\n"
        '    """\n'
        "    cached = get_cached(f\"forecast:{city}:{days}\")\n"
        "    if cached:\n"
        "        return cached\n"
        "    async with httpx.AsyncClient() as client:\n"
        "        resp = await client.get(f\"{BASE_URL}/forecast\", params={\"q\": city, \"cnt\": days * 8, \"units\": UNITS})\n"
        "        if resp.status_code == 404:\n"
        "            return None\n"
        "        resp.raise_for_status()\n"
        "        data = resp.json()\n"
        "    set_cached(f\"forecast:{city}:{days}\", data)\n"
        "    return data\n"
    ),

    "src/cache.py": (
        '"""Simple disk-based caching layer using diskcache."""\n\n'
        "from pathlib import Path\n"
        "from typing import Any\n\n"
        "import diskcache\n\n"
        "# TODO: Make cache directory configurable via config.json\n"
        "_cache: diskcache.Cache | None = None\n"
        "DEFAULT_TTL = 600  # seconds\n\n\n"
        "def init_cache(cache_dir: str = \".cache\") -> None:\n"
        "    global _cache\n"
        "    _cache = diskcache.Cache(cache_dir)\n\n\n"
        "def get_cached(key: str) -> Any | None:\n"
        "    if _cache is None:\n"
        "        return None\n"
        "    return _cache.get(key)\n\n\n"
        "def set_cached(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:\n"
        "    if _cache is None:\n"
        "        return\n"
        "    _cache.set(key, value, expire=ttl)\n"
    ),

    "src/cli.py": (
        '"""Command-line interface for WeatherBot."""\n\n'
        "import asyncio\n"
        "import click\n"
        "from .weather import get_current, get_forecast\n\n\n"
        "@click.group()\n"
        "def main() -> None:\n"
        '    """WeatherBot — check the weather from your terminal."""\n'
        "    pass\n\n\n"
        "@main.command()\n"
        "@click.argument(\"city\")\n"
        "def now(city: str) -> None:\n"
        '    """Show current weather for CITY."""\n'
        "    data = asyncio.run(get_current(city))\n"
        "    if data is None:\n"
        "        click.echo(f\"City '{city}' not found.\")\n"
        "        return\n"
        "    temp = data.get(\"main\", {}).get(\"temp\", \"?\")\n"
        "    desc = data.get(\"weather\", [{}])[0].get(\"description\", \"unknown\")\n"
        "    click.echo(f\"{city}: {temp}° — {desc}\")\n\n\n"
        "@main.command()\n"
        "@click.argument(\"city\")\n"
        "@click.option(\"--days\", default=5, help=\"Number of forecast days\")\n"
        "def forecast(city: str, days: int) -> None:\n"
        '    """Show multi-day forecast for CITY."""\n'
        "    data = asyncio.run(get_forecast(city, days))\n"
        "    if data is None:\n"
        "        click.echo(f\"City '{city}' not found.\")\n"
        "        return\n"
        "    # FIXME: This just dumps raw JSON — should format it nicely\n"
        "    click.echo(data)\n"
    ),

    # ── tests/ ──

    "tests/__init__.py": "",

    "tests/test_weather.py": (
        '"""Unit tests for the weather service."""\n\n'
        "import pytest\n"
        "from src.weather import get_current, get_forecast\n\n\n"
        "# TODO: Add mocked httpx responses for offline testing\n\n"
        "@pytest.mark.asyncio\n"
        "async def test_current_returns_dict() -> None:\n"
        '    """Smoke test — requires network access."""\n'
        "    result = await get_current(\"London\")\n"
        "    assert isinstance(result, dict)\n\n\n"
        "@pytest.mark.asyncio\n"
        "async def test_current_unknown_city_returns_none() -> None:\n"
        "    result = await get_current(\"NotARealCity12345\")\n"
        "    assert result is None\n\n\n"
        "# BUG: This test is flaky when the API rate-limits us\n"
        "@pytest.mark.asyncio\n"
        "async def test_forecast_returns_list() -> None:\n"
        "    result = await get_forecast(\"Berlin\", days=3)\n"
        "    assert result is not None\n"
    ),

    "tests/test_cache.py": (
        '"""Unit tests for the caching layer."""\n\n'
        "from src.cache import init_cache, get_cached, set_cached\n\n\n"
        "def test_cache_round_trip(tmp_path: str) -> None:\n"
        "    init_cache(str(tmp_path))\n"
        "    set_cached(\"key1\", {\"temp\": 20})\n"
        "    assert get_cached(\"key1\") == {\"temp\": 20}\n\n\n"
        "def test_cache_miss_returns_none(tmp_path: str) -> None:\n"
        "    init_cache(str(tmp_path))\n"
        "    assert get_cached(\"nonexistent\") is None\n"
    ),

    # ── docs/ ──

    "docs/architecture.md": (
        "# WeatherBot Architecture\n\n"
        "## Overview\n"
        "WeatherBot follows a simple layered architecture:\n\n"
        "```\n"
        "CLI / REST API\n"
        "    ↓\n"
        "Weather Service (core logic)\n"
        "    ↓\n"
        "Cache Layer (diskcache)\n"
        "    ↓\n"
        "OpenWeatherMap API (external)\n"
        "```\n\n"
        "## Design decisions\n"
        "- **diskcache** over Redis: no server to manage for a CLI tool\n"
        "- **httpx** over requests: native async support\n"
        "- **FastAPI** for the REST layer: auto-generated docs, async-first\n"
        "- **click** for CLI: composable commands, built-in help\n\n"
        "## TODO\n"
        "- Add a diagram showing the data flow\n"
        "- Document the caching strategy in detail\n"
    ),

    "docs/api-reference.md": (
        "# WeatherBot API Reference\n\n"
        "## Endpoints\n\n"
        "### GET /api/weather/{city}\n"
        "Returns current weather for the given city.\n\n"
        "**Response:**\n"
        "```json\n"
        '{ "temp": 18.5, "description": "partly cloudy", "humidity": 65 }\n'
        "```\n\n"
        "### GET /api/forecast/{city}?days=5\n"
        "Returns multi-day forecast.\n\n"
        "**Parameters:**\n"
        "- `days` (int, default 5): number of forecast days\n\n"
        "FIXME: Document error response format\n"
    ),

    "docs/changelog.md": (
        "# Changelog\n\n"
        "## v0.3.1 (2026-05-10)\n"
        "- Fixed cache TTL not respecting config.json value\n"
        "- Added unit tests for cache layer\n\n"
        "## v0.3.0 (2026-05-01)\n"
        "- Added 5-day forecast endpoint\n"
        "- Introduced diskcache for response caching\n"
        "- Added CLI forecast command\n\n"
        "## v0.2.0 (2026-04-15)\n"
        "- Added REST API with FastAPI\n"
        "- Refactored weather service to async\n\n"
        "## v0.1.0 (2026-04-01)\n"
        "- Initial CLI with current weather lookup\n"
    ),

    # ── data/ ──

    "data/sample_cities.csv": (
        "city,country,latitude,longitude,timezone\n"
        "London,GB,51.5074,-0.1278,Europe/London\n"
        "Vienna,AT,48.2082,16.3738,Europe/Vienna\n"
        "New York,US,40.7128,-74.0060,America/New_York\n"
        "Tokyo,JP,35.6762,139.6503,Asia/Tokyo\n"
        "Sydney,AU,-33.8688,151.2093,Australia/Sydney\n"
        "São Paulo,BR,-23.5505,-46.6333,America/Sao_Paulo\n"
        "Cairo,EG,30.0444,31.2357,Africa/Cairo\n"
        "Mumbai,IN,19.0760,72.8777,Asia/Kolkata\n"
    ),

    "data/test_responses.json": (
        '{\n'
        '  "london_current": {\n'
        '    "temp": 15.2,\n'
        '    "feels_like": 13.8,\n'
        '    "description": "overcast clouds",\n'
        '    "humidity": 72,\n'
        '    "wind_speed": 5.1\n'
        '  },\n'
        '  "vienna_current": {\n'
        '    "temp": 22.1,\n'
        '    "feels_like": 21.5,\n'
        '    "description": "clear sky",\n'
        '    "humidity": 45,\n'
        '    "wind_speed": 3.2\n'
        '  }\n'
        '}\n'
    ),
}


# ── Memory seeds ──────────────────────────────────────────────────────────

SEED_SOURCE = "seed_demo"

FACTS = [
    ("The demo workspace contains a Python weather assistant project called WeatherBot", 1.0),
    ("WeatherBot uses FastAPI for its REST API and click for the CLI", 1.0),
    ("The project has source code in src/, tests in tests/, docs in docs/, and sample data in data/", 0.95),
    ("The caching layer uses diskcache with a 600-second TTL configured in config.json", 0.9),
    ("The project targets Python 3.11+ and uses httpx for async HTTP requests", 0.9),
    ("There are known bugs: forecast fails on unicode city names, and partial data when days > 7", 0.85),
]

EPISODES = [
    ("Seed script created the WeatherBot demo workspace with 18 files across 5 directories.",
     "Demo workspace seeded with WeatherBot project"),
    ("Previous session explored the project structure and identified TODO items across 7 files.",
     "Explored workspace and catalogued TODOs"),
    ("User asked about the architecture and was shown the layered design: CLI/API → Service → Cache → External API.",
     "Explained WeatherBot architecture"),
]


# ── Main logic ────────────────────────────────────────────────────────────

async def clear_seed_memory(db_path: Path) -> int:
    """Delete all memory items created by the seed script."""
    conn = await get_connection(db_path)
    try:
        cursor = await conn.execute(
            "DELETE FROM memory_items WHERE source = ?", (SEED_SOURCE,))
        await conn.commit()
        return cursor.rowcount
    finally:
        await conn.close()


async def clear_all_memory(db_path: Path) -> int:
    """Delete ALL memory items regardless of source."""
    conn = await get_connection(db_path)
    try:
        cursor = await conn.execute("DELETE FROM memory_items")
        await conn.commit()
        return cursor.rowcount
    finally:
        await conn.close()


async def main() -> None:
    clean_mode = "--clean" in sys.argv
    clean_all_mode = "--clean-all" in sys.argv

    settings = get_settings()
    workspace = settings.resolved_workspace

    # ── Validate environment ──────────────────────────────────────
    key = settings.active_provider_key
    provider = settings.llm_provider or "anthropic"
    if not key or key.startswith("your-"):
        print(f"⚠  Warning: {provider.upper()} API key is not configured.")
        print(f"   Set it in .env before running the agent.")
        print(f"   (Workspace files and memory will still be created.)\n")

    # ── Clean modes: wipe and recreate ────────────────────────────
    should_wipe_workspace = clean_mode or clean_all_mode
    if should_wipe_workspace and workspace.exists():
        shutil.rmtree(workspace)
        print(f"Removed existing workspace: {workspace}")

    # ── Create workspace files ────────────────────────────────────
    workspace.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0
    for rel_path, content in FILES.items():
        full_path = workspace / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if full_path.exists() and not should_wipe_workspace:
            skipped += 1
            continue
        full_path.write_text(content, encoding="utf-8")
        created += 1

    print(f"Workspace: {workspace}")
    print(f"  Created {created} file(s), skipped {skipped} existing file(s)")

    # ── Seed memory (idempotent: clear old seed data first) ───────
    await create_tables(settings.resolved_database)

    if clean_all_mode:
        deleted = await clear_all_memory(settings.resolved_database)
        if deleted:
            print(f"  Cleared ALL {deleted} memory item(s)")
    else:
        deleted = await clear_seed_memory(settings.resolved_database)
        if deleted:
            print(f"  Cleared {deleted} old seed memory item(s)")

    mm = MemoryManager(settings.resolved_database)

    for content, confidence in FACTS:
        await mm.store_fact(content=content, source=SEED_SOURCE, confidence=confidence)

    for content, summary in EPISODES:
        await mm.store_episode(content=content, summary=summary, source=SEED_SOURCE, confidence=0.9)

    total = len(FACTS) + len(EPISODES)
    print(f"  Seeded memory with {len(FACTS)} fact(s) and {len(EPISODES)} episode(s)")

    # ── Summary ───────────────────────────────────────────────────
    print()
    print("Demo setup complete! Try these prompts to exercise all tools:")
    print()
    print("  1. List files in the workspace")
    print("  2. Read the README and summarize the project")
    print("  3. Search for all TODO and FIXME items")
    print("  4. Read src/weather.py and src/cache.py together")
    print("  5. Create a file called IMPROVEMENTS.md with suggestions")
    print("  6. What do you know about this project?")
    print("  7. Read /etc/passwd  (should be blocked by policy)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
