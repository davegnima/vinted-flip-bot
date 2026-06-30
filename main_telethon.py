"""
Vinted Flip Oracle Bot (versione Telethon / userbot) -- Scenario G con fallback F
====================================================================================
Pipeline finale (30/06/2026), basata sui 7 scenari testati in questa conversazione:

  SCENARIO G (primario): Gemini 3.1 Flash-Lite (occhi) -> Serper (comp Vinted/
  eBay/Vestiaire) -> Gemini 3.1 Flash-Lite (cervello, con grounding FORZATO nel
  prompt) -- risultato piu' economico e affidabile dei 7 scenari testati
  (~$0.004 per valutazione), con input occhi completo (non troncato come la
  versione 2.5 Flash-Lite) e comp reali da Serper.

  SCENARIO F (fallback automatico): stessa pipeline ma SENZA Serper -- si attiva
  automaticamente se Serper esaurisce i crediti o fallisce. Il cervello riceve
  solo la propria valutazione preliminare e DEVE affidarsi al grounding nativo
  Google Search per trovare comp reali.

IMPORTANTE -- limite tecnico del grounding: l'API Gemini NON permette di
forzare l'esecuzione di google_search nel senso stretto di un tool_choice
obbligatorio (a differenza di alcuni altri provider). Il tool e' sempre
disponibile al modello quando "tools" e' nel payload, ma la DECISIONE di
chiamarlo resta del modello. Possiamo solo istruirlo con forza nel prompt
("DEVI cercare", non "puoi cercare se vuoi") -- e nei test Scenario F ha
mostrato 0 query di grounding spontanee su 1 caso testato, quindi il prompt
rinforzato qui sotto e' un tentativo di correggere quel comportamento, non
una garanzia assoluta. Se in produzione si osserva ancora 0 query di
grounding sistematicamente nello scenario F, vale la pena rivedere la
strategia (es. instradare un secondo passaggio esplicito di ricerca anche
senza Serper, invece di affidarsi al solo prompt).

Modelli usati (prezzi verificati su ai.google.dev/gemini-api/docs/pricing,
30/06/2026):
  - gemini-3.1-flash-lite: $0.25/$1.50 per milione di token (input/output)
  - Grounding con Google Search: 5000 query/mese gratis (condivise su tutta
    la famiglia Gemini 3), poi $14 per 1000 query

Variabili d'ambiente richieste:
  TELEGRAM_API_ID
  TELEGRAM_API_HASH
  TELEGRAM_PHONE
  TELEGRAM_SESSION_STRING
  TELEGRAM_GROUP_ID
  TELEGRAM_BOT_TOKEN
  TELEGRAM_OWNER_CHAT_ID
  GEMINI_API_KEY
  SERPER_API_KEY (opzionale -- se assente o esaurita, fallback automatico a Scenario F)
"""

import os
import re
import json
import time
import asyncio
import base64
import logging
import traceback
from io import BytesIO
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

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
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")  # opzionale: assente -> fallback diretto a Scenario F

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# MODELLO UNICO per occhi e cervello (Scenario G/F): gemini-3.1-flash-lite.
# Verificato nei 7 scenari testati come il piu' economico e con output
# completo (a differenza di gemini-2.5-flash-lite, che nei test si e'
# troncato a meta' frase per esaurimento del budget di thinking dinamico).
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Prezzi verificati (30/06/2026) -- vedi pricing ufficiale Google.
PREZZO_GEMINI_INPUT = 0.25
PREZZO_GEMINI_OUTPUT = 1.50
PREZZO_GROUNDING_PER_QUERY = 14 / 1000  # sopra le 5000 query gratis/mese condivise

MAX_GALLERY_PHOTOS = 10

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

