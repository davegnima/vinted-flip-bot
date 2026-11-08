"""Verifica Jev dei brand nuovi della moda (bot/mj.py): URL dei comparabili, decisione, righe del messaggio."""
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
    assert any("Comparabili: 7" in x for x in r)
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
    assert not any("Foto vs" in r for r in righe)   # il confronto foto sta nel verdetto, non in una riga a parte (7/11)


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


def test_giallo_con_margine_e_roi_promettenti_va_a_jev_senza_invio_immediato(monkeypatch):
    import bot.fair_value as fvm
    from bot.fair_value import valuta_preavviso, REGOLA_DA_VERIFICARE
    monkeypatch.setattr(fvm, "PREAVVISO_TUTTI_A_JEV", False)
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
    assert verdetto.startswith("🚫 SCARTATO") and "~52 €" in verdetto and "~18 €" in verdetto and "almeno 40" in verdetto
    righe = mj.righe_messaggio(ris, "zimmermann")
    testo = "\n".join(righe)
    assert "da 45 a 60 €" in testo and "fiducia bassa" in testo and "Legit check non fatto" in testo
    assert "https://www.vinted.it/items/1-a" in testo and "Rotazione brand" in testo


def test_messaggio_conferma_mostra_le_domande_del_legit_check_di_jev():
    from bot.jev import Autenticita
    a = Autenticita(("originale_plausibile", 0.8))
    a.dettagli = {"etichetta": ("coerente", 0.9), "made_in": ("incoerente", 0.7), "lavorazione": (None, None), "prova": ("nessuna", 0.9)}
    ris = {"esito": "conferma", "motivo": "ok", "n": 9, "rivendita": 140, "margine": 90, "roi": 200, "esempi": [], "autenticita": a, "gemini": None,
           "link_comps": [], "prezzi_comps": (120.0, 160.0)}
    testo = "\n".join(mj.righe_messaggio(ris))
    assert "fiducia alta" in testo and "etichetta: coerente" not in testo   # il legit check e' nella riga Originalita', non sparso (7/11)
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


def test_valuta_moda_soglia_margine_40():
    """5/11 (utente): Jev scarta per margine solo sotto i 40 EUR; il radar resta a 50."""
    from bot.valore_mercato import valuta
    stima = {"mediana": 100.0, "n": 6, "prezzi": [90, 95, 100, 105, 110, 100], "conf": "media"}
    import inspect
    assert "margine_min" in inspect.signature(valuta).parameters
    assert mj.MODA_JEV_MARGINE_MIN == 40.0


def test_riga_originalita_mostra_subito_replica_dubbio_e_ok():
    """6/11 (utente): non declassare i confermati con 'replica probabile', ma far vedere subito se sono originali."""
    from bot.moda_jev import riga_originalita, riga_verdetto
    from bot.jev import Autenticita
    base = {"esito": "conferma", "motivo": "ok", "n": 5, "rivendita": 135.0, "margine": 103.0, "roi": 541.0}
    r = dict(base, autenticita=("replica_probabile", 0.36), gemini={"autenticita": "dubbia", "confidenza": 0.6})
    riga = riga_originalita(r)
    assert riga.startswith("🔐 Originalità: 🚨 FAKE") and "36%" in riga and "Gemini foto: dubbio (60%)" in riga
    assert riga_verdetto(r).startswith("✅ CONFERMATO") and "replica" not in riga_verdetto(r)   # l'originalita' ha la sua riga 🔐
    assert riga_originalita(dict(base, autenticita=("originale_plausibile", 0.76))).startswith("🔐 Originalità: ✅ LEGIT")
    assert riga_originalita(dict(base, autenticita=("non_chiaro", 0.4))).startswith("🔐 Originalità: ⚠️ DA CONTROLLARE (non chiara)")
    assert riga_originalita(dict(base, autenticita=None)).startswith("🔐 Originalità: ❔")
    assert riga_originalita(dict(base, esito="scarta", autenticita=("replica_probabile", 0.9))) is None
    assert riga_originalita(dict(base, legit_saltato=True)) is None
    a = Autenticita(("originale_plausibile", 0.7))
    a.dettagli = {"etichetta": ("incoerente", 0.8)}
    assert riga_originalita(dict(base, autenticita=a)).startswith("🔐 Originalità: ⚠️ DA CONTROLLARE")


