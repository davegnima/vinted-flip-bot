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

RADAR_APPRESO = os.environ.get("RADAR_APPRESO", "1").strip() in ("1", "true", "si")
RADAR_APPRESO_GIORNI = float(os.environ.get("RADAR_APPRESO_GIORNI", "7") or 7)
RADAR_APPRESO_CAMPIONE = int(os.environ.get("RADAR_APPRESO_CAMPIONE", "10") or 10)  # 1 su N passa comunque (0 = mai)
MIN_OSS = 3
MIN_COMPARABILI = 6
_MAX_OSS = 30
_oss = {}      # famiglia -> [(ts, limite)]
_contatori = {}  # famiglia -> annunci saltati (per il campione)
_segnalate = set()


def registra(famiglia, limite, n_usati, allargata, adesso=None):
    """Registra un'osservazione se e' solida (ricerca non allargata, abbastanza comparabili, limite noto). Pura salvo lo stato."""
    if not famiglia or limite is None or allargata or n_usati < MIN_COMPARABILI:
        return False
    lista = _oss.setdefault(famiglia, [])
    lista.append((adesso if adesso is not None else time.time(), max(float(limite), 0.0)))
    del lista[:-_MAX_OSS]
    return True


def limite_famiglia(famiglia, adesso=None):
    """Il limite di acquisto piu' alto visto di recente se le osservazioni bastano, altrimenti None. Pura."""
    adesso = adesso if adesso is not None else time.time()
    recenti = [lim for ts, lim in _oss.get(famiglia, ()) if adesso - ts < RADAR_APPRESO_GIORNI * 86400]
    return max(recenti) if len(recenti) >= MIN_OSS else None


def da_saltare(famiglia, prezzo, adesso=None):
    """Limite appreso se l'annuncio va scartato senza calcolo (prezzo oltre il limite con margine di sicurezza), altrimenti None."""
    if not RADAR_APPRESO or prezzo is None:
        return None
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
    log.info("RADAR APPRESO | caricate %d osservazioni, %d famiglie", n, len(_oss))
    return n
