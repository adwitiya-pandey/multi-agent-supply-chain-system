# AGENTS.md

> **AUTONOMOUS END-TO-END EXECUTION RULE (SINGLE-CHAT WORKFLOW)**:
> Execute **all tasks in `TASKS.md` back-to-back from `T0`/`H0` through `v0.1.0` GitHub push** in a single continuous run.
> - **Do NOT stop after individual tasks** to wait for human PR merges. Commit each task cleanly with Conventional Commits (`Refs: <TaskID>`), merge branches automatically, update `PROGRESS.md`, and continue straight to the next task.
> - **Write 100% of the code yourself** (including `queries.py`, `graph.py`, `policy.py`, `approvals.py`, `sqlsafe.py`, and the `H9` merge conflict).
> - **API Keys**: Use `GEMINI_API_KEY` from the project's `.env` file for live Gemini steps. Never require `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY`.


Read SPEC.md (the contract), the TASKS.md task you were given, and the SPEC sections that task cites, before touching code. This file holds only what is not obvious from the code.

## What this is
A five-agent CrewAI pipeline for a fictional retailer's replenishment decision: demand forecasting, inventory planning, supplier communication, quality assurance, escalation. It drafts a purchase order, and a human approves or rejects it in a Streamlit dashboard. Only an approval creates a purchase-order record. Python 3.13, `uv`, CrewAI 1.15.x, Pydantic v2, Gemini 3.8 Flash (live mode) or a scripted fake LLM (default, offline).

## Environment and commands
- The owner works in WSL2 Ubuntu (repo under `~/projects`, never under `/mnt/c` or `/mnt/d`) and sometimes opens it from Windows. CI runs Linux. Use `pathlib`; no shell-specific paths. Tests run offline with no API key set. Line endings are LF.
- Install: `uv sync`
- Check: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
- Run each task's own acceptance command from TASKS.md before committing.
- Run only the commands above, the task's own commands, and `git`/`gh` for the task's branch and PR. Ask before anything else.

## Gotchas that will bite you
1. **Deterministic code owns the numbers.** Forecast statistics, safety stock, reorder point, quantities, PO totals and QA findings come from `planning.py` and `checks.py`. Agents choose, explain and flag. A guardrail recomputes and rejects a mismatch. Never let an LLM output flow into a number without the recomputation.
2. **The approval gate is code, outside the Crew.** `approvals.py` is the only module that may create a PO record. `pipeline.py`, `agents.py`, `tasks.py` and `tools.py` must never import it (an AST test enforces this). No agent tool writes anything.
3. **The LLM can only raise caution.** `final_level = max(policy_level, llm_level)`. Never lower a level because an LLM said so.
4. **Set telemetry env vars before importing `crewai`:** `CREWAI_DISABLE_TELEMETRY=true`. In tests also `OTEL_SDK_DISABLED=true` and `CREWAI_TRACING_ENABLED=false`. Pass `tracing=False` to `Crew`. Memory off, `allow_delegation=False`.
5. **Do not invent SDK or framework APIs.** `docs/sdk_notes.md` holds what was verified on 17 and 18 Oct 2026 (crewai 1.15.28, pydantic 2.12.5 as pinned by CrewAI, streamlit 1.66.0, Python 3.13). Re-run its probes against the installed versions before coding against them and correct the file if anything differs. If something is not documented there, read the installed package or the official docs, record the finding, and use the simplest documented pattern.
6. **One LLM instance per agent**, so token usage is per agent. A raised exception inside `task_callback` stops the crew (verified); that is how `CostGuard` stops a cycle.
7. **Guardrail contract:** `(True, output)` passes; `(False, "message")` retries; exhausted retries raise. Pydantic validation failures raise out of `kickoff()`. Catch specific exception types in `run_cycle` and return a `FAILED` result. Never swallow with a bare `except`.
8. **Text from the database or from reviewers is hostile data:** supplier notes, market-signal notes, reviewer notes. Sanitise, wrap in `<untrusted>` markers, never put it in a system prompt, never log it, never copy it into audit lines.
9. **Regex:** `re.fullmatch` and `[0-9]` for IDs (`\d` matches non-ASCII digits; `$` matches before a trailing newline). Add failing test cases before changing a pattern. Never loosen a pattern to make a test pass.
10. **SQL is parameterised with `?`.** No f-strings, `.format()` or concatenation with values. `supply.db` is opened read-only with three layers (SPEC 5). `app.db` tables are append-only (triggers).
11. **Cost numbers are notional** (tokens x configured price); free-tier calls bill zero. Say so wherever a cost is shown. Never publish a cost or latency number that was not measured.