def test_comparabili_tutti_diversi_dalla_foto_non_confermano():
    """6/11 (utente): sacca Miu Miu a 5 EUR, comparabili da 3 a 600 EUR giudicati 'diverso' dalle foto: niente CONFERMATO."""
    diversi = [("diverso", 0.9), ("diverso", 0.8), ("diverso", 0.9)]
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, diversi) == ("non_verificato", "comparabili_non_simili")
    # basta un comparabile simile per tenere la stima testuale; senza confronto foto nulla cambia
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, diversi + [("simile", 0.7)]) == ("conferma", "ok")
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, [("non_chiaro", 0.5)] * 2) == ("conferma", "ok")
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9)) == ("conferma", "ok")
    ris = {"esito": "non_verificato", "motivo": "comparabili_non_simili", "n": 4, "rivendita": 80.0, "margine": 64.0, "roi": 752.0,
           "prezzi_comps": (3.0, 600.0), "foto_comps": diversi}
    assert "non assomigliano alla foto" in mj.riga_verdetto(ris)
    assert any("NON simili alla foto" in r for r in mj.righe_messaggio(ris))


def test_prezzi_troppo_dispersi_non_confermano():
    """6/11 (utente): limite alla dispersione: p75/p25 sopra soglia = nessun prezzo di mercato."""
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, None, 3.4) == ("non_verificato", "prezzi_dispersi")
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, None, 1.5) == ("conferma", "ok")
    assert mj.decidi({"ok": True}, ("originale_plausibile", 0.9), None, None, None) == ("conferma", "ok")
    ris = {"esito": "non_verificato", "motivo": "prezzi_dispersi", "n": 4, "rivendita": 80.0, "margine": 64.0, "roi": 752.0, "dispersione": 3.4}
    assert "3.4 volte" in mj.riga_verdetto(ris)
    assert any("prezzi molto dispersi" in r for r in mj.righe_messaggio(ris))


def test_filtra_per_linea_weekend_non_e_max_mara():
    assert mj.linea_dal_testo("Cappotto Weekend Max Mara", "max mara") == "weekend max mara"
    comps = [("Cappotto Weekend Max Mara", 90.0), ("Cappotto Max Mara lana", 250.0), ("Cappotto Max Mara Studio", 120.0), ("Cappotto Sportmax", 100.0)]
    assert mj.filtra_per_linea(comps, "max mara", "weekend max mara") == [("Cappotto Weekend Max Mara", 90.0)]
    assert mj.filtra_per_linea(comps, "max mara", None) == [("Cappotto Max Mara lana", 250.0)]
    assert mj.filtra_per_linea(comps, "prada", None) == comps


def test_linea_da_descrizione_e_da_etichetta():
    assert mj.linea_dal_testo("Cappotto Max Mara", "max mara", "Cappotto Weekend Max Mara taglia 40") == "weekend max mara"
    assert mj.linea_dal_testo("Cappotto Max Mara", "max mara", "Indossato solo nel weekend, ottime condizioni") is None
    assert mj.linea_da_etichetta("Weekend", "max mara") == (True, "weekend max mara")
    assert mj.linea_da_etichetta("principale", "max mara") == (True, None)
    assert mj.linea_da_etichetta("non_leggibile", "max mara") == (False, None)


def test_serve_ombra_solo_brand_con_stima_poco_sicura_e_sotto_il_tetto(monkeypatch):
    mj._ombra_chiamate.clear()
    monkeypatch.setattr(mj, "MODA_JEV_OMBRA", True)
    monkeypatch.setattr(mj, "MODA_JEV_OMBRA_MAX_ORA", 2)
    assert not mj.serve_ombra({"brand": "cult gaia", "conf": "alta"})
    assert not mj.serve_ombra({"brand": None, "conf": "bassa"})
    assert mj.serve_ombra({"brand": "cult gaia", "conf": "bassa"}, adesso=1000)
    assert mj.serve_ombra({"brand": "cult gaia", "conf": "stima"}, adesso=1001)
    assert not mj.serve_ombra({"brand": "cult gaia", "conf": "bassa"}, adesso=1002)   # tetto orario
    assert mj.serve_ombra({"brand": "cult gaia", "conf": "bassa"}, adesso=5000)       # passata un'ora
    mj._ombra_chiamate.clear()


