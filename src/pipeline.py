from src.config import DEFAULT
from src.loader import load_supplier
from src.outliers import clean
from src.stockout import restore
from src.forecast import forecast
from src.replenish import replenish
import pandas as pd


def calculate(data, config=DEFAULT):
    cleaned, spikes = clean(data["sales"], data["tx"], config)
    demand = restore(cleaned, data["stocks"], data["season"])
    predictions = forecast(demand, data["season"], config)
    orders = replenish(data["items"], demand, predictions, data["lead_days"], config)
    return {"orders": orders, "demand": demand, "predictions": predictions, "spikes": spikes}


def calculate_all(suppliers=("IEK", "SystemeElectric"), config=DEFAULT):
    results = {name: calculate(load_supplier(name), config) for name in suppliers}
    return results, pd.concat([r["orders"] for r in results.values()], ignore_index=True)
