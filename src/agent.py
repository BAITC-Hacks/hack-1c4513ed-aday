"""Purchasing-order review with deterministic tools and optional function calling."""
import json
import os
import time

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

TOOLS = [
    {"type": "function", "function": {"name": "list_flags", "description": "Найти позиции заказа с рисками для проверки", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_item_details", "description": "Получить числовые агрегаты по одному коду 1С", "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "supplier": {"type": "string"}}, "required": ["code"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_supplier_summary", "description": "Получить сводку заказа по поставщику", "parameters": {"type": "object", "properties": {"supplier": {"type": "string"}}, "additionalProperties": False}}},
]


def list_flags(orders):
    """Return one explicit risk per row, without invoice or customer data."""
    active = orders[orders.recommended > 0].copy()
    if active.empty:
        return pd.DataFrame(columns=["supplier", "code", "name", "priority", "flag", "reason"])
    average = active.recent_sales.fillna(0) / 6
    flags = []

    def add(mask, priority, label, reason):
        for row in active.loc[mask].itertuples():
            flags.append({"supplier": row.supplier, "code": row.code, "name": row.name,
                          "priority": priority, "flag": label, "reason": reason(row)})

    add(active.cover_after_months > 6, 0, "долгое покрытие",
        lambda row: f"покрытие после заказа {row.cover_after_months:.1f} мес.; проверьте MOQ {row.moq:.0f}")
    add((average > 0) & (active.recommended > 3 * average), 1, "крупный заказ",
        lambda row: f"заказ {row.recommended:.0f} ед. больше 3× средних продаж за 6 месяцев ({row.recent_sales/6:.0f} ед./мес.)")
    add((active.growth <= .7001) | (active.growth >= 1.499), 2, "рост на границе",
        lambda row: f"коэффициент роста {row.growth:.2f} на границе допустимого диапазона")
    add(active.confidence == "Низкая", 3, "низкая уверенность",
        lambda row: f"низкая уверенность: {row.confidence_reason}")
    add((active.excluded.fillna(0) + active.current_spike_qty.fillna(0)) > 3 * active.forecast_month.clip(lower=1), 4, "крупный исключённый всплеск",
        lambda row: f"исключённые отгрузки {row.excluded + row.current_spike_qty:.0f} ед. больше 3 месячных прогнозов")
    if "manager_avg12" in active:
        manager = active.manager_avg12.fillna(0)
        add((manager > 0) & ((active.forecast_month > manager * 1.5) | (active.forecast_month < manager / 1.5)),
            5, "расхождение с закупщиком",
            lambda row: f"прогноз {row.forecast_month:.0f} ед./мес. отличается от среднего в таблице закупщика {row.manager_avg12:.0f}")
    if "manager_cover" in active:
        manager_cover = active.manager_cover.fillna(0)
        add((manager_cover > 0) & ((active.cover_after_months > manager_cover * 2) | (active.cover_after_months < manager_cover / 2)),
            6, "расхождение покрытия",
            lambda row: f"после заказа {row.cover_after_months:.1f} мес. против «Запас» {row.manager_cover:.1f} мес. в таблице закупщика")
    if not flags:
        return pd.DataFrame(columns=["supplier", "code", "name", "priority", "flag", "reason"])
    return pd.DataFrame(flags).sort_values(["priority", "supplier", "code"]).reset_index(drop=True)


def get_item_details(orders, code, supplier=None):
    selected = orders[orders.code.astype(str) == str(code)]
    if supplier:
        selected = selected[selected.supplier == supplier]
    if selected.empty:
        return {"error": "Код не найден в текущем заказе"}
    fields = ("code", "name", "supplier", "recommended", "recent_sales", "forecast_month",
              "stock", "transit", "moq", "growth", "cover_after_months", "confidence",
              "confidence_reason", "excluded", "current_spike_qty", "restored_amount",
              "manager_avg12", "manager_cover")
    row = selected.iloc[0]
    return {key: (None if pd.isna(row[key]) else row[key].item() if isinstance(row[key], np.generic) else row[key])
            for key in fields if key in row}


def get_supplier_summary(orders, supplier=None):
    selected = orders[orders.recommended > 0]
    if supplier:
        selected = selected[selected.supplier == supplier]
    flags = list_flags(selected)
    return {"supplier": supplier or "Все", "positions": len(selected),
            "critical": int((selected.urgency == "Критично").sum()),
            "low_confidence": int((selected.confidence == "Низкая").sum()),
            "flag_counts": flags.flag.value_counts().to_dict() if len(flags) else {}}


def _fallback(orders, flags):
    summary = get_supplier_summary(orders)
    selected = []
    seen = set()
    for label in flags.flag.drop_duplicates():
        for supplier in flags.supplier.drop_duplicates():
            candidates = flags[(flags.flag == label) & (flags.supplier == supplier)]
            for row in candidates.itertuples():
                key = (row.supplier, row.code)
                if key not in seen:
                    selected.append(row)
                    seen.add(key)
                    break
            if len(selected) >= 7:
                break
        if len(selected) >= 7:
            break
    if len(selected) < 3:
        for row in flags.itertuples():
            key = (row.supplier, row.code)
            if key not in seen:
                selected.append(row)
                seen.add(key)
            if len(selected) >= 3:
                break
    if not selected:
        report = "В текущем заказе не найдено позиций по заданным правилам риска. Проверьте остатки перед утверждением."
    else:
        report = "\n".join(
            f"{i}. {row.supplier}, {row.code}: {row.reason}."
            for i, row in enumerate(selected, 1)
        )
    return {"report": report, "tool_calls": ["list_flags", "get_supplier_summary"],
            "mode": "Детерминированная проверка", "summary": summary}


def review_order(orders, client_factory=None, timeout=40):
    """Call tools for at most six steps; return the same structured fallback offline."""
    flags = list_flags(orders)
    fallback = _fallback(orders, flags)
    providers = [
        (os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), None),
        (os.getenv("NVIDIA_API_KEY"), os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct"), "https://integrate.api.nvidia.com/v1"),
    ]
    if client_factory is not None:
        providers = [("test-key", "mock-model", None)]
    started = time.monotonic()
    for key, model, base_url in providers:
        if not key:
            continue
        try:
            if client_factory is None:
                from openai import OpenAI
                client = OpenAI(api_key=key, base_url=base_url, timeout=min(12, timeout), max_retries=0)
            else:
                client = client_factory()
            trace = []
            messages = [
                {"role": "system", "content": "Ты агент проверки заказа закупщика. Используй инструменты для проверки риска. Ответь на русском 3–7 нумерованными пунктами с конкретными кодами артикулов и причинами. Не придумывай чисел. Номеров накладных и данных клиентов нет."},
                {"role": "user", "content": json.dumps(get_supplier_summary(orders), ensure_ascii=False)},
            ]
            for _ in range(6):
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Время проверки истекло")
                answer = client.chat.completions.create(model=model, messages=messages, tools=TOOLS,
                                                         tool_choice="auto", timeout=min(12, remaining), max_tokens=600)
                message = answer.choices[0].message
                calls = list(message.tool_calls or [])
                if not calls:
                    content = (message.content or "").strip()
                    if content and any(str(code) in content for code in flags.code.head(20)):
                        return {"report": content, "tool_calls": trace, "mode": "ИИ-агент", "summary": fallback["summary"]}
                    break
                messages.append({"role": "assistant", "content": message.content, "tool_calls": [
                    {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
                    for call in calls]})
                for call in calls:
                    if len(trace) >= 6:
                        raise RuntimeError("Достигнут предел вызовов инструментов")
                    args = json.loads(call.function.arguments or "{}")
                    name = call.function.name
                    if name == "list_flags":
                        value = flags.head(max(1, min(20, int(args.get("limit", 15))))).to_dict("records")
                    elif name == "get_item_details":
                        value = get_item_details(orders, args.get("code", ""), args.get("supplier"))
                    elif name == "get_supplier_summary":
                        value = get_supplier_summary(orders, args.get("supplier"))
                    else:
                        value = {"error": "Неизвестный инструмент"}
                    trace.append(f"{name}({json.dumps(args, ensure_ascii=False)})")
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": json.dumps(value, ensure_ascii=False, default=str)})
        except Exception:
            continue
    return fallback
