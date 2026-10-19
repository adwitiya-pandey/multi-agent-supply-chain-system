"""Builds the synthetic read-only supply SQLite database with deterministic seeding and scenario patching."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE warehouses(
    warehouse_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE skus(
    sku_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE suppliers(
    supplier_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DELAYED','ON_HOLD','INSOLVENT')),
    reliability REAL NOT NULL CHECK(reliability BETWEEN 0 AND 1),
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE sku_suppliers(
    sku_id TEXT,
    supplier_id TEXT,
    unit_cost REAL NOT NULL CHECK(unit_cost > 0),
    moq INTEGER NOT NULL CHECK(moq > 0),
    pack_size INTEGER NOT NULL CHECK(pack_size > 0),
    lead_time_days INTEGER NOT NULL CHECK(lead_time_days > 0),
    lead_time_std REAL NOT NULL CHECK(lead_time_std >= 0),
    is_primary INTEGER NOT NULL CHECK(is_primary IN (0, 1)),
    PRIMARY KEY(sku_id, supplier_id)
);

CREATE TABLE sales_daily(
    sale_date TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    units INTEGER NOT NULL CHECK(units >= 0),
    PRIMARY KEY(sale_date, sku_id, warehouse_id)
);

CREATE TABLE inventory(
    sku_id TEXT,
    warehouse_id TEXT,
    on_hand INTEGER NOT NULL CHECK(on_hand >= 0),
    on_order INTEGER NOT NULL CHECK(on_order >= 0),
    PRIMARY KEY(sku_id, warehouse_id)
);

CREATE TABLE market_signals(
    signal_id INTEGER PRIMARY KEY,
    sku_id TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('PROMO','COMPETITOR','WEATHER','NEWS')),
    note TEXT NOT NULL
);
"""

WAREHOUSES = [
    ("WH-N", "North Distribution Center"),
    ("WH-S", "South Distribution Center"),
    ("WH-W", "West Distribution Center"),
]

SKUS = [
    ("SKU0001", "Pour-Over Coffee Dripper", "Kitchen"),
    ("SKU0002", "Cast Iron Skillet 10in", "Kitchen"),
    ("SKU0003", "Linen Sheet Set Queen", "Bedding"),
    ("SKU0004", "Down Alternative Pillow", "Bedding"),
    ("SKU0005", "Stackable Storage Bins 3pk", "Storage"),
    ("SKU0006", "Canvas Closet Organizer", "Storage"),
    ("SKU0007", "Ceramic Table Lamp", "Decor"),
    ("SKU0008", "Handwoven Throw Blanket", "Decor"),
    ("SKU0009", "Stainless Steel Mixing Bowls", "Kitchen"),
    ("SKU0010", "Aromatherapy Diffuser", "Decor"),
    ("SKU0011", "Velvet Cushion Covers 2pk", "Decor"),
    ("SKU0012", "Bamboo Cutting Board Set", "Kitchen"),
]

SUPPLIERS = [
    ("SUP001", "Apex Craft Goods", "ACTIVE", 0.95, "Primary partner with consistent lead times."),
    ("SUP002", "Beacon Supply Co", "ACTIVE", 0.90, "Secondary regional supplier."),
    ("SUP003", "Crestview Logistics", "ACTIVE", 0.88, "Backup supplier."),
    ("SUP004", "Delta Home Goods", "ACTIVE", 0.85, "Alternative supplier."),
    ("SUP005", "Echo Manufacturing", "ACTIVE", 0.92, "Specialist manufacturer."),
]


