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


def test_maglie_leggere_courreges_loewe_miumiu_a_prezzo_basso_si_scartano():
    for t, b, pr in [("Miu miu tshirt", "Miu Miu", "35"), ("bianca T-shirt", "Courrèges", "20"), ("Thanktop", "Loewe", "12"),
                     ("Trägerhemden", "Miu Miu", "5"), ("Black & White Ringer Tee / Size M", "Courreges", "30"), ("Bluse Rose", "Miu Miu", "22")]:
        assert m.check_skip_pre_gemini(_li(t, b, "", price=pr))[0], (t, b)
    # sopra il tetto, altre categorie e altri brand passano
    assert not m.check_skip_pre_gemini(_li("T-shirt Loewe", "Loewe", "", price="120"))[0]
    assert not m.check_skip_pre_gemini(_li("Giacca Loewe", "Loewe", "ottime condizioni", price="35"))[0]
    assert not m.check_skip_pre_gemini(_li("Pull Courreges", "Courrèges", "", price="20"))[0]
    assert not m.check_skip_pre_gemini(_li("T-shirt Prada", "Prada", "", price="20"))[0]


def test_parser_tracker_legge_la_query_e_non_la_scambia_per_titolo():
    p = m.parse_vinted_tracker_message("🔎 Query: Prada capispalla 50\n💰 40 €\n🏷️ Prada")
    assert p["query_name"] == "Prada capispalla 50" and p["title"] == m.TITOLO_NON_RILEVATO
    p = m.parse_vinted_tracker_message("📌 Giacca\n💰 40 €\n🏷️ Prada\n🔎 Query: Prada capispalla 50")
    assert p["title"] == "Giacca" and p["query_name"] == "Prada capispalla 50"
    assert m.parse_vinted_tracker_message("📌 Giacca\n💰 40 €")["query_name"] is None


def test_url_da_bottoni_distingue_annuncio_e_ricerca():
    from types import SimpleNamespace as B
    bottoni = [[B(url="https://www.vinted.it/items/9-giacca")], [B(url="https://www.vinted.it/catalog?brand_ids[]=1")]]
    assert m.url_da_bottoni(bottoni, "/items/") == "https://www.vinted.it/items/9-giacca"
    assert m.url_da_bottoni(bottoni, "/catalog") == "https://www.vinted.it/catalog?brand_ids[]=1"
    assert m.url_da_bottoni(None, "/items/") is None


def test_url_da_entita_trova_il_link_della_ricerca():
    from types import SimpleNamespace as E
    entita = [E(offset=0), E(url="https://www.vinted.it/catalog?brand_ids[]=1")]
    assert m.url_da_entita(entita, "/catalog") == "https://www.vinted.it/catalog?brand_ids[]=1"
    assert m.url_da_entita(None, "/catalog") is None
