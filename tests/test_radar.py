"""Radar fase 0: smistamento, classificazione per modulo e filtro di livello 1 (logica pura)."""
import asyncio

import pytest

from bot import radar
from bot import radar_matrice as rm


@pytest.fixture(autouse=True)
def _senza_matrice(monkeypatch):
    # i test del livello 1 per modulo non dipendono dai dati reali della matrice ne' dal tetto di spesa
    monkeypatch.setattr(rm, "MATRICE", [])
    monkeypatch.setattr(radar, "RADAR_SPESA_MAX", 0)


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


def test_brand_lista_completa_ed_esclusi():
    assert radar.classifica_radar("Collana Christian Dior vintage")[0:2] == ("bijoux_vintage", "christian dior")
    assert radar.classifica_radar("Hot Toys Iron Man 1/6")[0] == "collezionismo"
    assert radar.classifica_radar("Leica M6")[0] == "fotografia"
    assert radar.filtro_livello1("Bracciale Tiffany argento", 60, "argento_gioielli")[1] == "brand_escluso:tiffany"


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


_RIGHE = [
    {"id": "artemide_tolomeo", "modello": "Tolomeo", "chiavi": ["artemide tolomeo", "tolomeo"],
     "rivendita_veloce_eur": 200, "affidabilita": "alta", "spedizione_eur": 9, "rischio_falsi": 2, "rischio_guasti": 2},
    {"id": "flos_arco", "modello": "Arco", "chiavi": ["arco"], "brand_chiavi": ["flos"],
     "rivendita_veloce_eur": 900, "affidabilita": "media", "spedizione_eur": None, "rischio_falsi": 2},
    {"id": "alessi_plisse", "modello": "Plisse", "chiavi": ["plisse", "plissé"], "sotto_soglia": True},
    {"id": "lego_75192", "modello": "Millennium Falcon", "chiavi": ["75192"],
     "rivendita_veloce_eur": 300, "affidabilita": "bassa", "spedizione_eur": 9},
    {"id": "lego_75313_usato", "chiavi": ["75313"], "rivendita_veloce_eur": 775, "affidabilita": "alta",
     "spedizione_eur": 15},
    {"id": "lego_75313_sigillato", "chiavi": ["75313"], "parole_variante": ["sigillato", "misb"],
     "rivendita_veloce_eur": 940, "affidabilita": "alta", "spedizione_eur": 15},
    {"id": "gb_sola", "chiavi": ["game boy"], "rivendita_veloce_eur": 48, "affidabilita": "alta", "sotto_soglia": True},
    {"id": "gb_scatola", "chiavi": ["game boy scatola"], "rivendita_veloce_eur": 179, "affidabilita": "alta",
     "spedizione_eur": 5},
    {"id": "zelda_scatola", "chiavi": ["zelda link awakening"], "parole_variante": ["scatola", "completo"],
     "rivendita_veloce_eur": 107, "affidabilita": "alta", "spedizione_eur": 5},
    {"id": "new_3ds_xl", "chiavi": ["new 3ds xl"], "parole_escluse": ["giochi", "custodia"],
     "rivendita_veloce_eur": 237, "affidabilita": "alta", "spedizione_eur": 6},
    {"id": "cassina_lc2", "chiavi": ["lc2"], "brand_chiavi": ["cassina"], "escluso": "non_spedibile"},
]


def test_buy_max_rispetta_margine_e_roi():
    bm = rm.buy_max(200, 9, 2, 2)
    assert bm == 76
    margine, roi = rm.margine_roi(bm, 200, 9, 2, 2)
    assert margine >= 50 and roi >= 100
    margine, roi = rm.margine_roi(bm + 3, 200, 9, 2, 2)
    assert roi < 100
    assert rm.buy_max(80, 6) == 14  # a 14 EUR il margine resta >= 50
    assert rm.buy_max(60, 6) == 0
    assert rm.buy_max(200, 9, 4, 4) < bm  # piu' rischio, meno spazio


def test_trova_modello_chiave_e_brand():
    m = rm.prepara(_RIGHE)
    assert rm.trova_modello("Lampada Tolomeo da tavolo", None, m)["id"] == "artemide_tolomeo"
    assert rm.trova_modello("Arco in legno", None, m) is None
    assert rm.trova_modello("Lampada Arco", "Flos", m)["id"] == "flos_arco"
    assert rm.trova_modello("Bollitore Alessi Plissé", None, m)["id"] == "alessi_plisse"
    assert rm.trova_modello("LEGO Star Wars 751920", None, m) is None
    assert rm.trova_modello("LEGO 75313 AT-AT", None, m)["id"] == "lego_75313_usato"
    assert rm.trova_modello("LEGO 75313 nuovo sigillato", None, m)["id"] == "lego_75313_sigillato"
    assert rm.trova_modello("Game Boy classico", None, m)["id"] == "gb_sola"
    assert rm.trova_modello("Game Boy in scatola originale", None, m)["id"] == "gb_scatola"
    assert rm.trova_modello("Custodia new 3DS XL", None, m) is None
    assert rm.trova_modello("New 3DS XL blu", None, m)["id"] == "new_3ds_xl"
    assert rm.valuta_modello("Zelda Link Awakening cartuccia", None, 10, m)[0] == "senza_dati"
    assert rm.valuta_modello("Zelda Link Awakening completo", None, 10, m)[0] == "ok"


