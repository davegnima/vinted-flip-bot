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
    assert any("Comparabili Vinted: 7" in x for x in r) and any("sembra originale" in x for x in r)
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
    from bot.moda_jev import comparabili_con_link, molto_simili, righe_messaggio
    from bot.testo import _normalizza_titolo_per_link as norm
    coppie = [("Borsa A", 40.0), ("Borsa B", 60.0), ("Borsa C", 200.0), ("Borsa D", 55.0)]
    mappa = {(norm(t), f"{p:.2f}"): f"https://www.vinted.it/items/{i}-x" for i, (t, p) in enumerate(coppie, 1)}
    out = comparabili_con_link(coppie, [None, mappa], n=2)
    assert sorted(c[1] for c in out) == [55.0, 60.0]   # i piu' vicini alla mediana (60), non gli estremi
    # la foto conta solo se Jev trova il comparabile MOLTO simile (stesso_modello, confidenza >= 0,6); altrimenti nessun effetto
    coppie = [(("A", 40.0, "u1"), b"x"), (("B", 55.0, "u2"), b"x"), (("C", 60.0, "u3"), b"x")]
    assert [c[1] for c in molto_simili(coppie, [("stesso_modello", 0.8), ("simile", 0.9), ("stesso_modello", 0.4)])] == [40.0]
    assert molto_simili(coppie, [("diverso", 0.9), ("simile", 0.9), ("non_chiaro", 0.9)]) == []
    assert molto_simili(coppie, None) == [] and molto_simili([], [("stesso_modello", 0.9)]) == []
    righe = righe_messaggio({"rivendita": 60, "n": 4, "margine": 50, "roi": 150, "esempi": [], "autenticita": None,
                             "foto_comps": [("stesso_modello", 0.8), ("diverso", 0.7)]})
    assert any("Foto comparabili" in r and "molto simile" in r for r in righe)


def test_gemini_moda_serve_controllo_e_decisione():
    from bot import moda_gemini as g
    from bot.moda_jev import decidi, riga_esito_scheda, righe_messaggio
    # Jev sicuro dell'originale e prezzo normale: niente chiamata; foto poco chiara o prezzo troppo basso: controllo
    assert g.serve_controllo(("originale_plausibile", 0.8), 30, 100)   # dal 5/11 il controllo approfondito vale per ogni avviso
    g.MODA_GEMINI_SEMPRE = False
    assert not g.serve_controllo(("originale_plausibile", 0.8), 30, 100)
    assert g.serve_controllo(("originale_plausibile", 0.4), 30, 100)
    assert g.serve_controllo(("non_chiaro", 0.9), 30, 100)
    assert g.serve_controllo(None, 30, 100)
    assert g.serve_controllo(("originale_plausibile", 0.9), 10, 100)   # 10 < 25% di 100
    g.MODA_GEMINI_SEMPRE = True
    d2 = g.leggi_risposta('{"autenticita":"altra_marca","confidenza":0.9,"etichetta_letta":"Kapitales","made_in":"China","prova_acquisto":"fattura","indizi":"x","motivo":"y"}')
    assert g.e_replica(d2) and d2["prova_acquisto"] == "fattura"
    assert "made in China" in g.riga_messaggio(d2) and "fattura" in g.riga_messaggio(d2)
    d = g.leggi_risposta('{"autenticita":"replica","confidenza":0.85,"indizi":"logo storto","motivo":"logo storto"}')
    assert g.e_replica(d)
    assert not g.e_replica(g.leggi_risposta('{"autenticita":"replica","confidenza":0.5,"indizi":"","motivo":""}'))
    assert not g.e_replica(g.leggi_risposta('{"autenticita":"dubbia","confidenza":0.95,"indizi":"","motivo":""}'))
    assert g.leggi_risposta("[ERRORE x]") is None and g.leggi_risposta('{"autenticita":"boh"}') is None
    ok = {"ok": True}
    assert decidi(ok, None, d) == ("scarta", "gemini:replica")
    assert decidi(ok, None, None)[0] == "conferma"
    ris = {"esito": "scarta", "motivo": "gemini:replica", "gemini": d}
    assert "Gemini" in riga_esito_scheda(ris)
    assert any("Gemini" in r for r in righe_messaggio({"rivendita": 60, "n": 4, "margine": 50, "roi": 150, "esempi": [], "autenticita": None, "gemini": d}))


def test_righe_messaggio_con_link_ai_comparabili():
    from bot.moda_jev import righe_messaggio
    ris = {"rivendita": 60, "n": 3, "margine": 50, "roi": 150, "esempi": [("Borsa A", 40.0)], "autenticita": None,
           "link_comps": [("Borsa A", 40.0, "https://www.vinted.it/items/1-borsa-a")]}
    righe = righe_messaggio(ris)
    assert any("https://www.vinted.it/items/1-borsa-a" in r for r in righe)


def test_verifica_usa_la_ricerca_testuale_senza_filtro_jev(monkeypatch):
    """Caso Bottega Veneta blazer: i comparabili della ricerca testuale bastano, Jev non li svuota piu'; la foto conta solo se molto simile."""
    import asyncio
    from bot import moda_jev as mj
    comps = [("Bottega Veneta blazer", p) for p in (150.0, 170.0, 180.0, 200.0, 220.0)]

    async def cerca(url):
        return "x", True, {}
    monkeypatch.setattr(mj, "_cerca_vinted_testo_diretto", cerca)
    monkeypatch.setattr(mj, "parse_comp", lambda r: comps)
    monkeypatch.setattr(mj, "solo_usato", lambda c: c)
    monkeypatch.setattr(mj, "comparabili_simili", lambda c, t, b: c)
    monkeypatch.setattr(mj, "giudica_autenticita", lambda *a: ("non_chiaro", 0.56))
    monkeypatch.setattr(mj, "optimize_image_bytes", lambda b, n: b)
    monkeypatch.setattr(mj, "JEV_FOTO_COMPS", False)
    async def nessun_gemini(*a, **k):
        return None
    monkeypatch.setattr(mj, "controlla_gemini", nessun_gemini)
    info = {"title": "Bottega veneta navy blue blazer", "price": 50, "catalog_id": 2050,
            "fair_value": {"brand": "bottega veneta", "fv": 211}}
    ris = asyncio.run(mj.verifica(info, b"img", [b"img"]))
    assert ris["esito"] == "conferma" and ris["n"] >= 3 and ris["rivendita"] and ris["rivendita"] > 100


