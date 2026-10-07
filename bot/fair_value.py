"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import json
import time
import statistics
import traceback


from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot.config import _env_float
from bot.categorie import estrai_categoria_da_titolo, scegli_materiale_per_ricerca
from bot.logger import log
# ---- fine import ----
# ---------------------------------------------------------------------------
# FAIR VALUE A PRIORI (richiesto dall'utente il 2026-09-30)
# ---------------------------------------------------------------------------
# Stima IMMEDIATA (nessuna chiamata a Gemini ne' a Vinted) del valore di
# rivendita italiano di un capo, in base a brand + tipo di capo + condizione
# + materiale, per capire subito se a priori c'e' margine.
#
# Come e' stata costruita la tabella (30/09/2026):
#  - ~2.800 comp venduti puliti (Poshmark + eBay) dai log di produzione del
#    23-28/09, tenuti solo se il titolo contiene il brand, deduplicati, con
#    "nuovo con cartellino" esclusi dalla mediana (gonfiano il prezzo);
#  - categoria assegnata con le STESSE keyword del bot (CATEGORIA_KEYWORDS);
#  - i comp sono mercato USA: confrontati con gli incassi reali dell'utente
#    (foglio "Acquisti flip", 68 vendite) il rapporto reale/comp ha mediana
#    ~0.7 (da 0.3 a 1.0 secondo il brand), quindi tutti i comp sono scontati
#    del 30% (FAIR_VALUE_SCONTO_COMP);
#  - dove esistono vendite reali (col. nr) la stima e' 60% incasso reale +
#    40% comp scontati; confidenza "alta" con >=2 vendite reali, "media" con
#    1 vendita reale o >=15 comp, "bassa" altrimenti (solo indicativa: niente
#    semaforo, mai usata per filtrare).
# Formato: "brand|categoria": (minimo, fair value, massimo, confidenza, n_comp, n_vendite_reali)
FAIR_VALUE_TABELLA = {
    "ann demeulemeester|gonna": (55, 74, 108, "bassa", 13, 0),
    "brunello cucinelli|camicia": (44, 58, 81, "media", 26, 1),
    "brunello cucinelli|canotta": (28, 37, 48, "media", 38, 1),
    "brunello cucinelli|maglia": (44, 59, 99, "media", 49, 1),
    "brunello cucinelli|pantaloni": (31, 59, 74, "media", 41, 1),
    "brunello cucinelli|t-shirt": (30, 60, 102, "media", 8, 1),
    "courreges|abito": (48, 69, 86, "media", 11, 1),
    "courreges|pantaloni": (27, 35, 62, "bassa", 6, 0),
    "dries van noten|camicia": (29, 54, 78, "media", 20, 0),
    "dries van noten|maglia": (27, 44, 79, "media", 20, 0),
    "engineered garments|camicia": (32, 39, 49, "media", 22, 0),
    "engineered garments|giacca": (52, 61, 67, "media", 21, 0),
    "haider ackermann|gonna": (25, 46, 74, "media", 17, 0),
    "helmut lang|giacca": (25, 37, 61, "media", 57, 0),
    "helmut lang|jeans": (15, 18, 28, "bassa", 13, 0),
    "helmut lang|maglia": (15, 26, 33, "media", 34, 0),
    "issey miyake|canotta": (74, 77, 138, "bassa", 10, 0),
    "issey miyake|gilet": (68, 80, 111, "bassa", 11, 0),
    "jean paul gaultier|abito": (49, 67, 76, "bassa", 9, 0),
    "jean paul gaultier|camicia": (62, 80, 144, "bassa", 13, 0),
    "jean paul gaultier|canotta": (45, 60, 78, "media", 1, 1),
    "jean paul gaultier|felpa": (55, 77, 102, "bassa", 14, 0),
    "jean paul gaultier|giacca": (71, 123, 222, "media", 19, 0),
    "jean paul gaultier|jeans": (35, 67, 95, "media", 30, 0),
    "jean paul gaultier|maglia": (25, 33, 59, "media", 37, 1),
    "jean paul gaultier|pantaloni": (40, 62, 77, "media", 23, 0),
    "jean paul gaultier|t-shirt": (28, 38, 68, "alta", 33, 2),
    "jil sander|cappotto": (61, 95, 172, "media", 16, 0),
    "jil sander|giacca": (23, 40, 72, "media", 19, 0),
    "jil sander|gilet": (22, 42, 60, "bassa", 14, 0),
    "jil sander|maglia": (18, 30, 53, "media", 72, 0),
    "khaite|blusa": (32, 43, 60, "bassa", 14, 0),
    "lemaire|abito": (29, 36, 65, "bassa", 12, 0),
    "loewe|abito": (92, 133, 166, "media", 9, 1),
    "loewe|canotta": (63, 73, 115, "media", 34, 0),
    "loewe|maglia": (78, 123, 191, "media", 24, 0),
    "loewe|t-shirt": (31, 38, 69, "bassa", 12, 0),
    "loro piana|abito": (32, 38, 69, "bassa", 7, 0),
    "loro piana|camicia": (35, 55, 72, "bassa", 12, 0),
    "loro piana|giacca": (48, 64, 83, "media", 6, 1),
    "loro piana|maglia": (49, 83, 148, "media", 73, 0),
    "loro piana|pantaloni": (20, 31, 47, "media", 15, 0),
    "loro piana|t-shirt": (40, 71, 95, "media", 16, 0),
    "marni|abito": (22, 34, 47, "media", 16, 0),
    "marni|blusa": (23, 46, 57, "media", 46, 1),
    "marni|camicia": (15, 18, 19, "bassa", 8, 0),
    "marni|canotta": (12, 16, 22, "media", 32, 0),
    "marni|gonna": (14, 25, 37, "media", 25, 0),
    "marni|maglia": (31, 62, 111, "media", 35, 0),
    "marni|pantaloni": (21, 30, 47, "media", 42, 0),
    "max mara|cappotto": (73, 123, 221, "media", 12, 1),
    "max mara|giacca": (37, 62, 92, "media", 25, 0),
    "max mara|gilet": (34, 67, 92, "media", 17, 0),
    "missoni|abito": (25, 42, 52, "media", 104, 1),
    "missoni|blusa": (16, 23, 41, "media", 19, 0),
    "missoni|camicia": (19, 32, 40, "alta", 28, 3),
    "missoni|canotta": (15, 27, 34, "media", 85, 1),
    "missoni|felpa": (8, 12, 15, "bassa", 12, 0),
    "missoni|giacca": (23, 44, 62, "media", 43, 1),
    "missoni|gilet": (18, 25, 44, "media", 26, 0),
    "missoni|gonna": (18, 29, 39, "media", 91, 1),
    "missoni|jeans": (18, 28, 41, "media", 29, 0),
    "missoni|maglia": (18, 37, 46, "media", 151, 1),
    "missoni|polo": (22, 30, 39, "media", 0, 1),
    "missoni|t-shirt": (26, 35, 46, "media", 3, 1),
    "missoni|tuta": (34, 45, 58, "media", 0, 1),
    "miu miu|blusa": (16, 22, 29, "bassa", 10, 0),
    "miu miu|canotta": (48, 62, 111, "media", 60, 0),
    "miu miu|gilet": (34, 45, 58, "media", 2, 1),
    "miu miu|jeans": (49, 80, 144, "bassa", 10, 0),
    "miu miu|maglia": (51, 102, 183, "media", 51, 0),
    "miu miu|t-shirt": (55, 105, 188, "media", 32, 0),
    "mugler|camicia": (30, 40, 52, "alta", 0, 3),
    "mugler|giacca": (54, 108, 171, "media", 18, 0),
    "mugler|gonna": (9, 15, 23, "media", 17, 0),
    "our legacy|camicia": (30, 31, 37, "bassa", 8, 0),
    "our legacy|felpa": (23, 46, 65, "bassa", 12, 0),
    "pucci|canotta": (52, 69, 86, "media", 12, 1),
    "pucci|maglia": (43, 48, 78, "bassa", 6, 0),
    "pucci|pantaloni": (54, 72, 94, "alta", 0, 2),
    "pucci|t-shirt": (46, 67, 103, "media", 16, 0),
    "raf simons|camicia": (25, 45, 49, "bassa", 6, 0),
    "raf simons|maglia": (45, 91, 128, "media", 30, 0),
    "rick owens|abito": (63, 92, 162, "media", 25, 0),
    "rick owens|maglia": (64, 90, 124, "media", 16, 0),
    "totême|camicia": (41, 45, 53, "bassa", 6, 0),
    "undercover|t-shirt": (38, 48, 70, "bassa", 6, 0),
    "vivienne westwood|jeans": (33, 41, 51, "bassa", 13, 0),
    "vivienne westwood|pantaloni": (59, 93, 125, "media", 20, 0),
    "vivienne westwood|t-shirt": (21, 26, 44, "media", 20, 0),
    "zegna|giacca": (30, 60, 107, "media", 17, 0),
}

