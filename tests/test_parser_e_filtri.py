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
