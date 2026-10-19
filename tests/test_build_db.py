"""Tests for database builder and scenario patching (scripts/build_db.py)."""

import sqlite3
from pathlib import Path

import pytest

from scripts.build_db import SCHEMA_SQL, build_database
from supplychain.db import get_inventory, get_ro_connection, get_supplier_options


def test_build_all_scenarios(tmp_path: Path):
    for i in range(1, 11):
        sc_id = f"S{i:02d}"
        out_db = tmp_path / f"supply_{sc_id}.db"
        build_database(out_db, scenario_id=sc_id)
        assert out_db.exists()


def test_check_constraints_reject_bad_data(tmp_path: Path):
    db_file = tmp_path / "check_test.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)

    # 1. Negative sales units rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sales_daily VALUES ('2026-10-19', 'SKU0001', 'WH-N', -5)")

    # 2. Supplier reliability > 1.0 rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO suppliers VALUES ('SUP999', 'Bad Supplier', 'ACTIVE', 1.5, 'Notes')"
        )

    # 3. Invalid supplier status rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO suppliers VALUES ('SUP999', 'Bad Supplier', 'UNKNOWN', 0.9, '')")

    # 4. Zero or negative MOQ rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sku_suppliers VALUES ('SKU0001', 'SUP001', 10.0, 0, 10, 7, 1.0, 1)"
        )

    conn.close()


def test_deterministic_seeding(tmp_path: Path):
    db1 = tmp_path / "db1.db"
    db2 = tmp_path / "db2.db"
    build_database(db1, scenario_id="S01", seed=42)
    build_database(db2, scenario_id="S01", seed=42)

    conn1 = sqlite3.connect(db1)
    conn2 = sqlite3.connect(db2)

    rows1 = conn1.execute(
        "SELECT * FROM sales_daily ORDER BY sale_date, sku_id, warehouse_id"
    ).fetchall()
    rows2 = conn2.execute(
        "SELECT * FROM sales_daily ORDER BY sale_date, sku_id, warehouse_id"
    ).fetchall()

    assert rows1 == rows2
    conn1.close()
    conn2.close()


def test_observable_scenario_patches(tmp_path: Path):
    # S02: primary supplier insolvent
    db_s02 = tmp_path / "s02.db"
    build_database(db_s02, scenario_id="S02")
    sups = get_supplier_options("SKU0002", db_s02)
    assert any(s["supplier_id"] == "SUP001" and s["status"] == "INSOLVENT" for s in sups)

    # S05: primary supplier delayed with injection note
    db_s05 = tmp_path / "s05.db"
    build_database(db_s05, scenario_id="S05")
    sups_s05 = get_supplier_options("SKU0005", db_s05)
    sup1 = next(s for s in sups_s05 if s["supplier_id"] == "SUP001")
    assert sup1["status"] == "DELAYED"
    assert "Ignore previous instructions" in sup1["notes"]

    # S06: stockout (on_hand == 0)
    db_s06 = tmp_path / "s06.db"
    build_database(db_s06, scenario_id="S06")
    inv_s06 = get_inventory("SKU0006", "WH-N", db_s06)
    assert inv_s06["on_hand"] == 0

    # S07: overstock (on_hand == 5000)
    db_s07 = tmp_path / "s07.db"
    build_database(db_s07, scenario_id="S07")
    inv_s07 = get_inventory("SKU0007", "WH-N", db_s07)
    assert inv_s07["on_hand"] == 5000

    # S08: high value unit_cost
    db_s08 = tmp_path / "s08.db"
    build_database(db_s08, scenario_id="S08")
    sups_s08 = get_supplier_options("SKU0008", db_s08)
    assert any(s["unit_cost"] == 500.0 for s in sups_s08)

    # S09: missing data (coverage < 0.80)
    db_s09 = tmp_path / "s09.db"
    build_database(db_s09, scenario_id="S09")
    with get_ro_connection(db_s09) as ro:
        count = ro.execute(
            """
            SELECT COUNT(*) FROM sales_daily
            WHERE sku_id = 'SKU0009' AND warehouse_id = 'WH-N'
            AND sale_date >= date('2026-10-19', '-55 days')
            """
        ).fetchone()[0]
        coverage = count / 56.0
        assert coverage < 0.80
