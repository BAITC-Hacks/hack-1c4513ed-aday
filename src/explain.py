"""Deterministic explanations for a purchasing manager."""
import pandas as pd


def quantity(value):
    return f"{float(value):,.0f}".replace(",", " ")


def decimal(value, digits=1):
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def short_reason(row):
    if row.get("no_stable_demand", False):
        if row.get("recent_sales", 0) <= 0:
            return "Нет устойчивого спроса: за последние 6 полных месяцев продаж не было, заказ не нужен."
        return "Прогноз ниже 0,5 ед./мес.: устойчивого спроса нет, заказ не нужен."
    cover = row.get("days_cover", 0) / 30
    cover = max(0, cover) if pd.notna(cover) else 0
    if row["recommended"] > 0:
        return (f"Остатка и товара в пути хватит примерно на {decimal(cover)} мес.; "
                f"с учётом поставки {int(row['lead_days'])} дн. и страхового запаса рекомендуем дозаказать {quantity(row['recommended'])} ед.")
    return f"Остатка и товара в пути хватит примерно на {decimal(cover)} мес.; дополнительный заказ сейчас не нужен."


def explain_item(row):
    growth = row["growth"]
    trend = "снижается" if growth < .95 else "растёт" if growth > 1.05 else "стабилен"
    season = row["season_index"]
    seasonal = "сезонный спад" if season < .9 else "сезонный подъём" if season > 1.1 else "обычный сезон"
    text = (f"{short_reason(row)} Продаём около {quantity(row['forecast_month'])} ед./мес.; "
            f"спрос {trend} (×{decimal(growth, 2)}), сейчас {seasonal} (×{decimal(season, 2)}). "
            f"Остаток {quantity(row['stock'])}, в пути {quantity(row['transit'])}, "
            f"страховой запас {quantity(row['safety_stock'])}; потребность на {int(row['lead_days'] + row['review_days'])} дн. — {quantity(row['need'])} ед. "
            f"Округление до кратности {quantity(row['moq'])}.")
    if row.get("spike_count", 0) > 0:
        text += f" Из прошлых полных месяцев исключено {int(row['spike_count'])} разовых всплесков на {quantity(row['excluded'])} ед."
    if row.get("restored_amount", 0) > 0:
        text += f" После дефицита восстановлено {quantity(row['restored_amount'])} ед. спроса."
    if row.get("smoothed_amount", 0) > 0:
        text += f" Для устойчивого прогноза сглажено {quantity(row['smoothed_amount'])} ед. месячных пиков."
    if row.get("current_spike_qty", 0) > 0:
        text += (f" В текущем месяце обнаружена разовая отгрузка {quantity(row['current_spike_qty'])} шт., "
                 "в регулярную потребность не включена.")
    if row.get("confidence") == "Низкая":
        text += f" Уверенность низкая: {row.get('confidence_reason', 'нужна проверка истории спроса')}."
    return text
