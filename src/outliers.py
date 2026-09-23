"""Remove exceptional invoice lines and Hampel spikes in months without invoices."""
import numpy as np
import pandas as pd
from src.config import DEFAULT


def clean(sales, tx, config=DEFAULT):
    result = sales.copy()
    result["raw_qty"] = result.qty.clip(lower=0)
    result["clean_qty"] = result.raw_qty.astype(float)
    result["excluded"] = 0.0
    result["spike_count"] = 0
    start = pd.Timestamp(config.as_of) - pd.DateOffset(months=12)
    recent = tx[(tx.date >= start) & (tx.date <= pd.Timestamp(config.as_of)) & (tx.qty > 0)].copy()
    if len(recent):
        stats = recent.groupby("code").qty.agg(median="median", count="count")
        recent = recent.join(stats, on="code")
        mad = recent.groupby("code").apply(lambda g: (g.qty - g["median"]).abs().median(), include_groups=False).rename("mad")
        recent = recent.join(mad, on="code")
        recent["threshold"] = np.maximum(recent["median"] + config.outlier_k * 1.4826 * recent.mad, config.outlier_m * recent["median"])
        recent["excess"] = np.where((recent.qty > recent.threshold) & (recent.qty > config.min_outlier_qty) & (recent["count"] >= 4), recent.qty - recent.threshold, 0)
        recent["month"] = recent.date.dt.to_period("M").dt.to_timestamp()
        spikes = recent[recent.excess > 0][["code", "month", "date", "qty", "threshold", "excess"]].copy()
        adj = spikes.groupby(["code", "month"]).agg(excluded=("excess", "sum"), spike_count=("excess", "size")).reset_index()
        result = result.drop(columns=["excluded", "spike_count"]).merge(adj, on=["code", "month"], how="left")
        result[["excluded", "spike_count"]] = result[["excluded", "spike_count"]].fillna(0)
        result["clean_qty"] = (result.raw_qty - result.excluded).clip(lower=0)
    else:
        spikes = pd.DataFrame(columns=["code", "month", "date", "qty", "threshold", "excess"])
    # 2024 has no reliable invoice lines; apply a one-sided Hampel filter per SKU.
    old = result.month.dt.year == 2024
    for _, group in result[old].groupby("code"):
        vals = group.clean_qty.to_numpy(dtype=float)
        positive = vals[vals > 0]
        if len(positive) < 4:
            continue
        med = np.median(positive)
        mad = np.median(np.abs(positive - med))
        threshold = max(med + config.outlier_k * 1.4826 * mad, config.outlier_m * med)
        mask = (vals > threshold) & (vals > config.min_outlier_qty)
        if mask.any():
            idx = group.index[mask]
            result.loc[idx, "excluded"] = vals[mask] - threshold
            result.loc[idx, "clean_qty"] = threshold
            result.loc[idx, "spike_count"] = 1
            spikes = pd.concat([spikes, pd.DataFrame({"code": group.loc[idx, "code"], "month": group.loc[idx, "month"], "date": group.loc[idx, "month"], "qty": vals[mask], "threshold": threshold, "excess": vals[mask] - threshold})], ignore_index=True)
    return result, spikes
