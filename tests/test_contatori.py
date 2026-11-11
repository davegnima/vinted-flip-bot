"""Contatori persistenti: sommano tra avvii, non ripartono a ogni deploy."""
import time

from bot import db, proxy


def test_contatori_si_sommano_tra_avvii(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "t.sqlite3"))
    db.chiudi()
    assert db.aggiungi_contatori("2026-11-10", "banda", {"pagina_annuncio|n": 3, "pagina_annuncio|ko": 1})
    assert db.aggiungi_contatori("2026-11-10", "banda", {"pagina_annuncio|n": 2})
    assert db.aggiungi_contatori("2026-11-11", "banda", {"pagina_annuncio|n": 4})
    assert db.leggi_contatori("banda")["pagina_annuncio|n"] == 9
    assert db.leggi_contatori("banda", "2026-11-11")["pagina_annuncio|n"] == 4
    assert db.leggi_contatori("banda")["pagina_annuncio|ko"] == 1
    db.chiudi()


def test_salvataggio_banda_svuota_le_differenze(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "t.sqlite3"))
    db.chiudi()
    proxy._BANDA_DELTA.clear()
    proxy._BANDA_DELTA.update({"foto|n": 5, "foto|rete": 1000})
    proxy._salva_contatori_banda(forza=True)
    assert proxy._BANDA_DELTA == {}
    oggi = time.strftime("%Y-%m-%d", time.gmtime())
    assert db.leggi_contatori("banda", oggi)["foto|n"] == 5
    db.chiudi()


def test_riepilogo_periodo_testo():
    t = proxy._riepilogo_periodo({"pagina_annuncio|n": 10, "pagina_annuncio|rete": 2097152, "pagina_annuncio|ko": 2})
    assert "pagina_annuncio: 10 richieste, 2MB, 403/429 2" in t
    assert proxy._riepilogo_periodo({}) == "nessun dato"
