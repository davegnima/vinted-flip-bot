"""Ricerche "a famiglia" del radar v2 (8/11, richiesta utente): una sola ricerca larga (brand + categoria) al posto di
tante ricerche per modello; il codice riconosce il modello dal titolo e applica il suo prezzo massimo prima di ogni
richiesta a Vinted. Titolo fuori lista o prezzo sopra il tetto del modello = annuncio scartato, zero banda.
I tetti sono quelli delle ricerche per modello che sostituiscono (decisione dell'utente), non nuovi dati misurati."""
import re
import unicodedata

# nome ricerca sul tracker -> modelli: (nome, chiavi alternative [ognuna: parole tutte presenti], tetto EUR)
FAMIGLIE = {
    "V2 console": [
        ("ps5", [("ps5",), ("playstation", "5")], 150),
        ("ps4 pro", [("ps4", "pro"), ("playstation", "4", "pro")], 60),
        ("switch", [("switch",)], 90),
        ("3ds", [("3ds",)], 60),
    ],
}
# Parole che indicano accessori o giochi: la console non e' l'oggetto in vendita.
ESCLUSE = frozenset("gioco giochi game controller joycon dualsense custodia cover pellicola dock cavo caricatore borsa "
                    "tracolla volante stand supporto cuffie".split())


def _parole(testo):
    t = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode().lower().replace("joy-con", "joycon")
    return frozenset(re.sub(r"[^\w]+", " ", t).split())


def modello_famiglia(nome_ricerca, titolo):
    """(nome modello, tetto) se la ricerca e' a famiglia e il titolo cita un modello della lista, ("", None) se la
    ricerca non e' a famiglia, (None, None) se e' a famiglia ma il titolo non cita nessun modello. Pura."""
    modelli = FAMIGLIE.get(nome_ricerca or "")
    if not modelli:
        return "", None
    p = _parole(titolo)
    if p & ESCLUSE:
        return None, None
    for nome, chiavi, tetto in modelli:
        if any(set(k) <= p for k in chiavi):
            return nome, tetto
    return None, None
