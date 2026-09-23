"""Reproducible real-data order, growth and exclusion audit."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.loader import load_supplier
from src.pipeline import calculate


def audit():
    report = {}
    for supplier in ("IEK", "SystemeElectric"):
        start = time.perf_counter()
        result = calculate(load_supplier(supplier))
        elapsed = time.perf_counter() - start
        orders = result["orders"]
        active = orders[orders.recommended > 0]
        demand = result["demand"]
        monthly = demand[(demand.month >= pd.Timestamp("2025-01-01")) & (demand.month < pd.Timestamp("2026-09-01"))].groupby("month").agg(raw=("raw_qty", "sum"), excluded=("excluded", "sum"))
        monthly["share"] = monthly.excluded / monthly.raw.replace(0, float("nan"))
        cover = (active.stock + active.transit + active.recommended) / (active.forecast_month / 30).replace(0, float("nan")) / 30
        report[supplier] = {
            "positions": len(active), "critical": int((active.urgency == "Критично").sum()),
            "growth_floor_share": float((orders.growth == .7).mean()),
            "growth_median": float(orders.growth.median()),
            "excluded_share": float(monthly.excluded.sum() / monthly.raw.sum()),
            "excluded_monthly": {str(m.date()): round(float(v), 4) for m, v in monthly.share.items()},
            "cover_months_median": float(cover.median()), "elapsed_seconds": round(elapsed, 2),
        }
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
