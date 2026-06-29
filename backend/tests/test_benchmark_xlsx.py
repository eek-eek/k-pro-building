"""Загрузка справочника цен из .xlsx (stdlib-парсер + эндпоинт импорта)."""
import base64
import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.gosdata.xlsx import read_xlsx_dicts

client = TestClient(app)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _col(i):
    s, n = "", i + 1
    while n > 0:
        m = (n - 1) % 26
        s = chr(65 + m) + s
        n = (n - 1) // 26
    return s


def _make_xlsx(rows):
    body = []
    for ri, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{_col(ci)}{ri}" t="inlineStr"><is><t>{v}</t></is></c>'
            for ci, v in enumerate(row))
        body.append(f'<row r="{ri}">{cells}</row>')
    sheet = (f'<?xml version="1.0"?><worksheet xmlns="{_NS}"><sheetData>'
             + "".join(body) + "</sheetData></worksheet>")
    parts = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0"?><workbook xmlns="{_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, doc in parts.items():
            z.writestr(name, doc)
    return buf.getvalue()


def test_read_xlsx_dicts_parses_headers():
    data = _make_xlsx([["work_key", "code", "kind", "unit", "price"],
                       ["roof", "x", "material", "м²", "9000"]])
    assert read_xlsx_dicts(data) == [
        {"work_key": "roof", "code": "x", "kind": "material", "unit": "м²", "price": "9000"}]


def test_benchmark_import_xlsx_endpoint():
    data = _make_xlsx([["work_key", "code", "name", "kind", "unit", "consumption", "price"],
                       ["roof", "bm_xlsx", "Кровля", "material", "м²", "1.05", "9200"],
                       ["frame_concrete", "bad", "Кривой", "labor", "м³", "1", "100"]])
    b64 = base64.b64encode(data).decode()
    r = client.post("/api/benchmark/import", json={"xlsx_b64": b64})
    assert r.status_code == 200
    rep = r.json()
    assert rep["inserted"] == 1 and rep["skipped"] == 1  # labor с м³ отбракован
    try:
        listing = client.get("/api/benchmark").json()
        assert any(x["code"] == "bm_xlsx" and x["price"] == 9200 for x in listing)
    finally:
        for x in client.get("/api/benchmark").json():
            if x["code"] == "bm_xlsx":
                client.delete(f"/api/benchmark/{x['id']}")


def test_benchmark_import_rejects_garbage():
    assert client.post("/api/benchmark/import", json={"xlsx_b64": "bm9wZQ=="}).status_code == 400
    assert client.post("/api/benchmark/import", json={}).status_code == 400