def test_giallo_con_margine_e_roi_promettenti_va_a_jev_senza_invio_immediato():
    from bot.fair_value import valuta_preavviso, REGOLA_DA_VERIFICARE
    # Kurt Geiger 30 EUR, 🟡, fair value 82, margine 52: la regola base dice 'no', ma ROI +173% -> da verificare con Jev
    assert valuta_preavviso({"semaforo": "🟡", "margine": 52, "conf": "media", "brand": "kurt geiger", "fv": 82}, 30) == (True, REGOLA_DA_VERIFICARE)
    # margine sotto 50, o ROI sotto 100%: resta 'no'
    assert valuta_preavviso({"semaforo": "🟡", "margine": 40, "conf": "media", "brand": "kurt geiger", "fv": 70}, 30) == (False, "no")
    assert valuta_preavviso({"semaforo": "🟡", "margine": 52, "conf": "media", "brand": "kurt geiger", "fv": 152}, 100) == (False, "no")
    assert valuta_preavviso({"semaforo": "🔴", "margine": 80, "conf": "media", "brand": "kurt geiger", "fv": 110}, 30) == (False, "no")


def test_da_verificare_viene_sempre_trattenuto_per_jev(monkeypatch):
    monkeypatch.setattr(mj, "MODA_JEV", True)
    assert mj.tratteni_per_verifica({"brand": "kurt geiger"}, "da_verificare") is True


def test_messaggio_a_passi_per_lo_scarto_sui_comparabili():
    """Caso Zimmermann Nightwear (5/11): l'utente vuole vedere cosa ha fermato l'annuncio, con i numeri, e che il legit check non e' stato fatto."""
    ris = {"esito": "scarta", "motivo": "comparabili:margine_basso", "n": 3, "rivendita": 52.5, "margine": 17.8, "roi": 71.0, "esempi": [],
           "autenticita": None, "gemini": None, "legit_saltato": True, "prezzi_comps": (45.0, 60.0),
           "link_comps": [("t", 60.0, "https://www.vinted.it/items/1-a")]}
    verdetto = mj.riga_verdetto(ris)
    assert verdetto.startswith("🚫 SCARTATO") and "~52 €" in verdetto and "~18 €" in verdetto and "almeno 50" in verdetto
    righe = mj.righe_messaggio(ris, "zimmermann")
    testo = "\n".join(righe)
    assert "da 45 a 60 €" in testo and "fiducia bassa" in testo and "Legit check non fatto" in testo
    assert "https://www.vinted.it/items/1-a" in testo and "Velocità" in testo


def test_messaggio_conferma_mostra_le_domande_del_legit_check_di_jev():
    from bot.jev import Autenticita
    a = Autenticita(("originale_plausibile", 0.8))
    a.dettagli = {"etichetta": ("coerente", 0.9), "made_in": ("incoerente", 0.7), "lavorazione": (None, None), "prova": ("nessuna", 0.9)}
    ris = {"esito": "conferma", "motivo": "ok", "n": 9, "rivendita": 140, "margine": 90, "roi": 200, "esempi": [], "autenticita": a, "gemini": None,
           "link_comps": [], "prezzi_comps": (120.0, 160.0)}
    testo = "\n".join(mj.righe_messaggio(ris))
    assert "fiducia alta" in testo and "etichetta: coerente (90%)" in testo and "made in: INCOERENTE (70%)" in testo and "lavorazione" not in testo
    assert mj.riga_verdetto(ris).startswith("✅ CONFERMATO")


def test_verifica_salta_il_legit_check_se_i_comparabili_scartano(monkeypatch):
    import asyncio
    comps = [("Zimmermann nightwear", p) for p in (45.0, 52.5, 60.0)]

    async def cerca(url):
        return "x", True, {}
    chiamato = []
    monkeypatch.setattr(mj, "_cerca_vinted_testo_diretto", cerca)
    monkeypatch.setattr(mj, "parse_comp", lambda r: comps)
    monkeypatch.setattr(mj, "solo_usato", lambda c: c)
    monkeypatch.setattr(mj, "comparabili_simili", lambda c, t, b: c)
    monkeypatch.setattr(mj, "giudica_autenticita", lambda *a: chiamato.append("jev") or ("originale_plausibile", 0.9))
    monkeypatch.setattr(mj, "optimize_image_bytes", lambda b, n: b)
    monkeypatch.setattr(mj, "JEV_FOTO_COMPS", False)

    async def gemini(*a, **k):
        chiamato.append("gemini")
    monkeypatch.setattr(mj, "controlla_gemini", gemini)
    info = {"title": "Nightwear", "price": 25, "catalog_id": 123, "fair_value": {"brand": "zimmermann", "fv": 115}}
    ris = asyncio.run(mj.verifica(info, b"img", [b"img"]))
    assert ris["esito"] == "scarta" and ris["legit_saltato"] is True and chiamato == []
