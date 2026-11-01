"""Controllo Gemini sui gialli e verdi del radar non moda (01/11, richiesta dell'utente).

Perche': la moda gira in SOLO_SEMAFORO (niente Occhio/Cervello) e la quota gratuita di Gemini resta libera. Ai pochi avvisi del radar
che hanno gia' superato semaforo e Jev si aggiunge una lettura delle FOTO (scaricate dalla pagina come nella moda) piu' descrizione:
Occhio e Cervello in UNA sola chiamata, con prompt per oggetti non moda (stato, completezza, danni, replica), non per capi di marca.
Regole: Gemini NON calcola margine, ROI o decisione (restano del codice); conferma, mette in dubbio o scarta, e dà la SUA stima di rivendita
(dalla conoscenza del modello e dalle foto, come il Cervello della moda), mostrata nel messaggio come stima accanto a quella del codice, senza cambiarne il semaforo.
Se Gemini non risponde (quota, errore) l'avviso parte lo stesso con una riga che lo dichiara: un affare non si perde per un 429.
Solo Gemini gratuito (cascata e chiavi di GEMINI_API_KEYS, ruolo 'occhio'); nessun servizio a pagamento.
"""
import asyncio
import json
import os
import time

from bot.config import MAX_GALLERY_PHOTOS
from bot.foto import download_image_bytes
from bot.gemini_api import chiama_gemini
from bot.logger import log

RADAR_GEMINI = os.environ.get("RADAR_GEMINI", "1").strip() not in ("0", "false", "no", "")
try:
    RADAR_GEMINI_MAX_ORA = int(os.environ.get("RADAR_GEMINI_MAX_ORA", "40") or 40)
    RADAR_GEMINI_FOTO = max(1, min(int(os.environ.get("RADAR_GEMINI_FOTO", "10") or 10), MAX_GALLERY_PHOTOS))
except ValueError:
    RADAR_GEMINI_MAX_ORA, RADAR_GEMINI_FOTO = 40, 10

SYSTEM_PROMPT = """Sei un controllore di annunci second hand di oggetti NON di moda (console, foto, elettronica, utensili, hi-fi, casa, giochi).
Ricevi titolo, prezzo, descrizione e alcune foto di UN annuncio che ha gia' superato un controllo sul prezzo. Il tuo compito e' dire se
l'oggetto e' davvero quello che il titolo promette, se si puo' rivendere cosi' com'e' e a quanto. Non calcolare margini o ROI: lo fa il codice.

Guarda le foto e il testo e rispondi solo sui fatti visibili o dichiarati:
- oggetto: marca e modello che leggi (etichette, serigrafie, schermo, scatola); se non li leggi scrivi "non leggibile".
- corrisponde_al_titolo: "si" se le foto mostrano l'oggetto del titolo, "no" se mostrano altro (solo scatola, accessorio, giocattolo, lotto misto, foto di catalogo rubata), "dubbio" se non si capisce.
- funzionante: "no" se il testo dichiara guasto, bloccato, iCloud/account, per ricambi, non si accende, display rotto; "si" se dichiarato funzionante o provato; "non_dichiarato" se non se ne parla.
- completo: "no" se manca una parte essenziale (cavo, alimentatore, obiettivo, batteria, controller, pezzi di un set) dichiarata o evidente; "si" altrimenti; "non_chiaro" se non si capisce.
- danni_visibili: "gravi" (crepe, rotture, ruggine diffusa, muffa, parti mancanti), "lievi" (graffi, usura normale), "nessuno".
- autenticita: "replica" se segni evidenti di copia o clone, "dubbia" se c'e' un motivo concreto di sospetto, "probabile" altrimenti. Non sospettare senza un indizio.
- verdetto: "scarta" se corrisponde_al_titolo = no, funzionante = no, danni gravi, replica o completo = no su una parte essenziale; "dubbio" se i fatti non bastano (foto poco chiare, testo ambiguo); "conferma" se tutto torna.
- motivo: una frase breve in italiano (max 110 caratteri) con il fatto che ha deciso, senza numeri di prezzo.
- confidenza: tra 0 e 1, quanto sei sicuro del verdetto.
- rivendita_eur: la tua stima in EUR del prezzo realistico a cui questo esemplare, nelle condizioni che vedi, si rivende usato in Italia in tempi brevi (non il prezzo di listino ne' di un esemplare nuovo). Usa il modello e lo stato che leggi dalle foto. Se non conosci abbastanza il modello scrivi 0.
- rivendita_confidenza: tra 0 e 1, quanto sei sicuro di quella stima (sotto 0,4 se il modello e' poco noto o le foto non bastano).
- rivendita_base: max 100 caratteri, su cosa si basa la stima (es. 'modello comune, prezzi usati tipici 90-110').
- velocita_rivendita: quanto ci mette tipicamente questo oggetto usato a vendersi in Italia a quel prezzo: "ore" (entro 24 h), "giorni" (entro una settimana), "settimane", "mesi". Usa la tua conoscenza del mercato dell'usato e di quanto e' richiesto il modello.
- velocita_base: max 100 caratteri, su cosa si basa (es. 'console molto richiesta, si vende subito').
- ricerca_modello: la ricerca di annunci SIMILI da fare su Vinted per trovare lo STESSO modello esatto che vedi/leggi (marca + modello + variante, 2-5 parole in minuscolo, senza condizioni ne' parole come usato/vendo). Es. 'nintendo switch oled', 'dyson v11 absolute'. Se non riconosci il modello scrivi "".
- ricerca_semantica: una ricerca piu' larga ma ancora molto comparabile (stessa famiglia/serie, 2-4 parole), da usare solo se quella del modello esatto trova pochi annunci. Es. 'nintendo switch console'. Se non sai scrivi "".
Nel dubbio tra scarta e dubbio scegli dubbio; nel dubbio tra dubbio e conferma scegli dubbio. Non inventare cio' che non vedi."""

SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": ["oggetto", "corrisponde_al_titolo", "funzionante", "completo", "danni_visibili", "autenticita",
                         "verdetto", "motivo", "confidenza", "rivendita_eur", "rivendita_confidenza", "rivendita_base",
                         "velocita_rivendita", "velocita_base", "ricerca_modello", "ricerca_semantica"],
    "properties": {
        "oggetto": {"type": "STRING"},
        "corrisponde_al_titolo": {"type": "STRING", "enum": ["si", "no", "dubbio"]},
        "funzionante": {"type": "STRING", "enum": ["si", "no", "non_dichiarato"]},
        "completo": {"type": "STRING", "enum": ["si", "no", "non_chiaro"]},
        "danni_visibili": {"type": "STRING", "enum": ["nessuno", "lievi", "gravi"]},
        "autenticita": {"type": "STRING", "enum": ["probabile", "dubbia", "replica"]},
        "verdetto": {"type": "STRING", "enum": ["conferma", "dubbio", "scarta"]},
        "motivo": {"type": "STRING"},
        "confidenza": {"type": "NUMBER"},
        "rivendita_eur": {"type": "NUMBER"},
        "rivendita_confidenza": {"type": "NUMBER"},
        "rivendita_base": {"type": "STRING"},
        "velocita_rivendita": {"type": "STRING", "enum": ["ore", "giorni", "settimane", "mesi"]},
        "velocita_base": {"type": "STRING"},
        "ricerca_modello": {"type": "STRING"},
        "ricerca_semantica": {"type": "STRING"},
    },
    "required": ["oggetto", "corrisponde_al_titolo", "funzionante", "completo", "danni_visibili", "autenticita", "verdetto", "motivo", "confidenza",
                 "rivendita_eur", "rivendita_confidenza", "rivendita_base",
                 "velocita_rivendita", "velocita_base", "ricerca_modello", "ricerca_semantica"],
}

VELOCITA = {"ore": "entro 24 ore", "giorni": "entro una settimana", "settimane": "in alcune settimane", "mesi": "lenta, anche mesi"}

_chiamate = []   # istanti (time.time) delle chiamate dell'ultima ora: tetto RADAR_GEMINI_MAX_ORA


def _entro_il_tetto(adesso=None):
    adesso = adesso if adesso is not None else time.time()
    while _chiamate and adesso - _chiamate[0] > 3600:
        _chiamate.pop(0)
    return len(_chiamate) < RADAR_GEMINI_MAX_ORA


def testo_utente(titolo, prezzo, descrizione, condizione=None):
    """Testo dell'annuncio per Gemini. Pura."""
    righe = [f"Titolo: {titolo}", f"Prezzo richiesto: {prezzo:g} EUR" if isinstance(prezzo, (int, float)) else "Prezzo richiesto: n/d"]
    if condizione:
        righe.append(f"Condizione dichiarata: {condizione}")
    righe.append("Descrizione del venditore: " + ((descrizione or "").strip()[:1500] or "(vuota)"))
    return "\n".join(righe)


def leggi_risposta(testo):
    """Dict valido dalla risposta di Gemini, o None. Pura."""
    if not testo or testo.lstrip().startswith("[ERRORE"):
        return None
    try:
        d = json.loads(testo)
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("verdetto") not in ("conferma", "dubbio", "scarta"):
        return None
    try:
        d["confidenza"] = max(0.0, min(1.0, float(d.get("confidenza"))))
    except (TypeError, ValueError):
        d["confidenza"] = None
    d["motivo"] = str(d.get("motivo") or "")[:140]
    try:
        r = float(d.get("rivendita_eur"))
        d["rivendita_eur"] = round(r, 2) if r > 0 else None   # 0 = "non conosco il modello": nessuna stima
    except (TypeError, ValueError):
        d["rivendita_eur"] = None
    try:
        d["rivendita_confidenza"] = max(0.0, min(1.0, float(d.get("rivendita_confidenza"))))
    except (TypeError, ValueError):
        d["rivendita_confidenza"] = None
    d["rivendita_base"] = str(d.get("rivendita_base") or "")[:110]
    d["velocita_rivendita"] = d.get("velocita_rivendita") if d.get("velocita_rivendita") in VELOCITA else None
    d["velocita_base"] = str(d.get("velocita_base") or "")[:110]
    for k in ("ricerca_modello", "ricerca_semantica"):
        d[k] = " ".join(str(d.get(k) or "").lower().split())[:60]
    return d


