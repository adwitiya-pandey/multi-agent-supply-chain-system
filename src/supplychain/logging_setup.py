"""Structured logging setup using structlog with JSON output and contextvars."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

# Explicitly forbidden field keys that must NEVER appear in logs
FORBIDDEN_LOG_KEYS = {
    "note",
    "notes",
    "supplier_notes",
    "reviewer_note",
    "reviewer_notes",
    "body",
    "email_body",
    "prompt",
    "prompts",
    "rationale",
    "summary",
    "gemini_api_key",
    "api_key",
    "secret",
    "password",
    "token",
}

# Permitted domain keys (ids, counts, codes, token counts, costs, durations, booleans, hashes)
PERMITTED_DATA_KEYS = {
    "cycle_id",
    "agent",
    "task",
    "sku_id",
    "warehouse_id",
    "supplier_id",
    "scenario_id",
    "po_id",
    "status",
    "policy_level",
    "final_level",
    "verdict",
    "decision",
    "reviewer",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "budget_usd",
    "duration_seconds",
    "code",
    "severity",
    "finding_codes",
    "sha256",
    "count",
    "retries",
    "success",
    "on_hand",
    "on_order",
    "reorder_point",
    "target_level",
    "safety_stock",
    "needed_qty",
    "qty",
    "unit_cost",
    "total",
    "is_primary",
    "moq",
    "pack_size",
    "lead_time_days",
    "error",
}

STANDARD_STRUCTLOG_KEYS = {
    "event",
    "level",
    "timestamp",
    "logger",
    "logger_name",
    "exception",
    "exc_info",
    "stack_info",
}


def sanitize_log_event(
    logger: logging.Logger | None, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Filter out any unapproved fields or secret/untrusted payload text."""
    clean_dict: dict[str, Any] = {}
    for key, value in event_dict.items():
        lower_key = key.lower()
        # Drop forbidden keys
        if lower_key in FORBIDDEN_LOG_KEYS or any(
            f in lower_key for f in ("key", "secret", "note", "body", "prompt")
        ):
            continue

        # Keep standard structlog keys and permitted domain keys
        if key in STANDARD_STRUCTLOG_KEYS or lower_key in PERMITTED_DATA_KEYS:
            clean_dict[key] = value

    return clean_dict


def setup_logging(log_level: str = "INFO", log_file: str | None = "logs/app.log") -> None:
    """Configure structlog for standard JSON output and optional file logging."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Standard library root logger configuration
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(format="%(message)s", level=level, handlers=handlers, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            sanitize_log_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "supplychain") -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance."""
    return structlog.get_logger(name)
