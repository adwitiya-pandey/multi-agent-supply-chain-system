"""Streamlit human-in-the-loop approval dashboard (app.py) per SPEC 12, 14 and TASKS.md T12."""

import sys
from pathlib import Path

# Add src and root to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st

from supplychain.approvals import ApprovalError, decide
from supplychain.config import get_settings
from supplychain.models import CycleRequest
from supplychain.pipeline import run_cycle
from supplychain.store import list_history, list_pending


def main() -> None:
    st.set_page_config(
        page_title="Multi-Agent Supply Chain Dashboard",
        page_icon="📦",
        layout="wide",
    )

    settings = get_settings()

    st.title("📦 Multi-Agent Replenishment Decision Dashboard")
    st.caption("Five-Agent CrewAI Pipeline with Deterministic Math & Human-in-the-Loop Governance")

    # 1. Sidebar Configuration & Controls
    with st.sidebar:
        st.header("⚙️ System Mode & Governance")

        # Mode banner per SPEC 12
        if settings.llm_mode == "scripted":
            st.warning("SCRIPTED DEMO: outputs are deterministic, not Gemini")
        else:
            st.info("LIVE MODE: Gemini 3.8 Flash High active")

        st.subheader("👤 Reviewer Profile")
        reviewer_name = st.text_input(
            "Reviewer Name",
            value="Alice Reviewer",
            help="Human reviewer name. Must match ^[A-Za-z][A-Za-z .'-]{1,39}$",
            key="reviewer_name_input",
        )
        reviewer_note = st.text_area(
            "Decision Notes",
            value="",
            placeholder="Enter rationale for approval or rejection...",
            help="Reviewer comments. Sanitized before persistence.",
            key="reviewer_note_input",
        )

        st.divider()
        st.subheader("🚀 Trigger Pipeline Cycle")
        selected_scenario = st.selectbox(
            "Scenario",
            options=[f"S{i:02d}" for i in range(1, 11)],
            index=0,
            key="scenario_select",
        )

        # Default mapping of scenario to SKU
        scenario_sku_map = {f"S{i:02d}": f"SKU{i:04d}" for i in range(1, 11)}
        default_sku = scenario_sku_map.get(selected_scenario, "SKU0001")

        sku_input = st.text_input("SKU ID", value=default_sku, key="sku_input")
        wh_input = st.selectbox(
            "Warehouse ID", options=["WH-N", "WH-S", "WH-W"], index=0, key="wh_select"
        )

        if st.button("Run Decision Cycle", type="secondary", key="run_cycle_btn"):
            with st.spinner("Executing 5-agent decision cycle..."):
                try:
                    req = CycleRequest(
                        scenario_id=selected_scenario,
                        sku_id=sku_input.strip(),
                        warehouse_id=wh_input,
                    )
                    fault = (
                        "invalid_json"
                        if (selected_scenario == "S10" and settings.llm_mode == "scripted")
                        else None
                    )
                    result = run_cycle(req, fault_mode=fault)
                    st.success(f"Cycle completed: {result.cycle_id} ({result.status})")
                    st.rerun()
                except (RuntimeError, ValueError, TypeError, KeyError) as exc:
                    st.error(f"Cycle execution failed: {exc}")

    # 2. Main Tabs
    tab_pending, tab_history, tab_docs = st.tabs(
        ["📋 Pending Approvals", "📜 Decision History", "🛡️ Governance & Architecture"]
    )

    # TAB 1: Pending Approvals
    with tab_pending:
        pending_cycles = list_pending()

        if not pending_cycles:
            st.info(
                "No decision cycles currently pending approval. Run a cycle from the sidebar to review."
            )
        else:
            cycle_options = [
                f"{c.cycle_id} | {c.request.scenario_id} | {c.request.sku_id} ({c.request.warehouse_id}) | Level: {c.final_level}"
                for c in pending_cycles
            ]
            selected_idx = st.selectbox(
                "Select Cycle to Inspect",
                options=range(len(pending_cycles)),
                format_func=lambda i: cycle_options[i],
                key="pending_cycle_picker",
            )
            cycle = pending_cycles[selected_idx]

            st.markdown(f"### Cycle Overview: `{cycle.cycle_id}`")
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Status", cycle.status)
            col_m2.metric("Scenario", cycle.request.scenario_id)
            col_m3.metric("Policy Level", cycle.policy_level)
            col_m4.metric("Final Level", cycle.final_level)

            # Details Section
            with st.expander("1. 📈 Demand Forecast", expanded=True):
                if cycle.forecast:
                    fc = cycle.forecast
                    f_c1, f_c2, f_c3 = st.columns(3)
                    f_c1.metric("Daily Demand Mean", f"{fc.daily_demand_mean:.3f}")
                    f_c2.metric("Method A (28d)", f"{fc.method_a_daily:.3f}")
                    f_c3.metric("Method B (56d fit)", f"{fc.method_b_daily:.3f}")

                    st.text(
                        f"Coverage: {fc.data_coverage * 100:.1f}% | Confidence: {fc.confidence:.2f}"
                    )
                    st.text(
                        f"Conflict: {fc.conflict} | Spike: {fc.demand_spike} | Flags: {', '.join(fc.flags) if fc.flags else 'None'}"
                    )
                    st.caption("Forecaster Rationale (Plain Text):")
                    st.text(fc.rationale)
                else:
                    st.write("No forecast data available.")

            with st.expander("2. 📊 Inventory Position & Reorder Plan", expanded=True):
                if cycle.plan:
                    pl = cycle.plan
                    p_c1, p_c2, p_c3, p_c4 = st.columns(4)
                    p_c1.metric("On-Hand Stock", pl.on_hand)
                    p_c2.metric("Safety Stock", pl.safety_stock)
                    p_c3.metric("Reorder Point (ROP)", pl.reorder_point)
                    p_c4.metric("Needed Quantity", pl.needed_qty)

                    st.text(
                        f"Action: {pl.action} | Urgency: {pl.urgency} | Planned Supplier: {pl.planned_supplier_id}"
                    )
                    st.caption("Planner Rationale (Plain Text):")
                    st.text(pl.rationale)
                else:
                    st.write("No inventory plan available.")

            with st.expander("3. 🏢 Supplier Selection & Draft Purchase Order", expanded=True):
                if cycle.supplier and cycle.supplier.po_draft:
                    po = cycle.supplier.po_draft
                    s_c1, s_c2, s_c3, s_c4 = st.columns(4)
                    s_c1.metric("Chosen Supplier", po.supplier_id)
                    s_c2.metric("Order Quantity", f"{po.qty:,} units")
                    s_c3.metric("Unit Cost", f"${po.unit_cost:.2f}")
                    s_c4.metric("Total PO Value", f"${po.total:,.2f}")

                    st.text(f"Requested Delivery Date: {po.requested_delivery_date}")
                    st.caption("Vendor Email Body (Plain Text Preview):")
                    st.code(
                        cycle.supplier.email.body if cycle.supplier.email else "", language=None
                    )
                else:
                    st.write("No Purchase Order generated for this cycle.")

            with st.expander("4. 🔍 Quality Assurance & Consistency Audit", expanded=True):
                if cycle.qa:
                    st.markdown(f"**QA Verdict**: `{cycle.qa.verdict}`")
                    if cycle.qa.findings:
                        st.markdown("**Consistency Findings:**")
                        for fd in cycle.qa.findings:
                            badge = (
                                "🚨 CRITICAL"
                                if fd.severity == "CRITICAL"
                                else ("⚠️ WARN" if fd.severity == "WARN" else "ℹ️ INFO")
                            )
                            st.text(f"[{badge}] {fd.code} ({fd.source}): {fd.message}")
                    else:
                        st.success("All automated consistency rules passed with 0 findings.")
                else:
                    st.write("No QA audit report available.")

            with st.expander("5. 💰 Token Usage & Notional Cost", expanded=False):
                st.caption(
                    "Cost numbers are notional (tokens × configured price); free-tier calls bill zero."
                )
                cost_data = []
                for ag in sorted(cycle.cost.usd.keys()):
                    p = cycle.cost.prompt_tokens.get(ag, 0)
                    c = cycle.cost.completion_tokens.get(ag, 0)
                    u = cycle.cost.usd.get(ag, 0.0)
                    cost_data.append(
                        {
                            "Agent": ag,
                            "Prompt Tokens": p,
                            "Completion Tokens": c,
                            "Cost (USD)": f"${u:.6f}",
                        }
                    )
                st.table(cost_data)
                st.markdown(f"**Total Cycle Cost**: `${cycle.cost.total_usd:.6f}`")

            # Human Approval Gate Controls
            st.divider()
            st.markdown("### ✍️ Human Decision Gate")

            is_blocked = cycle.final_level == "BLOCKED"
            if is_blocked:
                st.error(
                    "⚠️ APPROVAL BLOCKED: This cycle has final escalation level BLOCKED. Deterministic policy forbids approval."
                )

            btn_col1, btn_col2, _ = st.columns([1, 1, 2])

            with btn_col1:
                approve_clicked = st.button(
                    "Approve Purchase Order",
                    disabled=is_blocked,
                    type="primary",
                    key="approve_action_btn",
                )
                if approve_clicked:
                    try:
                        decision = decide(
                            cycle_id=cycle.cycle_id,
                            reviewer=reviewer_name.strip(),
                            decision="APPROVED",
                            note=reviewer_note.strip(),
                        )
                        po_id = decision.get("po_id") or ""
                        st.success(f"Successfully APPROVED! Purchase Order {po_id} finalized.")
                        st.rerun()
                    except ApprovalError as err:
                        st.error(f"Approval failed: {err}")
                    except ValueError as val_err:
                        st.error(f"Validation error: {val_err}")

            with btn_col2:
                reject_clicked = st.button(
                    "Reject Proposal",
                    type="secondary",
                    key="reject_action_btn",
                )
                if reject_clicked:
                    try:
                        decide(
                            cycle_id=cycle.cycle_id,
                            reviewer=reviewer_name.strip(),
                            decision="REJECTED",
                            note=reviewer_note.strip(),
                        )
                        st.warning(f"Cycle {cycle.cycle_id} REJECTED.")
                        st.rerun()
                    except ApprovalError as err:
                        st.error(f"Rejection failed: {err}")
                    except ValueError as val_err:
                        st.error(f"Validation error: {val_err}")

    # TAB 2: Decision History
    with tab_history:
        st.markdown("### 📜 Purchase Order & Decision Audit Trail")
        history_rows = list_history()

        if not history_rows:
            st.info("No recorded human decisions or finalized purchase orders in app.db.")
        else:
            clean_history = []
            for h in history_rows:
                clean_history.append(
                    {
                        "Cycle ID": h["cycle_id"],
                        "Decision": h["decision"] or "PENDING",
                        "Reviewer": h["reviewer"] or "-",
                        "PO ID": h["po_id"] or "-",
                        "PO Total ($)": f"${h['po_total']:.2f}"
                        if h["po_total"] is not None
                        else "-",
                        "Decided At": h["decided_at"] or "-",
                        "Note": h["note"] or "-",
                    }
                )
            st.dataframe(clean_history)

    # TAB 3: Governance & Architecture
    with tab_docs:
        st.markdown("### 🛡️ System Architecture & Safety Guarantees")
        st.markdown(
            """
            - **Deterministic Mathematics Owns Numbers**: Forecast statistics, safety stock, reorder point, MOQ/pack rounding, and QA findings are calculated by deterministic Python code.
            - **External Approval Gate**: Only `approvals.py` creates purchase order records. Agent tools have zero write access and cannot import approval functions.
            - **Monotonic Caution**: `final_level = max(policy_level, llm_level)`. LLMs can only escalate caution, never de-escalate.
            - **Immutable Persistence**: SQLite tables `cycles`, `approvals`, and `purchase_orders` enforce append-only semantics via abort triggers.
            - **Untrusted External Data**: Supplier notes, customer signals, and reviewer notes are wrapped in `<untrusted>` tags and sanitized against prompt injection patterns.
            """
        )


if __name__ == "__main__":
    main()
