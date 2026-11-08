"""Radar: filtri appresi dai dati (31/10, richiesta dell'utente: il sistema impara e riduce il rumore da solo).

Una "famiglia" e' il testo dei comparabili di un annuncio (es. "nintendo wii console"). Ogni volta che il radar valuta un annuncio
senza allargare la ricerca e con abbastanza comparabili, registra il prezzo massimo di acquisto che darebbe margine e ROI minimi
calcolato sul 75° percentile (stima generosa). Se dopo MIN_OSS osservazioni negli ultimi RADAR_APPRESO_GIORNI giorni anche il
limite piu' alto e' sotto il prezzo dell'annuncio (con un margine di sicurezza), gli annunci della famiglia sopra quel limite
si scartano senza richiesta a Vinted. Un annuncio su RADAR_APPRESO_CAMPIONE passa comunque il calcolo completo, cosi' un
mercato che cambia si scopre. Lo stato si ricostruisce dal DB (eventi radar_v2) a ogni avvio: sopravvive ai deploy.
"""
import os
import time

from bot import db
from bot.logger import log
from bot.valore_mercato import _PAROLE_GENERICHE, _PAROLE_VUOTE

RADAR_APPRESO = os.environ.get("RADAR_APPRESO", "1").strip() in ("1", "true", "si")
RADAR_APPRESO_GIORNI = float(os.environ.get("RADAR_APPRESO_GIORNI", "14") or 14)
RADAR_APPRESO_CAMPIONE = int(os.environ.get("RADAR_APPRESO_CAMPIONE", "10") or 10)  # 1 su N passa comunque (0 = mai)
MIN_OSS = 3
MIN_OSS_GRUPPO = 5       # gruppo = prime 3 parole utili della famiglia (8/11, utente: apprendere dai dati che ci sono)
MIN_FAMIGLIE_GRUPPO = 2  # il gruppo deve coprire almeno 2 famiglie diverse, altrimenti e' solo una famiglia
MIN_COMPARABILI = 6
_MAX_OSS = 30
_oss = {}      # famiglia -> [(ts, limite)]
_gruppi = {}   # prime 3 parole -> [(ts, limite, famiglia)]
_contatori = {}  # famiglia -> annunci saltati (per il campione)
_segnalate = set()


_COLORI_EXTRA = {"grigia", "rosa", "giallo", "gialla", "viola", "arancione", "marrone", "beige", "oro", "argento", "silver", "gold",
                 "pink", "grey", "gray", "red", "blue", "green", "nuova", "nuovo", "usato", "bianco", "bianca"}


def normalizza(famiglia):
    """Famiglia senza colori e parole di condizione (8/11, utente: i modelli che non valgono si imparano una volta sola):
    'nintendo switch lite grigia' e 'nintendo switch lite' sono lo stesso mercato. Pura."""
    if not famiglia:
        return famiglia
    parole = [w for w in famiglia.split() if w not in _PAROLE_GENERICHE and w not in _PAROLE_VUOTE and w not in _COLORI_EXTRA]
    return " ".join(parole) if len(parole) >= 2 else famiglia


def gruppo(famiglia):
    """Chiave piu' larga: le prime 3 parole della famiglia normalizzata ('nintendo switch lite' da 'nintendo switch lite grise').
    None se la famiglia ha meno di 4 parole (e' gia' la chiave piu' stretta). Pura."""
    parole = (famiglia or "").split()
    return " ".join(parole[:3]) if len(parole) >= 4 else None


def registra(famiglia, limite, n_usati, allargata, adesso=None):
    """Registra un'osservazione se e' solida (ricerca non allargata, abbastanza comparabili, limite noto). Pura salvo lo stato."""
    famiglia = normalizza(famiglia)
    if not famiglia or limite is None or allargata or n_usati < MIN_COMPARABILI:
        return False
    lista = _oss.setdefault(famiglia, [])
    lista.append((adesso if adesso is not None else time.time(), max(float(limite), 0.0)))
    del lista[:-_MAX_OSS]
    g = gruppo(famiglia)
    if g:
        elenco = _gruppi.setdefault(g, [])
        elenco.append((lista[-1][0], lista[-1][1], famiglia))
        del elenco[:-_MAX_OSS * 4]
    return True


def limite_famiglia(famiglia, adesso=None):
    """Il limite di acquisto piu' alto visto di recente se le osservazioni bastano, altrimenti None. Pura."""
    adesso = adesso if adesso is not None else time.time()
    famiglia = normalizza(famiglia)
    recenti = [lim for ts, lim in _oss.get(famiglia, ()) if adesso - ts < RADAR_APPRESO_GIORNI * 86400]
    if len(recenti) >= MIN_OSS:
        return max(recenti)
    # famiglia con poche osservazioni: si usa il gruppo (stesso modello scritto in modi diversi). Il limite e' il piu' alto
    # del gruppo, quindi un modello di valore maggiore nel gruppo alza il limite e fa saltare meno, mai di piu'.
    g = gruppo(famiglia)
    if g:
        rec = [(lim, f) for ts, lim, f in _gruppi.get(g, ()) if adesso - ts < RADAR_APPRESO_GIORNI * 86400]
        if len(rec) >= MIN_OSS_GRUPPO and len({f for _, f in rec}) >= MIN_FAMIGLIE_GRUPPO:
            return max(lim for lim, _ in rec)
    return None


def n_apprese(adesso=None):
    """(famiglie, gruppi) che oggi fanno saltare gli annunci sopra il limite. Per il log di avvio."""
    adesso = adesso if adesso is not None else time.time()
    fam = sum(1 for f in _oss if limite_famiglia(f, adesso) is not None)
    gr = sum(1 for g in _gruppi if limite_famiglia(g + " _", adesso) is not None)
    return fam, gr


def da_saltare(famiglia, prezzo, adesso=None):
    """Limite appreso se l'annuncio va scartato senza calcolo (prezzo oltre il limite con margine di sicurezza), altrimenti None."""
    if not RADAR_APPRESO or prezzo is None:
        return None
    famiglia = normalizza(famiglia)
    limite = limite_famiglia(famiglia, adesso)
    if limite is None or prezzo <= limite * 1.25 + 2:
        return None
    n = _contatori[famiglia] = _contatori.get(famiglia, 0) + 1
    if RADAR_APPRESO_CAMPIONE and n % RADAR_APPRESO_CAMPIONE == 0:
        return None
    if famiglia not in _segnalate:
        _segnalate.add(famiglia)
        log.info("RADAR APPRESO | famiglia=%s | limite=%.0f | osservazioni=%d | da ora gli annunci sopra il limite si scartano",
                 famiglia, limite, len(_oss.get(famiglia, ())))
    return limite


def carica_dal_db(adesso=None):
    """Ricostruisce lo stato dagli eventi radar_v2 degli ultimi giorni. Ritorna quante osservazioni ha caricato."""
    adesso = adesso if adesso is not None else time.time()
    n = 0
    try:
        for e in db.leggi_eventi("radar_v2", adesso - RADAR_APPRESO_GIORNI * 86400):
            if registra(e.get("fam"), e.get("limite"), e.get("n_usati") or 0, e.get("allargata"), e.get("ts")):
                n += 1
    except Exception as exc:
        log.warning("RADAR APPRESO | caricamento non riuscito (%s)", type(exc).__name__)
    fam, gr = n_apprese(adesso)
    log.info("RADAR APPRESO | caricate %d osservazioni, %d famiglie, %d famiglie con limite appreso, %d gruppi", n, len(_oss), fam, gr)
    return n
