"""Deterministic Russian explanations based only on calculation aggregates."""


def explain_item(row):
    return (f"Прогноз {row['forecast_month']:.1f}/мес. (рост ×{row['growth']:.2f}, сезонность ×{row['season_index']:.2f}); "
            f"остаток {row['stock']:.1f}, в пути {row['transit']:.1f}, страховой запас {row['safety_stock']:.1f}, MOQ {row['moq']:.0f}. "
            f"Исключено всплесков: {int(row['spike_count'])} ({row['excluded']:.1f} ед.); "
            f"восстановлено из-за дефицита {row['restored_amount']:.1f} ед. "
            f"Потребность на {row['lead_days'] + row['review_days']} дн. {row['need']:.1f}; заказ {row['recommended']:.0f}.")
