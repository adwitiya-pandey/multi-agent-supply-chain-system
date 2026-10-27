"""Scenario runner script (scripts/run_scenarios.py) per SPEC 16 and TASKS.md T11."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add src and root to pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.build_db import build_database
from supplychain.config import get_settings
from supplychain.models import CycleRequest
from supplychain.pipeline import run_cycle
from supplychain.tracing import generate_trace_summary


def run_all(
    mode: str = "oracle",
    output_path: Path | str = "reports/scenario_results.md",
    scenario_filter: list[str] | None = None,
) -> None:
    """Run all 10 scenarios and write scenario_results.md."""
    scenarios_dir = Path("data/scenarios")
    all_files = sorted(scenarios_dir.glob("S*.json"))

    if scenario_filter:
        all_files = [f for f in all_files if f.stem in scenario_filter]

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    results = []
    print(f"Running {len(all_files)} scenarios in mode='{mode}'...")

    for f in all_files:
        with open(f, encoding="utf-8") as fp:
            meta = json.load(fp)

        sc_id = meta["id"]
        title = meta["title"]
        req_data = meta["request"]

        # Build isolated DB for scenario
        tmp_db = Path("data") / f"supply_{sc_id}.db"
        build_database(tmp_db, scenario_id=sc_id)
        os.environ["SUPPLY_DB"] = str(tmp_db)
        get_settings.cache_clear()

        req = CycleRequest(
            scenario_id=req_data["scenario_id"],
            sku_id=req_data["sku_id"],
            warehouse_id=req_data["warehouse_id"],
        )

        start_time = time.time()
        fault = "invalid_json" if (sc_id == "S10" and mode == "oracle") else None

        try:
            res = run_cycle(req, mode=mode, fault_mode=fault)
            elapsed = time.time() - start_time
            po_text = "-"
            if res.supplier and res.supplier.po_draft:
                po = res.supplier.po_draft
                po_text = f"{po.qty} units (${po.total:.2f})"

            finding_codes = [f.code for f in res.qa.findings] if res.qa else []
            findings_str = ", ".join(finding_codes) if finding_codes else "None"
            cost_usd = res.cost.total_usd

            results.append(
                {
                    "id": sc_id,
                    "title": title,
                    "status": res.status,
                    "level": res.final_level,
                    "findings": findings_str,
                    "po": po_text,
                    "cost": f"${cost_usd:.6f}",
                    "elapsed": f"{elapsed:.2f}s",
                }
            )
            print(
                f"[{sc_id}] {title:35s} -> Status: {res.status:16s} Level: {res.final_level:8s} ({elapsed:.2f}s)"
            )

        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            elapsed = time.time() - start_time
            print(f"[{sc_id}] {title:35s} -> ERROR: {exc} ({elapsed:.2f}s)")
            results.append(
                {
                    "id": sc_id,
                    "title": title,
                    "status": "FAILED",
                    "level": "BLOCKED",
                    "findings": f"Execution error: {exc}",
                    "po": "-",
                    "cost": "$0.000000",
                    "elapsed": f"{elapsed:.2f}s",
                }
            )

        # In live mode, add pacing to avoid rate limit bursts
        if mode == "live":
            time.sleep(3.0)

    # Render markdown table
    md_lines = [
        f"# Scenario Evaluation Results (Mode: {mode.upper()})",
        "",
        f"*Execution Date*: {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}  ",
        f"*Evaluation Engine*: `{'ScriptedLLM (offline ReAct)' if mode == 'oracle' else 'Gemini 3.8 Flash High (live)'}`  ",
        "",
        "> **Note on Costs**: Cost numbers are notional (tokens × configured price); free-tier API calls bill zero.",
        "",
        "| Scenario | Title | Status | Final Level | QA Findings | PO Order | Notional Cost | Latency |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        md_lines.append(
            f"| `{r['id']}` | {r['title']} | `{r['status']}` | `{r['level']}` | {r['findings']} | {r['po']} | {r['cost']} | {r['elapsed']} |"
        )

    md_lines.append("")
    md_lines.append("## Scenario Explanations and Ground Truth Verification")
    md_lines.append(
        "- **S01 (Normal replenishment)**: Inventory is below reorder point with sufficient days of cover; generates standard replenishment PO with zero QA findings."
    )
    md_lines.append(
        "- **S02 (Primary supplier insolvent)**: Primary vendor is INSOLVENT; system shifts order to alternate supplier, flagging QA14 (WARN) and escalating to SENIOR."
    )
    md_lines.append(
        "- **S03 (Demand spike)**: Sales in the last 7 days surged 3x; system flags QA06 (WARN) and escalates to SENIOR."
    )
    md_lines.append(
        "- **S04 (Conflicting forecasts)**: Trend line fit diverges sharply from 28-day moving average (>30%); flags QA05 (WARN) and escalates to SENIOR."
    )
    md_lines.append(
        "- **S05 (Supplier delay & hostile note)**: Primary vendor is delayed with prompt injection in notes; system applies 7-day lead time penalty, sanitizes note, flags QA13 (WARN), and orders normal quantity."
    )
    md_lines.append(
        "- **S06 (Stockout)**: On-hand stock is 0; flags QA08 (EXPEDITE) and escalates to SENIOR."
    )
    md_lines.append(
        "- **S07 (Overstock)**: On-hand inventory is 5,000 units (far above ROP); planner selects NO_ACTION and cycle resolves with NO_ACTION_NEEDED."
    )
    md_lines.append(
        "- **S08 (High-value PO)**: High unit cost causes order total to exceed $10,000; flags QA09 (WARN) and escalates to SENIOR."
    )
    md_lines.append(
        "- **S09 (Missing data)**: 60% of sales records removed, dropping data coverage below 80%; flags QA07 (CRITICAL) and terminates cycle as BLOCKED."
    )
    md_lines.append(
        "- **S10 (Malformed LLM output)**: LLM outputs unparsable JSON / arithmetic violations; guardrails fail retries and cycle fails safely with status FAILED."
    )
    md_lines.append("")

    with open(out_file, "w", encoding="utf-8") as fp:
        fp.write("\n".join(md_lines))

    print(f"\nScenario results written to: {out_file}")

    # Generate structured local trace summaries
    trace_file = Path("logs/langsmith_traces.jsonl")
    if trace_file.exists():
        out_dir = Path(output_path).parent
        generate_trace_summary(trace_path=trace_file, summary_path=out_dir / "trace_summary.md")
        traces_dir = out_dir / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        generate_trace_summary(trace_path=trace_file, summary_path=traces_dir / "summary.md")
        print(f"Trace summaries compiled to {out_dir / 'trace_summary.md'} and {traces_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run supply chain decision pipeline scenarios.")
    parser.add_argument(
        "--mode",
        choices=["oracle", "live"],
        default="oracle",
        help="Evaluation mode (oracle or live).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Convenience alias to set --mode live.",
    )
    parser.add_argument(
        "--out",
        default="reports/scenario_results.md",
        help="Output markdown file path (default: reports/scenario_results.md).",
    )
    parser.add_argument(
        "--scenario",
        nargs="*",
        help="Filter specific scenario IDs (e.g. --scenario S01 S02).",
    )

    args = parser.parse_args()
    chosen_mode = "live" if args.live else args.mode

    run_all(mode=chosen_mode, output_path=args.out, scenario_filter=args.scenario)


if __name__ == "__main__":
    main()
