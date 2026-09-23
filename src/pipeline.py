from src.config import DEFAULT
from src.loader import load_supplier
from src.outliers import clean
from src.stockout import restore
from src.forecast import forecast
from src.replenish import replenish
from src.stable import stabilize
import pandas as pd
import numpy as np


def snapshot(data, config=DEFAULT):
    """Expose only observations available by the calculation date."""
    month = pd.Timestamp(config.as_of).replace(day=1)
    deadline = pd.Timestamp(config.as_of) + pd.Timedelta(days=1)
    result = dict(data)
    result["tx"] = data["tx"].loc[data["tx"].date < deadline].copy()
    result["sales"] = data["sales"].loc[data["sales"].month <= month].copy()
    result["stocks"] = data["stocks"].loc[data["stocks"].month <= month].copy()
    # Monthly exports contain the whole current month. Rebuild its partial
    # quantity from invoices actually dated on or before as_of.
    current = result["tx"].loc[result["tx"].date >= month].groupby("code").qty.sum().clip(lower=0)
    mask = result["sales"].month == month
    result["sales"].loc[mask, "qty"] = result["sales"].loc[mask, "code"].map(current).fillna(0).to_numpy()
    if "season_history" in data:
        past = data["season_history"].loc[data["season_history"].year < config.as_of.year]
        if len(past):
            values = past.groupby("month_num").amount.mean().reindex(range(1, 13), fill_value=0)
            mean = values.mean()
            indexes = values / mean if mean > 0 else np.ones(12)
        else:
            indexes = np.ones(12)
        result["season"] = pd.DataFrame({"month_num": range(1, 13), "index": np.asarray(indexes)})
    if "source_as_of" in data and config.as_of < data["source_as_of"]:
        # The current procurement sheet has no historical snapshots.
        items = data["items"].copy()
        items["transit"] = 0.0
        items["free_stock"] = np.nan
        for field in ("manager_avg12", "manager_cover", "manager_order"):
            if field in items:
                items[field] = np.nan
        if "manager_order_filled" in items:
            items["manager_order_filled"] = False
        if "manager_category" in items:
            items["manager_category"] = ""
        result["items"] = items
        result["lead_days"] = config.default_lead_days
    return result


def prepare(data, config=DEFAULT):
    """Heavy stage: independent of review period and service factors."""
    data = snapshot(data, config)
    cleaned, spikes = clean(data["sales"], data["tx"], config)
    demand = stabilize(restore(cleaned, data["stocks"], data["season"], config), config)
    predictions = forecast(demand, data["season"], config)
    return {"items": data["items"], "lead_days": data["lead_days"], "demand": demand, "predictions": predictions, "spikes": spikes}


def finish(prepared, config=DEFAULT):
    """Light stage: only ABC, safety stock, urgency and order quantities."""
    orders = replenish(prepared["items"], prepared["demand"], prepared["predictions"], prepared["lead_days"], config)
    return {**prepared, "orders": orders}


def calculate(data, config=DEFAULT):
    return finish(prepare(data, config), config)


def calculate_all(suppliers=("IEK", "SystemeElectric"), config=DEFAULT):
    results = {name: calculate(load_supplier(name), config) for name in suppliers}
    return results, pd.concat([r["orders"] for r in results.values()], ignore_index=True)
