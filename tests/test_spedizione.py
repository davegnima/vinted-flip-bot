"""Costo di spedizione verso l'Italia (01/11): stati, classi di taglia, lettura pagina, esempio dell'utente."""
from bot import radar
from bot.config import SPEDIZIONE_STIMATA_EUR
from bot.radar_matrice import costo_acquisto, margine_roi
from bot.spedizione import (ESTIMATED, UNKNOWN, VERIFIED, campi_spedizione_da_html, classe_taglia, costo_spedizione, paese_da_html)


def test_semi_dell_utente():
    assert costo_spedizione("Francia", "piccolo") == (5.0, ESTIMATED)
    assert costo_spedizione("francia", "ingombrante") == (20.0, ESTIMATED)
    assert costo_spedizione("Italia", "piccolo") == (SPEDIZIONE_STIMATA_EUR, ESTIMATED)


def test_cella_vuota_o_paese_ignoto_e_unknown():
    assert costo_spedizione("Germania", "medio") == (SPEDIZIONE_STIMATA_EUR, UNKNOWN)
    assert costo_spedizione("Francia", "medio") == (SPEDIZIONE_STIMATA_EUR, UNKNOWN)
    assert costo_spedizione(None, "piccolo") == (SPEDIZIONE_STIMATA_EUR, UNKNOWN)


def test_costo_letto_dalla_pagina_e_verified():
    assert costo_spedizione("Germania", "medio", letto=19) == (19.0, VERIFIED)


def test_tariffe_da_variabile(monkeypatch):
    monkeypatch.setenv("SPEDIZIONE_TARIFFE", '{"Germania": {"medio": 9}}')
    assert costo_spedizione("germania", "medio") == (9.0, ESTIMATED)
    monkeypatch.setenv("SPEDIZIONE_TARIFFE", "non json")
    assert costo_spedizione("Francia", "piccolo") == (5.0, ESTIMATED)


def test_classe_taglia():
    assert classe_taglia("Dyson aspirapolvere V11") == "ingombrante"
    assert classe_taglia("Skylanders Swap Force gioco Wii") == "piccolo"
    assert classe_taglia("Nintendo Switch OLED") == "medio"


def test_esempio_utente_10_19_2():
    # prezzo 10 + spedizione 19 + protezione: costo totale e margine su rivendita 90 (protezione = 5% + 0,70 EUR)
    costo = costo_acquisto(10, 19)
    assert round(costo, 2) == 30.2
    marg, roi = margine_roi(10, 90, 19)
    assert marg > 0 and roi > 0
    # con la spedizione fissa di prima lo stesso annuncio appariva piu' redditizio
    assert margine_roi(10, 90, SPEDIZIONE_STIMATA_EUR)[0] > marg


def test_lettura_pagina():
    html = '..."country_title_local":"Germania",..."shipping_price":"4,99","delivery_type":"home"...'
    assert paese_da_html(html) == "Germania"
    assert paese_da_html("<html></html>") is None
    assert ("shipping_price", "4,99") in campi_spedizione_da_html(html)


def test_riga_costo_totale():
    riga = radar._riga_costo_totale({"costo_totale": 31.0, "spedizione_eur": 19.0, "spedizione_stato": "ESTIMATED", "paese": "Francia"})
    assert "31.00" in riga and "19.00" in riga and "stimata" in riga and "Francia" in riga
    assert radar._riga_costo_totale({}) == ""


def test_altri_paesi_usano_la_francia():
    from bot.spedizione import costo_spedizione, ESTIMATED, UNKNOWN
    assert costo_spedizione("germania", "piccolo") == (5.0, ESTIMATED)
    assert costo_spedizione("spagna", "ingombrante") == (20.0, ESTIMATED)
    assert costo_spedizione("germania", "medio")[1] == UNKNOWN
    assert costo_spedizione(None, "piccolo")[1] == UNKNOWN
