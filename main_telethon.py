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
import uuid
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

# VINTED_ACCESS_TOKEN / VINTED_REFRESH_TOKEN: opzionali, servono SOLO per la
# ricerca visuale Vinted (search_by_image), l'unica fonte che richiede una
# sessione autenticata -- vedi la lunga docstring di _risolvi_search_by_image_id
# per la prova (raccolta il 2026-09-19 via DevTools) che senza login questa
# feature specifica non parte, mentre TUTTO il resto del bot (scraping
# annunci, ricerca testo/catalogo) resta anonimo come sempre e non ne ha
# bisogno. Vanno presi dai cookie del browser DOPO aver fatto login su un
# account Vinted -- l'utente ha scelto esplicitamente di usare un account
# dedicato/sacrificabile, MAI l'account principale, per il rischio di ban
# che l'uso automatizzato di un account comporta (vedi conversazione
# 2026-09-19). Se assenti, la ricerca visuale resta semplicemente disattivata
# (comportamento identico a prima di questa modifica) -- nessun'altra parte
# del bot dipende da queste variabili.
VINTED_ACCESS_TOKEN = os.environ.get("VINTED_ACCESS_TOKEN", "").strip()
VINTED_REFRESH_TOKEN = os.environ.get("VINTED_REFRESH_TOKEN", "").strip()

# VISUAL_SEARCH_ATTIVA: la 4a fonte comp "ricerca visuale Vinted" (equivalente
# al bottone "Cerca articoli simili" + filtro brand, vedi
# _risolvi_search_by_image_id/build_vinted_visual_search_url).
#
# STATO: CHIUSA DEFINITIVAMENTE il 2026-09-19 -- non e' un bug di header
# risolvibile, e' un requisito di autenticazione del prodotto Vinted stesso.
# Prova conclusiva raccolta via DevTools con l'utente: la richiesta che ha
# funzionato nel browser portava cookie access_token_web/refresh_token_web
# (sessione Vinted autenticata con l'account personale dell'utente, non
# anonima). Confermato con un test mirato: riaprire lo stesso URL gia'
# generato in incognito senza login funzionava (cache), ma generare una
# ricerca visuale NUOVA (mai vista da Vinted prima) sempre in incognito
# senza login veniva rimandata al login. Quindi senza una sessione
# autenticata la feature non parte, punto -- nessun Referer/Sec-Fetch/User-
# Agent puo' aggirarlo. Vedi la docstring di _risolvi_search_by_image_id per
# il dettaglio completo dei due tentativi precedenti (falliti) e di questa
# verifica finale.
# Decisione: il bot NON autentica MAI le proprie richieste con le
# credenziali Vinted personali dell'utente (rischio sull'account reale,
# uso improprio di credenziali per uno scraper, violazione ToS diretta) --
# quindi questa fonte resta chiusa a meno che l'utente non scelga
# esplicitamente, in futuro, di dedicare un account Vinted separato al bot
# con piena consapevolezza dei rischi. Il flag resta com'e' (default False,
# funzione gia' pronta e innocua se mai riattivata) solo per non buttare il
# codice, non perche' ci si aspetti che torni utile.
VISUAL_SEARCH_ATTIVA = os.environ.get("VISUAL_SEARCH_ATTIVA", "false").strip().lower() == "true"

# CERVELLO_PROVIDER: "gemini" (default, comportamento storico) oppure
# "openai" per usare GPT-4o-mini al posto di Gemini-3.7-flash sul solo step
# Cervello (verdetto/margine/ROI). L'Occhio (legit-check visivo) resta
# SEMPRE Gemini in entrambi i casi -- non e' toccato da questo flag: un
# test A/B su 12+ item reali (Set 2026-09) ha mostrato che Gemini resta
# nettamente piu' affidabile su OCR di etichette e rischio di dettagli
# allucinati, mentre sul solo ragionamento testuale (stesso identico input
# occhio) GPT-4o-mini e' risultato comparabile in qualita' e ~5x piu' veloce.
# Cambiare provider non richiede modifiche al codice: basta questa env var,
# quindi si puo' tornare a Gemini all'istante (senza deploy) se qualcosa si
# comporta male in produzione.
CERVELLO_PROVIDER = os.environ.get("CERVELLO_PROVIDER", "gemini").strip().lower()
if CERVELLO_PROVIDER not in ("gemini", "openai"):
    raise ValueError(f"CERVELLO_PROVIDER deve essere 'gemini' o 'openai', ricevuto: '{CERVELLO_PROVIDER}'")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if CERVELLO_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("CERVELLO_PROVIDER=openai richiede OPENAI_API_KEY nell'ambiente.")

# RETI_SICUREZZA_ATTIVE: interruttore diagnostico temporaneo. Log di
# produzione del 18-19/09/2026 hanno mostrato che con CERVELLO_PROVIDER=openai
# le reti di sicurezza post-processing (verifica_ancoraggio_prezzo_comp,
# verifica_comp_citati_sono_reali, forza_soglia_minima_compra,
# converti_tratta_senza_obiettivo_valido, declassa_urgenza_se_borderline,
# applica_soglia_trattativa_40_percento) intervengono su ~94% degli item
# (61/65), contro 0/43 con Gemini nello stesso periodo -- troppo alto per
# essere solo "casi limite corretti", serve vedere l'output NUDO del
# cervello per capire se il problema e' nel prompt o nel provider stesso.
# A False, process_listing salta tutte le correzioni automatiche e manda
# il verdetto cosi' come lo scrive il cervello -- SOLO per diagnosi
# mirata, mai lasciare a False in modo permanente (nessuna rete a
# protezione di falsi COMPRA basati su comp inventati).
RETI_SICUREZZA_ATTIVE = os.environ.get("RETI_SICUREZZA_ATTIVE", "true").strip().lower() == "true"

# DEBUG_CONFRONTO_COMP_TELEGRAM: quando True, aggiunge in fondo a OGNI
# messaggio Telegram (non solo quelli corretti) un blocco con i prezzi
# effettivamente presenti nei dati di ricerca ricevuti dal cervello per
# quell'item, cosi' si puo' confrontare a colpo d'occhio dal telefono cosa
# il cervello ha scritto in Analisi contro cosa gli e' stato davvero dato
# in pasto. Pensato per lo stesso esperimento diagnostico di cui sopra;
# messaggi piu' lunghi, disattivare quando la diagnosi e' conclusa.
DEBUG_CONFRONTO_COMP_TELEGRAM = os.environ.get("DEBUG_CONFRONTO_COMP_TELEGRAM", "false").strip().lower() == "true"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Due modelli distinti per i due ruoli della pipeline (aggiornato Ago 2026,
# gemini-3.1-flash-lite era l'unico disponibile quando il bot e' stato
# costruito -- da allora Google ha rilasciato la famiglia 3.5/3.6/3.7).
#
# OCCHIO (legit-check visivo, prima passata): resta su un modello Lite --
# compito piu' meccanico (leggere etichette, descrivere condizione), poco
# da guadagnare da un modello piu' pesante qui.
#
# CERVELLO (verdetto finale: prezzo di vendita, margine, ROI): upgrade a un
# Flash "pieno", non Lite. Questa e' la parte che ha prodotto quotazioni
# incoerenti su capi quasi identici (es. due camicie Our Legacy valutate
# €40 e €60) -- il ragionamento sui comp e l'ancoraggio ai prezzi reali
# beneficiano di piu' capacita' rispetto al filtro visivo. Costa di piu' per
# token, ma il Cervello viene chiamato una sola volta per annuncio (non ha
# senso risparmiare li' se il risultato e' il numero che decide l'acquisto).
GEMINI_MODEL_OCCHIO = "gemini-3.5-flash-lite"
GEMINI_MODEL_CERVELLO = "gemini-3.7-flash"
GEMINI_API_URL_OCCHIO = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_OCCHIO}:generateContent"
GEMINI_API_URL_CERVELLO = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_CERVELLO}:generateContent"

# Prezzi per milione di token, paid tier standard (Ago 2026) -- verificare su
# https://ai.google.dev/gemini-api/docs/pricing se cambiano.
PREZZO_OCCHIO_INPUT = 0.30
PREZZO_OCCHIO_OUTPUT = 2.50
# Prezzo scontato di lancio, valido fino al 31/12/2026 (poi raddoppia a
# $1.50/$7.50 -- verificare su ai.google.dev/gemini-api/docs/pricing).
PREZZO_CERVELLO_INPUT = 0.75
PREZZO_CERVELLO_OUTPUT = 3.75
PREZZO_GROUNDING_PER_QUERY = 14 / 1000

# Cervello alternativo via OpenAI (attivo solo con CERVELLO_PROVIDER=openai).
# Prezzi per milione di token, verificare su https://openai.com/api/pricing/
# se cambiano.
OPENAI_MODEL_CERVELLO = "gpt-4o-mini"
OPENAI_API_URL_CERVELLO = "https://api.openai.com/v1/chat/completions"
PREZZO_CERVELLO_OPENAI_INPUT = 0.15
PREZZO_CERVELLO_OPENAI_OUTPUT = 0.60

MAX_GALLERY_PHOTOS = 10

# Marker di versione, loggato all'avvio -- serve SOLO a verificare in modo
# inequivocabile quale codice sta girando su Railway dopo un deploy, senza
# doverlo dedurre dai timestamp dei log. Aggiorna la data quando fai una
# modifica significativa (facoltativo, ma utile per il debug futuro).
BOT_VERSION = "2026-09-13-parser-tracker-flessibile"

# GATE MARGINE ASSOLUTO (nuovo): soglia di qualita' del deal, separata dalla
# soglia minima di sicurezza (EUR 20 / ROI 100%) gia' presente nei prompt e
# nelle reti di sicurezza. Serve ad alzare il valore medio dei deal notificati
# senza toccare i cap delle watch: un capo con ROI altissimo ma margine
# assoluto piccolo (es. comprato a 5 EUR, rivenduto a 20) supera il ROI ma non
# avvicina l'obiettivo di margine, quindi non merita una notifica.
# Metti a 0 per disattivare il gate senza altre modifiche.
SOGLIA_MARGINE_ASSOLUTO_NOTIFICA = 0

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

_serper_fallimenti_consecutivi = [0]
_serper_timestamp_ultimo_fallimento = [0.0]
SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO = 3
RAFFREDDAMENTO_SERPER_SECONDI = 3600 * 6
_serper_notifica_esaurimento_inviata = [False]

# Rate-limiter tra richieste Vinted consecutive: dopo ~13h di attivita'
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
    titolo, e sceglie quella con il match PIU' LUNGO/specifico -- non la
    prima trovata nell'ordine del dizionario. Necessario perche' altrimenti
    keyword generiche possono "vincere" per errore su keyword piu'
    specifiche che le contengono come sottostringa: es. "shirt" (categoria
    camicia) e' una sottostringa di "t-shirt" (categoria t-shirt), quindi
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
        return True, f"[VENDITORE IN BLOCKLIST] L'utente '{seller}' e' nella blocklist."

    # 2. Categorie mai flippabili (lista minima -- volutamente corta, quelle
    # "teoriche" aggiunte in precedenza non si verificano mai in pratica)
    unflippable = [
        "calzini", "calze", "collant", "portachiavi", "profumi", "eau de parfum",
        "eau de toilette", "deodoranti", "cover per telefono", "ciondoli", "guinzagli",
        # calzini/calze/collant multilingua -- lo stesso bug di copertura
        # linguistica gia' visto altrove: l'italiano da solo lascia passare
        # titoli in altre lingue, sprecando foto+token fino all'occhio.
        "socken", "strumpfhose", "strümpfe",
        "socks", "tights", "stockings", "pantyhose",
        "chaussettes", "collants",
        # NOTA: il francese "bas" (calze) e' stato RIMOSSO da questa lista.
        # Era la causa di uno scarto silenzioso di annunci validi (un maglione
        # Loro Piana, uno short Engineered Garments, una t-shirt Our Legacy),
        # perche' "bas" e' anche una parola francese comunissima nelle
        # descrizioni ("en bas", "bassin", "basique") e il match a sottostringa
        # la trovava ovunque. Le calze francesi restano coperte da
        # "chaussettes" e "collants", che non hanno lo stesso problema.
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
    # Match a PAROLA INTERA (\b), non a sottostringa. Prima questa lista usava
    # un semplice "kw in testo", a differenza dei filtri danni/non-originalita'
    # sotto che gia' usavano \b: e' lo stesso bug di collisione per sottostringa
    # gia' visto con "shirt"/"t-shirt", e scartava silenziosamente annunci buoni.
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

    # 2c. Non originalita' dichiarata dal venditore stesso, multilingua
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
            return True, f"[NON ORIGINALE DICHIARATO] Rilevata keyword: '{kw}' -- venditore dichiara che non e' un pezzo originale."

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
Un privato con 0-30 recensioni che vende fast-fashion e ha sviste nel titolo è la "zona d'oro" più chiara. MA un numero alto di recensioni (es. 200, 500+) NON significa automaticamente "privato affidabile che svuota l'armadio" — potrebbe essere un rivenditore esperto che conosce perfettamente il valore dei suoi capi e prezza di conseguenza (meno probabile un vero affare). Il segnale decisivo NON è il conteggio recensioni da solo, ma COSA il venditore vende: se nel campo "Primi articoli in vendita" (quando disponibile) compaiono brand fast-fashion o generici misti a questo capo di lusso, è un forte segnale di privato genuino con guardaroba eterogeneo, anche con centinaia di recensioni accumulate negli anni. Se invece "Primi articoli in vendita" mostra solo brand di lusso/designer, è più probabile un rivenditore esperto — non significa automaticamente "prezzo non conveniente", ma alza la cautela sul fatto che il prezzo sia già "corretto" e non un errore di valutazione. Se il campo "Primi articoli in vendita" è presente nei dati, DEVI citarlo esplicitamente nell'Analisi dell'analista per giustificare il tuo giudizio sul venditore — non limitarti a dedurlo dal solo numero di recensioni. Ignora link a social nella bio (normali) o icone di scraping confuse per capi.

# ATTENZIONE AL BIAS "PREZZO TROPPO BASSO = DEVE ESSERE FALSO"
Caso reale già osservato: un capo Dries Van Noten autentico offerto a €5,95 è stato erroneamente giudicato "falso palese, Confidenza Alta" con motivazioni (font "grossolano", dettagli "generici") che un controllo indipendente ha smentito — le etichette erano in realtà coerenti col brand. Il prezzo basso aveva influenzato il giudizio nonostante l'istruzione esplicita di ignorarlo. Prima di scrivere "Probabilmente falso" con "Confidenza: Alta", fai una verifica interna: la stessa foto, con lo stesso identico dettaglio di etichetta/cucitura/font, ti sembrerebbe ugualmente sospetta se il prezzo fosse €200 invece di €6? Se la risposta è "forse no", il tuo giudizio è contaminato dal prezzo — declassa a "Sospetto, servono altre foto" con Confidenza Media, non "Probabilmente falso" con Confidenza Alta. Riserva "Probabilmente falso" + "Confidenza Alta" SOLO a discrepanze concrete, specifiche e descrivibili con precisione (non generiche tipo "font grossolano" senza specificare in cosa esattamente il font differisce dall'originale).

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

# BRAND COMPLETAMENTE ESTRANEO (non una sottolinea/diffusion — un marchio diverso)
Distingui SEMPRE due casi molto diversi quando l'etichetta reale non corrisponde al brand dichiarato nell'annuncio:
1. **Sottolinea/diffusion della stessa maison** (es. MM6 invece di Margiela mainline, See by Chloé invece di Chloé, Weekend Max Mara invece di Max Mara) — questo NON è un brand estraneo, ha ancora un valore (minore) e il Cervello deve valutarlo normalmente. Non usare il flag sotto per questi casi.
2. **Marchio completamente diverso e non correlato** (es. l'annuncio dichiara "Kapital" ma l'etichetta reale mostra "Kapitales", un brand francese di souvenir personalizzati senza alcun legame col Kapital giapponese; oppure l'annuncio dichiara un brand di lusso ma l'etichetta mostra un marchio fast-fashion generico) — qui il capo non ha alcun valore nel segmento che stai valutando, indipendentemente da condizione o prezzo.

Per il caso 2, scrivi ESPLICITAMENTE nella riga "🏷️ Legit:" la frase **"BRAND NON CORRISPONDENTE"** seguita dal nome del brand reale letto sull'etichetta, così il sistema può risparmiare la chiamata al Cervello (verdetto già scontato: NON COMPRARE, senza bisogno di comp di mercato). Usa questa frase SOLO quando sei sicuro che sia un marchio diverso e non correlato, non per semplici dubbi o quando il brand reale è comunque leggibile con Confidenza Bassa — in caso di dubbio, lascia decidere al Cervello.

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

# VENDITORE
Prezzo basso = vantaggio, mai sospetto. Se "Primi articoli in vendita" è presente nei dati: guardaroba misto fast-fashion+lusso = privato genuino (anche con centinaia di recensioni), citalo in Analisi; solo brand di lusso = probabile reseller esperto, più cauto sul fatto che il prezzo sia già corretto. Errori di battitura nel titolo = segno di privato genuino, ignorali.

# LINEE E ERE — MAI mischiare nei comp la colonna ✓ con la ✗
| Brand | ✓ Vale pieno | ✗ Vale meno / rischio fake |
|---|---|---|
| YSL | Vintage pre-2012, solo tailoring (blazer/cappotti/abiti) | Camicie/bluse (sature); borse moderne Loulou/Sac de Jour/Kate/Niki |
| Alexander McQueen | Alexander McQueen | McQ (frazione del valore) |
| Chloé | Chloé | See by Chloé |
| Stella McCartney | Mainline | Collab Adidas/activewear |
| Helmut Lang | Era Lang 1986-2005 (archivio) | Era Link Theory dal 2006 (commerciale) |
| Maison Margiela | Linee 1/10/0/22 | MM6 |
| Missoni | Pattern zigzag; M Missoni solo abiti strutturati | Missoni Sport; M Missoni basics |
| Vivienne Westwood | Gold Label (couture, alto); Anglomania (NON è "economica" — ricercatissima, top anche basic €120-250+ usati, pezzi statement/metallici valgono di più) | Red Label / collab retailer |
| Max Mara | Mainline | Weekend/Studio/Sportmax (salvo modello iconico o materiale pregiato) |
| Moschino | Couture/Mainline | Love Moschino |
| Versace | Mainline | Versace Jeans Couture / Versus |
| Armani | Giorgio / Collezioni | Emporio / Exchange |
| Arc'teryx | Veilance — SOLO se etichetta dice esplicitamente "VEILANCE" | Mainline outdoor/tecnico (se non vedi "Veilance" da nessuna parte, tratta come mainline) |
| Yohji Yamamoto | Yohji Yamamoto / Y's / S'yte / Ground Y / Wildside | Y-3 (collab Adidas, streetwear di massa — scarta SEMPRE dai comp, anche se il titolo cita "Yohji Yamamoto") |
| Junya Watanabe, Undercover, Thom Browne, Alaïa, Visvim, Kapital, 45RPM, Carol Christian Poell, Haider Ackermann, The Row, Boris Bidjan Saberi, sacai, Kiko Kostadinov | Mono-linea, rischio fake storicamente basso: valuta SEMPRE a pieno prezzo | — |