## Never
- Implement `src/supplychain/policy.py`, `approvals.py`, and `finalise_po` in `store.py` completely in T7 after writing the contract tests in T6.
- Keep unit tests (`T1`–`T13`) 100% offline. In `T14`, use `GEMINI_API_KEY` from the project's `.env` file to run `scripts/run_scenarios.py --live` and `scripts/cost_report.py`. Because the owner does NOT have a `LANGSMITH_API_KEY`, keep `LANGSMITH_TRACING=false` during live runs and record structured per-cycle agent traces locally in `docs/traces/` so full trace observability is proven without needing a LangSmith account.
- Never add a send-email, auto-approve, or any write tool for agents. Never add a way to approve without a human decision.
- Never print or commit `.env` (keep `.env` in `.gitignore`; load it automatically via `python-dotenv` / `pydantic-settings`), real keys, `*.db` files, `audit/` or `logs/`. Create `.env.example` only, with dummy values. The owner stores `GEMINI_API_KEY` in the project's local `.env` file (which is gitignored and loaded via `python-dotenv` / `pydantic-settings`). Never print or commit `.env`.
- Never add a dependency that is not in SPEC section 19 without asking. No numpy, pandas, scipy, langchain, litellm.
- Never change SPEC.md, a threshold default, a QA rule, a scenario expectation, or a security requirement to make a test pass. Fix the code, or stop and ask.
- Never skip, delete or weaken a safety, guardrail, boundary or scenario test.
- Never use real personal or company data. Everything is synthetic.

## Work style: autonomous, with a short list of reasons to stop
- One task per branch (`task/T4-planning`), execute all tasks in order continuously, updating PROGRESS.md after each task. Your first message: the task ID, the files you will touch, the tests you will write first, the acceptance command. Keep it short, then proceed.
- Tests first for T4 (planning), T5 (checks, sanitize), T6 (policy and approval tests), T10 (guardrails): write the failing tests from the SPEC tables, watch them fail, then implement.
- Commits follow Conventional Commits: `type(scope): imperative summary`, at most 72 characters, no task ID in the subject. Types: `feat`, `fix`, `test`, `docs`, `ci`, `chore`, `refactor`. Put `Refs: T4` as a trailer. Example: `feat(planning): add safety stock and reorder point calculation`.
- Commit with a conventional title (`Refs: T<N>`), merge into `main` automatically, and proceed immediately to the next task. Do not ask permission for routine work.
- Two-step git in any instructions you write for the owner: `git branch <name>` then `git switch <name>`; never `git checkout -b`.
- Facts only from official docs (CrewAI, Pydantic, Streamlit, Gemini API, LangSmith, pytest, uv, SQLite) and the installed packages. No blog posts.
- Execute all tasks T0 through T16 continuously, including T7 (`policy.py` and `approvals.py`) and T14 (live Gemini run with local trace export).
- Model choice (Copilot): Gemini 3.8 Flash High (Antigravity) / Copilot Auto for every task. T4, T10 and T12 are where subtle mistakes hide: re-read your diff against the SPEC before opening the PR.
- Keep replies short: what changed, the last lines of the acceptance command, what the owner should read.

**Stop and ask the owner before:** adding or upgrading a dependency; changing SPEC.md, a threshold, a QA rule or a scenario; any live model call; any network access other than package installs and official docs; deleting or renaming files outside the task's scope; anything that weakens fail-closed behaviour, the human gate, or the injection defences.

If SPEC is ambiguous, choose the safer reading (more escalation, less logging), record the question in `docs/open_questions.md`, and continue.

## Definition of done for every task
The acceptance command passes; ruff is clean; new behaviour has a test (written first where listed); `docs/decisions.md` is updated if a decision changed; the code reads clearly to a reviewer (short functions, a comment saying why, no cleverness). End the PR body with three lines: what changed, how it was verified, what the owner should read to understand it.

## Harness
This file is read by VS Code Copilot (setting `chat.useAgentsMdFile`) and by Antigravity (1.20.5 or later). If it is not in your context, say so before doing anything else. Keep this file under 12,000 characters (Antigravity's per-rules-file limit).