def populate_base_data(conn: sqlite3.Connection, as_of: date, seed: int = 42) -> None:
    """Populate base reproducible tables."""
    rng = random.Random(seed)

    # 1. Meta
    conn.execute("INSERT INTO meta(key, value) VALUES ('as_of_date', ?)", (as_of.isoformat(),))

    # 2. Warehouses
    conn.executemany("INSERT INTO warehouses VALUES (?, ?)", WAREHOUSES)

    # 3. SKUs
    conn.executemany("INSERT INTO skus VALUES (?, ?, ?)", SKUS)

    # 4. Suppliers
    conn.executemany("INSERT INTO suppliers VALUES (?, ?, ?, ?, ?)", SUPPLIERS)

    # 5. SKU-Suppliers
    # For every SKU, SUP001 is primary, SUP002 and SUP003 are alternates
    for sku_id, _, _ in SKUS:
        base_cost = 15.0 + rng.uniform(5.0, 25.0)
        conn.execute(
            """INSERT INTO sku_suppliers VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sku_id, "SUP001", round(base_cost, 2), 50, 10, 7, 1.0, 1),
        )
        conn.execute(
            """INSERT INTO sku_suppliers VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sku_id, "SUP002", round(base_cost * 1.08, 2), 40, 10, 9, 1.5, 0),
        )
        conn.execute(
            """INSERT INTO sku_suppliers VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sku_id, "SUP003", round(base_cost * 1.15, 2), 60, 20, 10, 2.0, 0),
        )

    # 6. Sales daily (120 days up to as_of_date)
    start_date = as_of - timedelta(days=119)
    sales_rows = []
    for day_offset in range(120):
        current_date = (start_date + timedelta(days=day_offset)).isoformat()
        for sku_id, _, _ in SKUS:
            for wh_id, _ in WAREHOUSES:
                # Baseline demand around 12 units/day with some noise
                base_units = max(0, int(rng.gauss(12, 3)))
                sales_rows.append((current_date, sku_id, wh_id, base_units))

    conn.executemany("INSERT INTO sales_daily VALUES (?, ?, ?, ?)", sales_rows)

    # 7. Inventory
    # Default: on_hand around 80 (below target, near or below ROP for ordering), on_order = 0
    inventory_rows = []
    for sku_id, _, _ in SKUS:
        for wh_id, _ in WAREHOUSES:
            inventory_rows.append((sku_id, wh_id, 80, 0))
    conn.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?)", inventory_rows)

    # 8. Market Signals
    signals = [
        (1, "SKU0001", (as_of - timedelta(days=5)).isoformat(), "PROMO", "Featured in newsletter"),
        (
            2,
            "SKU0003",
            (as_of - timedelta(days=12)).isoformat(),
            "COMPETITOR",
            "Competitor price drop",
        ),
    ]
    conn.executemany("INSERT INTO market_signals VALUES (?, ?, ?, ?, ?)", signals)


def apply_scenario_patches(
    conn: sqlite3.Connection, scenario_file: Path, as_of: date, seed: int = 42
) -> None:
    """Read scenario JSON and apply patch operations."""
    with open(scenario_file, encoding="utf-8") as f:
        data = json.load(f)

    scenario_id = data["id"]
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('scenario_id', ?)", (scenario_id,)
    )

    for patch in data.get("patches", []):
        patch_type = patch.get("type")

        if "table" in patch:
            # Generic table update
            table = patch["table"]
            set_clauses = [f"{k} = ?" for k in patch["set"]]
            set_values = list(patch["set"].values())
            where_clauses = [f"{k} = ?" for k in patch["where"]]
            where_values = list(patch["where"].values())

            query = (
                f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"
            )
            conn.execute(query, set_values + where_values)

        elif patch_type == "demand_spike":
            sku_id = patch["sku_id"]
            wh_id = patch["warehouse_id"]
            multiplier = patch["multiplier"]
            days = patch["days"]
            since_date = (as_of - timedelta(days=days - 1)).isoformat()

            conn.execute(
                """
                UPDATE sales_daily
                SET units = CAST(ROUND(units * ?) AS INTEGER)
                WHERE sku_id = ? AND warehouse_id = ? AND sale_date >= ?
                """,
                (multiplier, sku_id, wh_id, since_date),
            )

        elif patch_type == "conflict_trend":
            sku_id = patch["sku_id"]
            wh_id = patch["warehouse_id"]
            # Force a strong downward trend in the last 14 days and high in the prior 42 days
            # causing line fit (method b) to project near 0 while method a (28-day mean) remains high (>30% difference)
            for d in range(14):
                dt = (as_of - timedelta(days=d)).isoformat()
                val = max(1, 14 - d)  # drops from 14 down to 1
                conn.execute(
                    "UPDATE sales_daily SET units = ? WHERE sku_id = ? AND warehouse_id = ? AND sale_date = ?",
                    (val, sku_id, wh_id, dt),
                )
            for d in range(14, 56):
                dt = (as_of - timedelta(days=d)).isoformat()
                conn.execute(
                    "UPDATE sales_daily SET units = 25 WHERE sku_id = ? AND warehouse_id = ? AND sale_date = ?",
                    (sku_id, wh_id, dt),
                )

        elif patch_type == "remove_sales_rows":
            sku_id = patch["sku_id"]
            wh_id = patch["warehouse_id"]
            fraction = patch["fraction"]
            cutoff_date = (as_of - timedelta(days=55)).isoformat()

            # Deterministically select rows to delete
            rows = conn.execute(
                """
                SELECT sale_date FROM sales_daily
                WHERE sku_id = ? AND warehouse_id = ? AND sale_date >= ?
                ORDER BY sale_date ASC
                """,
                (sku_id, wh_id, cutoff_date),
            ).fetchall()

            rng = random.Random(seed + 101)
            num_to_delete = int(len(rows) * fraction)
            delete_dates = rng.sample([r[0] for r in rows], num_to_delete)

            conn.executemany(
                "DELETE FROM sales_daily WHERE sku_id = ? AND warehouse_id = ? AND sale_date = ?",
                [(sku_id, wh_id, dt) for dt in delete_dates],
            )


def build_database(out_path: Path, scenario_id: str = "S01", seed: int = 42) -> None:
    """Build and initialize SQLite database for the specified scenario."""
    as_of = date(2026, 10, 19)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(SCHEMA_SQL)
        populate_base_data(conn, as_of=as_of, seed=seed)

        scenario_path = Path(f"data/scenarios/{scenario_id}.json")
        if scenario_path.exists():
            apply_scenario_patches(conn, scenario_path, as_of=as_of, seed=seed)

        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build synthetic supply chain database.")
    parser.add_argument("--scenario", default="S01", help="Scenario ID (e.g. S01..S10)")
    parser.add_argument("--out", default="data/supply.db", help="Output database file path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for generation")
    args = parser.parse_args()

    build_database(Path(args.out), scenario_id=args.scenario, seed=args.seed)
    print(f"Database successfully built at {args.out} for scenario {args.scenario}")


if __name__ == "__main__":
    main()
