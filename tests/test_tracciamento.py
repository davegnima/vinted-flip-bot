import asyncio

import httpx
import pytest

import main_telethon as m
from bot import tracciamento as tr


ATTIVO = {"is_reserved": "false", "can_buy": "true"}
VENDUTO = {"can_buy": "false", "barra_venduto": True}


@pytest.mark.parametrize("http,segnali,atteso", [
    (200, ATTIVO, "attivo"),
    (200, VENDUTO, "venduto"),
    (200, {"is_reserved": "true", "can_buy": "false"}, "prenotato"),
    (404, {}, "rimosso"),
    (410, {}, "rimosso"),
    (None, {}, "n.d."),                      # nessuna risposta: sconosciuto
    (200, {}, "rimosso?"),                  # 200 senza dati: cancellato o in revisione, non un invenduto
    (200, {"can_buy": "true", "barra_venduto": True}, "attivo"),  # la barra di un altro articolo non conta
    (200, {"is_closed": "true"}, "venduto"),
    (500, {}, "n.d."),
])
def test_stato(http, segnali, atteso):
    assert m._tracc_stato(http, segnali) == atteso


def test_fasce_e_classi():
    assert [m._tracc_bucket(o) for o in (2, 15, 16, 31, 61, 301, 901, 3600, 3601)] == [
        "<=15s", "<=15s", "<=30s", "<=1min", "<=5min", "<=15min", "<=60min", "<=60min", ">60min"]
    assert [m._tracc_classe(o, "venduto") for o in (15, 300, 301, 900, 901)] == [
        "AFFARE", "AFFARE", "MEDIO AFFARE", "MEDIO AFFARE", "NORMALE"]
    assert m._tracc_classe(3600, "attivo") == "NON AFFARE"
    assert m._tracc_classe(300, "attivo") is None
    # senza dati o senza risposta a 60 minuti NON e' un invenduto
    assert m._tracc_classe(3600, "rimosso?") is None and m._tracc_classe(3600, "n.d.") is None


def test_segnali_sul_formato_reale_con_virgolette_escapate():
    html = '<div class="web_ui__Cell__body">Venduto</div> \\"can_buy\\":false \\"price\\":{\\"amount\\":\\"25\\"}'
    segnali, prezzo = m._tracc_estrai_segnali(html)
    assert segnali == {"can_buy": "false", "barra_venduto": True} and prezzo == 25.0


def test_timestamp_candidati_ignora_vecchi_e_id():
    import time
    ora = int(time.time())
    html = f'{{"a":{ora - 3600},"vecchio":"{ora - 86400 * 400}","id":12345678901,"iso":"2026-10-02T16:54:01Z"}}'
    trovati = m.trova_timestamp_candidati(html, giorni=3650)
    valori = [t.split(" -> ")[1].split(" = ")[0] for t in trovati]  # il valore trovato, senza il contesto
    assert str(ora - 3600) in valori and "12345678901" not in valori
    assert str(ora - 86400 * 400) in valori  # con giorni=3650 anche il vecchio e' ammesso
    assert m.trova_timestamp_candidati(html, giorni=45) and str(ora - 86400 * 400) not in [
        t.split(" -> ")[1].split(" = ")[0] for t in m.trova_timestamp_candidati(html, giorni=45)]


def test_serie_si_ferma_alla_vendita_e_salta_gli_scartati(monkeypatch):
    monkeypatch.setattr(tr, "TRACCIAMENTO_SERIE_SECONDI", (0.01, 0.02, 0.03))
    chiamate = []

    async def pagina(url, max_retries=1):
        chiamate.append(url)
        return 200, ('<div>Venduto</div> \\"can_buy\\":false' if "/10-" in url else '\\"can_buy\\":true')

    monkeypatch.setattr(tr, "_tracc_leggi_pagina", pagina)
    m._tracc_stop.clear()

    async def prova():
        import time
        t0 = time.time()
        for item in ("10", "20"):
            asyncio.get_running_loop().create_task(
                m._tracc_serie(item, f"https://www.vinted.it/items/{item}-x", "X", 20.0, t0))
        m._tracc_stop.add("30")  # scartato prima del verdetto
        asyncio.get_running_loop().create_task(m._tracc_serie("30", "https://www.vinted.it/items/30-x", "X", 20.0, t0))
        await asyncio.sleep(0.3)

    asyncio.run(prova())
    per_item = {i: sum(1 for c in chiamate if f"/{i}-" in c) for i in ("10", "20", "30")}
    assert per_item["30"] == 0 and per_item["20"] == 3 and per_item["10"] == 1


def test_preferiti_dalla_pagina():
    from bot.tracciamento import _tracc_estrai_segnali
    html = 'x \\"favourite_count\\":7,\\"view_count\\":132, "is_closed":false'
    segnali, _ = _tracc_estrai_segnali(html)
    assert segnali["preferiti"] == 7
    segnali2, _ = _tracc_estrai_segnali('"favorite_count": 0')
    assert segnali2["preferiti"] == 0
    segnali3, _ = _tracc_estrai_segnali("<html></html>")
    assert "preferiti" not in segnali3


def test_scartati_falsi_si_seguono_ridotti_gli_altri_si_fermano():
    li = {"url": "https://www.vinted.it/items/10250000001-prada", "brand": "Prada"}
    li2 = {"url": "https://www.vinted.it/items/10250000002-prada", "brand": "Prada"}
    li3 = {"url": "https://www.vinted.it/items/10250000003-prada", "brand": "Prada"}
    tr._log_esito(li, "SKIP_PRE_CERVELLO", motivo="[FALSO CONCLAMATO] etichetta")
    tr._log_esito(li2, "SKIP_PRE_CERVELLO", motivo="[NESSUNA ETICHETTA VISIBILE] x")
    tr._log_esito(li3, "ERRORE_CERVELLO")
    assert "10250000001" in tr._tracc_ridotti and "10250000001" not in tr._tracc_stop
    assert "10250000002" in tr._tracc_stop
    assert "10250000003" not in tr._tracc_stop and "10250000003" not in tr._tracc_ridotti


def test_annuncio_sparito_si_segue_e_se_riappare_si_logga(monkeypatch, caplog):
    import logging
    import time
    risposte = iter([(200, "<html></html>"), (404, ""), (200, "\\\"can_buy\\\":true \\\"price\\\":{\\\"amount\\\":\\\"25\\\"}")])

    async def finta(url, max_retries=1):
        return next(risposte)

    monkeypatch.setattr(tr, "_tracc_leggi_pagina", finta)
    monkeypatch.setattr(tr, "TRACCIAMENTO_SERIE_SECONDI", (0, 0, 0))
    monkeypatch.setattr(tr, "_tracc_scrivi", lambda r: None)
    tr._tracc_stop.discard("10259999999")
    with caplog.at_level(logging.INFO):
        asyncio.run(tr._tracc_serie("10259999999", "https://www.vinted.it/items/10259999999-x", "Prada", 25.0, time.time()))
    testo = caplog.text
    assert "stato=rimosso? |" in testo and "stato=rimosso |" in testo
    assert "RICONTROLLO RIAPPARSO" in testo
    assert "RICONTROLLO STORIA" in testo and "rimosso?" in testo
    assert "10259999999" not in tr._tracc_stop   # mai venduto: la serie e' arrivata in fondo
