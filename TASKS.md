# TASKS: multi-agent-supply-chain-system

> **AUTONOMOUS END-TO-END EXECUTION RULE (SINGLE-CHAT WORKFLOW)**:
> Execute **all tasks in `TASKS.md` back-to-back from `T0`/`H0` through `v0.1.0` GitHub push** in a single continuous run.
> - **Do NOT stop after individual tasks** to wait for human PR merges. Commit each task cleanly with Conventional Commits (`Refs: <TaskID>`), merge branches automatically, update `PROGRESS.md`, and continue straight to the next task.
> - **Write 100% of the code yourself** (including `queries.py`, `graph.py`, `policy.py`, `approvals.py`, `sqlsafe.py`, and the `H9` merge conflict).
> - **API Keys**: Use `GEMINI_API_KEY` from the project's `.env` file for live Gemini steps. Never require `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY`.


Order matters. Execute all tasks sequentially from start to finish in a single autonomous run. Owner tags: **AGENT** = coding agent does it; **HUMAN** = the owner does it; **REVIEW** = the owner reads and explains it back.

**Gate before starting:** Project A and Project B are tagged `v0.1.0` (the resume lists those two repos with links). This repo is third in the build order.

| Phase | Tasks |
|---|---|
| Foundations | T0, T1, T2 |
| Data and pure logic | T3, T4, T5 |
| The human gate | T6, T7 (AGENT) |
| Agents | T8, T9, T10 (AGENT) |
| Evidence | T11, T12 (AGENT) |
| Observability and docs | T13, T14, T15 (AGENT) |
| Ship | T16 (AGENT) |

Branch model: `main` plus one branch per task (`task/T4-planning`). The agent commits on each task branch, runs tests, merges into `main` automatically, documents the task in `docs/EXPLAIN-PLAIN-ENGLISH.md`, and continues to the next task without stopping. Two-step git always: `git branch <name>`, then `git switch <name>`.

Commit style: Conventional Commits with a `Refs: T4` trailer (see AGENTS.md).

---

## T0 (AGENT): create public GitHub repository `adwitiya-pandey/multi-agent-supply-chain-system`
Work in WSL2 Ubuntu under `~/projects`. `gh auth status` must show the account `adwitiya-pandey`.
1. `mkdir -p ~/projects/multi-agent-supply-chain-system && cd ~/projects/multi-agent-supply-chain-system`. Copy in this pack's files (`AGENTS.md`, `SPEC.md`, `TASKS.md`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.vscode/`, `.github/agents/`, `docs/`). `PLAN-PRIVATE.md` stays on your disk (gitignored). Then `find . -name '*Zone.Identifier' -delete`.
2. One command at a time: `git init`, `git branch -M main`, `git add .`, `git status` (no Zone.Identifier, no PLAN-PRIVATE.md), `git commit -m "docs: add scope contract (AGENTS, SPEC, TASKS)"`.
3. `gh repo create adwitiya-pandey/multi-agent-supply-chain-system --public --source=. --remote=origin --push --description "Five-agent CrewAI supply-chain pipeline: Pydantic-validated messages, deterministic guardrails, human approval gate, per-agent cost tracking"`. Open the URL in a private window.
4. In VS Code (WSL window) choose the `builder` agent, confirm the model shown is Gemini 3.8 Flash High (Antigravity) / Copilot Auto, and ask: "List the instruction files you loaded in this chat and quote the first line of each." `AGENTS.md` must be listed.
5. Read SPEC sections 1 to 12 once. Write nothing.
6. **Resume check:** the resume lists this project without a link. When T16 is done add `github.com/adwitiya-pandey/multi-agent-supply-chain-system` to that line. Until then, say "in progress" if asked.
Accept: GitHub shows the pack files; the instruction-file check passes.

