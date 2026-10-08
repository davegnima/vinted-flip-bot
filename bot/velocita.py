"""Semaforo corretto dalla velocita' di vendita del brand (8/10, richiesta dell'utente: il semaforo deve avvicinarsi
alla velocita' di vendita e, col tempo, sostituire Occhio e Cervello).

Idea: la stima rapida di fair value da' un semaforo (🟢/🟡/🔴) che conosce il prezzo e il valore del capo ma non la
domanda. La tabella `bot/dati/velocita.json` (aggiornata ogni mattina da `tools/aggiorna_velocita.py` con le vendite
tracciate) dice, per brand, quanti annunci sono stati venduti entro 15 minuti. Il tasso del brand (ristretto verso la
media con peso VELOCITA_K, per non fidarsi di pochi casi) diventa un "lift" che moltiplica il tasso storico del
semaforo: Loro Piana e Prada salgono, Max Mara, Fendi, Cucinelli e Courreges scendono. Provato a ritroso su 263
annunci con la regola "leave one out" (il brand dell'annuncio escluso dal proprio calcolo): 🟢 passa dal 50% al 66% di
vendite veloci, i veloci persi nel 🔴 da 21 a 11. Pura, nessuna rete."""
import json
import os

_AQUI = os.path.dirname(os.path.abspath(__file__))
VELOCITA_FILE = os.environ.get("VELOCITA_FILE", os.path.join(_AQUI, "dati", "velocita.json"))
VELOCITA_ATTIVA = os.environ.get("VELOCITA_ATTIVA", "1").strip() == "1"
VELOCITA_K = float(os.environ.get("VELOCITA_K", "10"))                    # peso della media nel tasso del brand
VELOCITA_SOGLIA_VERDE = float(os.environ.get("VELOCITA_SOGLIA_VERDE", "0.40"))
VELOCITA_SOGLIA_GIALLO = float(os.environ.get("VELOCITA_SOGLIA_GIALLO", "0.20"))
_VUOTO = {"base": 0.25, "semaforo": {"🟢": 0.50, "🟡": 0.29, "🔴": 0.14}, "brand": {}}


def carica_velocita(percorso=None):
    """Tabella dal file JSON; se manca o e' rotta, una tabella vuota (nessuna correzione)."""
    try:
        with open(percorso or VELOCITA_FILE, encoding="utf-8") as f:
            d = json.load(f)
        base = float(d.get("base") or _VUOTO["base"])
        sem = {k: float(v["veloci"]) / v["n"] if isinstance(v, dict) and v.get("n") else float(v)
               for k, v in (d.get("semaforo") or {}).items()}
        brand = {str(k).lower(): (float(v["n"]), float(v["veloci"])) for k, v in (d.get("brand") or {}).items()}
        return {"base": base, "semaforo": {**_VUOTO["semaforo"], **sem}, "brand": brand}
    except Exception:
        return {"base": _VUOTO["base"], "semaforo": dict(_VUOTO["semaforo"]), "brand": {}}


_DATI = carica_velocita()


def lift_brand(brand, dati=None):
    """Rapporto tra il tasso di vendite veloci del brand (ristretto verso la media) e la media. 1 = brand sconosciuto."""
    dati = dati or _DATI
    n, veloci = dati["brand"].get(str(brand or "").lower(), (0.0, 0.0))
    base = dati["base"]
    return ((veloci + VELOCITA_K * base) / (n + VELOCITA_K)) / base if base > 0 else 1.0


def semaforo_corretto(semaforo, brand, dati=None):
    """(semaforo corretto, lift). Senza semaforo, con la correzione spenta o con il semaforo sconosciuto non cambia nulla."""
    dati = dati or _DATI
    if not VELOCITA_ATTIVA or semaforo not in dati["semaforo"]:
        return semaforo, 1.0
    lift = lift_brand(brand, dati)
    punteggio = dati["semaforo"][semaforo] * lift
    nuovo = "🟢" if punteggio >= VELOCITA_SOGLIA_VERDE else "🟡" if punteggio >= VELOCITA_SOGLIA_GIALLO else "🔴"
    return nuovo, round(lift, 2)
