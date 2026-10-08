import asyncio
import json
import time

import pytest

from bot import db
from bot import tracciamento as tr
from bot import velocita as v


@pytest.fixture(autouse=True)
def db_pulito(tmp_path, monkeypatch):
    db.chiudi()
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "v.sqlite3"))
    yield
    db.chiudi()


TABELLA = {"base": 0.25, "semaforo": {"🟢": 0.50, "🟡": 0.29, "🔴": 0.14},
           "brand": {"loro piana": (10, 8), "max mara": (45, 5), "nuovo": (0, 0)}}


def test_lift_brand_veloce_lento_e_sconosciuto():
    assert v.lift_brand("Loro Piana", TABELLA) > 1.8
    assert v.lift_brand("Max Mara", TABELLA) < 0.6
    assert v.lift_brand("brand mai visto", TABELLA) == pytest.approx(1.0)


def test_semaforo_corretto_sale_per_i_brand_veloci_e_scende_per_i_lenti(monkeypatch):
    monkeypatch.setattr(v, "VELOCITA_ATTIVA", True)
    assert v.semaforo_corretto("🔴", "Loro Piana", TABELLA)[0] == "🟡"       # 0,14 x ~2,1 = 0,29
    assert v.semaforo_corretto("🟡", "Loro Piana", TABELLA)[0] == "🟢"
    assert v.semaforo_corretto("🟢", "Max Mara", TABELLA)[0] == "🟡"        # 0,50 x ~0,56 = 0,28
    assert v.semaforo_corretto("🔴", "Max Mara", TABELLA)[0] == "🔴"
    assert v.semaforo_corretto("🟢", "brand mai visto", TABELLA) == ("🟢", 1.0)
    assert v.semaforo_corretto(None, "Prada", TABELLA) == (None, 1.0)
    monkeypatch.setattr(v, "VELOCITA_ATTIVA", False)
    assert v.semaforo_corretto("🔴", "Loro Piana", TABELLA) == ("🔴", 1.0)


def test_tabella_del_repo_si_carica_e_ha_i_brand():
    d = v.carica_velocita()
    assert d["base"] > 0 and "loro piana" in d["brand"] and "max mara" in d["brand"]
    assert v.carica_velocita("/non/esiste.json")["brand"] == {}


def test_esito_finale_e_fascia_in_ritardo():
    assert tr._prossima_fascia(400) == 900 and tr._prossima_fascia(10) == 15 and tr._prossima_fascia(99999) == 3600
    assert tr._tracc_esito_finale([(15, "attivo"), (300, "venduto")]) == ("venduto", "AFFARE", 300)
    assert tr._tracc_esito_finale([(900, "attivo"), (3600, "attivo")]) == ("attivo", "NON AFFARE", None)
    assert tr._tracc_esito_finale([(900, "attivo"), (3600, "n.d.")]) == ("n.d.", None, None)
    assert tr._tracc_esito_finale([]) == ("-", None, None)


def test_riga_tracciato_ha_tutto():
    riga = tr._riga_tracciato("55", "Prada", 40.0, [(60, "attivo"), (300, "venduto")],
                              {"esito": "COMPRA", "sem": "🟢", "sem_base": "🟡", "brand_n": "prada", "lift": 1.4})
    for pezzo in ("TRACCIATO | item=55", "esito=COMPRA", "sem=🟢", "sem_base=🟡", "brand_n=prada", "classe=AFFARE",
                  "venduto_s=300", "storia=60:attivo,300:venduto", "incompleto=no"):
        assert pezzo in riga