FAIR_VALUE_BRAND = {
    "missoni": ["missoni"], "miu miu": ["miu miu", "miumiu"], "marni": ["marni"],
    "brunello cucinelli": ["cucinelli"], "courreges": ["courrèges", "courreges"],
    "jean paul gaultier": ["gaultier", "jpg"], "jil sander": ["jil sander"],
    "raf simons": ["raf simons"], "vivienne westwood": ["westwood"],
    "helmut lang": ["helmut lang"], "max mara": ["max mara", "maxmara"],
    "engineered garments": ["engineered garments"], "loro piana": ["loro piana"],
    "rick owens": ["rick owens"], "our legacy": ["our legacy"],
    "issey miyake": ["issey miyake", "pleats please"], "junya watanabe": ["junya"],
    "loewe": ["loewe"], "dries van noten": ["dries van noten"], "lemaire": ["lemaire"],
    "haider ackermann": ["haider ackermann"], "ann demeulemeester": ["demeulemeester"],
    "khaite": ["khaite"], "45rpm": ["45rpm"], "zegna": ["zegna"], "mugler": ["mugler"],
    "pucci": ["pucci"], "totême": ["totême", "toteme"], "undercover": ["undercover"],
    "claude montana": ["claude montana"], "bottega veneta": ["bottega veneta", "bottega"],
    "margiela": ["margiela"], "arc'teryx": ["arc'teryx", "arcteryx", "arc’teryx"],
    "yohji yamamoto": ["yohji"], "visvim": ["visvim"], "kapital": ["kapital"],
    "carol christian poell": ["poell"], "the row": ["the row"], "alaia": ["alaïa", "alaia"],
    "boris bidjan saberi": ["bidjan", "saberi"], "sacai": ["sacai"],
    "kiko kostadinov": ["kostadinov"], "thom browne": ["thom browne"],
    "thesoloist": ["thesoloist", "the soloist"],
}

# Livello di brand = fair value di una "camicia" in buono stato (base per i
# brand/capi senza riga in tabella). Brand con dati: livello ricavato da un
# modello brand x categoria adattato sulle 91 righe della tabella (errore
# mediano 14%). Brand SENZA dati nei log (segnati "stima"): livello dalla
# conoscenza del mercato dell'usato italiano, NON da comp reali -- verranno
# sostituiti quando il bot avra' raccolto comp veri. Non scartano mai.
FAIR_VALUE_LIVELLO_BRAND = {
    # ricavati dai dati
    "missoni": 34, "miu miu": 88, "marni": 38, "brunello cucinelli": 59, "courreges": 63,
    "jean paul gaultier": 59, "jil sander": 30, "raf simons": 85, "vivienne westwood": 54,
    "helmut lang": 24, "max mara": 54, "engineered garments": 39, "loro piana": 54,
    "rick owens": 84, "issey miyake": 75, "loewe": 114, "dries van noten": 47,
    "haider ackermann": 78, "zegna": 39, "mugler": 42, "pucci": 83,
    # stime da conoscenza di mercato (nessun dato nei log)
    "our legacy": 45, "lemaire": 50, "khaite": 60, "totême": 60, "junya watanabe": 90,
    "undercover": 70, "45rpm": 60, "ann demeulemeester": 75,
    "claude montana": 55, "bottega veneta": 110, "margiela": 95, "arc'teryx": 120,
    "yohji yamamoto": 90, "visvim": 140, "kapital": 110, "carol christian poell": 150,
    "the row": 160, "alaia": 140, "boris bidjan saberi": 150, "sacai": 110,
    "kiko kostadinov": 90, "thom browne": 120, "thesoloist": 90,
    # brand del tracker senza riga in tabella (aggiunti il 2026-10-04: ieri meta' degli annunci non aveva semaforo)
    "prada": 60, "fendi": 80, "jacquemus": 45, "acne studios": 45, "barena venezia": 50,
}
FAIR_VALUE_BRAND_NUOVI = {"prada", "fendi", "jacquemus", "acne studios", "barena venezia"}   # livello da conoscenza: confidenza bassa
FAIR_VALUE_LIVELLO_DEFAULT = _env_float("FAIR_VALUE_LIVELLO_DEFAULT", 45)  # brand mai visto: stima prudente, confidenza bassa
FAIR_VALUE_FATTORE_CATEGORIA = {
    "camicia": 1.0, "blusa": 0.91, "maglia": 1.07, "t-shirt": 0.88, "canotta": 0.70,
    "polo": 0.88, "felpa": 0.90, "gonna": 0.59, "pantaloni": 0.95, "jeans": 0.96,
    "abito": 1.09, "tuta": 1.31, "giacca": 1.53, "gilet": 0.77, "cappotto": 2.7,
    # categorie fuori dalla tabella dati (stime di mercato, confidenza bassa)
    "borsa": 2.5, "scarpe": 1.3, "cintura": 0.5, "sciarpa": 0.6, "cappello": 0.5, "occhiali": 0.7,
    "costume": 0.5, "intimo": 0.4,
}
FAIR_VALUE_FATTORE_SENZA_CATEGORIA = 1.0   # categoria non rilevabile: capo "medio" (come una camicia)
# Taratura (2026-10-04): sugli 87 annunci di ieri arrivati al Cervello la stima rapida era mediamente 0,73 volte il target
# del Cervello (0,68 sui capi venduti in fretta; Missoni 0,62, Cucinelli 0,60). Si applica solo alle voci NON apprese
# (quelle apprese hanno gia' imparato dai verdetti). Campione piccolo: rivedere col recap mattutino.
FAIR_VALUE_TARATURA_GLOBALE = _env_float("FAIR_VALUE_TARATURA_GLOBALE", 1.20)
def _fattori_da_env(testo):
    """'missoni=1.10,brunello cucinelli=1.15' -> {'missoni': 1.1, 'brunello cucinelli': 1.15}. Voci non valide ignorate."""
    out = {}
    for voce in (testo or "").split(","):
        nome, _, val = voce.partition("=")
        try:
            if nome.strip():
                out[nome.strip().lower()] = float(val)
        except ValueError:
            pass
    return out


