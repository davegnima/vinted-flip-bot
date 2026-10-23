import main_telethon as m
from bot import gemini_stato as gs


def test_consolida_target():
    c = m.consolida_target_cervello
    assert c([160]) == (160.0, 1.0, False)
    valore, spread, instabile = c([52, 160, 60])
    assert valore == 60 and instabile
    assert c([100, 110])[0] == 105 and not c([100, 110])[2]
    assert c([52, 160])[0] == 52  # con 2 campioni divergenti si tiene il piu' basso
    assert c([]) == (None, None, False)


def _v(target, **extra):
    v = {
        "prezzo_target_vendita_eur": target, "comp_riferimento_eur": target, "legit_verdetto": "probabilmente_autentico",
        "corrispondenza_brand": "corrisponde", "domanda_mercato": "media", "segnali_domanda": [],
        "materiale_confermato": True, "difetto_strutturale": False, "sconto_difetto_pct": 0,
        "sconto_ask_applicato_pct": 0, "fascia_taglia": "centrale",
    }
    v.update(extra)
    return v


def test_verdetto_deterministico_e_monotono_nel_target():
    # Stesso capo, stesso prezzo: piu' alto il target, mai un esito peggiore.
    ordine = {"NON COMPRARE": 0, "CHIEDI ALTRE FOTO": 1, "TRATTA": 2, "COMPRA": 3}
    esiti = []
    for target in (20, 60, 120, 250):
        r = m.calcola_verdetto(m.valida_payload_cervello(_v(target))[0], 20.0)
        assert r == m.calcola_verdetto(m.valida_payload_cervello(_v(target))[0], 20.0)  # puro
        esiti.append(ordine[r["decisione"]])
    assert esiti == sorted(esiti)
    assert esiti[0] == 0  # target 20 con acquisto 20: nessun margine


def test_margine_e_roi_coerenti():
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(120))[0], 20.0)
    assert r["margine"] is not None and r["roi"] is not None and r["margine"] > 0










def test_prompt_cervello_compatto_contiene_tutte_le_chiavi():
    import main_telethon as m
    p = m.prompt_cervello_compatto()
    for k in m.CERVELLO_RESPONSE_SCHEMA_OPENAI["properties"]:
        assert k + ":" in p
    assert len(p) < len(m.GEMINI_CERVELLO_SYSTEM_PROMPT) / 3




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


def test_cascata_per_fase_occhio_e_cervello(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_CASCATA", ["gen-1"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", ["occ-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_CERVELLO", ["cer-top", "cer-lite"])
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {})
    monkeypatch.setattr(gs, "_gemini_modello_escluso_fino", {})
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert "/models/occ-lite:" in gs._gemini_url_effettivo(url, "occhio")
    assert "/models/cer-top:" in gs._gemini_url_effettivo(url, "cervello")
    assert "/models/gen-1:" in gs._gemini_url_effettivo(url)                       # senza fase: cascata generica
    gs._gemini_segna_key_quota_esaurita("k1", "cer-top", 3600)
    assert "/models/cer-lite:" in gs._gemini_url_effettivo(url, "cervello")          # il Cervello scala...
    assert "/models/occ-lite:" in gs._gemini_url_effettivo(url, "occhio")            # ...l'Occhio non ne risente
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", [])
    assert gs.cascata_per("occhio") == ["gen-1"]                                     # fase non configurata: generica
    assert {"gen-1", "cer-top", "cer-lite"} <= gs.tutti_i_modelli_cascata()


def test_resellbot_disattivato_va_diretto_su_google(monkeypatch):
    import asyncio
    from bot import comps

    async def non_chiamare(*a, **k):
        raise AssertionError("Resellbot non deve essere chiamato")

    async def google(*a, **k):
        return "risultati google", True

    monkeypatch.setattr(comps, "RESELLBOT_ATTIVO", False)
    monkeypatch.setattr(comps, "_cerca_ebay_sold_via_resellbot", non_chiamare)
    monkeypatch.setattr(comps, "_serper_batch_query_ebay_sold", google)
    testo, ok, mappa = asyncio.run(comps._cerca_ebay_sold_con_fallback("Prada", "giacca", None, None))
    assert ok and "risultati google" in testo and "ASK" in testo and mappa == {}


def test_ruoli_gemini_dalla_stima_rapida_con_fallback_sul_prezzo():
    from bot import pipeline
    r = pipeline.ruoli_gemini
    assert r(20, {"semaforo": "🟢"}, 50) == (True, "occhio_alto", "cervello_alto", "stima")    # promettente anche se costa poco
    assert r(120, {"semaforo": "🟡"}, 50) == (True, "occhio_alto", "cervello_alto", "stima")
    assert r(120, {"semaforo": "🔴"}, 50) == (True, "occhio_alto", "cervello_alto", "prezzo")   # rosso ma sopra soglia: alto
    assert r(30, {"semaforo": "🔴"}, 50) == (False, "occhio", "cervello", "stima")             # rosso e sotto soglia: base
    assert r(80, {"semaforo": "⚪"}, 50) == (True, "occhio_alto", "cervello_alto", "prezzo")    # confidenza bassa: prezzo
    assert r(30, {"semaforo": "⚪"}, 50) == (False, "occhio", "cervello", "prezzo")
    assert r(80, None, 50) == (True, "occhio_alto", "cervello_alto", "prezzo")                  # nessuna stima: prezzo
    assert r(None, None, 50) == (False, "occhio", "cervello", "prezzo")