## T1 (AGENT): scaffold, CI, settings, SDK facts
Branch: `git branch task/T1-scaffold` then `git switch task/T1-scaffold`.
1. `uv init --package --python 3.13`; layout from SPEC 19 with empty modules, each with a one-line docstring. Dependencies exactly as SPEC 19 (pinned; extra `tracing` optional).
2. `.env.example` with every variable in SPEC 18 and dummy values; `LICENSE` (MIT, holder Adwitiya Pandey); minimal `README.md` saying "Status: in progress".
3. `.github/workflows/ci.yml` per SPEC 19. Look up current action versions; do not guess.
4. `docs/sdk_notes.md` is pre-filled. In a scratch script (not committed), re-run its probe snippets against the versions `uv` installs and correct the file where anything differs.
5. `tests/conftest.py` sets `CREWAI_DISABLE_TELEMETRY=true`, `OTEL_SDK_DISABLED=true`, `CREWAI_TRACING_ENABLED=false` before any `crewai` import. One smoke test imports `crewai` and the package.
Accept: `uv sync` then `uv run ruff check . && uv run pytest -q` pass; `docs/sdk_notes.md` is re-verified.

## T2 (AGENT): models, config, logging, audit
1. `models.py` per SPEC 6. `config.py` per SPEC 18 (`SecretStr`, validation, never echo secrets). `logging_setup.py` (structlog JSON, contextvars, allowed fields only, SPEC 14). `audit.py` (append-only JSONL, fail-closed, no payloads, `sha256` helper).
2. Tests: every model with valid, extra field, wrong type, bound violations, bad ID formats (trailing newline, non-ASCII digits); config defaults and validation; log capture proves no note text or key can be logged; audit write failure raises.
Accept: `uv run pytest tests/test_models.py tests/test_config.py tests/test_logging.py tests/test_audit.py -q`.
REVIEW: explain why `extra="forbid"` matters between agents.

## T3 (AGENT): supply database, scenarios, read-only access
1. `scripts/build_db.py` (SPEC 5 schema; deterministic seed; `--scenario`). `data/scenarios/S01..S10.json` (SPEC 16; expected quantities computed by `planning.py` later, so store rules, not typed numbers). `db.py` with the three read-only layers and the fixed functions.
2. Tests: DB builds for every scenario; CHECK constraints reject bad rows; INSERT, UPDATE, DELETE, DROP and ATTACH all fail through `db.py` (S1); each patch has an observable effect (insolvent supplier, spike, missing rows, zero stock, injection note present); same seed gives the same data.
Accept: `uv run pytest tests/test_db.py tests/test_build_db.py -q`; `uv run python scripts/build_db.py --scenario S01 --out data/supply.db` succeeds.
REVIEW: explain `mode=ro`, `query_only` and the authorizer, and why the agents get fixed functions and not SQL.

## T4 (AGENT): planning math (tests first)
1. Write `tests/test_planning.py` from SPEC 7 with **hand-computed** expectations (show the arithmetic in comments): method a, method b (line fit), conflict, spike, coverage, safety stock, reorder point, target, needed, rounding to MOQ and pack, urgency, eligible suppliers and order, delayed lead time penalty, edge cases (zero demand, zero std, `needed == 0`, MOQ larger than needed). Watch them fail.
2. Implement `planning.py` (stdlib only: `statistics.NormalDist`, `math.ceil`).
Accept: `uv run pytest tests/test_planning.py -q`.
REVIEW: explain safety stock with variable lead time in your own words, and why the LLM does not compute it.

## T5 (AGENT): QA rules and sanitising (tests first)
1. `tests/test_checks.py` (one test per rule QA01..QA14, plus "no findings" and "merge keeps rule findings") and `tests/test_sanitize.py` (at least 12 injection positives, 8 negatives, hidden characters, length cap, markers) from SPEC 10 and S3. Watch them fail.
2. Implement `checks.py` and `sanitize.py`.
Accept: `uv run pytest tests/test_checks.py tests/test_sanitize.py -q`.
REVIEW: explain why the QA agent cannot remove a rule finding.

