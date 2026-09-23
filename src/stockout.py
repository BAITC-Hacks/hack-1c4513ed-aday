"""Estimate censored demand in months with no opening stock."""
import numpy as np
import pandas as pd


def restore(cleaned, stocks, season):
    data = cleaned.merge(stocks[["code", "month", "stock"]], on=["code", "month"], how="left")
    data = data.merge(season.rename(columns={"index": "brand_index"}), left_on=data.month.dt.month, right_on="month_num", how="left").drop(columns="month_num")
    data["brand_index"] = data.brand_index.fillna(1)
    data = data.sort_values(["code", "month"])
    data["next_stock"] = data.groupby("code").stock.shift(-1)
    available = data[data.stock > 0].copy()
    available["level"] = available.clean_qty / available.brand_index.clip(lower=0.2)
    typical = available.groupby("code")["level"].median().rename("typical")
    data = data.join(typical, on="code")
    data["typical"] = data.typical.fillna(0)
    low_sales = data.clean_qty < data.typical * data.brand_index * 0.5
    data["stockout"] = (data.stock <= 0) & ((data.next_stock <= 0) | low_sales) & (data.typical > 0)
    expected = data.typical * data.brand_index
    data["restored_qty"] = np.where(data.stockout, np.maximum(data.clean_qty, expected), data.clean_qty)
    data["restored_amount"] = data.restored_qty - data.clean_qty
    return data
