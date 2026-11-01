# Anomalie di prezzo per marca, categoria e prodotto (01/11): quali identita' hanno gia' prodotto inefficienze vere e vendute in fretta.
# Unisce `RADAR V2 OMBRA` (prezzo, rivendita, margine, ricerca, titolo) e `TRACCIATO_RADAR` (marca, esito di vendita) di un file di log.
# Solo letture, zero banda. Uso: python3 anomalie.py LOG.txt [--min 3]   (file scaricato con i filtri di docs/procedure/analisi-log.md)
# Anomalia = margine >= 50 e ROI >= 100 (come l'avviso) oppure prezzo <= 60% della mediana dell'identita' (con >= 3 annunci).
# Un numero con meno di 15 casi e' solo indicativo: la tabella riporta sempre n.
import re
import statistics
import sys
from collections import defaultdict

import json
import os

ENTRO_S = 3600
_EXTRA = ("nintendo", "sony", "playstation", "xbox", "microsoft", "sega", "canon", "nikon", "fujifilm", "gopro", "garmin", "dji", "bose", "jbl",
          "technics", "panasonic", "olympus", "leica", "kodak", "minolta", "pentax", "samsung", "apple", "lego", "ghd", "dyson", "makita",
          "milwaukee", "dewalt", "festool", "sonos", "marantz", "pioneer", "yamaha", "steam", "valve", "polaroid", "contax", "hasselblad")


def _marche():
    try:
        qui = os.path.dirname(os.path.abspath(__file__))
        base = json.load(open(os.path.join(qui, "dati", "brand_ids.json"), encoding="utf-8")).get("marchi", {})
    except (OSError, ValueError):
        base = {}
    return sorted({*base, *_EXTRA}, key=lambda x: -len(x))
MARGINE_MIN, ROI_MIN, QUOTA_MEDIANA = 50.0, 100.0, 0.6
_RE_MODELLO = re.compile(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]{2,12}\b")


def campi(riga):
    """{chiave: valore} dai campi 'k=v' separati da ' | '. Il titolo (ultimo campo) puo' contenere barre: si prende fino a fine riga. Pura."""
    out = {}
    testa, _sep, titolo = riga.partition(" | titolo=")
    for parte in testa.split(" | ")[3:]:
        k, sep, v = parte.partition("=")
        if sep and k.strip().isidentifier():
            out.setdefault(k.strip(), v.strip())
    if _sep:
        out["titolo"] = titolo.strip()
    return out


def _num(x):
    try:
        return float(str(x).replace("'", "").strip())
    except ValueError:
        return None


def leggi(righe):
    """{item: dict} unendo OMBRA e TRACCIATO_RADAR. Pura."""
    dati = defaultdict(dict)
    for r in righe:
        if "RADAR V2 OMBRA" in r:
            c = campi(r)
            if c.get("item"):
                dati[c["item"]].update(ombra=True, prezzo=_num(c.get("prezzo")), rivendita=_num(c.get("rivendita")), margine=_num(c.get("margine")),
                                       roi=_num(c.get("roi")), semaforo=c.get("semaforo"), ricerca=c.get("ricerca", "-"), titolo=c.get("titolo", ""))
        elif "TRACCIATO_RADAR" in r:
            c = campi(r)
            if c.get("item"):
                s = c.get("venduto_s", "-")
                p = c.get("prenotato_s", "-")
                dati[c["item"]].update(brand=(c.get("brand") or "n/d").strip("'").lower(), venduto_s=int(s) if s.isdigit() else None,
                                       prenotato_s=int(p) if p.isdigit() else None, traccia=True, ricerca_t=c.get("ricerca"))
    return {k: v for k, v in dati.items() if v.get("ombra")}


def marca(d):
    """Marca: dal tracciamento se c'e' (e non e' n/d), altrimenti la prima marca nota trovata nel titolo. Pura."""
    if d.get("brand") and d["brand"] != "n/d":
        return d["brand"]
    t = f" {(d.get('titolo') or '').lower()} "
    return next((m for m in _marche() if f" {m} " in t or f" {m}" in t), "n/d")


def identita(d):
    """(marca, modello): modello = primo token con lettere e cifre del titolo ('-' se manca: mai raggruppato). Pura."""
    m = _RE_MODELLO.search((d.get("titolo") or "").lower())
    return marca(d), m.group(0) if m else "-"


def marca_anomalie(dati, min_n=3):
    """Aggiunge a ogni annuncio `anomalia` (True/False). Pura."""
    prezzi = defaultdict(list)
    for d in dati.values():
        if d.get("prezzo") and identita(d)[1] != "-":
            prezzi[identita(d)].append(d["prezzo"])
    for d in dati.values():
        vera = (d.get("margine") or 0) >= MARGINE_MIN and (d.get("roi") or 0) >= ROI_MIN
        gruppo = prezzi.get(identita(d), [])
        fuori = len(gruppo) >= min_n and d.get("prezzo") and d["prezzo"] <= QUOTA_MEDIANA * statistics.median(gruppo)
        d["anomalia"] = bool(vera or fuori)
    return dati


def tabella(dati, chiave, min_n=1):
    """[(gruppo, n, anomalie, con_esito, veloci)] ordinate per anomalie vendute in fretta. Pura."""
    g = defaultdict(lambda: [0, 0, 0, 0])
    for d in dati.values():
        k = chiave(d)
        r = g[k]
        r[0] += 1
        if d.get("anomalia"):
            r[1] += 1
            if d.get("traccia"):
                r[2] += 1
                # domanda provata = venduto o prenotato (acquirente gia' pagato) entro 1 h
                if any(x is not None and x <= ENTRO_S for x in (d.get("venduto_s"), d.get("prenotato_s"))):
                    r[3] += 1
    out = [(k, *v) for k, v in g.items() if v[0] >= min_n]
    return sorted(out, key=lambda x: (-x[4], -x[3], -x[2], -x[1], str(x[0])))


def stampa(titolo, righe, limite=15):
    print(f"\n{titolo}\n{'gruppo':<34}{'n':>5}{'anom':>6}{'tracc':>7}{'veloci':>8}")
    for k, n, a, t, v in righe[:limite]:
        print(f"{str(k)[:33]:<34}{n:>5}{a:>6}{t:>7}{v:>8}")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    min_n = int(argv[argv.index("--min") + 1]) if "--min" in argv else 3
    with open(argv[1], encoding="utf-8", errors="replace") as f:
        dati = marca_anomalie(leggi(f))
    print(f"{len(dati)} annunci valutati, {sum(1 for d in dati.values() if d.get('anomalia'))} con anomalia, "
          f"{sum(1 for d in dati.values() if d.get('traccia'))} con esito di vendita (campione parziale, n piccoli = indicativo)")
    stampa("Per ricerca", tabella(dati, lambda d: d.get("ricerca") or "-"))
    stampa("Per marca (dal tracciamento o dal titolo)", tabella(dati, marca))
    stampa(f"Per prodotto (marca + sigla), almeno {min_n} annunci", tabella(dati, identita, min_n=min_n))
    cand = [r for r in tabella(dati, identita, min_n=1) if r[4] >= 1 and r[0][0] != "n/d"]
    stampa("Candidati a nuova ricerca (anomalie con domanda provata (venduto o prenotato entro 1 h))", cand, limite=10)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
