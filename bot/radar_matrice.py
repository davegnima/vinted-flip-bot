"""Matrice dei modelli del radar (richiesta dall'utente l'8/10, brief "Vinted Arbitrage Bot", deliverable A e B).

Dati: `data/radar_matrice.json`, una riga per modello (brand, modello, chiavi di ricerca nel titolo, rivendita veloce
ricavata da venduti reali con fonte, spedizione, rischi). Come e' stata costruita: `docs/radar-matrice.md`.

Economia (deliverable B), stessa base di `calcola_verdetto` (protezione acquisti Vinted + spedizione in entrata):
  costo(p)      = p * (1 + COMMISSIONE_PROTEZIONE_PCT) + COMMISSIONE_PROTEZIONE_FISSA + spedizione
  netto(R)      = R * (1 - SCONTO_TIPICO_TRATTATIVA_VENDITA) - riserva_rischio(R)
  margine       = netto - costo            (>= RADAR_MARGINE_MIN)
  ROI           = margine / costo          (>= RADAR_ROI_MIN %)
  buy_max       = prezzo massimo che rispetta entrambe: costo_max = min(netto - margine_min, netto / (1 + roi_min))
La riserva di rischio e' una quota della rivendita per ogni punto di rischio falsi/guasti sopra 2 (scala 1-5):
valore di partenza, da tarare con gli esiti reali.
"""
import json
import os
import re
from pathlib import Path

from bot.config import COMMISSIONE_PROTEZIONE_FISSA, COMMISSIONE_PROTEZIONE_PCT, SCONTO_TIPICO_TRATTATIVA_VENDITA
from bot.logger import log
# ---- fine import ----

MATRICE_PERCORSO = Path(os.environ.get("RADAR_MATRICE_PERCORSO", "")
                        or Path(__file__).resolve().parent.parent / "data" / "radar_matrice.json")
RADAR_MARGINE_MIN = float(os.environ.get("RADAR_MARGINE_MIN", "50") or 50)
RADAR_ROI_MIN = float(os.environ.get("RADAR_ROI_MIN", "100") or 100)
RADAR_RISERVA_PER_PUNTO = float(os.environ.get("RADAR_RISERVA_PER_PUNTO", "0.03") or 0)
# Il livello 1 lascia passare fino a buy_max x tolleranza: oltre il buy_max resta la trattativa.
RADAR_TOLLERANZA_BUY_MAX = float(os.environ.get("RADAR_TOLLERANZA_BUY_MAX", "1.15") or 1)
# Righe con affidabilita' sotto questa non danno un buy_max (si torna al tetto del modulo).
_AFFIDABILITA_USABILI = ("alta", "media")


def costo_acquisto(prezzo, spedizione_eur):
    return prezzo * (1 + COMMISSIONE_PROTEZIONE_PCT) + COMMISSIONE_PROTEZIONE_FISSA + (spedizione_eur or 0)


def netto_rivendita(rivendita, rischio_falsi=1, rischio_guasti=1):
    punti = max(0, (rischio_falsi or 1) - 2) + max(0, (rischio_guasti or 1) - 2)
    return rivendita * (1 - SCONTO_TIPICO_TRATTATIVA_VENDITA) - rivendita * RADAR_RISERVA_PER_PUNTO * punti


def margine_roi(prezzo, rivendita, spedizione_eur, rischio_falsi=1, rischio_guasti=1):
    """(margine EUR, ROI %) stimati comprando a `prezzo` e rivendendo a `rivendita`. Pura."""
    costo = costo_acquisto(prezzo, spedizione_eur)
    margine = netto_rivendita(rivendita, rischio_falsi, rischio_guasti) - costo
    return round(margine, 2), round(margine / costo * 100, 1) if costo > 0 else 0.0


