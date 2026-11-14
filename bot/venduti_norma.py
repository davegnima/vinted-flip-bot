"""Normalizzazione dei venduti (fase 1 del piano 'archivio venduti moda', 14/11). Logica pura, nessuna rete.

Porta una riga grezza di qualunque fonte (Vinted tracciato, Vestiaire, eBay, file salvati a mano) allo stesso formato:
brand, categoria (le stesse di `CATEGORIA_KEYWORDS` del bot), tipo, condizione (le 5 di Vinted), prezzo in EUR.
Niente AI: solo dizionari e regole. Quello che non si riconosce resta None, mai inventato (regola 16).
"""
import re
import unicodedata

from bot.categorie import estrai_categoria_da_titolo
from bot.fair_value_tabelle import FAIR_VALUE_BRAND
from bot.valore_mercato import solo_usato
# ---- fine import ----

# Cambi APPROSSIMATI (14/11), solo per mettere in ordine di grandezza prezzi in valute diverse: non sono un dato di
# mercato misurato. Valuta sconosciuta -> None (la riga non entra nei calcoli).
CAMBIO_EUR = {"EUR": 1.0, "USD": 0.88, "GBP": 1.17, "CHF": 1.05, "SEK": 0.087, "DKK": 0.134, "PLN": 0.23}

CONDIZIONI = ("nuovo con cartellino", "nuovo senza cartellino", "ottime condizioni", "buone condizioni",
              "condizioni soddisfacenti")
# (parola chiave nel testo della fonte, condizione Vinted); il primo match vince, dal piu' specifico.
_CONDIZIONE_PAROLE = (
    ("never worn, with tag", "nuovo con cartellino"), ("new with tag", "nuovo con cartellino"),
    ("with tags", "nuovo con cartellino"), ("nwt", "nuovo con cartellino"), ("con cartellino", "nuovo con cartellino"),
    ("avec etiquette", "nuovo con cartellino"), ("neuf avec", "nuovo con cartellino"),
    ("never worn", "nuovo senza cartellino"), ("new without", "nuovo senza cartellino"),
    ("senza cartellino", "nuovo senza cartellino"), ("jamais port", "nuovo senza cartellino"),
    ("mai indossat", "nuovo senza cartellino"), ("neuf", "nuovo senza cartellino"), ("brand new", "nuovo senza cartellino"),
    ("excellent", "ottime condizioni"), ("ottim", "ottime condizioni"), ("tres bon", "ottime condizioni"),
    ("very good", "ottime condizioni"), ("like new", "ottime condizioni"), ("eccellent", "ottime condizioni"),
    ("fair", "condizioni soddisfacenti"), ("soddisf", "condizioni soddisfacenti"), ("acceptable", "condizioni soddisfacenti"),
    ("used", "condizioni soddisfacenti"), ("satisfactory", "condizioni soddisfacenti"),
    ("good", "buone condizioni"), ("buon", "buone condizioni"), ("bon etat", "buone condizioni"),
    ("pre-owned", "buone condizioni"),
)
# Esclusi per scelta dell'utente o perche' non sono la linea principale (stesso criterio di `_brand_fair_value`).
_RE_LINEE_ESCLUSE = re.compile(r"\bmm6\b|\by-?3\b|see by chlo")
_BRAND_ESCLUSI = {"celine"}


def _senza_accenti(testo):
    return "".join(c for c in unicodedata.normalize("NFD", testo or "") if unicodedata.category(c) != "Mn")


def _pulisci(testo):
    return " ".join(_senza_accenti(testo).lower().replace("_", " ").split())


def normalizza_brand(brand_raw, titolo=""):
    """Nome canonico del brand (le chiavi di FAIR_VALUE_BRAND se c'e' un alias, altrimenti il testo pulito).
    None se manca, se e' una linea esclusa (MM6, Y-3) o un brand escluso (Celine)."""
    brand = _pulisci(brand_raw)
    t = _pulisci(titolo)
    if _RE_LINEE_ESCLUSE.search(f"{brand} {t}"):
        return None
    if not brand or brand in ("?", "n/a", "none", "unknown") or len(brand) > 40:
        return None
    for nome, alias in FAIR_VALUE_BRAND.items():
        if any(_senza_accenti(a).lower() in brand for a in alias):
            brand = nome
            break
    return None if brand in _BRAND_ESCLUSI else brand


def categoria_da_titolo(titolo, descrizione=None):
    """Categoria nel linguaggio del bot (abito, giacca, borsa...); None se il titolo non la dice. Se le parole del bot
    non bastano (blazer, bomber, trench non sono in CATEGORIA_KEYWORDS) si usa la categoria della tabella TIPI."""
    cat = estrai_categoria_da_titolo(titolo or "", descrizione)
    if cat:
        return cat
    for c, _tipo, rx in _TIPI_RE:
        if rx.search(titolo or ""):
            return c
    return None


