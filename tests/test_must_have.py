from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.config import DEFAULT
from src.forecast import forecast
from src.loader import load_supplier
from src.loader import latest_sale_date
from src.outliers import clean
from src.pipeline import calculate
from src.replenish import replenish
from src.stockout import restore


@pytest.fixture
def sample():
    months = pd.date_range("2024-01-01", "2026-09-01", freq="MS")
    items = pd.DataFrame({"code": ["A_"], "name": ["Тестовый товар"], "article": ["T-1"], "transit": [0.], "manager_category": [""], "manager_order": [0.], "free_stock": [np.nan], "moq": [1.], "supplier": ["IEK"]})
    sales = pd.DataFrame({"code": "A_", "month": months, "qty": 20.})
    stocks = pd.DataFrame({"code": "A_", "month": months, "stock": 10.})
    tx = pd.DataFrame({"date": pd.date_range("2025-10-01", periods=12, freq="MS"), "invoice": [str(i) for i in range(12)], "code": "A_", "qty": 20.})
    season = pd.DataFrame({"month_num": range(1, 13), "index": [1.] * 12})
    return {"items": items, "sales": sales, "stocks": stocks, "tx": tx, "season": season, "lead_days": 30}


def amount(data):
    return float(calculate(data)["orders"].iloc[0].recommended)


def test_all_sources_affect_order(sample):
    base = amount(sample)
    high_stock = deepcopy(sample)
    high_stock["stocks"].loc[high_stock["stocks"].month == "2026-09-01", "stock"] = 100
    assert amount(high_stock) < base
    transit = deepcopy(sample)
    transit["items"].loc[0, "transit"] = 25
    assert amount(transit) < base
    stronger_sales = deepcopy(sample)
    stronger_sales["sales"].loc[stronger_sales["sales"].month >= "2026-03-01", "qty"] = 40
    assert amount(stronger_sales) > base
    # Explicitly vary growth while all other replenish inputs stay fixed.
    demand = restore(*clean(sample["sales"], sample["tx"])[:1], sample["stocks"], sample["season"])
    pred = forecast(demand, sample["season"])
    faster = pred.copy()
    faster["forecast"] *= 1.5
    faster["growth"] = 1.5
    assert replenish(sample["items"], demand, faster, 30).iloc[0].recommended > replenish(sample["items"], demand, pred, 30).iloc[0].recommended
    # Changing the ABC distribution changes the service factor and safety stock.
    months = pd.date_range("2025-09-01", periods=12, freq="MS")
    synthetic = pd.concat([pd.DataFrame({"code": sku, "month": months, "restored_qty": [vol - 8, vol + 8] * 6, "excluded": 0., "spike_count": 0, "restored_amount": 0., "stock": 0.}) for sku, vol in [("X", 80), ("Y", 20), ("Z", 5)]])
    synthetic["raw_qty"] = synthetic.restored_qty
    items = pd.DataFrame({"code": ["X", "Y", "Z"], "name": ["X", "Y", "Z"], "article": ["X", "Y", "Z"], "free_stock": [np.nan] * 3, "transit": [0.] * 3, "moq": [1.] * 3, "supplier": ["IEK"] * 3})
    future = pd.concat([pd.DataFrame({"code": sku, "month": pd.date_range("2026-09-01", periods=6, freq="MS"), "forecast": 20., "growth": 1., "season_index": 1., "season_source": "бренд"}) for sku in ("X", "Y", "Z")])
    first = replenish(items, synthetic, future, 30).set_index("code").loc["Y"]
    synthetic.loc[synthetic.code == "X", "restored_qty"] *= 2
    second = replenish(items, synthetic, future, 30).set_index("code").loc["Y"]
    assert first.category != second.category
    assert first.recommended != second.recommended


def test_seasonality(sample):
    sample["sales"].loc[sample["sales"].month.dt.month == 7, "qty"] = 200
    clean_sales, _ = clean(sample["sales"], sample["tx"])
    demand = restore(clean_sales, sample["stocks"], sample["season"])
    result = forecast(demand, sample["season"], horizon=12)
    july = result[result.month.dt.month == 7].forecast.iloc[0]
    january = result[result.month.dt.month == 1].forecast.iloc[0]
    assert july > january * 2
    assert july > sample["sales"].qty.mean() * 1.2


