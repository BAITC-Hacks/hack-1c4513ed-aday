"""Show why year-on-year demand ratios hit the lower clip."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.loader import load_supplier
from src.pipeline import calculate

for supplier in ("IEK", "SystemeElectric"):
    result = calculate(load_supplier(supplier))
    d = result["demand"]
    sums = []
    for year in (2025, 2026):
        span = d[(d.month.dt.year == year) & (d.month.dt.month.between(3, 8))]
        sums.append(span.groupby("code").agg(raw=("raw_qty", "sum"), clean=("clean_qty", "sum"), restored=("restored_qty", "sum"), excluded=("excluded", "sum")))
    joined = sums[0].join(sums[1], lsuffix="_25", rsuffix="_26").fillna(0)
    floor = result["orders"].set_index("code").growth.eq(.7)
    joined["floor"] = floor
    print(supplier, "floor", int(floor.sum()), "total", len(floor))
    for field in ("raw", "clean", "restored"):
        ratio = joined[f"{field}_26"] / joined[f"{field}_25"].replace(0, float("nan"))
        print(field, "ratio<.7", int((ratio < .7).sum()), "denom>0", int(ratio.notna().sum()), "median", round(ratio.median(), 3))
    print("floor sku with >0 recent clean", int(((joined.clean_26 > 0) & joined.floor).sum()))
