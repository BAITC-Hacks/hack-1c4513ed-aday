from types import SimpleNamespace

import pandas as pd

from src.agent import review_order


def order_row():
    return pd.DataFrame([{
        "code": "A_", "name": "Тестовый товар", "supplier": "IEK",
        "recommended": 120., "recent_sales": 60., "forecast_month": 10.,
        "stock": 0., "transit": 0., "moq": 20., "growth": .7,
        "cover_after_months": 12., "confidence": "Низкая",
        "confidence_reason": "спрос прерывистый", "excluded": 80.,
        "current_spike_qty": 0., "restored_amount": 0.,
        "urgency": "Критично", "manager_avg12": float("nan"),
        "manager_cover": float("nan"),
    }])


def test_agent_fallback_without_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    result = review_order(order_row())
    assert result["mode"] == "Детерминированная проверка"
    assert "A_" in result["report"]
    assert "list_flags" in result["tool_calls"]


def test_agent_calls_mocked_tools():
    calls = [SimpleNamespace(id=str(i), function=SimpleNamespace(name=name, arguments=args))
             for i, (name, args) in enumerate([
                 ("list_flags", '{"limit": 5}'),
                 ("get_item_details", '{"code": "A_"}'),
                 ("get_supplier_summary", '{"supplier": "IEK"}'),
             ])]

    class Completions:
        def __init__(self):
            self.count = 0

        def create(self, **kwargs):
            self.count += 1
            message = (SimpleNamespace(content=None, tool_calls=calls) if self.count == 1 else
                       SimpleNamespace(content="1. IEK, A_: проверьте покрытие и кратность.\n2. IEK, A_: уточните спрос.\n3. IEK, A_: подтвердите остаток.", tool_calls=None))
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    result = review_order(order_row(), client_factory=lambda: fake)
    assert result["mode"] == "ИИ-агент"
    assert len(result["tool_calls"]) == 3
    assert result["tool_calls"][0].startswith("list_flags")
    assert result["tool_calls"][1].startswith("get_item_details")
    assert "A_" in result["report"]
