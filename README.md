# Multi-Agent Supply Chain Decision System

[![CI](https://github.com/adwitiya-pandey/multi-agent-supply-chain-system/actions/workflows/ci.yml/badge.svg)](https://github.com/adwitiya-pandey/multi-agent-supply-chain-system/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![CrewAI 1.15.28](https://img.shields.io/badge/crewai-1.15.28-orange.svg)
![Coverage 93%](https://img.shields.io/badge/coverage-93%25-brightgreen.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)

> A production-grade five-agent CrewAI pipeline enforcing deterministic math, Pydantic message schemas, strict task guardrails, and an external human-in-the-loop approval gate for retail inventory replenishment.

---

## Architecture Diagram

```
 scenario JSON ─► build_db ─► data/supply.db (opened read-only: mode=ro + query_only + authorizer)
                                   │
 run_cycle(request, cycle_id) ─────┼───────────────────────────────────────────────┐
   structlog contextvars: cycle_id │                                               │
                                   ▼                                               │
   ┌───────────────────────── Crew (Process.sequential, one LLM instance per agent)┤
   │ 1 Forecast ─► ForecastMessage   guardrail: numbers == tool recomputation      │
   │ 2 Inventory ─► InventoryPlanMessage   guardrail: numbers == planning.py       │
   │ 3 Supplier ─► SupplierMessage (PO draft + email)  guardrail: terms, qty, $    │
   │ 4 QA ─► QAReport   guardrail: contains every rule finding (checks.py)          │
   │ 5 Escalation ─► EscalationDecision                                             │
   └─ task_callback: CostGuard (per-agent tokens × price) raises BudgetExceeded ────┘
                                   │
                                   ▼
        policy.py (deterministic floor)  ──►  final level = max(policy, LLM)
                                   │
              status: PENDING_APPROVAL | BLOCKED | NO_ACTION_NEEDED | FAILED | BUDGET_EXCEEDED
                                   │  (cycle saved to app.db, audit line written)
                                   ▼
      Streamlit dashboard ── reviewer approves / rejects ──► approvals.py (deterministic)
                                   │                          finalise_po(): append-only `purchase_orders`
                                   ▼
                     audit/audit.jsonl   +   logs (JSON, structlog)   +   LangSmith traces (optional)
```

---

## What This Proves (and What It Does Not)

*Per SPEC Section 17:*
- **What this proves**: Validates pipeline wiring, strongly-typed Pydantic schemas, strict guardrail intercepts, deterministic mathematical ownership of numbers, automated policy escalation floors, AST-enforced human approval gates, denial-of-wallet cost guards, and immutable event persistence across 10 simulated edge scenarios.
- **What this does not prove**: Offline scripted evaluation does not prove that Gemini will generate eloquent natural language explanations, exercise optimal subjective vendor negotiations, or behave predictably under native function calling without prompt drift. Live execution (T14) exercises the live Gemini model against these exact guardrails.

---

## Quickstart (Copy-Paste)

### Prerequisites
- Linux / WSL2 Ubuntu or macOS
- Python 3.13 (`uv` package manager installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

```bash
# 1. Clone the repository
git clone https://github.com/adwitiya-pandey/multi-agent-supply-chain-system.git
cd multi-agent-supply-chain-system

# 2. Install dependencies with locked resolution
uv sync

# 3. Configure environment file (offline mode runs out of the box)
cp .env.example .env

# 4. Build synthetic supply database
uv run python scripts/build_db.py

# 5. Run the 10 scenarios offline (generates docs/scenario_results.md)
uv run python scripts/run_scenarios.py --mode oracle

# 6. Generate the token and cost analysis report
uv run python scripts/cost_report.py

# 7. Start the human-in-the-loop Streamlit dashboard
uv run streamlit run src/supplychain/app.py
```

### Reviewing and Approving a Purchase Order
1. Open your browser to `http://localhost:8501`.
2. In the sidebar, type your reviewer name (e.g., `Jane Doe`).
3. Select Scenario `S01` and click **Run Decision Cycle**.
4. In the **Pending Approvals** tab, inspect the forecast, inventory plan, draft purchase order, and QA findings.
5. Click **Approve Purchase Order**.
6. Switch to the **Decision History** tab to view the finalized, immutable purchase order record.

---

## Live Gemini Mode

To run with live Google Gemini 3.8 Flash calls:

```bash
# 1. Export your Gemini API key (or add to .env)
export GEMINI_API_KEY="your-gemini-api-key"
export LLM_MODE="gemini"

# 2. Run scenarios with live model invocation (includes 3s pacing delay)
uv run python scripts/run_scenarios.py --live

# 3. View live token consumption and measured cost report
uv run python scripts/cost_report.py
```

---

## Scenario Evaluation Suite

Every scenario exercises specific business anomalies and security attacks:

| Scenario | Title | Description | Expected Status | Final Tier | QA Finding Codes |
|---|---|---|---|---|---|
| `S01` | Normal replenishment | Stock below ROP with ample cover; standard PO generated | `PENDING_APPROVAL` | `STANDARD` | None |
| `S02` | Primary supplier insolvent | Primary vendor insolvent; switches to backup vendor | `PENDING_APPROVAL` | `SENIOR` | `QA08`, `QA14` |
| `S03` | Demand spike | Recent 7-day sales surge 3x above 28-day baseline | `PENDING_APPROVAL` | `SENIOR` | `QA05`, `QA06`, `QA08`, `QA12` |
| `S04` | Conflicting forecasts | Linear trend line diverges >30% from moving average | `PENDING_APPROVAL` | `SENIOR` | `QA05`, `QA08`, `QA12` |
| `S05` | Supplier delay & hostile note | Vendor delayed with prompt injection string in notes | `PENDING_APPROVAL` | `SENIOR` | `QA08`, `QA13` |
| `S06` | Stockout | On-hand inventory is 0 units | `PENDING_APPROVAL` | `SENIOR` | `QA08` |
| `S07` | Overstock | On-hand inventory far exceeds ROP | `NO_ACTION_NEEDED` | `STANDARD` | None |
| `S08` | High-value PO | Order total exceeds $10,000 threshold | `PENDING_APPROVAL` | `SENIOR` | `QA09` |
| `S09` | Missing data | 60% of sales data missing (<80% coverage) | `BLOCKED` | `BLOCKED` | `QA07`, `QA12` |
| `S10` | Malformed LLM output | LLM returns arithmetic violations and invalid JSON | `FAILED` | `BLOCKED` | None |

---

## Measured Token & Cost Analysis

*Measured from autonomous scenario runs recorded in `docs/cost_report.md`:*

- **Total Analyzed Cycles**: 51
- **Aggregate Token Count**: 31,520 tokens (23,640 prompt, 7,880 completion)
- **Total Notional Cost**: $0.094560 USD (Average ~$0.0024 per cycle)
- **Governance Budget Ceiling**: $0.500000 USD per cycle

> [!IMPORTANT]
> **Cost numbers are notional (tokens × configured price); free-tier calls bill zero.**
> Free-tier Gemini 3.8 Flash calls incur $0.00 actual billing. Calculations use standard commercial reference rates of **$1.50 per 1M prompt tokens** and **$7.50 per 1M completion tokens** as defined in SPEC section 10.

| Agent Role | Prompt Tokens | Completion Tokens | Total Tokens | Notional Cost (USD) | Cost Share |
|---|---|---|---|---|---|
| `Demand Forecaster` | 4,920 | 1,640 | 6,560 | $0.019680 | 20.8% |
| `Inventory Planner` | 5,400 | 1,800 | 7,200 | $0.021600 | 22.8% |
| `Supplier Liaison` | 4,440 | 1,480 | 5,920 | $0.017760 | 18.8% |
| `Quality Assurance` | 4,440 | 1,480 | 5,920 | $0.017760 | 18.8% |
| `Escalation Manager` | 4,440 | 1,480 | 5,920 | $0.017760 | 18.8% |

---

## Security Architecture Summary

1. **Deterministic Numbers**: Forecasts, safety stock, reorder points, order quantities, pack rounding, and PO totals come exclusively from `planning.py` and `checks.py`. Guardrails recalculate and fail-closed if LLM text disagrees.
2. **Architectural AST Isolation**: `approvals.py` and `finalise_po` can NEVER be imported by `pipeline.py`, `agents.py`, `tasks.py`, or `tools.py` (enforced via AST unit tests). Agents possess zero write tools.
3. **Prompt Injection Defense**: External notes from suppliers, market feeds, or reviewer input are sanitized via `sanitize.py`, stripped of control characters, regex-checked for injection vectors, wrapped in `<untrusted>` tags, and excluded from system prompts and audit logs.
4. **Three-Layer Database Defense**: Ground truth database `supply.db` is opened read-only using `mode=ro`, `PRAGMA query_only = ON`, and a SQLite authorizer blocking all write opcodes.
5. **Append-Only Decision Store**: `app.db` enforces immutability via SQLite triggers on `cycles`, `human_decisions`, and `purchase_orders` that reject `UPDATE` and `DELETE` queries with `ABORT` signals.
6. **Cost Guard**: `CostGuard` task callback enforces a strict $0.50 cycle ceiling, aborting execution immediately upon budget breach.

---

## Known Limitations

*Per SPEC Section 22:*
- **Synthetic Data**: Uses synthetic catalog and sales history (Meridian Home Goods).
- **Single-SKU Processing**: Each decision cycle processes a single SKU-warehouse pair; multi-SKU cross-docking is out of scope.
- **Simulated Communications**: Vendor emails are drafted as plain text; real SMTP dispatch is deliberately omitted.
- **Reviewer Identity**: Reviewer identity is a validated typed name string rather than enterprise SAML/OAuth SSO.
- **Inter-Task Cost Checks**: Token budget checks occur at task callback boundaries; runaway streaming tokens within a single call are bounded by `max_tokens`.
- **Deliberately Simple Demand Models**: Employs moving-average and linear trend baselines rather than high-dimensional neural time-series models.

---

## Repository Tree

```
.
├── .github/workflows/ci.yml         # CI workflow (coverage gate, scenarios, boundaries)
├── data/
│   └── scenarios/                   # JSON test scenario contracts (S01.json .. S10.json)
├── docs/
│   ├── architecture.md              # System decomposition and component design
│   ├── cost_report.md               # Measured token consumption and notional costs
│   ├── decisions.md                 # Architectural decision log (D1..D10)
│   ├── EXPLAIN-PLAIN-ENGLISH.md     # Plain English task explanations and interview summaries
│   ├── scenario_results.md          # 10-scenario evaluation table
│   ├── sdk_notes.md                 # Verified CrewAI, Pydantic, Streamlit SDK facts
│   ├── threat_model.md              # Threat model and security mitigations
│   ├── trace_summary.md             # Autonomous execution trace evidence
│   └── traces/                      # Detailed per-cycle trace spans
├── pyproject.toml                   # Project metadata and locked dependency pins
├── README.md                        # Master documentation
├── scripts/
│   ├── build_db.py                  # Ground truth SQLite database builder
│   ├── cost_report.py               # Aggregated cost reporting script
│   └── run_scenarios.py             # Scenario test runner (oracle and live modes)
├── src/supplychain/
│   ├── agents.py                    # CrewAI agent definitions
│   ├── app.py                       # Streamlit human-in-the-loop dashboard
│   ├── approvals.py                 # Deterministic approval gate (outside CrewAI)
│   ├── audit.py                     # Fail-closed JSONL audit logger
│   ├── checks.py                    # Deterministic QA consistency checks (QA01..QA14)
│   ├── config.py                    # Pydantic-settings configuration
│   ├── cost.py                      # CostGuard and token pricing math
│   ├── db.py                        # 3-layer read-only database accessor
│   ├── guardrails.py                # Pydantic task output guardrails
│   ├── llm.py                       # LLM factory (Gemini and ScriptedLLM)
│   ├── logging_setup.py             # Context-bound structlog setup
│   ├── models.py                    # Strict Pydantic inter-agent schemas
│   ├── pipeline.py                  # Cycle runner orchestrating the 5-agent crew
│   ├── planning.py                  # Deterministic forecasting and inventory formulas
│   ├── policy.py                    # Deterministic escalation policy floor
│   ├── sanitize.py                  # Prompt injection detection and untrusted wrapping
│   ├── scripted.py                  # Offline ReAct fake LLM implementation
│   ├── store.py                     # Append-only SQLite event store with triggers
│   ├── tasks.py                     # Sequential CrewAI task definitions
│   ├── tools.py                     # Parameterized read-only agent tools
│   └── tracing.py                   # LangSmith OpenTelemetry hook and local trace spans
└── tests/                           # 168 unit, scenario, UI, and boundary tests
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
