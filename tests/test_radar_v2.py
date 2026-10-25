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
    monkeypatch.setattr(radar_v2, "_cerca_vinted_testo_diretto_con_fallback_serper", finto)
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
        "Semaforo: 🟢",
        "Jev: affare_vero (confidenza 0.9)",
    ]
    assert radar._righe_v2(None) == ["Comparabili: non calcolati"]
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
        "Comparabili: 1 trovati, nessuna stima (pochi_comparabili)",
        "Semaforo: in costruzione (servono più comparabili nel tempo)",
    ]
    assert radar._righe_v2({"semaforo": "rosso", "rivendita": None, "n": 0, "motivo": "titolo_generico"})[0] == \
        "Comparabili: 0 trovati, nessuna stima (titolo_generico)"
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