def test_livello1_usa_il_buy_max_del_modello():
    m = rm.prepara(_RIGHE)
    assert radar.filtro_livello1("Artemide Tolomeo", 70, "illuminazione_design", matrice=m) == (True, "ok")
    assert radar.filtro_livello1("Artemide Tolomeo", 120, "illuminazione_design", matrice=m) == (False, "sopra_buy_max:76")
    assert radar.filtro_livello1("Alessi Plissé", 30, "ceramiche_oggetti", matrice=m)[1] == "modello_sotto_soglia:alessi_plisse"
    # spedizione assente (ingombrante) -> buy_max calcolato senza spedizione, oltre il tetto del modulo
    assert radar.filtro_livello1("Flos Arco", 350, "illuminazione_design", matrice=m) == (True, "ok")
    # affidabilita' bassa: niente buy_max, decide il tetto del modulo
    assert radar.filtro_livello1("LEGO 75192", 60, "lego", matrice=m) == (True, "ok")
    assert radar.filtro_livello1("Lampada Artemide", 40, "illuminazione_design", matrice=m) == (True, "ok")
    assert radar.filtro_livello1("Cassina LC2 poltrona", 200, "illuminazione_design", matrice=m)[1] == \
        "modello_escluso:non_spedibile"
    # sotto il minimo passa solo un modello noto con buy max: l'errore di prezzo e' l'affare
    assert radar.filtro_livello1("Artemide Tolomeo", 5, "illuminazione_design", matrice=m) == (True, "ok")
    assert radar.filtro_livello1("Lampada Artemide", 5, "illuminazione_design", matrice=m)[1].startswith("prezzo_sotto_minimo")
    assert radar.filtro_livello1("Game Boy classico", 5, "console_retro", matrice=m)[1].startswith("prezzo_sotto_minimo")


def test_matrice_del_repo_valida():
    m = rm.carica_matrice()
    for r in m:
        assert r["_chiavi"] and r.get("id")
        assert r["buy_max"] is None or r["buy_max"] >= 0


def test_matrice_del_repo_casi_reali():
    # titoli veri dei log del 7-8/10 che la prima versione agganciava al modello sbagliato
    m = rm.carica_matrice()
    r = rm.trova_modello("Pokemon colloseum GameCube", None, m)
    assert r is None or "gale_of_darkness" not in r["id"]
    assert rm.trova_modello("Olympus mju II zoom", None, m)["sotto_soglia"]
    assert rm.trova_modello("LEGO 75313 AT-AT", None, m)["id"].startswith("lego_75313")
    # 9/10: giochi e accessori non sono la console; cartuccia sfusa non usa il buy max della riga in scatola
    for titolo in ("Pack accesoires new 3ds xl big ben", "Ma Vie avec mes Petits Amis Nintendo 3ds/XL/NEW -VF",
                   "Jeux Game Boy", "Barbie Game Boy Advance PAL completo"):
        assert rm.valuta_modello(titolo, None, 10, m)[0] != "ok", titolo
    assert rm.valuta_modello("Zelda Link's Awakening Nintendo Game Boy bon etat", None, 11, m)[0] == "senza_dati"
    assert rm.valuta_modello("New Nintendo 3DS XL nera", None, 60, m)[0] == "ok"
    # minifigure con il numero del set non sono il set; modelli nuovi per il tetto di 50 EUR
    assert rm.valuta_modello("Lego figurine Star Wars hoth Rebel Trooper sw0735 75098", None, 20, m)[0] != "ok"
    assert rm.valuta_modello("Lego 8088 Star Wars ARC-170 Starfighter", None, 20, m)[0] == "ok"
    assert rm.trova_modello("Appareil photo Yashica T4 Super", None, m)["id"].startswith("yashica_t4")


def test_spesa_massima_per_pezzo(monkeypatch):
    monkeypatch.setattr(radar, "RADAR_SPESA_MAX", 50)
    m = rm.prepara(_RIGHE)
    assert radar.filtro_livello1("Flos Arco", 350, "illuminazione_design", matrice=m) == (False, "sopra_spesa_max:50")
    assert radar.filtro_livello1("Artemide Tolomeo", 50, "illuminazione_design", matrice=m) == (True, "ok")