**JPG — due diffusion facilmente confuse, controlla il testo ESATTO dell'etichetta:**
"JEAN'S PAUL GAULTIER" (apostrofo dopo "Jean") → tetto rivendita realistico **€30**, non stimare sopra indipendentemente da stampe/loghi. "JPG.JEAN'S" o "JPG JEAN'S" (spesso "Collection N°...", mesh/stampe Y2K) → linea diversa, nessun tetto, valuta sui comp reali. Etichetta non leggibile → non assumere quale sia, abbassa Confidenza invece di applicare il tetto a caso. Tailoring JPG mainline (giacche/cappotti) vale di più, segue regole proprie.

**Collaborazioni con altri brand nei comp** (es. Fred Perry x Raf Simons, Y-3, See by Chloé): mai usarle come comp mainline senza dirlo. O le escludi esplicitamente dichiarandolo in Analisi, o — se il capo IN ANALISI è esso stesso quella collab — usi SOLO comp della stessa collab.

# LIQUIDITÀ PER SEGMENTO (calibra Deal, giorni di vendita, messaggio)
Archivio eclettico (Missoni, JPG, Pucci, Westwood, Mugler, Montana, Marni, Courrèges, Miu Miu): target 25-45, vendita lenta ma prezzo alto per pezzi iconici, valorizza provenienza/collezione. Quiet luxury 90s (Helmut Lang, Jil Sander, Margiela, Bottega, Max Mara): target 28-45, valorizza decade/collezione specifica, coats iconici molto più liquidi dei basic. Avantgarde (Rick Owens, Yohji, Dries, Ann Demeulemeester, Raf Simons, Loewe, Cucinelli, YSL, Chloé, Stella McCartney, Totême): community insider, alta disponibilità a premium con provenienza documentata. Giapponese/artigianale (Visvim, Kapital, CCP, Haider, The Row, Alaïa, BBS, Sacai, Kiko, Junya, Thom Browne, McQueen, Undercover): community verticale molto informata, taglie piccole 46-48 IT/S-M più liquide.

**Taglia**: standard/centrale (donna IT 40-44, uomo IT 48-52) = bacino ampio, alza liquidità. Estrema (donna <38 o >46, uomo <46 o >54) = bacino ridotto, abbassa Deal score, allunga giorni stimati, dichiaralo in Analisi. Taglia ignota = dichiara il limite, non ignorarlo.

**Stagionalità**: capo fuori stagione (invernale pesante in estate, o viceversa) = STESSO valore ma tempo di vendita più lungo — mai abbassare il prezzo per questo. Dichiara il mese consigliato per pubblicare (capispalla invernali da settembre, capi estivi da aprile).

# RICERCA E VERIFICA (usa cerca_comp_prezzo)
Comp pre-raccolti scarsi/assenti/fuori tema → cerca_comp_prezzo con query mirata prima di rispondere. Gerarchia fonti: eBay SOLD > Vinted — Ricerca visuale per foto (quando presente: e' lo stesso capo/modello, non solo lo stesso brand, il comp piu' affidabile tra gli ASK) > Vinted testo > Vestiaire.
Codici prodotto o diciture rare citati dall'occhio ("prototipo", "edizione limitata", ecc.) → verifica che esistano davvero con cerca_comp_prezzo prima di trattarli come prova di valore; se non confermati, tratta come non verificati e abbassa Confidenza, non usarli come giustificazione principale del margine.
La "Confidenza" che l'occhio dichiara su un verdetto "Probabilmente falso" NON è affidabile da sola (bias noto: prezzo molto basso può contaminare il giudizio con dettagli vaghi costruiti a posteriori) — se i dettagli citati sono generici e il prezzo è molto basso, verifica con cerca_comp_prezzo prima di confermare NON COMPRARE per sospetto falso.

# MATERIALE DEI COMP DEVE CORRISPONDERE AL CAPO
Il materiale cambia il valore quasi quanto la linea (es. Cucinelli: cashmere puro >> lana/cotone). Materiale noto (dati annuncio, etichetta leggibile) → scarta o segnala esplicitamente i comp di materiale diverso. Materiale IGNOTO (descrizione generica, nessuna etichetta leggibile) → usa il comp più ECONOMICO disponibile, mai il più caro, e dichiara in Analisi che è una stima prudente per materiale non confermato. Comp di materiali diversi con prezzi molto distanti → non fare la media, sono capi diversi.

# ANCORAGGIO PREZZI — la regola più violata in produzione, massima attenzione
Dati etichettati: **SOLD** (eBay, venduti confermati) vs **ASK** (Vinted/Vestiaire, annunci attivi NON necessariamente venduti, spesso sovrastimati). SOLD è sempre la base primaria per la stima di vendita. Solo ASK disponibile → applica sconto 20-30% prima di usarlo, mai citarlo come vendita realistica senza quello sconto.
**Controllo numerico obbligatorio, ogni volta prima di scrivere il prezzo**: la tua stima di vendita non può MAI superare il comp più alto (SOLD se disponibile) che tu stesso citi in Analisi — se lo supera, non è "prudente", è un errore: abbassala.
**Cita SEMPRE almeno 2 prezzi ESATTI verbatim** dai dati ricevuti in Analisi (mai un range parafrasato a memoria) — se il range che stai per scrivere non corrisponde a due prezzi realmente ricevuti, ricontrolla, non l'hai calcolato bene.

**PROCEDURA OBBLIGATORIA DI FILTRO OUTLIER, PRIMA di scrivere qualsiasi stima** — violazione osservata in produzione: un capo di categoria/prezzo minore (es. un singolo capo sartoriale) valutato usando come comp un capo di categoria completamente diversa e molto più costosa (es. un abito completo o un capospalla) comparso per errore nella stessa ricerca, ignorando tutti gli altri comp coerenti disponibili.
1. Elenca TUTTI i prezzi comp ricevuti per la STESSA categoria di capo (pantalone con pantalone, giacca con giacca, mai giacca con abito completo o capospalla con capo singolo).
2. Ordina questi prezzi e individua la mediana.
3. **Scarta ogni comp che supera 3× la mediana o è inferiore a 1/3 della mediana** — quasi sempre appartiene a un capo diverso (categoria, materiale o edizione), a un annuncio ASK irrealistico, o a un risultato di ricerca fuori tema finito per errore nell'elenco.
4. Calcola la stima SOLO sui comp rimasti dopo il filtro. Se dopo il filtro restano meno di 2 comp validi, dichiaralo esplicitamente in Analisi ("comp insufficienti dopo filtro outlier") e resta sulla fascia bassa/prudente, mai su un singolo comp isolato per giustificare una stima alta.
Esempio reale di violazione da evitare: comp per un capo sartoriale con prezzi €11, €40, €47, €75, €160, €170, €499, €600 (quest'ultimo per un ABITO COMPLETO, non il capo singolo in analisi) → mediana ≈ €61, il €499 e il €600 vanno scartati (>3× mediana) insieme all'€11 (<1/3 mediana); la stima corretta si basa solo su €40-170, non su €600.

Range di comp molto ampio (es. €25-200 per lo stesso brand) = quasi sempre stili diversi mescolati (basic vs lavorato/decorato) — usa solo i comp dello stesso stile del capo in analisi, mai la media di tutto il range.
Nessun comp specifico per il modello, solo per il brand in generale → usa la fascia mediana-bassa trovata, mai quella ottimistica. Se la tua stima finale supera nettamente ogni prezzo SOLD citato, stai ragionando sul prezzo retail, non sul second-hand — correggi al ribasso.

# MARGINE, SOGLIE, DECISIONE
Acquisto pieno = prezzo + protezione(~5%+€0,70) + spedizione (IT €2,50, EU €4,50-6). Incasso reale = prezzo listing stimato×0,80. Margine netto = incasso reale − acquisto pieno.
**COMPRA**: margine ≥€20 E ROI ≥100%. Sotto soglia → TRATTA o NON COMPRARE.
**Obiettivo operativo margine ≥€50** (calibrazione, non soglia rigida): se molto sotto, abbassa il Deal score e dichiaralo in Analisi ("margine sotto l'obiettivo operativo"), ma la Decisione resta guidata solo da €20/100%.
**Alta urgenza**: SOLO se margine ≥€30 E ROI ≥150% E comp specifici verificabili citati (mai per stime generiche di valore del brand senza comp). Altrimenti Media o Bassa, mai Alta.
**Trattativa**: sconto massimo 40% sul PREZZO PRODOTTO (mai sulla spedizione). TRATTA solo se l'Obiettivo trattativa, calcolato a quello sconto massimo, raggiunge DA SOLO ≥€20/≥100% — se anche a sconto massimo non ci arriva, la decisione corretta è NON COMPRARE, non ha senso negoziare per un obiettivo che comunque non risolve nulla. L'incasso nell'Obiettivo trattativa deve essere IDENTICO a quello del verdetto principale (cambia solo il costo d'acquisto, mai la stima di vendita): verifica margine_trattativa = incasso_principale − costo_trattato prima di scriverlo.

# TRASPARENZA OBBLIGATORIA
Se scrivi "Rischio fake: Alto" o menzioni falso/contraffatto/non autentico, specifica SEMPRE il motivo esatto (font etichetta, cuciture, materiale, wash tag incoerente, proporzioni logo) — mai "rischio alto" senza spiegazione, l'utente deve sapere COSA ha insospettito.

# FORMATO — non deviare
Emoji verdetto ESCLUSIVE: 🟢 COMPRA · 🟡 TRATTA · 🔴 NON COMPRARE · 🔵 CHIEDI ALTRE FOTO (mai ✅⚠️❌, riservate al legit check dell'occhio). Urgenza ESATTAMENTE "Alta urgenza"/"Media urgenza"/"Bassa urgenza", mai sinonimi.

# PRIMA DI RISPONDERE — verifica in ordine, correggi se necessario
1. Margine/ROI supportano la Decisione (soglia €20/100%)?
2. Se TRATTA: l'Obiettivo trattativa raggiunge DA SOLO €20/100%? Se no → NON COMPRARE.
3. Se "Alta urgenza": margine ≥€30 E ROI ≥150% E comp specifici citati? Se no → Media urgenza.
4. La stima di vendita supera il comp più alto (SOLD) citato in Analisi? Se sì → abbassala.
5. Il materiale dei comp usati corrisponde al capo? Se materiale ignoto, hai usato il comp più economico?
6. L'Obiettivo trattativa rispetta il 40% massimo sul prodotto (mai sulla spedizione)?

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
    """Manda 'text' con i bottoni inline in fondo. Bug corretto il 2026-09-19:
    a differenza di telegram_send_message, questa funzione non spezzava mai
    il testo -- oltre 4096 caratteri (limite Telegram per sendMessage) la
    richiesta falliva con lo STESSO errore sia col tentativo Markdown sia col
    retry senza parse_mode (il limite di lunghezza non c'entra col parse_mode),
    quindi l'intero messaggio testuale spariva silenziosamente: le foto
    (mandate prima, in una chiamata separata) arrivavano, il verdetto/analisi
    no. Osservato in produzione con DEBUG_CONFRONTO_COMP_TELEGRAM=true (il
    pool di ricerca grezzo in coda al messaggio spingeva facilmente oltre
    4096), ma il bug esisteva a prescindere per qualunque messaggio
    abbastanza lungo. Ora usa lo stesso chunking di telegram_send_message,
    con i bottoni spostati sull'ULTIMO chunk (dove servono davvero: aprire
    l'annuncio/scrivere al venditore dopo aver letto tutto)."""
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
    if not chunks:
        chunks = [text]

    keyboard = {"inline_keyboard": [[
        {"text": "🔗 Apri su Vinted", "url": url_annuncio},
    ]]}
    if item_id:
        keyboard["inline_keyboard"].append([
            {"text": "💬 Scrivi venditore", "url": f"https://www.vinted.it/items/{item_id}"},
        ])

    for i, chunk in enumerate(chunks):
        e_ultimo_chunk = (i == len(chunks) - 1)
        payload_base = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if e_ultimo_chunk:
            payload_base["reply_markup"] = keyboard
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={**payload_base, "parse_mode": "Markdown"},
            timeout=20,
        )
        if not resp.ok:
            log.warning(
                "telegram_send_with_buttons: Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode",
                resp.status_code, resp.text[:300],
            )
            requests.post(f"{TELEGRAM_API}/sendMessage", json=payload_base, timeout=20)


# ---------------------------------------------------------------------------
# PARSING MESSAGGI E SCRAPING VINTED
# ---------------------------------------------------------------------------

URL_REGEX = re.compile(r"https?://(?:www\.)?vinted\.[a-z]+/items/\S+", re.IGNORECASE)
# Tollerante sia al vecchio formato del servizio a pagamento (parole "Price"/
# "Brand" letterali) sia al nuovo formato solo-emoji di Vinted-Notifications
# (💰/🏷️ senza parole) -- prima riconosceva SOLO il vecchio formato, quindi
# passando a un tracker diverso prezzo e brand risultavano sempre vuoti ("?").
PRICE_REGEX = re.compile(
    r"(?:Price\s*:\s*|Prezzo\s*:\s*|💰\s*|💶\s*)([\d]+(?:[.,]\d+)?)\s*(?:EUR|€)?",
    re.IGNORECASE,
)
BRAND_REGEX = re.compile(
    r"(?:Brand\s*:\s*|Marca\s*:\s*|🏷️\s*|🛍️\s*)(.+)",
    re.IGNORECASE,
)


