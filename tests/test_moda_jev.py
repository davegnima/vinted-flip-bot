"""Verifica Jev dei brand nuovi della moda (bot/moda_jev.py): URL dei comparabili, decisione, righe del messaggio."""
import tests.conftest  # noqa: F401
from bot import moda_jev as mj


def test_url_comparabili_con_brand_categoria_e_testo():
    u = mj.url_comparabili("zimmermann", "abito lungo", 10)
    assert "brand_ids[]=172418" in u and "catalog[]=10" in u and "search_text=abito%20lungo" in u


def test_url_comparabili_senza_id_cerca_per_testo_con_il_brand():
    u = mj.url_comparabili("marchio inesistente", "giacca", 5)
    assert "brand_ids" not in u and "search_text=marchio%20inesistente%20giacca" in u and "catalog[]=5" in u
    assert mj.url_comparabili(None, "x", 1) is None


def test_decidi_conferma_se_i_comparabili_reggono_e_la_foto_e_ok():
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9)) == ("conferma", "ok")


def test_decidi_scarta_se_il_margine_sui_comparabili_non_c_e():
    assert mj.decidi({"ok": False, "motivo": "margine_basso"}, None)[0] == "scarta"


def test_decidi_scarta_replica_con_confidenza_alta_ma_non_con_confidenza_bassa():
    assert mj.decidi({"ok": True}, ("replica_probabile", 0.9))[0] == "scarta"
    assert mj.decidi({"ok": True}, ("altra_marca", 0.8))[0] == "scarta"
    assert mj.decidi({"ok": True}, ("replica_probabile", 0.3))[0] == "conferma"


def test_decidi_senza_comparabili_non_verificato_ma_il_falso_scarta_lo_stesso():
    assert mj.decidi(None, None) == ("non_verificato", "comparabili_non_trovati")
    assert mj.decidi(None, ("replica_probabile", 0.9))[0] == "scarta"


def test_tratteni_solo_per_brand_nuovo_con_regola_brand_nuovo(monkeypatch):
    monkeypatch.setattr(mj, "MODA_JEV", True)
    assert mj.tratteni_per_verifica({"brand": "zimmermann"}, "brand_nuovo")
    assert not mj.tratteni_per_verifica({"brand": "zimmermann"}, "giallo_economico")
    assert not mj.tratteni_per_verifica({"brand": "marni"}, "brand_nuovo")
    monkeypatch.setattr(mj, "MODA_JEV", False)
    assert not mj.tratteni_per_verifica({"brand": "zimmermann"}, "brand_nuovo")


def test_righe_messaggio_con_e_senza_comparabili():
    r = mj.righe_messaggio({"rivendita": 140, "n": 7, "margine": 90, "roi": 400, "esempi": [("Abito", 120)], "autenticita": ("originale_plausibile", 0.8)})
    assert any("7 annunci" in x for x in r) and any("sembra originale" in x for x in r)
    r2 = mj.righe_messaggio({"rivendita": None, "autenticita": None})
    assert any("non trovati" in x for x in r2) and any("non verificata" in x for x in r2)


def test_riga_esito_scheda_per_scarto_conferma_e_non_verificato():
    s = mj.riga_esito_scheda({"esito": "scarta", "motivo": "comparabili:margine_basso", "rivendita": 67.5, "n": 6, "margine": 15.5, "roi": 40})
    assert "non avvisato" in s and "68" in s
    f = mj.riga_esito_scheda({"esito": "scarta", "motivo": "foto:replica_probabile", "autenticita": ("replica_probabile", 0.9)})
    assert "replica probabile" in f
    assert "confermato" in mj.riga_esito_scheda({"esito": "conferma", "rivendita": 140, "margine": 90})
    assert "non trovati" in mj.riga_esito_scheda({"esito": "non_verificato"})


def test_tratteni_con_moda_jev_tutti(monkeypatch):
    monkeypatch.setattr(mj, "MODA_JEV", True)
    monkeypatch.setattr(mj, "MODA_JEV_TUTTI", True)
    assert mj.tratteni_per_verifica({"brand": "prada"}, "semaforo")
    assert mj.tratteni_per_verifica({"brand": "marni"}, "giallo_economico")
    assert not mj.tratteni_per_verifica({"brand": "prada"}, "no")


def test_fair_value_borse_lancel_e_kurt_geiger_dai_comparabili():
    """02/11: le borse Lancel e Kurt Geiger non devono tornare alle stime gonfiate (145 e 99) del fattore categoria."""
    from bot.fair_value import stima_fair_value
    for brand, massimo in (("lancel", 90), ("kurt geiger", 80)):
        r = stima_fair_value({"brand": brand, "title": f"Borsa {brand} in pelle", "price": 15})
        assert r and 40 <= r["fv"] <= massimo, (brand, r)


def test_comparabili_con_link_e_diversi():
    from bot.moda_jev import comparabili_con_link, comparabili_diversi, righe_messaggio
    from bot.testo import _normalizza_titolo_per_link as norm
    coppie = [("Borsa A", 40.0), ("Borsa B", 60.0), ("Borsa C", 200.0), ("Borsa D", 55.0)]
    mappa = {(norm(t), f"{p:.2f}"): f"https://www.vinted.it/items/{i}-x" for i, (t, p) in enumerate(coppie, 1)}
    out = comparabili_con_link(coppie, [None, mappa], n=2)
    assert sorted(c[1] for c in out) == [55.0, 60.0]   # i piu' vicini alla mediana (60), non gli estremi
    assert comparabili_diversi([("diverso", 0.9), ("diverso", 0.7), ("simile", 0.8)])
    assert not comparabili_diversi([("diverso", 0.9), ("simile", 0.8), ("stesso_modello", 0.8)])
    assert not comparabili_diversi([("diverso", 0.3), ("diverso", 0.2)])   # confidenza bassa: non conta
    assert not comparabili_diversi(None)
    righe = righe_messaggio({"rivendita": 60, "n": 4, "margine": 50, "roi": 150, "esempi": [], "autenticita": None,
                             "foto_comps": [("stesso_modello", 0.8), ("diverso", 0.7)]})
    assert any("Foto comparabili" in r and "molto simile" in r for r in righe)
