"""Ricerche "a famiglia" del radar v2 (8/11, richiesta utente): una sola ricerca larga (brand + categoria) al posto di
tante ricerche per modello; il codice riconosce il modello dal titolo e applica il suo prezzo massimo prima di ogni
richiesta a Vinted. Titolo fuori lista o prezzo sopra il tetto del modello = annuncio scartato, zero banda.
I tetti sono quelli delle ricerche per modello che sostituiscono (decisione dell'utente), non nuovi dati misurati."""
import os
import re
import time
import unicodedata
from collections import deque

# nome ricerca sul tracker -> modelli: (nome, chiavi alternative [ognuna: parole tutte presenti], tetto EUR)
FAMIGLIE = {
    "V2 console": [
        ("ps5", [("ps5",), ("playstation", "5")], 150),
        ("ps4 pro", [("ps4", "pro"), ("playstation", "4", "pro")], 60),
        ("switch", [("switch",)], 90),
        ("3ds", [("3ds",)], 60),
        # 13/11: ps4, ps vita e wii u a 80 EUR (non piu' 50): nelle console (ps5, switch, 3ds, ps4 pro, 5 giorni) la fascia 50-100 EUR
        # da' 32 affari su 70 gialli/verdi (46%) contro 25 su 88 nella fascia 25-50 e 9 su 46 sotto 25; il tetto 50 le tagliava.
        # Il tetto orario `consenti_nuova` non cambia: nessuna richiesta in piu'. game boy, psp, ds restano a 50 (rivendita bassa).
        # 11/11 (richiesta utente: piu' affari fuori moda): modelli che prima finivano in "fuori_famiglia" (circa 150 annunci/ora
        # scartati senza valutazione). Tetto 50 EUR = regola 10 per i modelli senza buy max misurato. Hanno un tetto orario di
        # valutazioni (`consenti_nuova`) per non gonfiare le richieste a Vinted; i tetti veri si fissano sui dati di 24 ore.
        ("ps4", [("ps4",), ("playstation", "4")], 80),
        ("ps vita", [("ps", "vita"), ("playstation", "vita"), ("psvita",)], 80),
        ("wii u", [("wii", "u"), ("wiiu",)], 80),
        ("game boy", [("gameboy",), ("gba",), ("gbc",)], 50),
        ("psp", [("psp",)], 50),
        ("ds", [("nintendo", "ds"), ("ds", "lite"), ("dsi",), ("2ds",)], 50),
        ("retro nintendo", [("snes",), ("super", "nintendo"), ("n64",), ("gamecube",)], 50),
    ],
}
# Modelli nuovi (11/11) soggetti al tetto orario di valutazioni.
NUOVI = frozenset({"ps4", "ps vita", "wii u", "game boy", "psp", "ds", "retro nintendo"})
NUOVI_MAX_ORA = int(os.environ.get("RADAR_FAMIGLIE_NUOVE_ORA", "40"))
_recenti = deque()
# Parole che indicano accessori o giochi: la console non e' l'oggetto in vendita.
ESCLUSE = frozenset("gioco giochi game controller joycon dualsense custodia cover pellicola dock cavo caricatore borsa "
                    "tracolla volante stand supporto cuffie".split())


def _parole(testo):
    t = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode().lower().replace("joy-con", "joycon").replace("game boy", "gameboy")
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


def consenti_nuova(nome, ora=None):
    """True se il modello non e' tra i nuovi o c'e' ancora posto nel tetto orario (RADAR_FAMIGLIE_NUOVE_ORA, 0 = nessun tetto).
    Conta solo le valutazioni concesse: protegge la banda e il rischio blocco di Vinted. Pura a parte lo stato dei recenti."""
    if nome not in NUOVI or NUOVI_MAX_ORA <= 0:
        return True
    t = time.time() if ora is None else ora
    while _recenti and _recenti[0] < t - 3600:
        _recenti.popleft()
    if len(_recenti) >= NUOVI_MAX_ORA:
        return False
    _recenti.append(t)
    return True
