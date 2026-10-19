"""Read-only database access layer with three layers of defense."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from supplychain.config import get_settings

# Permitted SQLite authorizer action codes
# SQLITE_SELECT = 21, SQLITE_READ = 20, SQLITE_FUNCTION = 31
ALLOWED_SQLITE_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}


def _sqlite_authorizer(
    action_code: int,
    arg1: str | None,
    arg2: str | None,
    db_name: str | None,
    trigger_name: str | None,
) -> int:
    """Authorizer callback allowing only read operations (SQLITE_SELECT, SQLITE_READ, SQLITE_FUNCTION)."""
    if action_code in ALLOWED_SQLITE_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def get_ro_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with 3 layers of read-only enforcement:

    1. URI mode=ro
    2. PRAGMA query_only=ON
    3. Python sqlite3 authorizer denying anything other than SELECT/READ/FUNCTION
    """
    path = Path(db_path or get_settings().supply_db).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found at {path}")

    # Layer 1: file: URI with mode=ro
    uri_path = f"file:{quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri_path, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row

    # Layer 2: PRAGMA query_only = ON
    conn.execute("PRAGMA query_only = ON;")

    # Layer 3: Authorizer
    conn.set_authorizer(_sqlite_authorizer)

    return conn


def get_as_of_date(db_path: str | Path | None = None) -> str:
    """Retrieve as_of_date from meta table."""
    with get_ro_connection(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", ("as_of_date",)).fetchone()
        if not row:
            raise ValueError("as_of_date not found in meta table")
        return str(row["value"])


def get_meta(key: str, db_path: str | Path | None = None) -> str | None:
    """Retrieve arbitrary meta value by key."""
    with get_ro_connection(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None


def get_sales_window(
    sku_id: str,
    warehouse_id: str,
    days: int,
    db_path: str | Path | None = None,
) -> list[tuple[str, int]]:
    """Retrieve (sale_date, units) for the last N days up to as_of_date."""
    as_of = get_as_of_date(db_path)
    query = """
        SELECT sale_date, units
        FROM sales_daily
        WHERE sku_id = ? AND warehouse_id = ? AND sale_date <= ?
        ORDER BY sale_date DESC
        LIMIT ?
    """
    with get_ro_connection(db_path) as conn:
        rows = conn.execute(query, (sku_id, warehouse_id, as_of, days)).fetchall()
        # Return chronologically ascending (oldest to newest)
        results = [(str(r["sale_date"]), int(r["units"])) for r in rows]
        results.reverse()
        return results


def get_inventory(
    sku_id: str,
    warehouse_id: str,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Retrieve inventory position (on_hand, on_order)."""
    query = """
        SELECT on_hand, on_order
        FROM inventory
        WHERE sku_id = ? AND warehouse_id = ?
    """
    with get_ro_connection(db_path) as conn:
        row = conn.execute(query, (sku_id, warehouse_id)).fetchone()
        if not row:
            return {"on_hand": 0, "on_order": 0}
        return {"on_hand": int(row["on_hand"]), "on_order": int(row["on_order"])}


def get_supplier_options(
    sku_id: str,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve supplier options for a SKU."""
    query = """
        SELECT
            ss.sku_id,
            ss.supplier_id,
            s.name,
            s.status,
            s.reliability,
            s.notes,
            ss.unit_cost,
            ss.moq,
            ss.pack_size,
            ss.lead_time_days,
            ss.lead_time_std,
            ss.is_primary
        FROM sku_suppliers ss
        JOIN suppliers s ON ss.supplier_id = s.supplier_id
        WHERE ss.sku_id = ?
        ORDER BY ss.is_primary DESC, ss.unit_cost ASC
    """
    with get_ro_connection(db_path) as conn:
        rows = conn.execute(query, (sku_id,)).fetchall()
        return [dict(r) for r in rows]


def get_signals(
    sku_id: str,
    since: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve market signals for a SKU."""
    if since:
        query = """
            SELECT signal_id, sku_id, signal_date, kind, note
            FROM market_signals
            WHERE sku_id = ? AND signal_date >= ?
            ORDER BY signal_date ASC
        """
        params = (sku_id, since)
    else:
        query = """
            SELECT signal_id, sku_id, signal_date, kind, note
            FROM market_signals
            WHERE sku_id = ?
            ORDER BY signal_date ASC
        """
        params = (sku_id,)

    with get_ro_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
