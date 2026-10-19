"""Supply chain decision pipeline orchestrator (pipeline.py) per SPEC 4, 8, 9, 10, 11."""

from __future__ import annotations

import os

os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"

import random
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

import structlog
from crewai import Crew, Process
from pydantic import ValidationError

from supplychain.agents import create_agents
from supplychain.audit import write_audit_event
from supplychain.checks import merge_findings, run_qa_checks
from supplychain.config import get_settings
from supplychain.cost import BudgetExceeded, CostGuard
from supplychain.db import (
    get_as_of_date,
    get_inventory,
    get_sales_window,
    get_supplier_options,
)
from supplychain.logging_setup import get_logger
from supplychain.models import (
    CycleRequest,
    CycleResult,
    EscalationDecision,
    ForecastMessage,
    InventoryPlanMessage,
    QAReport,
    SupplierMessage,
)
from supplychain.planning import (
    calculate_coverage,
    calculate_method_a,
    calculate_method_b,
    calculate_reorder_plan,
    filter_eligible_suppliers,
    is_conflict,
    is_demand_spike,
    round_to_supplier_pack,
)
from supplychain.policy import calculate_policy_level, compare_levels
from supplychain.sanitize import is_injection_pattern
from supplychain.store import save_cycle
from supplychain.tasks import create_tasks

logger = get_logger("pipeline")


def _generate_cycle_id() -> str:
    today_str = datetime.now(UTC).strftime("%Y%m%d")
    rnd = random.randint(1000, 9999)
    return f"CYC-{today_str}-{rnd}"


def _precompute_facts(sku_id: str, warehouse_id: str) -> dict[str, Any]:
    """Compute deterministic ground truth facts from database and planning math."""
    as_of = date.fromisoformat(get_as_of_date())
    sales_56 = [u for _, u in get_sales_window(sku_id, warehouse_id, 56)]
    sales_28 = sales_56[-28:] if len(sales_56) >= 28 else sales_56

    method_a = calculate_method_a(sales_28)
    method_b = calculate_method_b(sales_56)
    coverage = calculate_coverage(len(sales_56), total_days=56)
    conflict = is_conflict(method_a, method_b)
    spike = is_demand_spike(sales_56)

    expected_flags = []
    if conflict:
        expected_flags.append("CONFLICT")
    if spike:
        expected_flags.append("SPIKE")
    if coverage < 0.80:
        expected_flags.append("LOW_COVERAGE")

    inv = get_inventory(sku_id, warehouse_id)
    sups = get_supplier_options(sku_id)
    eligible = filter_eligible_suppliers(sups)

    sup0 = eligible[0] if eligible else None
    lt = sup0["effective_lead_time"] if sup0 else 7
    lt_std = sup0["lead_time_std"] if sup0 else 1.0

    plan_math = calculate_reorder_plan(
        on_hand=inv["on_hand"],
        on_order=inv["on_order"],
        daily_demand=round(method_a, 3),
        daily_demand_std=2.0,
        lead_time_days=lt,
        lead_time_std=lt_std,
        service_level=0.95,
        planned_supplier_id=sup0["supplier_id"] if sup0 else None,
    )

    expected_qty_by_sup = {}
    unit_cost_by_sup = {}
    lead_time_by_sup = {}
    for s in eligible:
        s_id = s["supplier_id"]
        expected_qty_by_sup[s_id] = round_to_supplier_pack(
            plan_math["needed_qty"], moq=s["moq"], pack_size=s["pack_size"]
        )
        unit_cost_by_sup[s_id] = s["unit_cost"]
        lead_time_by_sup[s_id] = s["effective_lead_time"]

    return {
        "as_of_date": as_of,
        "eligible_suppliers": eligible,
        "forecast": {
            "method_a_daily": round(method_a, 3),
            "method_b_daily": round(method_b, 3),
            "data_coverage": round(coverage, 3),
            "expected_flags": expected_flags,
        },
        "inventory": {
            "forecast_mean": round(method_a, 3),
            "expected_ss": plan_math["safety_stock"],
            "expected_rop": plan_math["reorder_point"],
            "expected_target": plan_math["target_level"],
            "expected_needed": plan_math["needed_qty"],
        },
        "supplier": {
            "eligible_ids": [s["supplier_id"] for s in eligible],
            "expected_qty_by_sup": expected_qty_by_sup,
            "unit_cost_by_sup": unit_cost_by_sup,
            "lead_time_by_sup": lead_time_by_sup,
            "as_of_date": as_of,
        },
        "qa": {
            "required_rule_codes": [],
            "worst_severity": "INFO",
        },
        "escalation": {},
    }


def _parse_task_output(task_output: Any, model_cls: type, cycle_id: str | None = None) -> Any:
    """Extract and validate Pydantic model from TaskOutput, with optional cycle_id synchronization."""
    m = getattr(task_output, "pydantic", None)
    if isinstance(m, model_cls):
        return (
            m.model_copy(update={"cycle_id": cycle_id})
            if (cycle_id and hasattr(m, "cycle_id"))
            else m
        )
    if isinstance(task_output, model_cls):
        return (
            task_output.model_copy(update={"cycle_id": cycle_id})
            if (cycle_id and hasattr(task_output, "cycle_id"))
            else task_output
        )
    raw = getattr(task_output, "raw", None)
    if isinstance(raw, str):
        try:
            parsed = model_cls.model_validate_json(raw)
            if cycle_id and hasattr(parsed, "cycle_id"):
                parsed = parsed.model_copy(update={"cycle_id": cycle_id})
            return parsed
        except (ValueError, TypeError, ValidationError):
            return None
    return None


