"""Controllo Gemini sui gialli e verdi del radar (01/11): risposta, righe del messaggio, scarto, ripiego senza Gemini, tetto orario."""
import asyncio
import json

from bot import radar, radar_gemini as rg

OK = {"oggetto": "Nintendo Switch OLED", "corrisponde_al_titolo": "si", "funzionante": "si", "completo": "si", "danni_visibili": "nessuno",
      "autenticita": "probabile", "verdetto": "conferma", "motivo": "console completa con dock", "confidenza": 0.9,
      "rivendita_eur": 0, "rivendita_confidenza": 0, "rivendita_base": ""}


def test_leggi_risposta():
    assert rg.leggi_risposta(json.dumps(OK))["verdetto"] == "conferma"
    assert rg.leggi_risposta("[ERRORE: quota]") is None
    assert rg.leggi_risposta("non json") is None
    assert rg.leggi_risposta(json.dumps({**OK, "verdetto": "boh"})) is None
    assert rg.leggi_risposta(json.dumps({**OK, "confidenza": 7}))["confidenza"] == 1.0
    assert rg.leggi_risposta(json.dumps({**OK, "confidenza": "x"}))["confidenza"] is None


def test_righe():
    assert rg.riga_gemini(None).startswith("Gemini: non disponibile")
    assert rg.riga_gemini(OK) == "Gemini foto: confermato (confidenza 0,90), console completa con dock"
    assert "da rivedere" in rg.riga_gemini({**OK, "verdetto": "dubbio"})


def test_stima_rivendita_gemini():
    d = rg.leggi_risposta(json.dumps({**OK, "rivendita_eur": 110, "rivendita_confidenza": 0.7, "rivendita_base": "OLED usata tipica 100-120"}))
    assert d["rivendita_eur"] == 110 and d["rivendita_confidenza"] == 0.7
    riga = rg.riga_gemini(d)
    assert "Stima Gemini della rivendita: circa 110 €" in riga and "confidenza 0,70" in riga and "OLED usata tipica" in riga
    # 0 o testo = modello sconosciuto: nessuna stima mostrata
    assert rg.leggi_risposta(json.dumps(OK))["rivendita_eur"] is None
    assert "Stima Gemini" not in rg.riga_gemini(rg.leggi_risposta(json.dumps(OK)))
    assert rg.leggi_risposta(json.dumps({**OK, "rivendita_eur": "x"}))["rivendita_eur"] is None


def test_foto_fino_a_dieci():
    assert rg.RADAR_GEMINI_FOTO == 10


def test_testo_utente():
    t = rg.testo_utente("Switch", 40.0, "ok", "Buone")
    assert "Prezzo richiesto: 40 EUR" in t and "Condizione dichiarata: Buone" in t and "ok" in t
    assert "(vuota)" in rg.testo_utente("x", None, None)


def test_tetto_orario(monkeypatch):
    monkeypatch.setattr(rg, "RADAR_GEMINI_MAX_ORA", 2)
    rg._chiamate[:] = [100.0, 200.0]
    assert rg._entro_il_tetto(adesso=300.0) is False
    assert rg._entro_il_tetto(adesso=4000.0) is True   # le chiamate piu' vecchie di 1 h escono dalla finestra
    rg._chiamate.clear()


def _prova(monkeypatch, risposta, verdetto_v2=None):
    inviati = []

    async def finto_invia(testo, foto, suono=False, ricerca=None, url=None):
        inviati.append((testo, suono))
        return True

    async def finta_controlla(*a, **k):
        return risposta

    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", False)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    monkeypatch.setattr(radar, "radar_in_pausa", lambda *a, **k: False)
    monkeypatch.setattr(radar, "controlla_gemini", finta_controlla)
    radar._radar_inviati.clear()
    esito = asyncio.run(radar.invia_verdetto_v2({"title": "Switch oled", "price": "40"}, "https://www.vinted.it/items/777-x", verdetto_v2 or {"semaforo": "verde"}))
    return esito, inviati


def test_scartato_da_gemini_non_parte(monkeypatch):
    esito, inviati = _prova(monkeypatch, {**OK, "verdetto": "scarta", "motivo": "solo scatola"})
    assert esito is False and inviati == []


