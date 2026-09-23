"""EKT StockPilot — purchasing dashboard."""
from dataclasses import replace
import time
import pandas as pd
import streamlit as st
from src.config import DEFAULT
from src.loader import FILES, load_supplier, source_signature
from src.pipeline import prepare, finish
from src.uploads import validate_and_store
from src.ui import render_dashboard

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
    confidence_filter = st.multiselect("Уверенность", ["Высокая", "Средняя", "Низкая"], default=["Высокая", "Средняя", "Низкая"])
    show_all = st.checkbox("Показать все позиции", False)
    automatic_date = st.checkbox("Дата автоматически по накладным", value=True, help="Чтобы выбрать дату вручную, снимите галочку и нажмите «Рассчитать».")
    with st.form("calculation_settings"):
        review = st.number_input("Период пересмотра R, дней", 1, 120, DEFAULT.review_days)
        z_a = st.number_input("Уровень сервиса A, z", 0.0, 4.0, DEFAULT.service_z["A"], step=.01)
        z_b = st.number_input("Уровень сервиса B, z", 0.0, 4.0, DEFAULT.service_z["B"], step=.01)
        z_c = st.number_input("Уровень сервиса C, z", 0.0, 4.0, DEFAULT.service_z["C"], step=.01)
        chosen_date = st.date_input("Дата расчёта (если автоматическая дата отключена)", value=max(source_dates.values()), disabled=automatic_date, help="Чтобы изменить дату, снимите галочку «Дата автоматически по накладным».")
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
render_dashboard(results, full, supplier, categories, urgencies, confidence_filter, show_all)
