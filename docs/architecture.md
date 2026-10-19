# System Architecture & Technical Specifications

This document outlines the detailed technical architecture of the Multi-Agent Supply Chain Decision System per SPEC sections 4 through 14.

---

## 1. High-Level System Architecture

The system coordinates five specialized agents orchestrated via CrewAI's sequential process pattern. Crucially, all numerical computations, safety thresholds, and financial gates are enforced by deterministic Python code outside the LLM.

```
                           ┌──────────────────────────────────────────────┐
                           │          Ingress / Data Layer                │
                           │  - data/supply.db (3-Layer Read-Only SQLite) │
                           │  - sanitize.py (Untrusted Tagging)           │
                           └──────────────────────┬───────────────────────┘
                                                  │
                                                  ▼
     ┌────────────────────────────────────────────────────────────────────────────────────────┐
     │                     CrewAI Sequential Cognitive Pipeline (Sequential)                  │
     │                                                                                        │
     │   [1. Demand Forecaster]                                                               │
     │       Tools: get_demand_stats, get_market_signals                                      │
     │       Output: ForecastMessage                                                          │
     │       Guardrail: Validates Method A/B mean and deterministic flags                     │
     │               │                                                                        │
     │               ▼                                                                        │
     │   [2. Inventory Planner]                                                               │
     │       Tools: get_inventory_position, calculate_reorder_plan                            │
     │       Output: InventoryPlanMessage                                                     │
     │       Guardrail: Recalculates safety stock, ROP, target level, needed quantity         │
     │               │                                                                        │
     │               ▼                                                                        │
     │   [3. Supplier Liaison]                                                                │
     │       Tools: get_supplier_options                                                      │
     │       Output: SupplierMessage (Draft PO + Draft Vendor Email)                          │
     │       Guardrail: Validates supplier eligibility, pack rounding, and total price        │
     │               │                                                                        │
     │               ▼                                                                        │
     │   [4. Quality Assurance]                                                               │
     │       Tools: run_consistency_checks                                                    │
     │       Output: QAReport                                                                 │
     │       Guardrail: Re-evaluates QA01..QA14 and ensures all deterministic findings present │
     │               │                                                                        │
     │               ▼                                                                        │
     │   [5. Escalation Manager]                                                              │
     │       Output: EscalationDecision                                                       │
     │       Decision: Recommends review tier (STANDARD, SENIOR, EXECUTIVE)                   │
     │                                                                                        │
     │   task_callback: CostGuard (Per-agent token accounting; halts if cost > $0.50)        │
     └────────────────────────────────────────────┬───────────────────────────────────────────┘
                                                  │
                                                  ▼
                           ┌──────────────────────────────────────────────┐
                           │           Policy & Safety Consolidation      │
                           │  - policy.py: Deterministic rule floor       │
                           │  - final_level = max(policy_level, llm_level)│
                           │  - Status: PENDING_APPROVAL | BLOCKED | etc. │
                           │  - store.py: Persist cycle to app.db         │
                           │  - audit.py: Append to audit/audit.jsonl     │
                           └──────────────────────┬───────────────────────┘
                                                  │
                                                  ▼
                           ┌──────────────────────────────────────────────┐
                           │       Human-in-the-Loop Approval Gate        │
                           │  - Streamlit Dashboard (src/supplychain/app) │
                           │  - approvals.py (Pure deterministic module)  │
                           │  - Approve button disabled on BLOCKED        │
                           │  - finalise_po(): Appends to purchase_orders │
                           └──────────────────────────────────────────────┘
```

---

## 2. Five Specialized Agents

| # | Agent Role | Goal & Responsibilities | Read-Only Tools | Output Schema | Deterministic Guardrail Check |
|---|---|---|---|---|---|
| 1 | **Demand Forecaster** | Compute 28-day & 56-day baseline sales rates, detect anomalies, analyze market signals | `get_demand_stats`, `get_market_signals` | `ForecastMessage` | Verifies daily demand mean is bounded within `[0.5 × min(a,b), 2.0 × max(a,b)]` and required flags are present |
| 2 | **Inventory Planner** | Evaluate on-hand stock and calculate safety stock, reorder point, and replenishment need | `get_inventory_position`, `calculate_reorder_plan` | `InventoryPlanMessage` | Recalculates exact safety stock, reorder point, target level, and needed quantity from ground truth formulas |
| 3 | **Supplier Liaison** | Identify eligible active suppliers, round order to pack size, draft PO and email | `get_supplier_options` | `SupplierMessage` | Verifies selected vendor is active, quantity matches pack rounding, PO total equals qty × cost, email contains no foreign numbers or URLs |
| 4 | **Quality Assurance** | Audit pipeline consistency, verify cross-agent claims, flag compliance findings | `run_consistency_checks` | `QAReport` | Runs 14 deterministic checks (`QA01`–`QA14`); rejects output if any deterministic finding code is missing |
| 5 | **Escalation Manager** | Review severity of findings, order value, and model confidence to recommend review tier | None (pure reasoning) | `EscalationDecision` | Gated by `policy.py`; output can only raise scrutiny, never lower below deterministic policy floor |

---

## 3. Deterministic Safety Rail & Import Boundaries

### The "Deterministic Code Owns the Numbers" Principle
At no point does an LLM completion determine quantities, prices, reorder thresholds, or QA rule determinations.
- Mathematical functions in `planning.py` (`calculate_method_a`, `calculate_method_b`, `calculate_safety_stock`, `calculate_reorder_plan`, `round_to_supplier_pack`) strictly calculate numerical fields.
- Even if an LLM is hijacked or hallucinates alternative quantities, task guardrails intercept the output and trigger retries until valid or fail-closed.

### AST Import Boundary Enforcement
To guarantee the approval gate cannot be subverted:
- `approvals.py` and `store.finalise_po` can NEVER be imported by `pipeline.py`, `agents.py`, `tasks.py`, or `tools.py`.
- Enforced by `tests/test_boundaries.py::test_forbidden_approval_imports_ast` via Python Abstract Syntax Tree analysis.
- Purchase orders can only be written when a human reviewer explicitly invokes the approval action.

---

## 4. Storage & Audit Architecture
1. **Supply Database (`data/supply.db`)**:
   - Seeded ground truth (catalog, sales history, inventory position, vendor terms).
   - Opened using a 3-layer read-only defense: SQLite URI flag `mode=ro`, `PRAGMA query_only = ON`, and a custom SQLite authorizer rejecting all write codes.
2. **Application Database (`data/app.db`)**:
   - Stores finalized decision cycles (`cycles`), reviewer decisions (`human_decisions`), and approved purchase orders (`purchase_orders`).
   - Append-only SQL triggers reject `UPDATE` and `DELETE` queries with `ABORT` signals.
3. **Audit Log (`audit/audit.jsonl`)**:
   - Fail-closed JSONL audit logger capturing structured lifecycle events: `cycle_started`, `task_completed`, `findings`, `policy_level`, `escalation_decided`, `cycle_finished`, `approval_decided`, `po_finalised`, and `cycle_failed`.
4. **Structured Logging (`logs/app.log`)**:
   - Context-bound `structlog` events carrying `cycle_id`, `sku_id`, and `warehouse_id`. Never logs raw notes, email text, or prompts.