# In piu' del fattore globale (Missoni: solo prima linea). Modificabile da Railway: FAIR_VALUE_TARATURA_BRAND.
FAIR_VALUE_TARATURA_BRAND = _fattori_da_env(os.environ.get(
    "FAIR_VALUE_TARATURA_BRAND", "missoni=1.10,brunello cucinelli=1.15"))
# Le stime a confidenza bassa ora hanno un colore (prima ⚪), con soglie moltiplicate per questo fattore. Dal
# 2026-10-07 vale 1 (era 1,5): nei dati 4-7/10 un 🟢 a confidenza bassa vendeva veloce quanto uno ad alta (33% vs 36%)
# e con le nuove soglie del semaforo il fattore 1,5 scartava proprio la fascia x3-4, la piu' redditizia.
FAIR_VALUE_RIGORE_BASSA = _env_float("FAIR_VALUE_RIGORE_BASSA", 1.0)
# Borse (watch 5): (minimo, fair value, massimo) per modelli correnti in
# buono stato -- stime da conoscenza di mercato, molto variabili per modello.
FAIR_VALUE_BORSE = {
    "loewe": (200, 380, 700), "lemaire": (150, 260, 420), "miu miu": (170, 330, 600),
}

# Moltiplicatori sulla stima di base (che rappresenta "buone condizioni").
# Condizione: dai comp, "come nuovo" ~1.29x e "da sistemare" ~0.57x rispetto a
# "buono"; il "nuovo con cartellino" dei comp (2.5x) e' troppo gonfiato da
# prezzi di listino USA, quindi limitato. Materiale: effetto piccolo e
# confuso col brand nei dati, quindi moltiplicatori prudenti.
FAIR_VALUE_MOLT_CONDIZIONE = (
    ("senza cartellino", 1.20), ("con cartellino", 1.25), ("ottim", 1.10),
    ("buon", 1.00), ("soddisf", 0.75), ("nuovo", 1.20),
)
FAIR_VALUE_MOLT_MATERIALE = {
    "cashmere": 1.15, "vicuna": 1.30, "vigogna": 1.30, "pelle": 1.25, "seta": 1.05,
    "lana": 1.05, "mohair": 1.05, "alpaca": 1.05, "viscosa": 0.95,
}
FAIR_VALUE_SCONTO_COMP = 0.70  # solo documentazione: gia' applicato nella tabella


# Semaforo: ROI = (fair value - prezzo) / prezzo.
# Ritarato il 2026-10-07 (richiesta dell'utente) sui 337 annunci 4-7/10 con semaforo e vendita tracciata. Venduti
# entro 15 min per fair value/prezzo: <1 9%, 1-1,5 13%, 1,5-2 14%, 2-3 21%, 3-4 41%, 4+ 48%: il salto vero e' a x3.
# Prima (ROI 100/40, margine 15): 🟢 36%, 🟡 17%, 🔴 11%. Ora (ROI 200/100, margine 20): 🟢 44%, 🟡 21%, 🔴 12%.
FAIR_VALUE_ROI_VERDE = _env_float("FAIR_VALUE_ROI_VERDE", 200)
FAIR_VALUE_ROI_GIALLO = _env_float("FAIR_VALUE_ROI_GIALLO", 100)
FAIR_VALUE_MARGINE_MIN_VERDE = _env_float("FAIR_VALUE_MARGINE_MIN_VERDE", 20)
# PREAVVISO (richiesto dall'utente il 2026-10-04): il 37% degli affari e' venduto prima del verdetto (mediana ~30 s),
# quindi la scheda con il semaforo (che parte ~4 s dopo il messaggio) diventa un push con suono quando la stima
# rapida e' promettente. NON cambia il semaforo (usato da ruoli_gemini e dal filtro): e' una regola a parte.
#  - regola "semaforo": 🟢 con margine rapido >= PREAVVISO_MARGINE_MIN;
#  - regola "prezzo_basso": prezzo <= PREAVVISO_PREZZO_BASSO, stima non rossa e margine rapido >= PREAVVISO_MARGINE_BASSO
#    (i venduti entro 30 s dell'analisi del 2026-10-03 costavano quasi tutti <= 30 EUR).
PREAVVISO_ATTIVO = os.environ.get("PREAVVISO_ATTIVO", "1").strip() != "0"
PREAVVISO_MARGINE_MIN = _env_float("PREAVVISO_MARGINE_MIN", 25)
PREAVVISO_PREZZO_BASSO = _env_float("PREAVVISO_PREZZO_BASSO", 20)   # 5/10: 52% di venduti rapidi a <=20 EUR, 22% a 20-40
PREAVVISO_MARGINE_BASSO = _env_float("PREAVVISO_MARGINE_BASSO", 20)
# Per brand (recap 5/10, venduti rapidi su 334 annunci): Acne Studios e Marni 6%, Jean Paul Gaultier 62% (base 25%).
PREAVVISO_BRAND_ESCLUSI = [b.strip().lower() for b in os.environ.get("PREAVVISO_BRAND_ESCLUSI", "acne studios,marni").split(",") if b.strip()]
PREAVVISO_BRAND_FACILI = [b.strip().lower() for b in os.environ.get("PREAVVISO_BRAND_FACILI", "jean paul gaultier").split(",") if b.strip()]
PREAVVISO_MARGINE_FACILI = _env_float("PREAVVISO_MARGINE_FACILI", 10)
# Suono solo per i migliori: fair value rapido / prezzo >= soglia (63% di venduti rapidi con >=4) o brand facile. Gli
# altri preavvisi arrivano in silenzio. 0 = suono sempre.
PREAVVISO_SUONO_RAPPORTO_MIN = _env_float("PREAVVISO_SUONO_RAPPORTO_MIN", 4)


