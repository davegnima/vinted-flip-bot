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
        "Jev: affare (confidenza 0.9)",
    ]
    assert radar._righe_v2(None) == ["Comparabili: non calcolati", "Semaforo: non calcolato"]
    assert radar.pallino_semaforo(v2) == "🟢" and radar.pallino_semaforo(None) == "🔎"
    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", False)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde"})
    assert radar._da_mandare(v2) is True
    assert radar._da_mandare({"semaforo": "giallo"}) is False
    assert radar._da_mandare(None) is False
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    assert radar._da_mandare({"semaforo": "giallo"}) is True
    assert radar._da_mandare({"semaforo": "rosso"}) is False
    assert radar._da_mandare(None) is False


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

    async def finto_invia(testo, foto, suono=False, ricerca=None, url=None):
        inviati.append(testo)

    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", False)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    asyncio.run(radar._manda_annuncio_senza_modello("1", "Psp portatile", 30.0, "https://www.vinted.it/items/1", {"semaforo": "giallo"}, None))
    assert inviati[0].startswith("🟡 fuori matrice | 30 €\nPsp portatile")
    inviati.clear()
    asyncio.run(radar._manda_annuncio_senza_modello("2", "Psp rotta", 30.0, "https://www.vinted.it/items/2", {"semaforo": "rosso"}, None))
    asyncio.run(radar._manda_annuncio_senza_modello("3", "Psp", 30.0, "https://www.vinted.it/items/3", None, None))
    assert inviati == []


def test_invia_verdetto_v2_gialli_e_verdi_una_volta(monkeypatch):
    import asyncio
    from bot import radar
    inviati = []

    async def finto_invia(testo, foto, suono=False, ricerca=None, url=None):
        inviati.append((testo, suono))

    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", False)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    monkeypatch.setattr(radar, "radar_in_pausa", lambda *a, **k: False)

    async def senza_gemini(*a, **k):
        return None

    monkeypatch.setattr(radar, "controlla_gemini", senza_gemini)
    radar._radar_inviati.clear()
    p = {"title": "Switch oled", "price": "40"}
    u = "https://www.vinted.it/items/901-switch"
    assert asyncio.run(radar.invia_verdetto_v2(p, u, {"semaforo": "giallo"})) is True
    assert asyncio.run(radar.invia_verdetto_v2(p, u, {"semaforo": "giallo"})) is False
    assert asyncio.run(radar.invia_verdetto_v2(p, "https://www.vinted.it/items/902-x", {"semaforo": "verde"})) is True
    assert asyncio.run(radar.invia_verdetto_v2(p, "https://www.vinted.it/items/903-x", {"semaforo": "rosso"})) is False
    assert [x[1] for x in inviati] == [False, True]
    assert inviati[0][0].startswith("🟡 *40 €*\nSwitch oled")
    # il vecchio ramo non rimanda lo stesso annuncio
    asyncio.run(radar._manda_annuncio_senza_modello("901", "Switch oled", 40.0, u, {"semaforo": "giallo"}, None))
    assert len(inviati) == 2


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
    assert radar.testo_risposta_gruppo(v2).startswith("🟢 verde · rivendita stimata 80 € · margine 60 € · ROI 150% · 7 comparabili")
    assert "Non inviato in COMPRA: Jev non lo da' come affare" in radar.testo_risposta_gruppo(v2)
    ok = {**v2, "jev": "affare_vero", "jev_conf": 0.95, "link_comps": [("t", 90.0, "https://www.vinted.it/items/1")]}
    t = radar.testo_risposta_gruppo(ok)
    assert "Inviato in COMPRA" in t and "• 90 € https://www.vinted.it/items/1" in t
    r = radar.testo_risposta_gruppo({"semaforo": "rosso", "rivendita": None, "n": 1, "motivo": "pochi_comparabili"})
    assert r.startswith("🔴 rosso · nessuna stima (pochi comparabili")
    assert radar.testo_risposta_gruppo(None) == "⚪ semaforo non calcolato"


