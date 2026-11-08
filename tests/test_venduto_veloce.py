from bot import tracciamento as t


def test_venduto_veloce_con_margine_del_verdetto():
    assert t.venduto_veloce_da_inviare({"margine": "55", "fv": 90}, 30, "AFFARE")
    assert not t.venduto_veloce_da_inviare({"margine": "39", "fv": 90}, 30, "AFFARE")


def test_venduto_veloce_senza_verdetto_usa_fair_value_meno_prezzo():
    assert t.margine_venduto_veloce({"fv": 80}, 30) == 50
    assert t.venduto_veloce_da_inviare({"fv": 80}, 30, "MEDIO AFFARE")
    assert not t.venduto_veloce_da_inviare({"fv": 60}, 30, "AFFARE")


def test_venduto_veloce_solo_classi_veloci_e_una_volta():
    assert not t.venduto_veloce_da_inviare({"fv": 200}, 30, "NORMALE")
    assert not t.venduto_veloce_da_inviare({"fv": 200}, 30, None)
    assert not t.venduto_veloce_da_inviare({"fv": 200, "_veloce_inviato": True}, 30, "AFFARE")
    assert not t.venduto_veloce_da_inviare({}, 30, "AFFARE")


def test_testo_venduto_veloce():
    ctx = {"fv": 90, "esito": "SKIP_SOLO_SEMAFORO", "sem": "🟢", "_titolo": "Giacca Burberry", "preavviso": "no"}
    testo = t.testo_venduto_veloce("1", "https://www.vinted.it/items/1", "Burberry", 30, 140, "AFFARE", ctx)
    assert "Venduto in 2 min" in testo and "margine ~60 €" in testo and "NON avvisato" in testo
    ctx["preavviso"] = "si"
    assert "NON avvisato" not in t.testo_venduto_veloce("1", "u", "B", 30, 140, "AFFARE", ctx)
