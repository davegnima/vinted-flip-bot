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
    v2 = {"semaforo": "🟢", "rivendita": 80, "margine": 60, "roi": 150, "n": 7, "jev": "affare_vero", "jev_conf": 0.9}
    righe = radar._righe_v2(v2)
    assert righe[0].startswith("Comparabili 🟢") and "7 simili" in righe[0]
    assert righe[1] == "Jev: affare_vero (confidenza 0.9)"
    assert radar._righe_v2(None) == []
    monkeypatch.setattr(radar, "RADAR_SOLO_VERDI", True)
    assert radar._da_mandare(v2) is True
    assert radar._da_mandare({"semaforo": "🟡"}) is False
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
    assert riga == ["Comparabili 🔴: pochi_comparabili (1 simili)"]
    assert radar._righe_v2({"semaforo": "rosso", "rivendita": None, "n": 0, "motivo": "titolo_generico"})[0].endswith("(0 simili)")
    from bot.radar_v2 import _rosso
    assert _rosso("parola_vietata:x")["semaforo"] == "rosso"