def test_fair_value_impara_dai_comparabili_jev(monkeypatch, tmp_path):
    from bot import fair_value as fvm
    monkeypatch.setattr(fvm, "FAIR_VALUE_APPRESO_FILE", str(tmp_path / "a.json"))
    righe = []
    for i in range(6):
        righe.append({"tipo": "rapida", "item_id": str(i), "brand": "cult gaia", "categoria": "vestito", "molt": 1.0})
        righe.append({"tipo": "jev", "item_id": str(i), "vendita": 150.0, "n": 8, "dispersione": 1.6, "valido": True})
    righe.append({"tipo": "rapida", "item_id": "x", "brand": "cult gaia", "categoria": "vestito", "molt": 1.0})
    righe.append({"tipo": "jev", "item_id": "x", "vendita": 900.0, "n": 8, "dispersione": 4.0, "valido": False})   # non valido: ignorato
    nuovo = fvm.fv_ricalibra(righe)
    assert nuovo["cult gaia|vestito"]["n"] == 6
    assert nuovo["cult gaia|vestito"]["fv"] == 150


def test_messaggio_recuperato_si_compone_senza_riga_finale():
    from bot.scheda import testo_preavviso
    li = {"title": "Robe Sea New York", "price": 49, "brand": "Sea New York", "fair_value": {"brand": "sea new york", "semaforo": "🔴", "fv": 58, "margine": 9, "roi": 18, "conf": "bassa", "minimo": 34, "massimo": 98},
          "righe_jev": ["🔎 12 comparabili 90-200 €"], "riga_verdetto_jev": "✅ CONFERMATO: rivendita ~140 €", "rivendita_jev": 140.0}
    t = testo_preavviso(li, "https://www.vinted.it/items/1-x", riga_finale="")
    assert "CONFERMATO" in t and "vinted.it/items/1" in t


def test_lancel_in_blocklist_brand():
    from bot.filtri import check_skip_pre_gemini
    skip, motivo = check_skip_pre_gemini({"brand": "Lancel", "title": "Sac Lancel noir", "price": 30})
    assert skip and "BLOCKLIST" in motivo


def test_gemini_condizioni_difetti_correggono_la_rivendita():
    """7/11 (utente): Gemini legge anche difetti, materiale e modello; i difetti abbassano la rivendita dei comparabili (con tetto per gravita')."""
    from bot import moda_gemini as g
    from bot.moda_jev import correggi_per_difetti, riga_verdetto, righe_messaggio
    from bot.valore_mercato import stima_mercato, valuta
    d = g.leggi_risposta('{"autenticita":"probabile","confidenza":0.8,"capo":"cardigan","materiale":"100% cashmere","condizione":"buona",'
                         '"difetti":"alone 3 cm sul petto","gravita_difetti":"moderata","sconto_difetti_pct":80,"rivendita_gemini_eur":70,'
                         '"rivendita_confidenza":0.7,"rivendita_base":"base"}')
    assert g.sconto_difetti(d) == 35.0   # tetto della gravita' 'moderata', anche se Gemini chiede 80
    assert g.sconto_difetti(g.leggi_risposta('{"autenticita":"probabile","confidenza":0.8,"gravita_difetti":"nessuno","difetti":""}')) == 0.0
    assert g.sconto_difetti(None) == 0.0
    assert g.sconto_difetti(g.leggi_risposta('{"autenticita":"probabile","confidenza":0.8,"gravita_difetti":"grave","difetti":"strappo"}')) == 40.0   # predefinito
    stima = stima_mercato([100.0, 105.0, 110.0, 95.0, 100.0], min_n=3)
    v = valuta(30.0, stima, margine_min=mj.MODA_JEV_MARGINE_MIN)
    nuovo, pct = correggi_per_difetti(v, 30.0, d)
    assert pct == 35.0 and nuovo["rivendita"] < v["rivendita"] and nuovo["margine"] < v["margine"]
    assert nuovo["rivendita_prima_difetti"] == v["rivendita"]
    assert correggi_per_difetti(v, 30.0, None) == (v, 0.0) and correggi_per_difetti(None, 30.0, d) == (None, 0.0)
    # un affare che resta tale dopo lo sconto resta confermato; uno che non regge diventa scarto
    forte, _ = correggi_per_difetti(valuta(10.0, stima, margine_min=40.0), 10.0, d)
    assert forte["ok"]
    debole, _ = correggi_per_difetti(valuta(60.0, stima, margine_min=40.0), 60.0, dict(d, gravita_difetti="grave", sconto_difetti_pct=60))
    assert not debole["ok"]
    righe = righe_messaggio({"rivendita": nuovo["rivendita"], "n": 5, "margine": nuovo["margine"], "roi": nuovo["roi"], "esempi": [], "autenticita": None,
                             "gemini": d, "sconto_difetti": pct, "rivendita_prima_difetti": v["rivendita"]})
    assert any("difetti moderata" in r and "alone" in r for r in righe)
    assert any("Difetti −35%" in r for r in righe)
    assert "difetti −35%" in riga_verdetto({"esito": "conferma", "motivo": "ok", "n": 5, "rivendita": 80, "margine": 40, "roi": 130, "sconto_difetti": 35.0})
    # stima di Gemini molto sotto i comparabili con buona confidenza: avviso (solo informativo)
    assert "molto meno" in g.riga_stima_gemini(dict(d, rivendita_gemini_eur=30), 100)
    assert "molto meno" not in g.riga_stima_gemini(d, 100)


