"""App database persistence for decision cycles, human approvals, and purchase orders.

Enforces append-only semantics using SQLite triggers.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from supplychain.config import get_settings
from supplychain.models import CycleResult

APP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cycles(
    cycle_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    final_level TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS abort_cycles_update
BEFORE UPDATE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles table is append-only: updates not permitted');
END;

CREATE TRIGGER IF NOT EXISTS abort_cycles_delete
BEFORE DELETE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles table is append-only: deletes not permitted');
END;

CREATE TABLE IF NOT EXISTS approvals(
    cycle_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS abort_approvals_update
BEFORE UPDATE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals table is append-only: updates not permitted');
END;

CREATE TRIGGER IF NOT EXISTS abort_approvals_delete
BEFORE DELETE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals table is append-only: deletes not permitted');
END;

CREATE TABLE IF NOT EXISTS purchase_orders(
    po_id TEXT PRIMARY KEY,
    cycle_id TEXT UNIQUE NOT NULL,
    supplier_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total REAL NOT NULL,
    requested_delivery_date TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS abort_po_update
BEFORE UPDATE ON purchase_orders
BEGIN
    SELECT RAISE(ABORT, 'purchase_orders table is append-only: updates not permitted');
END;

CREATE TRIGGER IF NOT EXISTS abort_po_delete
BEFORE DELETE ON purchase_orders
BEGIN
    SELECT RAISE(ABORT, 'purchase_orders table is append-only: deletes not permitted');
END;
"""


def init_app_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Initialize app database schema and triggers."""
    path = Path(db_path or get_settings().app_db).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(APP_SCHEMA_SQL)
    conn.commit()
    return conn


def save_cycle(result: CycleResult, db_path: str | Path | None = None) -> None:
    """Save completed or failed cycle to cycles table."""
    conn = init_app_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO cycles(cycle_id, created_at, status, final_level, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                result.cycle_id,
                result.created_at,
                result.status,
                result.final_level,
                result.model_dump_json(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_cycle(cycle_id: str, db_path: str | Path | None = None) -> CycleResult | None:
    """Retrieve cycle result by cycle_id."""
    conn = init_app_db(db_path)
    try:
        row = conn.execute(
            "SELECT result_json FROM cycles WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        if not row:
            return None
        return CycleResult.model_validate_json(row["result_json"])
    finally:
        conn.close()


def list_pending(db_path: str | Path | None = None) -> list[CycleResult]:
    """List cycles waiting for human approval."""
    conn = init_app_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT result_json FROM cycles
            WHERE status = 'PENDING_APPROVAL'
              AND cycle_id NOT IN (SELECT cycle_id FROM approvals)
            ORDER BY created_at ASC
            """
        ).fetchall()
        return [CycleResult.model_validate_json(r["result_json"]) for r in rows]
    finally:
        conn.close()


def list_history(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """List decision history with approvals and purchase orders."""
    conn = init_app_db(db_path)
    try:
        query = """
            SELECT
                c.cycle_id,
                c.created_at,
                c.status,
                c.final_level,
                a.decision,
                a.reviewer,
                a.note,
                a.decided_at,
                po.po_id,
                po.total as po_total
            FROM cycles c
            LEFT JOIN approvals a ON c.cycle_id = a.cycle_id
            LEFT JOIN purchase_orders po ON c.cycle_id = po.cycle_id
            ORDER BY c.created_at DESC
        """
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def finalise_po(
    conn: sqlite3.Connection,
    result: CycleResult,
    approved_by: str,
) -> str:
    """Finalise purchase order row in database within an existing transaction.

    Crucial: Copies fields ONLY from stored result.supplier.po_draft, never external inputs.
    """
    if not result.supplier or not result.supplier.po_draft:
        raise ValueError(f"Cycle {result.cycle_id} has no PO draft to finalise")

    po = result.supplier.po_draft
    po_id = f"PO-{result.cycle_id.replace('CYC-', '')}-{uuid4().hex[:4].upper()}"
    now_iso = datetime.now(UTC).isoformat()

    conn.execute(
        """
        INSERT INTO purchase_orders(
            po_id, cycle_id, supplier_id, sku_id, warehouse_id,
            qty, unit_cost, total, requested_delivery_date, approved_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            po_id,
            result.cycle_id,
            po.supplier_id,
            po.sku_id,
            po.warehouse_id,
            po.qty,
            po.unit_cost,
            po.total,
            po.requested_delivery_date.isoformat(),
            approved_by,
            now_iso,
        ),
    )
    return po_id
