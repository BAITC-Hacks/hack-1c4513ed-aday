"""Run the historical forecast comparison and save reproducible CSV files."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from src.backtest import run_backtest
from src.loader import load_supplier


def main():
    reports = [run_backtest(load_supplier(name), name) for name in ("IEK", "SystemeElectric")]
    metrics = pd.concat([part[0] for part in reports], ignore_index=True)
    details = pd.concat([part[1] for part in reports], ignore_index=True)
    target = Path(__file__).resolve().parents[1] / "output"
    target.mkdir(exist_ok=True)
    metrics.to_csv(target / "backtest_metrics.csv", index=False, encoding="utf-8-sig", sep=";")
    details.to_csv(target / "backtest_details.csv", index=False, encoding="utf-8-sig", sep=";")
    print(metrics.round({"wape": 1, "bias": 1}).to_string(index=False))
    print(f"\nСохранено: {target / 'backtest_metrics.csv'}, {target / 'backtest_details.csv'}")


if __name__ == "__main__":
    main()