def parse_vinted_tracker_message(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    for line in lines:
        line_lower = line.lower()
        # Salta le righe di prezzo/brand in ENTRAMBI i formati (vecchio a
        # parole, nuovo a emoji), cosi' non vengono scambiate per titolo.
        e_riga_prezzo = line_lower.startswith(("price", "prezzo")) or "price" in line_lower or line.startswith(("💰", "💶"))
        e_riga_brand = line_lower.startswith(("brand", "marca")) or line.startswith(("🏷️", "🛍️"))
        if e_riga_prezzo or e_riga_brand:
            continue
        # Rimuove QUALSIASI emoji iniziale (non solo "📌" come prima) -- il
        # bug del titolo con emoji duplicata (es. "🆕 🆕 Titolo") veniva da
        # qui: il vecchio codice toglieva solo "📌 ", quindi con un titolo
        # tracker che iniziava per "🆕 " quell'emoji restava nel testo salvato
        # e l'header del bot ne aggiungeva un'altra sopra.
        cleaned = re.sub(r"^[\U0001F000-\U0001FFFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]+\s*", "", line).strip()
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
if VINTED_ACCESS_TOKEN:
    _vinted_session.cookies.set("access_token_web", VINTED_ACCESS_TOKEN, domain=".vinted.it")
if VINTED_REFRESH_TOKEN:
    _vinted_session.cookies.set("refresh_token_web", VINTED_REFRESH_TOKEN, domain=".vinted.it")


def _jwt_scaduto(token, margine_secondi=120):
    """Decodifica (senza verificarne la firma -- non ci serve, ci fidiamo
    della fonte visto che l'ha inserito l'utente stesso in una env var) il
    campo 'exp' di un JWT Vinted (access_token_web/refresh_token_web sono
    entrambi JWT, visto nel payload reale catturato il 2026-09-19: struttura
    header.payload.firma in base64url) per sapere se e' scaduto SENZA fare
    una richiesta di rete a vuoto. Margine di 120s per non rischiare di
    usare un token che scade a meta' di una richiesta in corso. Se il
    parsing fallisce per qualunque motivo (token vuoto, formato inatteso,
    campo mancante), lo tratta come scaduto per sicurezza -- meglio un
    fallback alla ricerca visuale disattivata che un crash o un loop."""
    if not token:
        return True
    try:
        parti = token.split(".")
        if len(parti) != 3:
            return True
        payload_b64 = parti[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # padding base64url
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if not exp:
            return True
        return time.time() >= (exp - margine_secondi)
    except Exception:
        return True

# ---------------------------------------------------------------------------
# PROXY (opzionale) -- rotazione sulle richieste dirette a Vinted, stesso
# tipo di protezione gia' attiva sul tracker gratuito (Vinted-Notifications).
# Formato variabile d'ambiente PROXY_LIST: URL completi separati da virgola,
# es. "http://utente:password@p.webshare.io:80,http://utente:password@p2..."
# -- lo trovi copiandoli dalla dashboard Webshare (o qualunque provider).
# Se la variabile non e' impostata, il bot funziona esattamente come prima
# (nessuna proxy, richieste dirette) -- nessun rischio di rottura.
_PROXY_LIST_RAW = os.environ.get("PROXY_LIST", "").strip()
PROXY_LIST = [p.strip() for p in _PROXY_LIST_RAW.split(",") if p.strip()] if _PROXY_LIST_RAW else []
_proxy_indice_rotazione = [0]

if PROXY_LIST:
    log.info("Proxy attivi: %d indirizzi caricati da PROXY_LIST, in rotazione round-robin.", len(PROXY_LIST))
else:
    log.info("Nessun PROXY_LIST impostato -- richieste dirette senza proxy (comportamento originale).")


def _prossimo_proxy():
    """Restituisce il prossimo proxy in rotazione round-robin, o None se
    PROXY_LIST e' vuota (nessuna proxy configurata)."""
    if not PROXY_LIST:
        return None
    proxy_url = PROXY_LIST[_proxy_indice_rotazione[0] % len(PROXY_LIST)]
    _proxy_indice_rotazione[0] += 1
    return {"http": proxy_url, "https": proxy_url}


def _vinted_get_con_retry(url, timeout=15, max_retries=3, headers_extra=None):
    """GET con retry per lo scraping Vinted. In precedenza un singolo timeout
    faceva fallire l'intero scraping (foto, descrizione, venditore tutti
    vuoti), costringendo il cervello a lavorare quasi alla cieca.

    Impone anche una pausa minima rispetto alla richiesta Vinted precedente
    (qualunque essa fosse): dopo ~13h di attivita' continua, Vinted ha
    iniziato a rispondere 403 Forbidden in modo ricorrente, probabile
    rate-limit per volume di richieste troppo fitte.

    headers_extra: header aggiuntivi/di override per questa singola chiamata
    (es. Referer/Sec-Fetch-Site per simulare un click interno al sito invece
    di un arrivo diretto dall'esterno) -- fusi sopra VINTED_HEADERS, non
    toccano le altre chiamate."""
    tempo_trascorso = time.time() - _vinted_timestamp_ultima_richiesta[0]
    if tempo_trascorso < PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI:
        time.sleep(PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI - tempo_trascorso)

    headers_richiesta = VINTED_HEADERS if not headers_extra else {**VINTED_HEADERS, **headers_extra}

    ultimo_errore = None
    for tentativo in range(1, max_retries + 1):
        try:
            _vinted_timestamp_ultima_richiesta[0] = time.time()
            resp = _vinted_session.get(url, headers=headers_richiesta, timeout=timeout, proxies=_prossimo_proxy())
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
        "photo_urls": [], "cover_photo_id": None, "size": None, "condition": None, "description": None,
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
        html_pagina = resp.text

        marker_venditore = re.search(r'data-testid="profile-username"', html_pagina)

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

        foto_complete = _estrai_foto(html_pagina)
        if marker_venditore:
            foto_tagliate = _estrai_foto(html_pagina[:marker_venditore.start()])
            if 0 < len(foto_tagliate) and len(foto_complete) - len(foto_tagliate) <= 2:
                best_url_by_photo_id = foto_tagliate
            else:
                best_url_by_photo_id = foto_complete
        else:
            best_url_by_photo_id = foto_complete

        result["photo_urls"] = list(best_url_by_photo_id.values())[:MAX_GALLERY_PHOTOS]
        # Il photo_id della cover (prima foto) e' potenzialmente lo stesso ID
        # accettato dal parametro "search_by_image_id" del bottone Vinted
        # "Cerca articoli simili" (stesso formato osservato in produzione:
        # es. "02_015a4_6DEmrNgrJhNwjhWvNPecp79k"). NON confermato in modo
        # definitivo (nessun accesso di rete a Vinted da qui per testarlo),
        # ma se corretto permette di ottenere comp per-foto (non solo per
        # brand/categoria testuale) riusando tutta l'infrastruttura Serper
        # gia' esistente, senza browser. Vedi build_vinted_visual_search_url.
        if best_url_by_photo_id:
            result["cover_photo_id"] = next(iter(best_url_by_photo_id.keys()), None)

        size_match = re.search(r'"size_title"\s*:\s*"([^"]+)"', html_pagina)
        if size_match:
            result["size"] = size_match.group(1)

        condition_match = re.search(r'itemprop="status"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if condition_match:
            result["condition"] = condition_match.group(1).strip()

        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html_pagina)
        if desc_match:
            try:
                result["description"] = desc_match.group(1).encode().decode("unicode_escape")
            except Exception:
                result["description"] = desc_match.group(1)

        # Tentativi multipli per la data di pubblicazione. Vinted ha cambiato
        # formato: i pattern "classici" non matchano piu' in modo affidabile.
        # Aggiunte varianti con virgolette ESCAPATE (\"created_at\":...), tipiche
        # del payload React Server Components -- stesso trucco gia' usato con
        # successo per seller_id.
        created_match = re.search(r'\\?"created_at_ts\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)
        if not created_match:
            created_match = re.search(r'\\?"created_at\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)
        if not created_match:
            created_match = re.search(r'\\?"createdAt\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)

        epoch_match = None
        if not created_match:
            epoch_match = re.search(r'\\?"created_at_ts\\?"\s*:\s*(\d{10,13})', html_pagina)
            if not epoch_match:
                epoch_match = re.search(r'\\?"createdAtTs\\?"\s*:\s*(\d{10,13})', html_pagina)
            if not epoch_match:
                epoch_match = re.search(r'\\?"created_at\\?"\s*:\s*(\d{10,13})', html_pagina)

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
            # Declassato da WARNING a DEBUG: e' diventato sistematico su ogni
            # annuncio (Vinted rende la pagina lato client), quindi come
            # WARNING inondava i log senza aggiungere informazione. L'eta'
            # dell'annuncio e' comunque un dato secondario: il tracker
            # notifica entro ~25s dalla pubblicazione, quindi in pratica
            # ogni annuncio che arriva qui e' "appena pubblicato".
            log.debug(
                "Data di pubblicazione non trovata per %s (rendering lato client Vinted, atteso).",
                url,
            )

        catalog_matches = re.findall(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"', html_pagina)
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

        material_match = re.search(r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if material_match:
            result["material_raw"] = material_match.group(1).strip()
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(material_match.group(1).strip())

        if not result["material_per_ricerca"] and result.get("description"):
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(result["description"])

        color_match = re.search(r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if color_match:
            result["color_raw"] = color_match.group(1).strip()

        # ---- DATI VENDITORE E SELLER_LOGIN (con blocklist compatibility) ----
        seller_login_m = re.search(r'data-testid="profile-username"[^>]*>([^<]{2,40})<', html_pagina)
        if seller_login_m:
            result["seller_login"] = seller_login_m.group(1).strip()
        else:
            seller_login_m2 = re.search(r'"(?:user|seller)"\s*:\s*\{[^}]*"login"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html_pagina)
            if not seller_login_m2:
                seller_login_m2 = re.search(r'"(?:login|user_login)"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html_pagina)
            if seller_login_m2:
                result["seller_login"] = seller_login_m2.group(1)

        seller_id_m = re.search(r'href="/member/(\d+)"', html_pagina)
        if seller_id_m:
            result["seller_id"] = seller_id_m.group(1)
        else:
            seller_id_m2 = re.search(r'"user_id"\s*:\s*(\d+)', html_pagina)
            if seller_id_m2:
                result["seller_id"] = seller_id_m2.group(1)
            else:
                # Formato React Server Components scoperto in produzione:
                # \"seller_id\":49465070 -- chiave diversa da "user_id" E
                # valore numerico puro (non tra virgolette). Gestisce sia
                # la variante con virgolette escapate (\") sia quella normale.
                seller_id_m3 = re.search(r'\\?"seller_id\\?"\s*:\s*(\d+)', html_pagina)
                if seller_id_m3:
                    result["seller_id"] = seller_id_m3.group(1)

        rating_m = re.search(r'valutazione di\s+([\d.,]+)\s+su\s+5\s+stelle', html_pagina, re.IGNORECASE)
        if rating_m:
            try:
                result["seller_feedback_reputation"] = float(rating_m.group(1).replace(",", "."))
            except ValueError:
                pass
        else:
            feedback_rep_m2 = re.search(r'"feedback_reputation"\s*:\s*([\d.]+)', html_pagina)
            if feedback_rep_m2:
                try:
                    result["seller_feedback_reputation"] = float(feedback_rep_m2.group(1))
                except ValueError:
                    pass

        count_m = re.search(r'web_ui__Rating__label[^>]*>\s*<span[^>]*>\s*(\d+)\s*<', html_pagina)
        if count_m:
            result["seller_feedback_count"] = int(count_m.group(1))
        else:
            feedback_count_m2 = re.search(r'"feedback_count"\s*:\s*(\d+)', html_pagina)
            if feedback_count_m2:
                result["seller_feedback_count"] = int(feedback_count_m2.group(1))

        items_count_m = re.search(r'"items_count"\s*:\s*(\d+)', html_pagina)
        if items_count_m:
            result["seller_items_count"] = int(items_count_m.group(1))

        country_m = re.search(r'"country_title_local"\s*:\s*"([^"]{2,30})"', html_pagina)
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
                resp_profilo = _vinted_get_con_retry(profilo_url, timeout=12, max_retries=2)
                if resp_profilo is not None and resp_profilo.ok:
                    html_profilo = resp_profilo.text
                    # SOLO questo pattern e' verificato su HTML reale:
                    # data-testid="other_user_items-N--description-title">Brand</p>.
                    # I fallback generici su "title":"..." erano un problema
                    # serio: estraevano nomi di CATEGORIE del menu invece degli
                    # articoli reali -- dato sbagliato ma plausibile, piu'
                    # pericoloso di nessun dato perche' alimentava il giudizio
                    # sul venditore con informazioni false.
                    titoli = re.findall(
                        r'data-testid="other_user_items-\d+--description-title">([^<]+)<',
                        html_profilo
                    )

                    diagnostica_markup = ""
                    if not titoli:
                        idx = html_profilo.find("other_user_items")
                        if idx == -1:
                            diagnostica_markup = " [stringa 'other_user_items' assente dalla risposta HTTP grezza -- rendering lato client via JS, non catturabile senza browser headless]"
                        else:
                            estratto = html_profilo[max(0, idx - 50):idx + 150].replace("\n", " ")
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
                        # Declassato a DEBUG: sistematico su tutti i profili
                        # (rendering lato client), inutile come INFO ricorrente.
                        log.debug("Scraping guardaroba venditore: pagina caricata ma nessun titolo estratto per %s", profilo_url)
                    else:
                        result["seller_wardrobe_debug"] = f"ok: {len(titoli_unici)} titoli trovati"
                else:
                    result["seller_wardrobe_debug"] = "fetch fallito dopo i retry (nessuna risposta valida)"
                    log.debug("Scraping guardaroba venditore fallito (nessuna risposta valida) per %s", profilo_url)
            except Exception as e:
                result["seller_wardrobe_debug"] = f"eccezione durante il parsing: {e}"
                log.warning("Scraping guardaroba venditore fallito (eccezione): %s", e)
        else:
            result["seller_wardrobe_debug"] = "nessun seller_id/seller_login trovato nella pagina annuncio -- profilo mai contattato"
            log.debug("Guardaroba venditore non tentato: ne' seller_id ne' seller_login trovati per %s", url)

    except Exception as e:
        log.warning("Scraping Vinted fallito per %s: %s", url, e)

    return result


def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=3):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    # TEMP DIAGNOSTIC: this used to swallow every failure silently (bare
    # "except Exception: pass" and no logging even on a non-ok status), so
    # there was no way to tell a 403/429 rate-limit apart from a timeout or
    # a proxy connection failure from the logs alone. Remove once diagnosed.
    ultimo_dettaglio = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = _vinted_session.get(url, headers=headers, timeout=18, proxies=_prossimo_proxy())
            if resp.ok:
                return resp.content
            ultimo_dettaglio = f"HTTP {resp.status_code}"
        except Exception as e:
            ultimo_dettaglio = f"{type(e).__name__}: {e}"
        time.sleep(0.6 * attempt)
    log.warning(
        "download_image_bytes: fallito dopo %d tentativi per %s -- ultimo errore: %s",
        max_retries, url, ultimo_dettaglio,
    )
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


def costo_gemini_token(usage, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT):
    inp = usage.get("promptTokenCount", 0) or 0
    out = usage.get("candidatesTokenCount", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


def chiama_gemini(system_prompt, user_text, photo_bytes_list=None, grounding=False, max_retries=4,
                  api_url=GEMINI_API_URL_OCCHIO, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT):
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
            resp = requests.post(api_url, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
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
                    costo = costo_gemini_token(usage, prezzo_input, prezzo_output) + n_query * PREZZO_GROUNDING_PER_QUERY
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
    che la categoria non sia stata saltata per mancata rilevazione.

    Soglia abbassata da 5 a 3 (controllo costi, Pareto): i comp pre-raccolti
    sono gia' inclusi nel costo Serper esistente, mentre ogni ricerca extra
    che il Cervello decide di forzare quando questa funzione ritorna False
    e' un giro di chiamata Gemini aggiuntivo (il costo piu' caro e variabile
    del bot, vedi MAX_ROUNDS_FUNZIONE). 3 prezzi reali gia' anticipano quasi
    sempre un range utilizzabile, senza dover pagare per scoprirlo."""
    if not comps_text:
        return False
    if "Categoria non rilevata" in comps_text:
        return False
    n_prezzi = len(re.findall(r"€\s*\d", comps_text)) + len(re.findall(r"EUR\s*[\d.,]+", comps_text))
    return n_prezzi >= 3


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


def chiama_gemini_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4,
                                    api_url=GEMINI_API_URL_CERVELLO, prezzo_input=PREZZO_CERVELLO_INPUT, prezzo_output=PREZZO_CERVELLO_OUTPUT):
    """Variante del cervello con function calling. Se forza_ricerca=True, il
    primo giro DEVE chiamare cerca_comp_prezzo (mode ANY). Se False, il tool
    resta disponibile ma la scelta e' lasciata al modello (mode AUTO).

    Gestisce fino a MAX_ROUNDS_FUNZIONE giri di ricerca: se dopo aver
    ricevuto un risultato (es. una ricerca fallita per crediti Serper
    esauriti) il modello prova a richiamare di nuovo la funzione invece di
    rispondere, i giri precedenti lasciavano il messaggio Telegram vuoto
    (solo header, verdetto assente) perche' la seconda risposta veniva letta
    come testo finale anche quando conteneva solo un'altra richiesta di
    funzione. All'ultimo giro consentito, il tool viene dichiarato con
    "mode: NONE" esplicito (non piu' omesso del tutto: omettere "tools" non
    disattivava davvero il function calling quando la conversazione conteneva
    gia' uno scambio functionCall/functionResponse precedente -- bug
    osservato in produzione su quasi ogni item il 2026-09-13) per costringere
    il modello a rispondere con un verdetto testuale usando qualunque dato
    abbia gia' raccolto. Se anche cosi' il modello insiste con una
    functionCall, un ultimo tentativo di fallback (senza "tools" nel payload
    e con un turno "user" esplicito) prova a recuperare comunque un
    verdetto testuale prima di arrendersi."""
    contents = [{"role": "user", "parts": [{"text": user_text}]}]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []  # testo grezzo di ogni cerca_serper_mirata riuscita in
                              # questa chiamata -- usato da verifica_comp_citati_sono_reali
                              # per controllare che i prezzi citati in Analisi provengano
                              # davvero dai dati di ricerca, non da una stima "a memoria".
    MAX_ROUNDS_FUNZIONE = 2  # Rialzato da 1 a 2 il 2026-09-14. Con 1, i log
                             # mostravano che ~1 item su 2 finiva comunque nel
                             # fallback forzato (vedi sotto), che nel caso
                             # peggiore costa quanto il vecchio "2 giri" (3
                             # chiamate totali), ma senza dare al modello la
                             # seconda ricerca reale che chiedeva -- lo
                             # zittisce e basta, verdetto su comp che il
                             # modello stesso riteneva insufficienti. Con
                             # MAX_ROUNDS_FUNZIONE=2 il caso "un giro basta"
                             # costa uguale a prima (2 chiamate), il caso
                             # "serve una seconda ricerca" costa uguale al
                             # fallback di oggi (3 chiamate) ma con una
                             # ricerca vera al posto del rifiuto secco --
                             # stesso costo nel caso peggiore, qualita'
                             # probabilmente migliore. Se il costo medio reale
                             # sale sensibilmente rispetto a questa attesa
                             # (monitorare il footer costo su Telegram),
                             # il primo sospetto e' che il modello chieda
                             # ricerca extra anche quando non servirebbe --
                             # in quel caso riconsiderare, non tornare a 1
                             # alla cieca.

    def _chiama_gemini_raw(tool_mode, tools_abilitati, tentativi_rimasti, omit_tools=False):
        # NOTA: "tools_abilitati" e' ora vestigiale per i giri normali (le
        # funzioni vengono sempre dichiarate, con mode esplicito -- vedi fix
        # sotto). "omit_tools" resta per il SOLO tentativo di fallback finale,
        # dove vogliamo omettere "tools" e "tool_config" del tutto (zero
        # ambiguita' possibile), a differenza del fix normale che dichiara
        # sempre la funzione con mode "NONE".
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
            # thinkingConfig esplicito + maxOutputTokens alzato a 10000 (era
            # 3000 senza thinkingConfig; poi 6000 -- ANCORA insufficiente in
            # produzione: bug ripetuto su Loro Piana con 2 giri di ricerca
            # anche a 6000, quindi alzato di nuovo). Bug reale: con
            # gemini-3.7-flash (a differenza del 3.1-flash-lite originale)
            # il "pensiero" interno + il verdetto strutturato finale possono
            # insieme superare budget piu' bassi su casi complessi (piu' giri
            # di ricerca, comp multipli da citare) -- risultato: "il modello
            # non ha prodotto una risposta testuale", credito Gemini speso,
            # nessun verdetto. Vedi il log diagnostico su finishReason/
            # thoughtsTokenCount piu' sotto se ricapita anche a 10000: dira'
            # se e' ancora un problema di budget (finishReason=MAX_TOKENS) o
            # qualcos'altro.
            # thinkingLevel="low" (non il default "medium"): scelta
            # deliberata su costo/velocita' -- i token di pensiero sono
            # fatturati come output e a "medium" possono essere ~6x i token
            # della risposta finale (dato da benchmark indipendenti sul
            # modello gemello 3.6 Flash). "low" e' significativamente piu'
            # economico e piu' veloce, e benchmark indipendenti non mostrano
            # un guadagno di accuratezza affidabile sopra "low" per molti
            # task -- ma non e' stato specificamente testato sul compito di
            # questo Cervello (valutazione prezzi second-hand). Se dopo
            # qualche giorno tornano quotazioni incoerenti come il caso
            # Kapital/Kapitales o le due camicie Our Legacy, il primo
            # tentativo e' alzare questo a "medium", non aggiungere altre
            # reti di sicurezza.
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 10000,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        # FIX: la funzione va sempre dichiarata (anche quando tool_mode=="NONE"),
        # altrimenti "mode: NONE" non viene mai comunicato a Gemini -- prima
        # venivano omessi sia "tools" sia "tool_config" quando tools_abilitati
        # era False, e il modello, avendo gia' in "contents" uno scambio
        # model->functionCall / user->functionResponse dal giro precedente,
        # continuava a restituire un'altra functionCall invece di testo anche
        # senza funzioni dichiarate in quel turno (bug osservato in produzione
        # su quasi ogni item: Lemaire, Max Mara, Mugler, Miu Miu, Cucinelli,
        # Jil Sander, Loewe, Toteme, Rick Owens, Helmut Lang, JPG -- log
        # 2026-09-13). Dichiarare sempre "tools" ma con mode "NONE" esplicito
        # e' il meccanismo ufficiale Gemini per vietare la chiamata pur
        # lasciando la funzione visibile, e rimuove l'ambiguita' che il
        # modello aveva quando le funzioni sparivano di colpo dallo schema.
        if not omit_tools:
            payload["tools"] = [{"function_declarations": [CERVELLO_FUNCTION_DECLARATION]}]
            payload["tool_config"] = {"function_calling_config": function_calling_config}

        backoff_seconds = 2
        for attempt in range(1, tentativi_rimasti + 1):
            try:
                resp = requests.post(api_url, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
                if not resp.ok:
                    log.warning("Gemini (cervello forzato) HTTP %d: %s", resp.status_code, resp.text[:500])
                    if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    resp.raise_for_status()
                return resp.json()
            except Exception:
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
            return f"[ERRORE: cervello forzato fallito. Eccezione: {e}]", costo_totale, n_query_extra, ricerche_extra_raw

        candidates = data.get("candidates", [])
        if not candidates:
            return "[ERRORE: risposta Gemini senza candidates]", costo_totale, n_query_extra, ricerche_extra_raw

        usage = data.get("usageMetadata", {})
        costo_totale += costo_gemini_token(usage, prezzo_input, prezzo_output)

        parts = candidates[0].get("content", {}).get("parts", []) or []
        function_call = next((p.get("functionCall") for p in parts if p.get("functionCall")), None)

        if function_call and not ultimo_giro:
            query_richiesta = function_call.get("args", {}).get("query", "")
            log.info("Cervello Gemini ha richiesto ricerca mirata (giro %d/%d): '%s'", round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
            risultato_ricerca = cerca_serper_mirata(query_richiesta)
            n_query_extra += 1
            # Tagga il risultato con la query usata (Serper/google.serper.dev
            # search, non uno scrape di pagina) -- senza questo la query resta
            # visibile solo nei log, non nel pool che finisce nel messaggio
            # Telegram di debug (DEBUG_CONFRONTO_COMP_TELEGRAM).
            ricerche_extra_raw.append(
                f"\n📍 FONTE: RICERCA ON-DEMAND CERVELLO (Serper google search, query: '{query_richiesta}')\n{risultato_ricerca}"
            )

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

        if function_call and ultimo_giro:
            # RETE DI SICUREZZA RESIDUA: anche con "tools" dichiarato e mode
            # "NONE" esplicito (fix sopra), se il modello dovesse ANCORA
            # restituire una functionCall invece di testo (bug lato Gemini
            # non escludibile del tutto vista la ricorrenza osservata), non
            # buttiamo via i comp gia' raccolti. Un solo tentativo extra,
            # esplicito, senza alcuna dichiarazione di funzioni nel payload
            # (nessuna ambiguita' possibile) e con un turno "user" che dice
            # chiaramente di smettere di cercare e rispondere con i dati
            # disponibili.
            log.warning(
                "Cervello: functionCall ricevuta anche all'ultimo giro nonostante mode=NONE "
                "esplicito -- tentativo fallback forzato senza tools dichiarati."
            )
            contents.append({"role": "model", "parts": parts})
            contents.append({
                "role": "user",
                "parts": [{
                    "text": (
                        "Le ricerche sono terminate: non puoi e non devi chiamare "
                        "nessuna funzione. Rispondi ORA con il verdetto testuale "
                        "completo, usando esclusivamente i dati e i comp gia' "
                        "raccolti in questa conversazione."
                    )
                }]
            })
            try:
                data_fallback = _chiama_gemini_raw(
                    tool_mode="NONE", tools_abilitati=False, tentativi_rimasti=max_retries,
                    omit_tools=True,
                )
            except Exception as e:
                return (
                    f"[ERRORE: cervello forzato fallito nel tentativo fallback. Eccezione: {e}]",
                    costo_totale, n_query_extra, ricerche_extra_raw,
                )
            candidates_fb = data_fallback.get("candidates", [])
            usage_fb = data_fallback.get("usageMetadata", {})
            costo_totale += costo_gemini_token(usage_fb, prezzo_input, prezzo_output)
            parts_fb = (candidates_fb[0].get("content", {}).get("parts", []) if candidates_fb else []) or []
            testo_fb = "".join(p.get("text", "") for p in parts_fb)
            if testo_fb.strip():
                return testo_fb, costo_totale, n_query_extra, ricerche_extra_raw
            finish_reason_fb = candidates_fb[0].get("finishReason", "?") if candidates_fb else "?"
            return (
                f"[ERRORE: il modello ha insistito con una function call anche nel tentativo "
                f"fallback finale -- finishReason={finish_reason_fb}]"
            ), costo_totale, n_query_extra, ricerche_extra_raw

        testo = "".join(p.get("text", "") for p in parts)
        if testo.strip():
            return testo, costo_totale, n_query_extra, ricerche_extra_raw

        # DIAGNOSTICA per capire perche' il testo e' vuoto. Bug ricorrente
        # osservato in produzione con DUE varianti distinte finora:
        # 1. finishReason=MAX_TOKENS -- budget di pensiero+output esaurito
        #    (gia' mitigato alzando maxOutputTokens e limitando thinkingLevel).
        # 2. finishReason=STOP (completamento NORMALE, non troncato) con
        #    thoughtsTokenCount assente e testo comunque vuoto -- causa
        #    diversa e non ancora capita, il fix del budget non basta qui.
        # Loggato ora il JSON grezzo completo di parts/candidate (troncato)
        # cosi' se ricapita abbiamo la struttura esatta (es. se "parts" e'
        # una lista vuota, se contiene un part con "thought": true senza
        # "text", se c'e' un safetyRatings che blocca in silenzio, ecc.)
        # invece di dover indovinare di nuovo con solo due numeri.
        finish_reason = candidates[0].get("finishReason", "?")
        thoughts_tokens = usage.get("thoughtsTokenCount", "?")
        output_tokens = usage.get("candidatesTokenCount", "?")
        safety_ratings = candidates[0].get("safetyRatings", "assenti")
        log.warning(
            "Cervello: testo vuoto al giro %d/%d -- finishReason=%s, thoughtsTokenCount=%s, "
            "candidatesTokenCount=%s, maxOutputTokens configurato=%s, n_parts=%d, "
            "safetyRatings=%s\nDUMP GREZZO parts: %s\nDUMP GREZZO candidate (senza content): %s",
            round_idx + 1, MAX_ROUNDS_FUNZIONE + 1, finish_reason, thoughts_tokens,
            output_tokens, 10000, len(parts), safety_ratings,
            json.dumps(parts, ensure_ascii=False)[:1500],
            json.dumps({k: v for k, v in candidates[0].items() if k != "content"}, ensure_ascii=False)[:800],
        )

        if not ultimo_giro:
            # Nessun testo e nessuna function call valida (raro): un altro giro
            continue
        return (
            f"[ERRORE: il modello non ha prodotto una risposta testuale dopo i tentativi di ricerca "
            f"-- finishReason={finish_reason}, thinking={thoughts_tokens} token]"
        ), costo_totale, n_query_extra, ricerche_extra_raw

    return "[ERRORE: tentativi esauriti]", costo_totale, n_query_extra, ricerche_extra_raw


# ---------------------------------------------------------------------------
# CERVELLO OPENAI CON FUNCTION CALLING (equivalente GPT-4o-mini)
# ---------------------------------------------------------------------------
# Stessa logica del cervello Gemini sopra (multi-round di ricerca via
# cerca_serper_mirata, poi verdetto testuale finale), ma nel formato Chat
# Completions di OpenAI. Molto piu' semplice del gemello Gemini perche'
# "tool_choice": "required" e' vincolante in modo affidabile in OpenAI -- non
# servono i workaround osservati con Gemini (mode "NONE" dichiarato sempre,
# fallback senza tools, diagnostica su testo vuoto): qui un tool_choice
# esplicito basta, e un messaggio senza tool_calls e' sempre una risposta
# testuale vera. Stessa firma di ritorno (testo, costo_totale, n_query_extra)
# della funzione Gemini, per restare intercambiabile nel punto di chiamata.

OPENAI_CERVELLO_TOOL = {
    "type": "function",
    "function": {
        "name": CERVELLO_FUNCTION_DECLARATION["name"],
        "description": CERVELLO_FUNCTION_DECLARATION["description"],
        "parameters": CERVELLO_FUNCTION_DECLARATION["parameters"],
    },
}


def costo_openai_token(usage, prezzo_input=PREZZO_CERVELLO_OPENAI_INPUT, prezzo_output=PREZZO_CERVELLO_OPENAI_OUTPUT):
    inp = usage.get("prompt_tokens", 0) or 0
    out = usage.get("completion_tokens", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


def _chiama_openai_raw(messages, tool_choice, tentativi_rimasti, max_retries=4):
    payload = {
        "model": OPENAI_MODEL_CERVELLO,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2000,
        "tools": [OPENAI_CERVELLO_TOOL],
        "tool_choice": tool_choice,  # "required" | "auto" | "none"
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    backoff_seconds = 2
    for attempt in range(1, tentativi_rimasti + 1):
        try:
            resp = requests.post(OPENAI_API_URL_CERVELLO, headers=headers, json=payload, timeout=90)
            if not resp.ok:
                log.warning("OpenAI (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt < tentativi_rimasti:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            raise
    raise RuntimeError("tentativi esauriti")


def chiama_openai_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4):
    """Equivalente OpenAI di chiama_gemini_cervello_forzato. Stessa firma di
    ritorno (testo, costo_totale, n_query_extra, ricerche_extra_raw) per
    restare intercambiabile nel punto di chiamata via CERVELLO_PROVIDER."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []  # vedi commento gemello in chiama_gemini_cervello_forzato
    MAX_ROUNDS_FUNZIONE = 2  # stesso limite del gemello Gemini, per parita' di costo massimo

    tool_choice = "required" if forza_ricerca else "auto"

    for round_idx in range(MAX_ROUNDS_FUNZIONE + 1):
        ultimo_giro = round_idx == MAX_ROUNDS_FUNZIONE
        try:
            data = _chiama_openai_raw(
                messages,
                tool_choice="none" if ultimo_giro else tool_choice,
                tentativi_rimasti=max_retries,
            )
        except Exception as e:
            return f"[ERRORE: cervello OpenAI fallito. Eccezione: {e}]", costo_totale, n_query_extra, ricerche_extra_raw

        choices = data.get("choices", [])
        if not choices:
            return "[ERRORE: risposta OpenAI senza choices]", costo_totale, n_query_extra, ricerche_extra_raw

        usage = data.get("usage", {})
        costo_totale += costo_openai_token(usage)

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if tool_calls and not ultimo_giro:
            call = tool_calls[0]
            try:
                query_richiesta = json.loads(call.get("function", {}).get("arguments", "{}")).get("query", "")
            except (json.JSONDecodeError, TypeError):
                query_richiesta = ""
            log.info("Cervello OpenAI ha richiesto ricerca mirata (giro %d/%d): '%s'", round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
            risultato_ricerca = cerca_serper_mirata(query_richiesta)
            n_query_extra += 1
            # Vedi commento gemello in chiama_gemini_cervello_forzato: tagga
            # il risultato con la query usata per il blocco debug Telegram.
            ricerche_extra_raw.append(
                f"\n📍 FONTE: RICERCA ON-DEMAND CERVELLO (Serper google search, query: '{query_richiesta}')\n{risultato_ricerca}"
            )

            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": risultato_ricerca,
            })
            tool_choice = "auto"  # i giri successivi non sono piu' forzati
            continue

        if tool_calls and ultimo_giro:
            # Non dovrebbe succedere quasi mai (tool_choice="none" all'ultimo
            # giro impedisce esplicitamente la tool_call), ma per simmetria
            # con il fallback Gemini gestiamo comunque il caso senza perdere
            # i comp gia' raccolti.
            log.warning("Cervello OpenAI: tool_call ricevuta anche all'ultimo giro nonostante tool_choice=none.")
            messages.append({
                "role": "user",
                "content": (
                    "Le ricerche sono terminate: non puoi e non devi chiamare nessuna "
                    "funzione. Rispondi ORA con il verdetto testuale completo, usando "
                    "esclusivamente i dati e i comp gia' raccolti in questa conversazione."
                ),
            })
            try:
                data_fb = _chiama_openai_raw(messages, tool_choice="none", tentativi_rimasti=max_retries)
            except Exception as e:
                return f"[ERRORE: cervello OpenAI fallito nel tentativo fallback. Eccezione: {e}]", costo_totale, n_query_extra, ricerche_extra_raw
            choices_fb = data_fb.get("choices", [])
            usage_fb = data_fb.get("usage", {})
            costo_totale += costo_openai_token(usage_fb)
            testo_fb = (choices_fb[0].get("message", {}).get("content") or "") if choices_fb else ""
            if testo_fb.strip():
                return testo_fb, costo_totale, n_query_extra, ricerche_extra_raw
            return "[ERRORE: il modello ha insistito con una tool_call anche nel tentativo fallback finale]", costo_totale, n_query_extra, ricerche_extra_raw

        testo = msg.get("content") or ""
        if testo.strip():
            return testo, costo_totale, n_query_extra, ricerche_extra_raw

        finish_reason = choices[0].get("finish_reason", "?")
        log.warning("Cervello OpenAI: testo vuoto al giro %d/%d -- finish_reason=%s", round_idx + 1, MAX_ROUNDS_FUNZIONE + 1, finish_reason)
        if not ultimo_giro:
            continue
        return f"[ERRORE: il modello OpenAI non ha prodotto una risposta testuale -- finish_reason={finish_reason}]", costo_totale, n_query_extra, ricerche_extra_raw

    return "[ERRORE: tentativi esauriti]", costo_totale, n_query_extra, ricerche_extra_raw


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


def _risolvi_search_by_image_id(item_id, photo_id):
    """Il photo_id della foto (estratto dall'URL CDN, es. "06_00506_...")
    NON e' l'ID accettato da search_by_image_id nel catalogo -- verificato
    empiricamente confrontando tre URL reali forniti dall'utente il
    2026-09-18: foto con photo_id "06_00506_96X4vjNZUPdRFP3X2B6rTJMR",
    endpoint "/items/{id}/search_by_image?photo_id=06_00506_..." (stesso
    photo_id in input), che REDIRIGE (HTTP 302, l'utente ha confermato che
    il browser si sposta da solo senza altri click) a
    "/catalog?search_by_image_id=05_020ea_SjsgDv3J1EKG941GCMipbmQc" -- un ID
    completamente diverso, calcolato lato server (probabile embedding
    visivo). Questa funzione replica quel passaggio con una singola GET che
    segue il redirect (requests lo fa di default), poi legge l'ID vero
    dall'URL finale (resp.url). Nessun browser necessario.

    Passa per lo stesso canale "Vinted diretto" di scrape_vinted_listing
    (via _vinted_get_con_retry, stessa pausa minima anti-rate-limit), quindi
    aggiunge una richiesta extra a quel budget -- se in futuro tornano i 403
    osservati in produzione, questa e' una delle prime cose da rivedere o
    rendere disattivabile.

    STATO DEFINITIVO (confermato il 2026-09-19, chiude l'indagine aperta il
    2026-09-18): questa feature RICHIEDE una sessione Vinted autenticata,
    punto. Non e' un problema di Referer/Sec-Fetch/header che si possa
    aggiustare lato codice -- e' un vero requisito del prodotto.

    Prova definitiva raccolta con l'utente via DevTools: la richiesta
    "search_by_image?photo_id=..." che ha prodotto il redirect 307 al
    catalogo aveva nei cookie access_token_web/refresh_token_web (JWT con
    "purpose":"access", account_id valorizzato) -- l'utente era loggato col
    proprio account personale, non anonimo. Per confermare che fosse
    davvero questo e non altro, l'utente ha poi: (1) riaperto lo STESSO URL
    esatto in incognito senza login -> ha funzionato (probabile cache lato
    Vinted/CDN su quell'URL gia' generato in precedenza dalla sessione
    autenticata); (2) provato a generare una ricerca visuale NUOVA (nuovo
    item/photo_id mai richiesto prima) sempre in incognito senza login ->
    Vinted ha richiesto il login. Il primo test da solo sarebbe stato
    ambiguo (poteva sembrare che bastasse l'URL pubblico), il secondo lo
    disambigua: senza sessione autenticata, una ricerca visuale MAI vista
    prima da Vinted non parte.

    Conclusione: il bot NON puo' e non deve usare le credenziali Vinted
    personali dell'utente per autenticarsi (rischio sull'account reale,
    uso improprio delle credenziali per uno scraper automatico, violazione
    diretta dei ToS molto piu' seria di un semplice scraping di pagine
    pubbliche). VISUAL_SEARCH_ATTIVA resta quindi permanentemente
    disattivabile via env var ma la feature va considerata chiusa: non
    investire altro tempo qui a meno che l'utente non decida esplicitamente
    di autenticare il bot con un proprio account dedicato (scelta sua, con
    consapevolezza dei rischi, mai una decisione presa in autonomia dal
    codice).

    RIAPERTA il 2026-09-19 (stesso giorno): l'utente ha scelto di procedere
    con un account Vinted dedicato/sacrificabile (mai il suo account
    principale) per questo solo scopo. VINTED_ACCESS_TOKEN/REFRESH_TOKEN
    (env var, vedi CONFIGURAZIONE in testa al file) portano quella sessione
    autenticata; se assenti o scaduti la funzione si comporta esattamente
    come nello stato "chiuso" sopra (ritorna None, nessuna rottura del
    resto della pipeline). Refresh automatico del token NON ancora
    implementato (l'endpoint esatto va ancora catturato via DevTools): per
    ora, quando l'access token scade, questa fonte torna semplicemente
    inattiva finche' l'utente non aggiorna manualmente la env var su
    Railway con un nuovo access_token_web copiato dal browser."""
    if not VISUAL_SEARCH_ATTIVA:
        return None
    if not item_id or not photo_id:
        return None
    if not VINTED_ACCESS_TOKEN or _jwt_scaduto(VINTED_ACCESS_TOKEN):
        log.info(
            "_risolvi_search_by_image_id: VINTED_ACCESS_TOKEN assente o scaduto -- "
            "fonte visuale saltata per questo item (serve un token fresco dall'account "
            "dedicato, aggiornabile su Railway)."
        )
        return None
    url_intermedio = f"https://www.vinted.it/items/{item_id}/search_by_image?photo_id={quote(photo_id)}"
    headers_referer_annuncio = {
        "Referer": f"https://www.vinted.it/items/{item_id}",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
    }
    resp = _vinted_get_con_retry(
        url_intermedio, timeout=12, max_retries=2, headers_extra=headers_referer_annuncio
    )
    if resp is None:
        return None
    if "/member/register" in resp.url or "/member/login" in resp.url:
        log.info(
            "_risolvi_search_by_image_id: redirect a login/registrazione NONOSTANTE "
            "VINTED_ACCESS_TOKEN impostato e non scaduto (%s) -- possibile token "
            "invalidato lato Vinted prima della scadenza dichiarata, o blocco Datadome "
            "sul fingerprint della richiesta (vedi nota TLS/Datadome nella docstring "
            "sopra). Fonte visuale saltata per questo item.",
            resp.url,
        )
        return None
    m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", resp.url)
    if not m:
        log.info(
            "_risolvi_search_by_image_id: redirect non ha prodotto un search_by_image_id "
            "nell'URL finale (%s) -- fonte visuale saltata per questo item.",
            resp.url,
        )
        return None
    return m.group(1)


def build_vinted_visual_search_url(item_id, photo_id, brand):
    """URL equivalente al bottone Vinted "Cerca articoli simili" + filtro
    per brand. Risolve prima il vero search_by_image_id (vedi
    _risolvi_search_by_image_id -- il photo_id della foto da solo NON
    basta), poi vi aggiunge il filtro brand. Richiede SEMPRE un brand_id
    mappato: senza filtro brand la ricerca visuale pura e' troppo ampia per
    essere un comp utile (l'utente ha verificato che il filtro brand e'
    quello che rende i risultati "molto verosimili"). Ritorna None se manca
    un ingrediente o la risoluzione fallisce -- il chiamante deve trattarlo
    come fonte assente, non come errore."""
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    if not brand_id:
        return None
    search_by_image_id = _risolvi_search_by_image_id(item_id, photo_id)
    if not search_by_image_id:
        return None
    return (
        f"https://www.vinted.it/catalog?search_by_image_id={quote(search_by_image_id)}"
        f"&brand_ids[]={brand_id}"
        "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
    )


# search_comps_ebay_sold_url (URL diretto www.ebay.it/sch/i.html?...&LH_Sold=1)
# RIMOSSA il 2026-09-19: costruiva l'URL per lo scrape diretto della pagina
# eBay, abbandonato dopo conferma che eBay blocca sistematicamente Serper su
# quell'endpoint con la pagina anti-bot "Misura di sicurezza" (vedi
# _serper_batch_query_ebay_sold, che l'ha sostituita passando da una query
# Google invece dello scrape diretto).


def _estrai_articoli_vinted(content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dal markdown scrapato di una pagina
    catalogo Vinted. Fix 2026-09-19: il pattern prezzo riconosceva solo
    '€105' (simbolo prima del numero), mai '105€'/'105 €' -- se Vinted
    scrive il prezzo in quel secondo formato (comune altrove, es. Vestiaire),
    questa funzione tornava sistematicamente 'Nessun articolo trovato' anche
    con una pagina piena di risultati validi. Ora riconosce entrambi.

    Aggiunto lo stesso giorno: quando non trova nulla, distingue nel testo
    restituito TRE scenari diversi invece del generico "Nessun articolo
    trovato" -- (a) la pagina scrapata era vuota/senza righe di contenuto,
    (b) c'erano righe di contenuto ma nessuna con un simbolo di prezzo
    riconoscibile, (c) c'era un simbolo € ma la riga e' stata scartata dopo
    (titolo troppo corto o assente). Serve per capire, guardando il debug
    Telegram, se Serper ha davvero trovato la pagina/i risultati oppure no
    -- 'nessun prezzo' da solo non lo diceva."""
    righe_non_vuote = sum(1 for r in content.split("\n") if r.strip())
    righe_con_simbolo_prezzo = sum(1 for r in content.split("\n") if "€" in r or re.search(r"\bEUR\b", r, re.IGNORECASE))
    righe_pulite, visti = [], set()
    for riga in content.split("\n"):
        riga_dec = riga.replace("&#x20AC;", "€").replace("&#x20ac;", "€")
        match_prezzo = re.search(r"€\s*([\d]+(?:\.\d+)?)|([\d]+(?:\.\d+)?)\s*€", riga_dec)
        if not match_prezzo:
            continue
        prezzo = match_prezzo.group(1) or match_prezzo.group(2)
        riga_pulita = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', riga_dec)
        riga_pulita = re.sub(r'!\[', '', riga_pulita)
        riga_pulita = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', riga_pulita).replace('"', '').strip().lstrip('-').strip()
        # Prova entrambi i formati di prezzo ('€105' e '105€'/'105 €') nella
        # riga gia' ripulita dal markdown -- niente calcoli di posizione
        # incrociati tra riga_dec e riga_pulita (fragili: la pulizia
        # markdown cambia le lunghezze/offset in modo non prevedibile).
        pos_prezzo = riga_pulita.find(f"€{prezzo}")
        if pos_prezzo == -1:
            m_dopo = re.search(re.escape(prezzo) + r"\s*€", riga_pulita)
            pos_prezzo = m_dopo.start() if m_dopo else -1
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
    if righe_pulite:
        return "\n".join(righe_pulite)
    if righe_non_vuote == 0:
        return "  Nessun articolo trovato (pagina scrapata vuota/senza contenuto -- probabile scrape fallito o pagina bloccata)."
    if righe_con_simbolo_prezzo == 0:
        return f"  Nessun articolo trovato ({righe_non_vuote} righe di contenuto scrapate, ma NESSUNA conteneva un simbolo di prezzo -- probabile pagina senza risultati catalogo, o layout cambiato)."
    return f"  Nessun articolo trovato ({righe_con_simbolo_prezzo} righe con simbolo di prezzo trovate, ma titolo non estraibile/troppo corto per ciascuna)."


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

    if "VINTED" in label.upper():
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


def _cerca_ebay_sold_via_resellbot(brand, categoria, timeout=6):
    """Fonte PRIMARIA per eBay SOLD, aggiunta il 2026-09-19: interroga
    direttamente l'API pubblica di Resellbot (scan-api.resellbot.com/api/search),
    lo stesso endpoint usato dalla pagina https://resellbot.com/ebay-sold-listings/
    -- individuato ispezionando manualmente il tab Network del browser durante
    una ricerca reale (la pagina in se' non mostra risultati nell'HTML statico,
    li carica via fetch() asincrono dopo il caricamento, per questo uno scrape
    HTML classico -- sia il nostro WebFetch che, presumibilmente, Serper senza
    rendering JS -- vede solo la shell vuota).

    A differenza della query Google (_serper_batch_query_ebay_sold, tenuta
    sotto come fallback), questa e' l'API REALE che alimenta il tool: prezzi
    di vendita CONFERMATI con data (soldAt), non uno snippet testuale con la
    parola "sold" che puo' riferirsi a un annuncio ancora attivo.

    Nessuna autenticazione richiesta (verificato via DevTools: solo header
    CORS standard, Origin/Referer che imitano il browser). Rate limit
    dichiarato dal servizio stesso via header di risposta: 700 richieste/5min,
    140/min -- ampiamente sufficiente per l'uso di questo bot (poche decine
    di item/ora). Se Cloudflare (che protegge l'endpoint) dovesse iniziare a
    bloccare le richieste dirette da Railway (mancando il fingerprint TLS/JS
    di un vero browser), ok=False fa scattare comunque il fallback Google
    sotto -- questa fonte non e' un punto di fallimento singolo."""
    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()
    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query eBay "
            "(Resellbot) saltata per evitare risultati fuorvianti."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    query_testo = f'{brand_pulito} {termine_en}'.strip() if brand_pulito else termine_en

    payload = {
        "searchId": str(uuid.uuid4()),
        "queries": [{"query": query_testo, "specificity": "exact"}],
        "resultMode": "raw",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://resellbot.com",
        "Referer": "https://resellbot.com/",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36"
        ),
    }
    try:
        resp = requests.post(
            "https://scan-api.resellbot.com/api/search",
            headers=headers, json=payload, timeout=timeout,
        )
        if resp.status_code in (401, 403, 429):
            return f"  Resellbot bloccato/rate-limited (HTTP {resp.status_code}) -- uso fallback Google.", False
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"  Resellbot fallito: {e} -- uso fallback Google.", False

    risultati_per_piattaforma = data.get("results") or []
    righe = []
    for blocco_piattaforma in risultati_per_piattaforma:
        piattaforma = (blocco_piattaforma.get("platform") or "").strip()
        for item in blocco_piattaforma.get("listings") or []:
            titolo = (item.get("title") or "").strip()
            prezzo = item.get("price")
            if not titolo or prezzo is None:
                continue
            spedizione = item.get("shipping") or 0
            sold_at = (item.get("soldAt") or "")[:10]  # solo YYYY-MM-DD
            condizione = (item.get("condition") or "").strip()
            pezzi = [f"- {titolo} — €{prezzo:.2f}"]
            if spedizione:
                pezzi.append(f"(+€{spedizione:.2f} spedizione)")
            if sold_at:
                pezzi.append(f"[venduto: {sold_at}]")
            if piattaforma:
                pezzi.append(f"[{piattaforma}]")
            if condizione:
                pezzi.append(f"[cond: {condizione}]")
            righe.append(" ".join(pezzi))

    if not righe:
        return "  Nessun venduto trovato su Resellbot per questa query.", True
    return "\n".join(righe[:20]), True


def _serper_batch_query_ebay_sold(brand, categoria):
    """FALLBACK per eBay SOLD (fonte primaria: _cerca_ebay_sold_via_resellbot
    sopra) -- stesso schema di _serper_batch_query_vestiaire (Google search
    via Serper, non scrape diretto della pagina eBay).

    Sostituisce il vecchio approccio (_serper_scrape_page_diretto +
    _estrai_articoli_ebay) che scrapava direttamente l'URL di ricerca eBay
    con LH_Sold=1. Abbandonato il 2026-09-19 dopo conferma diretta nei log
    Railway: OGNI scrape, su item diversi con query diverse, restituiva la
    stessa identica pagina eBay ('metadata': {'title': 'Misura di sicurezza
    | eBay'}, sempre 217 righe di contenuto) -- non un problema di selettori
    CSS o layout cambiato, ma il muro anti-bot di eBay che intercetta
    sistematicamente lo scraper di Serper su quell'endpoint, prima ancora
    che la pagina risultati venga generata. Nessun fix ai selettori
    avrebbe mai funzionato.

    Interrogando invece Google (site:ebay.it/ebay.com) tramite l'endpoint
    /search di Serper, la richiesta non tocca mai eBay direttamente: e' lo
    stesso principio gia' usato per Vestiaire, che infatti non ha mai
    avuto questo problema. Perso il filtro nativo LH_Sold=1 (non
    disponibile fuori dall'URL di ricerca eBay), compensato aggiungendo
    "venduto"/"sold" in query -- lo stesso schema gia' usato con successo
    dalle ricerche on-demand del cervello (cerca_serper_mirata), che infatti
    su eBay trovano spesso dati reali (vedi log 'NWT Brunello Cucinelli...
    1 venduto' nei risultati on-demand) proprio perche' passano da Google
    e non dallo scrape diretto."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", False

    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()

    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query eBay "
            "saltata per evitare risultati fuorvianti. Se necessario, usa la "
            "function cerca_comp_prezzo con una query piu' mirata."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    # Parentesi esplicite sui due OR: senza raggruppamento la sintassi Google
    # ("A OR B OR C" senza parentesi ha precedenza ambigua) rischia di
    # applicare il vincolo site:ebay.* solo a un ramo della query invece che
    # a tutta la ricerca, con risultati fuori da eBay.
    base = f'{brand_pulito} "{termine_en}"'.strip() if brand_pulito else f'"{termine_en}"'
    query_serper = f'{base} (venduto OR sold) (site:ebay.it OR site:ebay.com)'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            # timeout ridotto a 8s (era 15s): questa funzione e' anche il
            # FALLBACK di _cerca_ebay_sold_con_fallback, chiamato DOPO il
            # tentativo Resellbot (fino a 6s) -- il budget totale deve restare
            # sotto i 15s del timeout dell'executor in search_comps_completo,
            # altrimenti la fonte eBay verrebbe scartata come "troppo lenta"
            # anche quando il fallback stava per riuscire.
            json=payload, timeout=8,
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
# economiche (es. "for Target"), e frasi che indicano che il brand e' citato
# solo come RIFERIMENTO/ispirazione, non come brand reale del prodotto.
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
# diverse (es. Y-3 e' streetwear di massa via Adidas, non Yohji Yamamoto
# mainline; See by Chloe' e' diffusion, non Chloe' mainline).
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
    # Aggiunti: stessa logica, brand delle watch che hanno sottolinee/collab
    # a fascia di prezzo molto piu' bassa e che contaminano i comp.
    "helmut lang": ["helmut lang jeans"],
    "issey miyake": ["me issey miyake", "haat", "bao bao"],
    "max mara": ["weekend max mara", "max mara weekend", "max mara studio", "sportmax", "marella", "pennyblack", "max&co", "max & co"],
    "jean paul gaultier": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "jpg": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "arc'teryx": ["arc'teryx lt", "arcteryx kids"],
    "moschino": ["love moschino", "moschino jeans", "boutique moschino"],
    "armani": ["emporio armani", "armani exchange", "armani jeans", "a|x"],
    "versace": ["versace jeans", "versus versace", "versace collection"],
    "vivienne westwood": ["vivienne westwood anglomania kids"],
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
    Necessario perche' eBay/Vestiaire a volte restituiscono risultati
    "correlati al brand" fuori categoria nonostante la query includa la
    categoria -- il motore di ricerca della fonte non la rispetta
    rigidamente, quindi il filtro va fatto sui risultati."""
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


def _recupera_comp_visuali_vinted(item_id, photo_id, brand):
    """Wrapper per la fonte visuale, pensato per essere sottomesso come UN
    solo future nello stesso executor delle altre 3 fonti (vedi
    search_comps_completo) cosi' la risoluzione dell'ID (chiamata di rete
    verso Vinted, non istantanea) corre IN PARALLELO alle altre ricerche
    invece di bloccarne l'avvio. Fa due passi in sequenza al suo interno
    (risolvi ID -> scrape del catalogo con quell'ID), ma dal punto di vista
    dell'executor e' un solo task con lo stesso contratto di ritorno
    (testo, ok) degli altri. ok=False (non un'eccezione) quando manca un
    ingrediente o la risoluzione fallisce, cosi' il chiamante lo tratta come
    fonte assente senza differenziare i log dalle altre query fallite."""
    url = build_vinted_visual_search_url(item_id, photo_id, brand)
    if not url:
        return "  Fonte non disponibile (photo_id/brand mancante o risoluzione ID falsa).", False
    return _serper_scrape_page_diretto("VINTED", url)


def _cerca_ebay_sold_con_fallback(brand, categoria):
    """Wrapper per l'executor: prova prima Resellbot (dati di vendita
    confermati, veri, vedi _cerca_ebay_sold_via_resellbot), e solo se fallisce
    (bloccato, rate-limited, errore di rete, o semplicemente 'nessun venduto
    trovato' con ok=True viene comunque accettato cosi' com'e' -- il fallback
    scatta solo su ok=False) prova la query Google di riserva. Tenute
    sequenziali (non in parallelo) per non raddoppiare le chiamate quando la
    prima fonte funziona, che e' il caso comune."""
    testo, ok = _cerca_ebay_sold_via_resellbot(brand, categoria)
    if ok:
        return testo, ok
    log.info("_cerca_ebay_sold_con_fallback: Resellbot fallito (%s), tento fallback Google.", testo)
    testo_fallback, ok_fallback = _serper_batch_query_ebay_sold(brand, categoria)
    if ok_fallback:
        return f"{testo_fallback}\n(Nota: fonte primaria Resellbot fallita, questi risultati vengono da Google/eBay.)", True
    return f"{testo} | fallback Google anch'esso fallito: {testo_fallback}", False


def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None, cover_photo_id=None, item_id=None):
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
    # Se manca l'ingrediente minimo (photo_id o brand mappato) la fonte
    # visuale e' inutile: lo sappiamo gia' qui senza fare rete, quindi non la
    # sottomettiamo affatto all'executor invece di sprecare uno slot/tempo.
    tentare_ricerca_visuale = (
        VISUAL_SEARCH_ATTIVA
        and bool(cover_photo_id)
        and bool(VINTED_BRAND_IDS.get((brand or "").strip().lower()))
    )

    risultati = {}
    successi = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_vestiaire = executor.submit(_serper_batch_query_vestiaire, brand, categoria)
        future_vinted = executor.submit(_serper_scrape_page_diretto, "VINTED", vinted_url)
        # eBay: fonte primaria Resellbot (API reale con vendite confermate,
        # vedi _cerca_ebay_sold_via_resellbot) con fallback automatico a
        # Google (_serper_batch_query_ebay_sold) se Resellbot fallisce --
        # niente scrape diretto della pagina ricerca eBay, bloccata
        # sistematicamente dal suo anti-bot (confermato in produzione il
        # 2026-09-19, vedi docstring di _serper_batch_query_ebay_sold).
        future_ebay = executor.submit(_cerca_ebay_sold_con_fallback, brand, categoria)
        futures = {future_vestiaire: "vestiaire", future_vinted: "vinted", future_ebay: "ebay"}
        if tentare_ricerca_visuale:
            future_visuale = executor.submit(_recupera_comp_visuali_vinted, item_id, cover_photo_id, brand)
            futures[future_visuale] = "vinted_visuale"

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
    # La fonte visuale conta come "presente" solo se ha davvero prodotto un
    # risultato (successi["vinted_visuale"] True) -- se photo_id/brand
    # mancavano non e' nemmeno stata sottomessa (tentare_ricerca_visuale
    # False), se e' stata sottomessa ma la risoluzione ID o lo scrape sono
    # falliti risulta un fallimento come le altre query, non un errore raro.
    fonte_visuale_riuscita = tentare_ricerca_visuale and successi.get("vinted_visuale")
    visual_comp_puliti = None
    if fonte_visuale_riuscita:
        visual_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted_visuale"), query_base)
        visual_comp_puliti = _filtra_comp_per_brand_sottolinee(visual_comp_puliti, brand)
        # NIENTE _filtra_comp_per_categoria qui: la ricerca e' gia' ristretta
        # dalla similarita' visiva con la foto reale, un filtro testuale sulla
        # categoria rischierebbe solo di scartare match validi con titoli
        # atipici.

    n_fonti = 4 if fonte_visuale_riuscita else 3
    parti = [f"RICERCA WEB PRE-RACCOLTA ({n_fonti} fonti, base: '{query_base}'):"]
    if nota_brand:
        parti.append(nota_brand)
    if categoria:
        parti.append(f"(Comp filtrati per categoria rilevata: '{categoria}' -- risultati fuori tema gia' scartati.)")
    if fonte_visuale_riuscita:
        parti.append(
            "\n📍 FONTE: VINTED — RICERCA VISUALE PER FOTO (stesso identikit visivo dell'annuncio, "
            "filtrato per brand — la piu' precisa delle 4, prezzi ASK)\n"
            f"{visual_comp_puliti or 'Nessun risultato'}"
        )
    parti.append(
        "\n📍 FONTE: VESTIAIRE COLLECTIVE (prezzi ASK — annunci attivi, NON necessariamente venduti)\n"
        f"{vestiaire_comp_puliti or 'Nessun risultato'}"
    )
    parti.append(
        "\n📍 FONTE: VINTED (prezzi ASK — annunci attivi, NON necessariamente venduti; annuncio in analisi gia' escluso)\n"
        f"{vinted_comp_puliti or 'Nessun risultato'}"
    )
    parti.append(
        "\n📍 FONTE: EBAY SOLD (dati di vendita CONFERMATI via Resellbot, con data di vendita — il dato "
        "PIU' affidabile per stimare il prezzo di vendita reale; SE il blocco sotto contiene la nota "
        "'fonte primaria Resellbot fallita', invece, i risultati vengono da una ricerca Google testuale "
        "di fallback e possono includere annunci ancora attivi che citano 'sold' fuori contesto — in tal "
        "caso verifica dal testo/snippet prima di trattarli come venduti confermati)\n"
        f"{ebay_comp_puliti or 'Nessun risultato'}"
    )

    return "\n".join(parti), serper_ha_funzionato, tentare_ricerca_visuale, fonte_visuale_riuscita


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
    dell'occhio invece di quelle proprie, specialmente quando riprende la
    formulazione dell'analisi visiva preliminare. Gestisce due casi:
    1. Emoji sbagliata + nessuna parola di decisione: inserisce sia
       l'emoji giusta sia la parola.
    2. Emoji sbagliata + parola di decisione gia' presente: sostituisce
       solo l'emoji, senza duplicare la parola.

    IMPORTANTE: lo swap nel caso 2 avviene SOLO nel prefisso PRIMA della
    parola di decisione, mai dopo -- altrove nel blocco possono comparire
    le annotazioni inserite dalle reti di sicurezza, che non vanno mai
    toccate o si generano doppioni."""
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
    che l'occhio produce (best-effort: i formati variano leggermente)."""
    return _estrai_margine_e_roi_da_blocco(output_occhi_testo or "")


def check_skip_pre_cervello(output_occhi_testo, listing_info=None):
    testo = (output_occhi_testo or "").lower()

    # NOTA (caso reale osservato): un Dries Van Noten a €5,95 e' stato
    # scartato qui come "falso palese, Confidenza Alta" con dettagli che
    # sembravano inventati, mentre 3 legit check esterni indipendenti sullo
    # stesso capo hanno concluso "Probabilmente autentico" 82-85%. La causa
    # probabile e' un bias "prezzo troppo basso = deve essere falso"
    # nell'occhio. Soluzione scelta: RINFORZARE il prompt dell'occhio (non
    # rimuovere questo filtro, che resta utile per risparmiare token sui
    # falsi genuinamente conclamati).
    if ("probabilmente falso" in testo or "falso conclamato" in testo) and \
       any(c in testo for c in ("confidenza alta", "90%", "95%", "100%", "molto alto")):
        return True, "[FALSO CONCLAMATO] Rilevato da analisi visiva con alta confidenza."

    # Skip su brand completamente estraneo (non una sottolinea/diffusion --
    # un marchio diverso e non correlato, es. l'annuncio dichiara "Kapital"
    # ma l'etichetta reale e' "Kapitales", brand francese di souvenir senza
    # alcun legame col Kapital giapponese monitorato). Il prompt dell'occhio
    # istruisce a scrivere la frase esatta "BRAND NON CORRISPONDENTE" solo
    # quando e' sicuro che sia un marchio diverso, non per semplici dubbi --
    # quindi qui e' sicuro fidarsi del match testuale senza ulteriori
    # controlli di confidenza (a differenza del "falso conclamato" sopra,
    # dove il bias prezzo-basso rendeva la sola dichiarazione del modello
    # inaffidabile). Risparmia la ricerca comp del cervello: il verdetto
    # e' gia' scontato (NON COMPRARE) indipendentemente da prezzo/comp.
    if "brand non corrispondente" in testo:
        return True, (
            "[BRAND NON CORRISPONDENTE] L'analisi visiva ha rilevato un marchio diverso "
            "e non correlato rispetto a quello dichiarato nell'annuncio -- cervello non "
            "consultato, il capo non ha valore nel segmento monitorato indipendentemente dal prezzo."
        )

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

    # Skip su nessuna etichetta visibile: senza nessuna etichetta il cervello
    # non ha nulla in piu' da aggiungere sull'autenticita' -- l'unico passo
    # utile e' chiedere altre foto, cosa che l'occhio ha gia' suggerito.
    #
    # ECCEZIONE IMPORTANTE: se le foto reali dell'annuncio non sono state
    # scaricate e l'analisi si basa solo sulla cover photo di Telegram, un
    # "nessuna etichetta visibile" e' quasi certamente un falso negativo
    # dovuto allo scraping fallito, non al capo -- in quel caso NON si
    # scarta, si lascia proseguire al cervello.
    solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
    BLOCCO_VERDETTO_INIZIALE = testo[:250]
    ETICHETTA_KEYWORDS_ESPLICITE = [
        "nessuna etichetta visibile", "assenza totale di etichette",
        "etichette non visibili", "zero etichette", "senza etichette visibili",
        "non sono visibili etichette", "nessuna etichetta è visibile",
    ]
    nessuna_etichetta = (
        "non verificabile" in BLOCCO_VERDETTO_INIZIALE
        or any(kw in testo for kw in ETICHETTA_KEYWORDS_ESPLICITE)
    )
    if nessuna_etichetta and not solo_cover:
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] L'analisi visiva non ha trovato etichette "
            "per verificare l'autenticita' -- cervello non consultato, servono piu' foto "
            "(main label + wash tag) prima di procedere."
        )
    if nessuna_etichetta and solo_cover:
        log.info(
            "Skip 'nessuna etichetta' NON applicato: analisi basata solo sulla cover photo "
            "(scraping foto fallito), probabile falso negativo -- si prosegue col cervello."
        )

    # Skip su margine preliminare chiaramente negativo: se anche la stima
    # dell'occhio (di solito ottimistica, senza comp reali) indica gia' una
    # perdita netta o ROI negativo, e' molto improbabile che il cervello,
    # con dati di mercato reali, trovi un risultato migliore.
    margine_prelim, roi_prelim = estrai_margine_preliminare(output_occhi_testo)
    margine_esplicitamente_nullo = any(k in testo for k in (
        "margine nullo", "margine negativo", "nessun valore di rivendita",
        "valore di rivendita non significativo", "non c'è valore di rivendita",
        "non vale il tempo",
    ))
    if margine_esplicitamente_nullo or (margine_prelim is not None and margine_prelim < 0) or (roi_prelim is not None and roi_prelim < 0):
        return True, (
            f"[MARGINE PRELIMINARE NEGATIVO] Stima preliminare dell'occhio indica "
            f"perdita netta (margine={margine_prelim}, ROI={roi_prelim}%) -- "
            "cervello non consultato per risparmiare token."
        )

    return False, None


def build_skip_report(listing_info, motivo_skip, output_occhi_testo=None):
    if motivo_skip.startswith("[MARGINE INSUFFICIENTE"):
        riga_legit = "Non valutato — filtro pre-cervello su margine insufficiente. Autenticita' non in dubbio."
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
            # separatore "---" (che nel template segue sempre il Verdetto).
            if not dettaglio:
                m_pos = re.search(r"\n---\s*\n+(.+?)(?=\n---|\n📨|\Z)", output_occhi_testo, re.DOTALL)
                if m_pos and m_pos.group(1).strip():
                    dettaglio = m_pos.group(1).strip()

            # Tentativo 3 (ultima risorsa): tutto il testo grezzo troncato.
            if not dettaglio:
                testo_grezzo = output_occhi_testo.strip()
                dettaglio = testo_grezzo[:600] + ("..." if len(testo_grezzo) > 600 else "")

            if dettaglio:
                riga_legit = f"Probabilmente falso. Motivo specifico: {dettaglio}"
        riga_rischio = "ALTO — falso conclamato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[BRAND NON CORRISPONDENTE"):
        riga_legit = "Brand non corrispondente — marchio reale sull'etichetta diverso e non correlato a quello dichiarato."
        if output_occhi_testo:
            m_legit = re.search(r"🏷️\s*Legit:\s*([^\n]+)", output_occhi_testo, re.IGNORECASE)
            if m_legit and m_legit.group(1).strip():
                riga_legit = m_legit.group(1).strip()
        riga_rischio = "N/A — brand estraneo al segmento monitorato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[CONDIZIONE DISTRUTTA"):
        riga_legit = "Autentico ma condizione fisica gravemente compromessa — non rivendibile."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — cervello non consultato"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE"):
        riga_legit = "Nessuna etichetta visibile nelle foto fornite — autenticita' non verificabile allo stato attuale."
        riga_rischio = "ALTO (non verificabile) — servono piu' foto (filtro pre-cervello, risparmio token)"
    elif motivo_skip.startswith("[MARGINE PRELIMINARE NEGATIVO"):
        riga_legit = "Non valutato nel dettaglio — la stima preliminare indicava gia' una perdita netta."
        riga_rischio = "N/A — margine preliminare negativo (cervello non consultato per risparmiare token)"
    elif motivo_skip.startswith("[CATEGORIA GENERICA NON FLIPPABILE"):
        riga_legit = "Categoria strutturalmente senza mercato — nessun valore di rivendita."
        riga_rischio = "BASSO — categoria non flippabile (filtro pre-Gemini)"
    elif motivo_skip.startswith("[DANNO GRAVE DICHIARATO NEL TESTO"):
        riga_legit = "Non valutato — venditore dichiara esplicitamente un danno grave nel testo."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — danno dichiarato dal venditore (filtro pre-Gemini)"
    elif motivo_skip.startswith("[NON ORIGINALE DICHIARATO"):
        riga_legit = "Venditore dichiara esplicitamente che il capo non e' originale."
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

    # Per il caso "nessuna etichetta", riusa il messaggio che l'occhio ha gia'
    # suggerito (di solito chiede foto di main label + wash tag).
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
        f"- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidita':** Bassa · **Rischio:** {riga_rischio} · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        f"## Legit check\n{riga_legit}\n\n"
        "## Da chiedere\nNon rilevante: filtro automatico attivato.\n\n"
        f"## Messaggio da inviare\n{messaggio_skip}"
    )


def forza_soglia_minima_compra(testo):
    """Ultima rete di sicurezza, indipendente dal formato esatto del verdetto.
    valida_contraddizioni_report funziona solo se il modello include l'emoji
    o la dicitura "**Decisione:**" -- se il modello omette entrambi (capita),
    quella funzione non ha nulla da correggere e una COMPRA sotto soglia
    passa inosservata. Questa funzione normalizza prima eventuali emoji
    sbagliate, poi scansiona il blocco iniziale del testo e forza TRATTA se
    margine <20€ o ROI <100% nonostante COMPRA."""
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
        "forza_soglia_minima_compra: COMPRA declassato a TRATTA (margine=%s, ROI=%s%%).",
        margine_valore, roi_valore,
    )
    return testa_corretta + resto


def declassa_urgenza_se_borderline(testo):
    """Rete di sicurezza indipendente dal formato: 'Alta urgenza' deve
    riflettere un margine di sicurezza reale (>=€30 netti E ROI >=150%),
    non un semplice superamento della soglia minima per COMPRA."""
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
    prezzo del PRODOTTO (mai sulla spedizione). Sostituisce l'INTERA riga
    "Obiettivo trattativa: ..." fino a fine riga, non solo il numero
    dell'offerta -- altrimenti il resto della frase resta calcolato sul
    vecchio valore e produce numeri incoerenti tra loro."""
    if prezzo_prodotto is None:
        return testo

    m = re.search(r"Obiettivo trattativa:\s*€\s*([\d.,]+)[^\n]*", testo, re.IGNORECASE)
    if not m:
        return testo

    try:
        valore_offerto = float(m.group(1).replace(",", "."))
    except ValueError:
        return testo

    STIMA_SPEDIZIONE_MINIMA = 2.50  # tariffa IT, la piu' economica
    soglia_minima = round(prezzo_prodotto * 0.6 + STIMA_SPEDIZIONE_MINIMA, 2)

    if valore_offerto >= soglia_minima - 0.01:
        return testo

    soglia_str = f"{soglia_minima:.2f}".replace(".", ",")
    riga_corretta = (
        f"Obiettivo trattativa: €{soglia_str} totale (minimo consentito: 40% sconto "
        f"su prezzo prodotto €{prezzo_prodotto:.2f} + spedizione) ⚠️ _offerta originale "
        f"del modello (€{valore_offerto:.2f}) era sotto il limite consentito ed e' stata "
        f"corretta al minimo -- margine e ROI relativi NON sono ricalcolati automaticamente, "
        f"verificare manualmente prima di inviare l'offerta_"
    )
    testo_corretto = testo[:m.start()] + riga_corretta + testo[m.end():]

    log.info(
        "applica_soglia_trattativa_40_percento: offerta corretta da €%.2f a €%.2f (prezzo prodotto=€%.2f).",
        valore_offerto, soglia_minima, prezzo_prodotto,
    )
    return testo_corretto


def converti_tratta_senza_obiettivo_valido(testo):
    """Rete di sicurezza: se il modello propone esplicitamente un
    'Obiettivo trattativa' che resta sotto soglia anche al massimo sconto,
    la negoziazione non risolve nulla -- la decisione corretta e' NON
    COMPRARE.

    IMPORTANTE: interviene SOLO se un obiettivo trattativa e' presente ed
    e' insufficiente. Se manca del tutto (es. perche' questa TRATTA e'
    stata generata da forza_soglia_minima_compra declassando un COMPRA
    borderline), NON forza NON COMPRARE."""
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
        return testo  # nessun obiettivo proposto: non e' un errore

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
        "converti_tratta_senza_obiettivo_valido: TRATTA convertito in NON COMPRARE (margine_obiettivo=%s, ROI_obiettivo=%s%%).",
        margine_obiettivo, roi_obiettivo,
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
    compare nel messaggio finale, deve esserci una spiegazione specifica
    vicino (font, cuciture, materiale, wash tag...). Se il testo e' troppo
    corto o coincide con una vecchia frase generica nota, aggiunge un
    avviso visibile invece di lasciare l'utente senza motivo."""
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
            "\n\n⚠️ _Nota automatica: e' stato rilevato un possibile falso ma non e' stato fornito "
            "un motivo specifico (font, cuciture, materiale, wash tag). Verificare manualmente le "
            "foto prima di scartare definitivamente l'annuncio._"
        )

    return testo


