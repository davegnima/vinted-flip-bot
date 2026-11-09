import asyncio
import time

import bot.telegram_api as ta


class _Risp:
    def __init__(self, codice, retry=None):
        self.status_code, self._retry = codice, retry
        self.is_success = codice == 200
        self.text = ""

    def json(self):
        return {"parameters": {"retry_after": self._retry}} if self._retry else {}


class _Client:
    def __init__(self, risposte):
        self.risposte, self.chiamate = list(risposte), 0

    async def post(self, url, **kw):
        self.chiamate += 1
        return self.risposte.pop(0)


def _prova(monkeypatch, metodo, risposte):
    monkeypatch.setattr(ta.hc, "_client_telegram", _Client(risposte), raising=False)
    monkeypatch.setattr(ta, "TELEGRAM_PASSO_DOPO_BLOCCO_SECONDI", 0.0)
    ta._blocco_429.update(fino=0.0, prossimo=0.0)
    attese = []

    async def finto_sleep(s):
        attese.append(s)
    monkeypatch.setattr(ta.asyncio, "sleep", finto_sleep)
    resp = asyncio.run(ta._telegram_post(metodo, json={}))
    return resp, ta.hc._client_telegram.chiamate, attese


def test_blocco_429_lungo_il_testo_aspetta_la_fine_e_riprova_una_volta(monkeypatch):
    resp, chiamate, attese = _prova(monkeypatch, "sendMessage", [_Risp(429, 900), _Risp(200)])
    assert resp.is_success and chiamate == 2
    assert attese and attese[0] > 800   # niente retry ogni 60 s: si aspetta la fine del blocco


def test_blocco_429_lungo_gli_album_non_partono_ne_martellano(monkeypatch):
    resp, chiamate, _ = _prova(monkeypatch, "sendMediaGroup", [_Risp(429, 900), _Risp(200)])
    assert resp.status_code == 429 and chiamate == 1
    # e con il blocco attivo una nuova foto non parte nemmeno
    assert asyncio.run(ta._telegram_post("sendPhoto", data={})) is None and ta.hc._client_telegram.chiamate == 1
    ta._blocco_429.update(fino=0.0, prossimo=0.0)


def test_429_breve_resta_il_vecchio_retry(monkeypatch):
    resp, chiamate, attese = _prova(monkeypatch, "sendMessage", [_Risp(429, 5), _Risp(200)])
    assert resp.is_success and chiamate == 2 and attese == [5.5]


def test_blocco_429_di_ore_nessun_invio_ne_testo_ne_album(monkeypatch):
    resp, chiamate, attese = _prova(monkeypatch, "sendMessage", [_Risp(429, 40000), _Risp(200)])
    assert resp.status_code == 429 and chiamate == 1 and not attese   # non dorme 11 ore e non riprova
    assert asyncio.run(ta._telegram_post("sendMessage", json={})) is None and ta.hc._client_telegram.chiamate == 1
    assert asyncio.run(ta._telegram_post("sendMediaGroup", data={})) is None and ta.hc._client_telegram.chiamate == 1
    ta._blocco_429.update(fino=0.0, prossimo=0.0)


def test_ritmo_album_muto_oltre_il_limite_non_parte_e_non_aspetta_in_coda(monkeypatch):
    monkeypatch.setattr(ta, "TELEGRAM_MSG_MINUTO", 14)
    monkeypatch.setattr(ta, "TELEGRAM_ATTESA_MUTI_MAX_S", 3.0)
    ta._finestra_invii.clear()
    attese = []

    async def finto_sleep(s):
        attese.append(s)
        monkeypatch.setattr(ta.time, "monotonic", lambda c=[ta.time.monotonic()]: c.__setitem__(0, c[0] + s) or c[0])
    monkeypatch.setattr(ta.asyncio, "sleep", finto_sleep)
    album = {"files": {f"p{i}": 1 for i in range(10)}, "data": {"disable_notification": True}}
    assert asyncio.run(ta._rispetta_ritmo("sendMediaGroup", album)) is True
    assert ta.unita_ultimo_minuto() == 10 and not attese
    assert asyncio.run(ta._rispetta_ritmo("sendMediaGroup", album)) is False   # 10 + 10 > 14: dopo al massimo 3 s l'album non parte
    assert sum(attese) <= 3.2
    assert asyncio.run(ta._rispetta_ritmo("sendMessage", {"json": {"disable_notification": True}})) is True   # il testo singolo parte
    ta._finestra_invii.clear()


def test_unita_chiamata():
    assert ta._unita_chiamata("sendMessage", {}) == 1
    assert ta._unita_chiamata("sendMediaGroup", {"files": {"a": 1, "b": 2, "c": 3}}) == 3


def test_invii_con_suono_non_aspettano_mai(monkeypatch):
    monkeypatch.setattr(ta, "TELEGRAM_MSG_MINUTO", 2)
    ta._finestra_invii.clear()
    attese = []

    async def finto_sleep(s):
        attese.append(s)
    monkeypatch.setattr(ta.asyncio, "sleep", finto_sleep)
    for _ in range(5):
        asyncio.run(ta._rispetta_ritmo("sendMessage", {"json": {"disable_notification": False}}))
    assert not attese and ta.unita_ultimo_minuto() == 5
    assert ta._e_urgente("sendMessage", {"json": {"disable_notification": False}})
    assert not ta._e_urgente("sendMediaGroup", {"data": {"disable_notification": True}})
    # 9/11: un avviso radar muto (verde con Gemini "da rivedere") restava 22 minuti in coda dietro gli album: urgente=True lo fa partire subito
    assert ta._e_urgente("sendPhoto", {"data": {"disable_notification": True}}, urgente=True)
    asyncio.run(ta._rispetta_ritmo("sendPhoto", {"data": {"disable_notification": True}}, urgente=True))
    assert not attese
    ta._finestra_invii.clear()
