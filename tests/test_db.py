"""Tests for read-only database access layer (db.py) verifying 3-layer security."""

import sqlite3
from pathlib import Path

import pytest

from supplychain.db import (
    get_as_of_date,
    get_inventory,
    get_meta,
    get_ro_connection,
    get_sales_window,
    get_signals,
    get_supplier_options,
)


def test_missing_db_raises():
    with pytest.raises(FileNotFoundError):
        get_ro_connection("nonexistent_path_to_db.db")


def test_three_layers_block_writes(tmp_path: Path):
    db_file = tmp_path / "test_supply.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE test_table(id TEXT PRIMARY KEY, val TEXT);")
    conn.execute("INSERT INTO test_table VALUES ('1', 'init');")
    conn.commit()
    conn.close()

    # Now open with get_ro_connection
    ro_conn = get_ro_connection(db_file)

    # 1. Verify read works
    row = ro_conn.execute("SELECT val FROM test_table WHERE id = '1'").fetchone()
    assert row["val"] == "init"

    # 2. INSERT fails (S1)
    with pytest.raises(sqlite3.DatabaseError):
        ro_conn.execute("INSERT INTO test_table VALUES ('2', 'fail')")

    # 3. UPDATE fails (S1)
    with pytest.raises(sqlite3.DatabaseError):
        ro_conn.execute("UPDATE test_table SET val = 'changed' WHERE id = '1'")

    # 4. DELETE fails (S1)
    with pytest.raises(sqlite3.DatabaseError):
        ro_conn.execute("DELETE FROM test_table WHERE id = '1'")

    # 5. DROP fails (S1)
    with pytest.raises(sqlite3.DatabaseError):
        ro_conn.execute("DROP TABLE test_table")

    # 6. ATTACH fails (S1)
    with pytest.raises(sqlite3.DatabaseError):
        ro_conn.execute("ATTACH DATABASE ':memory:' AS aux_db")

    ro_conn.close()


def test_fixed_functions_queries(tmp_path: Path):
    from scripts.build_db import build_database

    db_file = tmp_path / "supply.db"
    build_database(db_file, scenario_id="S01")

    # as_of_date
    as_of = get_as_of_date(db_file)
    assert as_of == "2026-10-19"

    # meta
    scenario_id = get_meta("scenario_id", db_file)
    assert scenario_id == "S01"

    # inventory
    inv = get_inventory("SKU0001", "WH-N", db_file)
    assert inv["on_hand"] >= 0
    assert inv["on_order"] >= 0

    # sales window
    sales_28 = get_sales_window("SKU0001", "WH-N", 28, db_file)
    assert len(sales_28) == 28
    assert sales_28[-1][0] == "2026-10-19"

    # supplier options
    sups = get_supplier_options("SKU0001", db_file)
    assert len(sups) >= 2
    assert sups[0]["is_primary"] == 1
    assert sups[0]["supplier_id"] == "SUP001"

    # signals
    signals = get_signals("SKU0001", db_path=db_file)
    assert len(signals) >= 1
    assert signals[0]["kind"] == "PROMO"
