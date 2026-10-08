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


def test_riga_scarto_con_motivo_e_link(monkeypatch):
    from bot import scheda
    monkeypatch.setattr(scheda, "TELEGRAM_OWNER_CHAT_ID", "-1001234567890")
    r = scheda.riga_scarto_preavviso("[ANNUNCIO FRAUDOLENTO] Segnali sulle immagini: descrizione_incoerente_con_le_foto", 55)
    assert r.startswith("🚫 scartato prima del verdetto: ")
    assert "descrizione" in r and "https://t.me/c/1234567890/55" in r
    assert "analisi interrotta" in scheda.riga_scarto_preavviso(None, None, interrotta=True)
    monkeypatch.setattr(scheda, "TELEGRAM_OWNER_CHAT_ID", "123456")        # chat privata: niente link
    assert "t.me" not in scheda.riga_scarto_preavviso("motivo", 55)
    assert scheda.link_messaggio_chat_principale(None) is None


def test_rosso_sicuro_salta_il_cervello():
    from bot.fair_value import check_skip_rosso
    rosso = {"semaforo": "🔴", "conf": "media", "margine": -12, "fv": 30, "brand": "Prada", "categoria": "maglia"}
    assert check_skip_rosso({"fair_value": rosso, "price": 40})[0]
    assert not check_skip_rosso({"fair_value": rosso, "price": 60})[0]                            # sopra la soglia di prezzo
    assert not check_skip_rosso({"fair_value": {**rosso, "conf": "bassa"}, "price": 40})[0]        # stima debole
    assert not check_skip_rosso({"fair_value": {**rosso, "margine": 5}, "price": 40})[0]           # margine non negativo
    assert not check_skip_rosso({"fair_value": {**rosso, "semaforo": "🟡"}, "price": 40})[0]


def test_fascia_alta_solo_con_stima_solida():
    from bot.pipeline import ruoli_gemini
    verde = {"semaforo": "🟢", "conf": "media"}
    assert ruoli_gemini(20, verde)[0]
    assert not ruoli_gemini(20, {**verde, "conf": "stima"})[0]    # conoscenza di mercato: dal prezzo
    assert not ruoli_gemini(20, {**verde, "conf": "bassa"})[0]
    assert ruoli_gemini(60, {**verde, "conf": "bassa"})[0]


def test_fattori_target_riserva_e_campioni():
    from bot.riserva_llm import fattore_target_riserva
    from bot.verdetto import CERVELLO_CAMPIONI_EXTRA
    assert fattore_target_riserva("mistral/ministral-14b-2512@c") == 1.0
    assert fattore_target_riserva("groq/openai/gpt-oss-120b@c") == 0.95
    assert fattore_target_riserva("groq/openai/gpt-oss-20b@c") == 0.55
    assert fattore_target_riserva("altro/modello") == 1.0
    assert CERVELLO_CAMPIONI_EXTRA == 1


def test_preavviso_con_riga_dei_tempi(monkeypatch):
    import asyncio
    scheda, chiamate = _finti(monkeypatch)
    info = {"price": 15, "brand": "Prada", "title": "Gonna", "url": "https://www.vinted.it/items/1-x",
            "fair_value": _stima("🟢", 40)}
    t = scheda.testo_preavviso(info, info["url"], riga_tempi="⏱ pubblicato→telegram 8s · telegram→preavviso 4s · totale 12s")
    assert "⏱ pubblicato→telegram 8s" in t and t.index("⏱") < t.index("preavviso del semaforo")
    esito = asyncio.run(scheda.invia_preavviso(
        info, info["url"], [b"1", b"2"], riga_tempi="⏱ totale 12s", secondi={"pub_telegram": 8.0, "telegram_notifica": 4.0, "totale": 12.0}))
    assert esito["riga_tempi"] == "⏱ totale 12s" and esito["tipo"] == "album"


def test_pausa_gemini_dopo_429(monkeypatch):
    from bot import riserva_llm as r
    r._gemini_pausa_fino.clear()
    assert not r.gemini_in_pausa("cervello")
    assert not r.segna_gemini_in_pausa_se_429("cervello", "errore 500 generico")
    assert r.segna_gemini_in_pausa_se_429("cervello", "Client error '429 Too Many Requests' for url ...")
    assert r.gemini_in_pausa("cervello") and not r.gemini_in_pausa("occhio")
    monkeypatch.setattr(r, "GEMINI_PAUSA_429_SECONDI", -1)
    r.segna_gemini_in_pausa_se_429("occhio", "429")
    assert not r.gemini_in_pausa("occhio")     # scaduta: Gemini si riprova
    r._gemini_pausa_fino.clear()


