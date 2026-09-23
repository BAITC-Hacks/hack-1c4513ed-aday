"""Leak-free forecast backtest against simple purchasing baselines."""
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from src.config import DEFAULT
from src.pipeline import prepare


ORIGINS = (date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1))
METHODS = {"forecast": "StockPilot", "average_12": "Среднее 12 мес.", "average_3": "Среднее 3 мес."}


def _metrics(details, origin):
    records = []
    for cohort, selected in (("Все активные", details), ("С корректировкой", details[details.had_correction])):
        for field, label in METHODS.items():
            actual = selected.actual.sum()
            error = selected[field] - selected.actual
            records.append({
                "supplier": selected.supplier.iloc[0] if len(selected) else details.supplier.iloc[0],
                "origin": origin, "cohort": cohort, "method": label,
                "wape": 100 * error.abs().sum() / actual if actual > 0 else np.nan,
                "bias": 100 * error.sum() / actual if actual > 0 else np.nan,
                "items": selected.code.nunique(), "observations": len(selected), "actual_total": actual,
            })
    return records


def run_backtest(data, supplier, origins=ORIGINS):
    """Return metrics and article-month rows; future rows are used only as truth."""
    details = []
    source_date = data.get("source_as_of")
    for origin in origins:
        if source_date is not None and origin > source_date:
            continue
        config = replace(DEFAULT, as_of=origin)
        trained = prepare(data, config)
        month = pd.Timestamp(origin).replace(day=1)
        past = trained["demand"].loc[trained["demand"].month < month]
        active = past.loc[past.month >= month - pd.DateOffset(months=12)].groupby("code").raw_qty.sum()
        active = active[active > 0].index
        if len(active) == 0:
            continue
        means12 = past.loc[past.month >= month - pd.DateOffset(months=12)].groupby("code").raw_qty.mean()
        means3 = past.loc[past.month >= month - pd.DateOffset(months=3)].groupby("code").raw_qty.mean()
        future = trained["predictions"].loc[
            (trained["predictions"].month >= month) &
            (trained["predictions"].month < month + pd.DateOffset(months=3)) &
            (trained["predictions"].code.isin(active)), ["code", "month", "forecast"],
        ]
        actual = data["sales"].loc[
            (data["sales"].month >= month) &
            (data["sales"].month < month + pd.DateOffset(months=3)), ["code", "month", "qty"],
        ].rename(columns={"qty": "actual"})
        actual["actual"] = actual.actual.clip(lower=0)
        rows = future.merge(actual, on=["code", "month"], how="inner")
        if rows.empty:
            continue
        corrected = set(trained["spikes"].loc[trained["spikes"].month < month, "code"])
        corrected.update(past.loc[past.restored_amount > 0, "code"])
        rows["average_12"] = rows.code.map(means12).fillna(0)
        rows["average_3"] = rows.code.map(means3).fillna(0)
        rows["had_correction"] = rows.code.isin(corrected)
        rows["supplier"] = "IEK" if supplier == "IEK" else "Systeme Electric"
        rows["origin"] = origin.isoformat()
        names = data["items"].set_index("code").name
        rows["name"] = rows.code.map(names).fillna("")
        details.append(rows)
    if not details:
        return pd.DataFrame(), pd.DataFrame()
    all_details = pd.concat(details, ignore_index=True)
    metrics = []
    for origin, group in all_details.groupby("origin", sort=True):
        metrics.extend(_metrics(group, origin))
    metrics.extend(_metrics(all_details, "Все даты"))
    return pd.DataFrame(metrics), all_details
