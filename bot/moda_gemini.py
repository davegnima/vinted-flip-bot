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
# 5/11 (utente): il legit check approfondito su tutte le foto vale per OGNI avviso, non solo quando Jev dubita. MODA_GEMINI_SEMPRE=0 torna a "solo se serve".
MODA_GEMINI_SEMPRE = os.environ.get("MODA_GEMINI_SEMPRE", "1").strip() not in ("0", "false", "no", "")
try:
    MODA_GEMINI_MAX_ORA = int(os.environ.get("MODA_GEMINI_MAX_ORA", "60") or 60)
    MODA_GEMINI_FOTO = max(1, int(os.environ.get("MODA_GEMINI_FOTO", "8") or 8))
except ValueError:
    MODA_GEMINI_MAX_ORA, MODA_GEMINI_FOTO = 60, 8
CONF_REPLICA_MIN = 0.7   # sotto questa confidenza una "replica" resta un dubbio nel messaggio, non uno scarto
RAPPORTO_PREZZO_SOSPETTO = 0.25   # prezzo sotto il 25% della rivendita dei comparabili: troppo bello per essere vero

SYSTEM_PROMPT = """Sei un esperto di autenticazione di capi e accessori di moda usati (Vinted, Vestiaire, Grailed, eBay). Ricevi titolo, marca dichiarata, prezzo,
descrizione e TUTTE le foto di un annuncio. Guardale una per una e dici se quello che vedi e' coerente con la marca dichiarata, SOLO sui fatti visibili.

REGOLE
- Il prezzo non e' mai una prova: un prezzo basso con etichette coerenti e' un affare, non un falso. Non citarlo.
- Trascrivi solo cio' che si legge davvero; mai completare a memoria una dicitura. Nel dubbio campo vuoto o "non_leggibile".
- Se il venditore scrive "replica", "riproduzione", "ispirato a", "stile", "tipo": e' una dichiarazione di non originalita', prevale sulle foto.
- Elenca i riscontri coerenti, non solo i sospetti: un giudizio negativo su un solo dettaglio, ignorandone cinque coerenti, e' un errore.

COSA CERCARE (in ogni foto)
1. Etichetta principale (collo/interno): font, proporzioni, materiale, cucitura, linea (mainline o diffusion: MM6, See by Chloe, McQ, Weekend, Love Moschino...).
2. Etichetta di lavaggio/composizione: paese dopo "Made in", composizione, codice prodotto; etichetta taglia (stile ed epoca).
3. Logo, ricami, serigrafie, cuciture, zip e hardware (peso, incisioni, finitura), fodera, codici a rilievo o numeri di serie.
4. Documenti e accessori: fattura, scontrino, cartellino, certificato, dustbag, scatola. Registra solo cio' che si vede; non sono mai una prova da soli.
5. Marchio diverso: se l'etichetta mostra un nome diverso o non correlato al brand dichiarato (non una sottolinea della stessa maison) -> autenticita "altra_marca".
6. Il nome di un tessuto (es. Loro Piana, Cerruti) non e' il brand del capo.

PAESE DI PRODUZIONE
- Prada, Miu Miu, Loro Piana, Brunello Cucinelli, Bottega Veneta, Fendi producono l'abbigliamento in Italia: "Made in" asiatico (Cina, Bangladesh, Vietnam, India...) e' un'incoerenza forte,
  non puoi dire "probabile" (almeno "dubbia").
- Marchi con produzione mista (Max Mara, Zegna, Loewe, Missoni, Marni, Jil Sander, Helmut Lang, Westwood, JPG...): un paese insolito per linea o epoca e' un'incoerenza media.
- Se non conosci la produzione abituale del brand, il paese da solo non e' un segnale.
Prada e Miu Miu: il logo esterno non basta; serve il cartellino interno con layout e font tipici, altrimenti al massimo "dubbia".

ESITO
- "probabile": i dettagli visibili sono coerenti, nessuna incoerenza.
- "dubbia": qualche incoerenza o elementi chiave non visibili (cartellino interno, wash tag).
- "replica": indizi concreti e multipli (logo/font sbagliato, cuciture grossolane, hardware economico, etichetta incoerente). Non sospettare senza un indizio.
- "altra_marca": l'etichetta e' di un marchio diverso.
- "non_verificabile": nessuna etichetta o dettaglio leggibile nelle foto.
Non calcolare prezzi, margini o decisioni. Risposta breve: campi a poche parole, "motivo" una frase italiana (max 120 caratteri) con il fatto che ha deciso."""

SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": ["autenticita", "confidenza", "etichetta_letta", "made_in", "prova_acquisto", "indizi", "motivo"],
    "properties": {
        "autenticita": {"type": "STRING", "enum": ["probabile", "dubbia", "replica", "altra_marca", "non_verificabile"]},
        "confidenza": {"type": "NUMBER"},
        "etichetta_letta": {"type": "STRING"},
        "made_in": {"type": "STRING"},
        "prova_acquisto": {"type": "STRING", "enum": ["nessuna", "cartellino", "scontrino", "fattura", "certificato", "scatola_dustbag"]},
        "indizi": {"type": "STRING"},
        "motivo": {"type": "STRING"},
    },
    "required": ["autenticita", "confidenza", "etichetta_letta", "made_in", "prova_acquisto", "indizi", "motivo"],
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
    if MODA_GEMINI_SEMPRE:
        return True
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
    if not isinstance(d, dict) or d.get("autenticita") not in ("probabile", "dubbia", "replica", "altra_marca", "non_verificabile"):
        return None
    try:
        d["confidenza"] = max(0.0, min(1.0, float(d.get("confidenza"))))
    except (TypeError, ValueError):
        d["confidenza"] = None
    for campo in ("etichetta_letta", "made_in"):
        d[campo] = str(d.get(campo) or "")[:60]
    d["prova_acquisto"] = d.get("prova_acquisto") if d.get("prova_acquisto") in ("cartellino", "scontrino", "fattura", "certificato", "scatola_dustbag") else "nessuna"
    d["indizi"] = str(d.get("indizi") or "")[:160]
    d["motivo"] = str(d.get("motivo") or "")[:140]
    return d


def e_replica(d):
    """True se Gemini dice replica (o marchio diverso) con confidenza sufficiente a scartare l'avviso. Pura."""
    return bool(d and d.get("autenticita") in ("replica", "altra_marca") and (d.get("confidenza") or 0) >= CONF_REPLICA_MIN)


def riga_messaggio(d):
    """Riga (testo semplice) per il messaggio: esito del controllo Gemini sulle foto. Pura."""
    if not d:
        return None
    etichetta = {"probabile": "dettagli coerenti con la marca", "dubbia": "qualche dubbio sull'autenticita'",
                 "replica": "indizi di replica", "altra_marca": "etichetta di un altro marchio", "non_verificabile": "dalle foto non si verifica"}[d["autenticita"]]
    conf = f" ({d['confidenza']:.0%})" if d.get("confidenza") is not None else ""
    extra = []
    if d.get("made_in"):
        extra.append(f"made in {d['made_in']}")
    if d.get("prova_acquisto") and d["prova_acquisto"] != "nessuna":
        extra.append(f"visibile: {d['prova_acquisto'].replace('_', '/')}")
    dettagli = f" [{'; '.join(extra)}]" if extra else ""
    return f"🕵️ Gemini (tutte le foto): {etichetta}{conf}" + (f", {d['motivo']}" if d.get("motivo") else "") + dettagli + ". Indizio dalle foto, non certificazione"


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
        log.info("MODA GEMINI | item=%s | brand=%s | autenticita=%s | conf=%s | foto=%s | %.1fs | etichetta=%s | made_in=%s | prova=%s | indizi=%s | motivo=%s | titolo=%s",
                 item_id or "-", brand, (d or {}).get("autenticita", "nessuna_risposta"), (d or {}).get("confidenza", "-"),
                 min(len(foto), MODA_GEMINI_FOTO), time.time() - t0, (d or {}).get("etichetta_letta", "-"), (d or {}).get("made_in", "-"), (d or {}).get("prova_acquisto", "-"),
                 (d or {}).get("indizi", "-"), (d or {}).get("motivo", (testo or "")[:80]),
                 (titolo or "")[:60])
        return d
    except Exception as e:  # noqa: BLE001 - il controllo non deve mai fermare l'avviso
        log.warning("MODA GEMINI | item=%s | errore: %s", item_id or "-", e)
        return None
