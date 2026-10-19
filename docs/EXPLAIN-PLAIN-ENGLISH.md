# Plain-English Architecture & Implementation Guide

This guide explains each part of the **Multi-Agent Supply Chain Decision System** in plain English. For each task and architectural component, it provides:
1. A real-world analogy
2. How the code works in simple terms
3. A 3-sentence interview answer

---

## T0: Project Setup and Contracts

### Real-World Analogy
Before breaking ground on a skyscraper, architects and engineers lay out the blueprints, zoning regulations, building codes, and safety contracts. T0 establishes the strict contractual scope (`SPEC.md`), task plan (`TASKS.md`), and agent rules (`AGENTS.md`) before any line of functional code is written.

### How the Code Works
We initialized the Git repository with strict LF line endings, `.gitignore` preventing data/secret leaks, and pushed the base scope contract to GitHub (`adwitiya-pandey/multi-agent-supply-chain-system`). This guarantees reproducible development in a clean Linux/WSL2 environment.

### 3-Sentence Interview Answer
I set up the repository foundation with exhaustive specification and task contracts defining a 5-agent sequential supply-chain system. The contract specifies deterministic mathematics owning all inventory numbers and an external human-in-the-loop approval gate. This architecture ensures safety, zero hallucinations in purchase orders, and complete auditability from day zero.

---

## T1: Project Scaffolding and SDK Verification

### Real-World Analogy
Before a flight crew boards a commercial airliner, maintenance engineers inspect the instruments, calibrate fuel gauges, and verify flight control sensors against manufacturer specifications. T1 builds the empty skeleton of the software aircraft and runs live probes against the CrewAI and Pydantic libraries to guarantee every underlying API behaves as documented.

### How the Code Works
Using Python 3.13 and `uv`, we created the modular package structure under `src/supplychain/` with all 21 modules stubbed out with docstrings. We set up GitHub Actions CI with Ruff linting/formatting and Pytest coverage, configured `.env.example` with zero secrets, and executed the SDK probe script verifying that offline ReAct tool calling, token tracking, and callback error propagation function properly in CrewAI 1.15.28.

### 3-Sentence Interview Answer
I scaffolded the project structure, dependency constraints, and GitHub Actions CI pipeline using Python 3.13 and uv. I verified the CrewAI 1.15 SDK behavior using an offline probe that proved ReAct fallback, token tracking, and task callback lifecycle without making external API calls. This confirmed all framework assumptions prior to implementing core business logic.

---

## T2: Message Contracts, Configuration, Structured Logging, and Audit Trail

### Real-World Analogy
Think of inter-agent messages like notarized legal customs declarations at an international border. If an incoming crate contains unexpected items not listed on the official manifest, customs officers immediately quarantine the shipment rather than guessing what the items are or silently passing them through. `extra="forbid"` acts as this customs inspection checkpoint between autonomous AI agents.

### Why `extra="forbid"` Matters Between Agents
Large Language Models frequently hallucinate subtle, non-standard fields (such as `discount_code: "FREE"`, `approved: true`, or `expedite_notes: "urgent"`). If a schema silently ignores extra fields (`extra="ignore"`), downstream agents or prompt templates might receive or act upon unvalidated side-channel information, bypassing guardrails. By setting `extra="forbid"`, any hallucinated field immediately triggers a `ValidationError`, halting the cycle fail-closed before any corrupted state can propagate.

### How the Code Works
- `models.py` implements Pydantic v2 schemas for all inter-agent messages with `extra="forbid"` and strict ASCII digit regexes that reject newlines and non-ASCII characters.
- `config.py` loads environment variables into typed settings using `pydantic-settings`, wrapping API keys in `SecretStr` so they are never printed in logs or string representations.
- `logging_setup.py` provides structlog JSON logging with a custom processor that filters out forbidden keys (such as prompts, raw email bodies, and notes) while retaining audit-safe identifiers and metrics.
- `audit.py` records append-only immutable events to `audit/audit.jsonl`, failing closed with `AuditError` if the audit record cannot be written.

### 3-Sentence Interview Answer
I implemented strict Pydantic v2 message schemas with `extra="forbid"` to ensure agents cannot pass hallucinated or unauthorized fields between tasks. I built a fail-closed, append-only JSONL audit log and a structured JSON logging pipeline that strictly filters out prompts, hostile note text, and secrets. This guarantees schema integrity, prevents prompt-injection payload leakage into logs, and enforces complete operational accountability.

---

## T3: Supply Database, Scenario Synthesis, and Defense-in-Depth Read-Only Access

### Real-World Analogy
Imagine a bank branch allowing researchers to inspect historical ledger transactions. The bank doesn't hand researchers a master key to the vault or a pen to rewrite ledger entries; instead, researchers view laminated read-only ledger sheets behind three layers of bulletproof glass, while bank tellers hand over only specific pre-approved summary cards.