def verifica_ancoraggio_prezzo_comp(testo):
    """Rete di sicurezza per una violazione osservata piu' volte in produzione
    nonostante la regola sia gia' esplicita nel prompt ("CONTROLLO NUMERICO
    OBBLIGATORIO SUL PREZZO DI LISTING"): il modello a volte fissa un prezzo
    di listing SUPERIORE al comp piu' alto che lui stesso cita nell'Analisi
    dell'analista, spesso chiamandolo "prudenziale" -- l'opposto della
    prudenza. Casi reali che hanno motivato questa funzione:
    - comp citati Vinted €215 e eBay SOLD €200, listing fissato a €225
      ("prudenzialmente");
    - maglioncino Brunello Cucinelli €90, comp citati fino a €180, listing
      stimato €225 con verdetto "COMPRA SUBITO".

    Versione precedente di questa funzione aggiungeva solo una nota di
    avviso in fondo al messaggio, lasciando il verdetto (COMPRA/TRATTA)
    intatto in testa -- rischio concreto che l'utente si fidi del verdetto
    senza scorrere fino alla nota. Ora la violazione DECLASSA il verdetto
    stesso, con lo stesso meccanismo (sostituzione di emoji + testo nel
    blocco dei primi 400 caratteri) usato dalle altre reti di sicurezza
    del file (forza_soglia_minima_compra, converti_tratta_senza_obiettivo_valido).
    Margine/ROI numerici NON vengono ricalcolati (troppo rischioso via
    regex): si declassa solo l'etichetta di decisione, ed e' comunque
    responsabilita' dell'utente verificare manualmente il caso."""
    m_verdetto = re.search(
        r"💰\s*€\s*([\d.,]+)\s*→\s*€\s*([\d.,]+)\s*→",
        testo[:400],
    )
    if not m_verdetto:
        return testo

    try:
        incasso_reale = float(m_verdetto.group(2).replace(",", "."))
    except ValueError:
        return testo

    if incasso_reale <= 0:
        return testo

    prezzo_listing_stimato = incasso_reale / 0.80

    m_analisi = re.search(
        r"Analisi dell'analista:?\**\s*\n(.+)", testo, re.IGNORECASE | re.DOTALL,
    )
    if not m_analisi:
        return testo
    blocco_analisi = m_analisi.group(1)

    comp_citati = []
    for m in re.finditer(r"€\s*([\d]+(?:[.,]\d+)?)|([\d]+(?:[.,]\d+)?)\s*€", blocco_analisi):
        # Esclude i numeri che sono il modello stesso che ripete la SUA
        # stima (es. "posizionando il listing a 225€, incasso netto 180€")
        # -- altrimenti questi vengono scambiati per comp esterni citati,
        # innalzando artificialmente il "massimo" e mascherando proprio la
        # violazione che questa funzione deve rilevare.
        finestra_precedente = blocco_analisi[max(0, m.start() - 40):m.start()].lower()
        if re.search(r"\b(listing|incasso)\b", finestra_precedente):
            continue
        valore = m.group(1) or m.group(2)
        comp_citati.append(float(valore.replace(",", ".")))
    if not comp_citati:
        return testo

    comp_massimo = max(comp_citati)

    TOLLERANZA = 1.02  # 2% di margine per arrotondamenti, non e' una soglia rigida
    if prezzo_listing_stimato <= comp_massimo * TOLLERANZA:
        return testo

    sforamento_percento = (prezzo_listing_stimato / comp_massimo - 1) * 100

    log.info(
        "verifica_ancoraggio_prezzo_comp: prezzo di listing stimato €%.2f supera il comp piu' alto "
        "citato nell'analisi (€%.2f, sforamento %.0f%%) -- declassato il verdetto.",
        prezzo_listing_stimato, comp_massimo, sforamento_percento,
    )

    nota_calcolo = (
        f"il prezzo di listing stimato (~€{prezzo_listing_stimato:.2f}, ricavato "
        f"dall'incasso €{incasso_reale:.2f}÷0.80) supera del {sforamento_percento:.0f}% "
        f"il comp piu' alto citato nell'Analisi dell'analista (€{comp_massimo:.2f}) -- "
        f"violazione della regola di ancoraggio ai comp reali"
    )

    testo = _normalizza_emoji_decisione(testo)
    LUNGHEZZA_BLOCCO_VERDETTO = 400
    testa = testo[:LUNGHEZZA_BLOCCO_VERDETTO]
    resto = testo[LUNGHEZZA_BLOCCO_VERDETTO:]
    testa_upper = testa.upper()

    # Sforamento grosso (>20% sopra il comp massimo): la stima e' cosi'
    # lontana dal comp reale che anche trattare non ha senso -- NON COMPRARE.
    # Sforamento piu' contenuto: declassa a TRATTA (o resta NON COMPRARE se
    # gia' tale, non c'e' nulla sotto a cui declassare).
    SOGLIA_SFORAMENTO_NON_COMPRARE = 20.0

    if "NON COMPRARE" in testa_upper:
        # Gia' al livello minimo: aggiunge solo la motivazione, senza toccare
        # l'emoji/decisione che e' gia' quella corretta.
        testa_corretta = re.sub(
            r"(NON COMPRARE)(\s*⚠️\s*_[^_]*_)?",
            lambda m: f"{m.group(1)} ⚠️ _corretto: {nota_calcolo}_",
            testa, count=1, flags=re.IGNORECASE,
        )
    elif sforamento_percento > SOGLIA_SFORAMENTO_NON_COMPRARE:
        testa_corretta = testa.replace("🟢", "🔴", 1).replace("🟡", "🔴", 1)
        testa_corretta = re.sub(
            r"\b(?:COMPRA(?:\s+(?:SUBITO|FORTE|IMMEDIATAMENTE|SE CI TIENI))?|TRATTA)\b(?:\s*⚠️\s*_[^_]*_)?",
            f"NON COMPRARE ⚠️ _corretto: {nota_calcolo}_",
            testa_corretta, count=1, flags=re.IGNORECASE,
        )
    else:
        testa_corretta = testa.replace("🟢", "🟡", 1)
        testa_corretta = re.sub(
            r"\bCOMPRA(?:\s+(?:SUBITO|FORTE|IMMEDIATAMENTE|SE CI TIENI))?\b(?:\s*⚠️\s*_[^_]*_)?",
            f"TRATTA ⚠️ _corretto: {nota_calcolo}_",
            testa_corretta, count=1, flags=re.IGNORECASE,
        )

    return testa_corretta + resto