# Contatore consecutivo di fallimenti Serper -- se troppi di fila (es.
# crediti esauriti, non solo un errore di rete isolato), passiamo in
# "modalita' fallback temporaneo" per un periodo di raffreddamento,
# evitando di tentare Serper ad ogni singolo annuncio sapendo che
# fallira'. Dopo il raffreddamento riprova automaticamente (utile se i
# crediti si rinnovano o sono stati ricaricati manualmente nel frattempo).
_serper_fallimenti_consecutivi = [0]
_serper_timestamp_ultimo_fallimento = [0.0]
SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO = 3
RAFFREDDAMENTO_SERPER_SECONDI = 3600 * 6  # 6 ore prima di riprovare

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
}

MATERIALI_PREGIATI_PRIORITA = [
    "cashmere", "vicuna", "vigogna", "seta", "velluto", "pelle", "shearling",
    "montone", "renna", "alpaca", "mohair", "lana", "lino", "viscosa", "lurex",
    "denim", "cotone",
]

CATEGORIA_KEYWORDS = {
    "abito": ["abito", "vestito", "kleid", "dress", "robe"],
    "blusa": ["blusa", "camicetta", "bluse", "blouse", "chemisier"],
    "camicia": ["camicia", "hemd", "shirt", "chemise"],
    "maglia": ["maglia", "maglione", "pullover", "sweater", "pull", "jumper"],
    "t-shirt": ["t-shirt", "tshirt", "maglietta"],
    "gonna": ["gonna", "rock", "skirt", "jupe"],
    "pantaloni": ["pantaloni", "pantalone", "hose", "trousers", "pants", "pantalon"],
    "giacca": ["giacca", "jacke", "jacket", "veste"],
    "cappotto": ["cappotto", "mantel", "coat", "manteau"],
    "borsa": ["borsa", "tasche", "bag", "sac"],
    "scarpe": ["scarpe", "schuhe", "shoes", "chaussures"],
    "felpa": ["felpa", "hoodie", "sweatshirt"],
    "top": ["top"],
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vinted_flip_bot")


def scegli_materiale_per_ricerca(testo_libero):
    if not testo_libero:
        return None
    testo_lower = testo_libero.lower()
    for materiale in MATERIALI_PREGIATI_PRIORITA:
        if materiale in testo_lower:
            return materiale
    return None


def estrai_categoria_da_titolo(titolo):
    if not titolo:
        return None
    titolo_lower = titolo.lower()
    for categoria_it, parole_chiave in CATEGORIA_KEYWORDS.items():
        for parola in parole_chiave:
            if parola in titolo_lower:
                return categoria_it
    return None


# ---------------------------------------------------------------------------
# PROMPT DI SISTEMA
# ---------------------------------------------------------------------------

# Prompt OCCHI: identico per G e F -- analisi visiva + valutazione
# finanziaria preliminare, in testo libero (non JSON), zero ricerca web.
GEMINI_OCCHI_SYSTEM_PROMPT = """
Sei un analista COMPLETO per il flipping di capi second-hand di lusso: fai SIA l'analisi visiva/autenticazione (guardando le foto) SIA la valutazione finanziaria finale, in un solo passaggio, usando SOLO la tua conoscenza generale del mercato (NESSUNA ricerca web disponibile in questo passaggio).

PARTE 1 - ANALISI VISIVA: identificazione brand/modello, trascrizione etichette visibili, legit check, condizione/difetti.

PARTE 2 - VALUTAZIONE FINANZIARIA, applicando queste regole:
Sei **Vinted Flip Oracle Pro**: valuti annunci second-hand per stabilire se conviene comprarli per rivendere. Freddo, preciso, conservativo: proteggi l'utente da fake, margini illusori, prezzi gonfiati, difetti nascosti, capi illiquidi.

# INPUT
Non vedi le foto originali in un secondo passaggio. Sii esaustivo e specifico nella trascrizione delle etichette, perche' un secondo te stesso (in un secondo passaggio, senza foto) dovra' basarsi SOLO su questo testo.

REGOLA VINCOLANTE — ASSENZA TOTALE PROVE BRAND: zero loghi/etichette in tutte le foto E descrizione senza dettagli verificabili → decisione NON PUÒ essere COMPRA/COMPRA SUBITO/TRATTA. Solo CHIEDI ALTRE FOTO o NON COMPRARE.

# MARGINE E SOGLIE
**Acquisto pieno** = prezzo + protezione (~5%+€0,70) + spedizione (IT 2,50€, altre EU 4,50-6€). **Incasso** = vendita probabile − spedizione offerta. **Margine netto = incasso − acquisto pieno**, € e ROI%. Soglia: 20€ netti — sotto, default NON COMPRARE.

SOGLIA ROI MINIMO — SECONDO GATE INDIPENDENTE: ROI minimo 100% sul costo pieno per qualsiasi livello COMPRA, ANCHE se margine € supera 20€.

Voto Margine: 0-2/10 <10€; 3-4/10 10-19€; 5-6/10 20-39€; 7-8/10 40-99€; 9-10/10 100€+.

# MATRICE
1. COMPRA SUBITO — Deal 9-10 E Margine 8-10 E Confidenza non Bassa E Rischio non ALTO.
2. COMPRA FORTE — Deal 8 E Margine 7-8, Rischio BASSO/MEDIO.
3. COMPRA — Deal 6-7 E Margine 5-7, Rischio BASSO/MEDIO.
4. COMPRA SE CI TIENI — Deal 4-5 O Margine 4-5.
5. TRATTA.
6. NON COMPRARE — margine insufficiente, Rischio ALTO, o legit check negativo.

# PREZZI
Vinted mostra solo ASK mai sold. Gerarchia: eBay sold > Vinted/Depop (solo ask, ma numerosi e diretti) > Vestiaire (ask, spesso meno numerosi/specifici). Comps scarsi/assenti → Confidenza Bassa o Media a seconda di quanta conoscenza generale hai del valore second-hand di quel brand/modello specifico.

CONSERVATORISMO: "Vendita probabile" mai punto medio/alto se Confidenza non Alta.

# OUTPUT — compatto, italiano, max 150 parole.

## Verdetto operativo
- **Decisione:** [qualità] · [urgenza]
- **Costo pieno richiesto:** €X (scomposto)
- **Costo pieno trattato:** sempre numerico
- **Vendita probabile:** €X in ~Z giorni
- **Margine netto:** €X (ROI Y%)
- **Deal:** X/10 · **Margine:** X/10 · **Liquidità:** B/M/A · **Rischio:** B/M/A · **Confidenza:** A/M/B
- **In una riga:** [max15 parole]

## Legit check
Una riga, max20 parole.

## Da chiedere
Max3 domande.

## Messaggio da inviare
Breve o "Non necessario".

Output: prima un riepilogo analisi visiva (4-5 righe), poi il Verdetto Operativo completo nel formato sopra. Dichiara Confidenza Bassa se ti manca un ancoraggio di mercato reale (questo e' sempre il caso, dato che non hai ricerca web in questo passaggio).
""".strip()

# Prompt CERVELLO: usato sia in G (con Serper) sia in F (senza Serper) --
# differenza gestita nel testo utente, non nel system prompt. Qui il
# grounding viene istruito con la massima forza possibile via prompt
# (vedi limite tecnico spiegato in testa al file: non e' un obbligo
# garantito dall'API, solo un'istruzione forte).
GEMINI_CERVELLO_SYSTEM_PROMPT = """
Sei **Vinted Flip Oracle Pro**: valuti annunci second-hand per stabilire se conviene comprarli per rivendere. Freddo, preciso, conservativo: proteggi l'utente da fake, margini illusori, prezzi gonfiati, difetti nascosti, capi illiquidi.

# INPUT
Ricevi la TUA STESSA valutazione preliminare (prodotta in un passaggio precedente, senza ricerca web) e, quando disponibili, dei risultati di ricerca web pre-raccolti (Vinted, eBay, Vestiaire).

REGOLA VINCOLANTE — ASSENZA TOTALE PROVE BRAND: zero loghi/etichette E descrizione senza dettagli verificabili → decisione NON PUÒ essere COMPRA/COMPRA SUBITO/TRATTA. Solo CHIEDI ALTRE FOTO o NON COMPRARE.

# RICERCA WEB OBBLIGATORIA (google_search)
Hai accesso al tool di ricerca Google. **DEVI usarlo attivamente in questo passaggio**, non solo se i dati che hai sono insufficienti: la tua valutazione preliminare e gli eventuali comp pre-raccolti non sono mai sufficienti da soli per una decisione COMPRA SUBITO/FORTE ad Alta Confidenza. Esegui ALMENO una ricerca mirata a trovare comp reali (prezzi di vendita effettivi o ask recenti) su una o piu' di queste fonti, nell'ordine di affidabilita' indicato:
1. eBay SOLD (filtro "venduto", massima priorita' — sono transazioni concluse, non semplici richieste)
2. Vinted (ask, ma numerosi e diretti)
3. Depop (ask)
4. Vestiaire Collective (ask, spesso pezzi piu' pregiati/vintage)
5. Grailed (ask, utile per streetwear/designer maschile)
6. 1stDibs (ask, utile per pezzi vintage/d'archivio di fascia alta)

Formula query specifiche per brand + categoria + eventuale materiale (es. "Dries Van Noten silk dress sold ebay", "site:vestiairecollective.com [brand] [categoria]"). Se la prima ricerca non da' risultati utili, prova una seconda query con termini diversi prima di rinunciare. Solo se DAVVERO non trovi nulla di utile su nessuna fonte, dichiara Confidenza Bassa e procedi con la tua sola conoscenza generale, specificandolo esplicitamente nel Legit check.

# MARGINE E SOGLIE
**Acquisto pieno** = prezzo + protezione (~5%+€0,70) + spedizione (IT 2,50€, altre EU 4,50-6€). **Incasso** = vendita probabile − spedizione offerta. **Margine netto = incasso − acquisto pieno**, € e ROI%. Soglia: 20€ netti — sotto, default NON COMPRARE.

SOGLIA ROI MINIMO — SECONDO GATE INDIPENDENTE: ROI minimo 100% sul costo pieno per qualsiasi livello COMPRA, ANCHE se margine € supera 20€.

Voto Margine: 0-2/10 <10€; 3-4/10 10-19€; 5-6/10 20-39€; 7-8/10 40-99€; 9-10/10 100€+.

# MATRICE
1. COMPRA SUBITO — Deal 9-10 E Margine 8-10 E Confidenza non Bassa E Rischio non ALTO.
2. COMPRA FORTE — Deal 8 E Margine 7-8, Rischio BASSO/MEDIO.
3. COMPRA — Deal 6-7 E Margine 5-7, Rischio BASSO/MEDIO.
4. COMPRA SE CI TIENI — Deal 4-5 O Margine 4-5.
5. TRATTA.
6. NON COMPRARE — margine insufficiente, Rischio ALTO, o legit check negativo.

# PREZZI — POLICY ASK-COME-PROXY
Vinted/Depop/Vestiaire mostrano solo ASK mai sold. Gerarchia: eBay sold > Vinted/Depop (numerosi, diretti) > Vestiaire/Grailed/1stDibs (spesso meno numerosi). Se hai MULTIPLI ask coerenti tra loro (stesso brand/modello, prezzi nello stesso ordine di grandezza, fonti diverse), trattali come proxy ragionevole del valore di uscita reale, applicando uno SCONTO DI PRUDENZA del 20-40%. Questo non e' la stessa confidenza di un sold confermato (resta Media, non Alta, salvo casi eccezionali). Riserva "Confidenza Bassa" ai casi in cui i comp sono VERAMENTE scarsi (0-1 risultato) o palesemente incoerenti tra loro.

CONSERVATORISMO: "Vendita probabile" mai punto medio/alto se Confidenza non Alta.

# OUTPUT — compatto, italiano, max 150 parole.

## Verdetto operativo
- **Decisione:** [qualità] · [urgenza]
- **Costo pieno richiesto:** €X (scomposto)
- **Costo pieno trattato:** sempre numerico
- **Vendita probabile:** €X in ~Z giorni
- **Margine netto:** €X (ROI Y%)
- **Deal:** X/10 · **Margine:** X/10 · **Liquidità:** B/M/A · **Rischio:** B/M/A · **Confidenza:** A/M/B
- **In una riga:** [max15 parole]

## Legit check
Una riga, max20 parole. Specifica se la confidenza si basa su comp reali trovati via ricerca o solo su conoscenza generale.

## Da chiedere
Max3 domande.

## Messaggio da inviare
Breve o "Non necessario".
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
            log.warning("sendMessage Markdown fallita (chunk %d/%d) -- HTTP %d: %s -- ritento senza parse_mode",
                        i, len(chunks), resp.status_code, resp.text[:300])
            resp2 = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )
            if not resp2.ok:
                log.error("sendMessage fallita ANCHE senza Markdown (chunk %d/%d) -- HTTP %d: %s",
                          i, len(chunks), resp2.status_code, resp2.text[:300])


def telegram_send_photo(chat_id, photo_bytes, caption=None):
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    resp = requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=30)
    if not resp.ok:
        log.warning("sendPhoto fallita: %s", resp.text[:300])


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
    "Accept-Language": "it-IT,it;q=0.9",
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


def scrape_vinted_listing(url):
    result = {
        "photo_urls": [], "size": None, "condition": None, "description": None,
        "created_at": None, "age_days": None, "catalog_id": None,
        "material_raw": None, "material_per_ricerca": None, "color_raw": None,
    }
    try:
        resp = _vinted_session.get(url, headers=VINTED_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        matches = re.findall(
            r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/((?:f800|\d+x\d+))/'
            r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html)
        full_matches = re.findall(
            r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/(?:f800|\d+x\d+)/'
            r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html)
        best_url_by_photo_id = {}
        for (photo_id, resolution), full_url in zip(matches, full_matches):
            if photo_id not in best_url_by_photo_id or resolution == "f800":
                best_url_by_photo_id[photo_id] = full_url
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

        created_match = re.search(r'"created_at_ts"\s*:\s*"([^"]+)"', html)
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
                log.warning("Impossibile calcolare l'eta' dell'annuncio.")

        catalog_matches = re.findall(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"', html)
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

        material_match = re.search(r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
        if material_match:
            result["material_raw"] = material_match.group(1).strip()
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(material_match.group(1).strip())

        color_match = re.search(r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)', html, re.DOTALL)
        if color_match:
            result["color_raw"] = color_match.group(1).strip()

    except Exception as e:
        log.warning("Scraping Vinted fallito per %s: %s", url, e)

    return result


def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=2):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    for attempt in range(1, max_retries + 1):
        try:
            resp = _vinted_session.get(url, headers=headers, timeout=15)
            if resp.ok:
                return resp.content
        except Exception:
            pass
        time.sleep(0.6 * attempt)
    return None


# ---------------------------------------------------------------------------
# GEMINI -- CHIAMATA UNICA PARAMETRIZZATA (occhi/cervello, grounding si/no)
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
    """Chiamata unica parametrizzata: usata sia per gli 'occhi' (con foto,
    senza grounding) sia per il 'cervello' (senza foto, con grounding
    attivo su entrambi gli scenari G e F).

    Ritorna: (testo_risposta, costo_totale_usd, numero_query_grounding)
    """
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
        # CORRETTO (30/06/2026): thinkingLevel e' specifico della famiglia
        # Gemini 3.x (qui usiamo solo gemini-3.1-flash-lite, quindi sempre
        # questo ramo -- thinkingBudget servirebbe solo per la serie 2.5,
        # non usata in questo file).
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 3000, "thinkingConfig": {"thinkingLevel": "low"}},
    }
    if grounding:
        payload["tools"] = [{"google_search": {}}]

    backoff_seconds = 2
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(GEMINI_API_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
            if not resp.ok:
                # Logghiamo SEMPRE il corpo dell'errore prima di eventualmente
                # ritentare -- altrimenti un 400 di configurazione (es.
                # parametro sbagliato) verrebbe ritentato alla cieca invece
                # di essere diagnosticato.
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
# SERPER -- RICERCA COMP (usata solo in Scenario G)
# ---------------------------------------------------------------------------

def build_vinted_search_url(brand, categoria, materiale=None):
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    parti_search_text = [p for p in (categoria, materiale) if p]
    search_text_finale = " ".join(parti_search_text)
    if brand_id:
        return (
            f"https://www.vinted.it/catalog?brand_ids[]={brand_id}"
            f"&search_text={quote(search_text_finale)}"
            "&order=newest_first&status_ids[]=2&status_ids[]=3"
        ), True
    query_text = f"{brand} {search_text_finale}".strip()
    return f"https://www.vinted.it/catalog?search_text={quote(query_text)}&order=newest_first", False


def search_comps_ebay_sold_url(brand, categoria):
    query_base = f"{brand} {categoria}".strip()
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


def _serper_scrape_page_diretto(label, url):
    """Ritorna (contenuto_pulito, successo). successo=False segnala un
    fallimento di Serper (rete, autenticazione, crediti esauriti) -- NON
    un semplice 'zero risultati', che e' invece un successo con contenuto
    vuoto/informativo."""
    if not SERPER_API_KEY:
        return "Scrape non eseguito (SERPER_API_KEY non impostata).", False

    payload = {"url": url, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True}
    try:
        resp = requests.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        # CORRETTO: un 401/403 (chiave invalida/scaduta) o 402/429 (crediti
        # esauriti/rate limit) sono FALLIMENTI veri del servizio, non
        # "zero risultati" -- vanno trattati come segnale per il fallback,
        # non come "nessun comp trovato".
        if resp.status_code in (401, 402, 403, 429):
            log.warning("Serper fallito per esaurimento crediti o autenticazione (HTTP %d): %s", resp.status_code, resp.text[:300])
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("Serper scrape fallito: %s", e)
        return f"  Scrape fallito: {e}", False

    if "EBAY" in label.upper():
        content = data.get("html") or data.get("rawHtml") or data.get("raw_html") or data.get("content") or data.get("markdown") or ""
        return _estrai_articoli_ebay(content), True
    elif "VINTED" in label.upper():
        content = data.get("markdown") or data.get("text") or ""
        return _estrai_articoli_vinted(content), True
    return "  Fonte non supportata.", True


def _serper_batch_query_vestiaire(brand, categoria):
    """Ritorna (testo_vestiaire, successo)."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", False

    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "dress").strip()
    query_serper = f'site:vestiairecollective.com "{brand_pulito}" {categoria_per_query} €'.strip() if brand_pulito else f'site:vestiairecollective.com {categoria_per_query} €'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if resp.status_code in (401, 402, 403, 429):
            log.warning("Serper search fallito per esaurimento crediti o autenticazione (HTTP %d)", resp.status_code)
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        log.warning("Serper Vestiaire query fallita: %s", e)
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


