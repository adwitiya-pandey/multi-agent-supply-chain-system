"""Scenario evaluation tests (test_scenarios.py) per SPEC 16 and TASKS.md T11."""

import json
from pathlib import Path

import pytest

from scripts.build_db import build_database
from supplychain.models import CycleRequest
from supplychain.pipeline import run_cycle

SCENARIO_IDS = [f"S{i:02d}" for i in range(1, 11)]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_scenario_execution(scenario_id: str, tmp_path: Path, monkeypatch):
    """Test each scenario through run_cycle in oracle mode against its JSON contract."""
    scenario_path = Path("data/scenarios") / f"{scenario_id}.json"
    with open(scenario_path, encoding="utf-8") as f:
        meta = json.load(f)

    supply_db = tmp_path / f"supply_{scenario_id}.db"
    app_db = tmp_path / f"app_{scenario_id}.db"
    audit_file = tmp_path / f"audit_{scenario_id}.jsonl"

    build_database(supply_db, scenario_id=scenario_id)

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))

    req_data = meta["request"]
    req = CycleRequest(
        scenario_id=req_data["scenario_id"],
        sku_id=req_data["sku_id"],
        warehouse_id=req_data["warehouse_id"],
    )

    fault = "invalid_json" if scenario_id == "S10" else None
    result = run_cycle(req, mode="oracle", fault_mode=fault)

    expected = meta["expected"]

    # 1. Status assertion
    assert result.status == expected["status"], (
        f"Scenario {scenario_id} expected status {expected['status']}, got {result.status}"
    )

    # 2. Final escalation level assertion
    assert result.final_level == expected["final_level"], (
        f"Scenario {scenario_id} expected final_level {expected['final_level']}, got {result.final_level}"
    )

    # 3. Must-have findings assertion
    if expected.get("must_have_findings"):
        assert result.qa is not None, f"Scenario {scenario_id} expected QA report but got None"
        actual_codes = {f.code for f in result.qa.findings}
        for code in expected["must_have_findings"]:
            assert code in actual_codes, (
                f"Scenario {scenario_id} missing mandatory finding {code}. Found: {actual_codes}"
            )

    # 4. PO existence assertion
    if expected.get("po_expected") is True:
        assert result.supplier is not None
        assert result.supplier.po_draft is not None
        assert result.supplier.po_draft.qty > 0
        assert result.supplier.po_draft.total > 0
    elif expected.get("po_expected") is False:
        if result.supplier and result.supplier.po_draft:
            assert result.supplier.po_draft.qty == 0 or result.status in (
                "FAILED",
                "NO_ACTION_NEEDED",
            )
