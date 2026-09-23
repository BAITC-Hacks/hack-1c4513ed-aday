"""Run both suppliers without Streamlit and print an audit summary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from src.pipeline import calculate_all


def main():
    results, orders = calculate_all()
    for key, result in results.items():
        order = result["orders"]
        active = order[order.recommended > 0]
        critical = active[active.urgency == "Критично"].sort_values("recommended", ascending=False).head(10)
        print(f"\n{key}: позиций к заказу {len(active)}, исключённых всплесков {len(result['spikes'])}, артикулов со stockout-коррекцией {result['demand'].loc[result['demand'].restored_amount > 0, 'code'].nunique()}")
        for row in critical.itertuples():
            print(f"  {row.code} {row.name}: {row.explanation}")
    target = results["IEK"]["spikes"]
    target = target[target.code == "010500008_"]
    print(f"\n010500008_: исключённых всплесков {len(target)}, максимум накладной {target.qty.max() if len(target) else 0:.0f}")


if __name__ == "__main__":
    main()
