"""Tests for the three feedback-driven utility tools (get_datetime, calculator, system_info)."""
from __future__ import annotations
from pathlib import Path

import pytest

from apps.api.skills.base import ToolContext
from apps.api.skills.calculator import CalculatorTool
from apps.api.skills.get_datetime import GetDatetimeTool
from apps.api.skills.system_info import SystemInfoTool


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=str(workspace), run_id="test_run", step_id="test_step")


# ── get_datetime ─────────────────────────────────────────────────


class TestGetDatetime:
    @pytest.mark.asyncio
    async def test_default_is_utc(self, tmp_path: Path) -> None:
        r = await GetDatetimeTool().execute({}, _ctx(tmp_path))
        assert r.status == "success"
        assert r.output["timezone"] == "UTC"
        assert r.output["utc_offset"] == "+00:00"
        assert isinstance(r.output["unix_timestamp"], float)

    @pytest.mark.asyncio
    async def test_explicit_timezone(self, tmp_path: Path) -> None:
        r = await GetDatetimeTool().execute({"timezone": "Europe/Vienna"}, _ctx(tmp_path))
        assert r.status == "success"
        assert r.output["timezone"] == "Europe/Vienna"
        # Vienna is CET (+01:00) or CEST (+02:00) depending on DST.
        assert r.output["utc_offset"] in ("+01:00", "+02:00")

    @pytest.mark.asyncio
    async def test_invalid_timezone_returns_error(self, tmp_path: Path) -> None:
        r = await GetDatetimeTool().execute({"timezone": "Mars/Olympus_Mons"}, _ctx(tmp_path))
        assert r.status == "error"
        assert r.output is None


# ── calculator ───────────────────────────────────────────────────


class TestCalculator:
    @pytest.mark.asyncio
    async def test_basic_arithmetic(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "2 + 3"}, _ctx(tmp_path))
        assert r.status == "success"
        assert r.output["result"] == 5

    @pytest.mark.asyncio
    async def test_sqrt(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "sqrt(144)"}, _ctx(tmp_path))
        assert r.status == "success"
        assert r.output["result"] == 12

    @pytest.mark.asyncio
    async def test_compound_expression(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute(
            {"expression": "sqrt(144) + 3 * (7 - 2)"}, _ctx(tmp_path)
        )
        assert r.status == "success"
        assert r.output["result"] == 27

    @pytest.mark.asyncio
    async def test_division_by_zero_returns_error(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "1 / 0"}, _ctx(tmp_path))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_code_injection_rejected(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "__import__('os')"}, _ctx(tmp_path))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_attribute_escape_rejected(self, tmp_path: Path) -> None:
        # Dunder traversal via attribute access must be blocked.
        r = await CalculatorTool().execute({"expression": "(1).__class__"}, _ctx(tmp_path))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_natural_log(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "ln(e)"}, _ctx(tmp_path))
        assert r.status == "success"
        assert abs(r.output["result"] - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_exp(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "exp(0)"}, _ctx(tmp_path))
        assert r.status == "success"
        assert r.output["result"] == 1.0

    @pytest.mark.asyncio
    async def test_caret_is_not_power(self, tmp_path: Path) -> None:
        # '^' is XOR in Python; the tool must reject it rather than miscompute.
        r = await CalculatorTool().execute({"expression": "2^3"}, _ctx(tmp_path))
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_full_expression_with_ln_and_exp(self, tmp_path: Path) -> None:
        # x=17, y=12, z=5 — uses ** for powers (not ^), ln and exp.
        expr = "((sqrt(17**3 - 12**2) + ln(12 * 5)) / (5**2 - sqrt(17 + 12))) + exp(5 - 12 + 7)"
        r = await CalculatorTool().execute({"expression": expr}, _ctx(tmp_path))
        assert r.status == "success"
        assert abs(r.output["result"] - 4.7295) < 1e-2

    @pytest.mark.asyncio
    async def test_unknown_name_rejected(self, tmp_path: Path) -> None:
        r = await CalculatorTool().execute({"expression": "foo + 1"}, _ctx(tmp_path))
        assert r.status == "error"


# ── system_info ──────────────────────────────────────────────────


class TestSystemInfo:
    @pytest.mark.asyncio
    async def test_all_returns_core_sections(self, tmp_path: Path) -> None:
        r = await SystemInfoTool().execute({"sections": ["all"]}, _ctx(tmp_path))
        assert r.status == "success"
        for key in ("cpu", "memory", "disk", "platform"):
            assert key in r.output

    @pytest.mark.asyncio
    async def test_single_section_only(self, tmp_path: Path) -> None:
        r = await SystemInfoTool().execute({"sections": ["cpu"]}, _ctx(tmp_path))
        assert r.status == "success"
        assert set(r.output.keys()) == {"cpu"}

    @pytest.mark.asyncio
    async def test_default_is_all(self, tmp_path: Path) -> None:
        r = await SystemInfoTool().execute({}, _ctx(tmp_path))
        assert r.status == "success"
        assert "platform" in r.output

    @pytest.mark.asyncio
    async def test_invalid_section_only_returns_error(self, tmp_path: Path) -> None:
        r = await SystemInfoTool().execute({"sections": ["gpu"]}, _ctx(tmp_path))
        assert r.status == "error"