## T6 (AGENT): policy and approval tests, stubs
1. `tests/test_policy.py` (full table from SPEC 11, including boundaries at exactly the threshold, exactly two WARN, confidence exactly 0.6, `max` of policy and LLM level), `tests/test_approvals.py` (every numbered rule in SPEC 12, double decision, blocked approve, PO copied from the stored result not the request, audit lines), `tests/test_store.py` (triggers reject UPDATE and DELETE).
2. `store.py`: schema, triggers, `save_cycle`, `get_cycle`, `list_pending`. In `policy.py` and `approvals.py` write only the function signatures with docstrings and `raise NotImplementedError`.
Accept: the new tests fail only because of `NotImplementedError`; `uv run pytest tests/test_store.py -q` passes.

## T7 (AGENT): implement `policy.py`, `approvals.py`, and `finalise_po`
Implement `policy.py` (SPEC 11) and `approvals.py` with `finalise_po` in `store.py` (SPEC 12) until `tests/test_policy.py`, `tests/test_approvals.py`, and `tests/test_store.py` pass, and explain the logic in `docs/EXPLAIN-PLAIN-ENGLISH.md`.
Accept: all three test files pass and `ruff` is clean.

## T8 (AGENT): tools and import boundaries
1. `tools.py`: the CrewAI tools of SPEC 8 (`@tool` from `crewai.tools`), each with a Pydantic-validated argument, a read-only implementation over `db.py` and `planning.py`, and text from notes wrapped by `sanitize.py`. Tool results are strings (JSON).
2. `tests/test_tools.py` (valid, invalid ID, unknown SKU returns an error string, hostile note wrapped and flagged) and `tests/test_boundaries.py` (SPEC 4 boundaries and the last rule of SPEC 12; tools snapshot: exact tool names per agent; no write calls in `tools.py` or `agents.py`).
Accept: `uv run pytest tests/test_tools.py tests/test_boundaries.py -q`.

## T9 (AGENT): scripted LLM, LLM factory, cost guard
1. `scripted.py`: `ScriptedLLM(BaseLLM)` following the verified pattern in `docs/sdk_notes.md`: replies in ReAct format so the real tools run, tracks fake token usage per instance, supports a scenario-controlled list of replies and an `oracle` mode that builds correct outputs from `planning.py` and `checks.py`, plus fault modes for S10 (wrong number, invalid JSON). `llm.py`: factory returning the Gemini LLM (`gemini/<model>`, key from config) or the scripted one by `LLM_MODE`. `cost.py`: price table, per-agent `CostReport`, `CostGuard`, `BudgetExceeded`.
2. Tests: scripted LLM drives a one-agent crew and a tool call executes; usage tracked per instance; `CostGuard` raises over budget and not at exactly the budget; cost math hand-computed; the Gemini branch constructs with a dummy key and makes no network call.
Accept: `uv run pytest tests/test_scripted.py tests/test_cost.py tests/test_llm.py -q`.

## T10 (AGENT): agents, tasks, guardrails, pipeline (tests first for guardrails)
1. `tests/test_guardrails.py`: one failing output per guardrail rule in SPEC 8 and 9 (wrong ROP, wrong qty, ineligible supplier, email with a foreign amount, a URL in the email, missing deterministic flag). Watch them fail.
2. `guardrails.py`, `agents.py`, `tasks.py`, `pipeline.py` (`run_cycle`): sequential crew, one LLM per agent, `task_callback=CostGuard`, specific exception handling to `FAILED` / `BUDGET_EXCEEDED`, `policy_level` and merge of rule findings, `final_level = max(...)`, `save_cycle`, audit lines, structlog contextvars.
3. Tests: S01 end to end in oracle mode; `FAILED` on a malformed message; `BUDGET_EXCEEDED` with a tiny budget; findings merge; the cycle never creates a PO (assert `purchase_orders` is empty after `run_cycle`).
Accept: `uv run pytest tests/test_guardrails.py tests/test_pipeline.py -q`.
REVIEW: draw the five tasks and say which fields each guardrail checks.

