"""Transparent reliability labels for purchasing recommendations."""
import numpy as np
import pandas as pd
from src.config import DEFAULT


def add_confidence(orders, demand, config=DEFAULT):
    out = orders.copy()
    month = pd.Timestamp(config.as_of).replace(day=1)
    past = demand[demand.month < month]
    positive = past[past.raw_qty > 0].groupby("code").month.min()
    out["history_months"] = out.code.map(positive).map(
        lambda first: max(0, (month.year - first.year) * 12 + month.month - first.month) if pd.notna(first) else 0
    )
    recent = past[past.month >= month - pd.DateOffset(months=12)].copy()
    recent["active"] = recent.raw_qty > 0
    stats = recent.groupby("code").agg(
        active_months_12=("active", "sum"), mean_stable=("stable_qty", "mean"),
        std_stable=("stable_qty", "std"), restored=("restored_amount", "sum"),
        restored_total=("restored_qty", "sum"), excluded_total=("excluded", "sum"),
        raw_total=("raw_qty", "sum"),
    )
    out = out.join(stats, on="code")
    out["active_share"] = out.active_months_12.fillna(0) / 12
    out["variability"] = (out.std_stable.fillna(0) / out.mean_stable.replace(0, np.nan)).fillna(0)
    out["restored_share"] = (out.restored.fillna(0) / out.restored_total.replace(0, np.nan)).fillna(0)
    out["excluded_share"] = (out.excluded_total.fillna(0) / out.raw_total.replace(0, np.nan)).fillna(0)
    factors = {
        "мало истории": out.history_months < 18,
        "спрос прерывистый": out.active_share < .75,
        "спрос сильно меняется": out.variability > .8,
        "рост на границе диапазона": (out.growth <= .7001) | (out.growth >= 1.499),
        "много восстановленного спроса": out.restored_share > .1,
        "существенные разовые отгрузки": (out.excluded_share > .1) |
            (out.current_spike_qty.fillna(0) > .25 * out.forecast_month.clip(lower=1)),
    }
    score = sum(flag.astype(int) for flag in factors.values())
    severe = ((out.history_months < 6) | (out.active_share < 1/3) |
              (out.variability > 1.5) | (out.restored_share > .35) |
              (out.excluded_share > .35))
    out["confidence"] = np.where(severe | (score >= 3), "Низкая", np.where(score >= 1, "Средняя", "Высокая"))
    out["confidence_reason"] = ""
    for reason, flag in factors.items():
        mask = (out.confidence == "Низкая") & flag & out.confidence_reason.eq("")
        out.loc[mask, "confidence_reason"] = reason
    return out.drop(columns=list(stats.columns))