def _estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo):
    """Estrae tutti i numeri che compaiono vicino a un simbolo di prezzo
    (€ prima o dopo, o 'EUR') nel testo grezzo dei risultati di ricerca
    (comp pre-raccolti + eventuali cerca_comp_prezzo on-demand). Sono gli
    UNICI numeri che il cervello puo' legittimamente citare come prezzi nel
    blocco Analisi -- qualunque altro prezzo citato non ha una fonte
    verificabile in questa conversazione.

    BUG corretto il 2026-09-19: il ramo "numero PRIMA del simbolo" (es.
    '105 €', '400€' -- il formato piu' comune negli snippet Vestiaire/eBay
    europei) non ha MAI matchato nulla, perche' il pattern terminava con
    "(?:€|EUR)\\b" e \\b (word boundary) non esiste subito dopo '€' (non e'
    un carattere di parola, quindi non crea un confine con cio' che segue).
    Risultato pratico: questa funzione vedeva SOLO i prezzi scritti come
    '€105', perdendo silenziosamente tutti quelli in formato '105€' -- cioe'
    sottostimava il pool reale, con rischio di falsi "comp inventato" da
    verifica_comp_citati_sono_reali quando il prezzo citato dal cervello
    corrispondeva in realta' a un prezzo vero scritto in quel formato."""
    prezzi = set()
    for m in re.finditer(r"€\s*([\d]+(?:[.,]\d+)?)|([\d]+(?:[.,]\d+)?)\s*(?:€|EUR\b)", pool_ricerca_grezzo, re.IGNORECASE):
        valore = m.group(1) or m.group(2)
        try:
            prezzi.add(round(float(valore.replace(",", ".")), 2))
        except ValueError:
            continue
    return prezzi


