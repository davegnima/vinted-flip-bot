from bot.fair_value import valuta_preavviso
from bot.scheda import _scheda_annuncio_testo, dati_deboli


def _stima(sem, margine):
    return {"semaforo": sem, "margine": margine, "fv": 60, "minimo": 30, "massimo": 90, "roi": 150, "conf": "media",
            "sottolinea": None}


def test_preavviso_semaforo_verde_con_margine():
    assert valuta_preavviso(_stima("🟢", 40), 30) == (True, "semaforo")
    assert valuta_preavviso(_stima("🟢", 20), 60) == (False, "no")   # verde ma margine sotto soglia, prezzo non basso


def test_preavviso_prezzo_basso():
    assert valuta_preavviso(_stima("🟡", 22), 15) == (True, "prezzo_basso")
    assert valuta_preavviso(_stima("🟡", 22), 40) == (False, "no")
    assert valuta_preavviso(_stima("🟡", 10), 15) == (False, "no")


def test_preavviso_non_scatta_senza_stima_affidabile():
    assert valuta_preavviso(None, 10) == (False, "no")
    assert valuta_preavviso(_stima("⚪", 50), 10) == (False, "no")
    assert valuta_preavviso(_stima("🔴", 50), 10) == (False, "no")
    assert valuta_preavviso(_stima("🟢", 50), None) == (False, "no")


def test_scheda_con_preavviso_ha_il_fulmine_in_prima_riga():
    info = {"price": 15, "brand": "Prada", "title": "Gonna", "fair_value": _stima("🟢", 40), "preavviso": True}
    prima = _scheda_annuncio_testo(info, "https://www.vinted.it/items/1-x", 3).split("\n")[0]
    assert prima.startswith("⚡ 🟢 ~+40 €")
    info["preavviso"] = False
    assert not _scheda_annuncio_testo(info, "https://www.vinted.it/items/1-x", 3).startswith("⚡")


def test_dati_deboli():
    assert dati_deboli({"decisione": "COMPRA", "comp_usati": [{"p": 1}]})
    assert dati_deboli({"decisione": "TRATTA", "comp_usati": [{}, {}]}, stima_instabile=True)
    assert not dati_deboli({"decisione": "COMPRA", "comp_usati": [{}, {}]})
    assert not dati_deboli({"decisione": "NON COMPRARE", "comp_usati": []}, stima_instabile=True)
