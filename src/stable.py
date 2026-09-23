"""A robust monthly demand series for forecasting and safety stock."""
import numpy as np
import pandas as pd
from src.config import DEFAULT


def stabilize(demand, config=DEFAULT):
    """Cap exceptional complete months while retaining the original series."""
    result = demand.copy()
    result["stable_qty"] = result.restored_qty.astype(float)
    result["smoothed_amount"] = 0.0
    last_month = pd.Timestamp(config.as_of).replace(day=1)
    window = result[(result.month >= last_month - pd.DateOffset(months=24)) &
                    (result.month < last_month) & (result.restored_qty > 0)].copy()
    if window.empty:
        return result
    stats = window.groupby("code").restored_qty.agg(median="median", count="count")
    window = window.join(stats, on="code")
    window["deviation"] = (window.restored_qty - window["median"]).abs()
    mad = window.groupby("code").deviation.median().rename("mad")
    window = window.join(mad, on="code")
    window["limit"] = window["median"] + 3 * 1.4826 * window.mad
    # A handful of positive months does not define a reliable Hampel level.
    candidates = window[(window["count"] >= 4) & (window.restored_qty > window.limit)].copy()
    if candidates.empty:
        return result
    # A sustained new level and a peak repeated in the same season are regular
    # demand, even when the global MAD is zero.
    high_months = candidates.groupby("code").month.nunique().rename("high_months")
    observed = result[result.month < last_month][["code", "month", "restored_qty"]].copy()
    observed["month_num"] = observed.month.dt.month
    observed = observed.sort_values("restored_qty", ascending=False)
    observed["rank"] = observed.groupby(["code", "month_num"]).cumcount()
    second = observed[observed["rank"] == 1].set_index(["code", "month_num"]).restored_qty.rename("second_season")
    candidates["month_num"] = candidates.month.dt.month
    candidates = candidates.join(high_months, on="code").join(second, on=["code", "month_num"])
    affected = candidates[(candidates.high_months < 3) &
                          (candidates.restored_qty > 2 * candidates.second_season.fillna(0))]
    result.loc[affected.index, "stable_qty"] = affected.limit.to_numpy()
    result.loc[affected.index, "smoothed_amount"] = (affected.restored_qty - affected.limit).to_numpy()
    return result