# Tipo di prodotto: piu' fine della categoria. (categoria del bot, tipo, regex nel titolo); il primo match vince.
TIPI = (
    ("giacca", "blazer", r"\b(blazer|giacca sartoriale|tailleur)\b"),
    ("giacca", "giubbotto", r"\b(giubbotto|bomber|biker|chiodo|parka|piumino|puffer|trucker|field jacket)\b"),
    ("giacca", "giacca", r"\b(giacca|jacket|veste|jacke)\b"),
    ("cappotto", "trench", r"\b(trench|impermeabile|raincoat)\b"),
    ("cappotto", "cappotto", r"\b(cappotto|coat|manteau|montgomery|cappa|giaccone)\b"),
    ("maglia", "cardigan", r"\b(cardigan|gilet in maglia)\b"),
    ("maglia", "maglione", r"\b(maglione|pullover|sweater|knit|dolcevita|girocollo|maglia)\b"),
    ("pantaloni", "pantaloni", r"\b(pantaloni|pants|trousers|pantalon|hose)\b"),
    ("jeans", "jeans", r"\b(jeans|denim)\b"),
    ("gonna", "gonna", r"\b(gonna|skirt|jupe|rock)\b"),
    ("abito", "abito", r"\b(abito|vestito|dress|robe|kleid)\b"),
    ("camicia", "camicia", r"\b(camicia|shirt|chemise|hemd)\b"),
    ("t-shirt", "t-shirt", r"\b(t-?shirt|maglietta)\b"),
    ("borsa", "borsa", r"\b(borsa|bag|tote|pochette|zaino|backpack|clutch|shopper|crossbody|sac)\b"),
    ("scarpe", "scarpe", r"\b(scarpe|sneakers|shoes|boots|stivali|sandali|mocassini|ballerine|loafers)\b"),
)
_TIPI_RE = tuple((c, t, re.compile(rx, re.I)) for c, t, rx in TIPI)


def tipo_da_titolo(titolo, categoria=None):
    """Tipo di prodotto dal titolo; se si passa la categoria, il tipo deve appartenere a quella categoria."""
    t = titolo or ""
    for cat, tipo, rx in _TIPI_RE:
        if categoria and cat != categoria:
            continue
        if rx.search(t):
            return tipo
    return None


def condizione_vinted(testo):
    """Una delle 5 condizioni di Vinted, o None se il testo non e' riconoscibile."""
    t = _pulisci(testo)
    if not t:
        return None
    for chiave, cond in _CONDIZIONE_PAROLE:
        if chiave in t:
            return cond
    return None


def a_eur(prezzo, valuta="EUR"):
    """Prezzo in EUR con cambio approssimato; None se il prezzo non e' un numero positivo o la valuta e' ignota."""
    try:
        p = float(prezzo)
    except (TypeError, ValueError):
        return None
    cambio = CAMBIO_EUR.get(str(valuta or "EUR").strip().upper())
    if p <= 0 or cambio is None:
        return None
    return round(p * cambio, 2)


def e_nuovo(titolo, condizione=None):
    """Vero se il pezzo e' dichiarato nuovo (cartellino, sigillato...): il suo prezzo gonfia la mediana dell'usato."""
    if condizione in ("nuovo con cartellino", "nuovo senza cartellino"):
        return True
    return not solo_usato([(titolo or "", 0)])


def riga_normalizzata(fonte, id_fonte, titolo, brand, prezzo, valuta="EUR", condizione=None, materiale=None, url=None,
                      paese=None, data_vendita=None, data_osservazione=None, certezza="osservata", modello=None,
                      categoria=None):
    """Riga nel formato dell'archivio, o None se manca brand, categoria o prezzo valido (non si inventano campi).
    `certezza`: 'confermata' (incasso reale o venduto Jev) oppure 'osservata' (annuncio sparito o venduto con prezzo
    richiesto)."""
    b = normalizza_brand(brand, titolo)
    cat = categoria or categoria_da_titolo(titolo)
    eur = a_eur(prezzo, valuta)
    if not b or not cat or eur is None or not id_fonte:
        return None
    cond = condizione_vinted(condizione)
    return {
        "fonte": fonte, "id_fonte": str(id_fonte), "url": url, "brand": b, "categoria": cat,
        "tipo": tipo_da_titolo(titolo, cat), "modello": modello, "condizione": cond, "materiale": materiale,
        "prezzo": float(prezzo), "valuta": str(valuta or "EUR").upper(), "prezzo_eur": eur, "paese": paese,
        "data_vendita": data_vendita, "data_osservazione": data_osservazione, "certezza": certezza,
        "titolo": (titolo or "")[:200], "nuovo": e_nuovo(titolo, cond),
    }
