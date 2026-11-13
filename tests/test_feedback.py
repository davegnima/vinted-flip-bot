import asyncio

import pytest

from bot import db
from bot import feedback as fb


@pytest.fixture(autouse=True)
def db_pulito(tmp_path, monkeypatch):
    db.chiudi()
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "f.sqlite3"))
    fb._contesti.clear()
    yield
    db.chiudi()


@pytest.mark.parametrize("testo,atteso", [
    ("f", ("falso", None)), ("Falso", ("falso", None)), ("o", ("originale", None)), ("o 90", ("originale", 90.0)),
    ("90", (None, 90.0)), ("90 €", (None, 90.0)), ("originale 45,5 eur", ("originale", 45.5)), ("falso 40", ("falso", None)),
    ("?", ("non_so", None)), ("ok", None), ("grazie mille", None), ("", None), ("o f", None), ("1 2 3 4", None),
])
def test_parse_risposta(testo, atteso):
    assert fb.parse_risposta(testo) == atteso


def test_tastiera_prezzi():
    p = fb.tastiera_prezzo("55", fv=112)
    dati = [b["callback_data"] for r in p for b in r]
    assert "fp|55|110" in dati and "fp|55|0" in dati and all(len(d) <= 64 for d in dati)


def test_bottoni_registrano_giudizio_e_prezzo(monkeypatch):
    modifiche, risposte = [], []

    async def edit(chat, mid, testo, tastiera=None):
        modifiche.append((testo, tastiera))
        return True

    async def risp(cb, testo=None):
        risposte.append(testo)

    monkeypatch.setattr(fb, "telegram_edit_con_tastiera", edit)
    monkeypatch.setattr(fb, "telegram_answer_callback", risp)
    fb._contesti["55"] = {"brand": "Prada", "fv": 79, "esito": "COMPRA", "prezzo": 19.0}
    msg = {"chat": {"id": 1}, "message_id": 9, "text": "🔎 Controllo autenticità\nPrada\nCosa dici tu?"}

    async def prova():
        await fb.gestisci_callback({"id": "c1", "data": "fb|55|o", "message": msg})
        msg2 = {"chat": {"id": 1}, "message_id": 9, "text": modifiche[0][0]}
        await fb.gestisci_callback({"id": "c2", "data": "fp|55|80", "message": msg2})
        await fb.gestisci_callback({"id": "c3", "data": "fb|56|f", "message": msg})
    asyncio.run(prova())
    eventi = db.leggi_eventi("feedback")
    assert len(eventi) == 2
    dati = [e for e in eventi]
    assert modifiche[0][1] and "prezzo" in modifiche[0][0].lower()           # dopo Originale chiede il prezzo
    assert "Registrato: originale" in modifiche[1][0] and "80" in modifiche[1][0] and modifiche[1][1] == []
    assert "Cosa dici" not in modifiche[1][0] and modifiche[1][0].count("✅") == 1
    assert "Registrato: falso" in modifiche[2][0]


def test_ogni_scheda_ha_la_riga_di_feedback():
    from bot import telegram_api as tg
    t = tg.tastiera_annuncio("https://www.vinted.it/items/10345-x")
    assert t[0][0]["url"].endswith("10345-x") and [b["callback_data"] for b in t[-3]] == ["sb|10345|o", "sb|10345|f", "sp|10345|ask"] and [b["callback_data"] for b in t[-2]] == ["sv|10345|g", "sv|10345|s"] and t[-1][0]["callback_data"] == "sp|10345|nota"
    assert len(tg.tastiera_annuncio("https://www.vinted.it/items/10345-x", [[{"text": "x", "url": "https://a"}]])) == 5
    assert tg.righe_feedback("https://www.vinted.it/catalog?x=1") == []


def test_bottoni_sulla_scheda_giudizio_prezzo_e_campo_libero(monkeypatch):
    from bot import telegram_api as tg
    tastiere, richieste, risposte = [], [], []

    async def edit(chat, mid, tastiera):
        tastiere.append(tastiera)
        return True

    async def ask(chat, testo, reply_to=None, segnaposto=None):
        richieste.append((testo, reply_to))
        return 3

    async def risp(cb, testo=None):
        risposte.append(testo)

    monkeypatch.setattr(fb, "telegram_edit_tastiera", edit)
    monkeypatch.setattr(fb, "telegram_send_richiesta_prezzo", ask)
    monkeypatch.setattr(fb, "telegram_answer_callback", risp)
    url = "https://www.vinted.it/items/77-x"
    msg = {"chat": {"id": 1}, "message_id": 9, "text": "verdetto", "reply_markup": {"inline_keyboard": tg.tastiera_annuncio(url)}}

    async def prova():
        await fb.gestisci_callback({"id": "a", "data": "sb|77|o", "message": msg})
        await fb.gestisci_callback({"id": "b", "data": "sp|77|ask", "message": msg})
        await fb.gestisci_callback({"id": "c", "data": "sp|77|80", "message": msg})
        await fb.gestisci_callback({"id": "d", "data": "sb|78|f", "message": msg})
    asyncio.run(prova())
    prezzi = [b["callback_data"] for r in tastiere[0] for b in r if b.get("callback_data", "").startswith("sp|")]
    assert tastiere[0][0][0]["url"] == url and "sp|77|80" in prezzi and "sp|77|ask" in prezzi     # restano 'Apri su Vinted' + prezzi rapidi
    assert richieste == [("💶 A che prezzo lo rivenderesti? Scrivi solo il numero (es. 90).\n" + url, 9)]
    assert "Registrato" not in str(tastiere[0])
    ultimo_ok = [b["text"] for r in tastiere[1] for b in r]
    assert "✅ originale · 80 €" in ultimo_ok and "↩️ Cambia" in ultimo_ok
    assert "❌ Registrato: falso" in [b["text"] for r in tastiere[2] for b in r]
    ev = db.leggi_eventi("feedback")
    assert len(ev) == 2