def test_da_cancellare_solo_i_non_oggetti(monkeypatch):
    from bot import radar
    from bot.radar_v2 import _rosso
    monkeypatch.setattr(radar, "RADAR_CANCELLA_ROSSI", False)
    assert radar.da_cancellare(_rosso("pezzo_o_accessorio:")) and radar.da_cancellare(_rosso("parola_vietata:"))
    assert radar.da_cancellare(_rosso("prezzo_segnaposto")) and radar.da_cancellare(_rosso("titolo_generico"))
    assert not radar.da_cancellare(_rosso("pochi_comparabili")) and not radar.da_cancellare(_rosso("sopra_riferimento", 11))
    assert not radar.da_cancellare(None) and not radar.da_cancellare({"semaforo": "verde", "motivo": "ok"})


def test_da_cancellare_tutti_i_rossi_ma_non_giallo_e_verde(monkeypatch):
    from bot import radar
    from bot.radar_v2 import _rosso
    monkeypatch.setattr(radar, "RADAR_CANCELLA_ROSSI", True)
    assert radar.da_cancellare(_rosso("margine_basso")) and radar.da_cancellare(_rosso("pochi_comparabili"))
    assert radar.da_cancellare(_rosso("sopra_riferimento", 11)) and radar.da_cancellare(_rosso("roi_basso"))
    assert not radar.da_cancellare({"semaforo": "giallo", "motivo": "ok"}) and not radar.da_cancellare({"semaforo": "verde", "motivo": "ok"})


def test_accessori_multilingua_e_parti_passeggino_sono_pezzi():
    from bot.valore_mercato import e_un_pezzo
    for t in ("Kamera-Zubehör Set", "Acessorios drone DJI mini 2", "Garmin Watchständer", "Soporte móvil Bugaboo",
              "Chasis Bugaboo bee 5", "Vestidura cuco Bugaboo Camaleon 3", "Accessoires GoPro Hero 7"):
        assert e_un_pezzo(t), t
    for t in ("Nintendo Switch OLED", "Bugaboo Fox 3 completo", "GoPro Hero 3+ black"):
        assert e_un_pezzo(t) is None, t


def test_scocche_cinturini_e_campane_sono_pezzi():
    from bot.valore_mercato import e_un_pezzo
    for t in ("Scocca Nintendo 3DS XL Pokemon X e Y", "campana de aspiración de polvo para radial",
              "Bracelet silicone bleu QuickFit 22 mm", "2 Batteries Enduro GoPro avec chageur DUO",
              "Bracelet à dégagement rapide 22mm en silicone noir"):
        assert e_un_pezzo(t), t
    for t in ("Garmin Forerunner 245", "Batterie électronique Roland TD-17", "Nintendo 3DS XL rossa"):
        assert e_un_pezzo(t) is None, t


def test_scala_di_allargamento_e_testo_pulito():
    from bot.radar_v2 import testi_piu_larghi
    from bot.valore_mercato import query_comp
    assert testi_piu_larghi("dyson v15 detect absolute", "Dyson") == ["dyson v15 detect"]
    assert testi_piu_larghi("dyson v15", "Dyson") == []
    assert testi_piu_larghi("ps5 slim digital edition", None) == ["ps5 slim"]
    assert query_comp("Dyson V8 nero gebraucht très bon état", "Dyson") == "dyson v8"
    from bot import radar
    v2 = {"semaforo": "rosso", "rivendita": None, "n": 1, "n_grezzi": 9, "allargata": 1, "motivo": "pochi_comparabili"}
    assert "(9 grezzi, ricerca allargata)" in radar.testo_risposta_gruppo(v2)


