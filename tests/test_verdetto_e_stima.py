import main_telethon as m
from bot import gemini_stato as gs


def test_cascata_gemini_scala_per_modello_quando_la_quota_finisce(monkeypatch):
    import main_telethon as m
    monkeypatch.setattr(gs, "GEMINI_CASCATA", ["m-top", "m-mid", "m-lite"])
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1", "k2"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert "/models/m-top:" in m._gemini_url_effettivo(url)
    m._gemini_segna_key_quota_esaurita("k1", "m-top")
    assert "/models/m-top:" in m._gemini_url_effettivo(url)          # k2 ha ancora quota su m-top
    assert m._gemini_key_attuale("m-top") == "k2"
    m._gemini_segna_key_quota_esaurita("k2", "m-top")
    assert "/models/m-mid:" in m._gemini_url_effettivo(url)          # m-top esaurito su tutte le key
    assert not m._gemini_key_in_quota_esaurita("k1", "m-mid")        # la quota e' per modello, non per key
    m._gemini_segna_key_quota_esaurita("k1", "m-mid"); m._gemini_segna_key_quota_esaurita("k2", "m-mid")
    m._gemini_segna_key_quota_esaurita("k1", "m-lite"); m._gemini_segna_key_quota_esaurita("k2", "m-lite")
    assert "/models/m-lite:" in m._gemini_url_effettivo(url)         # tutto esaurito: si resta sull'ultimo


def test_senza_cascata_url_invariato(monkeypatch):
    import main_telethon as m
    monkeypatch.setattr(gs, "GEMINI_CASCATA", [])
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert m._gemini_url_effettivo(url) == url


def test_secondi_retry_gemini_minuto_vs_giorno(monkeypatch):
    import main_telethon as m
    assert m._gemini_secondi_retry('... limit: 5, model: x\nPlease retry in 46.826763296s.') == 46.826763296
    assert m._gemini_secondi_retry('Please retry in 10h17m26.7s.') == 10 * 3600 + 17 * 60 + 26.7
    assert m._gemini_secondi_retry('"retryDelay": "37046s"') == 37046
    assert m._gemini_secondi_retry("niente") is None
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "prossimo_reset_quota_gemini", lambda adesso=None: __import__("time").time() + 20 * 3600)
    m._gemini_segna_key_quota_esaurita("k", "x", 46.8)                 # al minuto: ~49 s, non 6 ore
    scad = gs._gemini_key_quota_esaurita_fino[("k", "x")] - __import__("time").time()
    assert 40 < scad < 60
    m._gemini_segna_key_quota_esaurita("k", "y", 37046)                # giornaliera: l'attesa indicata
    assert 36000 < gs._gemini_key_quota_esaurita_fino[("k", "y")] - __import__("time").time() < 38000
    m._gemini_segna_key_quota_esaurita("k", "z")                       # senza indicazione: 6 ore come prima
    assert 21000 < gs._gemini_key_quota_esaurita_fino[("k", "z")] - __import__("time").time() < 22000


def test_cascata_per_fase_occhio(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_CASCATA", ["gen-1"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", ["occ-lite"])
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert "/models/occ-lite:" in gs._gemini_url_effettivo(url, "occhio")
    assert "/models/gen-1:" in gs._gemini_url_effettivo(url)                       # senza fase: cascata generica
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", [])
    assert gs.cascata_per("occhio") == ["gen-1"]                                     # fase non configurata: generica


