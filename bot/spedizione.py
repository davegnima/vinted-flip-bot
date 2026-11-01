"""Costo di spedizione verso l'Italia per il radar (01/11, richiesta dell'utente: Shipping Cost Intelligence).

Regola: un costo mai misurato non si inventa. Tre stati:
- VERIFIED: costo letto dalla pagina dell'annuncio (oggi nessun campo noto: si arriva qui solo con `letto`).
- ESTIMATED: cella della tabella paese x taglia (semi dati dall'utente, da tarare con i costi VERIFIED osservati).
- UNKNOWN: paese non letto o cella vuota. Il costo usato nel calcolo e' quello di base, ma il semaforo non supera il giallo.
Modulo puro: nessun import dal resto del bot oltre alla configurazione.
"""
import json
import os
import re

from bot.config import SPEDIZIONE_STIMATA_EUR

VERIFIED, ESTIMATED, UNKNOWN = "VERIFIED", "ESTIMATED", "UNKNOWN"

# Semi dell'utente (01/11): "piccolo e leggero Francia 5 EUR, pesante e ingombrante 20 EUR"; Italia piccolo = tariffa gia' in uso.
# Le celle non elencate sono UNKNOWN finche' non ci sono costi letti dalla pagina. Si puo' sovrascrivere con la variabile
# SPEDIZIONE_TARIFFE (JSON {"francia": {"medio": 9}}), senza toccare il codice.
_TARIFFE_BASE = {
    "italia": {"piccolo": SPEDIZIONE_STIMATA_EUR, "ingombrante": 20.0},
    "francia": {"piccolo": 5.0, "ingombrante": 20.0},
}


def _tariffe():
    tab = {p: dict(c) for p, c in _TARIFFE_BASE.items()}
    grezzo = os.environ.get("SPEDIZIONE_TARIFFE", "").strip()
    if grezzo:
        try:
            for paese, celle in json.loads(grezzo).items():
                for classe, eur in celle.items():
                    tab.setdefault(paese.strip().lower(), {})[classe.strip().lower()] = float(eur)
        except (ValueError, AttributeError, TypeError):
            pass  # variabile malformata: restano i semi
    return tab


_INGOMBRANTE = ("aspirapolvere", "lavatrice", "lavastoviglie", "frigorifero", "forno", "televisore", " tv ", "monitor", "bicicletta",
                " bici ", "passeggino", "seggiolone", "seggiolino", "mobile", "tavolo", "sedia", "divano", "materasso", "casse",
                "subwoofer", "amplificatore", "stereo", "tosaerba", "monopattino", "cyclone", "robot da cucina", "impastatrice", "kitchenaid")
_PICCOLO = ("gioco", "giochi", "cartuccia", "game boy", "gameboy", "cuffie", "auricolari", "airpods", "smartwatch", "gopro", "pin ",
            "cucchiaino", "posate", "portachiavi", "joystick", "controller", "pad ", "telecomando", "caricabatterie", "memory card", "sd card")


def classe_taglia(titolo):
    """'piccolo' | 'ingombrante' | 'medio' dal titolo. Senza parole note e' 'medio' (cella spesso UNKNOWN: dichiarato). Pura."""
    t = f" {(titolo or '').lower()} "
    if any(p in t for p in _INGOMBRANTE):
        return "ingombrante"
    if any(p in t for p in _PICCOLO):
        return "piccolo"
    return "medio"


def costo_spedizione(paese, classe, letto=None):
    """(eur, stato). `letto` = costo letto dalla pagina (VERIFIED). Con UNKNOWN eur e' il costo di base (SPEDIZIONE_STIMATA_EUR),
    usato nel calcolo ma con semaforo al massimo giallo. Pura."""
    if letto is not None and letto >= 0:
        return round(float(letto), 2), VERIFIED
    eur = _tariffe().get((paese or "").strip().lower(), {}).get((classe or "").strip().lower())
    if eur is None:
        return SPEDIZIONE_STIMATA_EUR, UNKNOWN
    return float(eur), ESTIMATED


_RE_PAESE = re.compile(r'"country_title_local"\s*:\s*"([^"]{2,30})"')
_RE_CHIAVI_SPED = re.compile(r'"([a-z_]*(?:shipping|delivery)[a-z_]*)"\s*:\s*("[^"]{0,30}"|[\d.]{1,10}|true|false|null)', re.IGNORECASE)


def paese_da_html(html):
    """Paese del venditore dalla pagina annuncio, o None. Pura."""
    m = _RE_PAESE.search(html or "")
    return m.group(1).strip() if m else None


def campi_spedizione_da_html(html, massimo=8):
    """[(chiave, valore)] dei campi della pagina con 'shipping' o 'delivery' nel nome: solo MISURA (log `SPEDIZIONE PAGINA`) per
    vedere cosa espone davvero Vinted; nessun nome di campo e' assunto come costo. Pura."""
    visti, out = set(), []
    for chiave, valore in _RE_CHIAVI_SPED.findall(html or ""):
        if chiave not in visti:
            visti.add(chiave)
            out.append((chiave, valore.strip('"')))
        if len(out) >= massimo:
            break
    return out