def valuta_preavviso(stima, prezzo):
    """(scatta, regola): push immediato sulla scheda anticipata. Pura. Senza stima o con confidenza bassa non scatta."""
    if not PREAVVISO_ATTIVO or not stima or prezzo is None or prezzo <= 0:
        return False, "no"
    sem, marg = stima.get("semaforo"), stima.get("margine")
    if sem not in ("🟢", "🟡") or marg is None or stima.get("conf") == "bassa":
        return False, "no"
    brand = (stima.get("brand") or "").lower()
    if brand in PREAVVISO_BRAND_ESCLUSI:
        return False, "no"
    if brand in PREAVVISO_BRAND_FACILI and marg >= PREAVVISO_MARGINE_FACILI:
        return True, "brand_facile"
    if sem == "🟢" and marg >= PREAVVISO_MARGINE_MIN:
        return True, "semaforo"
    if prezzo <= PREAVVISO_PREZZO_BASSO and marg >= PREAVVISO_MARGINE_BASSO:
        return True, "prezzo_basso"
    return False, "no"


def preavviso_con_suono(stima, prezzo):
    """True se il preavviso deve suonare (vedi PREAVVISO_SUONO_RAPPORTO_MIN). Pura."""
    if PREAVVISO_SUONO_RAPPORTO_MIN <= 0:
        return True
    stima = stima or {}
    if (stima.get("brand") or "").lower() in PREAVVISO_BRAND_FACILI:
        return True
    fv = stima.get("fv")
    return bool(fv and prezzo and prezzo > 0 and fv / prezzo >= PREAVVISO_SUONO_RAPPORTO_MIN)


# Rosso sicuro (2026-10-04, per ridurre le chiamate Gemini): stima rapida rossa con confidenza alta/media, margine
# rapido NEGATIVO (fair value sotto il prezzo) e prezzo sotto la soglia della fascia alta -> il Cervello non viene
# consultato (l'Occhio si': l'autenticita' e' gia' stata letta). Le eccezioni piu' care restano coperte dalla soglia di
# prezzo. Spento con SALTA_CERVELLO_ROSSO=0. Gli esiti si loggano come SKIP_ROSSO per misurare i falsi negativi.
SALTA_CERVELLO_ROSSO = os.environ.get("SALTA_CERVELLO_ROSSO", "1").strip() != "0"


def check_skip_rosso(listing_info):
    """(True, motivo) se l'annuncio e' un rosso sicuro (vedi SALTA_CERVELLO_ROSSO). Pura."""
    from bot.config import GEMINI_SOGLIA_PREZZO_ALTO
    stima = listing_info.get("fair_value") or {}
    prezzo = _a_float(listing_info.get("price"), None)
    if (not SALTA_CERVELLO_ROSSO or stima.get("semaforo") != "🔴" or stima.get("conf") not in ("alta", "media")
            or stima.get("margine") is None or stima["margine"] >= 0
            or prezzo is None or prezzo >= GEMINI_SOGLIA_PREZZO_ALTO):
        return False, None
    return True, (f"[ROSSO SICURO] Stima rapida {stima.get('brand')} {stima.get('categoria')}: fair value ~{stima.get('fv')} € "
                  f"sotto il prezzo {prezzo:.0f} € (confidenza {stima.get('conf')}) -- Cervello non consultato.")


# Filtro risparmio Gemini: se FAIR_VALUE_FILTRA=1 gli annunci con confidenza
# alta/media e ROI stimato sotto FAIR_VALUE_FILTRA_ROI_MIN % vengono scartati
# in silenzio prima di foto e Gemini. Di default e' in modalita' PROVA (0):
# non scarta nulla, scrive nei log "FAIR VALUE PROVA: avrebbe scartato ...".
FAIR_VALUE_FILTRA = os.environ.get("FAIR_VALUE_FILTRA", "0").strip() == "1"
FAIR_VALUE_FILTRA_ROI_MIN = _env_float("FAIR_VALUE_FILTRA_ROI_MIN", 30)


def _brand_fair_value(listing_info):
    brand = (listing_info.get("brand") or "").lower()
    titolo = (listing_info.get("title") or "").lower()
    # linee secondarie escluse (vedi BRAND_SOTTOLINEE_DA_ESCLUDERE): MM6 non
    # e' Margiela mainline, Y-3 non e' Yohji.
    if re.search(r"\bmm6\b|\by-?3\b|see by chlo", f"{brand} {titolo}"):
        return None
    for nome, kws in FAIR_VALUE_BRAND.items():
        if any(k in brand for k in kws):
            return nome
    for nome, kws in FAIR_VALUE_BRAND.items():
        if any(re.search(r"\b" + re.escape(k) + r"\b", titolo) for k in kws):
            return nome
    # brand del tracker non in elenco: lo si usa cosi' com'e', cosi' ogni annuncio ha una stima (e il brand puo'
    # essere imparato dai verdetti, vedi fv_ricalibra)
    if brand and brand != "?" and len(brand) <= 40:
        return " ".join(brand.split())
    return None


# Categoria da catalogo Vinted: se il titolo non dice che capo e', la categoria si ricava dall'id del catalogo
# (catalog_id letto dalla pagina). La mappa si IMPARA da sola (voto di ogni annuncio con categoria nota dal titolo);
# i semi sono i cataloghi indicati dall'utente (blazer donna 532, blazer uomo 1786). Nessuna richiesta a Vinted.
CATALOGO_CATEGORIE_FILE = os.environ.get("CATALOGO_CATEGORIE_FILE", "/data/catalogo_categorie.json")
CATALOGO_VOTI_MIN = 3        # voti minimi prima di fidarsi del catalogo
CATALOGO_QUOTA_MIN = 0.7     # quota minima della categoria piu' votata
_CATALOGO_SEME = {"532": "giacca", "1786": "giacca"}
_catalogo_voti = {}          # catalog_id -> {categoria: voti}
_catalogo_da_salvare = [0]


