"""Optional language explanations. Never used in numeric calculations."""
import json
import os
from dotenv import load_dotenv
from src.explain import explain_item as template_explain

load_dotenv()


def _ask(system, user):
    from openai import OpenAI
    providers = [
        ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini", None),
        ("NVIDIA_API_KEY", "NVIDIA_MODEL", "meta/llama-3.1-8b-instruct", "https://integrate.api.nvidia.com/v1"),
    ]
    for key_name, model_name, default_model, base_url in providers:
        key = os.getenv(key_name)
        if not key:
            continue
        try:
            client = OpenAI(api_key=key, base_url=base_url, timeout=12.0, max_retries=0)
            response = client.chat.completions.create(
                model=os.getenv(model_name, default_model),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=180,
            )
            answer = response.choices[0].message.content
            if answer:
                return answer.strip()
        except Exception:
            continue
    return None


def explain_item(row):
    fields = ("name", "supplier", "forecast_month", "growth", "season_index", "stock", "transit", "safety_stock", "moq", "excluded", "spike_count", "restored_amount", "recommended")
    aggregates = {key: row[key] for key in fields if key in row}
    result = _ask("Ты помощник закупщика. Ответь на русском в 1–2 предложениях. Используй только переданные числа, ничего не придумывай. Номеров накладных и данных клиентов нет.", json.dumps(aggregates, ensure_ascii=False, default=str))
    return result or template_explain(row)


def assistant_answer(question, orders):
    active = orders[orders.recommended > 0]
    top = active.sort_values("recommended", ascending=False).head(15)
    summary = {"positions": len(active), "critical": int((active.urgency == "Критично").sum()), "total_qty": float(active.recommended.sum()), "by_supplier": active.groupby("supplier").recommended.sum().to_dict(), "top": top[["code", "name", "supplier", "recommended", "urgency"]].to_dict("records")}
    answer = _ask("Ты ассистент закупщика. Отвечай кратко по-русски. Используй только переданную сводку, не выдумывай числа. Если данных недостаточно, скажи об этом.", json.dumps({"question": question, "orders": summary}, ensure_ascii=False, default=str))
    return answer or f"К заказу {summary['positions']} позиций, из них критичных {summary['critical']}; всего {summary['total_qty']:.0f} единиц. Для подробностей выберите позицию в таблице."
