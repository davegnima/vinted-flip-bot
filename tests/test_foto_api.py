"""Fallback foto via API JSON di Vinted (21/10): parser puro, nessuna rete."""
import json

from bot.vinted_scrape import _estrai_foto_da_json_item


def test_foto_da_json_con_item_annidato():
    dati = {"item": {"photos": [
        {"url": "https://images1.vinted.net/t/abc123/f800/x.jpeg?s=ab12"},
        {"full_size_url": "https://images1.vinted.net/t/def456/f800/y.jpeg", "url": "https://images1.vinted.net/t/def456/310x430/y.jpeg"},
    ]}}
    foto = _estrai_foto_da_json_item(json.dumps(dati))
    assert list(foto) == ["abc123", "def456"]
    assert foto["def456"].endswith("/f800/y.jpeg")


def test_foto_da_json_senza_item_e_duplicati():
    dati = {"photos": [
        {"url": "https://images2.vinted.net/t/zzz/f800/a.webp"},
        {"url": "https://images2.vinted.net/t/zzz/f800/a.webp"},
    ]}
    assert list(_estrai_foto_da_json_item(json.dumps(dati))) == ["zzz"]


def test_json_non_valido_o_senza_foto_ritorna_vuoto():
    assert _estrai_foto_da_json_item("<!DOCTYPE html><html>") == {}
    assert _estrai_foto_da_json_item(json.dumps({"item": {"title": "x"}})) == {}
    assert _estrai_foto_da_json_item("[]") == {}