def run_cycle(
    request: CycleRequest,
    cycle_id: str | None = None,
    mode: str | None = None,
    fault_mode: str | None = None,
) -> CycleResult:
    """Run one complete five-agent decision cycle per (sku_id, warehouse_id)."""
    settings = get_settings()
    cycle_id = cycle_id or _generate_cycle_id()

    # Set structlog contextvars for the cycle
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        cycle_id=cycle_id,
        sku_id=request.sku_id,
        warehouse_id=request.warehouse_id,
    )

    logger.info("cycle_started", scenario_id=request.scenario_id)
    write_audit_event(
        "cycle_started",
        cycle_id=cycle_id,
        scenario_id=request.scenario_id,
        sku_id=request.sku_id,
        warehouse_id=request.warehouse_id,
    )

    facts = _precompute_facts(request.sku_id, request.warehouse_id)
    context = {
        "cycle_id": cycle_id,
        "sku_id": request.sku_id,
        "warehouse_id": request.warehouse_id,
    }

    agents = create_agents(mode=mode, context=context, fault_mode=fault_mode)
    tasks = create_tasks(
        agents=agents,
        request_params=context,
        facts=facts,
    )

    cost_guard = CostGuard(
        agents=list(agents.values()),
        budget_usd=settings.cost_budget_usd,
        price_input_per_m=settings.price_input_per_m,
        price_output_per_m=settings.price_output_per_m,
    )

    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential,
        tracing=False,
        memory=False,
        task_callback=cost_guard,
    )

    now_iso = datetime.now(UTC).isoformat()
    status = "PENDING_APPROVAL"
    final_level = "STANDARD"
    policy_lvl = "STANDARD"

    forecast_msg = None
    plan_msg = None
    supplier_msg = None
    qa_report = None
    escalation_msg = None
    try:
        crew.kickoff()

        forecast_msg = _parse_task_output(tasks[0].output, ForecastMessage, cycle_id)
        plan_msg = _parse_task_output(tasks[1].output, InventoryPlanMessage, cycle_id)
        supplier_msg = _parse_task_output(tasks[2].output, SupplierMessage, cycle_id)
        qa_report = _parse_task_output(tasks[3].output, QAReport, cycle_id)
        escalation_msg = _parse_task_output(tasks[4].output, EscalationDecision, cycle_id)

        if not isinstance(forecast_msg, ForecastMessage) or not isinstance(
            plan_msg, InventoryPlanMessage
        ):
            raise TypeError("Invalid message payload generated during pipeline kickoff")

        # Execute deterministic QA consistency rules
        all_sups = get_supplier_options(request.sku_id)
        is_note_flagged = any(is_injection_pattern(s.get("notes", "")) for s in all_sups) or (
            "SIGNAL_UNTRUSTED" in forecast_msg.flags
        )
        rule_findings = run_qa_checks(
            forecast=forecast_msg,
            plan=plan_msg,
            supplier=supplier_msg,
            supplier_options=all_sups,
            untrusted_note_flagged=is_note_flagged,
            senior_threshold=settings.senior_po_threshold_usd,
            low_confidence_threshold=settings.low_confidence,
        )

        merged_findings = merge_findings(
            rule_findings=rule_findings,
            llm_findings=qa_report.findings if qa_report else None,
        )

        if qa_report:
            qa_report = qa_report.model_copy(update={"findings": merged_findings})

        has_eligible = len(facts["eligible_suppliers"]) > 0
        min_conf = min(
            forecast_msg.confidence,
            plan_msg.confidence,
            supplier_msg.confidence if supplier_msg else 1.0,
            escalation_msg.confidence if escalation_msg else 1.0,
        )

        po_total = supplier_msg.po_draft.total if (supplier_msg and supplier_msg.po_draft) else None

        policy_lvl = calculate_policy_level(
            findings=merged_findings,
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=has_eligible,
            po_total=po_total,
            min_confidence=min_conf,
            senior_threshold=settings.senior_po_threshold_usd,
            low_confidence_threshold=settings.low_confidence,
        )

        escalation_llm_lvl = escalation_msg.level if escalation_msg else "STANDARD"
        final_level = compare_levels(policy_lvl, escalation_llm_lvl)

        write_audit_event(
            "findings", cycle_id=cycle_id, finding_codes=[f.code for f in merged_findings]
        )
        write_audit_event("policy_level", cycle_id=cycle_id, policy_level=policy_lvl)
        write_audit_event("escalation_decided", cycle_id=cycle_id, final_level=final_level)

        if plan_msg.action == "NO_ACTION" or plan_msg.needed_qty == 0:
            status = "NO_ACTION_NEEDED"
        elif final_level == "BLOCKED":
            status = "BLOCKED"
        else:
            status = "PENDING_APPROVAL"

    except BudgetExceeded as exc:
        logger.error("budget_exceeded", error=str(exc))
        status = "BUDGET_EXCEEDED"
        policy_lvl = "BLOCKED"
        final_level = "BLOCKED"
        write_audit_event("cycle_failed", cycle_id=cycle_id, reason="BUDGET_EXCEEDED")

    except (
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        sqlite3.Error,
    ) as exc:
        logger.error("cycle_failed", error=str(exc))
        status = "FAILED"
        policy_lvl = "BLOCKED"
        final_level = "BLOCKED"
        write_audit_event("cycle_failed", cycle_id=cycle_id, reason="FAILED")

    cost_report = cost_guard.get_report()

    result = CycleResult(
        cycle_id=cycle_id,
        request=request,
        status=status,
        forecast=forecast_msg,
        plan=plan_msg,
        supplier=supplier_msg,
        qa=qa_report,
        escalation=escalation_msg,
        policy_level=policy_lvl,
        final_level=final_level,
        cost=cost_report,
        created_at=now_iso,
    )

    save_cycle(result)
    write_audit_event("cycle_finished", cycle_id=cycle_id, status=status, final_level=final_level)
    return result
