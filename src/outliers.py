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
    # The same invoice rule must cover both sides of the year-on-year comparison.
    recent = tx[(tx.date >= "2025-01-01") & (tx.date < pd.Timestamp(config.as_of) + pd.Timedelta(days=1)) & (tx.qty > 0)].copy()
    if len(recent):
        stats = recent.groupby("code").qty.agg(median="median", count="count")
        recent = recent.join(stats, on="code")
        recent["deviation"] = (recent.qty - recent["median"]).abs()
        mad = recent.groupby("code").deviation.median().rename("mad")
        recent = recent.join(mad, on="code")
        recent["threshold"] = np.maximum(recent["median"] + config.outlier_k * 1.4826 * recent.mad, config.outlier_m * recent["median"])
        recent["month"] = recent.date.dt.to_period("M").dt.to_timestamp()
        candidates = recent[(recent.qty > recent.threshold) & (recent.qty > config.min_outlier_qty) & (recent["count"] >= 4)].copy()
        months = pd.date_range("2025-01-01", pd.Timestamp(config.as_of).replace(day=1), freq="MS")
        maxima = recent.groupby(["code", "month"]).qty.max()
        rare_indices = []
        for sku, group in candidates.groupby("code"):
            monthly_max = maxima.loc[sku].reindex(months, fill_value=0).to_numpy(dtype=float)
            comparable = monthly_max[None, :] >= group.qty.to_numpy()[:, None] / 2
            width = min(12, len(months))
            counts = np.lib.stride_tricks.sliding_window_view(comparable, width, axis=1).sum(axis=2)
            starts = np.arange(counts.shape[1])
            positions = months.get_indexer(group.month)
            valid = (starts[None, :] <= positions[:, None]) & (starts[None, :] + width > positions[:, None])
            regular = np.where(valid, counts, 0).max(axis=1) >= 3
            rare_indices.extend(group.index[~regular].tolist())
        spikes = candidates.loc[rare_indices, ["code", "month", "date", "qty", "threshold"]].copy()
        # A truly exceptional shipment is removed in full. Monthly ordinary
        # demand remains untouched; no second month-level median cap is used.
        spikes["excess"] = spikes.qty
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
