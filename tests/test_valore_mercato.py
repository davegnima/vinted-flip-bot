from bot.valore_mercato import parse_comp, query_comp, solo_usato, stima_mercato, tetto_dal_nuovo, valuta

TESTO = "- Set posate Christofle 24 pezzi — €70,00\n- Posate argentate — €65.50\nrumore\n- Servizio posate — €80"


def test_parse_comp_formato_vinted():
    assert parse_comp(TESTO) == [("Set posate Christofle 24 pezzi", 70.0), ("Posate argentate", 65.5), ("Servizio posate", 80.0)]
    assert parse_comp("") == [] and parse_comp(None) == []


def test_solo_usato_toglie_i_nuovi():
    comps = [("Borsa nuova con cartellino", 200.0), ("Borsa usata", 90.0), ("Sigillato mai aperto", 150.0)]
    assert solo_usato(comps) == [("Borsa usata", 90.0)]


def test_query_comp_marca_e_parole_utili():
    assert query_comp("Vendo set posate Christofle usato ottime condizioni", "Christofle") == "christofle set posate"


def test_stima_pochi_comparabili():
    assert stima_mercato([50, 60, 70]) is None


def test_stima_toglie_anomali_e_usa_p25():
    s = stima_mercato([60, 62, 65, 68, 70, 72, 75, 78, 80, 82, 5, 900])
    assert s["n"] == 10 and 60 <= s["rivendita"] <= 70 and s["affidabilita"] == "alta"


def test_tetto_dal_nuovo():
    assert tetto_dal_nuovo(100, 120) == 72.0
    assert tetto_dal_nuovo(50, 120) == 50
    assert tetto_dal_nuovo(100, None) == 100


def test_valuta_posate_a_7_euro():
    stima = stima_mercato([70, 72, 75, 78, 80, 82, 85, 88, 90, 95])
    v = valuta(7, stima)
    assert v["ok"] and v["margine"] >= 50 and v["roi"] >= 100


def test_valuta_prezzo_alto_non_passa():
    stima = stima_mercato([70, 72, 75, 78, 80, 82, 85, 88, 90, 95])
    assert not valuta(60, stima)["ok"]


def test_valuta_tetto_nuovo_abbassa():
    stima = stima_mercato([100, 105, 110, 115, 120, 125])
    v = valuta(30, stima, prezzo_nuovo=110)
    assert v["limitato_dal_nuovo"] and v["rivendita"] == 66.0


def test_valuta_senza_stima():
    assert valuta(10, None)["motivo"] == "pochi_comparabili"


def test_pezzi_e_ricambi():
    from bot.valore_mercato import e_un_pezzo
    assert e_un_pezzo("Quadrante Omega Seamaster Cosmic") == "quadrante"
    assert e_un_pezzo("Mouvement Omega Seamaster quartz") == "mouvement"
    assert e_un_pezzo("Omega Seamaster automatico 41 mm") is None


def test_comparabili_simili_tolgono_pezzi_e_fuori_tema():
    from bot.valore_mercato import comparabili_simili
    comps = [("Omega Seamaster Cosmic automatic orologio", 700.0), ("Quadrante Omega Seamaster Cosmic", 30.0),
             ("Omega Constellation donna", 500.0)]
    out = comparabili_simili(comps, "omega seamaster cosmic automatic", "omega")
    assert out == [("Omega Seamaster Cosmic automatic orologio", 700.0)]


def test_query_comp_al_massimo_quattro_parole():
    assert query_comp("Cocotte Le Creuset ceramica smaltata arancione 24 cm", "Le Creuset") == "le creuset cocotte ceramica"
