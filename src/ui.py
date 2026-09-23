"""Streamlit presentation for a completed purchasing calculation."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.export import build_workbook
from src.llm import assistant_answer, explain_item as ai_explain


COLUMNS = {
    "code": "Код 1С", "article": "Артикул поставщика", "name": "Наименование",
    "supplier": "Поставщик", "category": "Категория ABC",
    "manager_category": "Категория 2026", "stock": "Остаток", "transit": "В пути",
    "forecast_month": "Прогноз/мес", "safety_stock": "Страховой запас",
    "moq": "MOQ", "recommended": "Рекомендовано", "urgency": "Срочность",
    "short_reason": "Кратко почему", "explanation": "Обоснование",
}
MAIN_COLUMNS = [
    "Код 1С", "Наименование", "Поставщик", "Остаток", "В пути",
    "Прогноз/мес", "Рекомендовано", "Корректировка", "Срочность", "Кратко почему",
]
URGENCY_LABELS = {"Критично": "🔴 Критично", "Высокая": "🟠 Высокая", "Плановая": "🟢 Плановая"}
URGENCY_ORDER = {"Критично": 0, "Высокая": 1, "Плановая": 2}


def _order_view(full, supplier, categories, urgencies, show_all):
    view = full.copy() if show_all else full[full.recommended > 0].copy()
    if supplier != "Все":
        view = view[view.supplier == supplier]
    view = view[view.category.isin(categories) & view.urgency.isin(urgencies)].copy()
    view["urgency_rank"] = view.urgency.map(URGENCY_ORDER).fillna(3)
    return view.sort_values(["urgency_rank", "recommended"], ascending=[True, False])


def _display_table(view):
    display = view[list(COLUMNS)].rename(columns=COLUMNS).reset_index(drop=True)
    for col in ("Остаток", "В пути", "Страховой запас", "MOQ", "Рекомендовано"):
        display[col] = pd.to_numeric(display[col], errors="coerce").fillna(0).round().astype("Int64")
    display["Прогноз/мес"] = pd.to_numeric(display["Прогноз/мес"], errors="coerce").fillna(0).round(1)
    display["Корректировка"] = display["Рекомендовано"]
    display["Срочность"] = display["Срочность"].replace(URGENCY_LABELS)
    return display


def _render_order(results, view, show_all):
    if show_all:
        st.warning("Показаны все позиции, включая нулевые заказы. Таблица может быть большой.")
    a, b, c = st.columns(3)
    a.metric("Позиций к заказу", int((view.recommended > 0).sum()))
    b.metric("Из них критичных", int(((view.recommended > 0) & (view.urgency == "Критично")).sum()))
    c.metric("Поставщиков в заказе", int(view.loc[view.recommended > 0, "supplier"].nunique()))

    st.subheader("Что заказать в первую очередь")
    critical = view[(view.urgency == "Критично") & (view.recommended > 0)].head(5)
    if critical.empty:
        st.caption("Критичных позиций среди выбранных фильтров нет.")
    else:
        for row in critical.itertuples():
            st.write(f"🔴 {row.code} · {row.name} · {row.supplier} · {row.recommended:,.0f} ед.".replace(",", " "))

    st.subheader("Рекомендованный заказ")
    st.caption("Экспорт станет доступен после утверждения заказа")
    all_columns = st.toggle("Показать все колонки", value=False)
    display = _display_table(view)
    order = list(display) if all_columns else MAIN_COLUMNS
    edited = st.data_editor(
        display, hide_index=True, width="stretch", column_order=order, num_rows="fixed",
        disabled=list(COLUMNS.values()),
        column_config={
            "Корректировка": st.column_config.NumberColumn(min_value=0, step=1),
            "Кратко почему": st.column_config.TextColumn(width="large", help="Полный текст находится в карточке артикула"),
        }, key="order_editor",
    )
    signature = (
        pd.util.hash_pandas_object(edited, index=False).sum(),
        tuple(view.code), st.session_state.settings,
    )
    if st.button("Утвердить заказ", type="primary", disabled=edited.empty):
        st.session_state.approved_signature = signature
    if st.session_state.get("approved_signature") == signature:
        st.success("Заказ утверждён. Excel готов к выгрузке.")
        approved = edited[["Код 1С", "Артикул поставщика", "Наименование", "Поставщик", "Корректировка"]].copy()
        approved["Срочность"] = view.urgency.to_numpy()
        approved["Обоснование"] = view.explanation.to_numpy()
        approved = approved.rename(columns={"Корректировка": "Количество"})
        approved["Количество"] = pd.to_numeric(approved["Количество"], errors="coerce").fillna(0).round().astype(int)
        approved = approved[approved["Количество"] > 0]
        folder = Path(__file__).resolve().parents[1] / "output"
        folder.mkdir(exist_ok=True)
        dates = st.session_state.active_dates
        workbook = build_workbook(approved, {"IEK": dates["IEK"], "Systeme Electric": dates["SystemeElectric"]})
        (folder / "stockpilot_order.xlsx").write_bytes(workbook)
        st.download_button("Скачать заказ (Excel)", workbook, file_name="stockpilot_order.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        with st.expander("Дополнительно: CSV по поставщикам"):
            for vendor, group in approved.groupby("Поставщик"):
                export = group[["Код 1С", "Артикул поставщика", "Наименование", "Количество"]]
                stem = "IEK" if vendor == "IEK" else "SystemeElectric"
                csv = export.to_csv(index=False, sep=";")
                (folder / f"order_{stem}.csv").write_text(csv, encoding="utf-8-sig")
                st.download_button(f"Скачать {vendor} CSV", csv.encode("utf-8-sig"),
                                   file_name=f"order_{stem}.csv", mime="text/csv")

    st.subheader("Тренд спроса по поставщикам")
    figure = go.Figure()
    for name, result in results.items():
        label = "IEK" if name == "IEK" else "Systeme Electric"
        trend = result["demand"].groupby("month", as_index=False).restored_qty.sum()
        figure.add_scatter(x=trend.month, y=trend.restored_qty, name=label, mode="lines+markers")
    figure.update_layout(xaxis_title="Месяц", yaxis_title="Очищенный спрос, ед.", height=300)
    st.plotly_chart(figure, width="stretch")


def _render_card(results, full, supplier, view):
    pool = full if supplier == "Все" else full[full.supplier == supplier]
    if pool.empty:
        st.info("Нет позиций для карточки.")
        return
    index = st.selectbox("Позиция", pool.index.tolist(),
                         format_func=lambda i: f"{pool.loc[i, 'supplier']} · {pool.loc[i, 'code']} — {pool.loc[i, 'name']}")
    item = pool.loc[index]
    source = "IEK" if item.supplier == "IEK" else "SystemeElectric"
    history = results[source]["demand"].query("code == @item.code").sort_values("month")
    pred = results[source]["predictions"].query("code == @item.code").sort_values("month")
    figure = go.Figure()
    figure.add_scatter(x=history.month, y=history.raw_qty, mode="lines+markers", name="Фактические продажи")
    figure.add_scatter(x=history.month, y=history.restored_qty, mode="lines+markers", name="Очищенный спрос")
    flagged = history[history.stockout]
    figure.add_scatter(x=flagged.month, y=flagged.restored_qty, mode="markers",
                       marker={"symbol": "x", "size": 12}, name="Дефицит")
    spikes = history[history.excluded > 0]
    figure.add_scatter(x=spikes.month, y=spikes.raw_qty, mode="markers",
                       marker={"symbol": "diamond", "size": 11}, name="Исключённый всплеск")
    current_month = pd.Timestamp(st.session_state.active_dates[source]).replace(day=1)
    current = results[source]["spikes"]
    current = current[(current.code == item.code) & (current.month == current_month)]
    if len(current):
        figure.add_scatter(x=current.date, y=current.qty, mode="markers+text",
                           text=[f"{x:,.0f}".replace(",", " ") for x in current.qty],
                           textposition="top center", marker={"symbol": "star", "size": 15, "color": "#d62728"},
                           name="Разовая отгрузка текущего месяца")
    figure.add_scatter(x=pred.month, y=pred.forecast, mode="lines+markers", name="Прогноз")
    figure.update_layout(xaxis_title="Месяц", yaxis_title="Количество", legend_title="Показатель")
    st.plotly_chart(figure, width="stretch")
    if item.current_spike_qty > 0:
        st.info(f"В текущем месяце обнаружена разовая отгрузка {item.current_spike_qty:,.0f} шт., в регулярную потребность не включена.".replace(",", " "))
    st.subheader("Почему такой заказ")
    st.write(item.explanation)
    st.write(f"Расчёт: спрос на горизонт {item.horizon_demand:,.1f} + страховой запас {item.safety_stock:,.1f} "
             f"− остаток {item.stock:,.1f} − в пути {item.transit:,.1f}; "
             f"округление до MOQ {item.moq:,.0f} → {item.recommended:,.0f}.".replace(",", " "))
    if st.button("Объяснить с ИИ"):
        st.info(ai_explain(item.to_dict()))
    if st.button("Объяснить с ИИ топ-20"):
        for row in view.head(20).itertuples():
            st.write(f"**{row.code}** — {ai_explain(row._asdict())}")


def _render_comparison(full, supplier):
    if supplier == "IEK":
        st.info("Таблица закупщика есть только для Systeme Electric. Выберите этого поставщика или «Все».")
        return
    comparison = full[full.supplier == "Systeme Electric"].copy()
    if comparison.empty:
        st.info("В таблице закупщика нет позиций для сравнения.")
        return
    st.caption("Сравниваем заполненные поля исходной таблицы закупщика с нашим расчётом. «Заказ» менеджера в демо-выгрузке пуст, поэтому его не сравниваем с нулём.")
    columns = {
        "code": "Код 1С", "name": "Наименование",
        "manager_avg12": "Таблица: продажи/мес за 12 мес.", "forecast_month": "Наш прогноз/мес",
        "manager_cover": "Таблица: запас, мес.", "cover_after_months": "После нашего заказа, мес.",
        "manager_category": "Таблица: категория 2026", "category": "Наша ABC",
    }
    st.dataframe(comparison[list(columns)].rename(columns=columns).round(1), hide_index=True, width="stretch")
    filled = comparison[comparison.manager_order_filled]
    if len(filled):
        st.subheader("Заполненные заказы менеджера")
        st.dataframe(filled[["code", "name", "manager_order", "recommended"]].rename(columns={
            "code": "Код 1С", "name": "Наименование", "manager_order": "Заказ менеджера",
            "recommended": "Наш расчёт"}), hide_index=True, width="stretch")


def _render_assistant(view):
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


def _render_methodology():
    st.markdown("""