def test_allargamento_trova_comparabili_e_non_da_verde(monkeypatch):
    eventi = []
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", True)
    monkeypatch.setattr(radar_v2, "RADAR_V2_PREFILTRO", False)
    monkeypatch.setattr(radar_v2, "radar_in_pausa", lambda: False)
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: eventi.append(a))
    radar_v2._visti.clear(); radar_v2._cache.clear(); radar_v2._conteggio.update(giorno=None, n=0)
    righe = "\n".join(f"- Dyson V8 Animal aspirapolvere — €{p}" for p in (90, 95, 100, 105, 110, 115, 120, 125))

    async def finto(url):
        return (righe if "absolute" not in url else ""), True, {}

    async def senza_catalogo(url):
        return None
    monkeypatch.setattr(radar_v2, "_cerca_vinted_testo_diretto", finto)
    monkeypatch.setattr(radar_v2, "_catalogo_annuncio", senza_catalogo)
    r = asyncio.run(radar_v2.analizza({"title": "Dyson V8 Animal Absolute detect", "price": "20", "brand": "Dyson"}, "https://www.vinted.it/items/555001-dyson"))
    assert r["allargata"] and r["n"] >= 6 and r["semaforo"] == "giallo"


def test_guasti_e_battery_grip_sono_pezzi():
    from bot.valore_mercato import e_un_pezzo
    for t in ("Switch ne s'allume plus", "Canon BG-E7", "Wii kaputt", "Battery grip Canon 5D", "Console no funciona"):
        assert e_un_pezzo(t), t
    assert e_un_pezzo("Nintendo Switch OLED completa") is None


def test_marca_dal_titolo_vince_sul_tracker():
    from bot.radar_v2 import marca_dal_titolo
    assert marca_dal_titolo("Cuffie Bose QuietComfort 35", "Sony") == "bose"
    assert marca_dal_titolo("Bang & Olufsen Beoplay H5", None) == "bang olufsen"
    assert marca_dal_titolo("Garmin Forerunner 35", "Garmin") == "Garmin"
    assert marca_dal_titolo("Console wii bon état", "Nintendo") == "Nintendo"
    assert marca_dal_titolo("Radiosveglia", None) is None
    assert marca_dal_titolo("Canon BG-E7 per Nikonos", "Canon") == "Canon"


def test_solo_i_verdi_fanno_suono():
    from bot import radar
    assert radar._con_suono({"semaforo": "verde"})
    assert not radar._con_suono({"semaforo": "giallo"}) and not radar._con_suono(None)


def test_descrizione_dalla_pagina():
    html = '<script>{"id":1,"description":"Non funziona, vendo per ricambi\\nSpedisco","x":2}</script>'
    assert radar_v2._descrizione_da_html(html) == "Non funziona, vendo per ricambi\nSpedisco"
    assert radar_v2._descrizione_da_html("niente") is None


def test_messaggio_gruppo_spiega_il_perche_di_jev():
    from bot.radar import testo_risposta_gruppo
    v2 = {"semaforo": "giallo", "rivendita": 160.0, "margine": 93.55, "roi": 185.4, "n": 14, "n_grezzi": 15, "allargata": 1,
          "jev": "non_affare", "jev_conf": 0.9, "jev_motivo_frase": "dichiarato rotto, incompleto, bloccato o per ricambi"}
    assert "Jev: non e' un affare, dichiarato rotto, incompleto, bloccato o per ricambi (confidenza 0.9)" in testo_risposta_gruppo(v2)


