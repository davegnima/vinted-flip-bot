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


def test_taratura_brand_in_piu_della_globale():
    from bot.fair_value import FAIR_VALUE_TARATURA_GLOBALE, stima_fair_value
    base = {"title": "Maglia", "price": 10}
    miss = stima_fair_value({**base, "brand": "Missoni"})
    m_line = stima_fair_value({**base, "brand": "Missoni", "title": "M Missoni maglia"})
    cuc = stima_fair_value({**base, "brand": "Brunello Cucinelli"})
    assert FAIR_VALUE_TARATURA_GLOBALE == 1.20
    assert miss["moltiplicatore"] == round(1.20 * 1.10, 2)       # prima linea: +10% in piu'
    assert m_line["moltiplicatore"] == 1.2                       # sottolinea: solo la globale (o apprese)
    assert cuc["moltiplicatore"] == round(1.20 * 1.15, 2)


def _finti(monkeypatch):
    import asyncio  # noqa: F401
    from bot import scheda
    chiamate = []

    async def album(chat, foto, caption=None, disable_notification=False, parse_mode=None):
        chiamate.append(("album", len(foto), disable_notification, parse_mode))
        return 7

    async def foto1(chat, b, testo, url, disable_notification=False):
        chiamate.append(("foto", disable_notification))
        return 8

    async def testo(chat, t, url, item=None, disable_notification=False, reply_to=None):
        chiamate.append(("testo", disable_notification))
        return 9

    async def edit_cap(chat, mid, cap, url=None):
        chiamate.append(("edit_cap", mid, len(cap) <= 1024, bool(url)))
        return True

    async def edit_txt(chat, mid, t, url=None):
        chiamate.append(("edit_txt", mid))
        return True

    monkeypatch.setattr(scheda, "TELEGRAM_ALERT_CHAT_ID", "-100")
    monkeypatch.setattr(scheda, "telegram_send_media_group", album)
    monkeypatch.setattr(scheda, "telegram_send_photo_con_bottone", foto1)
    monkeypatch.setattr(scheda, "telegram_send_with_buttons", testo)
    monkeypatch.setattr(scheda, "telegram_edit_caption", edit_cap)
    monkeypatch.setattr(scheda, "telegram_edit_message", edit_txt)
    return scheda, chiamate


def test_preavviso_album_foto_o_testo(monkeypatch):
    import asyncio
    scheda, chiamate = _finti(monkeypatch)
    info = {"price": 15, "brand": "Prada", "title": "Gonna", "fair_value": _stima("🟢", 40)}
    u = "https://www.vinted.it/items/1-x"
    a = asyncio.run(scheda.invia_preavviso(info, u, [b"1", b"2", b"3"]))
    f = asyncio.run(scheda.invia_preavviso(info, u, [b"1"]))
    t = asyncio.run(scheda.invia_preavviso(info, u, []))
    assert [a["tipo"], f["tipo"], t["tipo"]] == ["album", "foto", "testo"]
    assert chiamate == [("album", 3, False, "Markdown"), ("foto", False), ("testo", False)]


def test_aggiorna_preavviso_col_verdetto_una_sola_volta(monkeypatch):
    import asyncio
    scheda, chiamate = _finti(monkeypatch)
    info = {"price": 15, "brand": "Prada", "title": "Gonna", "fair_value": _stima("🟢", 40)}
    u = "https://www.vinted.it/items/1-x"

    async def prova():
        stato = {"task_preavviso": asyncio.ensure_future(scheda.invia_preavviso(info, u, [b"1", b"2"]))}
        lungo = "🟢 *COMPRA*\n" + "x" * 3000
        assert await scheda.aggiorna_preavviso(stato, u, testo_verdetto=lungo)
        assert not await scheda.aggiorna_preavviso(stato, u, riga_finale="altro")   # gia' aggiornato
        return stato
    stato = asyncio.run(prova())
    assert stato["preavviso_aggiornato"]
    assert chiamate[-1] == ("edit_cap", 7, True, False)   # album: didascalia <= 1024, niente bottone


def test_didascalia_verdetto_taglia_a_paragrafi():
    from bot.scheda import didascalia_verdetto
    corto = "a\n\nb"
    assert didascalia_verdetto(corto) == corto
    testo = "testa\nriga\n\n" + "c" * 600 + "\n\n" + "d" * 600
    out = didascalia_verdetto(testo, 1024)
    assert out.endswith("c" * 600) and "d" not in out and len(out) <= 1024
    assert len(didascalia_verdetto("riga\n" * 400, 1024)) <= 1024
