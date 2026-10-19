# Scenario Evaluation Results (Mode: ORACLE)

*Execution Date*: 2026-10-19 19:49:41Z  
*Evaluation Engine*: `ScriptedLLM (offline ReAct)`  

> **Note on Costs**: Cost numbers are notional (tokens × configured price); free-tier API calls bill zero.

| Scenario | Title | Status | Final Level | QA Findings | PO Order | Notional Cost | Latency |
|---|---|---|---|---|---|---|---|
| `S01` | Normal replenishment | `PENDING_APPROVAL` | `STANDARD` | None | 100 units ($3279.00) | $0.002400 | 0.37s |
| `S02` | Primary supplier insolvent | `PENDING_APPROVAL` | `SENIOR` | QA08, QA14 | 140 units ($3099.60) | $0.002400 | 0.32s |
| `S03` | Demand spike | `PENDING_APPROVAL` | `SENIOR` | QA05, QA06, QA08, QA12 | 210 units ($5355.00) | $0.002400 | 0.29s |
| `S04` | Conflicting forecasts | `PENDING_APPROVAL` | `SENIOR` | QA05, QA08, QA12 | 170 units ($4158.20) | $0.002400 | 0.33s |
| `S05` | Supplier delay plus hostile note | `PENDING_APPROVAL` | `SENIOR` | QA08, QA13 | 200 units ($6946.00) | $0.002400 | 0.50s |
| `S06` | Stockout | `PENDING_APPROVAL` | `SENIOR` | QA08 | 180 units ($6035.40) | $0.002400 | 0.40s |
| `S07` | Overstock | `NO_ACTION_NEEDED` | `STANDARD` | None | - | $0.002400 | 0.38s |
| `S08` | High-value PO | `PENDING_APPROVAL` | `SENIOR` | QA09 | 100 units ($50000.00) | $0.002400 | 0.47s |
| `S09` | Missing data | `BLOCKED` | `BLOCKED` | QA07, QA12 | 90 units ($2559.60) | $0.002400 | 0.37s |
| `S10` | Malformed LLM output | `FAILED` | `BLOCKED` | None | - | $0.001440 | 0.28s |

## Scenario Explanations and Ground Truth Verification
- **S01 (Normal replenishment)**: Inventory is below reorder point with sufficient days of cover; generates standard replenishment PO with zero QA findings.
- **S02 (Primary supplier insolvent)**: Primary vendor is INSOLVENT; system shifts order to alternate supplier, flagging QA14 (WARN) and escalating to SENIOR.
- **S03 (Demand spike)**: Sales in the last 7 days surged 3x; system flags QA06 (WARN) and escalates to SENIOR.
- **S04 (Conflicting forecasts)**: Trend line fit diverges sharply from 28-day moving average (>30%); flags QA05 (WARN) and escalates to SENIOR.
- **S05 (Supplier delay & hostile note)**: Primary vendor is delayed with prompt injection in notes; system applies 7-day lead time penalty, sanitizes note, flags QA13 (WARN), and orders normal quantity.
- **S06 (Stockout)**: On-hand stock is 0; flags QA08 (EXPEDITE) and escalates to SENIOR.
- **S07 (Overstock)**: On-hand inventory is 5,000 units (far above ROP); planner selects NO_ACTION and cycle resolves with NO_ACTION_NEEDED.
- **S08 (High-value PO)**: High unit cost causes order total to exceed $10,000; flags QA09 (WARN) and escalates to SENIOR.
- **S09 (Missing data)**: 60% of sales records removed, dropping data coverage below 80%; flags QA07 (CRITICAL) and terminates cycle as BLOCKED.
- **S10 (Malformed LLM output)**: LLM outputs unparsable JSON / arithmetic violations; guardrails fail retries and cycle fails safely with status FAILED.