def test_nota_libera_si_registra_e_si_apre_dal_bottone(monkeypatch):
    from bot import feedback as fb
    eventi, richieste = [], []
    monkeypatch.setattr(fb.db, "scrivi_evento", lambda *a, **k: eventi.append(a))

    async def ask(chat, testo, reply_to=None, segnaposto=None):
        richieste.append((testo, segnaposto))

    async def risp(cb, testo=None):
        pass
    monkeypatch.setattr(fb, "telegram_send_richiesta_prezzo", ask)
    monkeypatch.setattr(fb, "telegram_answer_callback", risp)
    msg = {"chat": {"id": 1}, "message_id": 9, "text": "v", "reply_markup": {"inline_keyboard": []}}
    asyncio.run(fb.gestisci_callback({"id": "a", "data": "sp|77|nota", "message": msg}))
    assert richieste and richieste[0][0].startswith("📝") and richieste[0][1] == "La tua nota"
    fb.registra_nota("77", "  etichetta   cucita male ", {"brand": "Prada"})
    fb.registra_nota("77", "   ")
    assert len(eventi) == 1 and eventi[0][3]["nota"] == "etichetta cucita male" and eventi[0][3]["fonte"] == "nota"


def test_conferma_del_verdetto_del_cervello(monkeypatch):
    from bot import feedback as fb
    eventi, tastiere = [], []
    monkeypatch.setattr(fb.db, "scrivi_evento", lambda *a, **k: eventi.append(a))

    async def edit(chat, mid, tastiera):
        tastiere.append(tastiera)

    async def risp(cb, testo=None):
        pass
    monkeypatch.setattr(fb, "telegram_edit_tastiera", edit)
    monkeypatch.setattr(fb, "telegram_answer_callback", risp)
    fb._contesti["88"] = {"brand": "Prada", "esito": "COMPRA"}
    msg = {"chat": {"id": 1}, "message_id": 9, "text": "v", "reply_markup": {"inline_keyboard": []}}
    asyncio.run(fb.gestisci_callback({"id": "a", "data": "sv|88|s", "message": msg}))
    assert eventi[0][3]["verdetto_utente"] == "sbagliato" and eventi[0][3]["esito"] == "COMPRA" and eventi[0][3]["fonte"] == "verdetto"
    assert "🧠 Verdetto sbagliato" in [b["text"] for r in tastiere[0] for b in r]


def test_testa_chiavi_gemini_non_espone_le_chiavi(monkeypatch):
    import asyncio
    from bot import gemini_api, http_clients as hc

    class R:
        def __init__(self, c): self.status_code = c

    codici = {"k1": 200, "k2": 403, "k3": 429}

    class C:
        async def get(self, url, headers=None, timeout=None):
            return R(codici[headers["x-goog-api-key"]])

    monkeypatch.setattr(hc, "_client_generico", C())
    ris = asyncio.run(gemini_api.testa_chiavi_gemini(["k1", "k2", "k3"]))
    assert ris == [(1, "valida"), (2, "NON VALIDA"), (3, "valida, ma 429")]
    assert "k1" not in str(ris)


def test_arresto_ordinato_aspetta_le_analisi(monkeypatch):
    """SIGTERM (deploy): il bot si disconnette solo quando le analisi in corso sono finite (o scade l'attesa)."""
    import asyncio
    import main_telethon as m
    chiamate = []

    async def disconnetti():
        chiamate.append(m._analisi_attive["n"])
    monkeypatch.setattr(m.client, "disconnect", disconnetti)
    monkeypatch.setitem(m._analisi_attive, "arresto", False)
    monkeypatch.setitem(m._analisi_attive, "n", 1)

    async def prova():
        async def fine_analisi():
            await asyncio.sleep(0.05)
            m._analisi_attive["n"] -= 1
        asyncio.get_running_loop().create_task(fine_analisi())
        await m._arresto_ordinato(attesa_max=5, passo=0.01)
        await m._arresto_ordinato(attesa_max=5, passo=0.01)   # secondo SIGTERM: ignorato
    asyncio.run(prova())
    assert chiamate == [0]

    monkeypatch.setitem(m._analisi_attive, "arresto", False)
    monkeypatch.setitem(m._analisi_attive, "n", 2)
    asyncio.run(m._arresto_ordinato(attesa_max=0.05, passo=0.01))   # analisi bloccata: esce comunque allo scadere
    assert chiamate == [0, 2]