def test_gemini_prevale_su_jev_replica_debole_e_recuperato_con_foto():
    """7/11 (utente): Jev 51% replica contro Gemini 95% coerente: prevale Gemini, niente 'possibile replica'."""
    from bot.moda_jev import decidi, gemini_prevale, riga_originalita, riga_verdetto
    from bot.scheda import testo_preavviso
    g = {"autenticita": "probabile", "confidenza": 0.95}
    assert gemini_prevale(("replica_probabile", 0.51), g)
    assert not gemini_prevale(("replica_probabile", 0.8), g)
    assert not gemini_prevale(("replica_probabile", 0.51), {"autenticita": "probabile", "confidenza": 0.7})
    assert not gemini_prevale(("replica_probabile", 0.51), {"autenticita": "dubbia", "confidenza": 0.95})
    assert not gemini_prevale(("altra_marca", 0.5), g)
    assert decidi({"ok": True}, ("replica_probabile", 0.65), g)[0] == "conferma"   # sopra la soglia di scarto di Jev, ma Gemini prevale
    assert decidi({"ok": True}, ("replica_probabile", 0.8), g)[0] == "scarta"
    ris = {"esito": "conferma", "motivo": "ok", "n": 10, "rivendita": 100.0, "margine": 71.0, "roi": 375.0, "autenticita": ("replica_probabile", 0.51), "gemini": g}
    assert riga_originalita(ris).startswith("🔐 Originalità: ✅ LEGIT") and "prevale Gemini" in riga_originalita(ris)
    assert "possibile replica" not in riga_verdetto(ris)
    t = testo_preavviso({"fair_value": {"semaforo": "🔴"}, "price": 50, "brand": "Ann", "title": "Pantalone", "righe_jev": ["x"], "riga_verdetto_jev": "v",
                         "rivendita_jev": 170, "riga_recupero": "♻️ Recuperato: prova"}, "https://www.vinted.it/items/1", riga_finale="")
    assert t.startswith("🔴 *Ann*") and t.split("\n")[1].startswith("♻️ Recuperato")


def test_messaggio_compatto_con_link_comparabili_nei_1024_caratteri():
    """7/11 (utente): la didascalia Telegram taglia a 1024 caratteri e il link dei comparabili spariva: ora sta subito sotto i numeri e le righe
    meno utili cadono per prime."""
    from bot.moda_jev import righe_messaggio
    from bot.scheda import testo_preavviso
    link = [("Pantaloni Missoni", p, f"https://www.vinted.it/items/{i}-missoni") for i, p in enumerate((80.0, 90.0, 95.0), 1)]
    ris = {"rivendita": 90.0, "n": 8, "margine": 40.0, "roi": 150.0, "esempi": [], "autenticita": None, "link_comps": link,
           "foto_comps": [("simile", 0.8)] * 3, "gemini": {"autenticita": "probabile", "confidenza": 0.9, "motivo": "x" * 120, "capo": "pantaloni", "materiale": "lana",
                                                          "condizione": "buona", "gravita_difetti": "nessuno", "difetti": "", "rivendita_gemini_eur": 60.0, "rivendita_confidenza": 0.7}}
    righe = righe_messaggio(ris, brand="missoni")
    assert righe[0].startswith("🔎") and righe[1].startswith("• 80 € https://www.vinted.it/items/1")
    info = {"fair_value": {"semaforo": "🟡", "fv": 40, "minimo": 30, "massimo": 70, "margine": 25, "conf": "alta"}, "price": 15, "brand": "Missoni", "title": "Pantaloni Missoni lunghi",
            "righe_jev": righe + ["y" * 150], "riga_verdetto_jev": "✅ CONFERMATO: rivendita ~90 €", "rivendita_jev": 90,
            "query_name": "Avanguardia Rick Yohji Dries AnnD Raf Loewe Lemaire Khaite 50", "query_url": "https://x.it/q"}
    t = testo_preavviso(info, "https://www.vinted.it/items/9")
    assert len(t) <= 1024 and t.count("https://www.vinted.it/items/") >= 4   # titolo + 3 comparabili


