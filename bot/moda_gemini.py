"""Controllo di autenticita' con Gemini GRATUITO sulla moda (02/11, richiesta dell'utente).

Quando la foto letta da Jev non basta a dire "sembra originale" (replica sospetta, marca diversa, foto poco chiara o prezzo molto sotto i
comparabili) Gemini guarda TUTTE le foto dell'annuncio (etichette, cuciture, serigrafie, hardware, codici) e dice se il capo e' coerente
con la marca del titolo. E' un indizio dalle foto, non una certificazione. Gemini NON calcola margini ne' decide l'avviso da solo:
solo una replica con confidenza alta scarta (come Jev), il resto diventa una riga nel messaggio.
Solo Gemini gratuito (cascata e chiavi di GEMINI_API_KEYS, ruolo 'occhio'); nessun servizio a pagamento. Mai eccezioni.
"""
import json
import os
import time

from bot.gemini_api import chiama_gemini
from bot.logger import log

MODA_GEMINI = os.environ.get("MODA_GEMINI", "1").strip() not in ("0", "false", "no", "")
try:
    MODA_GEMINI_MAX_ORA = int(os.environ.get("MODA_GEMINI_MAX_ORA", "30") or 30)
    MODA_GEMINI_FOTO = max(1, int(os.environ.get("MODA_GEMINI_FOTO", "8") or 8))
except ValueError:
    MODA_GEMINI_MAX_ORA, MODA_GEMINI_FOTO = 30, 8
CONF_REPLICA_MIN = 0.7   # sotto questa confidenza una "replica" resta un dubbio nel messaggio, non uno scarto
RAPPORTO_PREZZO_SOSPETTO = 0.25   # prezzo sotto il 25% della rivendita dei comparabili: troppo bello per essere vero

SYSTEM_PROMPT = """Sei un esperto di autenticazione di capi e accessori di moda usati. Ricevi titolo, marca dichiarata, prezzo, descrizione e TUTTE le
foto di un annuncio. Dici se quello che vedi e' coerente con la marca dichiarata, solo sui fatti visibili:
- etichette, loghi, cuciture, serigrafie, hardware (zip, bottoni, fibbie), codici/numeri di serie, dettagli di finitura, materiali.
- Se le foto non mostrano nulla di verificabile (niente etichetta, dettagli lontani, foto di catalogo) rispondi "non_verificabile".
- "replica" solo con indizi concreti (logo storto, carattere sbagliato, cuciture grossolane, hardware economico, etichetta incoerente).
- "dubbia" se c'e' un indizio ma non basta. "probabile" se i dettagli visibili sono coerenti. Non sospettare senza un indizio.
Non calcolare prezzi, margini o decisioni. Una frase breve in italiano (max 120 caratteri) col fatto che ha deciso."""

SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": ["autenticita", "confidenza", "indizi", "motivo"],
    "properties": {
        "autenticita": {"type": "STRING", "enum": ["probabile", "dubbia", "replica", "non_verificabile"]},
        "confidenza": {"type": "NUMBER"},
        "indizi": {"type": "STRING"},
        "motivo": {"type": "STRING"},
    },
    "required": ["autenticita", "confidenza", "indizi", "motivo"],
}

_chiamate = []   # istanti delle chiamate dell'ultima ora: tetto MODA_GEMINI_MAX_ORA


def _entro_il_tetto(adesso=None):
    adesso = adesso if adesso is not None else time.time()
    while _chiamate and adesso - _chiamate[0] > 3600:
        _chiamate.pop(0)
    return len(_chiamate) < MODA_GEMINI_MAX_ORA


def serve_controllo(autenticita_jev, prezzo, rivendita):
    """True se vale la pena far guardare tutte le foto a Gemini: Jev non dice con sicurezza "originale", oppure il prezzo e' molto sotto la
    rivendita dei comparabili (il caso classico del falso). `autenticita_jev` = (scelta, confidenza) o None. Pura."""
    if not MODA_GEMINI:
        return False
    if not autenticita_jev or autenticita_jev[0] != "originale_plausibile" or (autenticita_jev[1] or 0) < 0.6:
        return True
    return bool(rivendita and prezzo and prezzo < RAPPORTO_PREZZO_SOSPETTO * rivendita)


