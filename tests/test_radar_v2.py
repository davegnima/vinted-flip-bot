import asyncio

from bot import radar_v2


def test_url_comparabili_codifica_il_testo():
    assert radar_v2.url_comparabili("set posate") == "https://www.vinted.it/catalog?search_text=set%20posate&order=newest_first"


def test_tetto_giornaliero(monkeypatch):
    monkeypatch.setattr(radar_v2, "RADAR_V2_MAX_GIORNO", 2)
    radar_v2._conteggio.update(giorno=None, n=0)
    assert radar_v2._entro_il_tetto(1000) and radar_v2._entro_il_tetto(1000)
    assert not radar_v2._entro_il_tetto(1000)
    assert radar_v2._entro_il_tetto(1000 + 86400)


def test_ombra_registra_verdetto(monkeypatch):
    eventi = []
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", True)
    monkeypatch.setattr(radar_v2, "radar_in_pausa", lambda: False)
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: eventi.append(a))
    radar_v2._visti.clear(); radar_v2._cache.clear(); radar_v2._conteggio.update(giorno=None, n=0)
    righe = "\n".join(f"- Set posate argentate — €{p}" for p in (70, 72, 75, 78, 80, 82, 85, 88, 90, 95))

    async def finto(url):
        return righe, True, {}
    monkeypatch.setattr(radar_v2, "_cerca_vinted_testo_diretto", finto)
    parsed = {"title": "Set posate Christofle", "price": "7", "brand": "Christofle"}
    asyncio.run(radar_v2.analizza(parsed, "https://www.vinted.it/items/123456-set"))
    assert len(eventi) == 1
    dati = eventi[0][3]
    assert dati["ok"] is True and dati["margine"] >= 50 and dati["n_usati"] == 10


def test_ombra_spento_non_fa_nulla(monkeypatch):
    eventi = []
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", False)
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: eventi.append(a))
    asyncio.run(radar_v2.analizza({"title": "x", "price": "5"}, "https://www.vinted.it/items/1-x"))
    assert eventi == []


def test_righe_v2_e_filtro_solo_verdi(monkeypatch):
    from bot import radar
    v2 = {"semaforo": "verde", "rivendita": 80, "margine": 60, "roi": 150, "n": 7, "jev": "affare_vero", "jev_conf": 0.9}
    assert radar._righe_v2(v2) == [
        "Comparabili: 7 trovati · rivendita 80 € · margine 60 € · ROI 150%",
        "Semaforo: 🟢 verde",
        "Jev: affare_vero (confidenza 0.9)",
    ]
    assert radar._righe_v2(None) == ["Comparabili: non calcolati", "Semaforo: non calcolato"]
    assert radar.pallino_semaforo(v2) == "🟢" and radar.pallino_semaforo(None) == "🔎"
    monkeypatch.setattr(radar, "RADAR_SOLO_VERDI", True)
    assert radar._da_mandare(v2) is True
    assert radar._da_mandare({"semaforo": "giallo"}) is False
    assert radar._da_mandare(None) is False
    monkeypatch.setattr(radar, "RADAR_SOLO_VERDI", False)
    assert radar._da_mandare(None) is True


def test_jev_senza_chiave_non_chiama_nulla(monkeypatch):
    from bot import jev
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert jev.giudica("x", 10, [20], 30) == (None, None)


def test_righe_v2_mostra_sempre_il_motivo():
    from bot import radar
    riga = radar._righe_v2({"semaforo": "rosso", "rivendita": None, "n": 1, "motivo": "pochi_comparabili"})
    assert riga == [
        "Comparabili: 1 trovati, nessuna stima (pochi comparabili)",
        "Semaforo: 🔴 rosso, pochi comparabili",
    ]
    assert radar._righe_v2({"semaforo": "rosso", "rivendita": None, "n": 0, "motivo": "titolo_generico"})[0] == \
        "Comparabili: 0 trovati, nessuna stima (titolo troppo generico)"
    from bot.radar_v2 import _rosso
    assert _rosso("parola_vietata:x")["semaforo"] == "rosso"


def test_campione_pagina_vinted_conta_i_marcatori():
    from bot.comps_filtri import campione_pagina_vinted
    html = '<a href="/items/123-x"><img alt="Canon AE-1 — €40"></a>' * 2
    c = campione_pagina_vinted(html)
    assert c["marcatori"]["/items/"] == 2 and c["marcatori"]['alt="'] == 2
    assert "/items/123-x" in c["tratto"]


def test_url_comparabili_filtra_per_categoria():
    from bot.radar_v2 import url_comparabili
    assert "catalog[]=3061" in url_comparabili("ricoh r1", 3061)
    assert "catalog[]" not in url_comparabili("ricoh r1")


def test_url_comparabili_con_marchio_e_categoria():
    from bot.radar_v2 import url_comparabili, id_marchio
    assert id_marchio("Dyson") == 291992
    u = url_comparabili("dyson airwrap", 3767, "Dyson")
    assert "brand_ids[]=291992" in u and "catalog[]=3767" in u
    assert "brand_ids" not in url_comparabili("ricoh r1", 3061, "Ricoh")


