import json

from bot import vinted_api as va


def test_parametri_da_url_catalogo():
    u = "https://www.vinted.it/catalog?search_text=borsa&catalog[]=19&brand_ids[]=1&brand_ids[]=2&price_to=50&order=newest_first"
    p = va.parametri_da_url_catalogo(u, per_page=20)
    assert p["search_text"] == "borsa"
    assert p["attribute_ids[brand]"] == "1,2"
    assert p["attribute_ids[catalog]"] == "19"
    assert p["price_to"] == "50"
    assert p["per_page"] == 20 and p["page"] == 1
    assert "attribute_ids[color]" not in p and "price_from" not in p


def test_articoli_da_json_catalogo():
    dati = {"items": [
        {"id": 11, "title": "Borsa Prada nera", "price": {"amount": "45.0", "currency_code": "EUR"}, "photo": {"url": "https://images1.vinted.net/t/01_x/f800/1.jpg"}},
        {"id": 12, "title": "Borsa Prada nera", "price": {"amount": "45.0"}},
        {"id": 13, "title": "ab", "price": {"amount": "5"}},
        {"id": 14, "title": "Zaino Prada", "price": {"amount": "60"}},
    ]}
    testo, mappa, min_ = va.articoli_da_json_catalogo(json.dumps(dati))
    assert testo.splitlines() == ["- Borsa Prada nera — €45.00", "- Zaino Prada — €60.00"]
    assert "https://www.vinted.it/items/11" in mappa.values()
    assert min_ == {"11": "https://images1.vinted.net/t/01_x/f800/1.jpg"}
    assert va.articoli_da_json_catalogo("non json") == ("", {}, {})


def test_scheda_da_json_item():
    dati = {"item": {"description": "ciao", "size_title": "M", "photos": [
        {"full_size_url": "https://images1.vinted.net/t/01_aa/f800/1.jpeg"},
        {"url": "https://images1.vinted.net/t/02_bb/f800/2.jpeg"}]}}
    s = va.scheda_da_json_item(json.dumps(dati))
    assert list(s["foto"]) == ["01_aa", "02_bb"] and s["taglia"] == "M" and s["descrizione"] == "ciao"
    assert va.scheda_da_json_item("[]") == {}


def test_intestazioni():
    h = va._intestazioni("tok", "anon")
    assert h["Authorization"] == "Bearer tok" and h["x-anon-id"] == "anon" and h["Sec-Fetch-Mode"] == "cors"