def leggi_risposta(testo):
    """Dict valido {autenticita, confidenza, indizi, motivo} dalla risposta di Gemini, o None. Pura."""
    if not testo or testo.lstrip().startswith("[ERRORE"):
        return None
    try:
        d = json.loads(testo)
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("autenticita") not in ("probabile", "dubbia", "replica", "non_verificabile"):
        return None
    try:
        d["confidenza"] = max(0.0, min(1.0, float(d.get("confidenza"))))
    except (TypeError, ValueError):
        d["confidenza"] = None
    d["indizi"] = str(d.get("indizi") or "")[:160]
    d["motivo"] = str(d.get("motivo") or "")[:140]
    return d


def e_replica(d):
    """True se Gemini dice replica con confidenza sufficiente a scartare l'avviso. Pura."""
    return bool(d and d.get("autenticita") == "replica" and (d.get("confidenza") or 0) >= CONF_REPLICA_MIN)


def riga_messaggio(d):
    """Riga (testo semplice) per il messaggio: esito del controllo Gemini sulle foto. Pura."""
    if not d:
        return None
    etichetta = {"probabile": "dettagli coerenti con la marca", "dubbia": "qualche dubbio sull'autenticita'",
                 "replica": "indizi di replica", "non_verificabile": "dalle foto non si verifica"}[d["autenticita"]]
    conf = f" ({d['confidenza']:.0%})" if d.get("confidenza") is not None else ""
    return f"🕵️ Gemini (tutte le foto): {etichetta}{conf}" + (f", {d['motivo']}" if d.get("motivo") else "") + ". Indizio dalle foto, non certificazione"


async def controlla(titolo, brand, prezzo, descrizione, foto, item_id=None):
    """Controllo Gemini su tutte le foto (al massimo MODA_GEMINI_FOTO). Ritorna il dict di leggi_risposta o None (spento, oltre il tetto
    orario, senza foto o senza risposta). Mai eccezioni."""
    if not (MODA_GEMINI and foto):
        return None
    try:
        if not _entro_il_tetto():
            log.info("MODA GEMINI | item=%s | oltre il tetto orario (%s/h): niente controllo", item_id, MODA_GEMINI_MAX_ORA)
            return None
        _chiamate.append(time.time())
        t0 = time.time()
        utente = (f"Titolo: {titolo}\nMarca dichiarata: {brand or 'n/d'}\n"
                  + (f"Prezzo richiesto: {prezzo:g} EUR\n" if isinstance(prezzo, (int, float)) else "")
                  + "Descrizione del venditore: " + ((descrizione or "").strip()[:1200] or "(vuota)"))
        testo, _costo, _n = await chiama_gemini(SYSTEM_PROMPT, utente, list(foto)[:MODA_GEMINI_FOTO], grounding=False,
                                                response_schema=SCHEMA, ruolo="occhio")
        d = leggi_risposta(testo)
        log.info("MODA GEMINI | item=%s | brand=%s | autenticita=%s | conf=%s | foto=%s | %.1fs | indizi=%s | motivo=%s | titolo=%s",
                 item_id or "-", brand, (d or {}).get("autenticita", "nessuna_risposta"), (d or {}).get("confidenza", "-"),
                 min(len(foto), MODA_GEMINI_FOTO), time.time() - t0, (d or {}).get("indizi", "-"), (d or {}).get("motivo", (testo or "")[:80]),
                 (titolo or "")[:60])
        return d
    except Exception as e:  # noqa: BLE001 - il controllo non deve mai fermare l'avviso
        log.warning("MODA GEMINI | item=%s | errore: %s", item_id or "-", e)
        return None
