"""Scripted LLM for offline deterministic execution, ReAct tool invocation, and scenario replay."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from crewai.llms.base_llm import BaseLLM

from supplychain.db import get_as_of_date, get_inventory, get_sales_window, get_supplier_options
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


class ScriptedLLM(BaseLLM):
    """Deterministic offline LLM subclassing BaseLLM per docs/sdk_notes.md."""

    llm_type: str = "scripted"

    def __init__(
        self,
        replies: list[str] | None = None,
        mode: str = "replies",
        agent_role: str | None = None,
        context: dict[str, Any] | None = None,
        fault_mode: str | None = None,
    ) -> None:
        super().__init__(model="scripted")
        self._replies = list(replies) if replies is not None else []
        self.mode = mode
        self.agent_role = agent_role or ""
        self.context = context or {}
        self.fault_mode = fault_mode
        self._step_counter = 0

    def supports_function_calling(self) -> bool:
        """Returns False to force CrewAI to use the offline ReAct text format."""
        return False

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
        **kw: Any,
    ) -> str:
        """Process messages and return next scripted or oracle ReAct response."""
        # Track fake token usage per instance
        self._track_token_usage_internal(
            {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}
        )

        if self.mode == "replies":
            if not self._replies:
                return 'Thought: Done\nFinal Answer: {"status": "ok"}'
            return self._replies.pop(0)

        if self.mode == "oracle":
            return self._handle_oracle(messages)

        return 'Thought: Complete\nFinal Answer: {"status": "ok"}'

    def _extract_ids(self, text: str) -> tuple[str, str, str]:
        """Extract cycle_id, sku_id, warehouse_id from task descriptions / context."""
        cycle_match = re.search(r"CYC-[0-9]{8}-[0-9]{4}", text)
        sku_match = re.search(r"SKU[0-9]{4}", text)
        wh_match = re.search(r"WH-[NSW]", text)

        cycle_id = (
            cycle_match.group(0)
            if cycle_match
            else self.context.get("cycle_id", "CYC-20261019-0001")
        )
        sku_id = sku_match.group(0) if sku_match else self.context.get("sku_id", "SKU0001")
        wh_id = wh_match.group(0) if wh_match else self.context.get("warehouse_id", "WH-N")
        return cycle_id, sku_id, wh_id

    def _handle_oracle(self, messages: Any) -> str:
        """Dynamically generate ReAct tool calls and exact Pydantic outputs."""
        text = str(messages)
        cycle_id, sku_id, wh_id = self._extract_ids(text)

        # 1. Demand Forecaster
        if "Forecaster" in self.agent_role or "Forecast" in self.agent_role:
            if "Observation:" not in text and self._step_counter == 0:
                self._step_counter += 1
                return (
                    f"Thought: I need to query demand statistics for {sku_id} in {wh_id}.\n"
                    f"Action: get_demand_stats\n"
                    f'Action Input: {{"sku": "{sku_id}", "wh": "{wh_id}"}}'
                )
            # Second turn: build ForecastMessage
            sales = [u for _, u in get_sales_window(sku_id, wh_id, 56)]
            units_28 = sales[-28:] if len(sales) >= 28 else sales
            m_a = calculate_method_a(units_28)
            m_b = calculate_method_b(sales)
            cov = calculate_coverage(len(sales), 56)
            conf = is_conflict(m_a, m_b)
            spk = is_demand_spike(sales)

            flags = []
            if conf:
                flags.append("CONFLICT")
            if spk:
                flags.append("SPIKE")
            if cov < 0.80:
                flags.append("LOW_COVERAGE")

            payload = {
                "cycle_id": cycle_id,
                "sku_id": sku_id,
                "warehouse_id": wh_id,
                "horizon_days": 14,
                "daily_demand_mean": round(m_a, 3),
                "daily_demand_std": 2.0,
                "method_a_daily": round(m_a, 3),
                "method_b_daily": round(m_b, 3),
                "data_coverage": round(cov, 3),
                "conflict": conf,
                "demand_spike": spk,
                "flags": flags,
                "rationale": "Oracle deterministic forecast computed from historical sales.",
                "confidence": 0.95 if not conf and not spk and cov >= 0.80 else 0.55,
            }
            return (
                f"Thought: I now have the demand statistics.\nFinal Answer: {json.dumps(payload)}"
            )

        # 2. Inventory Planner
        if "Planner" in self.agent_role:
            if "Observation:" not in text and self._step_counter == 0:
                self._step_counter += 1
                return (
                    f"Thought: I need to check current inventory position for {sku_id} in {wh_id}.\n"
                    f"Action: get_inventory_position\n"
                    f'Action Input: {{"sku": "{sku_id}", "wh": "{wh_id}"}}'
                )

            # Fault mode for S10
            if self.fault_mode == "wrong_rop":
                self.fault_mode = "invalid_json"
                # Return wrong reorder point
                return (
                    f'Thought: Fault injection.\nFinal Answer: {{"cycle_id": "{cycle_id}", '
                    f'"sku_id": "{sku_id}", "warehouse_id": "{wh_id}", "on_hand": 50, "on_order": 0, '
                    f'"daily_demand": 10.0, "daily_demand_std": 2.0, "lead_time_days": 7, "lead_time_std": 1.0, '
                    f'"service_level": 0.95, "safety_stock": 19, "reorder_point": 9999, "target_level": 159, '
                    f'"needed_qty": 109, "action": "ORDER", "urgency": "NORMAL", "planned_supplier_id": "SUP001", '
                    f'"rationale": "Fault ROP", "confidence": 0.9}}'
                )
            if self.fault_mode == "invalid_json":
                # Return malformed JSON that fails Pydantic validation
                return (
                    'Thought: Fault injection.\nFinal Answer: {"reorder_point": "not_an_integer"}'
                )

            # Second turn: calculate reorder plan
            sales = [u for _, u in get_sales_window(sku_id, wh_id, 28)]
            m_a = calculate_method_a(sales)
            inv = get_inventory(sku_id, wh_id)
            sups = get_supplier_options(sku_id)
            eligible = filter_eligible_suppliers(sups)
            sup0 = eligible[0] if eligible else None
            lt = sup0["effective_lead_time"] if sup0 else 7
            lt_std = sup0["lead_time_std"] if sup0 else 1.0
            sup_id = sup0["supplier_id"] if sup0 else None

            plan = calculate_reorder_plan(
                on_hand=inv["on_hand"],
                on_order=inv["on_order"],
                daily_demand=round(m_a, 3),
                daily_demand_std=2.0,
                lead_time_days=lt,
                lead_time_std=lt_std,
                service_level=0.95,
                planned_supplier_id=sup_id,
            )
            plan["cycle_id"] = cycle_id
            plan["sku_id"] = sku_id
            plan["warehouse_id"] = wh_id
            plan["rationale"] = "Oracle deterministic inventory replenishment calculation."
            plan["confidence"] = 0.95
            return f"Thought: Plan complete.\nFinal Answer: {json.dumps(plan)}"

        # 3. Supplier Liaison
        if "Supplier" in self.agent_role:
            if "Observation:" not in text and self._step_counter == 0:
                self._step_counter += 1
                return (
                    f"Thought: I need to query supplier options for {sku_id}.\n"
                    f"Action: get_supplier_options\n"
                    f'Action Input: {{"sku": "{sku_id}"}}'
                )

            # Second turn: build SupplierMessage
            sups = get_supplier_options(sku_id)
            eligible = filter_eligible_suppliers(sups)
            sales = [u for _, u in get_sales_window(sku_id, wh_id, 28)]
            m_a = calculate_method_a(sales)
            inv = get_inventory(sku_id, wh_id)

            if not eligible:
                payload = {
                    "cycle_id": cycle_id,
                    "sku_id": sku_id,
                    "warehouse_id": wh_id,
                    "supplier_id": None,
                    "po_draft": None,
                    "email": None,
                    "alternates_considered": [],
                    "rationale": "No eligible suppliers available.",
                    "confidence": 0.0,
                }
                return f"Thought: No eligible suppliers.\nFinal Answer: {json.dumps(payload)}"

            sup0 = eligible[0]
            plan = calculate_reorder_plan(
                on_hand=inv["on_hand"],
                on_order=inv["on_order"],
                daily_demand=round(m_a, 3),
                daily_demand_std=2.0,
                lead_time_days=sup0["effective_lead_time"],
                lead_time_std=sup0["lead_time_std"],
                service_level=0.95,
            )

            if plan["action"] == "NO_ACTION" or plan["needed_qty"] == 0:
                payload = {
                    "cycle_id": cycle_id,
                    "sku_id": sku_id,
                    "warehouse_id": wh_id,
                    "supplier_id": None,
                    "po_draft": None,
                    "email": None,
                    "alternates_considered": [s["supplier_id"] for s in eligible[1:]],
                    "rationale": "Stock level sufficient, no purchase order required.",
                    "confidence": 0.95,
                }
                return f"Thought: No order needed.\nFinal Answer: {json.dumps(payload)}"

            order_qty = round_to_supplier_pack(
                plan["needed_qty"], moq=sup0["moq"], pack_size=sup0["pack_size"]
            )
            unit_cost = sup0["unit_cost"]
            total = round(order_qty * unit_cost, 2)
            as_of_dt = date.fromisoformat(get_as_of_date())
            delivery_date = (as_of_dt + timedelta(days=sup0["effective_lead_time"])).isoformat()

            po = {
                "sku_id": sku_id,
                "warehouse_id": wh_id,
                "supplier_id": sup0["supplier_id"],
                "qty": order_qty,
                "unit_cost": unit_cost,
                "total": total,
                "currency": "USD",
                "requested_delivery_date": delivery_date,
            }
            email = {
                "subject": f"Purchase Order Request - {sku_id}",
                "body": (
                    f"Please confirm purchase order for {order_qty} units of {sku_id} "
                    f"at unit cost ${unit_cost:.2f} for a total of ${total:.2f}. "
                    f"Requested delivery by {delivery_date}."
                ),
            }
            payload = {
                "cycle_id": cycle_id,
                "sku_id": sku_id,
                "warehouse_id": wh_id,
                "supplier_id": sup0["supplier_id"],
                "po_draft": po,
                "email": email,
                "alternates_considered": [s["supplier_id"] for s in eligible[1:]],
                "rationale": f"Selected primary eligible supplier {sup0['supplier_id']}.",
                "confidence": 0.95,
            }
            return f"Thought: Drafted supplier message.\nFinal Answer: {json.dumps(payload)}"

        # 4. Quality Assurance
        if "Quality" in self.agent_role or "QA" in self.agent_role:
            if "Observation:" not in text and self._step_counter == 0:
                self._step_counter += 1
                return (
                    "Thought: I need to run consistency checks on order draft.\n"
                    "Action: run_consistency_checks\n"
                    'Action Input: {"po_qty": 100, "needed_qty": 100, "moq": 50, "pack_size": 10, "po_total": 2000.0, "unit_cost": 20.0}'
                )

            # Second turn: build QAReport
            payload = {
                "cycle_id": cycle_id,
                "sku_id": sku_id,
                "warehouse_id": wh_id,
                "findings": [],
                "verdict": "PASS",
                "summary": "Oracle QA verified all deterministic rules and message parity.",
            }
            return f"Thought: QA complete.\nFinal Answer: {json.dumps(payload)}"

        # 5. Escalation Manager
        if "Escalation" in self.agent_role:
            # Deterministic escalation recommendation
            payload = {
                "cycle_id": cycle_id,
                "sku_id": sku_id,
                "warehouse_id": wh_id,
                "level": "STANDARD",
                "reasons": ["Automated replenishment within standard operating thresholds."],
                "confidence": 0.95,
            }
            return f"Thought: Escalation level assessed.\nFinal Answer: {json.dumps(payload)}"

        return 'Thought: Complete\nFinal Answer: {"status": "ok"}'