def _prezzi_per_fonte_da_pool(pool_ricerca_grezzo):
    """Come _riepilogo_comp_per_fonte ma restituisce i dati grezzi invece del
    testo: dict {chiave_fonte_normalizzata: set(prezzi)}, dove chiave_fonte
    e' il nome della fonte in minuscolo senza spazi/punteggiatura (es.
    'ebaysold', 'vestiairecollective', 'vinted') -- pensato per essere
    confrontato con un nome di fonte estratto dal testo del cervello con la
    stessa normalizzazione, cosi' da tollerare piccole differenze di
    formattazione ('eBay SOLD' vs 'ebay sold' vs 'eBay-SOLD'). Usato da
    verifica_comp_citati_sono_reali per il controllo di secondo livello
    'la fonte dichiarata dal cervello corrisponde a dove il prezzo si trova
    davvero nel pool'."""
    risultato = {}
    if not pool_ricerca_grezzo or not pool_ricerca_grezzo.strip():
        return risultato
    blocchi = re.split(r"\n?📍\s*FONTE:\s*", pool_ricerca_grezzo)
    for blocco in blocchi:
        blocco = blocco.strip()
        if not blocco:
            continue
        prima_riga, _, resto = blocco.partition("\n")
        if prima_riga.upper().startswith("RICERCA WEB PRE-RACCOLTA"):
            continue
        nome_fonte = prima_riga.split("(")[0].strip().rstrip(":—-").strip() or prima_riga.strip()
        chiave = re.sub(r"[^a-z0-9]", "", nome_fonte.lower())
        if not chiave:
            continue
        prezzi_fonte = _estrai_prezzi_da_pool_ricerca(resto or blocco)
        risultato.setdefault(chiave, set()).update(prezzi_fonte)
    return risultato


