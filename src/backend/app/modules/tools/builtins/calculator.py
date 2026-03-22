"""
Built-in calculator tool.

Safely evaluates arithmetic expressions using Python's ast module.
NEVER uses eval() or exec() — only numeric literals and arithmetic
operators (+, -, *, /, **, %, //) are permitted.

Input:  { expression: str }
Output: { result: float, expression_parsed: str }
"""
import ast
import operator
from typing import Any, Union

import structlog

logger = structlog.get_logger()

# Supported binary operators — no function calls, no attribute access
_SAFE_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Supported unary operators
_SAFE_UNOPS: dict[type, Any] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_MAX_EXPRESSION_LENGTH = 512
_MAX_INTERMEDIATE_VALUE = 1e300  # Guard against runaway exponentiation


def _safe_eval(node: ast.AST) -> Union[int, float]:
    """
    Recursively evaluate an AST node.
    Only numeric literals, binary ops, and unary ops are permitted.
    Raises ValueError for any unsupported construct.
    """
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported literal type: {type(node.value).__name__}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_BINOPS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        # Guard against division by zero
        if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
            raise ValueError("Division by zero")
        # Guard against exponent explosion
        if op_type is ast.Pow and abs(right) > 300:
            raise ValueError("Exponent too large (max 300)")
        result = _SAFE_BINOPS[op_type](left, right)
        if abs(result) > _MAX_INTERMEDIATE_VALUE:
            raise ValueError("Intermediate result exceeds maximum allowed value")
        return result
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_UNOPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand)
        return _SAFE_UNOPS[op_type](operand)
    raise ValueError(
        f"Unsupported expression node: {type(node).__name__}. "
        "Only numeric literals and arithmetic operators are permitted."
    )


async def calculator(expression: str, **_kwargs: Any) -> dict:
    """
    Evaluate a mathematical expression safely.

    Args:
        expression: An arithmetic expression string.
                    Allowed: +, -, *, /, **, %, // and numeric literals.
                    NOT allowed: function calls, variables, string operations.

    Returns:
        dict with 'result' (float) and 'expression_parsed' (str).

    Raises:
        ValueError: If the expression is unsafe, malformed, or overflows.
    """
    if not isinstance(expression, str):
        raise ValueError("expression must be a string")
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"Expression too long (max {_MAX_EXPRESSION_LENGTH} characters)"
        )

    expression_stripped = expression.strip()
    if not expression_stripped:
        raise ValueError("expression must not be empty")

    try:
        tree = ast.parse(expression_stripped, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {exc}") from exc

    result = _safe_eval(tree)
    result_float = float(result)

    logger.info(
        "calculator_evaluated",
        expression_length=len(expression_stripped),
        result_is_finite=abs(result_float) < float("inf"),
    )

    return {
        "result": result_float,
        "expression_parsed": expression_stripped,
    }