def test_stockout_compensation(sample):
    affected = (sample["sales"].month >= "2026-03-01") & (sample["sales"].month < "2026-09-01")
    sample["sales"].loc[affected, "qty"] = 1
    sample["stocks"].loc[affected, "stock"] = 0
    cleaned, _ = clean(sample["sales"], sample["tx"])
    restored = restore(cleaned, sample["stocks"], sample["season"])
    raw = restored.copy()
    raw["restored_qty"] = raw.clean_qty
    compensated = replenish(sample["items"], restored, forecast(restored, sample["season"]), 30).iloc[0].recommended
    uncorrected = replenish(sample["items"], raw, forecast(raw, sample["season"]), 30).iloc[0].recommended
    assert restored.restored_amount.sum() > 0
    assert compensated > uncorrected


def test_stockout_uses_recent_level(sample):
    sample["sales"].loc[sample["sales"].month < "2025-09-01", "qty"] = 1000
    shortage = sample["sales"].month == "2026-04-01"
    sample["sales"].loc[shortage, "qty"] = 0
    sample["stocks"].loc[shortage, "stock"] = 0
    demand = restore(*clean(sample["sales"], sample["tx"])[:1], sample["stocks"], sample["season"])
    april = demand.loc[shortage].iloc[0]
    assert april.stockout
    assert 0 < april.restored_qty <= 20
    assert april.available_months >= 3
    scarce = deepcopy(sample)
    recent = (scarce["stocks"].month >= "2025-09-01") & (scarce["stocks"].month < "2026-09-01")
    scarce["stocks"].loc[recent, "stock"] = 0
    scarce["stocks"].loc[scarce["stocks"].month.isin(pd.to_datetime(["2026-02-01", "2026-03-01"])), "stock"] = 10
    scarce_demand = restore(*clean(scarce["sales"], scarce["tx"])[:1], scarce["stocks"], scarce["season"])
    assert not scarce_demand.loc[scarce_demand.month == "2026-04-01", "stockout"].iloc[0]


def test_single_spike_not_seasonality(sample):
    # No invoice line exists for 2024, so the monthly Hampel step must protect
    # both the forecast level and the article seasonality.
    sample["sales"].loc[sample["sales"].month == "2024-09-01", "qty"] = 1000
    demand = restore(*clean(sample["sales"], sample["tx"])[:1], sample["stocks"], sample["season"])
    predicted = forecast(demand, sample["season"])
    september = predicted.loc[predicted.month == "2026-09-01"].iloc[0]
    assert september.season_index <= 2
    assert september.forecast < 60


def test_safety_stock_capped(sample):
    sample["sales"].loc[sample["sales"].month.dt.month.isin([1, 4, 7]), "qty"] = 200
    result = calculate(sample)["orders"].iloc[0]
    assert result.safety_stock <= result.forecast_month + 1e-9
    assert result.safety_stock <= result.horizon_demand + 1e-9


def test_manual_date_no_future_leak(sample):
    sample["source_as_of"] = date(2026, 9, 22)
    config = replace(DEFAULT, as_of=date(2026, 4, 1))
    baseline = calculate(sample, config)
    altered = deepcopy(sample)
    altered["sales"].loc[altered["sales"].month >= "2026-04-01", "qty"] = 100000
    altered["stocks"].loc[altered["stocks"].month > "2026-04-01", "stock"] = 100000
    altered["items"].loc[0, ["free_stock", "transit"]] = [100000, 100000]
    altered["tx"] = pd.concat([altered["tx"], pd.DataFrame({
        "date": [pd.Timestamp("2026-07-10")], "invoice": ["future"], "code": ["A_"], "qty": [100000.],
    })], ignore_index=True)
    compared = calculate(altered, config)
    pd.testing.assert_frame_equal(baseline["predictions"], compared["predictions"])
    assert baseline["orders"].iloc[0].recommended == compared["orders"].iloc[0].recommended
    assert compared["demand"].month.max() == pd.Timestamp("2026-04-01")


