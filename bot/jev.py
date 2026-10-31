"""Giudizio di Jev (TypeSafe AI) su un annuncio del radar: Jev risponde a tre domande chiuse sui fatti dell'annuncio,
il codice (verdetto_jev) decide l'esito. Jev non decide mai da solo.

Attivo con JEV_GIUDICE=1 e la chiave in TYPESAFE_API_KEY. Chiamata bloccante: usarla con asyncio.to_thread.
Il risultato va nel messaggio Telegram e nei log. Mai decisioni automatiche: il filtro e' RADAR_SOLO_VERDI.
Schema da docs.typesafe.ai/introduction/quickstart (domande di tipo choice con criteria).
"""
import base64
import json
import os
import urllib.request

from bot.logger import log

JEV_GIUDICE = os.environ.get("JEV_GIUDICE", "0").strip() in ("1", "true", "si")
# Prova sulle foto (25/10): Jev vede anche la prima foto, solo per gli annunci con semaforo verde. Anteprima di TypeSafe
# (header TypeSafe-Danger-Zone-Images): i token per immagine si misurano dal log "JEV DOMANDE ... input_tokens=".
JEV_FOTO = os.environ.get("JEV_FOTO", "0").strip() in ("1", "true", "si")
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODELLO = "jev-latest"
HEADER_IMMAGINI = "TypeSafe-Danger-Zone-Images"
RIFERIMENTO_FOTO = "foto1"
DOMANDA_FOTO = {
    "instructions": "La foto dell'annuncio mostra l'oggetto descritto nel titolo?",
    "criteria": {
        "corrisponde": "la foto mostra l'oggetto descritto, riconoscibile",
        "non_corrisponde": "la foto mostra un altro oggetto, un ricambio, una replica o un lotto diverso dal titolo",
        "non_chiaro": "la foto non permette di dirlo",
    },
}
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
        "instructions": "Il titolo o la descrizione dicono che l'oggetto e' completo o funzionante?",
        "criteria": {
            "si": "dicono completo, funzionante, in scatola o con accessori",
            "no": "dicono che manca qualcosa, che non funziona, che e' bloccato (iCloud, codice), venduto per ricambi o da riparare",
            "non_dichiarato": "non dicono nulla in proposito",
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
# Prova in ombra (31/10): i titoli dei comparabili vanno a Jev, che dice se sono lo stesso modello dell'annuncio. La risposta
# NON entra in verdetto_jev: finisce solo nel log e nell'evento, per tarare dopo una promozione dei gialli da ricerca allargata.
DOMANDA_SIMILI = {
    "instructions": "I titoli degli annunci simili sono lo stesso modello e la stessa versione dell'annuncio?",
    "criteria": {
        "stesso_modello": "quasi tutti i simili sono lo stesso modello e la stessa versione",
        "in_parte": "alcuni simili sono lo stesso modello, altri una versione o un modello diverso",
        "diverso": "i simili sono per lo piu' un altro modello, una serie diversa o oggetti diversi",
    },
}
MAX_DESCRIZIONE = 600
MAX_TITOLI_SIMILI = 15
# Esiti del radar: stessa lista di prima, ora decisa dal codice.
ESITI = ("affare_vero", "non_affare", "falso_o_ricambio")
TIPI_NON_VENDIBILI = ("ricambio_accessorio", "lotto", "replica_o_dubbio")
FORMATI_FOTO = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg"}


def verdetto_jev(risposte):
    """Esito e confidenza dalle risposte di Jev. `risposte` = {domanda: (scelta, confidenza)}.
    Regole fisse, in ordine: se una risposta manca, nessun esito (None, None). Un oggetto che non e' l'oggetto
    principale e' falso_o_ricambio. Mancanza o prezzo sopra la stima e' non_affare. Solo oggetto principale, completo
    (o non dichiarato) e prezzo sotto la stima e' affare_vero. La confidenza e' la piu' bassa delle tre. Pura."""
    scelte = {k: risposte.get(k, (None, None))[0] for k in DOMANDE}
    if any(v is None for v in scelte.values()):
        return None, None
    confidenze = [v[1] for k, v in risposte.items() if k in DOMANDE or k == "foto"]
    confidenze = [c for c in confidenze if c is not None]
    conf = min(confidenze) if confidenze else None
    if risposte.get("foto", (None, None))[0] == "non_corrisponde":
        return "falso_o_ricambio", conf
    if scelte["tipo"] in TIPI_NON_VENDIBILI:
        return "falso_o_ricambio", conf
    if scelte["completo"] == "no" or scelte["prezzo"] == "sopra":
        return "non_affare", conf
    if scelte["prezzo"] == "sotto" and scelte["completo"] in ("si", "non_dichiarato"):
        return "affare_vero", conf
    return "non_affare", conf


ETICHETTE_ESITO = {"affare_vero": "affare", "non_affare": "non e' un affare", "falso_o_ricambio": "falso o ricambio"}
FRASI_MOTIVO = {
    "foto_diversa": "la foto non corrisponde al titolo",
    "ricambio": "e' solo un ricambio o un accessorio",
    "lotto": "e' un lotto di piu' oggetti",
    "replica_dubbio": "replica o descrizione poco chiara",
    "guasto_incompleto": "dichiarato rotto, incompleto, bloccato o per ricambi",
    "prezzo_alto": "prezzo sopra la stima di rivendita",
    "prezzo_in_linea": "prezzo in linea con la stima, nessuno sconto",
    "ok": "oggetto vero, non dichiarato guasto, prezzo sotto la stima",
}
_MOTIVO_TIPO = {"ricambio_accessorio": "ricambio", "lotto": "lotto", "replica_o_dubbio": "replica_dubbio"}


def motivo_jev(risposte):
    """(codice, frase) del perche' dell'esito, dalle stesse risposte di verdetto_jev (stesso ordine delle regole), oppure
    (None, None) se manca una risposta. Con `simili` diverso o in_parte la frase avverte che la stima poggia su altri modelli.
    Non cambia l'esito. Pura."""
    scelte = {k: risposte.get(k, (None, None))[0] for k in DOMANDE}
    if any(v is None for v in scelte.values()):
        return None, None
    if risposte.get("foto", (None, None))[0] == "non_corrisponde":
        codice = "foto_diversa"
    elif scelte["tipo"] in TIPI_NON_VENDIBILI:
        codice = _MOTIVO_TIPO[scelte["tipo"]]
    elif scelte["completo"] == "no":
        codice = "guasto_incompleto"
    elif scelte["prezzo"] == "sopra":
        codice = "prezzo_alto"
    elif scelte["prezzo"] == "sotto" and scelte["completo"] in ("si", "non_dichiarato"):
        codice = "ok"
    else:
        codice = "prezzo_in_linea"
    frase = FRASI_MOTIVO[codice]
    if risposte.get("simili", (None, None))[0] in ("diverso", "in_parte"):
        frase += ", ma i simili non sono lo stesso modello"
    return codice, frase


def descrizione_jev(esito, conf, frase):
    """Riga per il messaggio: 'non e' un affare, dichiarato rotto... (confidenza 0,9)'. Pura."""
    testo = ETICHETTE_ESITO.get(esito, esito)
    if frase:
        testo += f", {frase}"
    return f"{testo} (confidenza {conf})"


# Fasce di confidenza (31/10): sopra SOGLIA_PASSA l'esito vale; tra le due soglie e' un caso limite da valutare a mano con i
# bottoni (taratura di soglie e domande); sotto SOGLIA_RIVEDERE e' scartato. Ipotesi iniziali, da tarare sui dati.
SOGLIA_PASSA = 0.85
SOGLIA_RIVEDERE = 0.70


def fascia(confidenza):
    """'passa', 'da_rivedere' o 'scartato' dalla confidenza di Jev (None = scartato). Pura."""
    if confidenza is None or confidenza < SOGLIA_RIVEDERE:
        return "scartato"
    return "passa" if confidenza >= SOGLIA_PASSA else "da_rivedere"


def _formato_foto(foto):
    """'png' o 'jpeg' dai primi byte del file, None se non e' una foto utilizzabile. Pura."""
    for firma, formato in FORMATI_FOTO.items():
        if foto and foto.startswith(firma):
            return formato
    return None


def _chiama_jev(corpo):
    """Risposta JSON di Jev. Solleva eccezioni: il chiamante decide il fallback."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    intestazioni = {"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"}
    if "assets" in corpo:
        intestazioni[HEADER_IMMAGINI] = "true"
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST", headers=intestazioni)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def giudica(titolo, prezzo, prezzi_simili, rivendita, foto=None):
    """(esito, confidenza) oppure (None, None). Versione senza descrizione ne' titoli dei simili: vedi giudica_completo."""
    return giudica_completo(titolo, prezzo, prezzi_simili, rivendita, foto)[:2]


def giudica_completo(titolo, prezzo, prezzi_simili, rivendita, foto=None, descrizione=None, titoli_simili=None):
    """(esito, confidenza, simili, motivo) oppure quattro None se Jev non e' attivo o non risponde. Bloccante.
    Con `foto` (bytes) e JEV_FOTO=1 Jev riceve anche la prima foto; se la richiesta con la foto fallisce, riprova solo testo.
    `descrizione` (tagliata a MAX_DESCRIZIONE caratteri) entra nello stato. Con `titoli_simili` Jev risponde anche a DOMANDA_SIMILI:
    la risposta ('stesso_modello', 'in_parte', 'diverso', confidenza) e' il terzo valore e non influisce sull'esito.
    Il quarto valore e' (codice, frase) da motivo_jev: il perche' dell'esito."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and chiave):
        return None, None, None, None
    simili = ", ".join(f"{p:g}" for p in sorted(prezzi_simili)[:20]) or "nessuno"
    formato = _formato_foto(foto) if JEV_FOTO else None
    stato = (f"Annuncio Vinted: {titolo}\nPrezzo chiesto: {prezzo} EUR\n"
             f"Prezzi chiesti di annunci simili usati: {simili}\n"
             f"Stima di rivendita (25 percentile): {rivendita} EUR")
    desc = " ".join((descrizione or "").split())[:MAX_DESCRIZIONE]
    if desc:
        stato += f"\nDescrizione del venditore: {desc}"
    titoli = [t for t in (titoli_simili or []) if t][:MAX_TITOLI_SIMILI]
    if titoli:
        stato += "\nTitoli degli annunci simili:\n" + "\n".join(f"- {t[:100]}" for t in titoli)
    domande = {k: {"type": "choice", "instructions": d["instructions"], "criteria": d["criteria"]}
               for k, d in DOMANDE.items()}
    corpo = {"model": MODELLO, "state": stato, "questions": dict(domande)}
    if titoli:
        corpo["questions"]["simili"] = {"type": "choice", **DOMANDA_SIMILI}
    if formato:
        corpo["state"] += f"\nFoto dell'annuncio: {RIFERIMENTO_FOTO}"
        corpo["assets"] = {RIFERIMENTO_FOTO: {"type": "image", "data_base64": base64.b64encode(foto).decode(),
                                              "format": formato}}
        corpo["questions"]["foto"] = {"type": "choice", **DOMANDA_FOTO}
    try:
        risposta = _chiama_jev(corpo)
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        if not formato:
            log.warning("JEV | giudizio non disponibile: %s", str(e)[:200])
            return None, None, None, None
        log.warning("JEV FOTO | richiesta con foto non riuscita, riprovo solo testo: %s", str(e)[:200])
        return giudica_completo(titolo, prezzo, prezzi_simili, rivendita, None, descrizione, titoli_simili)
    try:
        risposte = {k: (risposta["answers"][k].get("choice"), risposta["answers"][k].get("confidence"))
                    for k in domande}
    except Exception as e:  # noqa: BLE001
        log.warning("JEV | risposta non leggibile: %s", str(e)[:200])
        return None, None, None, None
    if formato:
        risposte["foto"] = (risposta["answers"]["foto"].get("choice"), risposta["answers"]["foto"].get("confidence"))
    simili_risp = None
    if titoli:
        try:
            r = risposta["answers"]["simili"]
            simili_risp = (r.get("choice"), r.get("confidence"))
        except Exception:  # noqa: BLE001 - e' solo una prova in ombra
            simili_risp = None
    token = (risposta.get("usage") or {}).get("input_tokens")
    log.info("JEV DOMANDE | titolo=%s | foto=%s | desc=%s | simili=%s | input_tokens=%s | %s", titolo[:60], formato or "no",
             len(desc), simili_risp[0] if simili_risp else "-", token,
             " | ".join(f"{k}={v[0]}({v[1]})" for k, v in risposte.items()))
    esito, conf = verdetto_jev(risposte)
    motivo = motivo_jev({**risposte, "simili": simili_risp or (None, None)})
    log.info("JEV MOTIVO | titolo=%s | esito=%s | motivo=%s", titolo[:60], esito, motivo[0])
    return esito, conf, simili_risp, motivo
