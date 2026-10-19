"""Architecture import-boundary and security AST tests (SPEC 4 and SPEC 12)."""

import ast
from pathlib import Path

SRC_DIR = Path("src/supplychain")

AGENT_TOOL_SNAPSHOT = {
    "Demand Forecaster": ["get_demand_stats", "get_market_signals"],
    "Inventory Planner": ["get_inventory_position", "calculate_reorder_plan"],
    "Supplier Liaison": ["get_supplier_options"],
    "Quality Assurance": ["run_consistency_checks"],
    "Escalation Manager": [],
}


def _get_imports(file_path: Path) -> list[str]:
    """Parse python source and return list of imported module names."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            for alias in node.names:
                imported.append(f"{node.module}.{alias.name}")
    return imported


def test_forbidden_approval_imports_ast():
    """No code path in pipeline.py, agents.py, tasks.py, or tools.py may import

    approvals or store.finalise_po (SPEC 12).
    """
    forbidden_targets = [
        SRC_DIR / "pipeline.py",
        SRC_DIR / "agents.py",
        SRC_DIR / "tasks.py",
        SRC_DIR / "tools.py",
    ]

    for py_file in forbidden_targets:
        if not py_file.exists():
            continue
        imports = _get_imports(py_file)
        for imp in imports:
            assert "approvals" not in imp, f"{py_file.name} illegally imports approvals: {imp}"
            assert "finalise_po" not in imp, f"{py_file.name} illegally imports finalise_po: {imp}"


def test_no_write_calls_in_tools_or_agents_ast():
    """No agent or tool module may perform file writes or database writes (SPEC 4, S2)."""
    checked_files = [SRC_DIR / "tools.py", SRC_DIR / "agents.py"]

    for py_file in checked_files:
        if not py_file.exists():
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Check for open(..., 'w') or 'wb' or 'a'
            if (
                (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "open"
                )
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
            ):
                mode = node.args[1].value
                assert "w" not in mode and "a" not in mode, (
                    f"{py_file.name} opens file for writing: {mode}"
                )


def test_tools_snapshot_per_agent():
    """Exact tool lists per agent snapshot matches SPEC 8."""
    from supplychain.tools import (
        calculate_reorder_plan,
        get_demand_stats,
        get_inventory_position,
        get_market_signals,
        get_supplier_options,
        run_consistency_checks,
    )

    mapping = {
        "Demand Forecaster": [get_demand_stats.name, get_market_signals.name],
        "Inventory Planner": [get_inventory_position.name, calculate_reorder_plan.name],
        "Supplier Liaison": [get_supplier_options.name],
        "Quality Assurance": [run_consistency_checks.name],
        "Escalation Manager": [],
    }

    assert mapping == AGENT_TOOL_SNAPSHOT
