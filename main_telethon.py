"""
Vinted Flip Oracle Bot (versione Telethon / userbot) -- Scenario G con fallback F
====================================================================================
Pipeline finale, basata sugli scenari di ottimizzazione dei costi e filtro.
Include: categorie multilingua estese, niente fallback "dress" pericoloso su
Vestiaire, e function calling FORZATO per il cervello Gemini (sostituisce
google_search, che su Gemini non e' forzabile in modo affidabile).
"""

import os
import re
import html
import json
import time
import asyncio
import base64
import logging
import traceback
from io import BytesIO
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from PIL import Image

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELEGRAM_SESSION_STRING = os.environ["TELEGRAM_SESSION_STRING"]
TELEGRAM_GROUP_ID = int(os.environ["TELEGRAM_GROUP_ID"])

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_CHAT_ID = os.environ["TELEGRAM_OWNER_CHAT_ID"]
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

PREZZO_GEMINI_INPUT = 0.25
PREZZO_GEMINI_OUTPUT = 1.50
PREZZO_GROUNDING_PER_QUERY = 14 / 1000

MAX_GALLERY_PHOTOS = 10

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

_serper_fallimenti_consecutivi = [0]
_serper_timestamp_ultimo_fallimento = [0.0]
SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO = 3
RAFFREDDAMENTO_SERPER_SECONDI = 3600 * 6
_serper_notifica_esaurimento_inviata = [False]

# Rate-limiter tra richieste Vinted consecutive: dopo ~13h di attività
# continua Vinted ha iniziato a rispondere 403 Forbidden (probabile blocco
# per volume di richieste). Impone una pausa minima tra una scrape e la
# successiva per restare sotto la soglia che scatena il blocco.
_vinted_timestamp_ultima_richiesta = [0.0]
PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI = 3.0

# BLOCKLIST VENDITORI
VENDITORI_BLOCKLIST = {"valeryepippo", "firmadonna98", "cicciodonna779", "hadourif"}

VINTED_BRAND_IDS = {
    "brunello cucinelli": "103740", "rick owens": "145654",
    "arc'teryx": "319730", "arcteryx": "319730", "patagonia": "90804",
    "marni": "12251", "missoni": "4463", "jean paul gaultier": "4129",
    "jpg": "4129", "emilio pucci": "10831", "pucci": "10831",
    "issey miyake": "75090", "pleats please": "395642",
    "pleats please issey miyake": "395642", "claude montana": "121608",
    "miu miu": "1745", "thierry mugler": "284", "mugler": "284",
    "courreges": "12639", "courrèges": "12639",
    "m missoni": "1702343", "missoni home": "2776470",
    "missoni mare": "2720679", "vivienne westwood": "14217",
    "yohji yamamoto": "200474", "dries van noten": "72138",
    "ann demeulemeester": "51445", "raf simons": "184436", "loewe": "24209",
    "helmut lang": "47829", "jil sander": "17991",
    "bottega veneta": "86972", "maison margiela": "639289",
    "margiela": "639289", "max mara": "5483",
    "veilance": "3388210", "nanga": "434286",
    "snow peak": "666350", "acronym": "712647",
    "isabel marant": "14361",
    "alaïa": "69184",
    "alaia": "69184",
    "yves saint laurent": "377",
    "junya watanabe": "235040",
    "thom browne": "399438",
    "khaite": "806862",
    "alexander mcqueen": "52193",
    "chloé": "2113",
    "chloe": "2113",
    "stella mccartney": "13893",
    "totême": "546105",
    "toteme": "546105",
    "ermenegildo zegna": "174480",
    "zegna": "174480",
    "our legacy": "218132",
    "loro piana": "219848",
    "lemaire": "295938",
    "the frankie shop": "378382",
    "frankie shop": "378382",
    "number (n)ine": "505614",
    "number nine": "505614",
    "takahiromiyashita thesoloist": "1726469",
    "takahiromiyashita the soloist": "1726469",
    "thesoloist": "1726469",
    "the soloist": "1726469",
    "engineered garments": "609050",
    "undercover": "59974",
    "visvim": "276225",
    "45rpm": "464091",
    "kapital": "576107",
    "carol christian poell": "1996050", "ccp": "1996050",
    "haider ackermann": "232276",
    "the row": "547584",
    "boris bidjan saberi": "484649", "bbs": "484649",
    "sacai": "369700",
    "kiko kostadinov": "5821136",
}
# ESCLUSIONI VOLUTE (non mappare per evitare falsi positivi o capi di scarso valore):
# - "saint laurent" (post-2012, id 83122): altissimo rischio fake, preferiamo concentrarci su YSL vintage.
# - "McQ" (id 849677): diffusion line di Alexander McQueen, valore di mercato molto inferiore.
# - "See by Chloé" (id 1472883): diffusion line di Chloé, satura e con basso ROI.

MATERIALI_PREGIATI_PRIORITA = [
    "cashmere", "vicuna", "vigogna", "seta", "velluto", "pelle", "shearling",
    "montone", "renna", "alpaca", "mohair", "lana", "lino", "viscosa", "lurex",
    "denim", "cotone",
]

MATERIALI_TRADUZIONI = {
    "silk": "seta", "soie": "seta", "seide": "seta",
    "velvet": "velluto", "velours": "velluto", "samt": "velluto",
    "leather": "pelle", "cuir": "pelle", "leder": "pelle",
    "wool": "lana", "laine": "lana", "wolle": "lana",
    "linen": "lino", "lin": "lino", "leinen": "lino",
    "cotton": "cotone", "coton": "cotone", "baumwolle": "cotone",
    "cashmere": "cashmere", "cachemire": "cashmere", "kaschmir": "cashmere",
    "viscose": "viscosa", "viskose": "viscosa",
    "mohair": "mohair", "alpaca": "alpaca", "alpaga": "alpaca",
}

# CATEGORIE MULTILINGUA (IT / EN / DE / FR / ES / PT) -- ampliata per coprire
# molti piu' tipi di capo e ridurre i casi di categoria non rilevata, che in
# precedenza causavano un fallback pericoloso ("dress") nella ricerca Vestiaire.
CATEGORIA_KEYWORDS = {
    "abito": ["abito", "vestito", "kleid", "dress", "robe", "vestido"],
    "blusa": ["blusa", "camicetta", "bluse", "blouse", "chemisier"],
    "camicia": ["camicia", "hemd", "shirt", "chemise", "camisa", "camisola"],
    "maglia": ["maglia", "maglione", "pullover", "sweater", "pull", "jumper", "jersey", "suéter", "trui", "strick"],
    "t-shirt": ["t-shirt", "tshirt", "t shirt", "maglietta", "camiseta", "playera"],
    "canotta": ["canotta", "canottiera", "top", "tank top", "canotte", "débardeur", "tirantes"],
    "felpa": ["felpa", "hoodie", "sweatshirt", "sudadera", "kapuzenpulli"],
    "gonna": ["gonna", "rock", "skirt", "jupe", "falda", "saia"],
    "pantaloni": ["pantaloni", "pantalone", "hose", "trousers", "pants", "pantalon", "pantalón", "calças"],
    "jeans": ["jeans", "denim", "vaqueros", "vaquero"],
    "giacca": ["giacca", "jacke", "jacket", "veste", "chaqueta", "casaco"],
    "cappotto": ["cappotto", "mantel", "coat", "manteau", "abrigo", "casaco longo"],
    "borsa": ["borsa", "tasche", "bag", "sac", "bolso", "bolsa"],
    "scarpe": ["scarpe", "schuhe", "shoes", "chaussures", "zapatos", "sapatos"],
    "polo": ["polo"],
    "costume": ["costume", "bikini", "swimsuit", "maillot", "bañador"],
    "intimo": ["intimo", "underwear", "lingerie", "ropa interior"],
    "sciarpa": ["sciarpa", "scarf", "echarpe", "bufanda"],
    "cintura": ["cintura", "belt", "ceinture", "cinturón"],
    "cappello": ["cappello", "hat", "chapeau", "sombrero", "cap", "berretto"],
    "occhiali": ["occhiali", "gafas", "lunettes", "glasses", "brille", "monturas", "montatura"],
    "tuta": ["tuta", "combinaison", "combishort", "jumpsuit", "playsuit", "overall", "salopette"],
}

# Termine inglese "canonico" per ogni categoria, usato per le query eBay/
# Vestiaire (dove i titoli sono in stragrande maggioranza in inglese anche
# su siti localizzati IT/DE/FR). Cercare in italiano ("canotta") su questi
# marketplace produce spesso zero match sul termine di categoria, facendo
# collassare la query a "solo brand" e restituendo risultati fuori tema.
CATEGORIA_TERMINE_EN = {
    "abito": "dress",
    "blusa": "blouse",
    "camicia": "shirt",
    "maglia": "sweater",
    "t-shirt": "t-shirt",
    "canotta": "tank top",
    "felpa": "hoodie",
    "gonna": "skirt",
    "pantaloni": "trousers",
    "jeans": "jeans",
    "giacca": "jacket",
    "cappotto": "coat",
    "borsa": "bag",
    "scarpe": "shoes",
    "polo": "polo",
    "costume": "swimsuit",
    "intimo": "underwear",
    "sciarpa": "scarf",
    "cintura": "belt",
    "cappello": "hat",
    "occhiali": "glasses",
    "tuta": "jumpsuit",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vinted_flip_bot")


def scegli_materiale_per_ricerca(material_value_raw):
    if not material_value_raw:
        return None
    testo_lower = material_value_raw.lower()
    materiali_annuncio = [m.strip() for m in testo_lower.split(",")]

    for materiale_prioritario in MATERIALI_PREGIATI_PRIORITA:
        if any(materiale_prioritario in elemento for elemento in materiali_annuncio):
            return materiale_prioritario

    for termine_straniero, termine_it in MATERIALI_TRADUZIONI.items():
        if re.search(r'\b' + re.escape(termine_straniero) + r'\b', testo_lower):
            return termine_it

    return None


def estrai_categoria_da_titolo(titolo):
    """Trova la categoria del capo cercando tutte le keyword multilingua nel
    titolo, e sceglie quella con il match PIÙ LUNGO/specifico -- non la
    prima trovata nell'ordine del dizionario. Necessario perché altrimenti
    keyword generiche possono "vincere" per errore su keyword più
    specifiche che le contengono come sottostringa: es. "shirt" (categoria
    camicia) è una sottostringa di "t-shirt" (categoria t-shirt), quindi
    con un semplice "primo match" un titolo come "T shirt uomo" veniva
    categorizzato come camicia invece che t-shirt, portando a comp di
    camicie eleganti al posto di magliette basic -- due fasce di prezzo
    completamente diverse."""
    if not titolo:
        return None
    titolo_lower = titolo.lower()
    migliore_categoria = None
    migliore_lunghezza = 0
    for categoria_it, parole_chiave in CATEGORIA_KEYWORDS.items():
        for parola in parole_chiave:
            if parola in titolo_lower and len(parola) > migliore_lunghezza:
                migliore_categoria = categoria_it
                migliore_lunghezza = len(parola)
    return migliore_categoria


# ---------------------------------------------------------------------------
# FILTRO PRE-GEMINI
# ---------------------------------------------------------------------------

def check_skip_pre_gemini(listing_info):
    """Filtro veloce basato sul testo, eseguito dopo lo scraping ma PRIMA di API/foto."""
    titolo = (listing_info.get("title") or "").lower()
    descrizione = (listing_info.get("description") or "").lower()
    brand = (listing_info.get("brand") or "").lower()
    seller = (listing_info.get("seller_login") or "").lower()
    
    testo_completo = f"{titolo} {descrizione}"
    
    # 1. Blocklist venditori
    if seller and seller in VENDITORI_BLOCKLIST:
        return True, f"[VENDITORE IN BLOCKLIST] L'utente '{seller}' è nella blocklist."
        
    # 2. Categorie mai flippabili (lista minima -- volutamente corta, quelle
    # "teoriche" aggiunte in precedenza non si verificano mai in pratica)
    unflippable = [
        "calzini", "calze", "collant", "portachiavi", "profumi", "eau de parfum",
        "eau de toilette", "deodoranti", "cover per telefono", "ciondoli", "guinzagli",
        # calzini/calze/collant multilingua -- lo stesso bug di copertura
        # linguistica gia' visto altrove: l'italiano da solo lascia passare
        # titoli in altre lingue, sprecando foto+token fino all'occhio
        "socken", "strumpfhose", "strümpfe",
        "socks", "tights", "stockings", "pantyhose",
        "chaussettes", "collants", "bas",
        "calcetines", "medias",
        "meias",
        # occhiali/occhialeria (vista o sole), montature, lenti, astucci -- basso
        # ROI ricorrente e mercato saturo, escluso a monte su richiesta esplicita
        "occhiali", "montatura", "montature", "lenti da vista", "occhiale da sole",
        "occhiale da vista", "astuccio occhiali",
        "glasses", "eyewear", "sunglasses", "spectacles", "eyeglass frames",
        "brille", "brillengestell", "sonnenbrille",
        "lunettes", "monture de lunettes",
        "gafas", "monturas de gafas", "lentes de sol",
        "óculos", "armação de óculos",
        # Collab mass-market note per brand monitorati -- diluiscono il
        # valore, capi economici e molto diffusi rispetto al mainline.
        # "uniqlo" e "h&m" da soli sono termini rari in un annuncio di
        # moda di lusso, rischio di falso positivo basso.
        "uniqlo", "h&m",
        "missoni for target", "missoni x target",
    ]
    for kw in unflippable:
    if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
        return True, f"[CATEGORIA GENERICA NON FLIPPABILE] Rilevata keyword: {kw}"

    # 2b. Danno grave dichiarato esplicitamente dal venditore, multilingua
    # (IT/EN/DE/FR/ES/PT -- stessa logica delle categorie: il tracker Vinted
    # intercetta annunci in tutta Europa). Usa \b per evitare falsi positivi
    # su sottostringhe (es. "roto" dentro un'altra parola).
    DANNO_GRAVE_KEYWORDS = [
        # IT
        "rotto", "rotta", "strappato", "strappata", "bucato", "bucata",
        "danneggiato", "danneggiata", "da riparare", "per ricambio", "per pezzi",
        "rovinato", "rovinata", "da buttare", "irreparabile",
        # EN
        "broken", "torn", "ripped", "damaged", "for repair", "for parts",
        "beyond repair", "unusable", "ruined",
        # DE
        "kaputt", "zerrissen", "beschädigt", "defekt", "unbrauchbar", "irreparabel",
        # FR
        "cassé", "cassée", "déchiré", "déchirée", "endommagé", "endommagée",
        "abîmé", "abîmée", "à réparer", "pour pièces", "irréparable", "troué", "trouée",
        # ES
        "roto", "rota", "rasgado", "rasgada", "dañado", "dañada",
        "para reparar", "para piezas", "irreparable",
        # PT
        "quebrado", "quebrada", "rasgado", "danificado", "danificada",
        "para reparo", "irreparável",
    ]
    for kw in DANNO_GRAVE_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[DANNO GRAVE DICHIARATO NEL TESTO] Rilevata keyword: '{kw}' -- non flippabile per regola su danni strutturali."

    # 2c. Non originalità dichiarata dal venditore stesso, multilingua
    NON_ORIGINALE_KEYWORDS = [
        # IT
        "non originale", "non è originale", "non e' originale", "ispirato a",
        "replica", "imitazione", "copia non originale",
        # EN
        "not authentic", "not original", "inspired by", "knockoff",
        # DE
        "nicht original", "inspiriert von", "nachahmung", "fälschung",
        # FR
        "non authentique", "pas authentique", "inspiré de", "inspirée de",
        "réplique", "contrefaçon",
        # ES
        "no original", "no es original", "inspirado en", "imitación",
        # PT
        "não original", "inspirado em", "imitação",
    ]
    for kw in NON_ORIGINALE_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[NON ORIGINALE DICHIARATO] Rilevata keyword: '{kw}' -- venditore dichiara che non è un pezzo originale."

    # 2d. Titoli con stringa di ricerca residua "gilet -blanc"
    if "gilet -blanc" in titolo:
        return True, "[TITOLO CON STRINGA DI RICERCA RESIDUA] Rilevato 'gilet -blanc' nel titolo."


    # 3. Regole specifiche per brand
    if "stella mccartney" in brand and "adidas" in testo_completo:
        return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Stella McCartney collab Adidas (basso valore)."
        
    if "yves saint laurent" in brand or "ysl" in brand or "saint laurent" in brand:
        camicie_kw = ["camicia", "camicie", "camicetta", "shirt", "chemise", "blusa", "camisa"]
        if any(kw in testo_completo for kw in camicie_kw):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] YSL camicie/bluse sature e scarso ROI."
        borse_moderne = ["saint laurent paris", "loulou", "sac de jour", "kate", "niki"]
        if any(kw in testo_completo for kw in borse_moderne):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] YSL borse moderne ad altissimo rischio fake."
            
    if "alexander mcqueen" in brand or "mcqueen" in brand:
        if re.search(r"\bmc_?q\b", testo_completo):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Alexander McQueen diffusion linea McQ."
            
    if "chloé" in brand or "chloe" in brand:
        if "see by chloé" in testo_completo or "see by chloe" in testo_completo:
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Chloé diffusion linea See by Chloé."
            
    return False, None


# ---------------------------------------------------------------------------
# PROMPT DI SISTEMA
# ---------------------------------------------------------------------------

GEMINI_OCCHI_SYSTEM_PROMPT = """
Sei l'analista visivo di un flipper professionista di lusso second-hand. Fai due cose in un solo passaggio: LEGIT CHECK visivo + valutazione finanziaria preliminare. Sei esperto di autenticazione su Vinted, Vestiaire, Grailed, eBay.

# REGOLA ASSOLUTA SUL PREZZO E VENDITORE
Il prezzo NON e' mai un indicatore di autenticita'. Un Brunello Cucinelli a 8€ con etichette coerenti e' un'opportunita' straordinaria, non un fake. Non citare mai il prezzo nel legit check.

# COME VALUTARE IL VENDITORE (non solo dal numero di recensioni)
Un privato con 0-30 recensioni che vende fast-fashion e ha sviste nel titolo è la "zona d'oro" più chiara. MA un numero alto di recensioni (es. 200, 500+) NON significa automaticamente "privato affidabile che svuota l'armadio" — potrebbe essere un rivenditore esperto che conosce perfettamente il valore dei suoi capi e prezza di conseguenza (meno probabile un vero affare). Il segnale decisivo NON è il conteggio recensioni da solo, ma COSA il venditore vende: se nel campo "Primi articoli in vendita" (quando disponibile) compaiono brand fast-fashion o generici misti a questo capo di lusso, è un forte segnale di privato genuino con guardaroba eterogeneo, anche con centinaia di recensioni accumulate negli anni. Se invece "Primi articoli in vendita" mostra solo brand di lusso/designer, è più probabile un rivenditore esperto — non significa automaticamente "prezzo non conveniente", ma alza la cautela sul fatto che il prezzo sia già "corretto" e non un errore di valutazione. Se il campo "Primi articoli in vendita" è presente nei dati, DEVI citarlo esplicitamente nell'Analisi dell'analista per giustificare il tuo giudizio sul venditore — non limitarti a dedurlo dal solo numero di recensioni. Ignore link a social nella bio (normali) o icone di scraping confuse per capi.

# ATTENZIONE AL BIAS "PREZZO TROPPO BASSO = DEVE ESSERE FALSO"
Caso reale già osservato: un capo Dries Van Noten autentico offerto a €5,95 è stato erroneamente giudicato "falso palese, Confidenza Alta" con motivazioni (font "grossolano", dettagli "generici") che un controllo indipendente ha smentito — le etichette erano in realtà coerenti col brand. Il prezzo basso aveva influenzato il giudizio nonostante l'istruzione esplicita di ignorarlo. Prima di scrivere "Probabilmente falso" con "Confidenza: Alta", fai una verifica interna: la stessa foto, con lo stesso identico dettaglio di etichetta/cucitura/font, ti sembrerebbe ugualmente sospetta se il prezzo fosse €200 invece di €6? Se la risposta è "forse no", il tuo giudizio è contaminato dal prezzo — declassa a "Sospetto, servono altre foto" con Confidenza Media, non "Probabilmente falso" con Confidenza Alta. Riserva "Probabilmente falso" + "Confidenza Alta" SOLO a discrepanze concrete, specifiche e descrivibili con precisione (non genériche tipo "font grossolano" senza specificare in cosa esattamente il font differisce dall'originale).

# LEGIT CHECK — COSA ANALIZZARE NELLE FOTO
1. **Etichetta brand** (collo/interno): font, proporzioni, materiale, cucitura.
2. **Wash tag / care label**: paese produzione, codice prodotto.
3. **Etichetta taglia**: stile ed epoca.
4. **Ricami/loghi/cuciture**: proporzioni, regolarità.
5. **Zip e hardware**.

# VERDETTO LEGIT CHECK (basato SOLO sulle foto)
- "Probabilmente autentico" — prove forti (main label + wash tag ok)
- "Sospetto, servono altre foto" — alcune prove presenti ma mancano elementi chiave
- "Probabilmente falso" — discrepanze evidenti
- "Non verificabile" — zero etichette visibili

# OBBLIGO DI MOTIVAZIONE ESPLICITA SU "PROBABILMENTE FALSO"
Se il verdetto è "Probabilmente falso", la sezione **Analisi visiva** DEVE specificare ESATTAMENTE quale discrepanza ha portato a questa conclusione — non basta scrivere "falso" o "discrepanze evidenti" senza dettaglio. Indica sempre COSA è sbagliato: font dell'etichetta non corretto (e come), proporzioni del logo errate, cuciture irregolari/di bassa qualità, materiale che non corrisponde a quanto dichiarato, wash tag con codice/paese di produzione incoerente, hardware (zip/bottoni) di qualità sbagliata, ecc. Questo motivo arriva direttamente all'utente su Telegram anche quando il cervello non viene consultato (skip automatico) — se non lo scrivi qui, l'utente non saprà mai perché è stato scartato.

# MAINLINE VS DIFFUSION — DISTINZIONE CRITICA PER IL MARGINE
Distingui SEMPRE le linee/ere per i brand, è un fattore critico per il valore. Specifica sempre l'epoca/linea in base alle etichette.

**HELMUT LANG:**
- ✅ Era Lang (1986-2005) → Archivio, valore alto.
- ❌ Era Link Theory (dal 2006) → Commerciale, basso valore.

**MAISON MARGIELA:**
- ✅ Linee 1, 10, 0, 22 → Valore alto.
- ⚠️ Linea 6 (MM6) → Diffusion, valore minore.

**YVES SAINT LAURENT (YSL):**
- ✅ "Yves Saint Laurent" / "YSL" vintage (pre-2012) → valore elevato, ma SOLO su tailoring (blazer, cappotti, abiti strutturati).
- ❌ Camicie e bluse YSL vintage → mercato saturo, ROI scarso.
- ❌ Borse moderne ("Saint Laurent Paris", "Loulou", "Sac de Jour", "Kate", "Niki") → rischio fake altissimo, esclusi a prescindere.

**ALEXANDER MCQUEEN:**
- ✅ "Alexander McQueen" mainline → valore.
- ❌ "McQ" → diffusion line, vale una frazione, non listare prezzi da mainline.

**CHLOÉ:**
- ✅ "Chloé" mainline → valore.
- ❌ "See by Chloé" → diffusion line satura.

**STELLA MCCARTNEY:**
- ✅ Mainline → valore.
- ❌ Collaborazioni "adidas" / activewear → basso valore.

**JUNYA WATANABE / UNDERCOVER / THOM BROWNE / ALAÏA:**
- ✅ Brand mono-linea, valore costante, rischio fake storicamente basso. Valuta a pieno prezzo.

**ALTRI BRAND:**
- MOSCHINO: ✅ Couture/Mainline | ❌ Love Moschino
- VERSACE: ✅ Mainline | ❌ Versace Jeans Couture / Versus
- MISSONI: ✅ Pattern colorati | ⚠️ M Missoni (abiti ok, basics no) | ❌ Missoni Sport
- ARMANI: ✅ Giorgio / Collezioni | ❌ Emporio / Exchange
- MAX MARA: ✅ Mainline | ⚠️ Sottolinee (Weekend, Studio) valgono solo se iconici/materiali pregiati

# DIFETTI MINORI VS STRUTTURALI
Difetti minori (macchie lavabili, pilling) riducono il prezzo e spostano la decisione a TRATTA o NON COMPRARE se il capo è costoso, ma sono accettabili sotto €15.
Difetti strutturali (buchi, strappi gravi, tessuto lacerato) = NON COMPRARE sempre, invendibili.

# OUTPUT — ottimizzato per lettura rapida da mobile. Il verdetto va SEMPRE in cima.

**Analisi visiva** (3-4 righe max): cosa vedi, etichette trascritte alla lettera, condizione.
⚠️ **REGOLA CRITICA — NON INVENTARE ETICHETTE**: trascrivi SOLO ciò che è visibile.

## Verdetto
[EMOJI] **[DECISIONE]** · [urgenza]

💰 €[acquisto pieno] → €[vendita probabile] → **€[margine netto] (ROI [X]%)**
🏷️ Legit: [una riga, max 15 parole]
🕐 ~[Z] giorni · Deal [X]/10 · Rischio fake: [B/M/A/MA] · Confidenza: [B]

---
📨 **Messaggio da inviare:**
"[testo pronto, copiabile, con offerta se TRATTA]"

---
❓ **Da chiedere**: [max 2 domande brevi]
""".strip()

GEMINI_CERVELLO_SYSTEM_PROMPT = """
Sei il valutatore finanziario di un flipper professionista di lusso second-hand. Ricevi l'analisi visiva e i dati di mercato.

# REGOLA SUL PREZZO E VENDITORE
Prezzo basso = vantaggio. Guarda il venditore: privato sprovveduto (fast fashion in armadio) conferma l'affare. Reseller con invenduto richiede più cautela sull'urgenza. Ignora errori di battitura nel titolo, sono segni di privato genuino.

Il NUMERO di recensioni da solo NON determina se un venditore è un "privato sprovveduto" o un rivenditore esperto — un venditore con centinaia di recensioni (es. 500+) può comunque essere un privato che vende il proprio guardaroba da anni, tanto quanto un rivenditore professionale. Il segnale decisivo è COSA vende: se il campo "Primi articoli in vendita" è presente nei dati venditore, DEVI citarlo esplicitamente nell'Analisi dell'analista per giustificare il tuo giudizio (es. "il venditore ha anche H&M/Zara in vendita, coerente con un guardaroba privato eterogeneo" oppure "il venditore vende solo brand di lusso, più cauto sul fatto che il prezzo sia già corretto"). Non dedurre "profilo affidabile/privato" dal solo rating alto senza guardare cosa vende, se quel dato è disponibile.

# NOTE SU LINEE E ERE (CRITICO PER I PREZZI)
- **YSL:** Vale solo il vintage pre-2012 e solo per capi tailoring (blazer, cappotti, abiti). Le camicie sono sature. Borse moderne (Loulou, Sac de Jour) sono rischio fake altissimo.
- **Alexander McQueen vs McQ:** McQ vale una frazione della mainline. Non confonderle nei comp.
- **Chloé vs See by Chloé:** See by Chloé è diffusion, ROI molto più basso.
- **Stella McCartney:** La mainline ha valore, la collab Adidas no.
- **Junya Watanabe, Undercover, Thom Browne, Alaïa:** Sono mono-linea, valore costante e alto, rischio fake generalmente basso.
- **Helmut Lang:** Solo era Lang (1986-2005) ha valore archivio. Era Link Theory (dal 2006) è commerciale, basso valore.
- **Maison Margiela:** Linee 1, 10, 0, 22 valgono. MM6 (linea 6) è diffusion, valore molto minore — non confondere nei comp.
- **Missoni:** Pattern colorati zig-zag hanno valore. M Missoni ok solo su abiti strutturati, non basics. Missoni Sport è diffusion, basso valore.
- **Vivienne Westwood:** "Gold Label" = alta sartoria/couture, valore molto alto. "Anglomania" è tecnicamente una linea diffusion MA NON va trattata come "economica" — è una linea riconosciuta e molto ricercata dai collezionisti del brand. Comp reali (The RealReal, eBay) mostrano top Anglomania anche basic tra €120-250+ usati; pezzi metallici, corsetteria o comunque "statement" (non semplici t-shirt/basic) valgono ancora di più — non stimare mai un top Anglomania metallico/decorato sotto questa fascia senza comp specifici che lo giustifichino. "Red Label"/linee più commerciali (es. collab con retailer) restano invece più economiche, quelle sì trattabili con cautela sui prezzi.
- **Max Mara:** Solo mainline ha valore pieno. Sottolinee (Weekend, Studio, Sportmax) valgono solo se modello iconico o materiale pregiato (es. cammello, cashmere) — altrimenti ROI marginale.
- **Visvim, Kapital, 45RPM, Carol Christian Poell, Haider Ackermann, The Row, Boris Bidjan Saberi, sacai, Kiko Kostadinov:** Mono-linea o quasi, valore costante, rischio fake storicamente basso. Valuta a pieno prezzo.
- **Arc'teryx — Veilance vs mainline outdoor:** "Veilance" è la linea urban/minimal di fascia alta (etichetta specifica "VEILANCE", non solo "Arc'teryx"), con valore di rivendita molto superiore al mainline. Il mainline Arc'teryx outdoor/tecnico (giacche a vento, hardshell da montagna generiche) è molto riconosciuto e diffuso, con margine di flip molto più basso — non trattarlo come Veilance solo perché il brand è lo stesso. Controlla sempre l'etichetta specifica prima di stimare il valore: se non trovi la scritta "Veilance" da nessuna parte, tratta il capo come mainline, non come statement piece.
- **Yohji Yamamoto — mainline/diffusion vs Y-3:** "Yohji Yamamoto", "Y's", "S'yte", "Ground Y", "Wildside" sono la linea principale o diffusion di alta gamma del brand. **"Y-3" è tutt'altro**: è la collaborazione con Adidas, streetwear/sportswear di massa con volumi enormi e prezzi molto più bassi (spesso €15-60 anche sold). Non mescolare MAI i due mondi nei comp: se stai valutando un capo "Yohji Yamamoto" (non Y-3), scarta ogni comp che contiene "Y-3" o "Adidas" nel titolo, anche se cita "Yohji Yamamoto" — altrimenti la stima crolla artificialmente.

# GESTIONE TRASPARENTE DELLE COLLABORAZIONI NEI COMP
Se tra i comp raccolti compaiono collaborazioni con altri brand (es. "Fred Perry x Raf Simons", "Calvin Klein x Raf Simons", "Y-3", "See by Chloé"), NON includerle nel calcolo del prezzo mainline senza dirlo. Hai due opzioni: (1) escludile esplicitamente e dillo nell'analisi ("escludo i comp Fred Perry x Raf Simons perché sono una collab a prezzo diverso"), oppure (2) se il capo in analisi è esso stesso una di queste collab, usa SOLO comp della stessa collab, mai comp mainline. Non selezionare silenziosamente solo i comp più favorevoli senza spiegare quali hai scartato e perché.
- **ATTENZIONE — due linee diffusion Gaultier facilmente confondibili, NON applicare la stessa regola a entrambe. Controlla SEMPRE il testo esatto dell'etichetta prima di decidere quale regola usare:**
  - **"JEAN'S PAUL GAULTIER"** (etichetta con questo testo esatto, logo con apostrofo dopo "Jean" e S stilizzata) — T-shirt e maglie manica corta o lunga in jersey semplice: tetto di prezzo di rivendita realistico **€30**. Non stimare vendite sopra questa soglia per questi capi, indipendentemente da stampe o loghi.
  - **"JPG.JEAN'S"** o **"JPG JEAN'S"** (etichetta diversa, spesso con dicitura "Collection N°..." stampata, tipica di capi in mesh/rete con stampe elaborate stile Y2K) — linea DIVERSA dalla precedente, il tetto €30 NON si applica. Valuta questi capi sui comp reali trovati (ricerca web), senza applicare la cap della linea "Jean's Paul Gaultier".
  - Se non riesci a leggere il testo esatto dell'etichetta dalle foto/analisi dell'occhio, NON assumere quale delle due linee sia — trattalo come incertezza (abbassa la Confidenza) invece di applicare automaticamente il tetto €30.
  - Il tailoring mainline Jean Paul Gaultier (giacche, cappotti) segue regole diverse da entrambe le linee diffusion sopra e può valere molto di più.

# NOTE SU DOMANDA E LIQUIDITÀ PER SEGMENTO (usa per calibrare Deal, giorni di vendita e messaggio)
- Archivio eclettico (Missoni, JPG, Pucci, Westwood, Mugler, Montana, Marni, Courrèges, Miu Miu): target 25-45, vendita più lenta ma prezzo alto per pezzi iconici riconoscibili; premia sempre provenienza/collezione nel messaggio di vendita.
- Quiet luxury 90s (Helmut Lang, Jil Sander, Margiela, Bottega, Max Mara): target 28-45 stile-consapevole, premia capi da collezione/decade specifica nel titolo; coats iconici (es. Max Mara 101801) molto più liquidi dei basic.
- Avantgarde/designer riconosciuti (Rick Owens, Yohji, Dries, Ann Demeulemeester, Raf Simons, Loewe, Cucinelli, YSL, Chloé, Stella McCartney, Totême): community fashion-insider, alta disponibilità a pagare premium per pezzi con provenienza documentata.
- Giapponese artigianale + designer esperto (Visvim, Kapital, CCP, Haider, The Row, Alaïa, BBS, Sacai, Kiko Kostadinov, Junya, Thom Browne, McQueen, Undercover): community verticale molto informata, taglie piccole (46-48 IT/S-M) più richieste e liquide, vendita rapida se il pezzo è riconosciuto come "grail".

# RICERCA WEB OBBLIGATORIA
Se hai dubbi sui comp pre-raccolti (assenti, insufficienti, o palesemente fuori tema rispetto alla categoria del capo), chiama la funzione cerca_comp_prezzo con una query mirata PRIMA di rispondere. Gerarchia preferita per i comp: eBay SOLD > Vinted > Vestiaire.

# VERIFICA ATTIVA DI CODICI E CLAIM SPECIFICI (non fidarti passivamente)
Se l'analisi visiva cita un codice prodotto, una dicitura rara ("prototipo", "campionario", "edizione limitata", stagione specifica) o qualunque dettaglio molto specifico usato per giustificare un'autenticità o un valore superiore alla media, NON accettarlo passivamente come prova e NON limitarti a segnalare il dubbio nel testo finale. Usa attivamente cerca_comp_prezzo per verificare che quel codice/claim esista davvero e sia plausibile per il brand (es. cerca il codice stesso, o la dicitura esatta unita al brand). Se la verifica conferma, procedi con confidenza normale. Se la verifica non trova riscontro o è ambigua, tratta il dettaglio come NON confermato: abbassa la Confidenza e non usarlo come giustificazione principale del margine o dell'urgenza.

# NON FIDARTI CIECAMENTE DI UN VERDETTO "FALSO" DELL'OCCHIO
La "Confidenza" che l'occhio dichiara di sé stesso NON è un segnale affidabile — è già capitato che un capo venisse giudicato "falso palese, Confidenza Alta" con dettagli inventati (es. "font grossolano" quando il font era in realtà corretto), specialmente su annunci a prezzo molto basso, dove il modello sembra sviluppare un bias "troppo economico per essere vero" che lo porta a costruire retroattivamente motivazioni negative non supportate dalle foto reali. Se l'occhio conclude "Probabilmente falso", NON limitarti a riportarlo: valuta se i dettagli citati (font, cuciture, materiale) sono davvero specifici e verificabili o generici/sospetti come costruiti a posteriori. Se il prezzo è molto basso E i dettagli del "falso" sembrano vaghi, usa cerca_comp_prezzo per cercare esempi autentici dello stesso stile/pattern/dettaglio (es. "Dries Van Noten zip asimmetrica perline blazer") prima di confermare NON COMPRARE per sospetto di falso — un margine enorme (capo di valore comprato a pochi euro) merita una verifica in più prima di scartarlo, non una fiducia cieca nel primo giudizio.

# MARGINE E SOGLIE — CALCOLO A DUE GAMBE
Acquisto pieno = prezzo + protezione (~5%+€0,70) + spedizione (IT 2,50€, EU 4,50-6€).
Incasso reale = prezzo listing stimato × 0,80 (sconto 20%).
Margine netto = incasso reale − acquisto pieno.
Soglia minima per COMPRA: €20 netti E ROI 100%+.

# LIMITE MASSIMO DI SCONTO IN TRATTATIVA (regola rigida)
Quando proponi un "Obiettivo trattativa", puoi chiedere al massimo il 40% di sconto sul PREZZO DEL PRODOTTO (non sul totale con spedizione), e solo se il venditore accetta — la spedizione non è mai scontabile. Esempio: prodotto €10 + spedizione €5 = totale €15. Sconto massimo: 40% di €10 = €4, quindi l'offerta minima proponibile è €6 (prodotto) + €5 (spedizione) = €11 totale, mai meno.

# COERENZA DELL'INCASSO TRA VERDETTO PRINCIPALE E TRATTATIVA (errore frequente)
L'incasso reale (prezzo di vendita stimato × 0,80) NON cambia tra lo scenario "acquisto a prezzo pieno" e lo scenario "acquisto in trattativa" — cambia SOLO il costo di acquisto, mai la stima di vendita. Se nel verdetto principale hai scritto "€X → €Y (incasso) → €Z", l'Obiettivo trattativa DEVE usare lo STESSO €Y, mostrato esplicitamente nello stesso formato "€[costo trattato] → €Y (incasso, IDENTICO al verdetto principale) → €[margine] (ROI)". Non scrivere MAI un margine di trattativa che implica un incasso diverso da quello già dichiarato sopra — è un errore di calcolo silenzioso che rende il numero finale inaffidabile. Prima di scrivere il margine dell'obiettivo trattativa, verifica: margine = incasso_principale − costo_trattato. Se il numero che stai per scrivere non torna con questa formula usando lo STESSO incasso di sopra, hai sbagliato — ricalcola.

# TRATTA SOLO SE L'OBIETTIVO DI TRATTATIVA FUNZIONA DAVVERO (regola critica, spesso violata)
Non proporre MAI TRATTA se il tuo stesso "Obiettivo trattativa" — calcolato al massimo sconto consentito (40% sul prodotto) — non raggiunge margine ≥€20 E ROI ≥100%. Prima di scrivere TRATTA, calcola il margine e il ROI dell'obiettivo di trattativa che stai per proporre: se anche a sconto massimo il margine resta <€20 o il ROI <100%, non ha senso negoziare — la decisione corretta è NON COMPRARE, non TRATTA con un obiettivo che comunque non risolve il problema. Un "Obiettivo trattativa" con ROI 40-70% è un errore: la trattativa deve portare l'affare SOPRA soglia, non semplicemente più vicino.

# SOGLIA SEPARATA PER L'URGENZA (non confondere con la soglia minima per COMPRA)
"Alta urgenza" NON è il default per ogni COMPRA che supera la soglia minima — è riservata ai casi con margine di sicurezza reale, non a quelli borderline. Usa "Alta urgenza" SOLO se margine netto ≥ €30 E ROI ≥ 150%. Se il margine/ROI supera la soglia minima (€20/100%) ma resta sotto questi valori, la decisione resta COMPRA ma l'urgenza deve essere "Media" o "Bassa", mai "Alta". Inoltre, non giustificare "Alta urgenza" con stime generiche di valore del brand ("il capo vale tipicamente tra X e Y") se la ricerca web non ha restituito comp specifici e verificabili: in quel caso l'urgenza non può essere Alta, indipendentemente dal margine calcolato.

# TAGLIA COME FATTORE DI LIQUIDITÀ (non ignorarla mai se nota)
Se la taglia del capo è nota (dai dati annuncio o dalle foto), FATTORIZZALA sempre nella stima di vendita, nel Deal score e nei giorni stimati di vendita — non limitarti a valutare il brand. Taglie standard/centrali (donna IT 40-44, uomo IT 48-52) hanno il bacino di acquirenti più ampio e liquidità migliore. Taglie estreme (donna sotto IT 38 o sopra IT 46, uomo sotto 46 o sopra 54) hanno domanda strutturalmente più bassa: bacino di acquirenti ridotto, tempi di vendita più lunghi, spesso prezzo di vendita finale inferiore rispetto alla stessa taglia standard dello stesso capo. In questi casi abbassa il Deal score, allunga la stima giorni di vendita, e menzlonalo esplicitamente nell'Analisi dell'analista. Se la taglia non è nota, dillo esplicitamente come limite dell'analisi invece di ignorare il tema.

# OBBLIGO DI MOTIVAZIONE ESPLICITA SU RISCHIO FAKE ALTO/FALSO
Se scrivi "Rischio fake: Alto" o menzioni "falso"/"contraffatto"/"non autentico" nella riga Legit, DEVI specificare il motivo esatto (font etichetta, cuciture, materiale, wash tag incoerente, proporzioni logo, ecc.) — riprendi il dettaglio già fornito dall'occhio nella sua analisi visiva, non limitarti a ripetere "rischio alto" senza spiegazione. L'utente deve sempre sapere COSA lo ha insospettito.

# ANCORAGGIO AI COMP REALI (non al prezzo retail scontato)
La stima di vendita DEVE ancorarsi ai comp di VENDUTO/ASK reali trovati (pre-raccolti o dalla ricerca), non al prezzo retail originale scontato di una percentuale arbitraria. Se i comp reali mostrano un range (es. venduti €35-55, ask €40-75), la tua stima di vendita non può superare il valore più alto dei comp reali raccolti, anche se il prezzo retail del capo nuovo è molto più alto. Se non hai comp specifici per quel modello ma solo per il brand in generale, usa il valore mediano-basso della fascia trovata, mai il valore più ottimistico. Diffida di te stesso se la tua stima di vendita finale supera nettamente tutti i prezzi "venduto" effettivamente citati nei dati raccolti: in quel caso stai probabilmente ragionando sul retail, non sul second-hand — correggi verso il basso.

# SOLD VS ASK — GERARCHIA OBBLIGATORIA DEI DATI
I dati che ricevi sono etichettati esplicitamente: "ASK" (Vestiaire, Vinted — annunci attivi, NON necessariamente venduti, spesso sovrastimati o mai venduti a quel prezzo) vs "SOLD" (eBay — venduti confermati, il dato più vicino alla realtà). Regole:
1. Se hai comp SOLD (eBay), usali come base primaria per la stima di vendita. I comp ASK servono solo a confermare che il prezzo SOLD sia plausibile, mai a sostituirlo.
2. Se hai SOLO comp ASK (nessun SOLD disponibile o pertinente), applica uno sconto del 20-30% rispetto al valore ASK medio prima di usarlo come stima di vendita — gli annunci attivi restano spesso invenduti proprio perché il prezzo chiesto è troppo alto.
3. NON citare mai un prezzo ASK come se fosse un prezzo di vendita realistico senza applicare questo sconto.

# CITA I COMP SPECIFICI USATI (non stime generiche a memoria, MAI inventare range)
Nella sezione "Analisi dell'analista", cita ALMENO 2 prezzi ESATTI copiati verbatim dai dati SOLD/ASK ricevuti (es. "eBay SOLD: 'Missoni Long Dress Chevron Pattern Size 40' venduto a €160,25"), non un range parafrasato a memoria. Se scrivi un range tipo "tra €X e €Y", quei due estremi devono corrispondere a due prezzi realmente presenti nei dati ricevuti, non a una tua stima approssimativa del "prezzo tipico" del brand. Prima di scrivere qualsiasi range di prezzo, controlla che entrambi gli estremi siano effettivamente citabili dai dati che hai ricevuto — se non lo sono, non li hai calcolati correttamente e devi ricontrollare i dati invece di scrivere un numero plausibile ma non verificato.

# DISTINGUI VARIANTI QUANDO I COMP HANNO RANGE AMPIO
Se i comp per lo stesso brand mostrano un range di prezzo molto ampio (es. da €25 a €200), è quasi sempre perché il set contiene sia capi basic (tinta unita, jersey semplice) sia capi lavorati/decorati/stampati (molto più costosi). Identifica lo stile del capo in analisi dalla descrizione/foto e usa SOLO i comp dello stesso tipo di capo, non la media di tutto il range.

# FORMATO RIGIDO — NON DEVIARE
Usa ESCLUSIVAMENTE queste 4 emoji per il verdetto: 🟢 (COMPRA) 🟡 (TRATTA) 🔴 (NON COMPRARE) 🔵 (CHIEDI ALTRE FOTO). NON usare mai ✅ ⚠️ ❌ nel tuo verdetto finale: sono riservate al legit check dell'occhio, non al tuo output. La parola urgenza deve essere ESATTAMENTE "Alta urgenza", "Media urgenza" o "Bassa urgenza" — mai sinonimi come "priorità", "importanza" o simili.

# VERIFICA FINALE OBBLIGATORIA
Verifica che i calcoli (Margine e ROI) supportino la tua Decisione. Se margine <20€ o ROI <100%, DEVI usare TRATTA o NON COMPRARE. Se scegli TRATTA, verifica che il margine/ROI del TUO STESSO "Obiettivo trattativa" raggiunga ≥€20/≥100% — se non ci arriva nemmeno lì, cambia la decisione in NON COMPRARE. Verifica anche che l'urgenza dichiarata rispetti la soglia separata sopra: se hai scritto "Alta urgenza" ma margine <€30 o ROI <150%, correggi in "Media urgenza". Verifica infine che la tua stima di vendita non superi il valore più alto tra i comp reali raccolti (regola di ancoraggio sopra), e che qualunque "Obiettivo trattativa" rispetti il limite massimo di sconto del 40% sul prezzo prodotto (mai sulla spedizione).

# OUTPUT — Verdetto in cima.

## Verdetto
[EMOJI] **[DECISIONE]** · [urgenza]

💰 €[acquisto pieno] → €[incasso reale = listing×0.80] → **€[margine netto] (ROI [X]%)**
🏷️ Legit: [max 15 parole, mai basato sul prezzo]
🕐 ~[Z] giorni · Deal [X]/10 · Rischio fake: [B/M/A/MA] · Confidenza: [A/M/B]

[Solo se TRATTA]
🤝 Obiettivo trattativa: €[costo totale trattato] → €[incasso — DEVE essere identico all'incasso del verdetto principale sopra] → €[margine netto] (ROI [X]%)

---
📨 **Messaggio da inviare:**
"[testo pronto]"

---
❓ **Da chiedere**: [max 2 domande]

---
🧠 **Analisi dell'analista:**
[3-5 righe. Spiega il ragionamento sui prezzi E commenta esplicitamente il profilo/guardaroba venditore.]
""".strip()


# ---------------------------------------------------------------------------
# TELEGRAM BOT API HELPERS
# ---------------------------------------------------------------------------

def telegram_send_message(chat_id, text):
    MAX_LEN = 3500
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_LEN:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    for i, chunk in enumerate(chunks, start=1):
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=20,
        )
        if not resp.ok:
            log.warning("sendMessage Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode", resp.status_code, resp.text[:300])
            requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )


def telegram_send_photo(chat_id, photo_bytes, caption=None):
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=30)


def telegram_send_media_group(chat_id, photos_bytes_list, caption=None):
    if not photos_bytes_list:
        return
    files = {}
    media = []
    for i, photo_bytes in enumerate(photos_bytes_list[:10]):
        key = f"photo{i}"
        files[key] = (f"photo{i}.jpg", photo_bytes, "image/jpeg")
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and caption:
            item["caption"] = caption[:1024]
        media.append(item)
    requests.post(
        f"{TELEGRAM_API}/sendMediaGroup",
        data={"chat_id": chat_id, "media": json.dumps(media)},
        files=files,
        timeout=60,
    )


def telegram_send_with_buttons(chat_id, text, url_annuncio, item_id=None):
    keyboard = {"inline_keyboard": [[
        {"text": "🔗 Apri su Vinted", "url": url_annuncio},
    ]]}
    if item_id:
        keyboard["inline_keyboard"].append([
            {"text": "💬 Scrivi venditore", "url": f"https://www.vinted.it/items/{item_id}"},
        ])
    resp = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": keyboard,
        },
        timeout=20,
    )
    if not resp.ok:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
                "reply_markup": keyboard,
            },
            timeout=20,
        )


# ---------------------------------------------------------------------------
# PARSING MESSAGGI E SCRAPING VINTED
# ---------------------------------------------------------------------------

URL_REGEX = re.compile(r"https?://(?:www\.)?vinted\.[a-z]+/items/\S+", re.IGNORECASE)
PRICE_REGEX = re.compile(r"Price\s*:\s*([\d.,]+)\s*EUR", re.IGNORECASE)
BRAND_REGEX = re.compile(r"Brand\s*:\s*(.+)", re.IGNORECASE)

def parse_vinted_tracker_message(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    for line in lines:
        if not line.lower().startswith(("price", "brand")) and "price" not in line.lower():
            cleaned = line.lstrip("📌 ").strip()
            if cleaned and title is None:
                title = cleaned
                break
    price_match = PRICE_REGEX.search(text)
    brand_match = BRAND_REGEX.search(text)
    return {
        "title": title or "Titolo non rilevato",
        "price": price_match.group(1) if price_match else None,
        "brand": brand_match.group(1).strip() if brand_match else None,
    }


def extract_url_from_text(text):
    match = URL_REGEX.search(text or "")
    return match.group(0) if match else None


VINTED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
IMAGE_DOWNLOAD_HEADERS = {
    "User-Agent": VINTED_HEADERS["User-Agent"],
    "Accept-Language": VINTED_HEADERS["Accept-Language"],
    "Referer": "https://www.vinted.it/",
    "Accept": "image/webp,image/avif,image/jpeg,image/png,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
}
_vinted_session = requests.Session()
_vinted_session.headers.update(VINTED_HEADERS)


def _vinted_get_con_retry(url, timeout=15, max_retries=3):
    """GET con retry per lo scraping Vinted. In precedenza un singolo timeout
    faceva fallire l'intero scraping (foto, descrizione, venditore tutti
    vuoti), costringendo il cervello a lavorare quasi alla cieca.

    Impone anche una pausa minima rispetto alla richiesta Vinted precedente
    (qualunque essa fosse): dopo ~13h di attività continua, Vinted ha
    iniziato a rispondere 403 Forbidden in modo ricorrente, probabile
    rate-limit per volume di richieste troppo fitte."""
    tempo_trascorso = time.time() - _vinted_timestamp_ultima_richiesta[0]
    if tempo_trascorso < PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI:
        time.sleep(PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI - tempo_trascorso)

    ultimo_errore = None
    for tentativo in range(1, max_retries + 1):
        try:
            _vinted_timestamp_ultima_richiesta[0] = time.time()
            resp = _vinted_session.get(url, headers=VINTED_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            ultimo_errore = e
            if tentativo < max_retries:
                # Su 403 (probabile rate-limit) attende piu' a lungo del
                # normale backoff, dando al blocco lato Vinted il tempo di
                # attenuarsi prima del prossimo tentativo.
                e_403 = "403" in str(e)
                attesa = (6.0 * tentativo) if e_403 else (1.5 * tentativo)
                time.sleep(attesa)
                continue
    log.warning("Scraping Vinted fallito dopo %d tentativi per %s: %s", max_retries, url, ultimo_errore)
    return None


def scrape_vinted_listing(url):
    result = {
        "photo_urls": [], "size": None, "condition": None, "description": None,
        "created_at": None, "age_days": None, "catalog_id": None,
        "material_raw": None, "material_per_ricerca": None, "color_raw": None,
        "seller_login": None, "seller_id": None,
        "seller_feedback_count": None, "seller_feedback_reputation": None,
        "seller_items_count": None, "seller_country": None,
        "seller_top_items": [],
        "seller_wardrobe_debug": "non tentato",
    }
    try:
        resp = _vinted_get_con_retry(url, timeout=15, max_retries=3)
        if resp is None:
            return result
        html = resp.text

        marker_venditore = re.search(r'data-testid="profile-username"', html)

        def _estrai_foto(html_sorgente):
            m1 = re.findall(
                r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/((?:f800|\d+x\d+))/'
                r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html_sorgente)
            m2 = re.findall(
                r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/(?:f800|\d+x\d+)/'
                r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html_sorgente)
            diz = {}
            for (photo_id, resolution), full_url in zip(m1, m2):
                if photo_id not in diz or resolution == "f800":
                    diz[photo_id] = full_url
            return diz

        foto_complete = _estrai_foto(html)
        if marker_venditore:
            foto_tagliate = _estrai_foto(html[:marker_venditore.start()])
            if 0 < len(foto_tagliate) and len(foto_complete) - len(foto_tagliate) <= 2:
                best_url_by_photo_id = foto_tagliate
            else:
                best_url_by_photo_id = foto_complete
        else:
            best_url_by_photo_id = foto_complete

        result["photo_urls"] = list(best_url_by_photo_id.values())[:MAX_GALLERY_PHOTOS]

        size_match = re.search(r'"size_title"\s*:\s*"([^"]+)"', html)
        if size_match:
            result["size"] = size_match.group(1)

        condition_match = re.search(r'itemprop="status"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
        if condition_match:
            result["condition"] = condition_match.group(1).strip()

        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
        if desc_match:
            try:
                result["description"] = desc_match.group(1).encode().decode("unicode_escape")
            except Exception:
                result["description"] = desc_match.group(1)

        # Tentativi multipli per la data di pubblicazione: il campo esatto
        # non è ancora stato confermato via ispezione HTML diretta (Vinted
        # potrebbe aver rinominato il campo o caricarlo via JS). Proviamo
        # diverse varianti note prima di arrenderci.
        created_match = re.search(r'"created_at_ts"\s*:\s*"([^"]+)"', html)
        if not created_match:
            created_match = re.search(r'"created_at"\s*:\s*"([^"]+)"', html)
        if not created_match:
            created_match = re.search(r'"createdAt"\s*:\s*"([^"]+)"', html)

        epoch_match = None
        if not created_match:
            epoch_match = re.search(r'"created_at_ts"\s*:\s*(\d{10,13})', html)
            if not epoch_match:
                epoch_match = re.search(r'"createdAtTs"\s*:\s*(\d{10,13})', html)

        if created_match:
            result["created_at"] = created_match.group(1)
            try:
                from datetime import datetime, timezone
                created_dt = datetime.fromisoformat(created_match.group(1))
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                result["age_days"] = round(age_days, 1)
            except Exception:
                log.warning("Impossibile calcolare l'eta' dell'annuncio (formato data inatteso: %s).", created_match.group(1))
        elif epoch_match:
            try:
                from datetime import datetime, timezone
                ts = int(epoch_match.group(1))
                if ts > 10**12:  # timestamp in millisecondi
                    ts = ts / 1000
                created_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                result["created_at"] = created_dt.isoformat()
                age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                result["age_days"] = round(age_days, 1)
            except Exception:
                log.warning("Impossibile interpretare il timestamp epoch trovato per la data di pubblicazione.")
        else:
            log.warning(
                "Data di pubblicazione non trovata con nessuno dei pattern noti (created_at_ts/created_at/createdAt) "
                "per %s -- Vinted potrebbe aver cambiato formato pagina, serve ispezione HTML manuale.",
                url,
            )

        catalog_matches = re.findall(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"', html)
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

        material_match = re.search(r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
        if material_match:
            result["material_raw"] = material_match.group(1).strip()
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(material_match.group(1).strip())

        if not result["material_per_ricerca"] and result.get("description"):
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(result["description"])

        color_match = re.search(r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
        if color_match:
            result["color_raw"] = color_match.group(1).strip()

        # ---- DATI VENDITORE E SELLER_LOGIN (con blocklist compatibility) ----
        seller_login_m = re.search(r'data-testid="profile-username"[^>]*>([^<]{2,40})<', html)
        if seller_login_m:
            result["seller_login"] = seller_login_m.group(1).strip()
        else:
            seller_login_m2 = re.search(r'"(?:user|seller)"\s*:\s*\{[^}]*"login"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html)
            if not seller_login_m2:
                seller_login_m2 = re.search(r'"(?:login|user_login)"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html)
            if seller_login_m2:
                result["seller_login"] = seller_login_m2.group(1)

        seller_id_m = re.search(r'href="/member/(\d+)"', html)
        if seller_id_m:
            result["seller_id"] = seller_id_m.group(1)
        else:
            seller_id_m2 = re.search(r'"user_id"\s*:\s*(\d+)', html)
            if seller_id_m2:
                result["seller_id"] = seller_id_m2.group(1)
            else:
                # Formato React Server Components scoperto in produzione:
                # \"seller_id\":49465070 -- chiave diversa da "user_id" E
                # valore numerico puro (non tra virgolette). Gestisce sia
                # la variante con virgolette escapate (\") sia quella normale.
                seller_id_m3 = re.search(r'\\?"seller_id\\?"\s*:\s*(\d+)', html)
                if seller_id_m3:
                    result["seller_id"] = seller_id_m3.group(1)

        rating_m = re.search(r'valutazione di\s+([\d.,]+)\s+su\s+5\s+stelle', html, re.IGNORECASE)
        if rating_m:
            try:
                result["seller_feedback_reputation"] = float(rating_m.group(1).replace(",", "."))
            except ValueError:
                pass
        else:
            feedback_rep_m2 = re.search(r'"feedback_reputation"\s*:\s*([\d.]+)', html)
            if feedback_rep_m2:
                try:
                    result["seller_feedback_reputation"] = float(feedback_rep_m2.group(1))
                except ValueError:
                    pass

        count_m = re.search(r'web_ui__Rating__label[^>]*>\s*<span[^>]*>\s*(\d+)\s*<', html)
        if count_m:
            result["seller_feedback_count"] = int(count_m.group(1))
        else:
            feedback_count_m2 = re.search(r'"feedback_count"\s*:\s*(\d+)', html)
            if feedback_count_m2:
                result["seller_feedback_count"] = int(feedback_count_m2.group(1))

        items_count_m = re.search(r'"items_count"\s*:\s*(\d+)', html)
        if items_count_m:
            result["seller_items_count"] = int(items_count_m.group(1))

        country_m = re.search(r'"country_title_local"\s*:\s*"([^"]{2,30})"', html)
        if country_m:
            result["seller_country"] = country_m.group(1)

        seller_id = result.get("seller_id")
        seller_login = result.get("seller_login")
        if seller_id or seller_login:
            profilo_url = (
                f"https://www.vinted.it/member/{seller_id}"
                if seller_id
                else f"https://www.vinted.it/member/{seller_login}"
            )
            try:
                # Prima usava un singolo tentativo con timeout 5s (troppo
                # aggressivo per una pagina pesante come il profilo, che
                # carica tutto il guardaroba del venditore) -- causava
                # fallimenti silenziosi quasi sistematici, per cui
                # "Primi articoli in vendita" non compariva quasi mai.
                resp_profilo = _vinted_get_con_retry(profilo_url, timeout=12, max_retries=2)
                if resp_profilo is not None and resp_profilo.ok:
                    html_profilo = resp_profilo.text
                    # SOLO questo pattern è verificato su HTML reale (schermate
                    # dell'utente): data-testid="other_user_items-N--description-
                    # title">Brand</p>. I fallback generici su "title":"..." che
                    # avevamo aggiunto si sono rivelati un problema serio: su un
                    # caso reale hanno estratto nomi di CATEGORIE del menu
                    # ("Cappe e poncho", "Montgomery", perfino un artefatto
                    # "$undefined" da un template JS rotto) invece degli
                    # articoli reali del venditore -- dato sbagliato ma
                    # plausibile, più pericoloso di nessun dato perché alimenta
                    # il giudizio sull'affidabilità del venditore con
                    # informazioni false. Meglio "non disponibile" onesto che
                    # un guardaroba inventato.
                    titoli = re.findall(
                        r'data-testid="other_user_items-\d+--description-title">([^<]+)<',
                        html_profilo
                    )

                    # Diagnostico mirato: se zero titoli, verifica se la
                    # stringa chiave "other_user_items" compare DA QUALCHE
                    # PARTE nella pagina, anche fuori dal pattern regex atteso
                    # -- distingue "markup presente ma in formato diverso" da
                    # "il contenuto non è proprio nella risposta" (probabile
                    # rendering lato client via JavaScript, non catturabile
                    # con una semplice richiesta HTTP senza esecuzione JS).
                    diagnostica_markup = ""
                    if not titoli:
                        idx = html_profilo.find("other_user_items")
                        if idx == -1:
                            diagnostica_markup = " [stringa 'other_user_items' assente dalla risposta HTTP grezza -- probabile rendering lato client via JS, non catturabile senza browser headless]"
                        else:
                            estratto = html_profilo[max(0, idx-50):idx+150].replace("\n", " ")
                            diagnostica_markup = f" [stringa presente, contesto: ...{estratto}...]"

                    ELEMENTI_UI_DA_SCARTARE = {
                        "vinted", "facebook", "instagram", "linkedin", "twitter", "x",
                        "tiktok", "app store", "google play", "logo", "logo di vinted",
                        "scarica l'app", "pinterest", "youtube", "whatsapp", "telegram",
                    }
                    titoli = [
                        t for t in titoli
                        if t.strip().lower() not in ELEMENTI_UI_DA_SCARTARE
                        and len(t.strip()) >= 4
                    ]

                    visti = set()
                    titoli_unici = []
                    for t in titoli:
                        t_clean = t.strip()
                        if t_clean.lower() not in visti and not t_clean.startswith("http"):
                            visti.add(t_clean.lower())
                            titoli_unici.append(t_clean)
                        if len(titoli_unici) >= 8:
                            break
                    result["seller_top_items"] = titoli_unici
                    if not titoli_unici:
                        result["seller_wardrobe_debug"] = f"pagina caricata (status {resp_profilo.status_code}, {len(html_profilo)} char) ma 0 titoli estratti.{diagnostica_markup}"
                        log.info("Scraping guardaroba venditore: pagina caricata ma nessun titolo estratto per %s", profilo_url)
                    else:
                        result["seller_wardrobe_debug"] = f"ok: {len(titoli_unici)} titoli trovati"
                else:
                    result["seller_wardrobe_debug"] = "fetch fallito dopo i retry (nessuna risposta valida)"
                    log.info("Scraping guardaroba venditore fallito (nessuna risposta valida) per %s", profilo_url)
            except Exception as e:
                result["seller_wardrobe_debug"] = f"eccezione durante il parsing: {e}"
                log.warning("Scraping guardaroba venditore fallito (eccezione): %s", e)
        else:
            result["seller_wardrobe_debug"] = "nessun seller_id/seller_login trovato nella pagina annuncio -- profilo mai contattato"
            log.warning("Guardaroba venditore non tentato: né seller_id né seller_login trovati per %s", url)

    except Exception as e:
        log.warning("Scraping Vinted fallito per %s: %s", url, e)

    return result


def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=3):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    for attempt in range(1, max_retries + 1):
        try:
            resp = _vinted_session.get(url, headers=headers, timeout=18)
            if resp.ok:
                return resp.content
        except Exception:
            pass
        time.sleep(0.6 * attempt)
    return None


# ---------------------------------------------------------------------------
# GEMINI E TOOLKIT IA
# ---------------------------------------------------------------------------

def optimize_image_bytes(img_bytes, max_size=768):
    try:
        img = Image.open(BytesIO(img_bytes))
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return img_bytes

def costruisci_parts_foto(photo_bytes_list):
    parts = []
    for img_bytes in photo_bytes_list:
        optimized = optimize_image_bytes(img_bytes)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(optimized).decode("utf-8")}})
    return parts

def costo_gemini_token(usage):
    inp = usage.get("promptTokenCount", 0) or 0
    out = usage.get("candidatesTokenCount", 0) or 0
    return (inp * PREZZO_GEMINI_INPUT + out * PREZZO_GEMINI_OUTPUT) / 1_000_000

def chiama_gemini(system_prompt, user_text, photo_bytes_list=None, grounding=False, max_retries=4):
    photo_bytes_list = photo_bytes_list or []
    parts = [{"text": user_text}] + costruisci_parts_foto(photo_bytes_list)

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 3000, "thinkingConfig": {"thinkingLevel": "low"}},
    }
    if grounding:
        payload["tools"] = [{"google_search": {}}]

    backoff_seconds = 2
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(GEMINI_API_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
            if not resp.ok:
                log.warning("Gemini HTTP %d: %s", resp.status_code, resp.text[:500])
            if resp.ok:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) or [])
                    usage = data.get("usageMetadata", {})
                    grounding_metadata = candidates[0].get("groundingMetadata", {}) if candidates else {}
                    n_query = len(grounding_metadata.get("webSearchQueries", []) or [])
                    costo = costo_gemini_token(usage) + n_query * PREZZO_GROUNDING_PER_QUERY
                    return text, costo, n_query
                return "[ERRORE: risposta Gemini senza candidates]", 0.0, 0
            if resp.status_code in {429, 500, 502, 503, 504}:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            return f"[ERRORE: chiamata Gemini fallita dopo {max_retries} tentativi. Eccezione: {e}]", 0.0, 0
    return "[ERRORE: tentativi esauriti]", 0.0, 0


# ---------------------------------------------------------------------------
# CERVELLO GEMINI CON FUNCTION CALLING FORZATO
# ---------------------------------------------------------------------------
# Il tool builtin "google_search" di Gemini NON e' forzabile in modo affidabile
# (il modello spesso decide di non chiamarlo mai, anche se il prompt lo chiede
# esplicitamente). Sostituiamo con una function custom che richiama Serper --
# stesso servizio gia' usato per i comp pre-raccolti -- e la forziamo con
# tool_config.function_calling_config.mode = "ANY", che per il function calling
# "vero" (non il retrieval builtin) e' effettivamente vincolante.

def valuta_qualita_comp(comps_text):
    """Stima se i comp pre-raccolti da Serper sono sufficienti a dare un
    verdetto senza bisogno di forzare una ricerca aggiuntiva. Euristica
    semplice: conta quanti prezzi reali compaiono nel blocco, e verifica
    che la categoria non sia stata saltata per mancata rilevazione."""
    if not comps_text:
        return False
    if "Categoria non rilevata" in comps_text:
        return False
    n_prezzi = len(re.findall(r"€\s*\d", comps_text)) + len(re.findall(r"EUR\s*[\d.,]+", comps_text))
    return n_prezzi >= 5


def cerca_serper_mirata(query):
    """Ricerca aggiuntiva mirata, richiamabile dal cervello quando i comp
    pre-raccolti sono insufficienti o fuori tema."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata)."
    payload = [{"q": query, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}"
    lines = []
    for batch in results:
        for r in batch.get("organic", [])[:8]:
            titolo = r.get("title", "")
            snippet = (r.get("snippet", "") or "")[:150]
            lines.append(f"- {titolo}: {snippet}")
    return "\n".join(lines) if lines else "Nessun risultato trovato per questa query."


CERVELLO_FUNCTION_DECLARATION = {
    "name": "cerca_comp_prezzo",
    "description": (
        "Cerca sul web per due scopi distinti, entrambi validi: (1) trovare comp "
        "di prezzo aggiuntivi quando i dati pre-raccolti sono insufficienti, fuori "
        "tema o troppo scarsi; (2) VERIFICARE la plausibilita' di codici prodotto, "
        "diciture rare ('prototipo', 'campionario', edizione limitata) o altri "
        "claim molto specifici citati nell'analisi visiva, prima di trattarli come "
        "prova di autenticita' o di valore superiore alla media."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query di ricerca mirata, es. 'YSL camicia vintage uomo venduto eBay' oppure 'Miu Miu codice PMMJ-2016 prototipo collezione'",
            }
        },
        "required": ["query"],
    },
}


def chiama_gemini_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4):
    """Variante del cervello con function calling. Se forza_ricerca=True, il
    primo giro DEVE chiamare cerca_comp_prezzo (mode ANY). Se False, il tool
    resta disponibile ma la scelta e' lasciata al modello (mode AUTO).

    Gestisce fino a MAX_ROUNDS_FUNZIONE giri di ricerca: se dopo aver
    ricevuto un risultato (es. una ricerca fallita per crediti Serper
    esauriti) il modello prova a richiamare di nuovo la funzione invece di
    rispondere, i giri precedenti lasciavano il messaggio Telegram vuoto
    (solo header, verdetto assente) perche' la seconda risposta veniva letta
    come testo finale anche quando conteneva solo un'altra richiesta di
    funzione. Ora, all'ultimo giro consentito, i tool vengono disabilitati
    (mode NONE) per costringere il modello a rispondere con un verdetto
    testuale usando qualunque dato abbia gia' raccolto."""
    contents = [{"role": "user", "parts": [{"text": user_text}]}]
    costo_totale = 0.0
    n_query_extra = 0
    MAX_ROUNDS_FUNZIONE = 2  # giri di ricerca consentiti prima di forzare una risposta testuale

    def _chiama_gemini_raw(tool_mode, tools_abilitati, tentativi_rimasti):
        function_calling_config = {"mode": tool_mode}
        if tool_mode == "ANY":
            function_calling_config["allowed_function_names"] = ["cerca_comp_prezzo"]

        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "safetySettings": [
                {"category": c, "threshold": "BLOCK_NONE"} for c in (
                    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
            ],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 3000},
        }
        if tools_abilitati:
            payload["tools"] = [{"function_declarations": [CERVELLO_FUNCTION_DECLARATION]}]
            payload["tool_config"] = {"function_calling_config": function_calling_config}

        backoff_seconds = 2
        for attempt in range(1, tentativi_rimasti + 1):
            try:
                resp = requests.post(GEMINI_API_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
                if not resp.ok:
                    log.warning("Gemini (cervello forzato) HTTP %d: %s", resp.status_code, resp.text[:500])
                    if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < tentativi_rimasti:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                raise
        raise RuntimeError("tentativi esauriti")

    tool_mode = "ANY" if forza_ricerca else "AUTO"

    for round_idx in range(MAX_ROUNDS_FUNZIONE + 1):
        ultimo_giro = round_idx == MAX_ROUNDS_FUNZIONE
        try:
            data = _chiama_gemini_raw(
                tool_mode="NONE" if ultimo_giro else tool_mode,
                tools_abilitati=not ultimo_giro,
                tentativi_rimasti=max_retries,
            )
        except Exception as e:
            return f"[ERRORE: cervello forzato fallito. Eccezione: {e}]", costo_totale, n_query_extra

        candidates = data.get("candidates", [])
        if not candidates:
            return "[ERRORE: risposta Gemini senza candidates]", costo_totale, n_query_extra

        usage = data.get("usageMetadata", {})
        costo_totale += costo_gemini_token(usage)

        parts = candidates[0].get("content", {}).get("parts", []) or []
        function_call = next((p.get("functionCall") for p in parts if p.get("functionCall")), None)

        if function_call and not ultimo_giro:
            query_richiesta = function_call.get("args", {}).get("query", "")
            log.info("Cervello Gemini ha richiesto ricerca mirata (giro %d/%d): '%s'", round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
            risultato_ricerca = cerca_serper_mirata(query_richiesta)
            n_query_extra += 1

            contents.append({"role": "model", "parts": parts})
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": "cerca_comp_prezzo",
                        "response": {"result": risultato_ricerca},
                    }
                }]
            })
            tool_mode = "AUTO"  # i giri successivi non sono piu' forzati
            continue

        testo = "".join(p.get("text", "") for p in parts)
        if testo.strip():
            return testo, costo_totale, n_query_extra
        if not ultimo_giro:
            # Nessun testo e nessuna function call valida (raro): un altro giro
            continue
        return "[ERRORE: il modello non ha prodotto una risposta testuale dopo i tentativi di ricerca]", costo_totale, n_query_extra

    return "[ERRORE: tentativi esauriti]", costo_totale, n_query_extra


# ---------------------------------------------------------------------------
# SERPER RICERCA
# ---------------------------------------------------------------------------

def build_vinted_search_url(brand, categoria, materiale=None, catalog_id=None):
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    parti_search_text = [p for p in (categoria, materiale) if p]
    search_text_finale = " ".join(parti_search_text)
    catalog_str = f"&catalog[]={catalog_id}" if catalog_id else ""
    if brand_id:
        url = (
            f"https://www.vinted.it/catalog?brand_ids[]={brand_id}"
            f"{catalog_str}"
            f"&search_text={quote(search_text_finale)}"
            "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
        )
        return url, True
    query_text = f"{brand} {search_text_finale}".strip()
    url = (
        f"https://www.vinted.it/catalog?search_text={quote(query_text)}"
        f"{catalog_str}"
        "&order=newest_first"
    )
    return url, False

def search_comps_ebay_sold_url(brand, categoria):
    termine_en = CATEGORIA_TERMINE_EN.get(categoria, categoria)
    query_base = f'{brand} "{termine_en}"'.strip() if termine_en else (brand or "").strip()
    if not query_base:
        return None
    return f"https://www.ebay.it/sch/i.html?_nkw={quote(query_base)}&_sacat=0&_from=R40&LH_Sold=1&rt=nc&LH_PrefLoc=2"

def _estrai_articoli_vinted(content, max_articoli=15):
    righe_pulite, visti = [], set()
    for riga in content.split("\n"):
        riga_dec = riga.replace("&#x20AC;", "€").replace("&#x20ac;", "€")
        match_prezzo = re.search(r"€\s*([\d]+(?:\.\d+)?)", riga_dec)
        if not match_prezzo:
            continue
        prezzo = match_prezzo.group(1)
        riga_pulita = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', riga_dec)
        riga_pulita = re.sub(r'!\[', '', riga_pulita)
        riga_pulita = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', riga_pulita).replace('"', '').strip().lstrip('-').strip()
        pos_prezzo = riga_pulita.find(f"€{prezzo}")
        if pos_prezzo == -1:
            pos_prezzo = riga_pulita.find("€")
        titolo = riga_pulita[:pos_prezzo].rstrip(", ").strip() if pos_prezzo > 0 else riga_pulita
        match_meta = re.search(r",\s*(?:brand|marca|condizioni|condition|taglia|size)\s*:", titolo, re.IGNORECASE)
        if match_meta:
            titolo = titolo[:match_meta.start()].strip()
        if not titolo or len(titolo) < 5 or titolo.startswith("http"):
            continue
        chiave = (titolo[:60].lower(), prezzo)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe_pulite.append(f"- {titolo} — €{prezzo}")
        if len(righe_pulite) >= max_articoli:
            break
    return "\n".join(righe_pulite) if righe_pulite else "  Nessun articolo trovato."

def _estrai_articoli_ebay(content, max_articoli=15):
    pattern_titolo = re.compile(r'<span[^>]*class="su-styled-text primary default"[^>]*>([^<]+)</span>', re.IGNORECASE)
    pattern_prezzo = re.compile(r'<span[^>]*class="[^"]*s-card__price[^"]*"[^>]*>([^<]+)</span>', re.IGNORECASE)
    titoli = [(m.start(), m.group(1).strip()) for m in pattern_titolo.finditer(content)]
    prezzi = [(m.start(), m.group(1).strip()) for m in pattern_prezzo.finditer(content)]
    righe_pulite = []
    if titoli and prezzi:
        for pos_titolo, titolo in titoli:
            prezzo_vicino = min((p for p in prezzi if p[0] >= pos_titolo), key=lambda p: p[0] - pos_titolo, default=None)
            if prezzo_vicino and (prezzo_vicino[0] - pos_titolo) < 2000:
                righe_pulite.append(f"- {titolo} — {prezzo_vicino[1]}")
            if len(righe_pulite) >= max_articoli:
                break
    if righe_pulite:
        return "\n".join(righe_pulite)
    blocchi = re.split(r"\n{1,2}", content)
    for i, blocco in enumerate(blocchi):
        match_titolo = re.search(r"\[([^\]]{15,150})\]\(https?://[^)]*ebay[^)]*\)", blocco, re.IGNORECASE)
        if not match_titolo:
            continue
        titolo = match_titolo.group(1).strip()
        prezzo = None
        for b_vicino in blocchi[i:i + 3]:
            match_prezzo = re.search(r"EUR\s*([\d.,]+)|€\s*([\d.,]+)", b_vicino)
            if match_prezzo:
                prezzo = match_prezzo.group(1) or match_prezzo.group(2)
                break
        if prezzo:
            righe_pulite.append(f"- {titolo} — €{prezzo}")
        if len(righe_pulite) >= max_articoli:
            break
    if not righe_pulite:
        if "nessun risultato" in content.lower() or "nessuna corrispondenza" in content.lower():
            return "  Nessun risultato sold trovato per questa query specifica su eBay."
        return "  Nessun articolo con titolo+prezzo riconosciuto in questa pagina."
    return "\n".join(righe_pulite)

def _e_errore_crediti_serper(resp):
    if resp.status_code in (400, 401, 402, 403, 429):
        testo_body = (resp.text or "").lower()
        if resp.status_code in (401, 402, 403, 429):
            return True
        if any(k in testo_body for k in ("credit", "insufficient", "balance", "payment", "quota")):
            return True
    return False

def _serper_scrape_page_diretto(label, url):
    if not SERPER_API_KEY:
        return "Scrape non eseguito (SERPER_API_KEY non impostata).", False

    payload = {"url": url, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True}
    try:
        resp = requests.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"  Scrape fallito: {e}", False

    if "EBAY" in label.upper():
        content = data.get("html") or data.get("rawHtml") or data.get("raw_html") or data.get("content") or data.get("markdown") or ""
        return _estrai_articoli_ebay(content), True
    elif "VINTED" in label.upper():
        content = data.get("markdown") or data.get("text") or ""
        return _estrai_articoli_vinted(content), True
    return "  Fonte non supportata.", True

def _serper_batch_query_vestiaire(brand, categoria):
    """Query mirata su Vestiaire Collective. NON usa piu' un fallback generico
    "dress" quando la categoria non e' rilevata: in quel caso salta la query
    ed espone chiaramente al cervello che manca il dato, invece di restituire
    comp completamente fuori tema (es. abiti da sera al posto di camicie)."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", False

    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()

    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query Vestiaire "
            "saltata per evitare risultati fuorvianti (es. abiti al posto di camicie). "
            "Se necessario, usa la function cerca_comp_prezzo con una query piu' mirata."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    query_serper = f'site:vestiairecollective.com "{brand_pulito}" "{termine_en}" €'.strip() if brand_pulito else f'site:vestiairecollective.com "{termine_en}" €'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}", False

    lines = []
    for batch in results:
        for r in batch.get("organic", [])[:10]:
            titolo = r.get("title", "")
            snippet = r.get("snippet", "")
            match_prezzo = re.search(r"€\s*[\d.,]+|\d+(?:[.,]\d+)?\s*€|EUR\s*[\d.,]+", snippet, re.IGNORECASE)
            snippet_troncato = snippet[:100].rstrip()
            if match_prezzo and match_prezzo.group(0) not in snippet_troncato:
                snippet_troncato += f"... [PREZZO: {match_prezzo.group(0)}]"
            elif len(snippet) > 100:
                snippet_troncato += "..."
            lines.append(f"- {titolo}\n  {snippet_troncato}")
    return ("\n".join(lines) if lines else "Nessun risultato trovato."), True

# Falsi positivi idiomatici: "dress" in "dress shirt"/"dress pants" e' un
# aggettivo (capo elegante), non indica un abito. Senza questa esclusione,
# il filtro categoria "abito" li fa passare per errore.
ESCLUSIONI_FALSI_POSITIVI_CATEGORIA = {
    "abito": ["dress shirt", "dress pants", "dress code", "dress shoes"],
}

# Rumore generico da scartare sempre, indipendentemente dalla categoria:
# taglie bambino (non comparabili a un capo adulto), collab diffusion
# economiche (es. "for Target"), e frasi che indicano che il brand è citato
# solo come RIFERIMENTO/ispirazione, non come brand reale del prodotto
# (es. "R&S Records Horse Logo T-Shirt – Similar Graphic to Raf Simons").
RUMORE_GENERICO_COMP = [
    # taglie/target bambino
    "girls age", "boys age", "kids size", "toddler", "baby size",
    "girl's", "girls'", "girls ", " girls", "boy's", "boys'", "boys ", " boys",
    "kids ", " kids", "kids logo", "kids cotton",
    "years old", "age 4", "age 6", "age 8", "age 10", "age 12",
    # collab diffusion economiche
    "for target", "x target", "for h&m", "x h&m",
    # brand citato solo come riferimento/ispirazione, non prodotto reale
    "similar to", "similar graphic", "similar style to", "inspired by",
    "reference to", "in the style of", "style of", "style inspired",
    "homage to", "tribute to",
]

# Per ogni brand monitorato, le sue sottolinee/collaborazioni da escludere
# SEMPRE dai comp quando si valuta la linea principale -- condividono il
# nome brand nei titoli ma appartengono a fasce di prezzo completamente
# diverse (es. Y-3 è streetwear di massa via Adidas, non Yohji Yamamoto
# mainline; See by Chloé è diffusion, non Chloé mainline).
BRAND_SOTTOLINEE_DA_ESCLUDERE = {
    "chloé": ["see by chloé", "see by chloe"],
    "chloe": ["see by chloé", "see by chloe"],
    "yohji yamamoto": ["y-3", "y3 ", " y3", "y-3 adidas", "adidas y-3"],
    "alexander mcqueen": ["mcq alexander mcqueen", " mcq "],
    "maison margiela": ["mm6"],
    "margiela": ["mm6"],
    "missoni": ["missoni sport", "missoni home", "missoni mare", "missoni kids", "missoni junior"],
    "stella mccartney": ["adidas by stella mccartney", "stella mccartney for adidas", "adidas x stella mccartney", "pour adidas"],
    "raf simons": ["fred perry x raf simons", "raf simons x fred perry", "calvin klein x raf simons"],
}


def _filtra_comp_per_brand_sottolinee(testo_comp, brand):
    """Esclude dai comp le righe che appartengono a una sottolinea/collab
    nota del brand (vedi BRAND_SOTTOLINEE_DA_ESCLUDERE), che altrimenti
    contamina la stima con prezzi di una fascia di mercato completamente
    diversa pur condividendo il nome brand nel titolo."""
    if not testo_comp or not brand:
        return testo_comp

    sottolinee = BRAND_SOTTOLINEE_DA_ESCLUDERE.get(brand.strip().lower(), [])
    if not sottolinee:
        return testo_comp

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            if any(sub in riga_lower for sub in sottolinee):
                scartate += 1
                continue
        righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_brand_sottolinee: scartate %d righe di sottolinea/collab per brand '%s'.", scartate, brand)

    return "\n".join(righe_filtrate)


def _filtra_comp_per_categoria(testo_comp, categoria):
    """Filtra le righe comp che non contengono nessuna keyword della
    categoria rilevata (in nessuna lingua tra quelle coperte da
    CATEGORIA_KEYWORDS), scartando anche falsi positivi idiomatici e
    rumore generico (taglie bambino, collab diffusion economiche).
    Necessario perché eBay/Vestiaire a volte restituiscono risultati
    "correlati al brand" fuori categoria (es. collane, pantaloni, libri
    quando si cerca una canotta) nonostante la query includa la categoria
    -- il motore di ricerca della fonte non la rispetta rigidamente, quindi
    il filtro va fatto sui risultati, non solo sulla query in ingresso."""
    if not testo_comp or not categoria:
        return testo_comp

    keywords = CATEGORIA_KEYWORDS.get(categoria, [])
    if not keywords:
        return testo_comp

    esclusioni = ESCLUSIONI_FALSI_POSITIVI_CATEGORIA.get(categoria, [])

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            e_rumore = any(kw in riga_lower for kw in RUMORE_GENERICO_COMP)
            e_falso_positivo = any(kw in riga_lower for kw in esclusioni)
            match_categoria = any(kw in riga_lower for kw in keywords)
            if match_categoria and not e_rumore and not e_falso_positivo:
                righe_filtrate.append(riga)
            else:
                scartate += 1
        else:
            righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_categoria: scartate %d righe fuori categoria/rumore '%s'.", scartate, categoria)

    return "\n".join(righe_filtrate)


def _rimuovi_comp_autoreferenziale(testo_comp_vinted, titolo_annuncio):
    """Filtra dai comp Vinted l'annuncio stesso in valutazione, che spesso
    compare tra i risultati di ricerca (stesso titolo) senza essere un dato
    di mercato indipendente -- rischia di essere scambiato per un comp
    reale invece che per l'oggetto stesso."""
    if not testo_comp_vinted or not titolo_annuncio:
        return testo_comp_vinted

    titolo_norm = _normalizza_titolo_per_dedup(html.unescape(titolo_annuncio))
    righe_filtrate = []
    for riga in testo_comp_vinted.split("\n"):
        m = re.match(r"-\s*(.+?)\s*—\s*€", riga)
        if m and _normalizza_titolo_per_dedup(html.unescape(m.group(1))) == titolo_norm:
            continue
        righe_filtrate.append(riga)
    return "\n".join(righe_filtrate)


def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None):
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
    ebay_url = search_comps_ebay_sold_url(brand, categoria)

    risultati = {}
    successi = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_vestiaire = executor.submit(_serper_batch_query_vestiaire, brand, categoria)
        future_vinted = executor.submit(_serper_scrape_page_diretto, "VINTED", vinted_url)
        future_ebay = executor.submit(_serper_scrape_page_diretto, "EBAY SOLD", ebay_url)
        futures = {future_vestiaire: "vestiaire", future_vinted: "vinted", future_ebay: "ebay"}

        try:
            for future in as_completed(futures, timeout=15):
                nome = futures[future]
                try:
                    testo, ok = future.result()
                    risultati[nome] = testo
                    successi[nome] = ok
                except Exception as e:
                    risultati[nome] = f"  Query fallita: {e}"
                    successi[nome] = False
        except TimeoutError:
            for future, nome in futures.items():
                if nome not in risultati:
                    if future.done():
                        try:
                            testo, ok = future.result()
                            risultati[nome] = testo
                            successi[nome] = ok
                        except Exception as e:
                            risultati[nome] = f"  Query fallita: {e}"
                            successi[nome] = False
                    else:
                        risultati[nome] = "  Timeout (fonte troppo lenta, oltre 15s)."
                        successi[nome] = False

    serper_ha_funzionato = any(successi.values())

    nota_brand = "" if vinted_per_id else (
        "⚠️ Brand non nella mappa brand_id Vinted -- la ricerca Vinted usa testo libero "
        "(meno precisa, possibili falsi positivi)."
    )

    vinted_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted"), query_base)
    vinted_comp_puliti = _filtra_comp_per_categoria(vinted_comp_puliti, categoria)
    vinted_comp_puliti = _filtra_comp_per_brand_sottolinee(vinted_comp_puliti, brand)
    vestiaire_comp_puliti = _filtra_comp_per_categoria(risultati.get("vestiaire"), categoria)
    vestiaire_comp_puliti = _filtra_comp_per_brand_sottolinee(vestiaire_comp_puliti, brand)
    ebay_comp_puliti = _filtra_comp_per_categoria(risultati.get("ebay"), categoria)
    ebay_comp_puliti = _filtra_comp_per_brand_sottolinee(ebay_comp_puliti, brand)

    parti = [f"RICERCA WEB PRE-RACCOLTA (3 fonti, base: '{query_base}'):"]
    if nota_brand:
        parti.append(nota_brand)
    if categoria:
        parti.append(f"(Comp filtrati per categoria rilevata: '{categoria}' -- risultati fuori tema già scartati.)")
    parti.append(
        "\n📍 FONTE: VESTIAIRE COLLECTIVE (prezzi ASK — annunci attivi, NON necessariamente venduti)\n"
        f"{vestiaire_comp_puliti or 'Nessun risultato'}"
    )
    parti.append(
        "\n📍 FONTE: VINTED (prezzi ASK — annunci attivi, NON necessariamente venduti; annuncio in analisi già escluso)\n"
        f"{vinted_comp_puliti or 'Nessun risultato'}"
    )
    parti.append(
        "\n📍 FONTE: EBAY SOLD (prezzi SOLD — venduti confermati, il dato PIÙ affidabile per stimare il prezzo di vendita reale)\n"
        f"{ebay_comp_puliti or 'Nessun risultato'}"
    )

    return "\n".join(parti), serper_ha_funzionato


def _estrai_margine_e_roi_da_blocco(blocco_testo):
    """Estrae margine netto e ROI da un blocco di testo. Gestisce anche i
    range (es. '€27-40 (ROI 110-165%)'), prendendo sempre il valore piu'
    basso come stima prudente -- il regex precedente si fermava sul primo
    numero e falliva silenziosamente quando seguito da un range invece che
    direttamente da 'ROI', lasciando margine=None e bypassando le reti di
    sicurezza a valle."""
    margine_m = re.search(r"€\s*(-?[\d.,]+)(?:\s*[-–]\s*[\d.,]+)?\s*\)?\s*\(?ROI", blocco_testo, re.IGNORECASE)
    roi_m = re.search(r"ROI\s*~?\s*(-?\d+)", blocco_testo, re.IGNORECASE)

    margine = None
    if margine_m:
        try:
            margine = float(margine_m.group(1).replace(",", "."))
        except ValueError:
            pass

    roi = None
    if roi_m:
        try:
            roi = int(roi_m.group(1))
        except ValueError:
            pass

    return margine, roi


def _normalizza_emoji_decisione(testo, lunghezza_blocco=400):
    """Il cervello a volte usa per errore le emoji del legit-check
    dell'occhio (✅⚠️❌) invece di quelle proprie (🟢🟡🔴), specialmente
    quando riprende la formulazione dell'analisi visiva preliminare.
    Gestisce due casi:
    1. Emoji sbagliata + nessuna parola di decisione: inserisce sia
       l'emoji giusta sia la parola (es. "✅ ..." -> "🟢 COMPRA ...").
    2. Emoji sbagliata + parola di decisione già presente (es. "✅ COMPRA
       SUBITO"): sostituisce solo l'emoji, senza duplicare la parola.

    IMPORTANTE: lo swap nel caso 2 avviene SOLO nel prefisso PRIMA della
    parola di decisione, mai dopo -- altrove nel blocco (es. dopo la
    parola) possono comparire le annotazioni ⚠️ _..._ inserite dalle reti
    di sicurezza (forza_soglia_minima_compra, converti_tratta_senza_
    obiettivo_valido), che non vanno mai toccate o si generano doppioni."""
    testa = testo[:lunghezza_blocco]
    resto = testo[lunghezza_blocco:]

    upper = testa.upper()
    posizioni = [upper.find(k) for k in ("COMPRA", "TRATTA", "NON COMPRARE", "CHIEDI")]
    posizioni = [p for p in posizioni if p != -1]

    if posizioni:
        idx_parola = min(posizioni)
        prefisso = testa[:idx_parola].replace("✅", "🟢", 1).replace("❌", "🔴", 1).replace("⚠️", "🟡", 1)
        testa = prefisso + testa[idx_parola:]
    else:
        if "✅" in testa:
            testa = testa.replace("✅", "🟢 COMPRA", 1)
        elif "❌" in testa:
            testa = testa.replace("❌", "🔴 NON COMPRARE", 1)
        elif "⚠️" in testa:
            testa = testa.replace("⚠️", "🟡 TRATTA", 1)

    return testa + resto


def normalizza_urgenza_wording(testo, lunghezza_blocco=400):
    """Il prompt prevede solo 3 livelli di urgenza (Alta/Media/Bassa), ma il
    modello a volte inventa varianti come 'Massima urgenza' o 'Urgenza
    massima' che sfuggono al controllo soglia (che cerca 'Alta'). Le
    normalizza tutte ad 'Alta urgenza' prima che declassa_urgenza_se_borderline
    valuti se il margine/ROI la giustifica davvero."""
    testa = testo[:lunghezza_blocco]
    resto = testo[lunghezza_blocco:]

    testa = re.sub(r"massima\s+(?:urgenza|priorit[aà])", "Alta urgenza", testa, flags=re.IGNORECASE)
    testa = re.sub(r"(?:urgenza|priorit[aà])\s+massima", "Alta urgenza", testa, flags=re.IGNORECASE)

    return testa + resto


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO e VALIDAZIONE POST-GENERAZIONE
# ---------------------------------------------------------------------------

def estrai_margine_preliminare(output_occhi_testo):
    """Estrae margine netto e ROI dalla valutazione finanziaria preliminare
    che l'occhio produce (best-effort: i formati variano leggermente).
    Usato per far risparmiare token al cervello quando anche la stima
    preliminare -- di solito ottimistica -- indica gia' una perdita."""
    return _estrai_margine_e_roi_da_blocco(output_occhi_testo or "")


def check_skip_pre_cervello(output_occhi_testo, listing_info=None):
    testo = (output_occhi_testo or "").lower()

    # NOTA (caso reale osservato): un Dries Van Noten a €5,95 è stato
    # scartato qui come "falso palese, Confidenza Alta" con dettagli che
    # sembravano inventati (font grossolano), mentre 3 legit check esterni
    # indipendenti sullo stesso capo hanno concluso "Probabilmente
    # autentico" 82-85%. La causa probabile è un bias "prezzo troppo basso
    # = deve essere falso" nell'occhio, nonostante il prompt gli dica di
    # ignorare il prezzo nel legit check. Soluzione scelta: RINFORZARE il
    # prompt dell'occhio (non rimuovere questo filtro, che resta utile per
    # risparmiare token sui falsi genuinamente conclamati) -- vedi la nuova
    # sezione "PREZZO BASSO NON È PROVA DI FALSO" nel GEMINI_OCCHI_SYSTEM_PROMPT.
    if ("probabilmente falso" in testo or "falso conclamato" in testo) and \
       any(c in testo for c in ("confidenza alta", "90%", "95%", "100%", "molto alto")):
        return True, "[FALSO CONCLAMATO] Rilevato da analisi visiva con alta confidenza."

    segnali_danno_fisico = sum([
        "buchi" in testo or "buco" in testo,
        "strappi gravi" in testo or "strappo grave" in testo,
        "bruciature" in testo or "bruciatura" in testo,
        "da riparare" in testo and "non riparabile" in testo,
        "condizione pessima" in testo,
        "indossabile" in testo and "non" in testo,
    ])
    if segnali_danno_fisico >= 2:
        return True, "[CONDIZIONE DISTRUTTA] Danni fisici gravi multipli rilevati dall'analisi visiva."

    # Skip su nessuna etichetta visibile: "Non verificabile" è uno dei 4
    # verdetti standard del legit check dell'occhio (zero etichette visibili
    # nelle foto). Senza nessuna etichetta il cervello non ha nulla in più
    # da aggiungere sull'autenticità -- l'unico passo utile è chiedere altre
    # foto al venditore, cosa che l'occhio stesso ha già suggerito nel suo
    # output. Risparmia la chiamata al cervello.
    #
    # "non verificabile" e' generico e potrebbe comparire fuori contesto
    # (es. "il colore non è verificabile dalla foto" pur con etichette
    # presenti) -- lo cerchiamo SOLO nel blocco verdetto iniziale, dove il
    # prompt lo colloca sempre come uno dei 4 esiti canonici del legit check.
    # Le frasi esplicite sotto sono già specifiche abbastanza da matchare
    # ovunque nel testo senza rischio di falsi positivi.
    BLOCCO_VERDETTO_INIZIALE = testo[:250]
    ETICHETTA_KEYWORDS_ESPLICITE = [
        "nessuna etichetta visibile", "assenza totale di etichette",
        "etichette non visibili", "zero etichette", "senza etichette visibili",
        "non sono visibili etichette", "nessuna etichetta è visibile",
    ]
    if "non verificabile" in BLOCCO_VERDETTO_INIZIALE or any(kw in testo for kw in ETICHETTA_KEYWORDS_ESPLICITE):
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] L'analisi visiva non ha trovato etichette "
            "per verificare l'autenticità -- cervello non consultato, servono più foto "
            "(main label + wash tag) prima di procedere."
        )

    # Skip su margine preliminare chiaramente negativo: se anche la stima
    # dell'occhio (di solito ottimistica, senza comp reali) indica gia' una
    # perdita netta o ROI negativo, e' molto improbabile che il cervello,
    # con dati di mercato reali, trovi un risultato migliore. Risparmia
    # una chiamata costosa (token + eventuale ricerca extra) senza cambiare
    # l'esito finale nella grande maggioranza dei casi.
    margine_prelim, roi_prelim = estrai_margine_preliminare(output_occhi_testo)
    margine_esplicitamente_nullo = any(k in testo for k in (
        "margine nullo", "margine negativo", "nessun valore di rivendita",
        "valore di rivendita non significativo", "non c'è valore di rivendita",
        "non vale il tempo",
    ))
    if margine_esplicitamente_nullo or (margine_prelim is not None and margine_prelim < 0) or (roi_prelim is not None and roi_prelim < 0):
        return True, (
            f"[MARGINE PRELIMINARE NEGATIVO] Stima preliminare dell'occhio indica "
            f"perdita netta (margine≈{margine_prelim}, ROI≈{roi_prelim}%) -- "
            "cervello non consultato per risparmiare token."
        )

    return False, None


def build_skip_report(listing_info, motivo_skip, output_occhi_testo=None):
    if motivo_skip.startswith("[MARGINE INSUFFICIENTE"):
        riga_legit = "Non valutato — filtro pre-cervello su margine insufficiente. Autenticità non in dubbio."
        riga_rischio = "BASSO — margine insufficiente (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[FALSO CONCLAMATO"):
        riga_legit = "Probabilmente falso — rilevato da analisi visiva con alta confidenza."
        if output_occhi_testo:
            dettaglio = None

            # Tentativo 1: formato atteso con intestazione "**Analisi visiva**"
            m_analisi = re.search(
                r"\*\*Analisi visiva\*\*[^\n]*\n+(.+?)(?=\n---|\n##|\n📨|\Z)",
                output_occhi_testo, re.IGNORECASE | re.DOTALL,
            )
            if m_analisi and m_analisi.group(1).strip():
                dettaglio = m_analisi.group(1).strip()

            # Tentativo 2: posizionale -- qualunque cosa segua il primo
            # separatore "---" (che nel template segue sempre il blocco
            # Verdetto), indipendentemente da come e' intitolata la sezione.
            if not dettaglio:
                m_pos = re.search(r"\n---\s*\n+(.+?)(?=\n---|\n📨|\Z)", output_occhi_testo, re.DOTALL)
                if m_pos and m_pos.group(1).strip():
                    dettaglio = m_pos.group(1).strip()

            # Tentativo 3 (ultima risorsa): mostra tutto il testo grezzo
            # dell'occhio troncato -- sempre meglio della frase generica,
            # l'utente ha diritto a vedere il ragionamento anche se il
            # formato non è quello atteso.
            if not dettaglio:
                testo_grezzo = output_occhi_testo.strip()
                dettaglio = testo_grezzo[:600] + ("..." if len(testo_grezzo) > 600 else "")

            if dettaglio:
                riga_legit = f"Probabilmente falso. Motivo specifico: {dettaglio}"
        riga_rischio = "ALTO — falso conclamato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[CONDIZIONE DISTRUTTA"):
        riga_legit = "Autentico ma condizione fisica gravemente compromessa — non rivendibile."
        riga_rischio = "BASSO (autenticità) / ALTO (condizione) — cervello non consultato"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE"):
        riga_legit = "Nessuna etichetta visibile nelle foto fornite — autenticità non verificabile allo stato attuale."
        riga_rischio = "ALTO (non verificabile) — servono più foto (filtro pre-cervello, risparmio token)"
    elif motivo_skip.startswith("[MARGINE PRELIMINARE NEGATIVO"):
        riga_legit = "Non valutato nel dettaglio — la stima preliminare indicava già una perdita netta."
        riga_rischio = "N/A — margine preliminare negativo (cervello non consultato per risparmiare token)"
    elif motivo_skip.startswith("[CATEGORIA GENERICA NON FLIPPABILE"):
        riga_legit = "Categoria strutturalmente senza mercato — nessun valore di rivendita."
        riga_rischio = "BASSO — categoria non flippabile (filtro pre-Gemini)"
    elif motivo_skip.startswith("[DANNO GRAVE DICHIARATO NEL TESTO"):
        riga_legit = "Non valutato — venditore dichiara esplicitamente un danno grave nel testo."
        riga_rischio = "BASSO (autenticità) / ALTO (condizione) — danno dichiarato dal venditore (filtro pre-Gemini)"
    elif motivo_skip.startswith("[NON ORIGINALE DICHIARATO"):
        riga_legit = "Venditore dichiara esplicitamente che il capo non è originale."
        riga_rischio = "MOLTO ALTO — non originale per dichiarazione diretta (filtro pre-Gemini)"
    elif motivo_skip.startswith("[TITOLO CON STRINGA DI RICERCA RESIDUA"):
        riga_legit = "Titolo contiene una stringa di ricerca residua ('gilet -blanc') — annuncio non valutato."
        riga_rischio = "BASSO — titolo malformato (filtro pre-Gemini)"
    elif motivo_skip.startswith("[LINEA/VARIANTE ESCLUSA PER BRAND"):
        riga_legit = "Linea o variante esclusa esplicitamente dalle regole di valutazione."
        riga_rischio = "ALTO / SCONVENIENTE — linea esclusa (filtro pre-Gemini)"
    elif motivo_skip.startswith("[VENDITORE IN BLOCKLIST"):
        riga_legit = "Venditore in blocklist (possibile truffatore o perditempo)."
        riga_rischio = "MOLTO ALTO — venditore bloccato (filtro pre-Gemini)"
    else:
        riga_legit = "Motivo di skip automatico non categorizzato."
        riga_rischio = "N/A — filtro automatico"
        
    motivo_breve = motivo_skip[:117].rsplit(" ", 1)[0] + "..." if len(motivo_skip) > 120 else motivo_skip

    # Per il caso "nessuna etichetta", riusa il messaggio che l'occhio ha già
    # suggerito (di solito chiede foto di main label + wash tag) invece del
    # generico "Non necessario" -- è l'unica azione utile in questo caso.
    messaggio_skip = "Non necessario."
    if motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE") and output_occhi_testo:
        m = re.search(
            r"📨\s*\*\*Messaggio da inviare:?\*\*\s*\n\"?([^\n\"]+)",
            output_occhi_testo, re.IGNORECASE,
        )
        if m:
            messaggio_skip = m.group(1).strip()

    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — filtro automatico\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        f"- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidità:** Bassa · **Rischio:** {riga_rischio} · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        f"## Legit check\n{riga_legit}\n\n"
        "## Da chiedere\nNon rilevante: filtro automatico attivato.\n\n"
        f"## Messaggio da inviare\n{messaggio_skip}"
    )


def forza_soglia_minima_compra(testo):
    """Ultima rete di sicurezza, indipendente dal formato esatto del verdetto.
    valida_contraddizioni_report funziona solo se il modello include l'emoji
    (🟢/🟡/🔴/🔵) o la dicitura "**Decisione:**" -- se il modello omette
    entrambi (capita), quella funzione non ha nulla da correggere e una
    COMPRA sotto soglia passa inosservata. Questa funzione normalizza prima
    eventuali emoji sbagliate (✅⚠️❌), poi scansiona il blocco iniziale del
    testo e forza TRATTA se margine <20€ o ROI <100% nonostante COMPRA."""
    testo = _normalizza_emoji_decisione(testo)

    LUNGHEZZA_BLOCCO_VERDETTO = 400
    testa = testo[:LUNGHEZZA_BLOCCO_VERDETTO]
    resto = testo[LUNGHEZZA_BLOCCO_VERDETTO:]

    testa_upper = testa.upper()
    contiene_compra = (
        re.search(r"\bCOMPRA\b", testa_upper)
        and "NON COMPRARE" not in testa_upper
        and "TRATTA" not in testa_upper
    )
    if not contiene_compra:
        return testo

    margine_valore, roi_valore = _estrai_margine_e_roi_da_blocco(testa)

    sotto_soglia = (
        (margine_valore is not None and margine_valore < 20)
        or (roi_valore is not None and roi_valore < 100)
    )
    if not sotto_soglia:
        return testo

    testa_corretta = testa.replace("🟢", "🟡", 1)
    testa_corretta = re.sub(
        r"\bCOMPRA(?:\s+(?:SUBITO|FORTE|IMMEDIATAMENTE|SE CI TIENI))?\b(?:\s*⚠️\s*_[^_]*_)?",
        "TRATTA ⚠️ _corretto automaticamente: sotto soglia minima (€20 netti / ROI 100%)_",
        testa_corretta, count=1, flags=re.IGNORECASE,
    )
    log.info(
        "forza_soglia_minima_compra: COMPRA declassato a TRATTA (margine=%s, ROI=%s%%) -- verdetto originale privo di emoji/formato standard.",
        margine_valore, roi_valore,
    )
    return testa_corretta + resto


def declassa_urgenza_se_borderline(testo):
    """Rete di sicurezza indipendente dal formato: 'Alta urgenza' deve
    riflettere un margine di sicurezza reale (>=€30 netti E ROI >=150%),
    non un semplice superamento della soglia minima per COMPRA. Se il
    modello scrive 'Alta urgenza' (o sinonimi come 'Alta priorità') con
    margine/ROI solo appena sopra soglia, la declassa a 'Media urgenza' --
    coerente con la regola nel prompt, ma applicata anche quando il modello
    non la rispetta da solo."""
    LUNGHEZZA_BLOCCO_VERDETTO = 400
    testa = testo[:LUNGHEZZA_BLOCCO_VERDETTO]
    resto = testo[LUNGHEZZA_BLOCCO_VERDETTO:]

    PATTERN_ALTA_URGENZA = r"alta\s+(?:urgenza|priorit[aà]|importanza)"
    if not re.search(PATTERN_ALTA_URGENZA, testa, re.IGNORECASE):
        return testo

    margine_valore, roi_valore = _estrai_margine_e_roi_da_blocco(testa)

    margine_insufficiente_per_urgenza = margine_valore is not None and margine_valore < 30
    roi_insufficiente_per_urgenza = roi_valore is not None and roi_valore < 150

    if not (margine_insufficiente_per_urgenza or roi_insufficiente_per_urgenza):
        return testo

    testa_corretta = re.sub(
        PATTERN_ALTA_URGENZA,
        "Media urgenza ⚠️ _declassata: margine/ROI sopra soglia minima ma non abbastanza abbondante per Alta urgenza_",
        testa, count=1, flags=re.IGNORECASE,
    )
    log.info(
        "declassa_urgenza_se_borderline: Alta urgenza declassata a Media (margine=%s, ROI=%s%%).",
        margine_valore, roi_valore,
    )
    return testa_corretta + resto


def applica_soglia_trattativa_40_percento(testo, prezzo_prodotto):
    """Rete di sicurezza sulla regola: sconto massimo trattabile = 40% sul
    prezzo del PRODOTTO (mai sulla spedizione). Se il modello propone
    un'offerta totale ("Obiettivo trattativa: €X") sotto il minimo
    consentito, la corregge -- usando una stima di spedizione conservativa
    (il valore reale e' quasi sempre uguale o superiore, quindi questo e'
    un limite di sicurezza, non una stima esatta).

    IMPORTANTE: sostituisce l'INTERA riga "Obiettivo trattativa: ..." fino
    a fine riga, non solo il numero dell'offerta. In precedenza veniva
    patchato solo il primo numero, lasciando invariato il resto della frase
    (es. "= €17,50 totale → €14,50 (ROI 83%)") calcolato sul vecchio
    valore -- il risultato era una frase con numeri incoerenti tra loro,
    illeggibile. Ora la riga intera viene ricostruita in modo onesto,
    dichiarando esplicitamente che margine/ROI non sono ricalcolati
    automaticamente e vanno verificati manualmente se si procede."""
    if prezzo_prodotto is None:
        return testo

    m = re.search(r"Obiettivo trattativa:\s*€\s*([\d.,]+)[^\n]*", testo, re.IGNORECASE)
    if not m:
        return testo

    try:
        valore_offerto = float(m.group(1).replace(",", "."))
    except ValueError:
        return testo

    STIMA_SPEDIZIONE_MINIMA = 2.50  # tariffa IT, la piu' economica -- il vero minimo e' spesso piu' alto
    soglia_minima = round(prezzo_prodotto * 0.6 + STIMA_SPEDIZIONE_MINIMA, 2)

    if valore_offerto >= soglia_minima - 0.01:
        return testo

    soglia_str = f"{soglia_minima:.2f}".replace(".", ",")
    riga_corretta = (
        f"Obiettivo trattativa: €{soglia_str} totale (minimo consentito: 40% sconto "
        f"su prezzo prodotto €{prezzo_prodotto:.2f} + spedizione) ⚠️ _offerta originale "
        f"del modello (€{valore_offerto:.2f}) era sotto il limite consentito ed è stata "
        f"corretta al minimo -- margine e ROI relativi NON sono ricalcolati automaticamente, "
        f"verificare manualmente prima di inviare l'offerta_"
    )
    testo_corretto = testo[:m.start()] + riga_corretta + testo[m.end():]

    log.info(
        "applica_soglia_trattativa_40_percento: offerta corretta da €%.2f a €%.2f (prezzo prodotto=€%.2f), riga intera ricostruita.",
        valore_offerto, soglia_minima, prezzo_prodotto,
    )
    return testo_corretto


def converti_tratta_senza_obiettivo_valido(testo):
    """Rete di sicurezza: se il modello propone esplicitamente un
    'Obiettivo trattativa' che resta sotto soglia (es. ROI 40-70%) anche al
    massimo sconto, la negoziazione non risolve nulla -- la decisione
    corretta e' NON COMPRARE, non un tentativo di trattativa inutile.

    IMPORTANTE: interviene SOLO se un obiettivo trattativa e' presente ed
    e' insufficiente. Se manca del tutto (es. perche' questa TRATTA e'
    stata generata da forza_soglia_minima_compra declassando un COMPRA
    borderline che non prevedeva negoziazione), NON forza NON COMPRARE --
    in quel caso la TRATTA implicita ("negozia un po', margine risicato")
    resta valida cosi' com'e'. Prima questa funzione trattava "nessun
    obiettivo" come motivo di conversione, causando falsi positivi su
    COMPRA borderline declassati (es. margine 99% ROI, mai proposta
    trattativa esplicita dal modello)."""
    testo = _normalizza_emoji_decisione(testo)

    LUNGHEZZA_BLOCCO_VERDETTO = 400
    testa = testo[:LUNGHEZZA_BLOCCO_VERDETTO]
    resto = testo[LUNGHEZZA_BLOCCO_VERDETTO:]

    testa_upper = testa.upper()
    e_tratta = (
        "TRATTA" in testa_upper
        and "NON COMPRARE" not in testa_upper
        and not re.search(r"\bCOMPRA\b", testa_upper)
    )
    if not e_tratta:
        return testo

    m_obiettivo = re.search(r"Obiettivo trattativa[:\s]*.{0,250}", testo, re.IGNORECASE | re.DOTALL)
    if m_obiettivo is None:
        return testo  # nessun obiettivo proposto: non e' un errore, lascia TRATTA cosi' com'e'

    margine_obiettivo, roi_obiettivo = _estrai_margine_e_roi_da_blocco(m_obiettivo.group(0))

    obiettivo_insufficiente = (
        (margine_obiettivo is not None and margine_obiettivo < 20)
        or (roi_obiettivo is not None and roi_obiettivo < 100)
    )
    if not obiettivo_insufficiente:
        return testo

    testa_corretta = testa.replace("🟡", "🔴", 1)
    testa_corretta = re.sub(
        r"\bTRATTA\b(?:\s*⚠️\s*_[^_]*_)?",
        "NON COMPRARE ⚠️ _corretto: anche l'obiettivo di trattativa non raggiunge la soglia minima (€20 netti / ROI 100%), non ha senso negoziare_",
        testa_corretta, count=1, flags=re.IGNORECASE,
    )
    log.info(
        "converti_tratta_senza_obiettivo_valido: TRATTA convertito in NON COMPRARE (margine_obiettivo=%s, ROI_obiettivo=%s%%, obiettivo_trovato=%s).",
        margine_obiettivo, roi_obiettivo, m_obiettivo is not None,
    )
    return testa_corretta + resto


def valida_contraddizioni_report(testo):
    final_text = _normalizza_emoji_decisione(testo)

    def _get_decisione_match(txt):
        m = re.search(r"(🟢|🟡|🔴|🔵)\s+\*?\*?([^\n*]+)\*?\*?", txt)
        if m:
            return m, "emoji", m.group(2).strip()
        m2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", txt)
        if m2:
            return m2, "markdown", m2.group(1).strip()
        return None, None, ""

    match_d, fmt, dt = _get_decisione_match(final_text)

    def _sostituisci_decisione(txt, nuova_decisione, motivo):
        if fmt == "emoji":
            emoji_map = {"NON COMPRARE": "🔴", "TRATTA": "🟡", "COMPRA": "🟢", "CHIEDI": "🔵"}
            nuova_emoji = next((e for k, e in emoji_map.items() if k in nuova_decisione.upper()), "🟡")
            return re.sub(
                r"(🟢|🟡|🔴|🔵)\s+\*?\*?[^\n*]+\*?\*?",
                f"{nuova_emoji} **{nuova_decisione}** ⚠️ _{motivo}_",
                txt, count=1
            )
        else:
            return re.sub(
                r"(\*\*Decisione:\*\*\s*)[^\n]+",
                r"\1" + nuova_decisione + f" ⚠️ _{motivo}_",
                txt, count=1
            )

    roi_m = re.search(r"ROI\s*~?\s*(\d+)(?:[-–](\d+))?\s*%", final_text, re.IGNORECASE)

    if re.search(r"\bCOMPRA\b", dt) and re.search(r"sotto\s+soglia", final_text, re.IGNORECASE):
        nuova = "NON COMPRARE · N/A"
        final_text = _sostituisci_decisione(final_text, nuova, "corretto: margine sotto soglia")
        match_d, fmt, dt = _get_decisione_match(final_text)

    if "COMPRA SUBITO" in dt and re.search(r"Confidenza[:\s]+Bassa", final_text, re.IGNORECASE):
        nuova = dt.replace("COMPRA SUBITO", "COMPRA FORTE")
        final_text = _sostituisci_decisione(final_text, nuova, "corretto: COMPRA SUBITO richiede Confidenza non Bassa")
        match_d, fmt, dt = _get_decisione_match(final_text)

    if re.search(r"\bCOMPRA\b", dt) and "TRATTA" not in dt.upper():
        margine_m = re.search(r"€\s*([\d.,]+)\s*\(?ROI", final_text, re.IGNORECASE)
        margine_valore = None
        if margine_m:
            try:
                margine_valore = float(margine_m.group(1).replace(",", "."))
            except ValueError:
                pass
        roi_max = None
        if roi_m:
            roi_max = max(int(roi_m.group(1)), int(roi_m.group(2)) if roi_m.group(2) else int(roi_m.group(1)))
        
        margine_troppo_basso = margine_valore is not None and margine_valore < 15
        roi_troppo_basso = roi_max is not None and roi_max < 60
        
        if margine_troppo_basso or roi_troppo_basso:
            nuova = dt
            for k in ("COMPRA SUBITO", "COMPRA FORTE", "COMPRA SE CI TIENI", "COMPRA"):
                if k in nuova.upper():
                    nuova = re.sub(re.escape(k), "TRATTA", nuova, flags=re.IGNORECASE)
                    break
            motivo_num = f"margine €{margine_valore}" if margine_troppo_basso else f"ROI {roi_max}%"
            final_text = _sostituisci_decisione(final_text, nuova, f"corretto: {motivo_num} troppo basso per COMPRA diretto")

    return final_text


def estrai_decisione_da_testo(testo):
    m = re.search(r"(?:🟢|🟡|🔴|🔵)\s+\*?\*?([^\n*⚠️]+)", testo)
    if m:
        return m.group(1).strip().rstrip("*").strip()
    m2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", testo)
    return m2.group(1).strip() if m2 else None


def _e_urgenza_alta(decisione_testo):
    testo = (decisione_testo or "").lower()
    return any(k in testo for k in ("alta", "altissima", "subito", "forte"))


def _estrai_item_id_da_url(url):
    if not url:
        return None
    m = re.search(r"/items/(\d+)", url)
    return m.group(1) if m else None


def verifica_falso_ha_motivazione(testo):
    """Regola generale: se la parola 'falso'/'contraffatto'/'non autentico'
    compare nel messaggio finale (sezione Legit, sia formato SKIP "## Legit
    check" sia formato normale "🏷️ Legit:"), deve esserci una spiegazione
    specifica vicino (font, cuciture, materiale, wash tag...). Se il testo
    è troppo corto o coincide con una vecchia frase generica nota, aggiunge
    un avviso visibile invece di lasciare l'utente senza motivo. Si applica
    a QUALSIASI output finale, sia dal percorso SKIP pre-cervello sia dal
    cervello completo -- non solo al caso specifico già corretto in
    build_skip_report."""
    testo_lower = testo.lower()
    if not any(kw in testo_lower for kw in ("falso", "contraffatto", "non autentico")):
        return testo

    m_blocco = re.search(
        r"(?:🏷️\s*Legit:|##\s*Legit check\s*\n)(.{0,500})",
        testo, re.IGNORECASE | re.DOTALL,
    )
    blocco_legit = m_blocco.group(1).strip() if m_blocco else testo[:500]

    troppo_corto = len(blocco_legit) < 60
    frase_generica_nota = (
        "rilevato da analisi visiva con alta confidenza" in blocco_legit.lower()
        and len(blocco_legit) < 120
    )

    if troppo_corto or frase_generica_nota:
        log.info("verifica_falso_ha_motivazione: 'falso' citato senza motivo specifico, aggiunto avviso.")
        return testo + (
            "\n\n⚠️ _Nota automatica: è stato rilevato un possibile falso ma non è stato fornito "
            "un motivo specifico (font, cuciture, materiale, wash tag). Verificare manualmente le "
            "foto prima di scartare definitivamente l'annuncio._"
        )

    return testo


def _invia_risultato_telegram(listing_info, url, photo_bytes_list, header, output_finale, decisione, e_compra, scenario_usato, n_query_grounding=0):
    item_id = _estrai_item_id_da_url(url)
    urgenza_alta = _e_urgenza_alta(decisione)
    e_compra_urgente = (
        e_compra
        and urgenza_alta
        and "NON COMPRARE" not in (decisione or "").upper()
        and "CHIEDI" not in (decisione or "").upper()
    )

    if len(photo_bytes_list) > 1:
        telegram_send_media_group(
            TELEGRAM_OWNER_CHAT_ID,
            photo_bytes_list,
            caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto"
        )
    elif len(photo_bytes_list) == 1:
        telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))

    if url:
        if e_compra_urgente:
            telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, item_id)
        else:
            telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, None)
    else:
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + output_finale)

    if TELEGRAM_ALERT_CHAT_ID and e_compra:
        alert_text = (
            f"🚨 *AZIONE RICHIESTA*\n"
            f"*{listing_info.get('title')}*\n"
            f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
            f"✅ {decisione}\n"
            f"{url or ''}"
        )
        if e_compra_urgente and item_id:
            telegram_send_with_buttons(TELEGRAM_ALERT_CHAT_ID, alert_text, url, item_id)
        else:
            telegram_send_message(TELEGRAM_ALERT_CHAT_ID, alert_text)


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE
# ---------------------------------------------------------------------------

def process_listing(parsed, url, cover_photo_bytes):
    listing_info = dict(parsed)
    listing_info["url"] = url
    costo_totale = 0.0

    photo_bytes_list = []
    if url:
        scraped = scrape_vinted_listing(url)
        listing_info.update({
            "size": scraped.get("size"), "condition": scraped.get("condition"),
            "description": scraped.get("description"), "age_days": scraped.get("age_days"),
            "catalog_id": scraped.get("catalog_id"), "material_raw": scraped.get("material_raw"),
            "material_per_ricerca": scraped.get("material_per_ricerca"),
            "color_raw": scraped.get("color_raw"),
            "seller_login": scraped.get("seller_login"),
            "seller_id": scraped.get("seller_id"),
            "seller_feedback_count": scraped.get("seller_feedback_count"),
            "seller_feedback_reputation": scraped.get("seller_feedback_reputation"),
            "seller_items_count": scraped.get("seller_items_count"),
            "seller_country": scraped.get("seller_country"),
            "seller_top_items": scraped.get("seller_top_items") or [],
            "seller_wardrobe_debug": scraped.get("seller_wardrobe_debug") or "n/d",
        })
        
        # NUOVO FILTRO PRE-GEMINI
        e_skip_pre, motivo_skip_pre = check_skip_pre_gemini(listing_info)
        if e_skip_pre:
            # Silenzioso: nessuna notifica Telegram per le esclusioni pre-Gemini.
            # Rimane visibile solo nei log (Railway) per debug/controllo.
            log.info("FILTRO PRE-GEMINI ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s", listing_info.get("title"), motivo_skip_pre)
            return
            
        photo_urls = scraped.get("photo_urls", [])
        if photo_urls:
            with ThreadPoolExecutor(max_workers=5) as pool:
                risultati_download = list(pool.map(
                    lambda u: download_image_bytes(u, referer=url), photo_urls
                ))
            photo_bytes_list = [img for img in risultati_download if img]

            # Se alcune foto non sono state scaricate, ritenta specificamente
            # quelle mancanti invece di procedere silenziosamente con meno
            # foto di quelle disponibili -- l'analisi visiva ne risente molto.
            mancanti = [u for u, img in zip(photo_urls, risultati_download) if img is None]
            if mancanti:
                log.warning(
                    "Download foto incompleto per %s: %d/%d riuscite al primo giro, ritento le mancanti...",
                    url, len(photo_bytes_list), len(photo_urls),
                )
                with ThreadPoolExecutor(max_workers=3) as pool:
                    retry_risultati = list(pool.map(
                        lambda u: download_image_bytes(u, referer=url, max_retries=4), mancanti
                    ))
                recuperate = [img for img in retry_risultati if img]
                photo_bytes_list.extend(recuperate)
                if len(photo_bytes_list) < len(photo_urls):
                    log.warning(
                        "Dopo il retry restano %d/%d foto mancanti per %s -- analisi visiva basata su set incompleto.",
                        len(photo_urls) - len(photo_bytes_list), len(photo_urls), url,
                    )

    fallback_solo_cover_photo = False
    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]
        fallback_solo_cover_photo = True
        log.warning(
            "Scraping foto fallito del tutto per %s -- uso solo la cover photo Telegram come fallback. "
            "L'analisi visiva sara' basata su una sola immagine, possibile falso 'nessuna etichetta visibile'.",
            url,
        )
    listing_info["fallback_solo_cover_photo"] = fallback_solo_cover_photo
    if not photo_bytes_list:
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Niente foto per: {listing_info.get('title')}\nURL: {url or 'non trovato'}\nSalto valutazione.")
        return

    age_days = listing_info.get("age_days")
    age_text = f"{age_days:.1f} giorni fa" if age_days is not None else "non disponibile"

    seller_info_parts = []
    feedback_count = listing_info.get("seller_feedback_count")
    feedback_rep = listing_info.get("seller_feedback_reputation")
    items_count = listing_info.get("seller_items_count")
    seller_login = listing_info.get("seller_login")
    seller_country = listing_info.get("seller_country")
    seller_top_items = listing_info.get("seller_top_items") or []

    if seller_login:
        seller_info_parts.append(f"Username: {seller_login}")
    if seller_country:
        seller_info_parts.append(f"Paese: {seller_country}")
    if feedback_count is not None:
        stelle = f"{feedback_rep:.1f}/5" if feedback_rep is not None else "n/d"
        seller_info_parts.append(f"Recensioni: {feedback_count} ({stelle} stelle)")
    if items_count is not None:
        seller_info_parts.append(f"Articoli in vendita: {items_count}")
    if seller_top_items:
        seller_info_parts.append(f"Primi articoli in vendita: {', '.join(seller_top_items)}")

    seller_info_text = "\n".join(seller_info_parts) if seller_info_parts else "non disponibile"

    user_text_occhi = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Materiale (da pagina annuncio): {listing_info.get('material_raw') or 'non disponibile'}\n"
        f"Colore (da pagina annuncio): {listing_info.get('color_raw') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"\nPROFILO VENDITORE:\n{seller_info_text}"
    )

    output_occhi, costo_occhi, _ = chiama_gemini(
        GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
    costo_totale += costo_occhi

    e_skip, motivo_skip = check_skip_pre_cervello(output_occhi, listing_info)
    if e_skip:
        log.info("FILTRO PRE-CERVELLO ATTIVATO. Motivo: %s", motivo_skip)
        if motivo_skip.startswith("[FALSO CONCLAMATO"):
            # Log leggero e sempre attivo (indipendente da INVIA_DEBUG_CORREZIONI)
            # per poter verificare su Railway se l'estrazione del motivo
            # specifico funziona sul formato reale che il modello produce.
            log.info("FALSO CONCLAMATO -- output occhi grezzo per '%s':\n%s", listing_info.get("title"), output_occhi)
        output_finale = build_skip_report(listing_info, motivo_skip, output_occhi_testo=output_occhi)
        n_query_grounding = 0
        scenario_usato = "SKIP"
        forza_ricerca = None
        comp_sufficienti = None
    else:
        titolo_annuncio = listing_info.get("title") or ""
        brand_annuncio = listing_info.get("brand") or ""
        categoria_per_ricerca = estrai_categoria_da_titolo(titolo_annuncio) or ""
        catalog_id = listing_info.get("catalog_id")
        material_per_ricerca = listing_info.get("material_per_ricerca")

        scenario_usato = "F"
        comps_text = None

        tempo_trascorso = time.time() - _serper_timestamp_ultimo_fallimento[0]
        in_raffreddamento = (
            _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
            and tempo_trascorso < RAFFREDDAMENTO_SERPER_SECONDI
        )
        serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

        if serper_disponibile:
            comps_text, serper_ok = search_comps_completo(
                brand_annuncio, categoria_per_ricerca, titolo_annuncio,
                catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
            )
            if serper_ok:
                scenario_usato = "G"
                _serper_fallimenti_consecutivi[0] = 0
                if _serper_notifica_esaurimento_inviata[0]:
                    _serper_notifica_esaurimento_inviata[0] = False
                    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, "✅ Serper è tornato a funzionare normalmente.")
            else:
                _serper_fallimenti_consecutivi[0] += 1
                _serper_timestamp_ultimo_fallimento[0] = time.time()
                if _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO:
                    if not _serper_notifica_esaurimento_inviata[0]:
                        _serper_notifica_esaurimento_inviata[0] = True
                        telegram_send_message(
                            TELEGRAM_OWNER_CHAT_ID,
                            f"⚠️ *Serper ha esaurito i crediti o non risponde*.\nFallback a Scenario F per {RAFFREDDAMENTO_SERPER_SECONDI/3600:.0f} ore."
                        )

        contesto_listing = (
            f"{user_text_occhi}\n"
            f"Annuncio pubblicato: {age_text}\n"
            f"URL annuncio: {url or 'non disponibile'}"
        )
        if scenario_usato == "G":
            comp_sufficienti = valuta_qualita_comp(comps_text)
            forza_ricerca = not comp_sufficienti
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                f"--- {comps_text} ---\n\n"
                "Usa i risultati di ricerca web PRE-RACCOLTI come base. Se sono insufficienti, "
                "assenti o palesemente fuori tema, chiama la function cerca_comp_prezzo con una "
                "query mirata prima di dare il verdetto finale."
            )
        else:
            forza_ricerca = True
            comp_sufficienti = False
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                "NOTA: non ci sono risultati di ricerca pre-raccolti. Chiama la function "
                "cerca_comp_prezzo per ottenere comp reali prima di rispondere."
            )

        output_finale_raw, costo_cervello, n_query_grounding = chiama_gemini_cervello_forzato(
            GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, forza_ricerca=forza_ricerca)
        costo_totale += costo_cervello

        output_finale = valida_contraddizioni_report(output_finale_raw)
        correzioni_applicate = []
        if output_finale != output_finale_raw:
            correzioni_applicate.append("valida_contraddizioni_report")

        prev = output_finale
        output_finale = forza_soglia_minima_compra(output_finale)
        if output_finale != prev:
            correzioni_applicate.append("forza_soglia_minima_compra")
        prev = output_finale

        output_finale = converti_tratta_senza_obiettivo_valido(output_finale)
        if output_finale != prev:
            correzioni_applicate.append("converti_tratta_senza_obiettivo_valido")
        prev = output_finale

        output_finale = normalizza_urgenza_wording(output_finale)
        if output_finale != prev:
            correzioni_applicate.append("normalizza_urgenza_wording")
        prev = output_finale

        output_finale = declassa_urgenza_se_borderline(output_finale)
        if output_finale != prev:
            correzioni_applicate.append("declassa_urgenza_se_borderline")
        prev = output_finale

        prezzo_prodotto = None
        try:
            prezzo_prodotto = float(str(listing_info.get("price") or "").replace(",", "."))
        except (ValueError, TypeError):
            pass
        output_finale = applica_soglia_trattativa_40_percento(output_finale, prezzo_prodotto)
        if output_finale != prev:
            correzioni_applicate.append("applica_soglia_trattativa_40_percento")

    decisione = estrai_decisione_da_testo(output_finale) or ""
    e_compra = any(k in decisione.upper() for k in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO"))

    if scenario_usato == "SKIP":
        info_scenario = " · filtro pre-cervello (occhi soli)"
    elif scenario_usato == "F":
        info_scenario = f" · nessun comp pre-raccolto, ricerca forzata"
        info_scenario += f" ({n_query_grounding} extra)" if n_query_grounding else ""
    else:  # Scenario G
        if forza_ricerca:
            info_scenario = " · comp pre-raccolti scarsi, ricerca forzata"
        else:
            info_scenario = " · comp pre-raccolti sufficienti"
        info_scenario += f" ({n_query_grounding} extra)" if n_query_grounding else " (nessuna extra)"

    info_foto = ""
    if listing_info.get("fallback_solo_cover_photo"):
        info_foto = (
            "\n⚠️ *Scraping foto Vinted fallito* (probabile blocco/rate-limit) — "
            "analisi basata SOLO sulla cover photo Telegram, non sulle foto reali "
            "dell'annuncio. Un eventuale 'nessuna etichetta visibile' potrebbe "
            "essere un falso negativo dovuto a questo, non ai capi reali."
        )

    header = (
        f"🆕 *{listing_info.get('title')}*\n"
        f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
        f"🔧 Scenario {scenario_usato}{info_scenario}"
        f"{info_foto}"
        + f"\n{url or ''}\n{'—' * 20}\n"
    )

    output_finale = verifica_falso_ha_motivazione(output_finale)

    if "NON COMPRARE" in output_finale:
        output_finale = re.sub(
            r"(🔴\s+\*\*NON COMPRARE\*\*)\s*·\s*[^\n]+",
            r"\1 · N/A",
            output_finale
        )

    output_finale = re.sub(
        r"[EÈè]'?\s*ancora disponibile\??[\s,]*(?:[Ss]e\s+s[ìi][,.]?\s*)?",
        "",
        output_finale,
        flags=re.IGNORECASE
    )

    decisione_upper = decisione.upper()
    e_compra_puro = (
        re.search(r"\bCOMPRA\b", decisione_upper)
        and "TRATTA" not in decisione_upper
        and "CHIEDI" not in decisione_upper
        and "NON COMPRARE" not in decisione_upper
    )
    if e_compra_puro:
        output_finale = re.sub(
            r"(📨\s*\*\*Messaggio da inviare[:\*]*\*?\*?)\s*\n.*?(?=\n---|\n#|\n❓|\n🧠|\Z)",
            r"\1\nNon necessario.",
            output_finale,
            flags=re.IGNORECASE | re.DOTALL
        )
        output_finale = re.sub(
            r"(❓\s*\*\*Da chiedere[:\*]*\*?\*?)\s*\n.*?(?=\n---|\n#|\n🧠|\Z)",
            r"\1\nNon necessario.",
            output_finale,
            flags=re.IGNORECASE | re.DOTALL
        )

    _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, n_query_grounding if scenario_usato != "SKIP" else 0
    )

    # Messaggio di debug separato, SOLO se una rete di sicurezza ha
    # effettivamente modificato il verdetto -- utile per controllare da
    # Telegram senza entrare su Railway. Disattivato su richiesta (troppo
    # rumore ora che le correzioni sono ben rodate) -- riattivabile
    # mettendo INVIA_DEBUG_CORREZIONI = True qui sotto, nessun'altra
    # modifica necessaria.
    INVIA_DEBUG_CORREZIONI = False
    if INVIA_DEBUG_CORREZIONI and scenario_usato != "SKIP" and correzioni_applicate:
        debug_text = (
            f"🔧 *DEBUG* — correzioni automatiche applicate a *{listing_info.get('title')}*:\n"
            f"{', '.join(correzioni_applicate)}\n\n"
            f"— OUTPUT GREZZO CERVELLO (prima delle correzioni) —\n{output_finale_raw}\n\n"
            f"— INPUT CERVELLO (occhi + comp Serper/ricerca extra) —\n{user_text_cervello}"
        )
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID, debug_text)


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_recent_listings_seen = {}

DEDUP_CONTENUTO_WINDOW_SECONDS = 300


def _normalizza_titolo_per_dedup(title):
    if not title:
        return ""
    t = title.strip()
    t_senza_virgolette = re.sub(r"['\"][^'\"]*['\"]\s*$", "", t).strip()
    if t_senza_virgolette != t:
        base = t_senza_virgolette
    else:
        parole = t.split()
        base = " ".join(parole[:-1]) if len(parole) > 1 else t
    return re.sub(r"\s+", " ", base).strip().lower()


def e_variante_recente(parsed):
    chiave = (
        _normalizza_titolo_per_dedup(parsed.get("title")),
        (parsed.get("brand") or "").strip().lower(),
        (parsed.get("price") or "").strip(),
    )
    now = time.time()
    scadute = [k for k, ts in _recent_listings_seen.items() if now - ts > DEDUP_CONTENUTO_WINDOW_SECONDS]
    for k in scadute:
        del _recent_listings_seen[k]
    if chiave in _recent_listings_seen:
        return True
    _recent_listings_seen[chiave] = now
    return False


@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
async def on_new_message(event):
    try:
        msg_id = event.message.id
        if msg_id in _processed_message_ids:
            return
        _processed_message_ids.add(msg_id)
        if len(_processed_message_ids) > 500:
            _processed_message_ids.discard(min(_processed_message_ids))

        sender = await event.get_sender()
        if not any(h in ((getattr(sender, "username", "") or "") + " " + (getattr(sender, "first_name", "") or "")).lower() for h in VINTED_TRACKER_NAME_HINTS):
            return

        text = event.message.message or ""
        parsed = parse_vinted_tracker_message(text)
        if e_variante_recente(parsed):
            return

        url = extract_url_from_text(text)
        if not url and event.message.buttons:
            for row in event.message.buttons:
                for btn in row:
                    if "vinted." in (getattr(btn, "url", None) or ""):
                        url = getattr(btn, "url", None)
                        break

        cover = await event.message.download_media(bytes) if event.message.photo else None
        await asyncio.to_thread(process_listing, parsed, url, cover)
    except Exception:
        log.error("Errore generico:\n%s", traceback.format_exc())


async def main():
    log.info("Vinted Oracle avviato su Telethon.")
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
