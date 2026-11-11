"""Storico delle righe strutturate dei log su SQLite."""
import logging

from bot import db, log_db


def test_estrai_riga_solo_strutturate():
    r = log_db.estrai_riga("RADAR GEMINI | item=123 | verdetto=conferma | conf=0.9", 5.0)
    assert r == (5.0, "RADAR GEMINI", "123", "RADAR GEMINI | item=123 | verdetto=conferma | conf=0.9")
    assert log_db.estrai_riga("Avvio del bot, tutto bene") is None
    assert log_db.estrai_riga("ESITO | brand='X' | item=9 | margine=3")[1] == "ESITO"


def test_campi_riga():
    c = log_db.campi_riga("RADAR GEMINI | item=1 | verdetto=scarta | motivo=foto diversa, titolo | 3.4s")
    assert c["verdetto"] == "scarta" and c["motivo"] == "foto diversa, titolo" and "3.4s" not in c


def test_scrittura_e_lettura(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "t.sqlite3"))
    db.chiudi()
    righe = [log_db.estrai_riga("RADAR PRIVATO | item=7 | consegnato=si", 10.0),
             log_db.estrai_riga("RIEPILOGO BANDA | x=1", 20.0)]
    assert log_db._scrivi_lotto(righe)
    out = log_db.leggi_righe("RADAR PRIVATO")
    assert len(out) == 1 and out[0][2] == "7"
    assert len(log_db.leggi_righe(None, 15.0)) == 1
    db.chiudi()


def test_gestore_non_blocca_con_coda_piena(monkeypatch):
    while not log_db._coda.empty():
        log_db._coda.get_nowait()
    monkeypatch.setattr(log_db, "_coda", __import__("queue").Queue(maxsize=1))
    g = log_db.GestoreLogDb()
    for i in range(3):
        g.emit(logging.LogRecord("x", logging.INFO, "f", 1, "ESITO | item=%d" % i, None, None))
    assert log_db._scartate[0] >= 2
