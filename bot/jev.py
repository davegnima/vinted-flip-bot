"""Giudizio di Jev (TypeSafe AI) su un annuncio del radar: Jev risponde a tre domande chiuse sui fatti dell'annuncio,
il codice (verdetto_jev) decide l'esito. Jev non decide mai da solo.

Attivo con JEV_GIUDICE=1 e la chiave in TYPESAFE_API_KEY. Chiamata bloccante: usarla con asyncio.to_thread.
Il risultato va nel messaggio Telegram e nei log. Mai decisioni automatiche: il filtro e' RADAR_SOLO_VERDI.
Schema da docs.typesafe.ai/introduction/quickstart (domande di tipo choice con criteria).
"""
import json
import os
import urllib.request

from bot.logger import log

JEV_GIUDICE = os.environ.get("JEV_GIUDICE", "0").strip() in ("1", "true", "si")
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODELLO = "jev-latest"
# Domande chiuse sui fatti dell'annuncio (25/10): ogni risposta e' un fatto, non un giudizio complessivo.
DOMANDE = {
    "tipo": {
        "instructions": "Che cosa vende l'annuncio?",
        "criteria": {
            "oggetto_principale": "l'oggetto stesso, come descritto nel titolo",
            "ricambio_accessorio": "solo una parte, un accessorio, un cavo o una custodia",
            "lotto": "piu' oggetti venduti insieme, senza un valore chiaro del singolo",
            "replica_o_dubbio": "replica, falso, o una descrizione che non fa capire cosa vende",
        },
    },
    "completo": {
        "instructions": "Il titolo dice che l'oggetto e' completo o funzionante?",
        "criteria": {
            "si": "il titolo dice completo, funzionante, in scatola o con accessori",
            "no": "il titolo dice che manca qualcosa o che non funziona",
            "non_dichiarato": "il titolo non dice nulla in proposito",
        },
    },
    "prezzo": {
        "instructions": "Il prezzo chiesto rispetto alla stima di rivendita dei simili?",
        "criteria": {
            "sotto": "chiaramente sotto la stima di rivendita",
            "in_linea": "vicino alla stima di rivendita",
            "sopra": "sopra la stima di rivendita",
        },
    },
}
# Esiti del radar: stessa lista di prima, ora decisa dal codice.
ESITI = ("affare_vero", "non_affare", "falso_o_ricambio")
TIPI_NON_VENDIBILI = ("ricambio_accessorio", "lotto", "replica_o_dubbio")


def verdetto_jev(risposte):
    """Esito e confidenza dalle risposte di Jev. `risposte` = {domanda: (scelta, confidenza)}.
    Regole fisse, in ordine: se una risposta manca, nessun esito (None, None). Un oggetto che non e' l'oggetto
    principale e' falso_o_ricambio. Mancanza o prezzo sopra la stima e' non_affare. Solo oggetto principale, completo
    (o non dichiarato) e prezzo sotto la stima e' affare_vero. La confidenza e' la piu' bassa delle tre. Pura."""
    scelte = {k: risposte.get(k, (None, None))[0] for k in DOMANDE}
    if any(v is None for v in scelte.values()):
        return None, None
    confidenze = [risposte[k][1] for k in DOMANDE if risposte[k][1] is not None]
    conf = min(confidenze) if confidenze else None
    if scelte["tipo"] in TIPI_NON_VENDIBILI:
        return "falso_o_ricambio", conf
    if scelte["completo"] == "no" or scelte["prezzo"] == "sopra":
        return "non_affare", conf
    if scelte["prezzo"] == "sotto" and scelte["completo"] in ("si", "non_dichiarato"):
        return "affare_vero", conf
    return "non_affare", conf


def giudica(titolo, prezzo, prezzi_simili, rivendita):
    """(esito, confidenza) oppure (None, None) se Jev non e' attivo o non risponde. Bloccante."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and chiave):
        return None, None
    simili = ", ".join(f"{p:g}" for p in sorted(prezzi_simili)[:20]) or "nessuno"
    stato = (f"Annuncio Vinted: {titolo}\nPrezzo chiesto: {prezzo} EUR\n"
             f"Prezzi chiesti di annunci simili usati: {simili}\n"
             f"Stima di rivendita (25 percentile): {rivendita} EUR")
    corpo = {"model": MODELLO, "state": stato,
             "questions": {chiave_domanda: {"type": "choice", "instructions": d["instructions"], "criteria": d["criteria"]}
                           for chiave_domanda, d in DOMANDE.items()}}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            risposta = json.loads(r.read().decode())
        risposte = {k: (risposta["answers"][k].get("choice"), risposta["answers"][k].get("confidence"))
                    for k in DOMANDE}
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        log.warning("JEV | giudizio non disponibile: %s", str(e)[:200])
        return None, None
    log.info("JEV DOMANDE | titolo=%s | %s", titolo[:60],
             " | ".join(f"{k}={v[0]}({v[1]})" for k, v in risposte.items()))
    return verdetto_jev(risposte)
