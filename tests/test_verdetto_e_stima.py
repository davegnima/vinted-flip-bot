import main_telethon as m
from bot import gemini_stato as gs
from bot import panel as pn


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


def test_estrai_target_da_testo_llm():
    import main_telethon as m
    assert m.estrai_target_da_testo_llm('```json\n{"prezzo_target_vendita_eur": 120}\n```') == 120.0
    assert m.estrai_target_da_testo_llm('{"prezzo_target_vendita_eur": 0}') is None
    assert m.estrai_target_da_testo_llm('{"prezzo_target_vendita_eur": true}') is None
    assert m.estrai_target_da_testo_llm("niente json") is None
    assert m.estrai_target_da_testo_llm(None) is None


def test_estrai_json_da_testo_llm():
    import main_telethon as m
    assert m.estrai_json_da_testo_llm('ecco:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert m.estrai_json_da_testo_llm("[1,2]") is None
    assert m.estrai_json_da_testo_llm("{rotto") is None


def test_panel_tetto_orario(monkeypatch):
    import main_telethon as m
    monkeypatch.setattr(pn, "PANEL_MAX_ANNUNCI_ORA", 2)
    monkeypatch.setattr(pn, "_panel_ingressi", [])
    assert m._panel_ammesso(1000) and m._panel_ammesso(1001)
    assert not m._panel_ammesso(1002)
    assert m._panel_ammesso(1000 + 3601)   # la finestra scorre


def test_riga_panel_occhio_senza_collisioni(caplog):
    import logging
    import main_telethon as m
    o, problemi = m.valida_payload_occhio({"verdetto_legit": "probabilmente_autentico", "modello_riconosciuto": "giacca X", "motivo_sintetico": "font | etichetta ok"})
    with caplog.at_level(logging.INFO):
        m._riga_panel("occhio", "1", "Prada", "PRIMARIO", True, 0, **m._campi_occhio_panel(o, problemi))
    assert "PANEL | occhio | 1 | Prada | PRIMARIO | ok" in caplog.text and "capo=giacca X" in caplog.text and "motivo_legit=font / etichetta ok" in caplog.text and "legit=probabilmente_autentico" in caplog.text


def test_prompt_cervello_compatto_contiene_tutte_le_chiavi():
    import main_telethon as m
    p = m.prompt_cervello_compatto()
    for k in m.CERVELLO_RESPONSE_SCHEMA_OPENAI["properties"]:
        assert k + ":" in p
    assert len(p) < len(m.GEMINI_CERVELLO_SYSTEM_PROMPT) / 3


def test_panel_scelta_modelli_rotazione_pausa_ed_esclusione_principale(monkeypatch):
    import main_telethon as m
    monkeypatch.setattr(pn, "_panel_pausa", {})
    monkeypatch.setattr(pn, "_panel_giro", {"occhio": 0, "cervello": 0})
    lista = [f"gemini/{m.GEMINI_MODEL_CERVELLO}", "a/1", "b/2@c", "c/3", "d/4"]
    monkeypatch.setattr(pn, "PANEL_MODELLI_PER_ANNUNCIO", 0)
    assert m.panel_scegli_modelli("cervello", lista, adesso=100) == ["a/1", "b/2@c", "c/3", "d/4"]   # niente modello principale
    monkeypatch.setattr(pn, "PANEL_MODELLI_PER_ANNUNCIO", 2)
    assert m.panel_scegli_modelli("cervello", lista, adesso=100) == ["a/1", "b/2@c"]
    assert m.panel_scegli_modelli("cervello", lista, adesso=100) == ["c/3", "d/4"]
    assert m.panel_scegli_modelli("cervello", lista, adesso=100) == ["a/1", "b/2@c"]                 # giro completo
    m._panel_segna_errore("a/1", "http429", adesso=100)                                                # quota finita
    monkeypatch.setattr(pn, "PANEL_MODELLI_PER_ANNUNCIO", 0)
    assert "a/1" not in m.panel_scegli_modelli("cervello", lista, adesso=100 + 60)
    assert "a/1" in m.panel_scegli_modelli("cervello", lista, adesso=100 + 31 * 60)                    # pausa scaduta


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


def test_pausa_del_pannello_segue_il_reset_dichiarato_dal_provider():
    sec = pn.secondi_reset_da_corpo
    assert sec('{"reset_seconds":20796,"retry_after":"x"}') == 20796
    assert sec("[mistral/x] [429]: upstream error (reset after 3s)") == 3
    assert sec("Rate limit reached ... (reset after 4m 40s)") == 280
    assert sec("Please try again in 5m23.568s. Need more tokens?") == 5 * 60 + 23.568
    assert sec("errore generico") is None
    pn._panel_reset_s["x/1"] = 3
    pn._panel_segna_errore("x/1", "http429", adesso=1000)
    assert pn._panel_pausa["x/1"] == 1000 + 10                  # minimo 10 s, non i 30 minuti fissi
    pn._panel_segna_errore("y/2", "http429", adesso=1000)       # nessun tempo dichiarato: pausa standard
    assert pn._panel_pausa["y/2"] == 1000 + pn.PANEL_PAUSA_QUOTA_MIN * 60

def test_riserva_scala_sui_modelli_in_ordine_e_salta_quelli_in_pausa(monkeypatch):
    import asyncio
    import bot.riserva_llm as rl
    chiamati = []

    async def finta(modello, system, contenuto, max_tokens):
        chiamati.append(modello)
        if modello == "a/uno":
            return None, 5, "http429"
        if modello == "b/due":
            return "non e' json", 5, None
        return '{"prezzo_target_vendita_eur": 80}', 5, None

    monkeypatch.setattr(rl, "_panel_chiama", finta)
    monkeypatch.setattr(rl, "_panel_pausa", {})
    monkeypatch.setattr(pn, "_panel_pausa", rl._panel_pausa)
    lista = ["a/uno", "b/due@c", "c/tre"]
    ok = lambda d: d.get("prezzo_target_vendita_eur", 0) > 0
    d, modello = asyncio.run(rl._prova_in_ordine("cervello", lista, lambda c: "sys", "u", 100, ok))
    assert modello == "c/tre" and d["prezzo_target_vendita_eur"] == 80
    assert chiamati == ["a/uno", "b/due", "c/tre"]                      # il suffisso @c non arriva al gateway
    assert "a/uno" in rl._panel_pausa                                     # il 429 mette il modello in pausa
    chiamati.clear()
    asyncio.run(rl._prova_in_ordine("cervello", lista, lambda c: "sys", "u", 100, ok))
    assert chiamati == ["b/due", "c/tre"]                                 # a/uno e' in pausa: salta al successivo


def test_cascata_gemini_esaurita_solo_se_tutti_i_modelli_sono_senza_quota(monkeypatch):
    monkeypatch.setattr(gs, "GEMINI_CASCATA", ["m-top", "m-lite"])
    monkeypatch.setattr(gs, "GEMINI_CASCATA_OCCHIO", [])
    monkeypatch.setattr(gs, "GEMINI_API_KEYS", ["k1"])
    monkeypatch.setattr(gs, "_gemini_key_quota_esaurita_fino", {("k1", "m-top"): 9e12})
    assert gs.gemini_cascata_esaurita("occhio") is False
    gs._gemini_key_quota_esaurita_fino[("k1", "m-lite")] = 9e12
    assert gs.gemini_cascata_esaurita("occhio") is True


def test_reset_del_provider_vale_anche_per_i_modelli_con_suffisso_compatto():
    pn._panel_reset_s["x/9"] = 3
    pn._panel_segna_errore("x/9@c", "http429", adesso=500)
    assert pn._panel_pausa["x/9@c"] == 500 + 10
