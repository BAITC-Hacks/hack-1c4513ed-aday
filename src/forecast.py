"""Vectorized seasonal six-month run rate and bounded year-on-year growth."""
import numpy as np
import pandas as pd
from src.config import DEFAULT


def forecast(demand, season, config=DEFAULT, horizon=6):
    complete = demand[demand.month < pd.Timestamp(config.as_of).replace(day=1)][["code", "month", "restored_qty"]].copy()
    if complete.empty:
        return pd.DataFrame(columns=["code", "month", "forecast", "base", "growth", "season_index", "season_source"])
    complete["month_num"] = complete.month.dt.month
    complete["positive"] = (complete.restored_qty > 0).astype(int)
    stats = complete.groupby("code").agg(n=("month", "size"), positive=("positive", "sum"), total=("restored_qty", "sum"), avg=("restored_qty", "mean"))
    stats["article_season"] = (stats.n >= 18) & (stats.positive >= 12) & (stats.total >= 60) & (stats.avg > 0)
    month_mean = complete.groupby(["code", "month_num"]).restored_qty.mean().rename("month_mean")
    levels = pd.MultiIndex.from_product([stats.index, range(1, 13)], names=["code", "month_num"]).to_frame(index=False)
    levels = levels.join(stats[["avg", "article_season"]], on="code").join(month_mean, on=["code", "month_num"])
    brand = season.set_index("month_num")["index"]
    levels["brand_index"] = levels.month_num.map(brand).fillna(1)
    article_index = (levels.month_mean / levels.avg.replace(0, np.nan)).clip(.3, 3).fillna(levels.brand_index)
    levels["season_index"] = np.where(levels.article_season, article_index, levels.brand_index)
    scale = levels.groupby("code").season_index.transform("mean")
    levels["season_index"] = levels.season_index / scale.replace(0, 1)
    levels["season_source"] = np.where(levels.article_season, "артикул", "бренд")
    complete = complete.merge(levels[["code", "month_num", "season_index"]], on=["code", "month_num"], how="left")
    complete["deseason"] = complete.restored_qty / complete.season_index.clip(lower=.2)
    tail = complete.sort_values(["code", "month"]).groupby("code", sort=False).tail(6).copy()
    tail["weight"] = tail.groupby("code").cumcount() + 1
    tail["weighted"] = tail.deseason * tail.weight
    base = tail.groupby("code").agg(weighted=("weighted", "sum"), weight=("weight", "sum"))
    base["base"] = base.weighted / base.weight
    current = tail.groupby("code").agg(current_sum=("restored_qty", "sum"), current_n=("month", "size"))
    previous = tail[["code", "month"]].copy()
    previous["month"] = previous.month - pd.DateOffset(years=1)
    previous = previous.merge(complete[["code", "month", "restored_qty"]], on=["code", "month"], how="left")
    earlier = previous.groupby("code").agg(earlier_sum=("restored_qty", "sum"), earlier_n=("restored_qty", "count"))
    metrics = base[["base"]].join(current).join(earlier)
    ratio = metrics.current_sum / metrics.earlier_sum.replace(0, np.nan)
    metrics["growth"] = np.where((metrics.current_n == 6) & (metrics.earlier_n == 6) & (metrics.earlier_sum > 0), ratio.clip(.7, 1.5), 1.0)
    future = pd.date_range(pd.Timestamp(config.as_of).replace(day=1), periods=horizon, freq="MS")
    result = pd.MultiIndex.from_product([stats.index, future], names=["code", "month"]).to_frame(index=False)
    result["month_num"] = result.month.dt.month
    result = result.merge(metrics[["base", "growth"]], on="code").merge(levels[["code", "month_num", "season_index", "season_source"]], on=["code", "month_num"])
    result["forecast"] = (result.base * result.growth * result.season_index).clip(lower=0)
    return result[["code", "month", "forecast", "base", "growth", "season_index", "season_source"]]
