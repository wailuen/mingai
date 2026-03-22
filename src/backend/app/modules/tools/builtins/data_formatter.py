"""
Built-in data_formatter tool.

Normalises structured data between formats: JSON, CSV, Markdown table.

Input:  { data: any, input_format: str, output_format: str }
Output: { formatted: str }
"""
import csv
import io
import json
from typing import Any

import structlog

logger = structlog.get_logger()

_SUPPORTED_FORMATS = {"json", "csv", "markdown_table"}
_MAX_DATA_SIZE = 1_000_000  # 1 MB string limit


def _parse_json(raw: Any) -> list[dict]:
    """Parse JSON input into a list of dicts."""
    if isinstance(raw, str):
        if len(raw) > _MAX_DATA_SIZE:
            raise ValueError(f"Data too large (max {_MAX_DATA_SIZE} characters)")
        parsed = json.loads(raw)
    else:
        parsed = raw

    if isinstance(parsed, list):
        return [row if isinstance(row, dict) else {"value": row} for row in parsed]
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError("JSON input must be an array of objects or a single object")


def _parse_csv(raw: str) -> list[dict]:
    """Parse CSV string into list of dicts."""
    if not isinstance(raw, str):
        raise ValueError("CSV input must be a string")
    if len(raw) > _MAX_DATA_SIZE:
        raise ValueError(f"Data too large (max {_MAX_DATA_SIZE} characters)")
    reader = csv.DictReader(io.StringIO(raw.strip()))
    return [dict(row) for row in reader]


def _parse_markdown_table(raw: str) -> list[dict]:
    """Parse a simple Markdown table into list of dicts."""
    if not isinstance(raw, str):
        raise ValueError("Markdown table input must be a string")
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("Markdown table must have at least a header and separator row")

    def _split_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    headers = _split_row(lines[0])
    rows = []
    for line in lines[2:]:  # Skip separator (line index 1)
        if line.startswith("|") or "|" in line:
            cells = _split_row(line)
            rows.append(dict(zip(headers, cells)))
    return rows


def _to_json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    headers = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _to_markdown_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    header_row = "| " + " | ".join(str(h) for h in headers) + " |"
    data_rows = [
        "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator] + data_rows)


_PARSERS = {
    "json": _parse_json,
    "csv": _parse_csv,
    "markdown_table": _parse_markdown_table,
}

_FORMATTERS = {
    "json": _to_json,
    "csv": _to_csv,
    "markdown_table": _to_markdown_table,
}


async def data_formatter(
    data: Any,
    input_format: str,
    output_format: str,
    **_kwargs: Any,
) -> dict:
    """
    Convert data between JSON, CSV, and Markdown table formats.

    Args:
        data: Input data (string for CSV/Markdown, any for JSON).
        input_format: One of 'json', 'csv', 'markdown_table'.
        output_format: One of 'json', 'csv', 'markdown_table'.

    Returns:
        dict with 'formatted' (output string).
    """
    if input_format not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported input_format '{input_format}'. "
            f"Allowed: {sorted(_SUPPORTED_FORMATS)}"
        )
    if output_format not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported output_format '{output_format}'. "
            f"Allowed: {sorted(_SUPPORTED_FORMATS)}"
        )

    rows = _PARSERS[input_format](data)
    formatted = _FORMATTERS[output_format](rows)

    logger.info(
        "data_formatter_completed",
        input_format=input_format,
        output_format=output_format,
        row_count=len(rows),
    )
    return {"formatted": formatted}