1. Берём продажи и остатки из шести выгрузок 1С. Дату расчёта берём из последней расходной накладной; её можно изменить в настройках.
2. Последний неполный месяц не считаем полным месяцем истории. Разовые крупные отгрузки ищем и в нём, чтобы показать их в карточке.
3. Редкие всплески исключаем из регулярного спроса. Крупные продажи, которые повторяются минимум в трёх месяцах года, сохраняем.
4. Если товар отсутствовал на складе, восстанавливаем вероятный спрос по месяцам с наличием и сезонности.
5. Прогноз учитывает последние шесть полных месяцев, изменение продаж к прошлому году и сезонный индекс.
6. Категория ABC задаёт уровень сервиса и страховой запас. Потребность покрывает срок поставки и период до следующего заказа.
7. Вычитаем свободный остаток и товар в пути, затем округляем вверх до кратности поставки. Если устойчивого спроса нет, заказ равен нулю.
8. Человек проверяет и при необходимости меняет количество, утверждает заказ и скачивает Excel. ИИ помогает объяснять, но не считает числа.
""")


def render_dashboard(results, full, supplier, categories, urgencies, show_all):
    st.info("1. Выберите поставщика и нажмите «Рассчитать». 2. Проверьте позиции, при необходимости исправьте «Корректировку». 3. Нажмите «Утвердить заказ» и скачайте Excel.")
    view = _order_view(full, supplier, categories, urgencies, show_all)
    order_tab, card_tab, comparison_tab, assistant_tab, method_tab = st.tabs([
        "Заказ", "Карточка артикула", "Сравнение с таблицей закупщика", "Ассистент", "Как считаем",
    ])
    with order_tab:
        _render_order(results, view, show_all)
    with card_tab:
        _render_card(results, full, supplier, view)
    with comparison_tab:
        _render_comparison(full, supplier)
    with assistant_tab:
        _render_assistant(view)
    with method_tab:
        _render_methodology()