def test_traccia_verdetto_v2_gialli_verdi_sempre_rossi_a_campione(monkeypatch):
    from bot import radar, tracciamento as tr
    partite = []
    monkeypatch.setattr(tr, "tracc_avvia_serie", lambda info, url, t0, offsets=None: partite.append((url, offsets)))
    monkeypatch.setattr(radar, "_radar_tracciati", set())
    monkeypatch.setattr(radar, "RADAR_TRACCIA_ROSSI_1_SU", 10)
    monkeypatch.setattr(radar, "RADAR_AUDIT_1_SU", 0)
    p = {"title": "Switch", "price": "40", "brand": "nintendo"}
    u = lambda n: f"https://www.vinted.it/items/{n}-switch"
    assert radar.traccia_verdetto_v2(p, u(101), {"semaforo": "verde", "motivo": "ok", "n": 8})
    assert radar.traccia_verdetto_v2(p, u(103), {"semaforo": "giallo", "motivo": "ok"})
    assert not radar.traccia_verdetto_v2(p, u(101), {"semaforo": "verde"})          # gia' tracciato
    assert not radar.traccia_verdetto_v2(p, u(105), {"semaforo": "rosso", "motivo": "margine_basso"})   # 105 % 10 != 0
    assert radar.traccia_verdetto_v2(p, u(110), {"semaforo": "rosso", "motivo": "margine_basso"})      # 110 % 10 == 0
    assert not radar.traccia_verdetto_v2(p, u(120), {"semaforo": "rosso", "motivo": "pezzo_o_accessorio"})
    assert not radar.traccia_verdetto_v2(p, u(130), None)
    assert tr._tracc_ctx["101"]["semaforo"] == "verde"
    assert len(partite) == 3 and partite[0][1] == radar.RADAR_RICONTROLLI_SECONDI


def test_audit_scartati_non_oggetto_a_campione(monkeypatch):
    from bot import radar, tracciamento as tr
    partite = []
    monkeypatch.setattr(tr, "tracc_avvia_serie", lambda info, url, t0, offsets=None: partite.append(url))
    monkeypatch.setattr(radar, "_radar_tracciati", set())
    monkeypatch.setattr(radar, "RADAR_AUDIT_1_SU", 20)
    p = {"title": "Switch", "price": "40", "brand": "nintendo"}
    u = lambda n: f"https://www.vinted.it/items/{n}-switch"
    assert not radar.traccia_verdetto_v2(p, u(125), {"semaforo": "rosso", "motivo": "jev_tipo"})   # 125 % 20 != 0
    assert radar.traccia_verdetto_v2(p, u(140), {"semaforo": "rosso", "motivo": "jev_tipo", "margine": 80, "roi": 150})
    assert tr._tracc_ctx["140"]["audit"] == "si"
    monkeypatch.setattr(radar, "RADAR_AUDIT_1_SU", 0)
    assert not radar.traccia_verdetto_v2(p, u(160), {"semaforo": "rosso", "motivo": "jev_tipo"})   # audit spento


def test_audit_radar_tabella():
    import importlib.util, pathlib
    sp = importlib.util.spec_from_file_location("audit_radar", pathlib.Path(__file__).parent.parent / "tools/radar_liste/audit_radar.py")
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    righe = [
        "x TRACCIATO_RADAR | item=1 | prezzo=40 | semaforo=rosso | motivo=jev_tipo | margine=80 | roi=150 | audit=si | venduto_s=120 | incompleto=no",
        "x TRACCIATO_RADAR | item=2 | prezzo=40 | semaforo=rosso | motivo=jev_tipo | margine=10 | roi=20 | venduto_s=- | incompleto=no",
        "x TRACCIATO_RADAR | item=3 | prezzo=40 | semaforo=verde | motivo=ok | venduto_s=60 | incompleto=no",
    ]
    assert mod.tabella(righe)["jev_tipo"] == [2, 2, 1, 1]
    assert "verde" not in mod.tabella(righe)


def test_da_mandare_richiede_jev_affare(monkeypatch):
    from bot import radar
    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", True)
    monkeypatch.setattr(radar, "RADAR_JEV_CONF_MIN", 0.7)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    ok = {"semaforo": "giallo", "jev": "affare_vero", "jev_conf": 0.9}
    assert radar._da_mandare(ok) is True
    assert radar._da_mandare({**ok, "jev": "non_affare"}) is False
    assert radar._da_mandare({**ok, "jev": "falso_o_ricambio"}) is False
    assert radar._da_mandare({**ok, "jev_conf": 0.6}) is False
    assert radar._da_mandare({"semaforo": "verde", "jev": None, "jev_conf": None}) is False
    assert radar._da_mandare({**ok, "semaforo": "rosso"}) is False
    assert radar.RADAR_CHAT_ID == (radar.TELEGRAM_ALERT_CHAT_ID or radar.TELEGRAM_OWNER_CHAT_ID)


