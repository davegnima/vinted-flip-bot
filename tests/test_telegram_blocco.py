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
