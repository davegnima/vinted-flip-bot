"""Radar fase 0: smistamento, classificazione per modulo e filtro di livello 1 (logica pura)."""
import asyncio

from bot import radar


def test_messaggio_radar_dal_marcatore():
    assert radar.e_messaggio_radar("📡\n🆕 Lampada Artemide\n💶 45 EUR")
    assert radar.e_messaggio_radar("  📡 Lampada Artemide")
    assert not radar.e_messaggio_radar("🆕 Giacca Max Mara\n💶 45 EUR")
    assert radar.togli_marcatore("📡 🆕 Lampada") == "🆕 Lampada"
    assert radar.togli_marcatore("🆕 Giacca") == "🆕 Giacca"


def test_messaggio_radar_dalla_chat(monkeypatch):
    monkeypatch.setattr(radar, "RADAR_CHAT_IDS", {-200})
    assert radar.e_messaggio_radar("🆕 Lampada", chat_id=-200)
    assert not radar.e_messaggio_radar("🆕 Lampada", chat_id=-100)


def test_classifica_brand_vince_sulla_parola():
    assert radar.classifica_radar("Lampada Artemide Tolomeo") == ("illuminazione_design", "artemide", "brand")
    assert radar.classifica_radar("Occhiali da sole", "Persol") == ("occhiali", "persol", "brand")
    assert radar.classifica_radar("Cuffie Bang & Olufsen H6")[0:2] == ("audio", "bang & olufsen")
    assert radar.classifica_radar("Putter Scotty Cameron Newport")[0] == "golf"


def test_classifica_generico_e_fuori_radar():
    assert radar.classifica_radar("Vecchia lampada da tavolo") == ("illuminazione_design", None, "generico")
    assert radar.classifica_radar("Giacca in lana") == (None, None, "fuori_radar")


def test_filtro_livello1():
    assert radar.filtro_livello1("Lampada Artemide", 40, "illuminazione_design") == (True, "ok")
    assert radar.filtro_livello1("Lampada Artemide rotta", 40, "illuminazione_design")[1] == "parola_vietata:rotta"
    assert radar.filtro_livello1("Game Boy non funziona", 20, "console_retro")[1] == "parola_vietata:non_funziona"
    assert radar.filtro_livello1("Lampada stile Atollo", 40, "illuminazione_design")[1] == "parola_vietata:stile"
    assert radar.filtro_livello1("Lampada Artemide", 900, "illuminazione_design")[1].startswith("prezzo_sopra_tetto")
    assert radar.filtro_livello1("Lampada Artemide", None, "illuminazione_design") == (False, "prezzo_mancante")
    assert radar.filtro_livello1("Giacca", 10, None) == (False, "fuori_radar")
    assert radar.filtro_livello1("Minifigure LEGO", 5, "lego")[1].startswith("prezzo_sotto_minimo")


def test_negazione_annulla_parola_vietata():
    assert radar.parola_vietata("Set LEGO completo, nessun pezzo mancante") is None
    assert radar.parola_vietata("LEGO 10179 mancano 3 pezzi") == "mancano"
    assert radar.parola_vietata("Console non funzionante") == "non funzionante"


def test_campione_scarti_deterministico(monkeypatch):
    monkeypatch.setattr(radar, "RADAR_CAMPIONE_SCARTI_OGNI", 10)
    assert radar.nel_campione_scarti("1234567890")
    assert not radar.nel_campione_scarti("1234567891")
    monkeypatch.setattr(radar, "RADAR_CAMPIONE_SCARTI_OGNI", 0)
    assert not radar.nel_campione_scarti("1234567890")


def test_scartato_non_visita_la_pagina(monkeypatch):
    visitate = []

    async def finto_scrape(url, includi_guardaroba=True):
        visitate.append(url)
        return {}

    monkeypatch.setattr(radar, "scrape_vinted_listing", finto_scrape)
    parsed = {"title": "Lampada Artemide rotta", "price": "30", "brand": None}
    asyncio.run(radar.gestisci_annuncio_radar(parsed, "https://www.vinted.it/items/1234567891-lampada"))
    assert visitate == []


def test_promosso_visita_la_pagina_una_volta(monkeypatch):
    visitate = []

    async def finto_scrape(url, includi_guardaroba=True):
        visitate.append((url, includi_guardaroba))
        return {"photo_urls": ["a", "b"], "description": "Funziona perfettamente", "catalog_id": "1234",
                "stato_vendita": "venduto"}

    monkeypatch.setattr(radar, "scrape_vinted_listing", finto_scrape)
    parsed = {"title": "Lampada Artemide Tolomeo", "price": "45", "brand": None}
    url = "https://www.vinted.it/items/2234567891-tolomeo"
    asyncio.run(radar.gestisci_annuncio_radar(parsed, url))
    asyncio.run(radar.gestisci_annuncio_radar(parsed, url))
    assert visitate == [(url, False)]


def test_risolvi_gruppo_per_nome(monkeypatch):
    class Dialogo:
        def __init__(self, name, id):
            self.name, self.id = name, id

    class Client:
        async def iter_dialogs(self):
            for d in (Dialogo("Moda", -100), Dialogo("Radar grezzo", -300)):
                yield d

    monkeypatch.setattr(radar, "RADAR_CHAT_IDS", set())
    assert asyncio.run(radar.risolvi_gruppo_radar(Client())) == -300
    assert radar.e_messaggio_radar("🆕 Lampada", chat_id=-300)


def test_radar_in_pausa_di_notte_ora_italiana(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from bot import radar
    monkeypatch.setattr(radar, "RADAR_PAUSA_DA", "23")
    monkeypatch.setattr(radar, "RADAR_PAUSA_A", "6")

    def alle(h):
        return datetime(2026, 10, 7, h, 30, tzinfo=ZoneInfo("Europe/Rome"))

    assert radar.radar_in_pausa(alle(23)) and radar.radar_in_pausa(alle(0)) and radar.radar_in_pausa(alle(5))
    assert not radar.radar_in_pausa(alle(6)) and not radar.radar_in_pausa(alle(22)) and not radar.radar_in_pausa(alle(12))
    monkeypatch.setattr(radar, "RADAR_PAUSA_DA", "")
    assert not radar.radar_in_pausa(alle(2))
