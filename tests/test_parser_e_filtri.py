import main_telethon as m


def test_parser_tracker_con_brand_none_usa_il_titolo():
    p = m.parse_vinted_tracker_message("📌 Loro Piana\n💰 40 €\n🏷️ None")
    assert p["brand"] == "Loro Piana" and p["price"] == "40"


def test_parser_tracker_brand_esplicito_vince():
    assert m.parse_vinted_tracker_message("📌 Pull fendî\n💶 43\n🏷️ Fendi")["brand"] == "Fendi"


def test_parser_tracker_senza_brand_noto_resta_vuoto():
    assert m.parse_vinted_tracker_message("📌 Sweater blu\nBrand: None")["brand"] is None


def test_brand_da_titolo_parola_intera():
    assert m._brand_da_titolo("Cardigan Missoni M") == "Missoni"
    assert m._brand_da_titolo("giacca gannina") is None


def _li(titolo, brand, descrizione=None, **extra):
    li = {"title": titolo, "brand": brand}
    if descrizione is not None:
        li["description"] = descrizione
    li.update(extra)
    return li


def test_jacquemus_tshirt_esclusa_ma_non_il_francese_portee():
    assert m.check_skip_pre_gemini(_li("T-shirt Jacquemus", "Jacquemus", ""))[0]
    assert not m.check_skip_pre_gemini(_li("Robe Jacquemus", "Jacquemus", "jamais portee"))[0]


def test_loro_piana_blazer_scartato_solo_dopo_lo_scrape():
    assert m.check_skip_pre_gemini(_li("Blazer loro piana", "Loro Piana", "Taglia 50"))[0]
    assert not m.check_skip_pre_gemini(_li("Blazer loro piana", "Loro Piana"))[0]  # prima dello scrape: nessuna descrizione
    assert not m.check_skip_pre_gemini(_li("Giacca Loro Piana Storm System", "Loro Piana", ""))[0]


def test_borsa_nei_filtri_non_scarta_un_capo_normale():
    assert not m.check_skip_pre_gemini(_li("Cappotto Max Mara", "Max Mara", "ottime condizioni"))[0]


def test_foto_di_uno_schermo_non_scarta_piu():
    from bot.occhio import calcola_scarto_occhio
    base = {"etichette": [{"leggibilita": "leggibile"}], "cartellino_interno_leggibile": True}

    def scarto(segnali):
        return calcola_scarto_occhio({**base, "segnali_rischio_annuncio": segnali})

    assert not scarto(["foto_di_uno_schermo"])[0]
    assert not scarto(["capi_diversi_tra_le_foto"])[0]
    scartato, motivo = scarto(["watermark_di_altro_sito"])
    assert scartato and "ANNUNCIO FRAUDOLENTO" in motivo
    # insieme a un segnale che scarta, il motivo non cita quello declassato
    assert not scarto(["foto_stock_non_del_capo"])[0]
    _, motivo2 = scarto(["foto_di_uno_schermo", "foto_stock_non_del_capo", "watermark_di_altro_sito"])
    assert "watermark_di_altro_sito" in motivo2
    assert "foto_di_uno_schermo" not in motivo2 and "foto_stock_non_del_capo" not in motivo2


def test_descrivi_pagina_leggera_riporta_titolo_e_parole_di_blocco():
    from bot.vinted_scrape import descrivi_pagina_leggera
    h = ("<!DOCTYPE html><html lang=\"en\"><head><title>Access denied</title><script>var x=1;</script></head>"
         "<body><div>Please verify you are human</div></body></html>")
    d = descrivi_pagina_leggera(h)
    assert "Access denied" in d and "verify" in d and "denied" in d and "var x" not in d
    assert "nessuna" in descrivi_pagina_leggera("<html><body><p>ciao</p></body></html>")


def test_miumiu_top_e_canotte_si_scartano_a_qualunque_prezzo():
    assert m.check_skip_pre_gemini(_li("Canotta Miu Miu nera", "Miu Miu", "", price="150"))[0]
    assert m.check_skip_pre_gemini(_li("Top Miu Miu in raso", "Miu Miu", "", price="80"))[0]
    assert not m.check_skip_pre_gemini(_li("Cappotto Miu Miu", "Miu Miu", "ottime condizioni", price="150"))[0]


def test_paese_di_produzione_incoerente_col_brand():
    from bot.occhio import applica_paese_al_verdetto, calcola_scarto_occhio, paese_incoerente

    def occhio(testo, brand_letto="Prada", **extra):
        o = {"etichette": [{"tipo": "wash_care_tag", "testo_verbatim": testo, "leggibilita": "nitida"}],
             "brand_letto_etichetta": brand_letto, "relazione_brand": "corrisponde", "verdetto_legit": "probabilmente_autentico",
             "confidenza_legit": "alta", "segnali_rischio_annuncio": [], "difetti": []}
        o.update(extra)
        return o

    li = {"brand": "Prada", "title": "Maglione Prada"}
    assert paese_incoerente(occhio("PRADA MADE IN CHINA 100% WOOL"), li) == ("China", "Prada", "forte")
    assert paese_incoerente(occhio("Fabriqué en Chine"), li)[0] == "Chine"
    assert paese_incoerente(occhio("Made in P.R.C."), li) is not None
    assert paese_incoerente(occhio("MADE IN ITALY 100% LANA"), li) is None
    assert paese_incoerente(occhio("x", paese_produzione_letto="Vietnam"), li)[0] == "Vietnam"
    # brand "forte": scarto come falso; brand "medio": solo verdetto declassato; brand fuori tabella: nessuna regola
    scartato, motivo = calcola_scarto_occhio(occhio("PRADA MADE IN CHINA"), listing_info=li)
    assert scartato and motivo.startswith("[FALSO CONCLAMATO] Made in China su Prada")
    assert not calcola_scarto_occhio(occhio("PRADA MADE IN ITALY"), listing_info=li)[0]
    for brand in ("Brunello Cucinelli", "Loro Piana", "Fendi", "Bottega Veneta"):
        assert calcola_scarto_occhio(occhio("MADE IN CHINA", brand_letto=brand), listing_info={"brand": brand, "title": "x"})[0]
    mm = {"brand": "Max Mara", "title": "Cappotto"}
    o_mm = occhio("MADE IN CHINA", brand_letto="Max Mara")
    assert paese_incoerente(o_mm, mm) == ("China", "Max Mara", "medio")
    assert not calcola_scarto_occhio(o_mm, listing_info=mm)[0]
    v = {"legit_verdetto": "probabilmente_autentico", "legit_motivo_specifico": "etichetta ok"}
    assert applica_paese_al_verdetto(v, o_mm, mm) and v["legit_verdetto"] == "sospetto_servono_altre_foto"
    assert "Made in China" in v["legit_motivo_specifico"]
    v2 = {"legit_verdetto": "probabilmente_falso", "legit_motivo_specifico": "x"}
    assert applica_paese_al_verdetto(v2, o_mm, mm) is None and v2["legit_verdetto"] == "probabilmente_falso"
    acne = {"brand": "Acne Studios", "title": "Pull"}
    assert paese_incoerente(occhio("MADE IN CHINA", brand_letto="Acne Studios"), acne) is None   # Acne produce anche in Cina
