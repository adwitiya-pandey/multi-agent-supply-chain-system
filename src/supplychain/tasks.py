"""CrewAI task definitions per SPEC 8 and 9."""

from __future__ import annotations

from typing import Any

from crewai import Agent, Task

from supplychain.guardrails import (
    build_escalation_guardrail,
    build_forecast_guardrail,
    build_inventory_guardrail,
    build_qa_guardrail,
    build_supplier_guardrail,
)
from supplychain.models import (
    EscalationDecision,
    ForecastMessage,
    InventoryPlanMessage,
    QAReport,
    SupplierMessage,
)


def create_tasks(
    agents: dict[str, Agent],
    request_params: dict[str, str],
    facts: dict[str, Any],
) -> list[Task]:
    """Create the 5 sequential CrewAI tasks with Pydantic outputs and deterministic guardrails."""
    cycle_id = request_params["cycle_id"]
    sku_id = request_params["sku_id"]
    warehouse_id = request_params["warehouse_id"]

    # 1. Demand Forecast Task
    t1_forecast = Task(
        description=(
            f"Analyze sales data and market signals for SKU {sku_id} at warehouse {warehouse_id} "
            f"(cycle {cycle_id}). Compute baseline Method A and Method B statistics using get_demand_stats. "
            "Return a ForecastMessage."
        ),
        expected_output="JSON conforming to ForecastMessage schema",
        agent=agents["forecaster"],
        output_pydantic=ForecastMessage,
        guardrail=build_forecast_guardrail(facts.get("forecast", {})),
        guardrail_max_retries=2,
    )

    # 2. Inventory Planning Task
    t2_inventory = Task(
        description=(
            f"Evaluate inventory position for {sku_id} at {warehouse_id} (cycle {cycle_id}). "
            "Use get_inventory_position and calculate_reorder_plan to determine replenishment requirements. "
            "Return an InventoryPlanMessage."
        ),
        expected_output="JSON conforming to InventoryPlanMessage schema",
        agent=agents["planner"],
        output_pydantic=InventoryPlanMessage,
        context=[t1_forecast],
        guardrail=build_inventory_guardrail(facts.get("inventory", {})),
        guardrail_max_retries=2,
    )

    # 3. Supplier Liaison Task
    t3_supplier = Task(
        description=(
            f"Select eligible supplier for {sku_id} (cycle {cycle_id}) using get_supplier_options. "
            "If an order is needed, compute pack-rounded quantities and draft vendor email. "
            "Return a SupplierMessage."
        ),
        expected_output="JSON conforming to SupplierMessage schema",
        agent=agents["supplier"],
        output_pydantic=SupplierMessage,
        context=[t2_inventory],
        guardrail=build_supplier_guardrail(facts.get("supplier", {})),
        guardrail_max_retries=2,
    )

    # 4. QA Task
    t4_qa = Task(
        description=(
            f"Audit inter-agent messages for cycle {cycle_id} against consistency rules QA01 through QA14. "
            "Return a QAReport."
        ),
        expected_output="JSON conforming to QAReport schema",
        agent=agents["qa"],
        output_pydantic=QAReport,
        context=[t1_forecast, t2_inventory, t3_supplier],
        guardrail=build_qa_guardrail(facts.get("qa", {})),
        guardrail_max_retries=2,
    )

    # 5. Escalation Task
    t5_escalation = Task(
        description=(
            f"Assess operational risk and determine review escalation level for cycle {cycle_id}. "
            "Return an EscalationDecision."
        ),
        expected_output="JSON conforming to EscalationDecision schema",
        agent=agents["escalation"],
        output_pydantic=EscalationDecision,
        context=[t4_qa],
        guardrail=build_escalation_guardrail(facts.get("escalation", {})),
        guardrail_max_retries=2,
    )

    return [t1_forecast, t2_inventory, t3_supplier, t4_qa, t5_escalation]