def test_riga_originalita_dice_cosa_fare_e_cosa_chiedere():
    """7/11 (utente, caso Lemaire): con autenticita' dubbia il messaggio dice cosa chiedere al venditore; con 'ok' nessuna riga in piu'."""
    from bot.moda_jev import riga_originalita
    base = {"esito": "conferma", "motivo": "ok", "n": 13, "rivendita": 330.0, "margine": 274.0, "roi": 1183.0}
    dubbio = dict(base, autenticita=("originale_plausibile", 0.6),
                  gemini={"autenticita": "dubbia", "confidenza": 0.6, "da_chiedere": "foto dell'etichetta di lavaggio con il made in"})
    riga = riga_originalita(dubbio)
    assert riga.startswith("🔐 Originalità: ⚠️ DA CONTROLLARE") and "\n👉 Prezzo buono ma originalità non verificata: prima chiedi foto dell'etichetta" in riga
    assert "chiedi al venditore foto di etichette" in riga_originalita(dict(base, autenticita=None))   # ripiego senza richiesta di Gemini
    assert "Non comprare" in riga_originalita(dict(base, autenticita=("originale_plausibile", 0.9), gemini={"autenticita": "replica", "confidenza": 0.5}))
    assert "\n" not in riga_originalita(dict(base, autenticita=("originale_plausibile", 0.8), gemini={"autenticita": "probabile", "confidenza": 0.9}))


def test_rivendita_mista_pesa_semaforo_comparabili_e_gemini_e_li_mostra_in_testata():
    """7/11 (utente): prezzo di rivendita bilanciato tra semaforo, comparabili e Gemini, con i tre valori tra parentesi nell'intestazione."""
    from bot.moda_jev import rivendita_mista
    from bot.moda_jev import parti_rivendita_testo, riga_verdetto as riga_verdetto_v
    from bot.scheda import testo_preavviso
    # tre stime: pesi 0,2 (semaforo media) + 0,4 (comparabili 5) + 0,28 (Gemini 0,7 x 0,4)
    mix, parti = rivendita_mista({"fv": 100, "conf": "media"}, 200, 5, {"rivendita_gemini_eur": 150, "rivendita_confidenza": 0.7})
    assert parti == {"semaforo": 100.0, "comparabili": 200.0, "gemini": 150.0}
    assert abs(mix - (100 * 0.2 + 200 * 0.4 + 150 * 0.28) / 0.88) < 0.01
    # Gemini poco sicuro o assente: non entra; nessuna stima: (None, {})
    assert "gemini" not in rivendita_mista({"fv": 100, "conf": "alta"}, 200, 9, {"rivendita_gemini_eur": 150, "rivendita_confidenza": 0.3})[1]
    assert rivendita_mista(None, None, 0, None) == (None, {})
    assert rivendita_mista({"fv": 80, "conf": "bassa"}, None, 0, None) == (80.0, {"semaforo": 80.0})
    assert parti_rivendita_testo(parti) == " (semaforo 100 · comparabili 200 · Gemini 150)" and parti_rivendita_testo({"semaforo": 80.0}) == ""
    ris = {"esito": "conferma", "rivendita": 160.0, "margine": 110.0, "roi": 550.0, "parti_rivendita": parti}
    assert riga_verdetto_v(ris) == "✅ CONFERMATO · rivendita ~160 € (semaforo 100 · comparabili 200 · Gemini 150) · margine ~110 € · ROI 550%"


