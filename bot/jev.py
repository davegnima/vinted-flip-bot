"""Giudizio di Jev (TypeSafe AI) su un annuncio del radar, con i prezzi dei simili come riferimento.

Attivo con JEV_GIUDICE=1 e la chiave in TYPESAFE_API_KEY. Chiamata bloccante: usarla con asyncio.to_thread.
Il risultato va nel messaggio Telegram e nei log. Mai decisioni automatiche: il filtro e' RADAR_SOLO_VERDI.
Schema da docs.typesafe.ai/introduction/quickstart (domanda di tipo choice con criteria).
"""
import json
import os
import urllib.request

from bot.logger import log

JEV_GIUDICE = os.environ.get("JEV_GIUDICE", "0").strip() in ("1", "true", "si")
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODELLO = "jev-latest"
OPZIONI = {
    "affare_vero": "il prezzo e' chiaramente sotto il valore dell'oggetto usato, e l'oggetto sembra autentico e completo",
    "non_affare": "il prezzo e' nella norma dei simili, oppure l'oggetto non sembra un affare",
    "falso_o_ricambio": "replica, falso, ricambio, accessorio, lotto o descrizione troppo poco chiara per valutarlo",
}


def giudica(titolo, prezzo, prezzi_simili, rivendita):
    """(scelta, confidenza) oppure (None, None) se Jev non e' attivo o non risponde. Bloccante."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and chiave):
        return None, None
    simili = ", ".join(f"{p:g}" for p in sorted(prezzi_simili)[:20]) or "nessuno"
    stato = (f"Annuncio Vinted: {titolo}\nPrezzo chiesto: {prezzo} EUR\n"
             f"Prezzi chiesti di annunci simili usati: {simili}\n"
             f"Stima di rivendita (25 percentile): {rivendita} EUR")
    corpo = {"model": MODELLO, "state": stato,
             "questions": {"giudizio": {
                 "type": "choice",
                 "instructions": "Valuta l'annuncio: e' un affare da comprare e rivendere, o no?",
                 "criteria": OPZIONI}}}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            risposta = json.loads(r.read().decode())
        giud = risposta["answers"]["giudizio"]
        return giud.get("choice"), giud.get("confidence")
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        log.warning("JEV | giudizio non disponibile: %s", str(e)[:200])
        return None, None
