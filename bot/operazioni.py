"""Acquisti e rivendite reali registrati dall'utente (01/11, tappa 5, livelli 2-3). Modulo puro: parsing dei comandi Telegram
`/comprato` e `/rivenduto` e calcolo del margine reale. Nessun numero e' stimato: se manca un dato, il campo resta vuoto."""
import re

_RE_ITEM = re.compile(r"(?:items/)?(\d{6,})")
_RE_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")


def _num(t):
    return float(t.replace(",", ".")) if _RE_NUM.match(t) else None


def parse_operazione(testo):
    """'/comprato <item|url> <prezzo> [costi]' o '/rivenduto <item|url> <prezzo> [giorni]'
    -> {"tipo", "item", "prezzo", "extra"} oppure None se non valido. Pura."""
    parti = (testo or "").strip().split()
    if len(parti) < 3:
        return None
    tipo = {"/comprato": "acquisto", "/rivenduto": "rivendita"}.get(parti[0].lower())
    m = _RE_ITEM.search(parti[1])
    prezzo = _num(parti[2])
    if not tipo or not m or prezzo is None or prezzo < 0:
        return None
    extra = _num(parti[3]) if len(parti) > 3 else None
    return {"tipo": tipo, "item": m.group(1), "prezzo": prezzo, "extra": extra}


def margine_reale(acquisto, costi, rivendita):
    """(margine, roi_percentuale) con costo = acquisto + costi (spedizione, protezione). ROI None se il costo e' 0. Pura."""
    costo = (acquisto or 0.0) + (costi or 0.0)
    margine = round((rivendita or 0.0) - costo, 2)
    return margine, (round(100 * margine / costo, 1) if costo > 0 else None)