def test_messaggio_stile_aerei_identificazione_esito_azione_poi_dettagli():
    """8/11 (utente: 'capisco dopo troppe righe di che oggetto parliamo'): prima brand, titolo e prezzo, poi esito, originalita', azione, riga vuota, dettagli."""
    from bot.scheda import testo_preavviso
    li = {"fair_value": {"semaforo": "🟡"}, "price": 20, "brand": "Jean Paul Gaultier", "title": "Maglia donna", "condition": "Ottime",
          "righe_jev": ["🔎 Comparabili: 14"], "riga_verdetto_jev": "✅ CONFERMATO · rivendita ~119 € · margine ~83 € · ROI 343%",
          "riga_originalita_jev": "🔐 Originalità: ⚠️ DA CONTROLLARE\n👉 Prima chiedi: etichetta"}
    righe = testo_preavviso(li, "https://www.vinted.it/items/1").split("\n")
    assert righe[0] == "🟡 *Jean Paul Gaultier* · [Maglia donna](https://www.vinted.it/items/1) · *20 €*"
    assert righe[1].startswith("✅ CONFERMATO") and righe[2].startswith("🔐 Originalità") and righe[3].startswith("👉") and righe[4] == ""
    assert righe[5].startswith("✨") and "🔎 Comparabili: 14" in righe
    testo = "\n".join(righe)
    assert testo.count("20 €") == 1 and "➜" not in testo and "🚦" not in testo and "💶" not in testo   # niente ripetizioni del prezzo


def test_evereve_in_blocklist_brand():
    from bot.filtri import check_skip_pre_gemini
    skip, motivo = check_skip_pre_gemini({"brand": "Evereve", "title": "Evereve dress", "price": 20})
    assert skip and "BLOCKLIST" in motivo


def test_tutti_a_jev_mirato_verdi_gialli_e_rossi_di_brand_scelti(monkeypatch):
    import bot.fair_value as fvm
    monkeypatch.setattr(fvm, "PREAVVISO_TUTTI_A_JEV", True)
    monkeypatch.setattr(fvm, "PREAVVISO_ROSSI_A_JEV", {"max mara"})
    da = fvm.REGOLA_DA_VERIFICARE
    # 8/11 (utente): recuperare i veloci scartati dal semaforo senza aprire tutto
    assert fvm.valuta_preavviso({"semaforo": "🟢", "margine": 0, "conf": "media", "brand": "missoni", "fv": 10}, 5) == (True, da)
    assert fvm.valuta_preavviso({"semaforo": "🟡", "margine": 5, "conf": "media", "brand": "prada", "fv": 40}, 25) == (True, da)
    assert fvm.valuta_preavviso({"semaforo": "🔴", "margine": -5, "conf": "media", "brand": "max mara", "fv": 40}, 50) == (True, da)
    assert fvm.valuta_preavviso({"semaforo": "🔴", "margine": -5, "conf": "media", "brand": "prada", "fv": 40}, 50) == (False, "no")
    assert fvm.valuta_preavviso(None, 20) == (False, "no")
    assert fvm.valuta_preavviso({"semaforo": "🟢", "brand": "marni"}, 20) == (False, "no")   # brand escluso
    assert fvm.valuta_preavviso({"semaforo": "🟢", "brand": "prada"}, 0) == (False, "no")


def test_azione_codice():
    assert mj.azione_codice({"esito": "scarta"}) == "scartato"


def test_semaforo_da_verificare_si_ferma_con_abbastanza_campioni_appresi(monkeypatch):
    monkeypatch.setattr(mj, "FAIR_VALUE_APPRESO", {"prada|gilet": {"n": 5}, "prada|gonna": {"n": 2}})
    monkeypatch.setattr(mj, "MODA_JEV_OMBRA_CAMPIONI_MIN", 5)
    assert not mj.semaforo_da_verificare({"brand": "prada", "categoria": "gilet", "conf": "alta"})    # verificato: stop
    assert mj.semaforo_da_verificare({"brand": "prada", "categoria": "gonna", "conf": "alta"})       # pochi campioni
    assert mj.semaforo_da_verificare({"brand": "prada", "categoria": "borsa", "conf": "media"})      # nessun campione
    assert mj.semaforo_da_verificare({"brand": "sezane", "categoria": "camicia", "conf": "bassa"})
    assert not mj.semaforo_da_verificare({"brand": "prada", "categoria": None, "conf": "alta"})


def test_url_comparabili_ordine_configurabile():
    assert mj.url_comparabili("zimmermann", "abito", 10).endswith("&order=newest_first")
    assert mj.url_comparabili("zimmermann", "abito", 10, "relevance").endswith("&order=relevance")
    assert "order=price_low_to_high" in mj.url_comparabili("marchio inesistente", "giacca", 5, "price_low_to_high")


def test_riga_stima():
    assert mj._riga_stima(None) == "n=0"
    assert mj._riga_stima({"n": 8, "p25": 40.0, "mediana": 55.0, "p75": 70.0}) == "n=8|p25=40|med=55|p75=70|disp=1.75"