def test_verifica_comparabili_filtra_e_toglie_il_suffisso(monkeypatch):
    from bot import radar
    monkeypatch.setattr(radar, "RADAR_VERIFICA", True)
    base = {"semaforo": "giallo", "jev": "affare_vero", "jev_conf": 0.9, "rivendita": 200, "margine": 150, "roi": 300, "n": 14,
            "jev_motivo_frase": "oggetto vero, ma i simili non sono lo stesso modello"}
    rosso = {**base, "verificata": {"semaforo": "rosso", "n_stesso": 0, "n_giudicati": 14, "rivendita": None}}
    assert radar._da_mandare(rosso) is False
    giallo = {**base, "verificata": {"semaforo": "giallo", "n_stesso": 4, "n_giudicati": 4, "rivendita": 187.5, "margine": 107, "roi": 250}}
    assert radar._da_mandare(giallo) is True
    testo = "\n".join(radar._righe_v2(giallo))
    assert "Verificati: 4 su 4" in testo and "simili non sono" not in testo
    assert radar._da_mandare(base) is True


def test_classifica_titolo_vuoto_non_sfasa(monkeypatch):
    from bot import jev
    monkeypatch.setattr(jev, "JEV_GIUDICE", True)
    monkeypatch.setattr(jev, "JEV_COMPS", True)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    visto = {}
    def finto(corpo):
        visto.update(corpo)
        return {"answers": {f"c{i}": {"choice": "altro", "confidence": 0.9} for i in range(3)}}
    monkeypatch.setattr(jev, "_chiama_jev", finto)
    out = jev.classifica_comparabili("x", ["a", "", "c"])
    assert len(out) == 3 and set(visto["questions"]) == {"c0", "c1", "c2"}


def test_query_alternative_dalla_sigla():
    from bot.valore_mercato import query_alternative
    alt = query_alternative("Sony cuffie bluetooth WH-CH520 nere", "sony")
    assert alt and all(q.startswith("sony ") and "ch520" in q for q in alt)
    assert query_alternative("Giacca elegante", "zara") == []


def test_verifica_cerca_dalla_sigla_se_gli_stessi_modelli_sono_pochi(monkeypatch):
    import asyncio
    from bot import radar_v2
    radar_v2._comps_simili.clear()
    radar_v2._comps_simili[("sony cuffie", None)] = [("Sony cuffie vecchie", 10), ("Sony radio", 12), ("Sony altro", 14)]
    radar_v2._comps_simili[("sony ch520", None)] = [("Sony WH-CH520 nere", 30), ("Sony WH-CH520 bianche", 32), ("Sony WH-CH520", 35)]

    async def finta_ricerca(q, *a, **k):
        return [], 0, False

    def finta_classifica(titolo, titoli, desc):
        return [("stesso_modello" if "CH520" in t else "altro", 0.9) for t in titoli]

    monkeypatch.setattr(radar_v2, "_prezzi_simili", finta_ricerca)
    monkeypatch.setattr(radar_v2, "classifica_comparabili", finta_classifica)
    monkeypatch.setattr(radar_v2, "query_alternative", lambda t, b, max_n=2: ["sony ch520"])
    info, ok = asyncio.run(radar_v2._verifica_comparabili("Sony WH-CH520", 15, "sony", None, "sony cuffie"))
    assert sorted(ok) == [30, 32, 35] and info["n_stesso"] == 3 and info["query"] == ["sony cuffie", "sony ch520"]