### Why `mode=ro`, `query_only`, and the Authorizer Matter, and Why Agents Get Fixed Functions Instead of SQL
1. **`mode=ro` (OS/Filesystem level)**: Tells SQLite to open the file descriptor strictly in read-only mode, blocking any OS-level file modifications.
2. **`PRAGMA query_only=ON` (Engine level)**: Instructs SQLite's query planner to refuse any database-modifying statement (`INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`).
3. **`sqlite3` Authorizer (Callback level)**: A gatekeeper hook executed before statement compilation that explicitly permits only `SQLITE_SELECT`, `SQLITE_READ`, and `SQLITE_FUNCTION`, and returns `SQLITE_DENY` for any write, drop, or database-attach attempts (`ATTACH DATABASE`).
4. **Fixed Functions vs. LLM SQL**: If agents were given a generic SQL execution tool, an LLM could hallucinate arbitrary joins, leak database schema internals, or fall victim to SQL injection through untrusted text in supplier notes. By providing fixed Python query functions (`get_sales_window`, `get_inventory`, `get_supplier_options`), the system eliminates the SQL attack surface entirely.

### How the Code Works
- `scripts/build_db.py` creates a clean SQLite schema (`meta`, `warehouses`, `skus`, `suppliers`, `sku_suppliers`, `sales_daily`, `inventory`, `market_signals`) with CHECK constraints and seeds 120 days of deterministic data for 12 SKUs, 3 warehouses, and 5 suppliers.
- Scenarios S01 through S10 are defined in `data/scenarios/` and applied as deterministic patches (e.g. insolvent primary supplier in S02, demand spike in S03, hostile injection note in S05, stockout in S06, missing sales rows in S09).
- `db.py` implements `get_ro_connection()` utilizing the 3-layer read-only defense.

### 3-Sentence Interview Answer
I built a reproducible synthetic supply chain database with 10 simulated operational scenarios using SQLite and deterministic random seeding. I enforced a 3-layer read-only security architecture combining URI `mode=ro`, SQLite's `query_only` pragma, and an engine-level authorizer callback. Rather than exposing arbitrary SQL tools to LLMs, I exposed strictly typed Python query functions to permanently eliminate SQL injection and unauthorized data mutation.

---

## T4: Deterministic Planning Mathematics and Inventory Modeling

### Real-World Analogy
Imagine packing an emergency reserve kit for a transatlantic sailing expedition. You face two compounding uncertainties: how much fresh water your crew consumes each day (demand variability) and how many extra days storm weather might delay your arrival at port (lead time variability). If either demand surges OR the ship is delayed, you run out of water. Safety stock with variable lead time mathematically accounts for both risks simultaneously.

### Why Safety Stock Has Variable Lead Time and Why the LLM Does Not Compute It
1. **The Formula**:
   $$\text{SS} = \lceil z \cdot \sqrt{\text{LT} \cdot \sigma_d^2 + d^2 \cdot \sigma_{\text{LT}}^2} \rceil$$
   The first term under the square root ($\text{LT} \cdot \sigma_d^2$) buffers against day-to-day demand fluctuations during an average delivery window. The second term ($d^2 \cdot \sigma_{\text{LT}}^2$) buffers against supplier transit delays when demand continues at the mean daily rate.
2. **Why the LLM Does Not Compute It**:
   Large Language Models are probabilistic token predictors, not calculators. Under token generation, arithmetic operations like square roots, non-linear inverse normal CDF conversions ($\text{inv\_cdf}(0.95) \approx 1.645$), and integer ceilings frequently hallucinate subtle discrepancies (e.g., claiming $\sqrt{128} \approx 12$ instead of $11.31$, or calculating $85$ units instead of $110$). In enterprise supply chain procurement, an error of 25 units or a misplaced decimal translates directly to stockouts or wasted working capital. Therefore, deterministic Python code owns 100% of the numbers, while agents only interpret, contextualize, and flag anomalies.

### How the Code Works
- `planning.py` implements pure functions using Python stdlib (`math.ceil`, `math.sqrt`, `statistics.NormalDist`).
- It computes baseline demand via Method A (28-day moving average) and Method B (14-day future projection from a 56-day least-squares line fit floored at 0).
- It calculates safety stock, reorder point (ROP), target replenishment levels, and rounds order quantities to supplier MOQ and pack size multiples.
- It detects forecast conflicts ($>30\%$ divergence) and sudden demand spikes ($\ge 2\times$ baseline).

### 3-Sentence Interview Answer
I implemented deterministic inventory replenishment mathematics in pure Python using standard normal distributions and two forecasting baselines. The safety stock formula simultaneously buffers demand variance and supplier lead-time variance using exact statistical calculations. The LLM is strictly prohibited from calculating procurement numbers to eliminate hallucination risk, while deterministic guardrails verify every downstream decision against ground-truth arithmetic.