def test_annuncio_fuori_matrice_ha_intestazione_chiara(monkeypatch):
    import asyncio
    from bot import radar
    inviati = []

    async def finto_invia(testo, foto):
        inviati.append(testo)

    monkeypatch.setattr(radar, "RADAR_SOLO_VERDI", False)
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    asyncio.run(radar._manda_annuncio_senza_modello("1", "Psp portatile", 30.0, "https://www.vinted.it/items/1", None, None))
    assert inviati[0].startswith("🔎 fuori matrice | 30 €\nPsp portatile")


QUERY_URL = "https://www.vinted.it/catalog?search_text=ps5%20slim&catalog[]=3025&price_to=150&currency=EUR&order=newest_first"


def test_testo_e_url_senza_prezzo():
    assert radar_v2.testo_ricerca(QUERY_URL) == "ps5 slim"
    assert radar_v2.testo_ricerca("https://www.vinted.it/catalog?brand_ids[]=1") == ""
    u = radar_v2.url_senza_prezzo(QUERY_URL + "&price_from=5&page=2")
    assert "price_to" not in u and "price_from" not in u and "page=" not in u and "ps5" in u and "3025" in u


def test_prefiltro_scarta_sopra_il_riferimento_senza_comparabili(monkeypatch):
    eventi, urls = [], []
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", True)
    monkeypatch.setattr(radar_v2, "RADAR_SPESA_MAX", 500)
    monkeypatch.setattr(radar_v2, "radar_in_pausa", lambda: False)
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: eventi.append(a))
    radar_v2._visti.clear(); radar_v2._cache.clear(); radar_v2._riferimenti.clear(); radar_v2._conteggio.update(giorno=None, n=0)
    righe = "\n".join(f"- PlayStation 5 slim — €{p}" for p in (300, 310, 320, 330, 340, 350, 360, 370))

    async def finto(url):
        urls.append(url)
        return righe, True, {}
    monkeypatch.setattr(radar_v2, "_cerca_vinted_testo_diretto", finto)
    parsed = {"title": "PlayStation 5 slim", "price": "290", "brand": "Sony", "query_name": "V2 ps5"}
    v = asyncio.run(radar_v2.analizza(parsed, "https://www.vinted.it/items/777001-ps5", query_url=QUERY_URL))
    assert v["semaforo"] == "rosso" and v["motivo"] == "sopra_riferimento"
    assert len(urls) == 1 and "price_to" not in urls[0]  # solo la ricerca di riferimento, nessuna pagina ne' comparabili in piu'
    # un secondo annuncio della stessa ricerca usa la cache: zero richieste
    parsed2 = {"title": "PlayStation 5 slim", "price": "280", "brand": "Sony", "query_name": "V2 ps5"}
    asyncio.run(radar_v2.analizza(parsed2, "https://www.vinted.it/items/777002-ps5", query_url=QUERY_URL))
    assert len(urls) == 1


def test_pezzi_non_funzionanti():
    from bot.valore_mercato import e_un_pezzo
    assert e_un_pezzo("Playstation 5 non funzionante") and e_un_pezzo("iPhone bloccato icloud")
    assert e_un_pezzo("Switch OLED completa con box") is None


def test_accessori_e_scatole_sono_pezzi():
    from bot.valore_mercato import e_un_pezzo
    for t in ("Aufbewahrungstasche Nintendo 3DS", "DJI Air 3s ND filters Freewell", "Scatola Xbox series X",
              "Lot de 2 supports de bureau pour Sonos One", "Ventilador xbox series x", "PokeBall Nintendo Switch, 8 cartucce",
              "Switch 2 Zelda Edition Verpackung (keine Konsole!)"):
        assert e_un_pezzo(t), t
    for t in ("Nintendo Switch OLED con accessori", "Switch in scatola originale", "Canon EF 50mm obiettivo", "Olympus Mju 1"):
        assert e_un_pezzo(t) is None, t


def test_prezzo_segnaposto_e_rosso(monkeypatch):
    eventi = []
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", True)
    monkeypatch.setattr(radar_v2, "radar_in_pausa", lambda: False)
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: eventi.append(a))
    r = asyncio.run(radar_v2.analizza({"title": "Bugaboo Fox 5 Renew 1000€ VB", "price": "1"}, "https://www.vinted.it/items/99001-bugaboo"))
    assert r["semaforo"] == "rosso" and r["motivo"] == "prezzo_segnaposto"


def test_risposta_gruppo_con_stima_e_senza():
    from bot import radar
    v2 = {"semaforo": "verde", "rivendita": 80, "margine": 60, "roi": 150, "n": 7}
    assert radar.testo_risposta_gruppo(v2) == "🟢 verde · rivendita stimata 80 € · margine 60 € · ROI 150% · 7 comparabili"
    r = radar.testo_risposta_gruppo({"semaforo": "rosso", "rivendita": None, "n": 1, "motivo": "pochi_comparabili"})
    assert r.startswith("🔴 rosso · nessuna stima (pochi comparabili")
    assert radar.testo_risposta_gruppo(None) == "⚪ semaforo non calcolato"
