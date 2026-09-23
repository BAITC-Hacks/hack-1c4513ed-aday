from io import BytesIO
import pandas as pd
import pytest
from src.loader import FILES, load_supplier
from src.uploads import validate_and_store


def workbook(frame):
    buffer = BytesIO()
    frame.to_excel(buffer, index=False)
    return BytesIO(buffer.getvalue())


@pytest.fixture
def upload_books():
    sales = pd.DataFrame({"Номенклатура": ["Товар"], "Номенклатура.Код": ["A_"], "мар. 2026": [20], "апр. 2026": [20]})
    stock = pd.DataFrame({"Номенклатура": ["Товар"], "Ед.": ["шт"], "Номенклатура.Код": ["A_"], "мар. 2026": [10], "апр. 2026": [5]})
    tx = pd.DataFrame({"Дата": ["12.03.2026 12:00:00"], "Номер": [1], "Документ": ["Расходная накладная 1"], "Код": ["A_"], "Номенклатура": ["Товар"], "Ед.": ["шт"], "Склад": ["Основной"], "Количество": [20]})
    transit = pd.DataFrame({"Код 1с": ["A_"], "Артикул ИЭК": ["T-1"], "Наименование": ["Товар"], "РФ УТ-1 от 1 августа 2026 г. (поступление до 01.09.2026)": [5]})
    moq = pd.DataFrame({"№": [1], "Код 1с": ["A_"], "Артикул поставщика": ["T-1"], "Наименование": ["Товар"], "Мин. разр. к отгр.": [2]})
    season = pd.DataFrame([[2024] + [100] * 12, [2025] + [100] * 12], columns=["год"] + [f"месяц {i}" for i in range(12)])
    books = dict(zip(FILES, map(workbook, (tx, sales, stock, transit, moq, season))))
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"Примечание": ["Служебный лист"]}).to_excel(writer, sheet_name="Служебный", index=False)
        transit.to_excel(writer, sheet_name="Лист4", index=False)
    books["in_transit.xlsx"] = BytesIO(buffer.getvalue())
    return books


def test_uploads_are_validated_and_loaded(tmp_path, monkeypatch, upload_books):
    monkeypatch.setattr("src.uploads.ROOT", tmp_path)
    folder = validate_and_store("IEK", upload_books)
    assert folder.is_relative_to(tmp_path / "data" / "uploads")
    loaded = load_supplier("IEK", use_cache=False, source_dir=folder)
    assert loaded["items"].iloc[0].code == "A_"
    assert loaded["lead_days"] == 31
    assert len(list(folder.glob("*.xlsx"))) == 6


def test_upload_error_names_bad_file(tmp_path, monkeypatch, upload_books):
    monkeypatch.setattr("src.uploads.ROOT", tmp_path)
    upload_books["sales_monthly.xlsx"] = BytesIO(b"not an Excel file")
    with pytest.raises(ValueError, match="sales_monthly.xlsx"):
        validate_and_store("IEK", upload_books)
    assert not list((tmp_path / "data" / "uploads" / "IEK").glob("staging-*"))
