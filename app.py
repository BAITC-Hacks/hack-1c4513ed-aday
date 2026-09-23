"""EKT StockPilot — purchasing dashboard."""
from dataclasses import replace
from pathlib import Path
import time
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.config import DEFAULT
from src.loader import FILES, load_supplier, source_signature
from src.pipeline import prepare, finish
from src.export import build_workbook
from src.uploads import validate_and_store
from src.llm import explain_item as ai_explain, assistant_answer

st.set_page_config(page_title="EKT StockPilot", page_icon="📦", layout="wide")
st.title("EKT StockPilot — автопилот закупа")
date_caption = st.empty()

@st.cache_data(show_spinner=False)
def cached_source_date(name, fingerprint, source_dir):
    return load_supplier(name, source_dir=source_dir)["source_as_of"]


@st.cache_data(show_spinner=False)
def cached_prepare(name, fingerprint, source_dir, as_of):
    started = time.perf_counter()
    prepared = prepare(load_supplier(name, source_dir=source_dir), replace(DEFAULT, as_of=as_of))
    return prepared, time.perf_counter() - started


if "uploaded_sources" not in st.session_state:
    st.session_state.uploaded_sources = {}
source_dates = {name: cached_source_date(name, source_signature(name, st.session_state.uploaded_sources.get(name)), st.session_state.uploaded_sources.get(name)) for name in ("IEK", "SystemeElectric")}
uploaded_now = False
revert_to_demo = False
with st.sidebar:
    st.header("Настройки расчёта")
    supplier = st.selectbox("Поставщик", ["Все", "IEK", "Systeme Electric"])
    categories = st.multiselect("Категория ABC", ["A", "B", "C"], default=["A", "B", "C"])
    urgencies = st.multiselect("Срочность", ["Критично", "Высокая", "Плановая"], default=["Критично", "Высокая", "Плановая"])
    show_all = st.checkbox("Показать все позиции", False)
    with st.form("calculation_settings"):
        review = st.number_input("Период пересмотра R, дней", 1, 120, DEFAULT.review_days)
        z_a = st.number_input("Уровень сервиса A, z", 0.0, 4.0, DEFAULT.service_z["A"], step=.01)
        z_b = st.number_input("Уровень сервиса B, z", 0.0, 4.0, DEFAULT.service_z["B"], step=.01)
        z_c = st.number_input("Уровень сервиса C, z", 0.0, 4.0, DEFAULT.service_z["C"], step=.01)
        automatic_date = st.checkbox("Дата автоматически по накладным", value=True)
        chosen_date = st.date_input("Дата расчёта (если автоматическая дата отключена)", value=max(source_dates.values()))
        calculate = st.form_submit_button("Рассчитать", type="primary", width="stretch")
    st.divider()
    st.subheader("Загрузить новые выгрузки 1С")
    upload_supplier = st.selectbox("Поставщик для загрузки", ["IEK", "Systeme Electric"])
    upload_key = "IEK" if upload_supplier == "IEK" else "SystemeElectric"
    labels = {"sales_tx.xlsx": "Продажи по накладным", "sales_monthly.xlsx": "Помесячные продажи", "stock_monthly.xlsx": "Помесячные остатки", "in_transit.xlsx": "Товар в пути", "moq.xlsx": "MOQ и кратность", "seasonality.xlsx": "Сезонность"}
    with st.form("upload_workbooks"):
        uploaded = {name: st.file_uploader(label, type=["xlsx"], key=f"upload_{upload_key}_{name}") for name, label in labels.items()}
        upload_clicked = st.form_submit_button("Проверить и использовать")
    if upload_clicked:
        try:
            path = validate_and_store(upload_key, uploaded)
            st.session_state.uploaded_sources[upload_key] = str(path)
            uploaded_now = True
            st.success(f"Проверены все {len(FILES)} файлов. Используются загруженные данные {upload_supplier}.")
        except Exception as exc:
            st.error(f"Не удалось принять выгрузки: {exc}")
    revert_to_demo = st.button("Вернуться к демо-данным")
    if revert_to_demo:
        st.session_state.uploaded_sources = {}
    for name, label in (("IEK", "IEK"), ("SystemeElectric", "Systeme Electric")):
        mode = "загруженные" if name in st.session_state.uploaded_sources else "демо"
        st.caption(f"{label}: {mode} данные")

if uploaded_now or revert_to_demo:
    source_dates = {name: cached_source_date(name, source_signature(name, st.session_state.uploaded_sources.get(name)), st.session_state.uploaded_sources.get(name)) for name in ("IEK", "SystemeElectric")}

