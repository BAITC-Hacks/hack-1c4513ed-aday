"""EKT StockPilot — purchasing dashboard."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.config import DEFAULT
from src.pipeline import calculate_all
from src.llm import explain_item as ai_explain, assistant_answer

st.set_page_config(page_title="EKT StockPilot", page_icon="📦", layout="wide")
st.title("EKT StockPilot — автопилот закупа")
st.caption("Расчёт на 22.09.2026 по выгрузкам 1С. Количества рассчитывает Python; ИИ помогает с объяснением.")

with st.sidebar:
    st.header("Настройки расчёта")
    supplier = st.selectbox("Поставщик", ["Все", "IEK", "Systeme Electric"])
    categories = st.multiselect("Категория ABC", ["A", "B", "C"], default=["A", "B", "C"])
    urgencies = st.multiselect("Срочность", ["Критично", "Высокая", "Плановая"], default=["Критично", "Высокая", "Плановая"])
    review = st.number_input("Период пересмотра R, дней", 1, 120, DEFAULT.review_days)
    z_a = st.number_input("Уровень сервиса A, z", 0.0, 4.0, DEFAULT.service_z["A"], step=.01)
    z_b = st.number_input("Уровень сервиса B, z", 0.0, 4.0, DEFAULT.service_z["B"], step=.01)
    z_c = st.number_input("Уровень сервиса C, z", 0.0, 4.0, DEFAULT.service_z["C"], step=.01)
    show_all = st.checkbox("Показать позиции без продаж и заказа", False)
    calculate = st.button("Рассчитать", type="primary", width="stretch")

settings = (int(review), float(z_a), float(z_b), float(z_c))
if calculate or "calculation" not in st.session_state or st.session_state.get("settings") != settings:
    config = replace(DEFAULT, review_days=int(review), service_z={"A": z_a, "B": z_b, "C": z_c})
    with st.spinner("Читаем выгрузки и считаем потребность…"):
        try:
            st.session_state.calculation = calculate_all(config=config)
            st.session_state.settings = settings
            st.session_state.approved = False
        except Exception as exc:
            st.error(f"Не удалось рассчитать заказ: {exc}")
            st.stop()

results, full = st.session_state.calculation
view = full[full.recommended > 0].copy()
if show_all:
    view = full.copy()
if supplier != "Все":
    view = view[view.supplier == supplier]
view = view[view.category.isin(categories) & view.urgency.isin(urgencies)].copy()
view = view.sort_values(["supplier", "recommended"], ascending=[True, False])

a, b, c = st.columns(3)
a.metric("Позиций к заказу", int((view.recommended > 0).sum()))
b.metric("Из них критичных", int(((view.recommended > 0) & (view.urgency == "Критично")).sum()))
c.metric("Суммарное количество", f"{view.recommended.sum():,.0f}")
st.subheader("Рекомендованный заказ")

mapping = {"code": "Код 1С", "article": "Артикул поставщика", "name": "Наименование", "supplier": "Поставщик", "category": "Категория ABC", "manager_category": "Категория 2026", "stock": "Остаток", "transit": "В пути", "forecast_month": "Прогноз/мес", "safety_stock": "Страховой запас", "moq": "MOQ", "recommended": "Рекомендовано", "urgency": "Срочность", "explanation": "Обоснование"}
display = view[list(mapping)].rename(columns=mapping).reset_index(drop=True)
display["Корректировка"] = display["Рекомендовано"]
edited = st.data_editor(display, hide_index=True, width="stretch", num_rows="fixed", disabled=list(mapping.values()), column_config={"Корректировка": st.column_config.NumberColumn(min_value=0, step=1)}, key="order_editor")
if not edited["Корректировка"].equals(display["Корректировка"]):
    st.session_state.approved = False

if supplier in ("Все", "Systeme Electric"):
    comparison = view[view.supplier == "Systeme Electric"]["code name manager_order recommended".split()].copy()
    if len(comparison):
        with st.expander("Systeme Electric: заказ менеджера и наш расчёт"):
            comparison.columns = ["Код 1С", "Наименование", "Заказ менеджера", "Наш расчёт"]
            comparison["Разница"] = comparison["Наш расчёт"] - comparison["Заказ менеджера"]
            st.dataframe(comparison, hide_index=True, width="stretch")

st.subheader("Карточка артикула")
if len(view):
    chosen = st.selectbox("Позиция", view.code.tolist(), format_func=lambda x: f"{x} — {view.loc[view.code == x, 'name'].iloc[0]}")
    item = view[view.code == chosen].iloc[0]
    source = "IEK" if item.supplier == "IEK" else "SystemeElectric"
    history = results[source]["demand"].query("code == @chosen").sort_values("month")
    pred = results[source]["predictions"].query("code == @chosen").sort_values("month")
    fig = go.Figure()
    fig.add_scatter(x=history.month, y=history.raw_qty, mode="lines+markers", name="Факт")
    fig.add_scatter(x=history.month, y=history.restored_qty, mode="lines+markers", name="Очищенный и восстановленный спрос")
    flagged = history[history.stockout]
    fig.add_scatter(x=flagged.month, y=flagged.restored_qty, mode="markers", marker={"symbol": "x", "size": 12}, name="Дефицит")
    spikes = history[history.excluded > 0]
    fig.add_scatter(x=spikes.month, y=spikes.raw_qty, mode="markers", marker={"symbol": "diamond", "size": 11}, name="Исключённый всплеск")
    fig.add_scatter(x=pred.month, y=pred.forecast, mode="lines+markers", name="Прогноз")
    fig.update_layout(xaxis_title="Месяц", yaxis_title="Количество", legend_title="Показатель")
    st.plotly_chart(fig, width="stretch")
    st.write(item.explanation)
    st.write(f"Шаги: спрос на горизонт {item.horizon_demand:.1f} + страховой запас {item.safety_stock:.1f} − остаток {item.stock:.1f} − в пути {item.transit:.1f}; округление до MOQ {item.moq:.0f} → {item.recommended:.0f}.")
    if st.button("Объяснить с ИИ"):
        st.info(ai_explain(item.to_dict()))
    if st.button("Объяснить с ИИ топ-20"):
        for _, row in view.head(20).iterrows():
            st.write(f"**{row.code}** — {ai_explain(row.to_dict())}")

st.subheader("Ассистент закупщика")
if "chat" not in st.session_state:
    st.session_state.chat = []
for role, message in st.session_state.chat:
    with st.chat_message(role):
        st.write(message)
question = st.chat_input("Спросите о текущем заказе")
if question:
    answer = assistant_answer(question, view)
    st.session_state.chat.extend([("user", question), ("assistant", answer)])
    st.rerun()

st.divider()
if st.button("Утвердить заказ", type="primary", disabled=edited.empty):
    st.session_state.approved = True
if st.session_state.get("approved"):
    st.success("Заказ утверждён. Файлы для каждого поставщика готовы к выгрузке.")
    approved = edited[["Код 1С", "Артикул поставщика", "Наименование", "Поставщик", "Корректировка"]].copy()
    approved = approved.rename(columns={"Корректировка": "Количество"})
    approved["Количество"] = pd.to_numeric(approved["Количество"], errors="coerce").fillna(0)
    approved = approved[approved["Количество"] > 0]
    folder = Path(__file__).resolve().parent / "output"
    folder.mkdir(exist_ok=True)
    for vendor, group in approved.groupby("Поставщик"):
        export = group.drop(columns="Поставщик")
        stem = "IEK" if vendor == "IEK" else "SystemeElectric"
        csv = export.to_csv(index=False, sep=";", encoding="utf-8-sig")
        buffer = BytesIO()
        export.to_excel(buffer, index=False)
        (folder / f"order_{stem}.csv").write_text(csv, encoding="utf-8-sig")
        (folder / f"order_{stem}.xlsx").write_bytes(buffer.getvalue())
        left, right = st.columns(2)
        left.download_button(f"Скачать {vendor} CSV", csv.encode("utf-8-sig"), file_name=f"order_{stem}.csv", mime="text/csv")
        right.download_button(f"Скачать {vendor} Excel", buffer.getvalue(), file_name=f"order_{stem}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