def test_verifica_usa_i_simili_se_gli_stessi_modelli_sono_pochi(monkeypatch):
    import asyncio
    from bot import radar_v2
    radar_v2._comps_simili.clear()
    radar_v2._comps_simili[("canon eos", None)] = [("Canon EOS 4000D", 150), ("Canon EOS 2000D", 140), ("Canon EOS 1300D", 130), ("Canon cover", 5)]

    async def finta_ricerca(q, *a, **k):
        return [], 0, False

    def finta_classifica(titolo, titoli, desc):
        et = {"Canon EOS 4000D": "stesso_modello", "Canon EOS 2000D": "simile", "Canon EOS 1300D": "simile"}
        return [(et.get(t, "altro"), 0.9) for t in titoli]

    monkeypatch.setattr(radar_v2, "_prezzi_simili", finta_ricerca)
    monkeypatch.setattr(radar_v2, "classifica_comparabili", finta_classifica)
    monkeypatch.setattr(radar_v2, "query_alternative", lambda t, b, max_n=2: [])
    info, ok = asyncio.run(radar_v2._verifica_comparabili("Canon EOS 4000D", 60, "canon", None, "canon eos"))
    assert info["n_stesso"] == 1 and info["n_simili"] == 2 and info["n_usabili"] == 3
    assert sorted(ok) == [130, 140, 150]  # il "altro" (cover) resta fuori


def test_link_comparabili_i_piu_vicini_alla_mediana():
    from bot.testo import _normalizza_titolo_per_link as norm
    coppie = [("A uno", 10.0), ("B due", 90.0), ("C tre", 100.0), ("D quattro", 110.0), ("E cinque", 400.0), ("F senza", 95.0)]
    mappa = {(norm(t), f"{p:.2f}"): f"https://www.vinted.it/items/{i}" for i, (t, p) in enumerate(coppie[:5], 1)}
    out = radar_v2.link_comparabili(coppie, [mappa], n=3)
    assert [p for _t, p, _u in out] == [100.0, 90.0, 110.0]
    assert all(u.startswith("https://www.vinted.it/items/") for _t, _p, u in out)
    assert radar_v2.link_comparabili([], [mappa]) == []
    assert radar_v2.link_comparabili(coppie, [{}, None]) == []


def test_righe_v2_mostra_i_link_dei_comparabili():
    from bot import radar
    v2 = {"semaforo": "giallo", "rivendita": 100, "margine": 60, "roi": 150, "n": 5,
          "link_comps": [("Sony WH-CH520", 95.0, "https://www.vinted.it/items/1"), ("Sony WH-CH520 nere", 105.5, "https://www.vinted.it/items/2")]}
    righe = radar._righe_v2(v2)
    assert "Comparabili da controllare:" in righe
    assert "• 95 € https://www.vinted.it/items/1" in righe
    assert "• 105.5 € https://www.vinted.it/items/2" in righe
    assert "Comparabili da controllare:" not in "\n".join(radar._righe_v2({**v2, "link_comps": []}))


def test_estrai_miniature_vinted_e_id_da_url():
    from bot.comps_filtri import _estrai_miniature_vinted
    from bot.radar_v2 import id_da_url_comp
    html = ('<img src="https://images1.vinted.net/t/ab/310x430/x.webp?s=1&amp;v=2" alt="Switch, 40 €" class="c" '
            'data-testid="product-item-id-123--image--img"/><img src="/altro.png" data-testid="product-item-id-9--image--img"/>')
    assert _estrai_miniature_vinted(html) == {"123": "https://images1.vinted.net/t/ab/310x430/x.webp?s=1&v=2"}
    assert id_da_url_comp("https://www.vinted.it/items/123-slug") == "123"
    assert id_da_url_comp("https://x") is None


