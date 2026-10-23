import time

import pytest

from bot import db
from bot import gemini_stato as gs
import main_telethon as m


@pytest.fixture(autouse=True)
def db_pulito(tmp_path, monkeypatch):
    db.chiudi()
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "t.sqlite3"))
    yield
    db.chiudi()


def test_eventi_scrittura_e_lettura():
    assert db.scrivi_evento("esito", "1", "Prada", {"esito": "COMPRA", "target": 120})
    assert db.scrivi_evento("panel", "1", "Prada", {"modello": "x", "ok": True})
    ev = db.leggi_eventi("esito")
    assert len(ev) == 1 and ev[0]["esito"] == "COMPRA" and ev[0]["brand"] == "Prada" and ev[0]["item_id"] == "1"
    assert db.conta_eventi("panel") == 1 and db.conta_eventi("tracciamento") == 0
    assert db.leggi_eventi("esito", dal_ts=time.time() + 100) == []


def test_stato_gemini_sopravvive_al_riavvio_senza_salvare_la_key(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["chiave-segreta-1", "chiave-2"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    gs._gemini_segna_key_quota_esaurita("chiave-segreta-1", "modello-x", 600)
    gs._gemini_segna_modello_non_disponibile("modello-y", 7200, "non disponibile")
    # "riavvio": dizionari vuoti, DB riaperto
    db.chiudi()
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    assert gs.ripristina_stato_gemini() == (1, 1)
    assert gs._gemini_key_in_quota_esaurita("chiave-segreta-1", "modello-x")
    assert not gs._gemini_key_in_quota_esaurita("chiave-2", "modello-x")
    assert gs._gemini_modello_escluso("modello-y")
    # nel file non c'e' la key in chiaro
    db.chiudi()
    assert b"chiave-segreta-1" not in open(db.DB_FILE, "rb").read()


def test_cooldown_scaduto_o_key_rimossa_non_si_ripristinano(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1"])
    db.salva_quota_gemini("k1", "m", time.time() - 10)           # scaduto
    db.salva_quota_gemini("k-vecchia", "m", time.time() + 999)   # key non piu' configurata
    quote, esclusi = db.carica_stato_gemini(["k1"])
    assert quote == {} and esclusi == {}




