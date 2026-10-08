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