def test_cascata_esaurita_conta_anche_i_modelli_esclusi(monkeypatch):
    from bot import gemini_stato as g
    monkeypatch.setattr(g, "GEMINI_CASCATA", ["m-escluso", "m-senza-quota"])
    monkeypatch.setattr(g, "GEMINI_CASCATA_CERVELLO", [])
    monkeypatch.setattr(g, "_gemini_modello_escluso", lambda m: m == "m-escluso")
    monkeypatch.setattr(g, "_gemini_modello_senza_quota", lambda m: m == "m-senza-quota")
    assert g.gemini_cascata_esaurita("cervello")
    monkeypatch.setattr(g, "_gemini_modello_senza_quota", lambda m: False)
    assert not g.gemini_cascata_esaurita("cervello")


def test_pagamento_ultima_riserva_e_tetto(monkeypatch):
    import asyncio
    import bot.riserva_llm as rl
    monkeypatch.setattr(rl, "GEMINI_CHIAVE_PAGAMENTO", "chiave-finta")
    monkeypatch.setattr(rl, "EXTRA_LLM_URL", "http://gw")
    monkeypatch.setattr(rl, "PAGAMENTO_MAX_RICHIESTE_GIORNO", 2)
    rl._pagamento_conteggio.update(giorno=None, n=0)
    rl._riserva_lenta_fino.clear(); rl._latenze_riserva.clear(); rl._panel_pausa.clear()
    voce = rl.PREFISSO_PAGAMENTO + rl.GEMINI_MODELLO_PAGAMENTO
    assert rl.lista_con_pagamento("cervello", ["a/uno"]) == ["a/uno", voce]          # in coda
    chiamati = []

    async def finta(modello, system, contenuto, max_tokens, uso=None, url=None, chiave=None):
        chiamati.append((modello, bool(url)))
        return (None, 5, "http429") if modello == "a/uno" else ('{"prezzo_target_vendita_eur": 80}', 5, None)
    monkeypatch.setattr(rl, "_panel_chiama", finta)
    ok = lambda d: d.get("prezzo_target_vendita_eur", 0) > 0
    d, m = asyncio.run(rl._prova_in_ordine("cervello", ["a/uno"], lambda c: "s", "u", 100, ok))
    assert m == voce and chiamati[-1] == (rl.GEMINI_MODELLO_PAGAMENTO, True)         # gratuito fallito -> pagamento
    # tetto giornaliero
    rl._panel_pausa.clear()
    asyncio.run(rl._prova_in_ordine("cervello", ["a/uno"], lambda c: "s", "u", 100, ok))
    rl._panel_pausa.clear()
    assert not rl.pagamento_disponibile()
    assert rl.lista_con_pagamento("cervello", ["a/uno"]) == ["a/uno"]
    rl.db.salva_pagamento(rl._pagamento_conteggio["giorno"], 0)   # il contatore e' nel DB di test condiviso
    rl._pagamento_conteggio.update(giorno=None, n=0); rl._panel_pausa.clear()


def test_riserva_lenta_passa_prima_dal_pagamento(monkeypatch):
    import bot.riserva_llm as rl
    monkeypatch.setattr(rl, "GEMINI_CHIAVE_PAGAMENTO", "chiave-finta")
    monkeypatch.setattr(rl, "EXTRA_LLM_URL", "http://gw")
    rl._pagamento_conteggio.update(giorno=None, n=0)
    rl._riserva_lenta_fino.clear(); rl._latenze_riserva.clear()
    voce = rl.PREFISSO_PAGAMENTO + rl.GEMINI_MODELLO_PAGAMENTO
    assert not rl.registra_latenza_riserva("occhio", 25000, adesso=1000)
    assert not rl.registra_latenza_riserva("occhio", 30000, adesso=1001)
    assert rl.registra_latenza_riserva("occhio", 28000, adesso=1002)                 # mediana 28 s > 20 s
    assert rl.lista_con_pagamento("occhio", ["a/uno"], adesso=1003) == [voce, "a/uno"]
    assert rl.lista_con_pagamento("occhio", ["a/uno"], adesso=1002 + rl.RISERVA_LENTA_PAUSA_S + 1) == ["a/uno", voce]
    rl._riserva_lenta_fino.clear()