def search_comps_completo(brand, categoria, query_base):
    """Esegue le 3 ricerche Serper (Vestiaire via Google, Vinted, eBay) in
    parallelo. Ritorna (testo_comp_completo, serper_ha_funzionato).
    serper_ha_funzionato=False se TUTTE e 3 le chiamate sono fallite per
    motivi di servizio (non "zero risultati", che e' un successo)."""
    materiale_per_ricerca = scegli_materiale_per_ricerca(query_base)
    vinted_url, _ = build_vinted_search_url(brand, categoria, materiale_per_ricerca)
    ebay_url = search_comps_ebay_sold_url(brand, categoria)

    risultati = {}
    successi = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_vestiaire = executor.submit(_serper_batch_query_vestiaire, brand, categoria)
        future_vinted = executor.submit(_serper_scrape_page_diretto, "VINTED", vinted_url)
        future_ebay = executor.submit(_serper_scrape_page_diretto, "EBAY SOLD", ebay_url)
        futures = {future_vestiaire: "vestiaire", future_vinted: "vinted", future_ebay: "ebay"}
        for future in as_completed(futures, timeout=25):
            nome = futures[future]
            try:
                testo, ok = future.result()
                risultati[nome] = testo
                successi[nome] = ok
            except Exception as e:
                risultati[nome] = f"  Query fallita: {e}"
                successi[nome] = False

    serper_ha_funzionato = any(successi.values())  # almeno UNA fonte ha risposto correttamente

    testo_finale = (
        f"RICERCA WEB PRE-RACCOLTA (3 fonti, base: '{query_base}'):\n\n"
        f"📍 FONTE: VESTIAIRE COLLECTIVE\n{risultati.get('vestiaire', 'Nessun risultato')}\n\n"
        f"📍 FONTE: VINTED (scrape diretto)\n{risultati.get('vinted', 'Nessun risultato')}\n\n"
        f"📍 FONTE: EBAY SOLD (scrape diretto)\n{risultati.get('ebay', 'Nessun risultato')}"
    )
    return testo_finale, serper_ha_funzionato


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO (early exit a costo zero, identico alla logica precedente)
# ---------------------------------------------------------------------------