if calculate or uploaded_now or revert_to_demo or "calculation" not in st.session_state:
    if calculate or "settings" not in st.session_state:
        settings = (int(review), float(z_a), float(z_b), float(z_c), bool(automatic_date), chosen_date)
    else:
        settings = st.session_state.settings
    active_dates = {name: source_dates[name] if settings[4] else settings[5] for name in ("IEK", "SystemeElectric")}
    with st.spinner("Считаем потребность…"):
        try:
            results = {}
            heavy_total = light_total = 0.0
            for name in ("IEK", "SystemeElectric"):
                source_dir = st.session_state.uploaded_sources.get(name)
                config = replace(DEFAULT, as_of=active_dates[name], review_days=settings[0], service_z={"A": settings[1], "B": settings[2], "C": settings[3]})
                started = time.perf_counter()
                prepared, compute_time = cached_prepare(name, source_signature(name, source_dir), source_dir, active_dates[name])
                heavy_elapsed = time.perf_counter() - started
                heavy_total += heavy_elapsed
                print(f"{name}: тяжёлая часть доступ {heavy_elapsed:.2f} с, исходный расчёт {compute_time:.2f} с")
                started = time.perf_counter()
                results[name] = finish(prepared, config)
                light_elapsed = time.perf_counter() - started
                light_total += light_elapsed
                print(f"{name}: лёгкая часть {light_elapsed:.2f} с")
            full = pd.concat([r["orders"] for r in results.values()], ignore_index=True)
            print(f"Итого: тяжёлая часть {heavy_total:.2f} с, лёгкая часть {light_total:.2f} с")
            st.session_state.calculation = (results, full)
            st.session_state.settings = settings
            st.session_state.active_dates = active_dates
            st.session_state.timings = (heavy_total, light_total)
            st.session_state.approved_signature = None
        except Exception as exc:
            st.error(f"Не удалось рассчитать заказ: {exc}")
            st.stop()

results, full = st.session_state.calculation
shown_dates = st.session_state.active_dates
date_caption.caption("Дата расчёта: " + "; ".join(f"{name if name == 'IEK' else 'Systeme Electric'} — {date:%d.%m.%Y}" for name, date in shown_dates.items()) + ". Количества рассчитывает Python; ИИ помогает с объяснением.")
view = full[full.recommended > 0].copy()
if show_all:
    view = full.copy()
    st.warning("Показаны все позиции, включая нулевые заказы. Таблица может быть большой.")
if supplier != "Все":
    view = view[view.supplier == supplier]
view = view[view.category.isin(categories) & view.urgency.isin(urgencies)].copy()
view = view.sort_values(["supplier", "recommended"], ascending=[True, False])

a, b, c = st.columns(3)
a.metric("Позиций к заказу", int((view.recommended > 0).sum()))
b.metric("Из них критичных", int(((view.recommended > 0) & (view.urgency == "Критично")).sum()))
c.metric("Поставщиков в заказе", int(view.loc[view.recommended > 0, "supplier"].nunique()))
st.subheader("Рекомендованный заказ")
st.caption("Экспорт станет доступен после утверждения заказа")

mapping = {"code": "Код 1С", "article": "Артикул поставщика", "name": "Наименование", "supplier": "Поставщик", "category": "Категория ABC", "manager_category": "Категория 2026", "stock": "Остаток", "transit": "В пути", "forecast_month": "Прогноз/мес", "safety_stock": "Страховой запас", "moq": "MOQ", "recommended": "Рекомендовано", "urgency": "Срочность", "short_reason": "Кратко почему", "explanation": "Обоснование"}
display = view[list(mapping)].rename(columns=mapping).reset_index(drop=True)
for col in ("Остаток", "В пути", "Страховой запас", "MOQ", "Рекомендовано"):
    display[col] = pd.to_numeric(display[col], errors="coerce").fillna(0).round().astype("Int64")
display["Прогноз/мес"] = pd.to_numeric(display["Прогноз/мес"], errors="coerce").fillna(0).round(1)
display["Корректировка"] = display["Рекомендовано"]
edited = st.data_editor(display, hide_index=True, width="stretch", row_height=96, column_order=[c for c in display if c != "Обоснование"], num_rows="fixed", disabled=list(mapping.values()), column_config={"Корректировка": st.column_config.NumberColumn(min_value=0, step=1), "Кратко почему": st.column_config.TextColumn(width=750, help="Полный текст обоснования показан в карточке артикула")}, key="order_editor")
if not edited["Корректировка"].equals(display["Корректировка"]):
    st.session_state.approved = False