def test_tempi_da_caricato_con_testo_relativo():
    from datetime import datetime, timezone
    from bot.tempi import _calcola_tempi_pipeline, parse_caricato_secondi
    assert parse_caricato_secondi("20 secondi fa") == (20, False)
    assert parse_caricato_secondi("Caricato: 3 minuti fa, descrizione") == (180, True)
    assert parse_caricato_secondi("un'ora fa") == (3600, True)
    assert parse_caricato_secondi("1 ora fa") == (3600, True)
    assert parse_caricato_secondi("ieri") is None and parse_caricato_secondi(None) is None
    t_scrape = 1_000_000.0
    info = {"uploaded_text": "20 secondi fa", "t_scrape": t_scrape}        # caricato a t=999980
    msg_date = datetime.fromtimestamp(t_scrape - 8, tz=timezone.utc)       # messaggio Telegram a t=999992
    pezzi, sec = _calcola_tempi_pipeline(info, msg_date, t_scrape - 10, t_riferimento=t_scrape + 3)
    assert round(sec["pub_telegram"]) == 12 and round(sec["totale"]) == 23
    assert pezzi[0].startswith("pubblicato→telegram 12s") and "totale 23s" in pezzi[-1]
    pezzi2, _ = _calcola_tempi_pipeline({"uploaded_text": "2 minuti fa", "t_scrape": t_scrape}, msg_date, None, t_riferimento=t_scrape)
    assert "~" in pezzi2[0]


def test_taratura_brand_da_env():
    from bot.fair_value import FAIR_VALUE_TARATURA_BRAND, _fattori_da_env
    assert FAIR_VALUE_TARATURA_BRAND == {"missoni": 1.10, "brunello cucinelli": 1.15}
    assert _fattori_da_env("Prada=1.3, rotto, x=abc ,=2") == {"prada": 1.3}
    assert _fattori_da_env("") == {}


def test_preavviso_brand_e_suono():
    from bot.fair_value import preavviso_con_suono, valuta_preavviso
    verde = {"semaforo": "🟢", "margine": 60, "conf": "media", "fv": 90, "brand": "prada"}
    assert valuta_preavviso(verde, 30) == (True, "semaforo")
    assert valuta_preavviso({**verde, "brand": "acne studios"}, 30) == (False, "no")
    assert valuta_preavviso({**verde, "brand": "marni"}, 30) == (False, "no")
    # brand facile: soglia di margine piu' bassa, anche con semaforo giallo
    assert valuta_preavviso({"semaforo": "🟡", "margine": 12, "conf": "media", "fv": 50, "brand": "jean paul gaultier"}, 30) == (True, "brand_facile")
    # prezzo basso ora <= 20
    giallo = {"semaforo": "🟡", "margine": 22, "conf": "media", "fv": 40, "brand": "prada"}
    assert valuta_preavviso(giallo, 18) == (True, "prezzo_basso")
    assert valuta_preavviso(giallo, 24) == (False, "no")
    # suono: solo con fv/prezzo >= 4 o brand facile
    assert preavviso_con_suono({**verde, "fv": 130}, 30)
    assert not preavviso_con_suono({**verde, "fv": 90}, 30)
    assert preavviso_con_suono({**verde, "brand": "jean paul gaultier", "fv": 50}, 30)


def test_soglie_semaforo_ritarate():
    # Soglie del 2026-10-07: 🟢 da fair value x3 (ROI 200%) con margine >= 20, 🟡 da x2, sotto 🔴.
    from bot.fair_value import stima_fair_value
    fv = stima_fair_value({"brand": "Prada", "title": "Maglia lana", "price": 1000})["fv"]
    colore = lambda prezzo: stima_fair_value({"brand": "Prada", "title": "Maglia lana", "price": prezzo})["semaforo"]
    assert colore(fv / 3.2) == "🟢"
    assert colore(fv / 2.5) == "🟡"
    assert colore(fv / 1.6) == "🔴"


def test_chiedi_foto_brand_esclusi_stessa_soglia_degli_altri():
    from bot.scheda import chiedi_foto_da_notificare as n
    assert n("Max Mara", 31) and not n("Max Mara", 30) and not n("Max Mara", None)
    assert not n("Prada", 30) and n("Prada", 31) and n("Miu Miu", 79) and n("Loewe", 41)