def _stima_costo_pieno_da_prezzo_e_lingua(prezzo_richiesto_str, titolo, descrizione):
    try:
        prezzo = float(str(prezzo_richiesto_str).replace(",", "."))
    except (TypeError, ValueError):
        return None
    testo = f"{titolo or ''} {descrizione or ''}".lower()
    indicatori_non_it = (" la ", " et ", " avec ", " une ", " talle ", " size ", " größe ", " und ", " met ", " con la ", " der ", " die ", " das ")
    spedizione_stimata = 4.50 if any(ind in testo for ind in indicatori_non_it) else 2.50
    return round(prezzo + round(prezzo * 0.05 + 0.70, 2) + spedizione_stimata, 2)


def estrai_decisione_da_testo(testo):
    """Estrae la riga 'Decisione' dal verdetto in testo libero, per
    decidere se vale la pena mandare il messaggio al proprietario o se
    e' chiaramente un NON COMPRARE da poter loggare e basta."""
    match = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", testo)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE: SCENARIO G CON FALLBACK A F
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
            "color_raw": scraped.get("color_raw"),
        })
        for photo_url in scraped.get("photo_urls", []):
            img = download_image_bytes(photo_url, referer=url)
            if img:
                photo_bytes_list.append(img)
            time.sleep(0.4)

    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]
    if not photo_bytes_list:
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID, f"⚠️ Niente foto per: {listing_info.get('title')}\nSalto valutazione.")
        return

    user_text_occhi = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Materiale (da pagina annuncio): {listing_info.get('material_raw') or 'non disponibile'}\n"
        f"Colore (da pagina annuncio): {listing_info.get('color_raw') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}"
    )

    # ===== STEP 1: OCCHI -- foto + valutazione preliminare, zero ricerca web =====
    output_occhi, costo_occhi, _ = chiama_gemini(GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
    costo_totale += costo_occhi
    log.info("Occhi completati. Costo: $%.5f", costo_occhi)

    # ===== STEP 2: decidere Scenario G o F in base a Serper =====
    titolo_annuncio = listing_info.get("title") or ""
    brand_annuncio = listing_info.get("brand") or ""
    categoria_per_ricerca = estrai_categoria_da_titolo(titolo_annuncio) or ""

    scenario_usato = "F"  # default pessimista, sovrascritto sotto se Serper funziona
    comps_text = None

    tempo_trascorso_da_ultimo_fallimento = time.time() - _serper_timestamp_ultimo_fallimento[0]
    in_raffreddamento = (
        _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
        and tempo_trascorso_da_ultimo_fallimento < RAFFREDDAMENTO_SERPER_SECONDI
    )
    serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

    if serper_disponibile:
        comps_text, serper_ok = search_comps_completo(brand_annuncio, categoria_per_ricerca, titolo_annuncio)
        if serper_ok:
            scenario_usato = "G"
            _serper_fallimenti_consecutivi[0] = 0
        else:
            _serper_fallimenti_consecutivi[0] += 1
            _serper_timestamp_ultimo_fallimento[0] = time.time()
            log.warning(
                "Serper fallito (%d fallimenti consecutivi) -- fallback a Scenario F per questo annuncio.",
                _serper_fallimenti_consecutivi[0],
            )
            if _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO:
                log.warning(
                    "Soglia di %d fallimenti consecutivi raggiunta -- Serper verra' SALTATO per le prossime %.1f ore "
                    "(probabile esaurimento crediti), poi si ritentera' automaticamente. Verificare manualmente "
                    "l'account Serper se il problema persiste oltre questo periodo.",
                    SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO, RAFFREDDAMENTO_SERPER_SECONDI / 3600,
                )
    else:
        if in_raffreddamento:
            ore_rimanenti = (RAFFREDDAMENTO_SERPER_SECONDI - tempo_trascorso_da_ultimo_fallimento) / 3600
            log.info("Serper in raffreddamento (~%.1f ore rimanenti prima del prossimo tentativo) -- uso Scenario F.", ore_rimanenti)
        else:
            log.info("Serper non disponibile (SERPER_API_KEY assente) -- uso Scenario F.")

    # ===== STEP 3: CERVELLO -- rivalutazione con grounding forzato, G o F =====
    if scenario_usato == "G":
        user_text_cervello = (
            f"{user_text_occhi}\n\n--- LA TUA VALUTAZIONE PRELIMINARE (prodotta poco fa, senza ricerca web) ---\n"
            f"{output_occhi}\n--- FINE ---\n\n"
            f"--- {comps_text} ---\n\n"
            "Usa i risultati di ricerca web PRE-RACCOLTI sopra per confermare/correggere la tua proposta. "
            "Esegui INOLTRE almeno una ricerca con il tool google_search per verificare o completare questi "
            "dati (es. se manca un sold eBay, se i prezzi Vestiaire sono pochi, se vuoi controllare Depop/"
            "Grailed/1stDibs che non sono stati pre-raccolti). Produci il verdetto operativo completo."
        )
    else:
        user_text_cervello = (
            f"{user_text_occhi}\n\n--- LA TUA VALUTAZIONE PRELIMINARE (prodotta poco fa, senza ricerca web) ---\n"
            f"{output_occhi}\n--- FINE ---\n\n"
            "NOTA: non ci sono risultati di ricerca pre-raccolti in questo scenario (Serper non disponibile). "
            "DEVI usare attivamente il tool google_search per trovare comp reali prima di produrre il verdetto "
            "finale, seguendo le istruzioni nel tuo system prompt (eBay sold, Vinted, Depop, Vestiaire, Grailed, "
            "1stDibs nell'ordine di priorita' indicato)."
        )

    output_finale, costo_cervello, n_query_grounding = chiama_gemini(
        GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, photo_bytes_list=[], grounding=True,
    )
    costo_totale += costo_cervello
    log.info(
        "Scenario %s completato. Query grounding: %d. Costo cervello: $%.5f. Costo totale annuncio: $%.5f",
        scenario_usato, n_query_grounding, costo_cervello, costo_totale,
    )

    # ===== INVIO TELEGRAM =====
    header = (
        f"🆕 *{listing_info.get('title')}*\n"
        f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
        f"🔧 Scenario {scenario_usato}"
        + (f" ({n_query_grounding} ricerche)" if n_query_grounding else " (nessuna ricerca eseguita dal modello)")
        + f"\n{url or ''}\n{'—' * 20}\n"
    )
    telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))
    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + output_finale)


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_recent_listings_seen = {}


def e_variante_recente(parsed):
    t = parsed.get("title", "").strip()
    chiave = (re.sub(r"\s+", " ", t).strip().lower(), (parsed.get("brand") or "").strip().lower(), (parsed.get("price") or "").strip())
    now = time.time()
    for k in [k for k, ts in _recent_listings_seen.items() if now - ts > 300]:
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
    log.info("Vinted Oracle (Scenario G con fallback F) avviato su Telethon.")
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