if supplier in ("Все", "Systeme Electric"):
    comparison = view[view.supplier == "Systeme Electric"].copy()
    if len(comparison):
        with st.expander("Systeme Electric: данные таблицы закупщика и наш расчёт"):
            st.caption("Сравниваем средние продажи за 12 месяцев с прогнозом, месяцы запаса из таблицы с покрытием после нашего заказа и категории. Пустой «Заказ» менеджера не принимаем за ноль.")
            columns = {"code": "Код 1С", "name": "Наименование", "manager_avg12": "Таблица: продажи/мес за 12 мес.", "forecast_month": "Наш прогноз/мес", "manager_cover": "Таблица: запас, мес.", "cover_after_months": "После нашего заказа, мес.", "manager_category": "Таблица: категория 2026", "category": "Наша ABC"}
            st.dataframe(comparison[list(columns)].rename(columns=columns).round(1), hide_index=True, width="stretch")
            filled_orders = comparison[comparison.manager_order_filled]
            if len(filled_orders):
                st.caption("Заказ менеджера — только заполненные строки")
                st.dataframe(filled_orders[["code", "name", "manager_order", "recommended"]].rename(columns={"code": "Код 1С", "name": "Наименование", "manager_order": "Заказ менеджера", "recommended": "Наш расчёт"}), hide_index=True, width="stretch")

st.subheader("Карточка артикула")
if len(view):
    chosen_index = st.selectbox("Позиция", view.index.tolist(), format_func=lambda x: f"{view.loc[x, 'supplier']} · {view.loc[x, 'code']} — {view.loc[x, 'name']}")
    item = view.loc[chosen_index]
    chosen = item.code
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
    current_month = pd.Timestamp(st.session_state.active_dates[source]).replace(day=1)
    current_spikes = results[source]["spikes"]
    current_spikes = current_spikes[(current_spikes.code == chosen) & (current_spikes.month == current_month)]
    if len(current_spikes):
        fig.add_scatter(x=current_spikes.date, y=current_spikes.qty, mode="markers+text", text=[f"{x:,.0f}".replace(",", " ") for x in current_spikes.qty], textposition="top center", marker={"symbol": "star", "size": 15, "color": "#d62728"}, name="Разовая отгрузка текущего месяца")
    fig.add_scatter(x=pred.month, y=pred.forecast, mode="lines+markers", name="Прогноз")
    fig.update_layout(xaxis_title="Месяц", yaxis_title="Количество", legend_title="Показатель")
    st.plotly_chart(fig, width="stretch")
    if item.current_spike_qty > 0:
        st.info(f"В текущем месяце обнаружена разовая отгрузка {item.current_spike_qty:,.0f} шт., в регулярную потребность не включена.".replace(",", " "))
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
signature = pd.util.hash_pandas_object(edited, index=False).sum(), supplier, tuple(categories), tuple(urgencies), show_all, st.session_state.settings
if st.button("Утвердить заказ", type="primary", disabled=edited.empty):
    st.session_state.approved_signature = signature
if st.session_state.get("approved_signature") == signature:
    st.success("Заказ утверждён. Файл Excel готов к выгрузке.")
    approved = edited[["Код 1С", "Артикул поставщика", "Наименование", "Поставщик", "Корректировка", "Срочность"]].copy()
    approved["Обоснование"] = view.explanation.to_numpy()
    approved = approved.rename(columns={"Корректировка": "Количество"})
    approved["Количество"] = pd.to_numeric(approved["Количество"], errors="coerce").fillna(0).round().astype(int)
    approved = approved[approved["Количество"] > 0]
    folder = Path(__file__).resolve().parent / "output"
    folder.mkdir(exist_ok=True)
    workbook = build_workbook(approved, {"IEK": st.session_state.active_dates["IEK"], "Systeme Electric": st.session_state.active_dates["SystemeElectric"]})
    (folder / "stockpilot_order.xlsx").write_bytes(workbook)
    st.download_button("Скачать заказ (Excel)", workbook, file_name="stockpilot_order.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    with st.expander("Дополнительно: CSV по поставщикам"):
        for vendor, group in approved.groupby("Поставщик"):
            export = group[["Код 1С", "Артикул поставщика", "Наименование", "Количество"]]
            stem = "IEK" if vendor == "IEK" else "SystemeElectric"
            csv = export.to_csv(index=False, sep=";")
            (folder / f"order_{stem}.csv").write_text(csv, encoding="utf-8-sig")
            st.download_button(f"Скачать {vendor} CSV", csv.encode("utf-8-sig"), file_name=f"order_{stem}.csv", mime="text/csv")