def catalogo_carica():
    try:
        with open(CATALOGO_CATEGORIE_FILE, encoding="utf-8") as f:
            dati = json.load(f)
        _catalogo_voti.clear()
        _catalogo_voti.update(dati)
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("Mappa catalogo-categoria non letta:\n%s", traceback.format_exc())


def catalogo_impara(catalog_id, categoria):
    """Un voto per (catalogo, categoria letta dal titolo). Salva su disco ogni 20 voti."""
    if not catalog_id or not categoria:
        return
    voti = _catalogo_voti.setdefault(str(catalog_id), {})
    voti[categoria] = voti.get(categoria, 0) + 1
    _catalogo_da_salvare[0] += 1
    if _catalogo_da_salvare[0] >= 20:
        _catalogo_da_salvare[0] = 0
        try:
            cartella = os.path.dirname(CATALOGO_CATEGORIE_FILE)
            if cartella:
                os.makedirs(cartella, exist_ok=True)
            with open(CATALOGO_CATEGORIE_FILE, "w", encoding="utf-8") as f:
                json.dump(_catalogo_voti, f, ensure_ascii=False)
        except Exception:
            log.warning("Mappa catalogo-categoria non salvata:\n%s", traceback.format_exc())


def categoria_da_catalogo(catalog_id):
    """Categoria piu' votata per il catalogo (con voti e quota minimi), altrimenti il seme, altrimenti None. Pura."""
    if not catalog_id:
        return None
    voti = _catalogo_voti.get(str(catalog_id)) or {}
    totale = sum(voti.values())
    if totale >= CATALOGO_VOTI_MIN:
        categoria, n = max(voti.items(), key=lambda kv: kv[1])
        if n / totale >= CATALOGO_QUOTA_MIN:
            return categoria
    return _CATALOGO_SEME.get(str(catalog_id))


def categoria_annuncio(listing_info):
    """(categoria, fonte): titolo -> descrizione -> catalogo Vinted -> (None, 'nessuna'). Pura."""
    titolo = listing_info.get("title") or ""
    cat = estrai_categoria_da_titolo(titolo, None)
    if cat:
        return cat, "titolo"
    cat = estrai_categoria_da_titolo("", listing_info.get("description"))
    if cat:
        return cat, "descrizione"
    cat = categoria_da_catalogo(listing_info.get("catalog_id"))
    if cat:
        return cat, "catalogo"
    return None, "nessuna"


# Sottolinee/linee secondarie riconoscibili dal TESTO dell'annuncio: valgono
# meno (o diversamente) del brand madre, quindi non devono usare la sua riga.
FAIR_VALUE_SOTTOLINEE = {
    "max mara": {
        "weekend max mara": r"\bweekend\b", "marella": r"\bmarella\b", "sportmax": r"\bsportmax\b",
        "max mara studio": r"\bmax\s*mara\s+studio\b", "'s max mara": r"(?:^|\s)'?s\s+max\s*mara\b",
    },
    "missoni": {"m missoni": r"\bm\s+missoni\b", "missoni sport": r"\bmissoni\s+sport\b"},
    "jean paul gaultier": {"jean's paul gaultier": r"jean'?s\s+paul\s+gaultier"},
}


def _sottolinea_da_testo(listing_info, brand):
    testo = f"{listing_info.get('title') or ''} {listing_info.get('brand') or ''}".lower()
    for nome, pattern in FAIR_VALUE_SOTTOLINEE.get(brand, {}).items():
        if re.search(pattern, testo):
            return nome
    return None


def _moltiplicatore_fair_value(listing_info):
    """Correzione condizione x materiale rispetto alla base 'buone condizioni'."""
    molt = 1.0
    condizione = (listing_info.get("condition") or "").lower()
    for chiave, m in FAIR_VALUE_MOLT_CONDIZIONE:
        if chiave in condizione:
            molt *= m
            break
    materiale = scegli_materiale_per_ricerca(listing_info.get("material_raw"))
    return molt * FAIR_VALUE_MOLT_MATERIALE.get(materiale, 1.0)