def buy_max(rivendita, spedizione_eur, rischio_falsi=1, rischio_guasti=1):
    """Prezzo Vinted massimo con margine >= RADAR_MARGINE_MIN e ROI >= RADAR_ROI_MIN; 0 se nessun prezzo basta. Pura."""
    if not rivendita or rivendita <= 0:
        return 0
    netto = netto_rivendita(rivendita, rischio_falsi, rischio_guasti)
    costo_max = min(netto - RADAR_MARGINE_MIN, netto / (1 + RADAR_ROI_MIN / 100))
    prezzo = (costo_max - COMMISSIONE_PROTEZIONE_FISSA - (spedizione_eur or 0)) / (1 + COMMISSIONE_PROTEZIONE_PCT)
    return int(prezzo) if prezzo > 0 else 0


def _normalizza(testo):
    return re.sub(r"\s+", " ", re.sub(r"[^\w&]+", " ", (testo or "").lower())).strip()


def _contiene(chiave, testo_norm):
    return re.search(r"(?<!\w)" + re.escape(chiave) + r"(?!\w)", testo_norm) is not None


def prepara(righe):
    """Aggiunge a ogni riga le chiavi normalizzate e il buy_max calcolato. Pura."""
    pronte = []
    for r in righe:
        chiavi = sorted({_normalizza(c) for c in r.get("chiavi") or () if _normalizza(c)}, key=len, reverse=True)
        if not chiavi:
            continue
        usabile = (r.get("rivendita_veloce_eur") and r.get("affidabilita") in _AFFIDABILITA_USABILI
                   and not r.get("sotto_soglia"))
        bm = buy_max(r["rivendita_veloce_eur"], r.get("spedizione_eur"), r.get("rischio_falsi"),
                     r.get("rischio_guasti")) if usabile else None
        pronte.append({**r, "_chiavi": chiavi, "_brand": [_normalizza(b) for b in r.get("brand_chiavi") or ()],
                       "buy_max": bm})
    return pronte


def trova_modello(titolo, brand, matrice):
    """Riga della matrice citata dal titolo (chiave piu' lunga vince), None se nessuna. Se la riga ha `brand_chiavi`
    serve anche il brand nel titolo o nel campo brand dell'annuncio (chiavi generiche come "arco"). Pura."""
    t = _normalizza(" ".join(p for p in (brand or "", titolo or "") if p))
    migliore, lung = None, 0
    for r in matrice:
        for c in r["_chiavi"]:
            if len(c) <= lung or not _contiene(c, t):
                continue
            if r["_brand"] and not any(_contiene(b, t) for b in r["_brand"]):
                continue
            migliore, lung = r, len(c)
            break
    return migliore


def valuta_modello(titolo, brand, prezzo, matrice):
    """(esito, riga) per il livello 1: 'nessuno' (si usa il tetto del modulo), 'sotto_soglia', 'sopra_buy_max',
    'senza_dati' (modello noto ma prezzi insufficienti: tetto del modulo), 'ok'. Pura."""
    r = trova_modello(titolo, brand, matrice)
    if r is None:
        return "nessuno", None
    if r.get("sotto_soglia"):
        return "sotto_soglia", r
    if r["buy_max"] is None:
        return "senza_dati", r
    if r["buy_max"] <= 0 or (prezzo is not None and prezzo > r["buy_max"] * RADAR_TOLLERANZA_BUY_MAX):
        return "sopra_buy_max", r
    return "ok", r


def carica_matrice(percorso=None):
    p = Path(percorso or MATRICE_PERCORSO)
    try:
        righe = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("Radar: matrice modelli %s assente, si usano solo i tetti dei moduli", p)
        return []
    except (OSError, ValueError) as e:
        log.warning("Radar: matrice modelli %s illeggibile (%s), si usano solo i tetti dei moduli", p, e)
        return []
    pronte = prepara(righe)
    log.info("Radar: matrice modelli caricata, %d righe (%d con buy_max)", len(pronte),
             sum(1 for r in pronte if r["buy_max"]))
    return pronte


MATRICE = carica_matrice()
