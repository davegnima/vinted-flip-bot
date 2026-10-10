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
import math
import os
import re
import unicodedata
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


_SINONIMI = (("gba", "game boy advance"), ("gbc", "game boy color"), ("n64", "nintendo 64"))


def _normalizza(testo):
    testo = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode()  # plissé -> plisse
    testo = " " + re.sub(r"[^\w&]+", " ", testo.lower()).replace("gameboy", "game boy") + " "
    for corto, lungo in _SINONIMI:
        testo = testo.replace(f" {corto} ", f" {lungo} ")
    return re.sub(r"\s+", " ", testo).strip()


def _parole(testo):
    return frozenset(_normalizza(testo).split())


def prepara(righe):
    """Aggiunge a ogni riga le chiavi come insiemi di parole e il buy_max calcolato. Pura."""
    pronte = []
    for r in righe:
        chiavi = [k for k in {_parole(c) for c in r.get("chiavi") or ()} if k]
        if not chiavi:
            continue
        usabile = (r.get("rivendita_veloce_eur") and r.get("affidabilita") in _AFFIDABILITA_USABILI
                   and not r.get("sotto_soglia") and not r.get("escluso"))
        bm = buy_max(r["rivendita_veloce_eur"], r.get("spedizione_eur"), r.get("rischio_falsi"),
                     r.get("rischio_guasti")) if usabile else None
        pronte.append({**r, "_chiavi": chiavi, "_brand": [k for k in (_parole(b) for b in r.get("brand_chiavi") or ()) if k],
                       "_variante": [k for k in (_parole(v) for v in r.get("parole_variante") or ()) if k],
                       "_escluse": [k for k in (_parole(v) for v in r.get("parole_escluse") or ()) if k],
                       "buy_max": bm})
    # Peso di una chiave = rarita' (idf) della sua parola piu' rara, piu' un centesimo della somma per gli spareggi:
    # "pokemon cristallo" batte "game boy color pokemon" perche' "cristallo" e' rara e le altre sono ovunque.
    df = {}
    for r in pronte:
        for w in set().union(*r["_chiavi"]):
            df[w] = df.get(w, 0) + 1
    # Le parole del brand ("scotty", "cameron") non contano: sono rare tra le righe ma non distinguono il modello.
    parole_brand = set().union(*(b for r in pronte for b in r["_brand"])) if pronte else set()
    n = len(pronte) + 1
    for r in pronte:
        r["_pesi"] = {}
        for k in r["_chiavi"]:
            idf = [math.log(n / df[w]) for w in k if w not in parole_brand] or [0.1]
            r["_pesi"][k] = round(max(idf) + 0.01 * sum(idf), 6)
    return pronte


def trova_modello(titolo, brand, matrice):
    """Riga della matrice citata dal titolo, None se nessuna. Una chiave e' citata se tutte le sue parole sono nel
    titolo (in qualsiasi ordine) e nessuna delle sue `parole_escluse` lo e'; vince la chiave con le parole piu' rare (peso idf, vedi `prepara`). Se la riga ha `brand_chiavi` serve anche il brand
    nel titolo o nel campo brand dell'annuncio. A parita' (es. stesso set LEGO usato e sigillato) vince la riga le cui
    `parole_variante` sono nel titolo, altrimenti quella senza varianti, altrimenti la rivendita piu' bassa. Pura."""
    t = _parole(" ".join(p for p in (brand or "", titolo or "") if p))
    candidati, migliore = [], 0
    for r in matrice:
        n = max((r["_pesi"][k] for k in r["_chiavi"] if k <= t), default=0)
        if not n or (r["_brand"] and not any(b <= t for b in r["_brand"])):
            continue
        if any(e <= t for e in r.get("_escluse") or ()):
            continue  # es. console: "giochi", "custodia", "schermo" nel titolo = non e' la console
        if r["_variante"] and not any(v <= t for v in r["_variante"]):
            n = n * 0.9  # "in scatola"/"sigillato" senza le sue parole nel titolo: a pari chiave vince la riga base
        n = round(n, 6)
        if n > migliore:
            candidati, migliore = [r], n
        elif n == migliore:
            candidati.append(r)
    if not candidati:
        return None
    if len(candidati) > 1:
        con_variante = [r for r in candidati if any(v <= t for v in r["_variante"])]
        candidati = con_variante or [r for r in candidati if not r["_variante"]] or candidati
        candidati.sort(key=lambda r: r.get("rivendita_veloce_eur") or 0)
    return candidati[0]


def valuta_modello(titolo, brand, prezzo, matrice):
    """(esito, riga) per il livello 1: 'nessuno' (si usa il tetto del modulo), 'sotto_soglia', 'escluso' (es. non
    spedibile), 'sopra_buy_max', 'senza_dati' (modello noto ma prezzi poco affidabili: tetto del modulo), 'ok'. Pura."""
    r = trova_modello(titolo, brand, matrice)
    if r is None:
        return "nessuno", None
    if r.get("escluso"):
        return "escluso", r
    if r.get("sotto_soglia"):
        return "sotto_soglia", r
    # Riga "in scatola"/"sigillato" senza le sue parole nel titolo (es. cartuccia sfusa agganciata alla riga completa,
    # 9/10): il suo buy max non vale, decide il tetto del modulo.
    if r["buy_max"] is None or (r["_variante"] and not any(v <= _parole(f"{brand or ''} {titolo or ''}")
                                                            for v in r["_variante"])):
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


# Radar spento (RADAR_ATTIVO=0, 10/10): la matrice non si carica.
MATRICE = carica_matrice() if os.environ.get("RADAR_ATTIVO", "1").strip() not in ("0", "false", "no", "") else []
