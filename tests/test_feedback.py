import asyncio

import pytest

from bot import db
from bot import feedback as fb


@pytest.fixture(autouse=True)
def db_pulito(tmp_path, monkeypatch):
    db.chiudi()
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "f.sqlite3"))
    fb._proposti.update({"giorno": "", "n": 0, "item": set()})
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


def test_quando_proporre_il_controllo():
    assert fb.rischio_falso_da_verdetto("sospetto_servono_altre_foto", "COMPRA", "🔴")
    assert fb.rischio_falso_da_verdetto("probabilmente_falso", "NON COMPRARE", "🟢")
    assert not fb.rischio_falso_da_verdetto("probabilmente_falso", "NON COMPRARE", "🔴")        # falso e senza interesse economico
    assert not fb.rischio_falso_da_verdetto("probabilmente_autentico", "COMPRA", "🟢")
    assert fb.rischio_falso_da_scarto("[FALSO CONCLAMATO] etichetta", "🟢")
    assert fb.rischio_falso_da_scarto("[BRAND NON CORRISPONDENTE] x", "🟡")
    assert not fb.rischio_falso_da_scarto("[FALSO CONCLAMATO] etichetta", "🔴")
    assert not fb.rischio_falso_da_scarto("[CONDIZIONE DISTRUTTA] x", "🟢")


def test_tastiere_e_testo():
    t = fb.tastiera_giudizio("55")
    assert [b["callback_data"] for b in t[0]] == ["fb|55|o", "fb|55|f", "fb|55|n"]
    p = fb.tastiera_prezzo("55", fv=112)
    dati = [b["callback_data"] for r in p for b in r]
    assert "fp|55|110" in dati and "fp|55|0" in dati and all(len(d) <= 64 for d in dati)
    testo = fb.testo_controllo({"brand": "Prada", "titolo": "Maglione", "prezzo": 19.0, "sem": "🟢", "fv": 79}, "https://www.vinted.it/items/55-x", "etichetta dubbia")
    assert "Controllo autenticità" in testo and "Prada" in testo and "etichetta dubbia" in testo and "vedi su Vinted" in testo


def test_proponi_controllo_una_volta_e_nel_limite(monkeypatch):
    inviati = []

    async def invia(chat, testo, tastiera, reply_to=None, disable_notification=True):
        inviati.append((testo, tastiera, reply_to, disable_notification))
        return 7

    monkeypatch.setattr(fb, "telegram_send_con_tastiera", invia)
    monkeypatch.setattr(fb, "FEEDBACK_MAX_GIORNO", 2)

    async def prova():
        r = [await fb.proponi_controllo("1", "https://www.vinted.it/items/1-x", {"brand": "Prada"}, "m", reply_to=5)]
        r.append(await fb.proponi_controllo("1", "https://www.vinted.it/items/1-x", {"brand": "Prada"}, "m"))     # stesso annuncio
        r.append(await fb.proponi_controllo("2", "https://www.vinted.it/items/2-x", {"brand": "Prada"}, "m"))
        r.append(await fb.proponi_controllo("3", "https://www.vinted.it/items/3-x", {"brand": "Prada"}, "m"))     # oltre il limite
        return r
    assert asyncio.run(prova()) == [True, False, True, False]
    assert inviati[0][2] == 5 and inviati[0][3] is True      # in risposta alla galleria, senza suono


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
