from src.config import DEFAULT
from src.loader import load_supplier
from src.outliers import clean
from src.stockout import restore
from src.forecast import forecast
from src.replenish import replenish
import pandas as pd


def prepare(data, config=DEFAULT):
    """Heavy stage: independent of review period and service factors."""
    cleaned, spikes = clean(data["sales"], data["tx"], config)
    demand = restore(cleaned, data["stocks"], data["season"], config)
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
