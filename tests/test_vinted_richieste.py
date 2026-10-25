"""Richieste a Vinted (25/10): categoria dell'annuncio con una sola richiesta; ricerca diretta con due tentativi
e un tetto complessivo sotto i 25 s della fonte."""
import asyncio

from bot import comps, radar_v2


BREADCRUMB = '<a href="/catalog/3025-console-retro?referrer=item-crumbs">Console</a>'


def test_catalogo_da_html_legge_l_ultimo_breadcrumb():
    assert radar_v2._catalogo_da_html(BREADCRUMB) == "3025"
    assert radar_v2._catalogo_da_html("<html></html>") is None


def test_catalogo_annuncio_fa_una_sola_richiesta(monkeypatch):
    chiamate = []

    class _Risposta:
        text = BREADCRUMB

    async def finto_get(url, timeout, max_retries, **kw):
        chiamate.append(max_retries)
        return _Risposta()

    monkeypatch.setattr(radar_v2, "_vinted_get_con_retry", finto_get)
    assert asyncio.run(radar_v2._catalogo_annuncio("https://www.vinted.it/items/1-x")) == "3025"
    assert chiamate == [1]


def test_catalogo_annuncio_senza_risposta_e_none(monkeypatch):
    async def nessuna(url, timeout, max_retries, **kw):
        return None

    monkeypatch.setattr(radar_v2, "_vinted_get_con_retry", nessuna)
    assert asyncio.run(radar_v2._catalogo_annuncio("https://www.vinted.it/items/1-x")) is None


def test_ricerca_diretta_ha_due_tentativi_e_tetto_sotto_la_fonte():
    assert comps.TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_TOTALE_SECONDI < 25
    assert comps.TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_TOTALE_SECONDI >= 2 * comps.TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI
