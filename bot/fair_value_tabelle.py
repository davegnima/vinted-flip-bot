"""Tabelle e tarature del fair value (spostate da bot/fair_value.py senza cambiare nulla): livelli per brand, fattori per categoria,
tarature, moltiplicatori di condizione e materiale, sottolineature. Solo dati e la lettura delle loro variabili d'ambiente.
bot/fair_value.py le reimporta con gli stessi nomi (restano disponibili come bot.fair_value.NOME).
Non sono qui valuta_preavviso e le soglie PREAVVISO_*: i test le cambiano con monkeypatch su bot.fair_value e dovrebbero restare li'."""

import os

from bot.config import _env_float


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
    "zimmermann": ["zimmermann"], "cult gaia": ["cult gaia"], "greg lauren": ["greg lauren"],
    "fuzzi": ["fuzzi"], "staud": ["staud"], "ulla johnson": ["ulla johnson"], "sea new york": ["sea new york"],
    "saloni": ["saloni"], "veronica beard": ["veronica beard"], "la doublej": ["la doublej", "doublej"],
    "johnny was": ["johnny was"], "gudrun sjödén": ["gudrun sj"], "madhappy": ["madhappy"],
    "henry beguelin": ["beguelin"], "lancel": ["lancel"], "double d ranch": ["double d ranch"],
    "self-portrait": ["self-portrait", "self portrait"], "jonathan simkhai": ["simkhai"],
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
    # 1/11 boutique (lista dell'utente, nessun dato nei log): livelli prudenti da prezzi richiesti visti su Vinted, confidenza bassa
    "greg lauren": 120, "zimmermann": 80, "la doublej": 65, "ulla johnson": 60, "self-portrait": 55,
    # 1/11 terzo giro (stime prudenti da prezzi richiesti, confidenza bassa)
    "by walid": 100,
    "l.a.m.b.": 70,
    "erdem": 90,
    "emilia wickstead": 100,
    "rosie assoulin": 100,
    "agua bendita": 45,
    "borgo de nor": 45,
    "leo lin": 50,
    "alémais": 45,
    "juliet dunn": 40,
    "celia b": 40,
    "banjanan": 40,
    "ciao lucia": 40,
    "posse": 40,
    "dragon diffusion": 45,
    "jérôme dreyfuss": 40,
    "kurt geiger": 30,
    "radley": 30,
    "mz wallace": 30,
    "hill house home": 40,
    "sézane": 40,
    "oleana": 50,
    "antik batik": 35,
    "farm rio": 35,
    "pink city prints": 35,
    "cleobella": 35,
    # 2/11 livelli prudenti (stime, nessun dato)
    "tuckernuck": 30,
    "hyacinth house": 30,
    "mirth": 30,
    "oliphant": 30,
    "pomander place": 30,
    "rococo sand": 30,
    "carolina k": 35,
    "printfresh": 30,
    "the strike gold": 30,
    "the great china wall": 30,
    "loretta caponi": 45,
    "cara cara": 30,
    "goen.j": 30,
    "hunter bell": 30,
    "fanm mon": 30,
    "emporio sirenuse": 40,
    "evereve": 30,
    "wildfang": 30,
    "the great": 35,
    "pistola": 30,
    "alex mill": 30,
    "taylor stitch": 30,
    "quince": 25,
    "johnny was": 40, "gudrun sjödén": 35, "madhappy": 45, "henry beguelin": 45, "lancel": 35, "double d ranch": 50, "cult gaia": 55, "sea new york": 40, "staud": 40, "saloni": 40, "veronica beard": 35, "jonathan simkhai": 40, "fuzzi": 30,
}

FAIR_VALUE_BRAND_NUOVI = {"prada", "fendi", "jacquemus", "acne studios", "barena venezia", "greg lauren", "bode", "zimmermann",
                          "la doublej", "ulla johnson", "self-portrait", "cult gaia", "sea new york", "staud", "saloni",
                          "veronica beard", "jonathan simkhai", "fuzzi", "henry beguelin", "lancel", "double d ranch", "johnny was", "gudrun sjödén", "madhappy",
                          "by walid", "l.a.m.b.", "erdem", "emilia wickstead", "rosie assoulin", "agua bendita", "borgo de nor", "leo lin", "alémais", "juliet dunn", "celia b", "banjanan", "ciao lucia", "posse", "dragon diffusion", "jérôme dreyfuss", "kurt geiger", "radley", "mz wallace", "hill house home", "sézane", "oleana", "antik batik", "farm rio", "pink city prints", "cleobella", "the great", "pistola", "alex mill", "taylor stitch", "quince", "tuckernuck", "hyacinth house", "mirth", "oliphant", "pomander place", "rococo sand", "carolina k", "printfresh", "the strike gold", "the great china wall", "loretta caponi", "cara cara", "goen.j", "hunter bell", "fanm mon", "emporio sirenuse", "evereve", "wildfang"}   # livello da conoscenza: confidenza bassa

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
# 6/11, da 249 verifiche Jev (3 giorni, rivendita p25 dei comparabili / stima del semaforo, mediana per brand): Prada x1,45 (n=37, 59% venduti
# in fretta), Cucinelli x1,19 (n=15, 55%). Fattore = 1 + n/(n+15) x (rapporto-1), tetto 1,30: Prada 1,30; Cucinelli 1,15 x 1,10 = 1,26.
# NON toccati: Missoni 1,20 (15% veloci), Max Mara 1,04, JPG 1,15 (19%), Lancel 0,84 (8%: abbassare e' rimandato dall'utente).
FAIR_VALUE_TARATURA_BRAND = _fattori_da_env(os.environ.get(
    "FAIR_VALUE_TARATURA_BRAND", "missoni=1.10,brunello cucinelli=1.26,prada=1.30"))

# Le stime a confidenza bassa ora hanno un colore (prima ⚪), con soglie moltiplicate per questo fattore. Dal
# 2026-10-07 vale 1 (era 1,5): nei dati 4-7/10 un 🟢 a confidenza bassa vendeva veloce quanto uno ad alta (33% vs 36%)
# e con le nuove soglie del semaforo il fattore 1,5 scartava proprio la fascia x3-4, la piu' redditizia.
FAIR_VALUE_RIGORE_BASSA = _env_float("FAIR_VALUE_RIGORE_BASSA", 1.0)

# Borse (watch 5): (minimo, fair value, massimo) per modelli correnti in
# buono stato -- stime da conoscenza di mercato, molto variabili per modello.
FAIR_VALUE_BORSE = {
    "loewe": (200, 380, 700), "lemaire": (150, 260, 420), "miu miu": (170, 330, 600),
    # 02/11: dai comparabili Vinted verificati con Jev (borse usate): Lancel 50-107 EUR, Kurt Geiger ~56 EUR. Il livello x fattore borsa
    # (2,5) le gonfiava (Lancel 145, Kurt Geiger 99). Stime dai comparabili, campione piccolo.
    "lancel": (40, 65, 110), "kurt geiger": (35, 55, 100),
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