def test_cascata_fascia_alta_con_fallback_alla_base(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_CASCATA", [])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", ["occ-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_CERVELLO", ["cer-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO_ALTO", ["occ-top", "occ-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_CERVELLO_ALTO", [])
    assert gs.cascata_per("occhio_alto") == ["occ-top", "occ-lite"]
    assert gs.cascata_per("occhio") == ["occ-lite"]
    assert gs.cascata_per("cervello_alto") == ["cer-lite"]      # alta non configurata: vale la base della fase
    assert "occ-top" in gs.tutti_i_modelli_cascata()





def test_cascata_gemini_esaurita_solo_se_tutti_i_modelli_sono_senza_quota(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_CASCATA", ["m-top", "m-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", [])
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {("k1", "m-top"): 9e12})
    assert gs.gemini_cascata_esaurita("occhio") is False
    gs._gemini_key_quota_esaurita_fino[("k1", "m-lite")] = 9e12
    assert gs.gemini_cascata_esaurita("occhio") is True




def test_compra_capo_sottoprezzato():
    # 10 EUR con target 30 (x3, dopo lo sconto ASK di default del 25%): margine sotto i 25 EUR standard, ma COMPRA
    # per la via "sottoprezzato".
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(40))[0], 10.0)
    assert 15 <= r["margine"] < 25 and r["decisione"] == "COMPRA"
    assert any("sottoprezzato" in x for x in r["limiti_applicati"])
    # Stesso margine ma prezzo alto e rapporto basso: niente via sottoprezzato.
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(90))[0], 60.0)
    assert r["decisione"] != "COMPRA"
    # Il falso resta NON COMPRARE anche se sottoprezzato.
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(40, legit_verdetto="probabilmente_falso"))[0], 10.0)
    assert r["decisione"] == "NON COMPRARE"


def test_sospetto_con_margine_alto_diventa_compra():
    sospetto = _v(160, legit_verdetto="sospetto_servono_altre_foto")
    r = m.calcola_verdetto(m.valida_payload_cervello(sospetto)[0], 30.0)
    assert r["margine"] >= 80 and r["decisione"] == "COMPRA"
    # Margine sotto 80: resta CHIEDI ALTRE FOTO.
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(140, legit_verdetto="sospetto_servono_altre_foto"))[0], 30.0)
    assert r["margine"] < 80 and r["decisione"] == "CHIEDI ALTRE FOTO"
    # "non_verificabile" non compra mai.
    r = m.calcola_verdetto(m.valida_payload_cervello(_v(160, legit_verdetto="non_verificabile"))[0], 30.0)
    assert r["decisione"] == "CHIEDI ALTRE FOTO"
    # Senza un'etichetta NITIDA (caso Loewe 8/10: una foto da lontano, etichetta parziale) il sospetto non compra mai.
    from bot.occhio import applica_prove_al_verdetto
    v_s = m.valida_payload_cervello(sospetto)[0]
    applica_prove_al_verdetto(v_s, {"etichette": [{"tipo": "main_label", "leggibilita": "parziale"}]})
    assert v_s["_etichetta_nitida"] is False and m.calcola_verdetto(v_s, 30.0)["decisione"] == "CHIEDI ALTRE FOTO"
    applica_prove_al_verdetto(v_s, None)
    assert v_s["_etichetta_nitida"] is False
    applica_prove_al_verdetto(v_s, {"etichette": [{"tipo": "wash_care_tag", "leggibilita": "nitida"}]})
    assert v_s["_etichetta_nitida"] is True and m.calcola_verdetto(v_s, 30.0)["decisione"] == "COMPRA"


def test_compra_senza_etichetta_interna_per_brand_obbligatori_e_senza_etichetta_nitida():
    # caso Prada Sport 10/10: COMPRA con "manca il wash tag": con il solo marchio esterno nitido diventa CHIEDI ALTRE FOTO
    from bot.occhio import applica_prove_al_verdetto
    ok = _v(160)
    esterna = {"etichette": [{"tipo": "main_label", "leggibilita": "nitida"}]}
    v = m.valida_payload_cervello(ok)[0]
    applica_prove_al_verdetto(v, esterna, "Prada")
    r = m.calcola_verdetto(v, 30.0)
    assert r["decisione"] == "CHIEDI ALTRE FOTO" and any("etichetta" in x for x in r["limiti_applicati"])
    v = m.valida_payload_cervello(ok)[0]
    applica_prove_al_verdetto(v, esterna, "Jacquemus")                  # brand non obbligatorio: il marchio nitido basta
    assert m.calcola_verdetto(v, 30.0)["decisione"] == "COMPRA"
    v = m.valida_payload_cervello(ok)[0]
    applica_prove_al_verdetto(v, {"etichette": [{"tipo": "main_label", "leggibilita": "parziale"}]}, "Jacquemus")
    assert m.calcola_verdetto(v, 30.0)["decisione"] == "CHIEDI ALTRE FOTO"   # nemmeno uno straccio di etichetta nitida
    v = m.valida_payload_cervello(ok)[0]
    applica_prove_al_verdetto(v, {"etichette": [{"tipo": "wash_care_tag", "leggibilita": "nitida"}]}, "Prada")
    assert m.calcola_verdetto(v, 30.0)["decisione"] == "COMPRA"