def _motivo_nessun_prezzo(blocco_fonte):
    """Quando una fonte non ha prodotto prezzi, va a leggere il motivo che
    le funzioni di estrazione (_estrai_articoli_vinted, _estrai_articoli_ebay,
    _serper_batch_query_vestiaire) ora incorporano nel loro stesso testo di
    ritorno quando non trovano nulla -- distingue 'Serper non ha trovato
    proprio niente' da 'Serper ha trovato risultati ma senza un prezzo
    riconoscibile' da 'la richiesta a Serper e' fallita (rete/crediti)'.
    Aggiunto il 2026-09-19 su richiesta esplicita: sapere solo 'nessun
    prezzo' non bastava, serviva vedere se la ricerca aveva davvero
    restituito qualcosa di scartato dopo, o se era vuota dall'inizio."""
    testo = blocco_fonte.strip()
    testo_lower = testo.lower()
    # Controlli sull'INIZIO della stringa (non substring generica): i
    # messaggi di errore vero (rete/crediti) iniziano sempre cosi', mentre
    # "scrape fallito"/"fallito" possono comparire anche DENTRO la spiegazione
    # di uno scenario "0 risultati" (es. "...probabile scrape fallito o
    # pagina bloccata" dentro il messaggio di pagina vuota) -- un controllo
    # a substring qui darebbe falsi positivi "query FALLITA" per quel caso.
    if (
        testo_lower.startswith("serper fallito")
        or testo_lower.startswith("scrape fallito")
        or testo_lower.startswith("ricerca fallita")
        or testo_lower.startswith("ricerca non eseguita")
    ):
        return f"query Serper FALLITA -- {testo}"
    if "categoria non rilevata" in testo_lower:
        return "query saltata (categoria non rilevata dal titolo)"
    if testo_lower == "nessun risultato trovato.":
        return "query Google (site:vestiairecollective.com) interrogata, 0 risultati organici trovati"
    if "pagina scrapata vuota" in testo_lower or testo_lower.startswith("nessun risultato trovato") or testo_lower.startswith("nessun risultato sold trovato"):
        return f"Serper interrogato, 0 risultati -- {testo}"
    if "righe di contenuto scrapate" in testo_lower or "titoli o prezzi trovati singolarmente" in testo_lower:
        return f"Serper ha trovato contenuto ma nessun prezzo utilizzabile -- {testo}"
    # Fallback: testo diagnostico non riconosciuto in uno dei pattern noti
    # (es. "Fonte non disponibile", messaggi futuri) -- lo mostriamo cosi'
    # com'e' invece di nasconderlo dietro un generico "nessun prezzo".
    return testo if testo else "nessun prezzo, motivo non disponibile"


def _riepilogo_comp_per_fonte(pool_ricerca_grezzo):
    """Riassume pool_ricerca_grezzo in UNA riga per fonte (conteggio + range
    di prezzo quando ci sono prezzi, motivo diagnostico quando non ce ne
    sono), invece di riportare gli snippet grezzi Serper per intero --
    pensata per il blocco debug Telegram (DEBUG_CONFRONTO_COMP_TELEGRAM).
    Riconosce i blocchi gia' etichettati "📍 FONTE: <nome>" (comp pre-raccolti
    E ricerche on-demand, entrambi taggati cosi', vedi search_comps_completo/
    chiama_*_cervello_forzato) e spacca il pool su quell'etichetta.

    Aggiornato il 2026-09-19: il ramo 'nessun prezzo' ora richiama
    _motivo_nessun_prezzo per dire ANCHE se Serper ha trovato qualcosa (poi
    scartato/senza prezzo) o non ha trovato proprio nulla -- prima
    'nessun prezzo' copriva indistintamente entrambi i casi, nascondendo se
    la ricerca stessa avesse funzionato."""
    if not pool_ricerca_grezzo or not pool_ricerca_grezzo.strip():
        return "(pool vuoto)"

    blocchi = re.split(r"\n?📍\s*FONTE:\s*", pool_ricerca_grezzo)
    righe = []
    for blocco in blocchi:
        blocco = blocco.strip()
        if not blocco:
            continue
        # Primo blocco (prima della prima 📍) e' l'header "RICERCA WEB
        # PRE-RACCOLTA (...)" senza fonte propria -- non contiene mai prezzi
        # utili, lo saltiamo.
        prima_riga, _, resto = blocco.partition("\n")
        if prima_riga.upper().startswith("RICERCA WEB PRE-RACCOLTA"):
            continue
        nome_fonte = prima_riga.split("(")[0].strip().rstrip(":—-").strip() or prima_riga.strip()
        blocco_dati = resto or blocco
        prezzi_fonte = sorted(_estrai_prezzi_da_pool_ricerca(blocco_dati))
        if not prezzi_fonte:
            righe.append(f"• {nome_fonte}: {_motivo_nessun_prezzo(blocco_dati)}")
        elif len(prezzi_fonte) == 1:
            righe.append(f"• {nome_fonte}: 1 prezzo (€{prezzi_fonte[0]:.2f})")
        else:
            righe.append(
                f"• {nome_fonte}: {len(prezzi_fonte)} prezzi (€{min(prezzi_fonte):.2f}–€{max(prezzi_fonte):.2f})"
            )
    return "\n".join(righe) if righe else "(nessuna fonte con prezzi)"


