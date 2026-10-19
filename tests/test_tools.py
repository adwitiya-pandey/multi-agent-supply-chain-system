"""Tests for CrewAI tools (tools.py)."""

import json
from pathlib import Path

from scripts.build_db import build_database
from supplychain.tools import (
    calculate_reorder_plan,
    get_demand_stats,
    get_inventory_position,
    get_market_signals,
    get_supplier_options,
    run_consistency_checks,
)


def test_get_demand_stats_valid(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "supply.db"
    build_database(db_file, scenario_id="S01")
    monkeypatch.setenv("SUPPLY_DB", str(db_file))

    res_json = get_demand_stats.run(sku="SKU0001", wh="WH-N")
    data = json.loads(res_json)
    assert data["sku"] == "SKU0001"
    assert data["wh"] == "WH-N"
    assert "daily_demand_mean" in data
    assert "method_a_daily" in data
    assert "method_b_daily" in data
    assert "data_coverage" in data


def test_get_demand_stats_invalid_id():
    # Bad SKU format with trailing newline
    res = get_demand_stats.run(sku="SKU0001\n", wh="WH-N")
    data = json.loads(res)
    assert "error" in data


def test_get_demand_stats_unknown_sku(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "supply.db"
    build_database(db_file, scenario_id="S01")
    monkeypatch.setenv("SUPPLY_DB", str(db_file))

    res = get_demand_stats.run(sku="SKU9999", wh="WH-N")
    data = json.loads(res)
    assert "error" in data


def test_get_market_signals_wrapped_and_flagged(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "supply.db"
    build_database(db_file, scenario_id="S01")
    monkeypatch.setenv("SUPPLY_DB", str(db_file))

    res = get_market_signals.run(sku="SKU0001")
    data = json.loads(res)
    assert "signals" in data
    for sig in data["signals"]:
        assert sig["note"].startswith("<untrusted>")
        assert sig["note"].endswith("</untrusted>")


def test_get_inventory_position_valid(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "supply.db"
    build_database(db_file, scenario_id="S01")
    monkeypatch.setenv("SUPPLY_DB", str(db_file))

    res = get_inventory_position.run(sku="SKU0001", wh="WH-N")
    data = json.loads(res)
    assert data["on_hand"] >= 0
    assert data["on_order"] >= 0


def test_calculate_reorder_plan_valid():
    res = calculate_reorder_plan.run(
        on_hand=50,
        on_order=0,
        daily_demand=10.0,
        daily_demand_std=2.0,
        lead_time_days=7,
        lead_time_std=1.0,
        service_level=0.95,
    )
    data = json.loads(res)
    assert data["action"] == "ORDER"
    assert data["safety_stock"] == 19
    assert data["reorder_point"] == 89
    assert data["needed_qty"] == 109


def test_get_supplier_options_hostile_note_flagged(tmp_path: Path, monkeypatch):
    # S05 has hostile injection note in SUP001
    db_file = tmp_path / "supply_s05.db"
    build_database(db_file, scenario_id="S05")
    monkeypatch.setenv("SUPPLY_DB", str(db_file))

    res = get_supplier_options.run(sku="SKU0005")
    data = json.loads(res)
    sups = data["suppliers"]
    sup1 = next(s for s in sups if s["supplier_id"] == "SUP001")
    assert sup1["notes"].startswith("<untrusted>")
    assert sup1["note_flagged"] is True


def test_run_consistency_checks():
    # Matching quantity and total
    res = run_consistency_checks.run(
        po_qty=110,
        needed_qty=109,
        moq=50,
        pack_size=10,
        po_total=2200.0,
        unit_cost=20.0,
    )
    data = json.loads(res)
    assert data["passed"] is True
    assert data["expected_qty"] == 110

    # Mismatched quantity
    res_bad = run_consistency_checks.run(
        po_qty=999,
        needed_qty=109,
        moq=50,
        pack_size=10,
        po_total=2200.0,
        unit_cost=20.0,
    )
    data_bad = json.loads(res_bad)
    assert data_bad["passed"] is False
    assert len(data_bad["findings"]) > 0
