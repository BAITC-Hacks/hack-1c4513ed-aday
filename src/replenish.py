"""ABC, safety stock, MOQ, urgency and order calculation."""
from datetime import timedelta
import numpy as np
import pandas as pd
from src.config import DEFAULT
from src.explain import explain_item


def replenish(items, demand, predictions, lead_days, config=DEFAULT):
    last_month = pd.Timestamp(config.as_of).replace(day=1)
    hist = demand[(demand.month >= last_month - pd.DateOffset(months=12)) & (demand.month < last_month)]
    totals = hist.groupby("code").agg(volume=("restored_qty", "sum"), excluded=("excluded", "sum"), spike_count=("spike_count", "sum"), restored_amount=("restored_amount", "sum"), sigma=("restored_qty", "std"))
    totals["sigma"] = totals.sigma.fillna(0)
    out = items.merge(totals, on="code", how="left")
    for c in ("volume", "excluded", "spike_count", "restored_amount", "sigma"):
        out[c] = out[c].fillna(0)
    recent_start = last_month - pd.DateOffset(months=6)
    recent = demand[(demand.month >= recent_start) & (demand.month < last_month)].groupby("code").agg(
        recent_sales=("raw_qty", "sum"), active_months=("raw_qty", lambda values: int((values > 0).sum()))
    )
    out = out.join(recent, on="code")
    out[["recent_sales", "active_months"]] = out[["recent_sales", "active_months"]].fillna(0)
    latest = demand[demand.month == last_month][["code", "stock"]].drop_duplicates("code")
    out = out.merge(latest, on="code", how="left")
    out["stock"] = out.free_stock.combine_first(out.stock).fillna(0)
    out = out.sort_values("volume", ascending=False)
    total = out.volume.sum()
    before = (out.volume.cumsum() - out.volume) / total if total else 0
    out["category"] = np.where(before < .8, "A", np.where(before < .95, "B", "C"))
    out["z"] = out.category.map(config.service_z)
    pred = predictions[predictions.month == last_month][["code", "forecast", "growth", "season_index", "season_source"]]
    out = out.merge(pred, on="code", how="left")
    out = out.rename(columns={"forecast": "forecast_month"})
    for c, val in (("forecast_month", 0), ("growth", 1), ("season_index", 1)):
        out[c] = out[c].fillna(val)
    out["lead_days"] = lead_days
    out["review_days"] = config.review_days
    out["safety_stock"] = out.z * out.sigma * np.sqrt((lead_days + config.review_days) / 30)
    future = predictions.set_index(["code", "month"]).forecast.to_dict()
    start = pd.Timestamp(config.as_of)
    needs = []
    for row in out.itertuples():
        end = start + timedelta(days=int(lead_days + config.review_days))
        day = start
        need = 0.0
        while day < end:
            next_month = day.replace(day=1) + pd.DateOffset(months=1)
            stop = min(next_month, end)
            value = future.get((row.code, day.replace(day=1)), row.forecast_month)
            need += value * (stop - day).days / day.days_in_month
            day = stop
        needs.append(need)
    out["horizon_demand"] = needs
    intermittent = out.active_months < 4
    out.loc[intermittent, "safety_stock"] = np.minimum(out.loc[intermittent, "safety_stock"], out.loc[intermittent, "horizon_demand"])
    out["no_stable_demand"] = (out.recent_sales <= 0) | (out.forecast_month < 0.5)
    out.loc[out.no_stable_demand, "safety_stock"] = 0
    out["need"] = out.horizon_demand + out.safety_stock
    out["recommended"] = np.ceil((out.need - out.stock - out.transit).clip(lower=0) / out.moq.clip(lower=1)) * out.moq.clip(lower=1)
    out.loc[out.no_stable_demand, "recommended"] = 0
    out["days_cover"] = (out.stock + out.transit) / (out.forecast_month / 30).replace(0, np.nan)
    out["urgency"] = np.where(out.days_cover < lead_days, "Критично", np.where(out.days_cover < lead_days + 14, "Высокая", "Плановая"))
    out["explanation"] = out.apply(explain_item, axis=1)
    return out.reset_index(drop=True)