def verifica_comp_citati_sono_reali(testo, pool_ricerca_grezzo):
    """Rete di sicurezza per una violazione distinta da quella di
    verifica_ancoraggio_prezzo_comp: qui il cervello non sfora un comp reale
    che cita, ma CITA COMP CHE NON ESISTONO nei dati di ricerca effettivamente
    ricevuti -- una stima "a memoria del brand" (es. "vendite recenti tra
    €150 e €280" per una t-shirt Undercover, quando la ricerca web reale non
    conteneva quei numeri da nessuna parte) presentata come se venisse dai
    dati. Il prompt lo vieta esplicitamente ("Cita SEMPRE almeno 2 prezzi
    ESATTI verbatim dai dati ricevuti... mai un range parafrasato a memoria")
    ma nessun controllo automatico lo verificava finora.

    Se ANCHE SOLO UNO dei prezzi citati nel blocco Analisi non trova
    corrispondenza (con una piccola tolleranza per arrotondamenti) tra i
    numeri realmente presenti nel pool di ricerca, il verdetto non ha base
    interamente verificabile: declassa allo stesso modo di
    verifica_ancoraggio_prezzo_comp (COMPRA/TRATTA -> declassati, NON
    COMPRARE lasciato con nota). Corretto il 2026-09-19: la versione
    precedente richiedeva che TUTTI i prezzi citati fossero senza riscontro
    prima di declassare (bastava un solo numero vero per far passare
    l'intera Analisi) -- troppo permissivo per il pattern osservato in
    produzione di un'Analisi che mescola un comp reale con uno inventato e
    attribuito a una fonte piu' autorevole di quella vera (es. taggato
    "eBay SOLD" quando eBay era vuoto nel pool).

    SECONDO LIVELLO aggiunto lo stesso giorno: non basta che un prezzo
    citato esista DA QUALCHE PARTE nel pool complessivo -- se il cervello
    dichiara esplicitamente una fonte vicino al prezzo (es. "€103.66 su
    eBay SOLD"), quel prezzo deve trovarsi PROPRIO nel blocco di quella
    fonte nel pool, non altrove. Senza questo controllo un numero vero preso
    da una fonte debole (es. Vestiaire) puo' essere rietichettato come
    proveniente da una fonte piu' autorevole (es. "eBay SOLD confermato")
    senza che nessuna rete se ne accorga, dato che il numero di per se' e'
    verificabile nel pool complessivo. Riconosce le fonti eBay/Vestiaire/
    Vinted/Depop/Grailed (vedi ALIAS_FONTE); un prezzo senza fonte dichiarata
    vicino continua a passare col solo controllo di primo livello."""
    if not pool_ricerca_grezzo or not pool_ricerca_grezzo.strip():
        return testo  # nessun dato di ricerca disponibile: non c'e' nulla da verificare

    m_analisi = re.search(
        r"Analisi dell'analista:?\**\s*\n(.+)", testo, re.IGNORECASE | re.DOTALL,
    )
    if not m_analisi:
        return testo
    blocco_analisi = m_analisi.group(1)

    # Il prezzo RICHIESTO dell'annuncio (es. "💰 €50.00 → ...") non e' un comp
    # e va escluso dal confronto: e' normalissimo che l'Analisi lo ripeta, e
    # non e' una prova di ricerca -- includerlo indebolirebbe la verifica.
    prezzo_richiesto = None
    m_richiesto = re.search(r"💰\s*€\s*([\d.,]+)\s*→", testo[:400])
    if m_richiesto:
        try:
            prezzo_richiesto = round(float(m_richiesto.group(1).replace(",", ".")), 2)
        except ValueError:
            pass

    # Nomi di fonte riconosciuti quando compaiono vicino a un prezzo citato
    # nell'Analisi -- usati per il controllo di secondo livello "la fonte
    # dichiarata corrisponde a dove il prezzo si trova davvero nel pool".
    # Ogni variante testuale mappa alla stessa chiave normalizzata usata da
    # _prezzi_per_fonte_da_pool (nome fonte pool in minuscolo, senza spazi/
    # punteggiatura), cosi' "eBay SOLD", "eBay" e "ebay" puntano tutte allo
    # stesso blocco pool.
    ALIAS_FONTE = [
        (r"ebay\s*sold", "ebaysold"),
        (r"ebay", "ebaysold"),
        (r"vestiaire\s*collective", "vestiairecollective"),
        (r"vestiaire", "vestiairecollective"),
        (r"vinted", "vinted"),
        (r"depop", "depop"),
        (r"grailed", "grailed"),
    ]

    prezzi_citati = []
    fonte_dichiarata_per_prezzo = {}  # indice in prezzi_citati -> chiave fonte pool o None
    for m in re.finditer(r"€\s*([\d]+(?:[.,]\d+)?)|([\d]+(?:[.,]\d+)?)\s*€", blocco_analisi):
        finestra_precedente = blocco_analisi[max(0, m.start() - 40):m.start()].lower()
        if re.search(r"\b(listing|incasso)\b", finestra_precedente):
            continue  # e' la stima del modello stesso, non un comp citato
        valore = m.group(1) or m.group(2)
        try:
            prezzo = round(float(valore.replace(",", ".")), 2)
        except ValueError:
            continue
        if prezzo_richiesto is not None and abs(prezzo - prezzo_richiesto) < 0.01:
            continue  # e' solo la ripetizione del prezzo richiesto, non un comp

        # Cerca un nome di fonte esplicito vicino al prezzo citato (finestra
        # stretta, prima o dopo il numero: "€103.66 su eBay SOLD", "eBay:
        # €103.66", "venduto a €103 (Vestiaire)"). Se trovato, lo normalizza
        # nella stessa chiave usata per i blocchi del pool.
        finestra_dopo = blocco_analisi[m.end():m.end() + 40].lower()
        finestra_fonte = finestra_precedente + " " + finestra_dopo
        chiave_fonte_citata = None
        for pattern_alias, chiave_pool in ALIAS_FONTE:
            if re.search(pattern_alias, finestra_fonte):
                chiave_fonte_citata = chiave_pool
                break

        indice = len(prezzi_citati)
        prezzi_citati.append(prezzo)
        fonte_dichiarata_per_prezzo[indice] = chiave_fonte_citata
    if not prezzi_citati:
        return testo  # nessun comp citato in Analisi: altre reti coprono questo caso

    prezzi_pool = _estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo)
    prezzi_per_fonte = _prezzi_per_fonte_da_pool(pool_ricerca_grezzo)

    TOLLERANZA_ASSOLUTA = 1.0  # euro, per arrotondamenti (es. 89.99 vs 90)

    prezzi_non_verificati = []
    prezzi_fonte_sbagliata = []  # (prezzo, chiave_fonte_citata) -- esiste nel pool ma non in quella fonte
    for indice, citato in enumerate(prezzi_citati):
        esiste_nel_pool = any(abs(citato - reale) <= TOLLERANZA_ASSOLUTA for reale in prezzi_pool)
        if not esiste_nel_pool:
            prezzi_non_verificati.append(citato)
            continue

        chiave_fonte_citata = fonte_dichiarata_per_prezzo.get(indice)
        if chiave_fonte_citata is None:
            continue  # verificato nel pool, nessuna fonte specifica dichiarata: ok cosi'

        prezzi_di_quella_fonte = prezzi_per_fonte.get(chiave_fonte_citata, set())
        esiste_nella_fonte_dichiarata = any(
            abs(citato - reale) <= TOLLERANZA_ASSOLUTA for reale in prezzi_di_quella_fonte
        )
        if not esiste_nella_fonte_dichiarata:
            prezzi_fonte_sbagliata.append((citato, chiave_fonte_citata))

    if not prezzi_non_verificati and not prezzi_fonte_sbagliata:
        return testo  # OGNI prezzo citato ha riscontro nel pool, nella fonte giusta: nessuna violazione

    # BUG corretto il 2026-09-19: la versione precedente lasciava passare
    # l'intera Analisi appena UN SOLO prezzo citato risultava verificato,
    # anche se altri citati nello stesso paragrafo erano inventati -- caso
    # reale osservato: Analisi che cita "eBay SOLD €103.66" (fonte eBay
    # completamente vuota nel pool -- numero senza alcun riscontro) insieme
    # a "Vestiaire €132.00" (questo si', presente nel pool), il prezzo vero
    # dava credibilita' a tutto il paragrafo e la violazione sul primo
    # passava inosservata. Ora la verifica e' PER OGNI prezzo citato: anche
    # un solo numero senza riscontro fa scattare la rete, perche' e'
    # comunque un dato presentato come verificato quando non lo e' (nel
    # caso Miu Miu, proprio quel numero non verificato era la base
    # dell'attribuzione "venduto confermato" che giustificava il COMPRA).
    #
    # SECONDO LIVELLO aggiunto lo stesso giorno: un prezzo puo' esistere DA
    # QUALCHE PARTE nel pool ma essere attribuito dal cervello a una fonte
    # diversa e piu' autorevole di quella reale (es. un prezzo che nel pool
    # sta solo nel blocco Vestiaire, ma il cervello lo cita come "eBay SOLD
    # €X" -- il numero e' vero, la fonte no). Caso osservato: Robe Missoni,
    # "€66 eBay" mentre la query on-demand eBay per quell'item non aveva
    # ancora dati confermati nel pool. prezzi_fonte_sbagliata isola questi
    # casi separandoli da quelli senza riscontro nel pool (prezzi_non_verificati).
    if prezzi_non_verificati:
        log.info(
            "verifica_comp_citati_sono_reali: %d/%d prezzi citati in Analisi senza corrispondenza "
            "nei dati di ricerca realmente ricevuti -- non verificati: %s (citati: %s, pool: %s) "
            "-- declassato il verdetto.",
            len(prezzi_non_verificati), len(prezzi_citati), prezzi_non_verificati, prezzi_citati, sorted(prezzi_pool),
        )
    if prezzi_fonte_sbagliata:
        log.info(
            "verifica_comp_citati_sono_reali: %d prezzi citati con fonte dichiarata non corrispondente "
            "al blocco pool reale -- fonte_sbagliata: %s -- declassato il verdetto.",
            len(prezzi_fonte_sbagliata), prezzi_fonte_sbagliata,
        )

    if prezzi_non_verificati and len(prezzi_non_verificati) == len(prezzi_citati):
        nota_calcolo = (
            f"i prezzi citati nell'Analisi dell'analista ({', '.join(f'€{p:.2f}' for p in prezzi_citati)}) "
            f"non corrispondono a nessun prezzo presente nei dati di ricerca realmente raccolti per "
            f"questo annuncio -- possibile stima 'a memoria del brand' invece che dai comp reali"
        )
    elif prezzi_fonte_sbagliata and not prezzi_non_verificati:
        dettaglio_fonti = ', '.join(f"€{p:.2f} (non e' in {fonte})" for p, fonte in prezzi_fonte_sbagliata)
        nota_calcolo = (
            f"nell'Analisi dell'analista alcuni prezzi sono attribuiti a una fonte che non li contiene "
            f"davvero nei dati di ricerca raccolti ({dettaglio_fonti}) -- il numero esiste nel pool ma "
            f"in una fonte diversa da quella dichiarata, probabile fonte mal attribuita"
        )
    else:
        pezzi_non_ok = [f"€{p:.2f}" for p in prezzi_non_verificati] + [
            f"€{p:.2f} (fonte errata: dichiarato {fonte})" for p, fonte in prezzi_fonte_sbagliata
        ]
        nota_calcolo = (
            f"parte dei prezzi citati nell'Analisi dell'analista non corrisponde ai dati di ricerca "
            f"realmente raccolti (problemi su: {', '.join(pezzi_non_ok)}) "
            f"-- possibile mix di comp reali e stime 'a memoria del brand' o attribuiti alla fonte sbagliata"
        )

    testo = _normalizza_emoji_decisione(testo)
    LUNGHEZZA_BLOCCO_VERDETTO = 400
    testa = testo[:LUNGHEZZA_BLOCCO_VERDETTO]
    resto = testo[LUNGHEZZA_BLOCCO_VERDETTO:]
    testa_upper = testa.upper()

    if "NON COMPRARE" in testa_upper:
        testa_corretta = re.sub(
            r"(NON COMPRARE)(\s*⚠️\s*_[^_]*_)?",
            lambda m: f"{m.group(1)} ⚠️ _corretto: {nota_calcolo}_",
            testa, count=1, flags=re.IGNORECASE,
        )
    elif "TRATTA" in testa_upper:
        testa_corretta = testa.replace("🟡", "🔴", 1)
        testa_corretta = re.sub(
            r"\bTRATTA\b(?:\s*⚠️\s*_[^_]*_)?",
            f"NON COMPRARE ⚠️ _corretto: {nota_calcolo}_",
            testa_corretta, count=1, flags=re.IGNORECASE,
        )
    else:
        testa_corretta = testa.replace("🟢", "🟡", 1)
        testa_corretta = re.sub(
            r"\bCOMPRA(?:\s+(?:SUBITO|FORTE|IMMEDIATAMENTE|SE CI TIENI))?\b(?:\s*⚠️\s*_[^_]*_)?",
            f"TRATTA ⚠️ _corretto: {nota_calcolo}_",
            testa_corretta, count=1, flags=re.IGNORECASE,
        )

    return testa_corretta + resto


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
    correzioni_applicate = []
    output_finale_raw = ""
    user_text_cervello = ""

    photo_bytes_list = []
    if url:
        scraped = scrape_vinted_listing(url)
        listing_info.update({
            "size": scraped.get("size"), "condition": scraped.get("condition"),
            "description": scraped.get("description"), "age_days": scraped.get("age_days"),
            "catalog_id": scraped.get("catalog_id"), "cover_photo_id": scraped.get("cover_photo_id"),
            "material_raw": scraped.get("material_raw"),
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

        # FILTRO PRE-GEMINI
        e_skip_pre, motivo_skip_pre = check_skip_pre_gemini(listing_info)
        if e_skip_pre:
            # Silenzioso: nessuna notifica Telegram per le esclusioni pre-Gemini.
            # Rimane visibile solo nei log (Railway) per debug/controllo.
            log.info("FILTRO PRE-GEMINI ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s", listing_info.get("title"), motivo_skip_pre)
            return

        photo_urls = scraped.get("photo_urls", [])
        # TEMP DIAGNOSTIC: distinguishes "the listing page itself yielded zero
        # photo URLs" (regex extraction failed / page fetch failed upstream in
        # scrape_vinted_listing) from "photo URLs were found but every single
        # download attempt failed" -- the two have different causes and the
        # existing logs never separated them. Remove once diagnosed.
        if not photo_urls:
            log.warning(
                "scrape_vinted_listing non ha restituito nessun photo_url per %s "
                "(pagina annuncio non raggiunta o regex di estrazione foto non ha trovato match).",
                url,
            )
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
            "Scraping foto fallito del tutto per %s -- uso solo la cover photo Telegram come fallback.",
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
    if fallback_solo_cover_photo:
        user_text_occhi += (
            "\n\nATTENZIONE: lo scraping delle foto dell'annuncio e' fallito. Stai vedendo "
            "SOLO l'immagine di copertina, non la galleria completa. NON concludere "
            "'nessuna etichetta visibile' o 'non verificabile' come se il venditore non "
            "avesse fotografato le etichette: molto probabilmente le ha fotografate, ma "
            "quelle foto non sono arrivate fino a te. Valuta cio' che vedi e segnala "
            "esplicitamente il limite."
        )

    output_occhi, costo_occhi, _ = chiama_gemini(
        GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
    costo_totale += costo_occhi

    e_skip, motivo_skip = check_skip_pre_cervello(output_occhi, listing_info)
    if e_skip:
        log.info("FILTRO PRE-CERVELLO ATTIVATO. Motivo: %s", motivo_skip)
        if motivo_skip.startswith("[FALSO CONCLAMATO"):
            log.info("FALSO CONCLAMATO -- output occhi grezzo per '%s':\n%s", listing_info.get("title"), output_occhi)
        output_finale = build_skip_report(listing_info, motivo_skip, output_occhi_testo=output_occhi)
        n_query_grounding = 0
        scenario_usato = "SKIP"
        forza_ricerca = None
        comp_sufficienti = None
        costo_cervello = 0.0
        pool_ricerca_grezzo = ""  # SKIP: nessuna ricerca comp eseguita, nulla da verificare
    else:
        titolo_annuncio = listing_info.get("title") or ""
        brand_annuncio = listing_info.get("brand") or ""
        categoria_per_ricerca = estrai_categoria_da_titolo(titolo_annuncio) or ""
        catalog_id = listing_info.get("catalog_id")
        material_per_ricerca = listing_info.get("material_per_ricerca")
        cover_photo_id = listing_info.get("cover_photo_id")
        item_id_annuncio = _estrai_item_id_da_url(url)

        scenario_usato = "F"
        comps_text = None
        # Default per lo scenario "Serper non disponibile" (raffreddamento o
        # API key assente): nessuna ricerca comp e' stata neppure tentata,
        # quindi la fonte visuale non e' stata ne' tentata ne' riuscita --
        # usati dal blocco debug DEBUG_CONFRONTO_COMP_TELEGRAM piu' avanti.
        tentare_ricerca_visuale = False
        fonte_visuale_riuscita = False

        tempo_trascorso = time.time() - _serper_timestamp_ultimo_fallimento[0]
        in_raffreddamento = (
            _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
            and tempo_trascorso < RAFFREDDAMENTO_SERPER_SECONDI
        )
        serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

        if serper_disponibile:
            comps_text, serper_ok, tentare_ricerca_visuale, fonte_visuale_riuscita = search_comps_completo(
                brand_annuncio, categoria_per_ricerca, titolo_annuncio,
                catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
                cover_photo_id=cover_photo_id, item_id=item_id_annuncio,
            )
            if serper_ok:
                scenario_usato = "G"
                _serper_fallimenti_consecutivi[0] = 0
                if _serper_notifica_esaurimento_inviata[0]:
                    _serper_notifica_esaurimento_inviata[0] = False
                    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, "✅ Serper e' tornato a funzionare normalmente.")
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

        if CERVELLO_PROVIDER == "openai":
            output_finale_raw, costo_cervello, n_query_grounding, ricerche_extra_raw = chiama_openai_cervello_forzato(
                GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, forza_ricerca=forza_ricerca)
        else:
            output_finale_raw, costo_cervello, n_query_grounding, ricerche_extra_raw = chiama_gemini_cervello_forzato(
                GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, forza_ricerca=forza_ricerca)
        costo_totale += costo_cervello

        # Pool di TUTTO il testo grezzo di ricerca visto dal cervello per
        # questo item -- comp pre-raccolti (Scenario G) + eventuali ricerche
        # on-demand (cerca_comp_prezzo). Usato da verifica_comp_citati_sono_reali
        # per controllare che i prezzi scritti in Analisi provengano davvero
        # da qui, non da una stima "a memoria del brand" del modello.
        pool_ricerca_grezzo = "\n".join(filter(None, [comps_text] + ricerche_extra_raw))

        output_finale = valida_contraddizioni_report(output_finale_raw)
        if output_finale != output_finale_raw:
            correzioni_applicate.append("valida_contraddizioni_report")

        # normalizza_urgenza_wording resta SEMPRE attiva anche con
        # RETI_SICUREZZA_ATTIVE=False: e' solo normalizzazione di wording
        # (mai un declassamento), e serve al parsing di estrai_decisione_da_testo
        # a valle -- disattivarla romperebbe il parsing, non l'esperimento.
        prev = output_finale
        output_finale = normalizza_urgenza_wording(output_finale)
        if output_finale != prev:
            correzioni_applicate.append("normalizza_urgenza_wording")
        prev = output_finale

        if RETI_SICUREZZA_ATTIVE:
            output_finale = forza_soglia_minima_compra(output_finale)
            if output_finale != prev:
                correzioni_applicate.append("forza_soglia_minima_compra")
            prev = output_finale

            output_finale = converti_tratta_senza_obiettivo_valido(output_finale)
            if output_finale != prev:
                correzioni_applicate.append("converti_tratta_senza_obiettivo_valido")
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

    # ---- GATE MARGINE ASSOLUTO (qualita' del deal, non sicurezza) ----
    # Sopprime la notifica quando il margine netto stimato resta sotto
    # l'obiettivo operativo, anche se ROI e soglia minima sono superati.
    # Serve ad alzare il valore medio dei deal che arrivano su Telegram
    # senza toccare i cap delle watch. Scarto silenzioso (solo log), stessa
    # logica gia' usata dal filtro pre-Gemini.
    if scenario_usato != "SKIP" and SOGLIA_MARGINE_ASSOLUTO_NOTIFICA > 0:
        margine_finale, _roi_finale = _estrai_margine_e_roi_da_blocco(output_finale[:400])
        decisione_upper_gate = decisione.upper()
        sotto_obiettivo = (
            margine_finale is not None
            and margine_finale < SOGLIA_MARGINE_ASSOLUTO_NOTIFICA
            and "NON COMPRARE" not in decisione_upper_gate
        )
        if sotto_obiettivo:
            log.info(
                "GATE MARGINE ASSOLUTO: notifica soppressa per '%s' (margine=%.2f EUR < soglia %d EUR). Decisione originale: %s",
                listing_info.get("title"), margine_finale, SOGLIA_MARGINE_ASSOLUTO_NOTIFICA, decisione,
            )
            return

    if scenario_usato == "SKIP":
        info_scenario = " · filtro pre-cervello (occhi soli)"
    elif scenario_usato == "F":
        info_scenario = " · nessun comp pre-raccolto, ricerca forzata"
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

    prev_ancoraggio = output_finale
    if RETI_SICUREZZA_ATTIVE:
        output_finale = verifica_ancoraggio_prezzo_comp(output_finale)
        output_finale = verifica_comp_citati_sono_reali(output_finale, pool_ricerca_grezzo)
    if output_finale != prev_ancoraggio:
        # Una delle due reti sopra ha cambiato l'emoji/decisione in testa:
        # ricalcola 'decisione' ed 'e_compra' sul testo aggiornato, altrimenti
        # la logica sotto (soppressione "Messaggio da inviare"/"Da chiedere",
        # normalizzazione "NON COMPRARE · N/A", alert su TELEGRAM_ALERT_CHAT_ID)
        # continuerebbe a ragionare sul verdetto originale non piu' valido --
        # es. un COMPRA declassato a NON COMPRARE non deve piu' triggerare
        # l'alert "AZIONE RICHIESTA".
        decisione = estrai_decisione_da_testo(output_finale) or decisione
        e_compra = any(k in decisione.upper() for k in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO"))

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

    # ---- BLOCCO DIAGNOSTICO: da dove vengono i comp REALMENTE ricevuti ----
    # Attivo solo con DEBUG_CONFRONTO_COMP_TELEGRAM=true (esperimento sul
    # tasso di "comp inventati a memoria" osservato con CERVELLO_PROVIDER=
    # openai, log 2026-09-18/19). Non mostra solo i prezzi (gia' disponibile
    # come riepilogo rapido), ma anche LA PROVENIENZA di ciascuno: quale
    # fonte pre-raccolta (Vinted visuale/testo, eBay SOLD, Vestiaire -- gia'
    # etichettate "📍 FONTE: ..." dentro comps_text) oppure quale query
    # Serper on-demand del cervello (etichettata allo stesso modo quando
    # aggiunta a ricerche_extra_raw, vedi chiama_gemini_cervello_forzato/
    # chiama_openai_cervello_forzato) -- inclusa la conferma esplicita se la
    # ricerca visuale Vinted (search_by_image) ha prodotto risultati per
    # QUESTO item o e' stata saltata. Va in coda al messaggio principale
    # invece che in un messaggio separato per essere visibile anche quando
    # RETI_SICUREZZA_ATTIVE=False sopprime le note automatiche.
    if DEBUG_CONFRONTO_COMP_TELEGRAM and scenario_usato != "SKIP":
        n_prezzi_pool_debug = len(_estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo))

        if fonte_visuale_riuscita:
            nota_visuale = "✅ riuscita"
        elif tentare_ricerca_visuale:
            nota_visuale = "❌ fallita per questo item"
        else:
            nota_visuale = "— non tentata"

        # Riepilogo per fonte in UNA riga ciascuna (conteggio + range), non
        # il testo grezzo Serper -- l'utente ha chiesto esplicitamente "solo
        # come arriva a quel prezzo", non gli snippet completi (2026-09-19).
        # Il pool completo resta comunque nei log Railway per chi vuole il
        # dettaglio integrale.
        output_finale += (
            f"\n\n🔬 *DEBUG* — {n_prezzi_pool_debug} prezzi reali ricevuti, "
            f"visuale: {nota_visuale}\n"
            f"{_riepilogo_comp_per_fonte(pool_ricerca_grezzo)}"
        )

    # ---- FOOTER COSTO IA: recap per-modello, per-messaggio ----
    # Aggiunto in coda al messaggio cosi' e' sempre visibile quanto e'
    # costata la valutazione di QUESTO specifico annuncio, senza dover
    # controllare i log su Railway o sommare a mano.
    if scenario_usato == "SKIP":
        footer_costo = (
            f"\n\n💵 _Costo IA: 👁 {GEMINI_MODEL_OCCHIO} ${costo_occhi:.4f} "
            f"· Cervello non consultato · Totale ${costo_occhi:.4f}_"
        )
    else:
        footer_costo = (
            f"\n\n💵 _Costo IA: 👁 {GEMINI_MODEL_OCCHIO} ${costo_occhi:.4f} "
            f"+ 🧠 {GEMINI_MODEL_CERVELLO} ${costo_cervello:.4f} "
            f"= Totale ${costo_totale:.4f}_"
        )
    output_finale = output_finale + footer_costo

    _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, n_query_grounding if scenario_usato != "SKIP" else 0
    )

    # Messaggio di debug separato, SOLO se una rete di sicurezza ha
    # effettivamente modificato il verdetto -- utile per controllare da
    # Telegram senza entrare su Railway. Riattivabile mettendo
    # INVIA_DEBUG_CORREZIONI = True qui sotto.
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
    log.info("Vinted Oracle avviato su Telethon. Versione: %s", BOT_VERSION)
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
