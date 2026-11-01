"""Qualita' dei comparabili e identita' del prodotto (01/11, tappa 3). Moduli puri.

Punteggio 0-100 dai soli dati che il radar ha davvero: numero di comparabili, quota "stesso modello" giudicata da Jev,
dispersione dei prezzi (p75/p25), duplicati (stesso titolo e stesso prezzo). Venditori distinti, anzianita' degli annunci e
coerenza delle condizioni NON sono nel catalogo che scarichiamo: non pesano e il punteggio lo dichiara (`non_valutati`).
Per ora solo misura (log e messaggio): nessuna soglia blocca finche' non e' tarata sui casi tracciati.
"""
import re
import statistics

NON_VALUTATI = ("venditori_distinti", "anzianita", "condizioni")


def fascia_numero(n):
    """Fascia di affidabilita' per numero di comparabili: 0-2 insufficiente, 3-4 bassa, 5-7 media, 8-14 buona, 15+ alta."""
    if n <= 2:
        return "insufficiente"
    if n <= 4:
        return "bassa"
    if n <= 7:
        return "media"
    return "buona" if n <= 14 else "alta"


def _norm(t):
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def punteggio_comparabili(coppie, n_stesso=None, n_giudicati=None):
    """{punteggio 0-100, fascia, n, duplicati, dispersione, quota_stesso, non_valutati}. `coppie` = [(titolo, prezzo)].
    Pesi: numero 40, quota stesso modello 30 (se giudicata, altrimenti i 30 si ridistribuiscono), dispersione 20, duplicati 10. Pura."""
    prezzi = sorted(p for _, p in coppie if p and p > 0)
    n = len(prezzi)
    if n == 0:
        return {"punteggio": 0, "fascia": "insufficiente", "n": 0, "duplicati": 0, "dispersione": None, "quota_stesso": None,
                "non_valutati": list(NON_VALUTATI)}
    visti, dup = set(), 0
    for t, p in coppie:
        k = (_norm(t), round(p, 2))
        dup += k in visti
        visti.add(k)
    if n >= 4:
        q = statistics.quantiles(prezzi, n=4, method="inclusive")
        disp = round(q[2] / q[0], 2) if q[0] > 0 else None
    else:
        disp = None
    pt_numero = 40 * min(n, 15) / 15
    pt_disp = 0 if disp is None else 20 * max(0.0, min(1.0, (2.5 - disp) / 1.5))  # 1,0 -> 20 ; 2,5 o piu' -> 0
    pt_dup = 10 * (1 - dup / n)
    quota = (n_stesso / n_giudicati) if n_giudicati else None
    pt_quota = 30 * quota if quota is not None else 0
    tot = pt_numero + pt_disp + pt_dup + pt_quota
    if quota is None:
        tot = tot / 70 * 100  # senza giudizio di Jev si riporta a 100 sui pesi disponibili
    return {"punteggio": round(tot), "fascia": fascia_numero(n), "n": n, "duplicati": dup, "dispersione": disp,
            "quota_stesso": None if quota is None else round(quota, 2), "non_valutati": list(NON_VALUTATI)}


_RE_SIGLA = re.compile(r"\b(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9-]{3,}\b", re.IGNORECASE)


def product_identity(titolo, brand=None, catalogo=None, nome=None):
    """{brand, nome, codice_modello, categoria}: solo quello che si sa davvero (None il resto). Il codice modello e' la prova
    piu' forte per confrontare i comparabili. Variante, completezza e condizione richiedono una lettura di Jev: non qui. Pura."""
    m = _RE_SIGLA.search(titolo or "")
    return {"brand": brand, "nome": nome, "codice_modello": m.group(0).lower() if m else None, "categoria": catalogo}


_FRASI_GUASTO = ("non funziona", "non funzionante", "non funzionano", "per ricambi", "per pezzi di ricambio", "pezzi di ricambio",
                 "da riparare", "bloccat", "icloud", "rotto", "rotta", "difettos", "non si accende", "non si avvia")


def guasto_nella_descrizione(descrizione):
    """Frase che dichiara l'oggetto rotto/bloccato/per ricambi nella descrizione, o None. Controllo gratuito prima di Jev. Pura."""
    d = (descrizione or "").lower()
    return next((f for f in _FRASI_GUASTO if f in d), None)
