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
# Soglie PROPORZIONALI alla velocita' media della tabella (9/10): verde da 1,6 volte la media, giallo da 0,8 volte (con la media
# di allora, 0,25, erano 0,40 e 0,20). Con soglie fisse l'aggiornamento della tabella dell'8/10 (media scesa da 0,25 a 0,19) faceva
# scendere a giallo anche un Cucinelli a 12 EUR con fair value 67 EUR. VELOCITA_SOGLIA_VERDE/GIALLO (assolute) restano come forzatura.
VELOCITA_VERDE_X = float(os.environ.get("VELOCITA_VERDE_X", "1.6"))
VELOCITA_GIALLO_X = float(os.environ.get("VELOCITA_GIALLO_X", "0.8"))
VELOCITA_SOGLIA_VERDE = float(os.environ.get("VELOCITA_SOGLIA_VERDE") or 0)     # 0 = proporzionale alla media
VELOCITA_SOGLIA_GIALLO = float(os.environ.get("VELOCITA_SOGLIA_GIALLO") or 0)
# Brand "lento" (9/10): con almeno VELOCITA_LENTO_N_MIN annunci e un lift <= VELOCITA_LENTO_LIFT il rosso salta il Cervello anche
# a margine rapido positivo (vedi fair_value.check_skip_rosso). Oggi solo Max Mara (n ~155, lift 0,51).
VELOCITA_LENTO_N_MIN = float(os.environ.get("VELOCITA_LENTO_N_MIN", "100"))
VELOCITA_LENTO_LIFT = float(os.environ.get("VELOCITA_LENTO_LIFT", "0.60"))
# Capi economici (15/10): sotto VELOCITA_PREZZO_NEUTRO il lift di un brand lento (< 1) non si applica. Il lift viene quasi tutto da
# annunci a 40-70 EUR; a <= 20 EUR (8-14/10, 297 annunci di brand con lift < 0,8) il semaforo d'origine distingue meglio: 🟢 27% venduti
# entro 15 min e 🟡 11%, contro 🟢 20% e 🟡 26% col semaforo corretto. Es. Acne a 12 EUR con fair value 62: era sempre 🔴 (lift 0,36),
# mentre l'Acne a <= 20 EUR vendeva in fretta 4 volte su 13. Il lift > 1 (brand veloci) vale a ogni prezzo. 0 = spento.
# 25/10: tra verde e giallo la correzione sbaglia verso (dati 18-24/10, n=69: i 🟡 promossi a 🟢 sono veloci veri nel 23% dei casi, i 🟢
# retrocessi a 🟡 nel 52%; i 🟢 restati tali 38%, i 🟡 restati tali 32%). Con VELOCITA_SOLO_ROSSO=1 il lift sposta solo da/verso il 🔴.
VELOCITA_SOLO_ROSSO = os.environ.get("VELOCITA_SOLO_ROSSO", "1").strip() == "1"
VELOCITA_PREZZO_NEUTRO = float(os.environ.get("VELOCITA_PREZZO_NEUTRO", "20"))
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


def brand_lento(brand, dati=None):
    """True se il brand ha abbastanza annunci (VELOCITA_LENTO_N_MIN) e un lift basso (VELOCITA_LENTO_LIFT). Pura."""
    dati = dati or _DATI
    n, _ = dati["brand"].get(str(brand or "").lower(), (0.0, 0.0))
    return VELOCITA_ATTIVA and n >= VELOCITA_LENTO_N_MIN and lift_brand(brand, dati) <= VELOCITA_LENTO_LIFT


def semaforo_corretto(semaforo, brand, dati=None, prezzo=None):
    """(semaforo corretto, lift). Senza semaforo, con la correzione spenta o con il semaforo sconosciuto non cambia nulla.
    Con prezzo <= VELOCITA_PREZZO_NEUTRO un lift sotto 1 non abbassa il semaforo (vedi sopra)."""
    dati = dati or _DATI
    if not VELOCITA_ATTIVA or semaforo not in dati["semaforo"]:
        return semaforo, 1.0
    lift = lift_brand(brand, dati)
    if lift < 1 and prezzo is not None and 0 < prezzo <= VELOCITA_PREZZO_NEUTRO:
        lift = 1.0
    punteggio = dati["semaforo"][semaforo] * lift
    verde = VELOCITA_SOGLIA_VERDE or VELOCITA_VERDE_X * dati["base"]
    giallo = VELOCITA_SOGLIA_GIALLO or VELOCITA_GIALLO_X * dati["base"]
    nuovo = "🟢" if punteggio >= verde else "🟡" if punteggio >= giallo else "🔴"
    if VELOCITA_SOLO_ROSSO and nuovo != "🔴" and semaforo != "🔴":
        nuovo = semaforo
    return nuovo, round(lift, 2)
