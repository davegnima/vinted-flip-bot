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