def test_ricambio_dal_titolo_non_cerca_comparabili(monkeypatch):
    import asyncio
    from bot import radar_v2
    monkeypatch.setattr(radar_v2, "precontrollo_tipo", lambda t: "ricambio")
    chiamate = []

    async def finto(*a, **k):
        chiamate.append(a)
        return None, 0, False
    monkeypatch.setattr(radar_v2, "_prezzi_simili", finto)
    monkeypatch.setattr(radar_v2, "RADAR_V2_OMBRA", True)
    monkeypatch.setattr(radar_v2, "radar_in_pausa", lambda: False)
    v2 = asyncio.run(radar_v2.analizza({"title": "Dyson V8 Animal aspirapolvere", "price": "40", "brand": "Dyson"},
                                       "https://www.vinted.it/items/987654321-dyson-v8"))
    assert v2["motivo"] == "jev_tipo:ricambio" and v2["semaforo"] == "rosso"
    assert chiamate == []


def test_spezza_didascalia_non_perde_nulla():
    from bot.radar import spezza_didascalia
    righe = [f"riga {i} " + "x" * 80 for i in range(20)]
    testo = "\n".join(righe)
    d, resto = spezza_didascalia(testo)
    assert len(d) <= 1000 and d.endswith("x") and resto
    assert (d + "\n" + resto) == testo
    assert spezza_didascalia("corto") == ("corto", "")


def test_invia_radar_bottone_e_resto(monkeypatch):
    import asyncio
    from bot import radar
    inviati = []
    async def foto_(chat, foto, caption=None, disable_notification=False, url_bottone=None):
        inviati.append(("foto", len(caption), url_bottone))
    async def msg_(chat, testo, disable_notification=False, reply_to=None, url_bottone=None):
        inviati.append(("msg", len(testo), url_bottone))
    monkeypatch.setattr(radar, "telegram_send_photo", foto_)
    monkeypatch.setattr(radar, "telegram_send_message", msg_)
    url = "https://www.vinted.it/items/123456789-x"
    testo = "\n".join(["riga " + "y" * 90] * 15 + [url])
    asyncio.run(radar._invia_radar(testo, foto=b"x"))
    assert inviati[0][0] == "foto" and inviati[0][2] == url and inviati[1][0] == "msg"
    inviati.clear()
    asyncio.run(radar._invia_radar("ciao\n" + url))
    assert inviati == [("msg", len("ciao\n" + url), url)]


def test_sigla_spezzata_si_unisce_nella_query():
    from bot.valore_mercato import query_comp, unisci_sigla
    assert unisci_sigla("Sony h 1") == "sony h1"
    assert unisci_sigla("Sony i 3 giochi") == "sony i 3 giochi"  # vocale: articolo, non sigla
    assert "h1" in query_comp("Sony h 1", "sony").split()


def test_bottone_usa_l_url_dell_annuncio_non_un_comparabile():
    from bot import radar
    testo = "🟡 *40 €*\nSwitch\n\n🔗 Comparabili da controllare:\n• 90 € https://www.vinted.it/items/111-comp\n\nhttps://www.vinted.it/items/999-giusto"
    assert radar.url_annuncio_nel_testo(testo) == "https://www.vinted.it/items/999-giusto"
    assert radar.url_annuncio_nel_testo(testo, "https://www.vinted.it/items/5-x") == "https://www.vinted.it/items/5-x"
    assert radar.url_annuncio_nel_testo("niente link") is None


def test_ricerca_diversa():
    d = radar_v2.ricerca_diversa
    assert d("nintendo switch", "nintendo switch oled") is True
    assert d("nintendo switch oled", "nintendo switch oled") is False
    assert d("dyson v11 absolute extra", "dyson v11 absolute") is False   # contorno senza sigle diverse
    assert d("dyson v8 absolute", "dyson v11 absolute") is True            # sigla diversa
    assert d("qualunque cosa", "") is False


