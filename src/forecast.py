"""Seasonal six-month run rate and bounded year-on-year growth."""
import numpy as np
import pandas as pd
from src.config import DEFAULT


def forecast(demand, season, config=DEFAULT, horizon=6):
    complete = demand[demand.month < pd.Timestamp(config.as_of).replace(day=1)].copy()
    brand = season.set_index("month_num")["index"].to_dict()
    future = pd.date_range(pd.Timestamp(config.as_of).replace(day=1), periods=horizon, freq="MS")
    rows = []
    for sku, g in complete.groupby("code"):
        g = g.sort_values("month").copy()
        levels = dict(brand)
        positive = (g.restored_qty > 0).sum()
        if len(g) >= 18 and positive >= 12 and g.restored_qty.sum() >= 60:
            by_month = g.groupby(g.month.dt.month).restored_qty.mean()
            avg = g.restored_qty.mean()
            if avg > 0:
                raw = (by_month / avg).clip(0.3, 3)
                levels = {m: float(raw.get(m, brand.get(m, 1))) for m in range(1, 13)}
                scale = np.mean(list(levels.values()))
                levels = {m: v / scale for m, v in levels.items()}
        g["deseason"] = g.restored_qty / g.month.dt.month.map(levels).clip(lower=0.2)
        tail = g.tail(6)
        weights = np.arange(1, len(tail) + 1, dtype=float)
        base = float(np.average(tail.deseason, weights=weights)) if len(tail) else 0
        earlier = g[g.month.isin(tail.month - pd.DateOffset(years=1))]
        growth = 1.0
        if len(tail) == 6 and len(earlier) == 6 and earlier.restored_qty.sum() > 0:
            growth = float(np.clip(tail.restored_qty.sum() / earlier.restored_qty.sum(), 0.7, 1.5))
        for month in future:
            idx = levels.get(month.month, 1)
            rows.append({"code": sku, "month": month, "forecast": max(0, base * growth * idx), "base": base, "growth": growth, "season_index": idx, "season_source": "артикул" if levels != brand else "бренд"})
    return pd.DataFrame(rows, columns=["code", "month", "forecast", "base", "growth", "season_index", "season_source"])
