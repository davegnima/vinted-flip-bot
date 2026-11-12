import asyncio
import time
from bot import moda_jev as mj


def test_tetto_raggiunto_ha_messaggio_proprio():
    ris = {"esito": "non_verificato", "motivo": "tetto_giornaliero"}
    assert "tetto giornaliero" in mj.riga_esito_scheda(ris)
    assert "comparabili non trovati" not in mj.riga_esito_scheda(ris)


def test_ombra_non_consuma_il_tetto_giornaliero(monkeypatch):
    monkeypatch.setattr(mj, "MODA_JEV_MAX_GIORNO", 1)
    mj._conteggio.update(giorno=time.strftime("%Y-%m-%d"), n=1)   # tetto gia' pieno
    ris = asyncio.run(mj.verifica({"fair_value": {"brand": "x"}, "price": 10}, [], solo_comparabili=True))
    assert ris["motivo"] != "tetto_giornaliero"
    ris = asyncio.run(mj.verifica({"fair_value": {"brand": "x"}, "price": 10}, []))
    assert ris["motivo"] == "tetto_giornaliero"
