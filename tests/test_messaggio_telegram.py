import asyncio

import main_telethon as m


def _comp(prezzo, titolo):
    return {"titolo_verbatim": f"{titolo} — €{prezzo:.2f}", "prezzo_eur": float(prezzo), "fonte": "vinted_testo",
            "fonte_reale": "vinted_testo", "escluso": False}


def _v():
    return m.valida_payload_cervello({
        "prezzo_target_vendita_eur": 60, "comp_riferimento_eur": 66, "legit_verdetto": "probabilmente_autentico",
        "corrispondenza_brand": "corrisponde", "domanda_mercato": "media", "segnali_domanda": [],
        "materiale_confermato": True, "difetto_strutturale": False, "sconto_difetto_pct": 0,
        "sconto_ask_applicato_pct": 25, "fascia_taglia": "centrale",
        "note_analista": "Camicia mainline in cotone.", "legit_motivo_specifico": "Etichetta serif pulita.",
        "motivo_profilo_venditore": "Venditore privato con 25 recensioni.",
        "comp_candidati": [_comp(120, "Chemise Dries Van Noten"), _comp(85, "Chemise en coton taille 40")],
        "linea_o_era_rilevata": "mainline", "rischio_fake": "basso", "confidenza": "alta", "deal_score": 8,
        "giorni_stimati_vendita": 35, "messaggio_venditore_template": "Ciao! {OFFERTA}?", "domande_al_venditore": [],
    })[0]


LISTING = {
    "title": "Shirt dries van noten", "brand": "Dries van Noten", "price": "35", "condition": "Nuovo senza cartellino",
    "material_raw": "Cotone", "color_raw": "Cachi, Multi",
    "uploaded_text": "Proprio adesso, Shirt dries van notes 38 like new cotton, Spedizione",
    "seller_login": "augusta", "seller_feedback_reputation": 4.8, "seller_feedback_count": 25,
    "description": "Shirt dries van notes 38 like new cotton",
    "fair_value": {"fv": 65, "minimo": 35, "massimo": 94, "roi": 86, "semaforo": "🟡", "conf": "media"},
}


def _componi():
    v = _v()
    verdetto = m.calcola_verdetto(v, 35.0)
    out = m.render_messaggio_verdetto(v, verdetto, [], {"n_memoria": 0, "n_prezzi_pool": 6, "n_comp": 2})
    return m.componi_testi_verdetto(LISTING, verdetto, out, "", "60/60/95", True, url="https://www.vinted.it/items/1-x")


def test_unificato_ogni_dato_una_volta_sola():
    _, _, uni = _componi()
    assert uni.count("Shirt dries van noten") == 1       # titolo
    assert uni.count("Dries van Noten") == 1             # brand
    assert uni.count("vinted.it/items") == 2              # link dopo la decisione e in fondo
    assert uni.rstrip().endswith("[Apri su Vinted](https://www.vinted.it/items/1-x)")
    assert uni.count("Fair value") == 1 and uni.count("Gemini ~") == 1
    assert "stima instabile 60/60/95" in uni
    assert "~35gg" not in uni
    assert uni.count("augusta") == 1                      # venditore
    assert "like new cotton" not in uni                   # descrizione = titolo con refuso: omessa


def test_unificato_prima_riga_ha_verdetto_prezzo_brand():
    _, _, uni = _componi()
    righe = uni.splitlines()
    assert any(d in righe[0] for d in ("COMPRA", "TRATTA")) and "[vedi su Vinted](https://www.vinted.it/items/1-x)" in righe[0]
    assert "💶 35,00 €" in righe[1] and "Dries van Noten" in righe[1]


def _compatto(url="https://www.vinted.it/items/1-x"):
    v = _v()
    verdetto = m.calcola_verdetto(v, 35.0)
    out = m.render_messaggio_verdetto(v, verdetto, [], {"n_memoria": 0, "n_prezzi_pool": 6, "n_comp": 2})
    return m.componi_testi_verdetto(LISTING, verdetto, out, "", "60/60/95", False, url=url, v=v,
                                    footer_compatto="💵 $0.037 · ⏱ 32s")[2]


def test_messaggio_compatto_contenuto_e_breve():
    t = _compatto()
    righe = t.splitlines()
    assert righe[0].endswith("[vedi su Vinted](https://www.vinted.it/items/1-x)") and "COMPRA" in righe[0]
    assert "→ 🎯" in righe[1] and "ROI" in righe[1]                  # acquisto (spese incluse) -> atteso
    assert "Dries van Noten" in righe[2] and "Shirt dries van noten" in righe[2] and "~35 gg" in righe[2]
    assert "🧠 Camicia mainline in cotone." in t
    assert t.rstrip().endswith("💵 $0.037 · ⏱ 32s")
    assert "📊 Comp:\n• €120 · Chemise Dries Van Noten" in t and "---" not in t
    assert "🎯 4/10" in t                                            # NON COMPRARE: score del modello (8) riportato in fascia


def _markdown_legacy_valido(testo):
    """Controllo grezzo del parser Markdown legacy di Telegram: *, _ e ` fuori dai link devono essere pari."""
    import re
    senza_link = re.sub(r"\]\([^)]*\)", "]", testo)
    senza_escape = senza_link.replace("\\_", "").replace("\\*", "").replace("\\`", "")
    return all(senza_escape.count(c) % 2 == 0 for c in "*_`")


def test_messaggio_compatto_markdown_valido_e_tappe_senza_underscore():
    assert _markdown_legacy_valido(_compatto())
    nome = m._formatta_tappe_pipeline([("a", 0.0), ("campioni_target", 7.0)])[0]
    assert "_" not in nome


def test_caricato_senza_descrizione():
    assert m._riga_caricato_annuncio(LISTING) == "🕒 Caricato: Proprio adesso"


def test_comp_con_prezzo_una_volta():
    _, _, uni = _componi()
    assert "• €120 · Chemise Dries Van Noten" in uni and "€120.00 — Chemise" not in uni


def test_standalone_non_ripete_url_e_titolo_una_volta():
    header, resto, _ = _componi()
    assert header.count("vinted.it") == 1 and header.count("Shirt dries van noten") == 1
    assert "Fair value" in header


def test_descrizione_informativa_resta():
    li = dict(LISTING, description="Taglia 38, indossata una volta, ottime condizioni, senza difetti, lavata a 30 gradi")
    assert m._descrizione_utile(li) is not None


def test_campione_extra_ritorna_il_verdetto_validato():
    async def chiama(sistema, testo, forza_ricerca=None, mappa_url_ricerche_extra=None):
        return _v(), None, 0.01, 0, []
    v2, problemi, costo = asyncio.run(m._campione_target_cervello(chiama, "x", False))
    assert v2["prezzo_target_vendita_eur"] == 60 and costo == 0.01

    async def rotta(*a, **k):
        return None, "errore", 0.02, 0, []
    assert asyncio.run(m._campione_target_cervello(rotta, "x", False)) == (None, [], 0.02)