def stima_fair_value(listing_info):
    """Ritorna None solo se manca anche il brand, altrimenti dict con minimo/fair value/massimo gia' corretti per
    condizione e materiale, confidenza, e (se il prezzo e' noto) ROI, margine e semaforo. Ogni annuncio con brand ha un
    semaforo (2026-10-04): tabella dati -> appreso dai verdetti -> livello del brand x fattore della categoria -> livello
    di default; la categoria viene dal titolo, dalla descrizione o dal catalogo Vinted."""
    brand = _brand_fair_value(listing_info)
    if not brand:
        return None
    categoria, fonte_cat = categoria_annuncio(listing_info)
    voce = FAIR_VALUE_TABELLA.get(f"{brand}|{categoria}") if categoria else None
    appreso = FAIR_VALUE_APPRESO.get(f"{brand}|{categoria}") if categoria else None
    da_appreso = bool(appreso)
    if appreso:
        # la tabella appresa (da Gemini e dalle tue stime) ha la precedenza
        voce = (appreso["lo"], appreso["fv"], appreso["hi"], appreso["conf"], appreso["n"], voce[5] if voce else 0)
    if not voce and categoria == "borsa" and brand in FAIR_VALUE_BORSE:
        minimo, fv, massimo = FAIR_VALUE_BORSE[brand]
        voce = (minimo, fv, massimo, "stima", 0, 0)
    if not voce:
        # livello del brand x fattore della categoria; sconosciuti -> default con confidenza bassa
        livello = FAIR_VALUE_LIVELLO_BRAND.get(brand)
        fattore = FAIR_VALUE_FATTORE_CATEGORIA.get(categoria) if categoria else FAIR_VALUE_FATTORE_SENZA_CATEGORIA
        conf_gen = ("stima" if (livello and fattore and categoria in FAIR_VALUE_FATTORE_CATEGORIA
                             and brand not in FAIR_VALUE_BRAND_NUOVI) else "bassa")
        fv = (livello or FAIR_VALUE_LIVELLO_DEFAULT) * (fattore if fattore is not None else FAIR_VALUE_FATTORE_SENZA_CATEGORIA)
        voce = (round(fv * 0.6), round(fv), round(fv * 1.7), conf_gen, 0, 0)
    minimo, fv, massimo, conf, n_comp, n_reali = voce
    sottolinea = _sottolinea_da_testo(listing_info, brand)
    if sottolinea:
        appreso_sott = FAIR_VALUE_APPRESO.get(f"{sottolinea}|{categoria}")
        if appreso_sott:
            minimo, fv, massimo, conf, n_comp = appreso_sott["lo"], appreso_sott["fv"], appreso_sott["hi"], appreso_sott["conf"], appreso_sott["n"]
            da_appreso = True
        else:
            conf = "bassa"   # stima del brand madre: solo indicativa finche' non impara la sottolinea
    molt = _moltiplicatore_fair_value(listing_info)
    if not da_appreso:
        extra = FAIR_VALUE_TARATURA_BRAND.get(brand, 1.0)
        if sottolinea:
            extra = 1.0   # M Missoni, Missoni Sport, Weekend...: il fattore in piu' vale per la prima linea
        molt *= FAIR_VALUE_TARATURA_GLOBALE * extra
    out = {
        "brand": brand, "categoria": categoria, "fonte_categoria": fonte_cat, "conf": conf, "n_comp": n_comp,
        "n_reali": n_reali,
        "minimo": round(minimo * molt), "fv": round(fv * molt), "massimo": round(massimo * molt),
        "moltiplicatore": round(molt, 2), "roi": None, "margine": None, "semaforo": None,
        "sottolinea": sottolinea,
    }
    prezzo = _a_float(listing_info.get("price"), None)
    if prezzo is not None and prezzo > 0:
        out["margine"] = round(out["fv"] - prezzo, 2)
        out["roi"] = round((out["fv"] - prezzo) / prezzo * 100)
        rigore = FAIR_VALUE_RIGORE_BASSA if conf == "bassa" else 1.0   # stima debole: servono margini piu' netti
        if out["roi"] >= FAIR_VALUE_ROI_VERDE * rigore and out["margine"] >= FAIR_VALUE_MARGINE_MIN_VERDE * rigore:
            out["semaforo"] = "🟢"
        elif out["roi"] >= FAIR_VALUE_ROI_GIALLO * rigore:
            out["semaforo"] = "🟡"
        else:
            out["semaforo"] = "🔴"
    return out


def _riga_fair_value_unica(stima, verdetto, campioni=None, instabile=False):
    """UNICA riga di fair value del verdetto (prima erano due: 'Fair value' nella scheda e 'Rapido…Gemini…'
    nel verdetto): giudizio rapido (con intervallo), stima di Gemini, semaforo e, se le valutazioni
    indipendenti del Cervello divergono, l'avviso di stima instabile. Stringa vuota se non c'e' nulla."""
    parti = []
    if stima:
        parti.append(f"Fair value ~{stima['fv']} € ({stima['minimo']}-{stima['massimo']})")
    if verdetto and verdetto.get("vendita_attesa"):
        parti.append(f"Gemini ~{verdetto['vendita_attesa']:.0f} €")
    if not parti:
        return ""
    if stima and stima.get("semaforo"):
        parti.append(stima["semaforo"])
    if instabile and campioni:
        parti.append(f"⚠️ stima instabile {campioni} €")
    return "📊 " + " · ".join(parti)


def _riga_fair_value_testo(stima):
    if not stima:
        return None
    parti = [f"📊 Fair value ~{stima['fv']} € ({stima['minimo']}-{stima['massimo']})"]
    if stima["roi"] is not None:
        parti.append(f"ROI {stima['roi']:+d}%")
    if stima["semaforo"]:
        parti.append(stima["semaforo"])
    if stima.get("sottolinea") and stima["conf"] == "bassa":
        parti.append(f"{stima['sottolinea']}: stima del brand madre, indicativa")
    elif stima["conf"] == "bassa":
        parti.append("indicativo")
    elif stima["conf"] == "stima":
        parti.append("stima di mercato")
    return " · ".join(parti)


def check_skip_fair_value(listing_info):
    """(True, motivo) se il fair value a priori indica che non c'e' margine.
    Solo con confidenza alta/media: le voci 'bassa' non scartano mai."""
    stima = stima_fair_value(listing_info)
    if not stima or stima["roi"] is None or stima["conf"] not in ("alta", "media"):
        return False, None
    if stima["roi"] < FAIR_VALUE_FILTRA_ROI_MIN:
        return True, (f"[FAIR VALUE SOTTO SOGLIA] {stima['brand']} {stima['categoria']}: fair value ~{stima['fv']} € "
                      f"contro prezzo {listing_info.get('price')} € (ROI {stima['roi']:+d}%, confidenza {stima['conf']})")
    return False, None


# ---------------------------------------------------------------------------
# APPRENDIMENTO DEL FAIR VALUE (richiesto dall'utente il 2026-10-01)
# ---------------------------------------------------------------------------
# Il bot confronta il giudizio rapido (tabella) con quello di Gemini con le
# foto e con le tue stime umane, e corregge la tabella da solo.
#  - Archivio: righe JSON in FAIR_VALUE_LOG_FILE (volume Railway /data). Tre
#    tipi: "rapida" (stima al momento dell'annuncio), "gemini" (esito del
#    verdetto), "umana" (tua stima, rispondendo con un numero alla scheda).
#  - Ricalibrazione: per ogni "brand|categoria" la nuova stima e' la media
#    pesata tra il valore di partenza (peso 4 se alta, 3 media, 2 bassa, 1.5
#    stima) e la MEDIANA PESATA dei campioni (Gemini peso 1, tu peso 3),
#    riportati alla base "buone condizioni" dividendo per il moltiplicatore.
#    Limitata a 0.3x-3x del valore di partenza. Gemini conta solo se ha
#    usato almeno 2 comp reali; la tua stima conta sempre.
#  - Confidenza: peso campioni >= 12 alta, >= 5 media, sotto resta quella di
#    partenza. Il filtro (FAIR_VALUE_FILTRA) agisce solo su alta/media.
FAIR_VALUE_LOG_FILE = os.environ.get("FAIR_VALUE_LOG_FILE", "/data/fair_value_log.jsonl")
FAIR_VALUE_APPRESO_FILE = os.environ.get("FAIR_VALUE_APPRESO_FILE", "/data/fair_value_appreso.json")
FAIR_VALUE_APPRESO = {}
_FV_PESO_PARTENZA = {"alta": 4.0, "media": 3.0, "bassa": 2.0, "stima": 1.5}
_FV_PESO_GEMINI = 1.0
_FV_PESO_UMANO = 3.0
_FV_NUOVE_RIGHE_PER_RICALCOLO = 10
_fv_righe_da_ricalcolo = [0]


