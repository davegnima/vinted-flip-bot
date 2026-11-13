"""Condizioni dei comparabili Vinted (ids di stato per la ricerca, correzione del prezzo)."""
import os


# ---- fine import ----
# 11/11 (utente): i comparabili si cercano SEMPRE in nuovo senza cartellino, ottime e buone (ids 1, 2, 3), oltre a brand e categoria;
# se l'annuncio e' in un'altra condizione (6 nuovo con cartellino, 4 soddisfacenti) si aggiunge anche quella. Il prezzo dei comparabili
# in condizione diversa si corregge di poco (`aggiusta_prezzo_comp`). Ids Vinted: 6 nuovo con cartellino, 1 nuovo senza, 2 ottime,
# 3 buone, 4 soddisfacenti. Prima (10/11): solo la condizione dell'annuncio.
_STATI_PER_CONDIZIONE = (("con cartellino", 6), ("senza cartellino", 1), ("ottim", 2), ("buon", 3), ("soddisfacent", 4))
STATI_COMPS_BASE = (1, 2, 3)
# scala di valore in punti percentuali (piu' basso = migliore), cumulata dai gradini scelti dall'utente (11/11, STIME non misurate):
# nuovo con cartellino -> nuovo senza 5%, nuovo senza -> ottime 5%, ottime -> buone 10%, buone -> soddisfacenti 10%
_LIVELLO_STATO = {6: 0, 1: 5, 2: 10, 3: 20, 4: 30}
# moltiplicatore della scala (1 = i valori sopra, 0 = nessuna correzione)
COMPS_COND_SCALA = float(os.environ.get("COMPS_COND_SCALA", "1") or 0)


def stato_da_condizione(condizione):
    """Id Vinted della condizione scritta nell'annuncio ('Ottime', 'Nuovo senza cartellino'...). None se assente o non riconosciuta. Pura."""
    t = str(condizione or "").lower()
    return next((i for chiave, i in _STATI_PER_CONDIZIONE if chiave in t), None)


def stati_ricerca_comps(condizione=None):
    """Ids di condizione da cercare per i comparabili: 1, 2, 3 piu' quella dell'annuncio se e' un'altra. Pura."""
    proprio = stato_da_condizione(condizione)
    return STATI_COMPS_BASE + ((proprio,) if proprio is not None and proprio not in STATI_COMPS_BASE else ())


def stati_comps(condizione=None):
    """Parametri `&status_ids[]=N` per la ricerca dei comparabili, dalla condizione dell'annuncio. Pura."""
    return "".join(f"&status_ids[]={i}" for i in stati_ricerca_comps(condizione))


def aggiusta_prezzo_comp(prezzo, stato_comp, condizione_annuncio):
    """Prezzo del comparabile portato alla condizione dell'annuncio: comparabile peggiore -> il nostro vale di piu' (prezzo su),
    comparabile migliore -> prezzo giu', secondo la scala `_LIVELLO_STATO`. `stato_comp` e' l'id o la condizione scritta del comparabile.
    Senza condizione nota di uno dei due non cambia. Pura."""
    proprio = stato_da_condizione(condizione_annuncio)
    if isinstance(stato_comp, str):
        stato_comp = stato_da_condizione(stato_comp)
    if proprio is None or stato_comp not in _LIVELLO_STATO or COMPS_COND_SCALA <= 0:
        return prezzo
    return prezzo * max(0.5, 1 + COMPS_COND_SCALA * (_LIVELLO_STATO[stato_comp] - _LIVELLO_STATO[proprio]) / 100)


