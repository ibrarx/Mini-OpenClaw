"""skills/calculator — Safely evaluate a math expression by walking the AST (no eval/exec)."""
from __future__ import annotations
import ast
import math
import operator
from typing import Any, Callable

from apps.api.models.run import RiskLevel, ToolResult
from apps.api.models.tool_manifest import ToolManifest
from apps.api.skills.base import BaseTool, ToolContext

# Allowed binary operators → callables.
_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

# Allowed unary operators → callables.
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed callable names. NOTE: abs/round/min/max are builtins (they do NOT
# exist on the math module); the rest resolve from math.
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "ceil": math.ceil,
    "floor": math.floor,
    "pow": math.pow,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}

# Allowed constant names.
_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}


class _Disallowed(Exception):
    """Raised when the expression contains a node or name outside the allowlist."""


class CalculatorTool(BaseTool):
    """Stateless, safe arithmetic evaluator. Rejects anything outside a strict allowlist."""

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="calculator",
            description=(
                "Evaluate a mathematical expression safely. Supports +, -, *, /, **, %, "
                "parentheses, and common math functions (sqrt, sin, cos, tan, log, abs, "
                "round, min, max, pi, e)."
            ),
            risk_level=RiskLevel.SAFE,
            approval_required=False,
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate, e.g. 'sqrt(144) + 3 * (7 - 2)'",
                    },
                },
                "required": ["expression"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "result": {"type": "number"},
                },
                "required": ["expression", "result"],
            },
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = self._now()
        expr = args.get("expression", "")
        if not isinstance(expr, str) or not expr.strip():
            return self._error(args, "Expression must be a non-empty string.", started)

        try:
            tree = ast.parse(expr, mode="eval")
            result = self._eval(tree.body)
        except _Disallowed as exc:
            return self._error(args, f"Disallowed expression: {exc}", started)
        except SyntaxError as exc:
            return self._error(args, f"Could not parse expression: {exc.msg}", started)
        except ZeroDivisionError:
            return self._error(args, "Division by zero.", started)
        except (OverflowError, ValueError) as exc:
            return self._error(args, f"Math error: {exc}", started)
        except TypeError as exc:
            return self._error(args, f"Invalid operand: {exc}", started)

        # math functions can yield complex/bool/None — only finite real numbers pass.
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            return self._error(args, "Expression did not evaluate to a real number.", started)

        return self._success(args, {"expression": expr, "result": result}, started)

    def _eval(self, node: ast.AST) -> Any:
        """Recursively evaluate an allowlisted AST node. Raises _Disallowed otherwise."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise _Disallowed(f"non-numeric constant {node.value!r}")
            return node.value

        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if op is None:
                raise _Disallowed(f"operator {type(node.op).__name__}")
            return op(self._eval(node.left), self._eval(node.right))

        if isinstance(node, ast.UnaryOp):
            op = _UNARY_OPS.get(type(node.op))
            if op is None:
                raise _Disallowed(f"unary operator {type(node.op).__name__}")
            return op(self._eval(node.operand))

        if isinstance(node, ast.Name):
            if node.id in _CONSTS:
                return _CONSTS[node.id]
            raise _Disallowed(f"name {node.id!r}")

        if isinstance(node, ast.Call):
            # Only direct, positional calls to allowlisted names. Attribute access
            # is intentionally NOT permitted (it is the classic sandbox-escape vector,
            # e.g. (1).__class__.__bases__...).
            if not isinstance(node.func, ast.Name):
                raise _Disallowed("only direct function calls are allowed")
            fn = _FUNCS.get(node.func.id)
            if fn is None:
                raise _Disallowed(f"function {node.func.id!r}")
            if node.keywords:
                raise _Disallowed("keyword arguments are not allowed")
            return fn(*[self._eval(a) for a in node.args])

        raise _Disallowed(type(node).__name__)
