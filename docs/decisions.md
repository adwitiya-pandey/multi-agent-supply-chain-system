# Architecture Decision Log

This document records the foundational architectural decisions for the Multi-Agent Supply Chain Decision System per SPEC section 21. Each decision specifies the rationale, rejected alternatives, and explicit conditions that would warrant reconsideration ("What would change my mind").

---

### D1: CrewAI Sequential Task Pipeline (5 Specialized Agents)
- **Decision**: Structure the decision cycle as five sequential CrewAI agents (`Demand Forecaster`, `Inventory Planner`, `Supplier Liaison`, `Quality Assurance`, `Escalation Manager`) passing strongly-typed Pydantic messages.
- **Rejected Alternative**: A single monolithic general-purpose agent; or LangGraph cyclical workflow.
- **Why**: Enforces clear separation of cognitive responsibilities aligning with supply chain roles. Sequential tasks ensure deterministic data dependency ordering without unpredictable agent-to-agent delegation loops.
- **What would change my mind**: If the replenishment decision required non-linear back-and-forth multi-party negotiation between supplier and buyer, requiring cyclic graph execution (in which case a state machine engine like LangGraph would be appropriate).

---

### D2: Deterministic Code Owns All Numbers; Guardrails Recompute
- **Decision**: All forecasts, safety stock, reorder points, pack rounding, purchase order totals, and QA rule evaluations are computed strictly by deterministic Python functions (`planning.py` and `checks.py`). Task guardrails intercept agent outputs, recalculate every metric, and reject arithmetic mismatches.
- **Rejected Alternative**: Allowing the LLM to directly calculate order quantities, unit costs, or inventory thresholds.
- **Why**: LLMs are probabilistic token predictors prone to arithmetic hallucination and prompt drift. In a financial and inventory system, numerical errors directly cause stockouts or capital loss.
- **What would change my mind**: If LLMs provided provable, formally verified formal-arithmetic guarantees with zero variance across all floating-point operations.

---

### D3: Human Approval Gate Exists Entirely Outside CrewAI
- **Decision**: The approval gate is pure deterministic application code in `approvals.py` and `store.py`. `pipeline.py`, `agents.py`, `tasks.py`, and `tools.py` are strictly prohibited from importing `approvals` or `finalise_po` (enforced via AST unit tests).
- **Rejected Alternative**: An in-crew "Human Approval Agent" or setting `human_input=True` on an agent task.
- **Why**: In-crew human approval steps can be bypassed, subverted, or hallucinated past by prompt injection or conversational steering. An external code boundary guarantees that no purchase order can physically be finalized without an authenticated human hitting an external endpoint.
- **What would change my mind**: Never. Bypassing human authorization in financial disbursement decisions violates foundational enterprise governance.

---

### D4: Mandatory Human Review for Every Purchase Order; Level Dictates Tier
- **Decision**: Every purchase order draft requires explicit human review (`STANDARD`, `SENIOR`, or `EXECUTIVE`). Low-risk orders cannot auto-approve.
- **Rejected Alternative**: Automatic silent approval for low-dollar or low-risk replenishment orders.
- **Why**: Establishes strict compliance and governance. The decision tier ensures high-risk, volatile, or high-value orders receive senior oversight while retaining accountability for all disbursements.
- **What would change my mind**: If enterprise policy explicitly authorized micro-transactions under $50 with a bounded monthly loss-reserve pool.

---

### D5: Deterministic Policy Floor; LLM Can Only Raise Caution
- **Decision**: System policy sets a deterministic minimum escalation level (`policy_level`). The LLM's recommended escalation level can only elevate scrutiny (`final_level = max(policy_level, llm_level)`).
- **Rejected Alternative**: Allowing the LLM to downgrade or override a rule-based escalation.
- **Why**: Self-reported LLM confidence is inherently noisy and susceptible to sycophancy or injection attacks. An LLM must never be able to dismiss an algorithmic red flag.
- **What would change my mind**: If extensive historical calibration demonstrated that rule triggers exhibited unacceptable false-positive rates causing human reviewer fatigue.

---

### D6: Dedicated LLM Instance Per Agent
- **Decision**: Construct a distinct `LLM` instance for each agent in the crew.
- **Rejected Alternative**: Sharing a single global LLM instance across all agents.
- **Why**: Enables granular, per-agent token accounting and cost tracking, allowing engineering to identify which agents consume the bulk of the token budget.
- **What would change my mind**: If memory overhead from client connection pooling became prohibitive at scale.

---

### D7: ScriptedLLM as Default Offline Mode
- **Decision**: The test suite, CI pipeline, and default local developer workflow run against an offline, zero-network `ScriptedLLM` with an honesty banner displayed in the UI.
- **Rejected Alternative**: Requiring live Gemini API keys for all test suites and demonstrations.
- **Why**: Ensures 100% offline determinism, instantaneous test suite execution (<30s), zero CI flakiness, and zero API cost for prospective employers and code reviewers.
- **What would change my mind**: If integration tests specifically aimed to benchmark LLM latency or model regression against live endpoints.

---

### D8: Cost Guard Callback Between Crew Tasks
- **Decision**: Implement `CostGuard` as a CrewAI `task_callback` that monitors cumulative prompt and completion tokens against a $0.50 budget ceiling, raising `BudgetExceeded` to halt runaway cycles.
- **Rejected Alternative**: Middleware intercepting every individual API call chunk.
- **Why**: `task_callback` is CrewAI's simplest, officially verified interception point that halts the crew immediately when an exception is raised.
- **What would change my mind**: If streaming token responses required mid-generation cutoffs to avoid wasting partial tokens during a massive hallucinated loop.

---

### D9: Append-Only SQLite Event Store with Triggers
- **Decision**: Store decisions and purchase orders in SQLite tables (`cycles`, `human_decisions`, `purchase_orders`) protected by database triggers that raise errors on `UPDATE` or `DELETE`.
- **Rejected Alternative**: Mutable row updates with standard ORM semantics.
- **Why**: Financial auditability demands immutable historical records. Once written, neither agents nor administrators can tamper with cycle results or decisions.
- **What would change my mind**: If GDPR or statutory data-retention laws mandated physical deletion of specific personal reviewer identifiers.

---

### D10: Parameterized Read-Only Tool Functions (No Agent SQL Access)
- **Decision**: Agents access database facts strictly through fixed, typed Python functions using `?` parameterization over a 3-layer read-only SQLite connection (URI `mode=ro`, `PRAGMA query_only=ON`, and `set_authorizer`). No SQL query tools are exposed to agents.
- **Rejected Alternative**: Giving agents a generic `execute_sql` tool.
- **Why**: Providing SQL generation capabilities creates massive prompt injection and information disclosure vulnerabilities. Fixed tools constrain data access strictly to domain needs.
- **What would change my mind**: If users required arbitrary dynamic ad-hoc analytics queries that could not be pre-formulated into parameterized schemas.