def test_one_off_excluded(sample):
    baseline = amount(sample)
    changed = deepcopy(sample)
    changed["sales"].loc[changed["sales"].month == "2026-08-01", "qty"] += 10000
    changed["tx"] = pd.concat([changed["tx"], pd.DataFrame({"date": [pd.Timestamp("2026-08-12")], "invoice": ["huge"], "code": ["A_"], "qty": [10000.]})], ignore_index=True)
    result = calculate(changed)
    assert len(result["spikes"]) > 0
    assert abs(result["orders"].iloc[0].recommended - baseline) / baseline <= .1


def test_growth_symmetric(sample):
    changed = deepcopy(sample)
    changed["sales"].loc[changed["sales"].month == "2025-04-01", "qty"] += 10000
    changed["tx"] = pd.concat([changed["tx"], pd.DataFrame({"date": [pd.Timestamp("2025-04-12")], "invoice": ["last-year-spike"], "code": ["A_"], "qty": [10000.]})], ignore_index=True)
    result = calculate(changed)
    assert ((result["spikes"].date == pd.Timestamp("2025-04-12")).any())
    assert result["orders"].iloc[0].growth == pytest.approx(1, abs=.05)


def test_no_order_without_demand(sample):
    quiet = (sample["sales"].month >= "2026-03-01") & (sample["sales"].month < "2026-09-01")
    sample["sales"].loc[quiet, "qty"] = 0
    result = calculate(sample)["orders"].iloc[0]
    assert result.recommended == 0
    assert "Нет устойчивого спроса" in result.explanation


def test_recurring_wholesale_kept(sample):
    months = ["2026-01-01", "2026-02-01", "2026-03-01"]
    sample["sales"].loc[sample["sales"].month.isin(pd.to_datetime(months)), "qty"] += 1000
    extra = pd.DataFrame({"date": pd.to_datetime(months), "invoice": ["bulk1", "bulk2", "bulk3"], "code": "A_", "qty": 1000.})
    sample["tx"] = pd.concat([sample["tx"], extra], ignore_index=True)
    cleaned, spikes = clean(sample["sales"], sample["tx"])
    assert not spikes.qty.eq(1000).any()
    assert cleaned.loc[cleaned.month.isin(pd.to_datetime(months)), "clean_qty"].eq(1020).all()


def test_current_month_spike_is_explained_without_changing_stock(sample):
    baseline = calculate(sample)["orders"].iloc[0]
    changed = deepcopy(sample)
    changed["sales"].loc[changed["sales"].month == "2026-09-01", "qty"] += 7488
    changed["tx"] = pd.concat([changed["tx"], pd.DataFrame({"date": [pd.Timestamp("2026-09-02")], "invoice": ["once"], "code": ["A_"], "qty": [7488.]})], ignore_index=True)
    result = calculate(changed)
    item = result["orders"].iloc[0]
    assert item.current_spike_qty == 7488
    assert item.current_spike_count == 1
    assert item.stock == baseline.stock
    assert item.recommended == baseline.recommended
    assert "В текущем месяце обнаружена разовая отгрузка 7 488 шт." in item.explanation
    assert item.explanation.startswith(item.short_reason)
    assert len(result["spikes"].query("code == 'A_' and qty == 7488")) == 1


def test_calculation_date_comes_from_latest_invoice(sample):
    assert latest_sale_date(sample["tx"]) == pd.Timestamp("2026-09-01").date()
    later = pd.concat([sample["tx"], pd.DataFrame({"date": [pd.Timestamp("2026-10-03 14:00")], "invoice": ["late"], "code": ["A_"], "qty": [1.]})], ignore_index=True)
    assert latest_sale_date(later) == pd.Timestamp("2026-10-03").date()


def test_output_explained_by_supplier(sample):
    other = deepcopy(sample)
    other["items"]["supplier"] = "Systeme Electric"
    other["items"]["code"] = "B_"
    for key in ("sales", "stocks", "tx"):
        other[key]["code"] = "B_"
    combined = pd.concat([calculate(sample)["orders"], calculate(other)["orders"]])
    assert set(combined.supplier) == {"IEK", "Systeme Electric"}
    assert combined.explanation.str.len().min() > 20
    assert all(combined.groupby("supplier").size() > 0)


@pytest.mark.skipif(not (Path(__file__).parents[1] / "data/raw/IEK/sales_monthly.xlsx").exists(), reason="Нет реальных выгрузок")
def test_real_iek_loads():
    data = load_supplier("IEK")
    assert len(data["items"]) > 100
    assert "010500008_" in set(data["items"].code)
