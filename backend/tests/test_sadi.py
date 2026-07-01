"""Справочники SADI: сидирование материалов/тарифов и поисковые эндпоинты."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import LaborTariff, MaterialPrice

client = TestClient(app)  # справочники — открытый раздел, без авторизации


def test_materials_seeded(db):
    total = db.scalar(select(func.count()).select_from(MaterialPrice))
    priced = db.scalar(select(func.count()).select_from(MaterialPrice).where(MaterialPrice.price.is_not(None)))
    assert total > 20000            # полный каталог ~27 420
    assert priced > 5000            # с ценами ~8 957
    # у каждой позиции заполнена нормализованная строка поиска
    row = db.scalars(select(MaterialPrice).limit(1)).first()
    assert row.name_lc == f"{row.code} {row.name}".lower()


def test_tariffs_seeded(db):
    total = db.scalar(select(func.count()).select_from(LaborTariff))
    regions = db.scalar(select(func.count(func.distinct(LaborTariff.region))))
    assert total > 1000
    assert regions == 16


def test_search_is_cyrillic_case_insensitive():
    # SQLite LIKE регистронезависим только для ASCII — проверяем, что кириллица ловится
    low = client.get("/api/materials", params={"q": "бетон"}).json()
    up = client.get("/api/materials", params={"q": "БЕТОН"}).json()
    assert low["total"] > 0
    assert low["total"] == up["total"]


def test_search_only_priced_filters():
    all_hits = client.get("/api/materials", params={"q": "бетон"}).json()["total"]
    priced = client.get("/api/materials", params={"q": "бетон", "only_priced": "true"}).json()
    assert priced["total"] <= all_hits
    assert all(it["price"] is not None for it in priced["items"])


def test_search_by_code():
    r = client.get("/api/materials", params={"q": "21-020101"}).json()
    assert r["total"] > 0
    assert any(it["code"].startswith("21-020101") for it in r["items"])


def test_search_limit_capped():
    r = client.get("/api/materials", params={"q": "а", "limit": 999}).json()
    assert r["limit"] <= 200
    assert len(r["items"]) <= 200


def test_material_categories():
    cats = client.get("/api/materials/categories").json()
    assert len(cats) >= 5
    assert all("category" in c and "count" in c for c in cats)
    assert sum(c["count"] for c in cats) > 20000


def test_tariff_regions_and_rows():
    regions = client.get("/api/tariffs/regions").json()
    assert len(regions) == 16
    assert "Алматы" in regions
    data = client.get("/api/tariffs", params={"region": "Алматы", "kind": "ИТР"}).json()
    assert data["count"] > 0
    assert all(t["region"] == "Алматы" and t["kind"] == "ИТР" for t in data["items"])
    assert all(t["rate"] > 0 for t in data["items"])
