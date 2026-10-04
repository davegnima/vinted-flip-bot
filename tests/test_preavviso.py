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


def test_lingua_titolo_e_campi_annuncio():
    from bot.tracciamento import campi_annuncio, lingua_titolo
    assert lingua_titolo("Schulterfreies Oberteil von Dries van Noten M") == "de"
    assert lingua_titolo("Veste en laine taille 38") == "fr"
    assert lingua_titolo("Cappotto Max Mara lana") == "it"
    c = campi_annuncio({"title": "Cappotto Max Mara", "condition": "Molto buone", "size": "M | 40",
                        "seller_feedback_count": 12, "description": "ottimo"}, n_foto=5, adesso=0)
    assert c["cond"] == "Molto_buone" and c["taglia"] == "M_/_40" and c["n_foto"] == 5
    assert c["ora_utc"] == 0 and c["gs"] == 3 and c["lingua"] == "it" and c["v_rec"] == 12


def test_testo_preavviso_prima_riga_e_dettagli():
    from bot.scheda import testo_preavviso
    info = {"price": 15, "brand": "Prada", "title": "Gonna lana", "condition": "Buone", "size": "M",
            "fair_value": _stima("🟢", 40)}
    t = testo_preavviso(info, "https://www.vinted.it/items/1-x")
    assert t.split("\n")[0].startswith("⚡ 🟢 ~+40 €")
    assert "Gonna lana" in t and "preavviso" in t


def test_ogni_annuncio_con_brand_ha_un_semaforo():
    from bot.fair_value import stima_fair_value
    # brand nuovo, titolo senza categoria: stima generica con confidenza bassa ma COLORATA
    s = stima_fair_value({"brand": "Brand Mai Visto", "title": "Pezzo bellissimo", "price": 10})
    assert s and s["conf"] == "bassa" and s["semaforo"] in ("🟢", "🟡", "🔴")
    assert s["categoria"] is None and s["fonte_categoria"] == "nessuna"
    # Prada senza riga in tabella ora ha una stima
    s2 = stima_fair_value({"brand": "Prada", "title": "Maglia lana", "price": 20})
    assert s2 and s2["semaforo"] and s2["categoria"] == "maglia"
    assert stima_fair_value({"brand": "?", "title": "x", "price": 10}) is None


def test_stima_bassa_richiede_soglie_piu_alte():
    from bot.fair_value import stima_fair_value
    ec = stima_fair_value({"brand": "Brand Mai Visto", "title": "Pezzo", "price": 1})
    assert ec["semaforo"] == "🟢"
    ec2 = stima_fair_value({"brand": "Brand Mai Visto", "title": "Pezzo", "price": 40})
    assert ec2["semaforo"] == "🔴"


def test_categoria_dal_catalogo_vinted():
    from bot import fair_value as fv
    assert fv.categoria_annuncio({"title": "Pezzo", "catalog_id": "532"}) == ("giacca", "catalogo")   # seme: blazer donna
    assert fv.categoria_annuncio({"title": "Cappotto lana"}) == ("cappotto", "titolo")
    assert fv.categoria_annuncio({"title": "Pezzo", "description": "bella gonna"}) == ("gonna", "descrizione")
    for _ in range(4):
        fv.catalogo_impara("99999", "gonna")
    fv.catalogo_impara("99999", "abito")
    assert fv.categoria_da_catalogo("99999") == "gonna"   # 4 su 5 = 80% >= 70%
    assert fv.categoria_da_catalogo("11111") is None


def test_preavviso_non_scatta_con_stima_debole():
    assert valuta_preavviso({**_stima("🟢", 60), "conf": "bassa"}, 10) == (False, "no")