async def _foto_pagina(url, foto_tracker):
    """(foto_bytes_list, descrizione, condizione): foto scaricate dalla pagina come nella moda (fino a RADAR_GEMINI_FOTO), con la foto
    del tracker come ripiego. Una richiesta di pagina per candidato (pochi al giorno)."""
    from bot.vinted_scrape import scrape_vinted_listing   # import tardivo: il modulo e' pesante e si carica solo se serve
    scraped = {}
    try:
        scraped = await scrape_vinted_listing(url, includi_guardaroba=False) or {}
    except Exception:  # noqa: BLE001 - senza pagina restano la foto del tracker e il titolo
        log.warning("RADAR GEMINI | pagina non letta per %s", url)
    urls = (scraped.get("photo_urls") or [])[:RADAR_GEMINI_FOTO]
    foto = []
    if urls:
        scaricate = await asyncio.gather(*(download_image_bytes(u, referer=url) for u in urls))
        foto = [b for b in scaricate if b]
    if not foto and foto_tracker:
        foto = [foto_tracker]
    return foto, scraped.get("description"), scraped.get("condition")


async def controlla(titolo, prezzo, url, foto_tracker=None, item_id=None):
    """Controllo Gemini di un candidato. Ritorna dict (vedi SCHEMA) oppure None se spento, oltre il tetto orario o senza risposta. Mai eccezioni."""
    if not RADAR_GEMINI:
        return None
    try:
        if not _entro_il_tetto():
            log.info("RADAR GEMINI | item=%s | oltre il tetto orario (%s/h): avviso senza controllo", item_id, RADAR_GEMINI_MAX_ORA)
            return None
        foto, descrizione, condizione = await _foto_pagina(url, foto_tracker)
        _chiamate.append(time.time())
        t0 = time.time()
        testo, costo, _n = await chiama_gemini(SYSTEM_PROMPT, testo_utente(titolo, prezzo, descrizione, condizione), foto,
                                               grounding=False, response_schema=SCHEMA, ruolo="occhio")
        d = leggi_risposta(testo)
        log.info("RADAR GEMINI | item=%s | verdetto=%s | conf=%s | oggetto=%s | funz=%s | completo=%s | danni=%s | autent=%s | foto=%s | %.1fs | rivendita_gem=%s | conf_riv=%s | velocita=%s | ric_modello=%s | ric_sem=%s | motivo=%s | titolo=%s",
                 item_id, d["verdetto"] if d else "nessuna_risposta", d.get("confidenza") if d else "-", (d or {}).get("oggetto", "-"),
                 (d or {}).get("funzionante", "-"), (d or {}).get("completo", "-"), (d or {}).get("danni_visibili", "-"),
                 (d or {}).get("autenticita", "-"), len(foto), time.time() - t0, (d or {}).get("rivendita_eur"), (d or {}).get("rivendita_confidenza"), (d or {}).get("velocita_rivendita"), (d or {}).get("ricerca_modello"), (d or {}).get("ricerca_semantica"), (d or {}).get("motivo", (testo or "")[:80]), (titolo or "")[:60])
        return d
    except Exception as e:  # noqa: BLE001 - il controllo non deve mai fermare l'avviso
        log.warning("RADAR GEMINI | item=%s | errore: %s", item_id, e)
        return None


def riga_gemini(d):
    """Riga del messaggio Telegram sul controllo Gemini. Pura."""
    if not d:
        return "Gemini: non disponibile, avviso senza lettura delle foto"
    etichetta = {"conferma": "confermato", "dubbio": "da rivedere", "scarta": "scartato"}[d["verdetto"]]
    conf = f" (confidenza {d['confidenza']:.2f})".replace(".", ",") if d.get("confidenza") is not None else ""
    riga = f"Gemini foto: {etichetta}{conf}" + (f", {d['motivo']}" if d.get("motivo") else "")
    if d.get("rivendita_eur"):
        rc = d.get("rivendita_confidenza")
        riga += f"\nStima Gemini della rivendita: circa {d['rivendita_eur']:g} € (stima" + (f", confidenza {rc:.2f}".replace(".", ",") if rc is not None else "") + ")" \
                + (f": {d['rivendita_base']}" if d.get("rivendita_base") else "")
    if d.get("velocita_rivendita"):
        riga += f"\nVelocità di rivendita stimata da Gemini: {VELOCITA[d['velocita_rivendita']]} (stima)" + (f": {d['velocita_base']}" if d.get("velocita_base") else "")
    return riga