def test_confermato_parte_con_suono_e_riga(monkeypatch):
    esito, inviati = _prova(monkeypatch, OK)
    assert esito is True and inviati[0][1] is True and "Gemini foto: confermato" in inviati[0][0]


def test_dubbio_parte_muto(monkeypatch):
    esito, inviati = _prova(monkeypatch, {**OK, "verdetto": "dubbio", "motivo": "foto poco chiare"})
    assert esito is True and inviati[0][1] is False and "da rivedere" in inviati[0][0]


def test_senza_gemini_parte_e_lo_dichiara(monkeypatch):
    esito, inviati = _prova(monkeypatch, None)
    assert esito is True and inviati[0][1] is True and "Gemini: non disponibile" in inviati[0][0]


def test_controlla_non_solleva(monkeypatch):
    async def pagina(url, foto):
        return [b"x"], "desc", "Buone"

    async def gemini(*a, **k):
        return json.dumps(OK), 0.0, 0

    monkeypatch.setattr(rg, "_foto_pagina", pagina)
    monkeypatch.setattr(rg, "chiama_gemini", gemini)
    monkeypatch.setattr(rg, "RADAR_GEMINI", True)
    rg._chiamate.clear()
    assert asyncio.run(rg.controlla("Switch", 40.0, "https://x", None, "1"))["verdetto"] == "conferma"

    async def rotto(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rg, "chiama_gemini", rotto)
    assert asyncio.run(rg.controlla("Switch", 40.0, "https://x", None, "1")) is None
    monkeypatch.setattr(rg, "RADAR_GEMINI", False)
    assert asyncio.run(rg.controlla("Switch", 40.0, "https://x", None, "1")) is None
    rg._chiamate.clear()


def test_testo_avviso_a_blocchi():
    v2 = {"semaforo": "verde", "rivendita": 110, "margine": 53.8, "roi": 119, "n": 13, "costo_totale": 47.1, "spedizione_eur": 2.5,
          "spedizione_stato": "ESTIMATED", "paese": "Italia", "richiesto_mediano": 130, "vendita_rapida": 95,
          "qualita": {"punteggio": 72, "fascia": "media", "n": 13}, "jev": "affare_vero", "jev_conf": 0.9,
          "link_comps": [("t", 100.0, "https://www.vinted.it/items/1-a")]}
    g = {**OK, "rivendita_eur": 105, "rivendita_confidenza": 0.7, "rivendita_base": "usata tipica"}
    t = radar.testo_avviso_v2({"title": "Switch_oled 64GB", "price": "40"}, "https://www.vinted.it/items/777-x", v2, g)
    righe = t.split("\n")
    assert righe[0].endswith("rivendita ~*110 €*") and "*40 €*" in righe[0]
    assert "Switch\\_oled" in righe[1]          # il trattino basso non rompe il Markdown
    assert any(r.startswith("💶 Margine *53.8 €*") for r in righe)
    assert any(r.startswith("📦 Costo totale") for r in righe) and any(r.startswith("📊") for r in righe)
    assert any(r.startswith("🧠 Jev") for r in righe) and any(r.startswith("👁 Gemini foto") for r in righe)
    assert any(r.startswith("💡 Stima Gemini") for r in righe)
    assert righe[-1] == "https://www.vinted.it/items/777-x" and righe[-2] == ""


def test_velocita_e_ricerca_modello():
    d = rg.leggi_risposta(json.dumps({**OK, "velocita_rivendita": "ore", "velocita_base": "molto richiesta", "ricerca_modello": "  Nintendo Switch OLED ",
                                      "ricerca_semantica": "Nintendo Switch console"}))
    assert d["velocita_rivendita"] == "ore" and d["ricerca_modello"] == "nintendo switch oled" and d["ricerca_semantica"] == "nintendo switch console"
    riga = rg.riga_gemini(d)
    assert "Velocità di rivendita stimata da Gemini: entro 24 ore (stima): molto richiesta" in riga
    # valore fuori elenco o assente: nessuna velocita'
    assert rg.leggi_risposta(json.dumps({**OK, "velocita_rivendita": "boh"}))["velocita_rivendita"] is None
    assert "Velocità" not in rg.riga_gemini(rg.leggi_risposta(json.dumps(OK)))