def test_serie_salvata_e_ripresa_dopo_il_riavvio(monkeypatch, caplog):
    import logging
    t0 = time.time() - 400   # il processo e' morto 400 s dopo l'arrivo del messaggio
    db.salva_serie("77", "https://www.vinted.it/items/77-x", "Prada", 30.0, t0, [15, 30, 60, 300, 900, 3600])
    db.aggiorna_serie("77", storia=[(15, "attivo"), (30, "attivo"), (60, "attivo")],
                      ctx={"esito": "TRATTA", "target": 90, "sem": "🟢", "sem_base": "🟢"})
    chiamate = []

    async def pagina(url, max_retries=1):
        chiamate.append(url)
        return 200, '<div>Venduto</div> \\"can_buy\\":false'

    monkeypatch.setattr(tr, "_tracc_leggi_pagina", pagina)
    monkeypatch.setattr(tr, "_tracc_scrivi", lambda r: None)
    tr._tracc_stop.discard("77")

    async def prova():
        n = tr.tracc_riprendi_serie()
        await asyncio.sleep(0.3)
        return n

    with caplog.at_level(logging.INFO):
        assert asyncio.run(prova()) == 1
    assert len(chiamate) == 1    # un solo controllo per gli offset scaduti (300), poi venduto e fine
    assert "RICONTROLLO LAMPO | item=77" in caplog.text and "offset=900s" in caplog.text   # fascia reale (400 s -> 900)
    assert "TRACCIATO | item=77" in caplog.text and "esito=TRATTA" in caplog.text and "classe=MEDIO AFFARE" in caplog.text
    assert db.carica_serie(0) == []    # serie conclusa: tolta dal DB


def test_serie_troppo_vecchia_non_si_riprende():
    db.salva_serie("88", "https://www.vinted.it/items/88-x", "Prada", 30.0, time.time() - 5000, [15, 3600])
    assert tr.tracc_riprendi_serie() == 0


def test_tool_aggiorna_velocita_conta_una_volta_e_decade(tmp_path):
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location(
        "aggiorna_velocita", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "aggiorna_velocita.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    righe = [
        ("2026-10-08T10:00:00Z", "x | PREAVVISO | item=1 | brand='Prada' | prezzo=30 | semaforo=🟢 | fv=100 | margine=70 | conf=alta | regola=no | sem_base=🟡 | brand_n=prada"),
        ("2026-10-08T10:03:00Z", "x | RICONTROLLO LAMPO | item=1 | brand='Prada' | offset=300s | stato=venduto | bucket=<=5min | classe=AFFARE | esito=COMPRA"),
        ("2026-10-08T10:01:00Z", "x | PREAVVISO | item=2 | brand='Max Mara' | prezzo=40 | semaforo=🔴 | fv=50 | margine=10 | conf=alta | regola=no"),
        ("2026-10-08T11:01:00Z", "x | RICONTROLLO LAMPO | item=2 | brand='Max Mara' | offset=3600s | stato=attivo | bucket=- | classe=NON AFFARE | esito=NON COMPRARE"),
        ("2026-10-08T10:02:00Z", "x | PREAVVISO | item=3 | brand='Fendi' | prezzo=40 | semaforo=🔴 | fv=50 | margine=10 | conf=alta | regola=no"),
        ("2026-10-08T11:02:00Z", "x | RICONTROLLO LAMPO | item=3 | brand='Fendi' | offset=3600s | stato=n.d. | bucket=- | classe=- | esito=NON COMPRARE"),
        ("2026-10-08T12:00:00Z", "x | TRACCIATO | item=4 | brand='Loro Piana' | sem=🟡 | sem_base=🟡 | brand_n=loro piana | stato=attivo | classe=NON AFFARE"),
    ]
    annunci = t.costruisci_annunci(righe)
    assert set(annunci) == {"1", "2", "4"}                       # il 3 e' senza risposta: non conta
    assert annunci["1"]["sem"] == "🟡" and annunci["1"]["brand"] == "prada"      # conta il semaforo d'origine
    tab = {}
    assert t.aggiorna(tab, annunci, 1.0, "2026-10-08T13:00:00Z") == 3
    assert tab["brand"]["prada"] == {"n": 1, "veloci": 1} and tab["semaforo"]["🔴"] == {"n": 1, "veloci": 0}
    assert t.aggiorna(tab, annunci, 1.0, "2026-10-08T13:00:00Z") == 0     # niente doppio conteggio
    t.aggiorna(tab, {}, 0.5, "2026-10-08T13:00:00Z")
    assert tab["brand"]["prada"]["n"] == 0.5                              # decadimento