def test_invia_verdetto_v2_rivaluta_col_modello_di_gemini(monkeypatch):
    import asyncio
    from bot import radar
    inviati = []

    async def finto_invia(testo, foto, suono=False, ricerca=None, url=None):
        inviati.append((testo, suono, url))

    async def gemini(*a, **k):
        return {"verdetto": "conferma", "confidenza": 0.9, "motivo": "ok", "ricerca_modello": "nintendo switch oled", "ricerca_semantica": "",
                "rivendita_eur": None, "velocita_rivendita": "giorni", "velocita_base": "molto richiesta"}

    chiamate = []

    async def rivaluta(parsed, url, v2, g):
        chiamate.append(g["ricerca_modello"])
        return {**v2, "semaforo": "giallo", "rivalutata": True, "ricerca_rifatta": "nintendo switch oled", "rivendita": 150, "margine": 60, "roi": 150, "n": 8}

    monkeypatch.setattr(radar, "RADAR_JEV_RICHIESTO", False)
    monkeypatch.setattr(radar, "RADAR_SEMAFORI", {"verde", "giallo"})
    monkeypatch.setattr(radar, "_invia_radar", finto_invia)
    monkeypatch.setattr(radar, "radar_in_pausa", lambda *a, **k: False)
    monkeypatch.setattr(radar, "controlla_gemini", gemini)
    radar._radar_inviati.clear()
    u = "https://www.vinted.it/items/910-switch"
    assert asyncio.run(radar.invia_verdetto_v2({"title": "Switch", "price": "40"}, u, {"semaforo": "verde", "rivendita": 90}, rivaluta=rivaluta)) is True
    testo, suono, url_bottone = inviati[0]
    assert chiamate == ["nintendo switch oled"] and suono is False   # il verde e' diventato giallo: niente suono
    assert url_bottone == u and "Comparabili rifatti sul modello letto da Gemini" in testo and "Velocità di rivendita stimata da Gemini" in testo

    # se la rivalutazione la porta a rosso l'avviso non parte
    async def rosso(parsed, url, v2, g):
        return {**v2, "semaforo": "rosso", "motivo": "margine_basso"}

    assert asyncio.run(radar.invia_verdetto_v2({"title": "Switch", "price": "40"}, "https://www.vinted.it/items/911-x", {"semaforo": "giallo"}, rivaluta=rosso)) is False
    assert len(inviati) == 1


def test_rivaluta_rifa_i_comparabili_sul_modello_di_gemini(monkeypatch):
    import asyncio
    cercate = []

    async def prezzi_finti(testo, titolo, prezzo, brand=None, catalogo=None):
        cercate.append(testo)
        return ([140, 150, 160, 155, 145], 15, False) if testo == "nintendo switch oled" else ([60, 70], 15, False)

    async def verifica_finta(*a, **k):
        return None, []

    monkeypatch.setattr(radar_v2, "_prezzi_simili", prezzi_finti)
    monkeypatch.setattr(radar_v2, "_verifica_comparabili", verifica_finta)
    monkeypatch.setattr(radar_v2, "giudica_completo", lambda *a, **k: ("affare_vero", 0.9, ("stesso_modello", 0.9), ("ok", "oggetto vero")))
    monkeypatch.setattr(radar_v2.db, "scrivi_evento", lambda *a, **k: None)
    v2 = {"semaforo": "verde", "q": "nintendo switch", "titolo": "Switch OLED", "brand": "nintendo", "catalogo": "3025", "spedizione_eur": 5.0, "spedizione_stato": "ESTIMATED",
          "_descrizione": "", "rivendita": 65}
    g = {"ricerca_modello": "nintendo switch oled", "ricerca_semantica": "nintendo switch console"}
    nuovo = asyncio.run(radar_v2.rivaluta({"price": "40"}, "https://www.vinted.it/items/920-x", v2, g))
    assert cercate == ["nintendo switch oled"] and nuovo["rivalutata"] and nuovo["q"] == "nintendo switch oled" and nuovo["rivendita"] > 100
    # stesso modello: niente da rifare
    assert asyncio.run(radar_v2.rivaluta({"price": "40"}, "https://www.vinted.it/items/921-x", v2, {"ricerca_modello": "nintendo switch"})) is v2