_JSONL_CARTELLE_CREATE = set()


def _jsonl_append(path, record, nome):
    """Aggiunge una riga JSON (con timestamp) a un archivio .jsonl. Mai bloccante."""
    try:
        cartella = os.path.dirname(path)
        if cartella and cartella not in _JSONL_CARTELLE_CREATE:
            os.makedirs(cartella, exist_ok=True)
            _JSONL_CARTELLE_CREATE.add(cartella)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), **record}, ensure_ascii=False) + "\n")
        return True
    except Exception:
        log.warning("%s non scritto:\n%s", nome, traceback.format_exc())
        return False


def _jsonl_read(path, nome):
    righe = []
    try:
        with open(path, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if riga:
                    try:
                        righe.append(json.loads(riga))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("%s non letto:\n%s", nome, traceback.format_exc())
    return righe


def _fv_scrivi(record):
    """Aggiunge una riga all'archivio. Mai bloccante."""
    return _jsonl_append(FAIR_VALUE_LOG_FILE, record, "Archivio fair value")


def _fv_leggi():
    return _jsonl_read(FAIR_VALUE_LOG_FILE, "Archivio fair value")


def fv_registra_rapida(listing_info, url, scartato=False):
    """Giudizio rapido al momento dell'annuncio (anche senza riga in tabella:
    servono per imparare le combinazioni nuove)."""
    item_id = _estrai_item_id_da_url(url) if url else None
    if not item_id:
        return
    stima = listing_info.get("fair_value")
    _fv_scrivi({
        "tipo": "rapida", "item_id": str(item_id), "brand": _brand_fair_value(listing_info),
        "categoria": categoria_annuncio(listing_info)[0],
        "titolo": listing_info.get("title"), "prezzo": _a_float(listing_info.get("price"), None),
        "condizione": listing_info.get("condition"), "molt": round(_moltiplicatore_fair_value(listing_info), 3),
        "fv": stima["fv"] if stima else None, "conf": stima["conf"] if stima else None,
        "semaforo": stima["semaforo"] if stima else None, "scartato": bool(scartato),
    })


def fv_classifica_campione(listing_info, decisione, occhio_json=None, legit=None):
    """Decide se l'esito di Gemini e' un campione valido per imparare il
    valore del brand dichiarato, e con quale chiave. Caso tipico da NON
    imparare: titolo "cappotto Max Mara" ma nelle foto l'etichetta e' Weekend
    (sottolinea): Gemini lo valuta molto meno, e quel prezzo non e' quello di
    un Max Mara. Regole:
     - relazione_brand deve essere esplicitamente "corrisponde" (letto
       dall'etichetta) -> campione del brand dichiarato;
     - "sottolinea_stessa_maison" con nome noto -> campione della SOTTOLINEA
       (riga separata, es. "weekend max mara"), mai del brand madre;
     - brand_estraneo, tessuto_non_brand, non_leggibile, Occhio assente,
       legit "probabilmente_falso" o SKIP -> scartato (motivo registrato).
    Ritorna (valido, chiave_brand, motivo_scarto)."""
    o = occhio_json or {}
    rel = o.get("relazione_brand")
    sott = str(o.get("nome_sottolinea") or "").strip().lower()
    brand = _brand_fair_value(listing_info)
    if decisione == "SKIP":
        return False, None, "skip"
    if legit == "probabilmente_falso":
        return False, None, "probabilmente falso"
    if rel == "corrisponde" and not sott:
        return (True, brand, None) if brand else (False, None, "brand fuori tabella")
    if rel == "sottolinea_stessa_maison" and sott:
        chiave = sott if (not brand or brand in sott) else f"{sott} {brand}"
        return True, chiave, None
    return False, None, f"relazione brand: {rel or 'Occhio assente'}"


def fv_registra_gemini(listing_info, url, decisione, verdetto, occhio_json=None, legit=None):
    item_id = _estrai_item_id_da_url(url) if url else None
    if not item_id:
        return
    v = verdetto or {}
    valido, chiave_brand, motivo = fv_classifica_campione(listing_info, decisione, occhio_json, legit)
    _fv_scrivi({
        "tipo": "gemini", "item_id": str(item_id), "decisione": decisione,
        "vendita": v.get("vendita_attesa"), "margine": v.get("margine"), "roi": v.get("roi"),
        "n_comp_reali": v.get("n_comp_reali"), "valido": valido, "chiave_brand": chiave_brand,
        "motivo_scarto": motivo, "relazione": (occhio_json or {}).get("relazione_brand"),
        "sottolinea": (occhio_json or {}).get("nome_sottolinea"), "legit": legit,
    })
    _fv_dopo_scrittura()


def fv_registra_umana(item_id, valore):
    _fv_scrivi({"tipo": "umana", "item_id": str(item_id), "stima": float(valore)})
    _fv_dopo_scrittura()


def _fv_dopo_scrittura():
    _fv_righe_da_ricalcolo[0] += 1
    if _fv_righe_da_ricalcolo[0] >= _FV_NUOVE_RIGHE_PER_RICALCOLO:
        _fv_righe_da_ricalcolo[0] = 0
        try:
            fv_ricalibra()
        except Exception:
            log.warning("Ricalibrazione fair value fallita:\n%s", traceback.format_exc())


def fv_unisci(righe):
    """Una riga per annuncio con rapida + gemini + umana."""
    per_item = {}
    for r in righe:
        d = per_item.setdefault(r.get("item_id"), {})
        if r.get("tipo") == "rapida":
            d["rapida"] = r
        elif r.get("tipo") == "gemini":
            d["gemini"] = r
        elif r.get("tipo") == "umana":
            d["umana"] = r
    return per_item


def _mediana_pesata(coppie):
    coppie = sorted(coppie)
    totale = sum(w for _, w in coppie)
    cumulo = 0.0
    for x, w in coppie:
        cumulo += w
        if cumulo >= totale / 2:
            return x
    return coppie[-1][0]


def fv_ricalibra(righe=None):
    """Ricalcola FAIR_VALUE_APPRESO dall'archivio e lo salva su disco."""
    per_item = fv_unisci(righe if righe is not None else _fv_leggi())
    campioni = {}
    for d in per_item.values():
        rap = d.get("rapida") or {}
        g = d.get("gemini") or {}
        cat = rap.get("categoria")
        # la chiave del brand viene dall'etichetta letta da Gemini (puo' essere
        # una sottolinea), altrimenti da quella del titolo
        brand = g.get("chiave_brand") if g.get("valido") else rap.get("brand")
        if not brand or not cat:
            continue
        molt = rap.get("molt") or 1.0
        chiave = f"{brand}|{cat}"
        if (g.get("valido") and g.get("vendita") and (g.get("n_comp_reali") or 0) >= 2
                and g.get("decisione") != "SKIP"):
            campioni.setdefault(chiave, []).append((g["vendita"] / molt, _FV_PESO_GEMINI))
        u = d.get("umana")
        if u and u.get("stima"):
            campioni.setdefault(chiave, []).append((u["stima"] / molt, _FV_PESO_UMANO))
    nuovo = {}
    for chiave, lista in campioni.items():
        peso = sum(w for _, w in lista)
        mediana = _mediana_pesata(lista)
        voce = FAIR_VALUE_TABELLA.get(chiave)
        if voce:
            lo0, fv0, hi0, conf0 = voce[0], voce[1], voce[2], voce[3]
        else:
            brand, cat = chiave.split("|")
            livello = FAIR_VALUE_LIVELLO_BRAND.get(brand)
            fattore = FAIR_VALUE_FATTORE_CATEGORIA.get(cat)
            if livello and fattore:
                fv0 = livello * fattore
                lo0, hi0, conf0 = fv0 * 0.6, fv0 * 1.7, "stima"
            else:
                fv0 = lo0 = hi0 = conf0 = None
        if fv0:
            w0 = _FV_PESO_PARTENZA.get(conf0, 2.0)
            fv = (w0 * fv0 + peso * mediana) / (w0 + peso)
            fv = max(0.3 * fv0, min(3.0 * fv0, fv))
            scala = fv / fv0
            lo, hi = lo0 * scala, hi0 * scala
        else:
            if peso < 3:
                continue
            fv, lo, hi, conf0 = mediana, mediana * 0.6, mediana * 1.7, "stima"
        da_peso = "alta" if peso >= 12 else "media" if peso >= 5 else None
        ordine = {"stima": 0, "bassa": 1, "media": 2, "alta": 3}
        conf = max((c for c in (conf0, da_peso) if c), key=lambda c: ordine.get(c, 0))
        nuovo[chiave] = {"lo": round(lo), "fv": round(fv), "hi": round(hi), "conf": conf, "n": len(lista)}
    FAIR_VALUE_APPRESO.clear()
    FAIR_VALUE_APPRESO.update(nuovo)
    try:
        cartella = os.path.dirname(FAIR_VALUE_APPRESO_FILE)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        with open(FAIR_VALUE_APPRESO_FILE, "w", encoding="utf-8") as f:
            json.dump(nuovo, f, ensure_ascii=False, indent=1)
    except Exception:
        log.warning("Tabella appresa non salvata:\n%s", traceback.format_exc())
    log.info("Fair value ricalibrato: %d righe apprese (%d annunci in archivio)", len(nuovo), len(per_item))
    return nuovo


def fv_carica_appreso():
    catalogo_carica()
    try:
        with open(FAIR_VALUE_APPRESO_FILE, encoding="utf-8") as f:
            dati = json.load(f)
        FAIR_VALUE_APPRESO.clear()
        FAIR_VALUE_APPRESO.update(dati)
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("Tabella appresa non letta:\n%s", traceback.format_exc())


_DECISIONI_POSITIVE = ("COMPRA", "TRATTA")


def fv_rapporto(righe=None):
    """Testo del rapporto di confronto giudizio rapido / Gemini / tua stima."""
    per_item = fv_unisci(righe if righe is not None else _fv_leggi())
    tot = len(per_item)
    con_g = [d for d in per_item.values() if d.get("rapida") and d.get("gemini")
             and d["gemini"].get("decisione") not in (None, "SKIP")]
    out = ["📊 Fair value: rapporto", f"Annunci in archivio: {tot} · con verdetto Gemini: {len(con_g)}"]
    if len(con_g) < 10:
        out.append("Pochi dati per trarre conclusioni: servono almeno 10-20 confronti.")
    scartati = {}
    for d in per_item.values():
        g = d.get("gemini") or {}
        if g and not g.get("valido") and g.get("motivo_scarto"):
            scartati[g["motivo_scarto"]] = scartati.get(g["motivo_scarto"], 0) + 1
    if scartati:
        out.append("Esiti Gemini NON usati per imparare: " + ", ".join(f"{n} ({m})" for m, n in sorted(scartati.items(), key=lambda x: -x[1])))
    colori = {}
    for d in con_g:
        sem = d["rapida"].get("semaforo") or "senza stima"
        colori.setdefault(sem, []).append(d["gemini"].get("decisione") in _DECISIONI_POSITIVE)
    if colori:
        out.append("")
        out.append("Semaforo rapido -> Gemini dice COMPRA o TRATTA:")
        for sem in ("🟢", "🟡", "🔴", "⚪", "senza stima"):
            if sem in colori:
                lista = colori[sem]
                out.append(f"{sem} {len(lista)} annunci, {sum(lista)} positivi ({sum(lista) * 100 // len(lista)}%)")
    rossi = colori.get("🔴", [])
    if rossi:
        falsi = sum(rossi)
        out.append("")
        out.append(f"Falsi scarti se il filtro fosse acceso: {falsi} su {len(rossi)} rossi "
                   f"({falsi * 100 // len(rossi)}%). Risparmio: {len(rossi)} chiamate su {len(con_g)} "
                   f"({len(rossi) * 100 // len(con_g)}%).")
        out.append("Filtro consigliato solo con falsi scarti sotto il 5% su almeno 30 rossi.")
    rapporti = [d["rapida"]["fv"] / d["gemini"]["vendita"] for d in con_g
                if d["rapida"].get("fv") and d["gemini"].get("vendita") and (d["gemini"].get("n_comp_reali") or 0) >= 2]
    if rapporti:
        out.append("")
        out.append(f"Fair value rapido / vendita stimata da Gemini: mediana {statistics.median(rapporti):.2f} su {len(rapporti)} annunci (1.00 = identici).")
    umane = [d for d in per_item.values() if d.get("umana")]
    if umane:
        rr = [d["rapida"]["fv"] / d["umana"]["stima"] for d in umane if d.get("rapida", {}).get("fv")]
        out.append(f"Tue stime: {len(umane)}" + (f" · fair value / tua stima: mediana {statistics.median(rr):.2f}" if rr else ""))
    out.append("")
    out.append(f"Righe apprese dalla tabella: {len(FAIR_VALUE_APPRESO)}")
    out.append("Per darmi una stima: rispondi alla scheda (o al verdetto) con un numero, es. 55.")
    return "\n".join(out)