## T11 (AGENT): ten scenarios offline, results report
1. `tests/test_scenarios.py`: all ten scenarios through `run_cycle` in oracle mode against the JSON expectations (status, level, findings, PO yes or no, quantity computed by `planning.py`). S10 uses the fault modes.
2. `scripts/run_scenarios.py` (`--mode oracle` default; `--live` exists but the agent never runs it) writes `docs/scenario_results.md` table (scenario, status, level, findings, PO, cost) with a header that says the mode used.
3. `scripts/cost_report.py` writes `docs/cost_report.md` from stored cycles: per-agent tokens and notional cost, with the notional-cost caveat.
Accept: `uv run pytest tests/test_scenarios.py -q`; `uv run python scripts/run_scenarios.py --mode oracle` exits 0 and writes the table.

## T12 (AGENT): Streamlit dashboard
1. `app.py` (SPEC 12, 14): sidebar with reviewer name and mode banner (scripted mode: "SCRIPTED DEMO: outputs are deterministic, not Gemini"); scenario picker and "Run cycle" button; pending list; a detail view with the forecast, plan, PO draft, email (read-only text), QA findings, policy level, final level, per-agent cost; Approve and Reject buttons (Approve disabled when `BLOCKED`); history of decisions and POs. All text from the database or the LLM rendered as plain text, never as HTML or Markdown with raw HTML.
2. `tests/test_app.py` with `streamlit.testing.v1.AppTest`: pending renders; approve creates a PO row; blocked cannot be approved; banner shown in scripted mode; hostile reviewer note stored sanitised.
Accept: `uv run pytest tests/test_app.py -q`; `uv run streamlit run src/supplychain/app.py` starts (the owner checks it in a browser).
REVIEW: run it yourself, approve one PO, and look at `purchase_orders` with `sqlite3`.

## T13 (AGENT): tracing hook and CI hardening
1. `tracing.py::enable_langsmith()` exactly per the LangSmith docs page for CrewAI (find it in the LangSmith docs; record the URL and the packages in `docs/sdk_notes.md`). Off unless `LANGSMITH_TRACING=true`. Unit test that it does nothing when off and that no network call is made in tests.
2. CI: coverage gate 85%, scenario tests, boundary tests, `uv lock --check`.
Accept: `uv run pytest -q --cov=src/supplychain --cov-fail-under=85`.

## T14 (AGENT): live Gemini scenario run, local trace capture & measured cost report
1. Using `GEMINI_API_KEY` from the project's `.env` file (with `LANGSMITH_TRACING=false` since no LangSmith key is required), run `uv run python scripts/run_scenarios.py --live` with rate-limit-friendly pacing and `uv run python scripts/cost_report.py`.
2. Export the structured per-agent trace summary to `docs/trace_summary.md` and update `docs/scenario_results.md` and `docs/cost_report.md`.
Accept: `docs/scenario_results.md`, `docs/cost_report.md`, and `docs/trace_summary.md` updated and committed.

## T15 (AGENT): documentation
1. `README.md`: title, badges, one-line description, architecture diagram (ASCII from SPEC 4), what it proves and does not (section 17 wording), quickstart (copy-paste: prerequisites, clone, `uv sync`, `cp .env.example .env`, build DB, run scenarios offline, start Streamlit, approve a PO), live mode instructions (key as shell variable), scenario table, cost section (measured numbers from T14 only), security summary, limitations (SPEC 22), repo tree, licence.
2. `docs/architecture.md`, `docs/threat_model.md` (assets, trust boundaries, threats and mitigations mapped to S1 to S10, residual risks), `docs/decisions.md` (SPEC 21, each with a "what would change my mind" line).
3. Re-run the quickstart commands exactly as written in a fresh `git clone` into a temp folder and fix anything that fails.
Accept: the quickstart commands run from a fresh clone; links resolve.

## T16 (AGENT): final verification, git tag `v0.1.0`, and push to GitHub
1. Fresh clone into a temp folder; follow the README exactly; approve a PO in scripted mode.
2. Check the claims table in `PLAN-PRIVATE.md`; every line must be true.
3. `git tag -a v0.1.0 -m "First release"`, `git push origin v0.1.0`; create a GitHub release with the README summary.
4. Add the repo link to the resume line; send the updated resume only to new recipients.
Accept: CI green on `main`; tag visible; the README works for someone who is not you.
