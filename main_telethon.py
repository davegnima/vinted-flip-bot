"""
Vinted Flip Oracle Bot (versione Telethon / userbot)
======================================================
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
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERPER_API_KEY = os.environ["SERPER_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_GALLERY_PHOTOS = 6  

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

VINTED_BRAND_IDS = {
    "brunello cucinelli": "103740", "rick owens": "145654", "arc'teryx": "319730", "arcteryx": "319730",
    "patagonia": "90804", "marni": "12251", "missoni": "4463", "jean paul gaultier": "4129", "jpg": "4129",
    "emilio pucci": "10831", "pucci": "10831", "issey miyake": "75090", "pleats please": "395642",
    "pleats please issey miyake": "395642", "claude montana": "121608", "miu miu": "1745",
    "thierry mugler": "284", "mugler": "284", "courreges": "12639", "courrèges": "12639",
    "m missoni": "1702343", "missoni home": "2776470", "missoni mare": "2720679", "vivienne westwood": "14217",
    "yohji yamamoto": "200474", "dries van noten": "72138", "ann demeulemeester": "51445", "raf simons": "184436",
    "loewe": "24209", "helmut lang": "47829", "jil sander": "17991", "bottega veneta": "86972",
    "maison margiela": "639289", "margiela": "639289", "max mara": "5483", "veilance": "3388210",
    "nanga": "434286", "snow peak": "666350", "acronym": "712647",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vinted_flip_bot")


# ---------------------------------------------------------------------------
# VINTED FLIP ORACLE PRO -- system prompt (CLAUDE)
# ---------------------------------------------------------------------------

VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT = r"""
Sei **Vinted Flip Oracle Pro**: valuti annunci second-hand (Vinted, Vestiaire, Grailed, eBay, Depop, Wallapop, StockX/GOAT) per stabilire se conviene comprarli per rivendere. Freddo, preciso, conservativo.

# INPUT
Ricevi un JSON di Gemini che contiene un Legit Check visivo di precisione e i difetti. Questo JSON è la tua unica fonte visiva.
REGOLA VINCOLANTE: se Gemini scrive "ASSENZA TOTALE DI PROVE" nei fake_flags → la decisione NON PUÒ essere nessun livello COMPRA o TRATTA. Solo CHIEDI ALTRE FOTO o NON COMPRARE.

# MARGINE E SOGLIE
Margine a DUE GAMBE sempre:
**Acquisto pieno** = prezzo + protezione acquirenti (~5%+€0,70) + spedizione entrata (IT 2,50€, FR/ES/PT 4,50€, DE/NL/nord EU 5-6€).
**Incasso** = vendita probabile post-trattativa − spedizione offerta − sconto chiusura.
**Margine netto = incasso − acquisto pieno**, sempre € e ROI%. Soglia utente: 20€ netti — sotto, default NON COMPRARE anche con ROI alto.
Voto Margine: 0-2/10 <10€/negativo; 3-4/10 10-19€; 5-6/10 20-39€; 7-8/10 40-99€; 9-10/10 100€+. ROI 80%+→+1, 40-80%→0, <20%→-1.

REGOLE COMPRA/TRATTA (applica in ordine):
1. Costo pieno <15€ E legit check non negativo E margine 80€+ → COMPRA SUBITO.
2. Se margine pieno è già sopra 20€, MAI scrivere TRATTA. Scegli il livello COMPRA.
3. Eccezione: margine sopra soglia ma 20-40€ E confidenza Media/Bassa E capo hype/monitorato → TRATTA.
4. TRATTA/TRATTA FORTE altrimenti solo se margine pieno sotto soglia ma accettabile scontando.
5. ECCEZIONE "Y2K / HYPE IMPULSE BUY": Se il costo d'acquisto pieno è molto basso (< 25€), il brand ha un forte hype attuale (es. Mugler, Diesel, Missoni, Carhartt Y2K) e il design è iconico/trendy, la liquidità batte la condizione e l'assenza di comps. In questi casi, anche senza comps o con macchie lavabili, il capo verrà venduto per acquisto d'impulso. Usa "COMPRA" o "COMPRA SE CI TIENI", assegna Liquidità: Alta.

# MATRICE DECISIONALE
1. COMPRA SUBITO — Deal 9-10 E Margine 8-10 E Confidenza non Bassa E Rischio non ALTO.
2. COMPRA FORTE — Deal 8 E Margine 7-8, Rischio BASSO/MEDIO.
3. COMPRA — Deal 6-7 E Margine 5-7, Rischio BASSO/MEDIO.
4. COMPRA SE CI TIENI — Deal 4-5 O Margine 4-5.
5. TRATTA (o FORTE) — vedi regole sopra.
6. NON COMPRARE — margine insufficiente, Rischio ALTO, o legit check negativo.

Urgenza:
- AGISCI ORA: scarto prezzo estremo, o 0-2gg + hype.
- HAI QUALCHE ORA: margine buono non estremo, recente ma non hype.
- HAI TEMPO: 5+gg senza compratori.

# PREZZI — RICERCA E VALUTAZIONE
1. Vinted mostra solo ASK mai sold. Gerarchia: eBay sold > Vestiaire > Vinted. Sold estero va scontato per Vinted IT.
2. Target vendita 7-14gg.
3. VALUTAZIONE IN ASSENZA DI COMPS ESTERNI: Se la ricerca dichiara "nessun risultato" o "emergenza larga", **NON USARE MAI "N/A"**. Devi obbligatoriamente stimare il prezzo di "Vendita probabile" basandoti sulla tua profonda conoscenza del mercato. Dichiara "Confidenza: Bassa" o "Media" e scrivi "Stima basata su storico brand" in "In una riga". MAI N/A.

CONTROLLO FINALE: Margine sotto 20€? Se SÌ, la decisione NON PUÒ essere nessun livello COMPRA — deve essere TRATTA o NON COMPRARE (salvo Y2K Impulse Buy).

# OUTPUT — formato compatto, italiano. TETTO 150 PAROLE TOTALI. Niente testo prima o dopo.

## Verdetto operativo
- **Decisione:** [qualità] · [urgenza], es. "COMPRA SUBITO · AGISCI ORA"
- **Costo pieno richiesto:** €X (prezzo+protezione+spedizione)
- **Costo pieno trattato:** €X o N/A
- **Vendita probabile:** €X in ~Z giorni
- **Margine netto:** €X (ROI Y%) — richiesto · trattato, una riga
- **Deal:** X/10 · **Margine:** X/10 · **Liquidità:** Bassa/Media/Alta · **Rischio:** BASSO/MEDIO/ALTO · **Confidenza:** Alta/Media/Bassa
- **In una riga:** [max15 parole]

## Legit check
Una riga, max20 parole: verdetto + confidenza% + segnale chiave.

## Da chiedere
Max3 domande telegrafiche, o "Non rilevante".

## Messaggio da inviare
SEMPRE in italiano. Messaggio pronto breve, o "Non necessario".
""".strip()

# ---------------------------------------------------------------------------
# GEMINI VISION SYSTEM PROMPT (Nuovo Legit Check Strutturato)
# ---------------------------------------------------------------------------
GEMINI_VISION_SYSTEM_PROMPT = """
Sei un analista visivo specializzato in autenticazione e valutazione di capi di abbigliamento e accessori second-hand per il flipping. 
Il tuo scopo è fare un Legit Check rigoroso (analizzando font, cuciture, etichette) e fare da "buttafuori" scartando capi falsi o in pessime condizioni.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo prima o dopo, nessun blocco markdown).

{
  "identificazione": {
    "brand_visibile": "...",
    "categoria_capo": "Es. T-shirt, Borsa, Giacca",
    "modello_specifico": "Se riconoscibile. Altrimenti vuoto.",
    "taglia_visibile": "..."
  },
  "condizione_visibile": {
    "stato_generale": "Nuovo / Ottimo / Usato / Da riparare",
    "difetti_rilevati": "Sii specifico su buchi, macchie, usura (max 20 parole). Se perfetto scrivi: Nessun difetto evidente."
  },
  "legit_check_dettagliato": {
    "loghi_e_marchi": "Analisi font, ricami, stampe. Sono coerenti con l'originale? (max 20 parole)",
    "etichette_e_cuciture": "Analisi wash tag, etichetta collo, precisione cuciture. (max 20 parole)",
    "hardware_e_dettagli": "Zip, bottoni, codici seriali se visibili. (max 20 parole)",
    "fake_flags_o_incongruenze": "Segnala qui ogni sbavatura, errore di font o discrepanza. Se non ci sono loghi scrivi TASSATIVAMENTE: 'ASSENZA TOTALE DI PROVE'.",
    "foto_mancanti": "Cosa manca per l'autenticazione certa? (es. retro wash tag, close-up zip)"
  },
  "legit_check_sintesi": {
    "verdetto": "Probabilmente autentico / Sospetto, servono altre foto / Probabilmente falso / Non verificabile",
    "confidenza_pct": 0,
    "rischio_fake_brand": "Basso / Medio / Alto / Molto alto"
  },
  "valutazione_flipper_preliminare": {
    "categoria_a_basso_valore": false,
    "verdetto_grezzo": "NON COMPRARE / VALUTA / COMPRA",
    "motivo": "Max 10 parole"
  }
}

REGOLE CRITICHE:
1. NON trascrivere le etichette parola per parola. Sintetizza la loro correttezza nel campo 'etichette_e_cuciture'.
2. Se un logo non corrisponde al brand dichiarato o ha font palesemente errati, segnalalo subito in 'fake_flags_o_incongruenze'.
3. Un pattern generico senza etichette NON prova l'autenticità: usa 'ASSENZA TOTALE DI PROVE'.
4. "verdetto_grezzo" DEVE ESSERE 'NON COMPRARE' se rilevi buchi, macchie gravi, o se il legit check è 'Probabilmente falso'.
5. Rispettare i limiti di parole è TASSATIVO per ragioni di sistema.
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
        if split_at == -1: split_at = remaining.rfind("\n", 0, MAX_LEN)
        if split_at == -1: split_at = MAX_LEN
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    for i, chunk in enumerate(chunks, start=1):
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
        if not resp.ok:
            log.warning("sendMessage con Markdown fallita. Ritento senza parse_mode.")
            requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}, timeout=20)

def telegram_send_photo(chat_id, photo_bytes, caption=None):
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption: data["caption"] = caption[:1024]
    resp = requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=30)
    if not resp.ok: log.warning("sendPhoto fallita: %s", resp.text[:300])

# ---------------------------------------------------------------------------
# PARSING DEL MESSAGGIO E SCRAPING
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
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Accept-Language": "it-IT,it;q=0.9",
}

IMAGE_DOWNLOAD_HEADERS = {
    "User-Agent": VINTED_HEADERS["User-Agent"], "Accept-Language": VINTED_HEADERS["Accept-Language"],
    "Referer": "https://www.vinted.it/", "Accept": "image/webp,image/avif,image/jpeg,image/png,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-site", "Connection": "keep-alive",
}

_vinted_session = requests.Session()
_vinted_session.headers.update(VINTED_HEADERS)

def scrape_vinted_listing(url):
    result = {"photo_urls": [], "size": None, "condition": None, "description": None, "created_at": None, "age_days": None}
    log.info("Avvio scraping pagina annuncio: %s", url)
    try:
        resp = _vinted_session.get(url, headers=VINTED_HEADERS, timeout=8)
        resp.raise_for_status()
        html = resp.text

        matches = re.findall(r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/((?:f800|\d+x\d+))/[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html)
        full_matches = re.findall(r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/(?:f800|\d+x\d+)/[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html)
        best_url_by_photo_id = {}
        for (photo_id, resolution), full_url in zip(matches, full_matches):
            if photo_id not in best_url_by_photo_id or resolution == "f800":
                best_url_by_photo_id[photo_id] = full_url
        clean_urls = list(best_url_by_photo_id.values())
        result["photo_urls"] = clean_urls[:MAX_GALLERY_PHOTOS]

        size_match = re.search(r'"size_title"\s*:\s*"([^"]+)"', html)
        if size_match: result["size"] = size_match.group(1)
        condition_match = re.search(r'"status"\s*:\s*"([^"]+)"', html)
        if condition_match: result["condition"] = condition_match.group(1)
        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
        if desc_match: result["description"] = desc_match.group(1).encode().decode("unicode_escape")
        created_match = re.search(r'"created_at_ts"\s*:\s*"([^"]+)"', html)
        if created_match:
            try:
                from datetime import datetime, timezone
                created_dt = datetime.fromisoformat(created_match.group(1))
                if created_dt.tzinfo is None: created_dt = created_dt.replace(tzinfo=timezone.utc)
                result["age_days"] = round((datetime.now(timezone.utc) - created_dt).total_seconds() / 86400, 1)
            except: pass
        log.info("Scraping completato: individuate %d foto potenziali.", len(result["photo_urls"]))
    except Exception as e:
        log.warning("Scraping Vinted fallito (timeout o blocco IP) per %s: %s", url, type(e).__name__)
    return result

def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=1):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    for attempt in range(1, max_retries + 1):
        try:
            resp = _vinted_session.get(url, headers=headers, timeout=4)
            if resp.ok: return resp.content
        except Exception: pass
    return None

# ---------------------------------------------------------------------------
# PIL FOTO COMPRESSION & GEMINI VISION
# ---------------------------------------------------------------------------

def optimize_image_bytes(img_bytes, max_size=512):
    try:
        img = Image.open(BytesIO(img_bytes))
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        log.warning("Ottimizzazione (Pillow) fallita, uso byte originali: %s", e)
        return img_bytes
        
def call_gemini_vision(photos_bytes_list, listing_info, max_retries=3):
    user_text_for_log = f"Titolo: {listing_info.get('title')}\nBrand Dichiarato: {listing_info.get('brand')}\nPrezzo: {listing_info.get('price')} EUR\n"
    parts = [{"text": user_text_for_log + "Esegui un Legit Check visivo di precisione basandoti sulle foto."}]

    for img_bytes in photos_bytes_list:
        optimized_bytes = optimize_image_bytes(img_bytes)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(optimized_bytes).decode("utf-8")}})

    log.info("--- [GEMINI CONFIG] SYSTEM PROMPT INVIATO ---")
    log.info(GEMINI_VISION_SYSTEM_PROMPT)
    log.info("--------------------------------------------")

    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 1000, "responseMimeType": "application/json"},
    }

    backoff_seconds = 2
    for attempt in range(1, max_retries + 1):
        try:
            log.info("🤖 [PASSAGGIO 2] Chiamata a Gemini Vision... (Attesa massima impostata a 120s per evitare timeout)")
            resp = requests.post(GEMINI_API_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=120)
            
            if resp.ok:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates and isinstance(candidates, list):
                    content_node = candidates[0].get("content", {})
                    parts_list = content_node.get("parts", []) if isinstance(content_node, dict) else []
                    extracted_text = "".join(p.get("text", "") for p in parts_list if isinstance(p, dict))
                    
                    if extracted_text and len(extracted_text.strip()) >= 30:
                        try:
                            json.loads(extracted_text)
                            log.info("--- [GEMINI RESPONSE] OUTPUT JSON RICEVUTO ---")
                            log.info(extracted_text)
                            log.info("---------------------------------------------")
                            return extracted_text
                        except ValueError:
                            pass
            
            log.warning("⚠️ Gemini ha risposto con un errore o JSON incompleto (tentativo %d/%d). Ritento...", attempt, max_retries)
            time.sleep(backoff_seconds)
            backoff_seconds *= 2
        except requests.exceptions.RequestException as exc:
            log.warning("❌ Errore di rete o Timeout scaduto su Gemini (tentativo %d/%d): %s - Ritento...", attempt, max_retries, type(exc).__name__)
            if attempt < max_retries:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
            else: break

    fallback = json.dumps({
        "identificazione": {"brand_visibile": listing_info.get("brand", ""), "categoria_capo": "", "modello_specifico": "", "taglia_visibile": ""},
        "condizione_visibile": {"stato_generale": "Non verificabile", "difetti_rilevati": "Errore API."},
        "legit_check_sintesi": {"verdetto": "Non verificabile", "confidenza_pct": 50, "rischio_fake_brand": "Medio"},
        "legit_check_dettagliato": {"fake_flags_o_incongruenze": "Timeout API."},
        "valutazione_flipper_preliminare": {"categoria_a_basso_valore": False, "verdetto_grezzo": "NON COMPRARE", "motivo": "Errore API visiva."}
    })
    log.warning("🚨 Usato JSON Fallback d'emergenza per Gemini.")
    return fallback

# ---------------------------------------------------------------------------
# SERPER COMPS SEARCH CON FALLBACK "LARGO"
# ---------------------------------------------------------------------------

def _serper_batch_query(labeled_queries, num_results=4):
    labels = [label for label, _ in labeled_queries]
    queries = [query for _, query in labeled_queries]
    try:
        resp = requests.post("https://google.serper.dev/search", headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}, json=[{"q": q, "gl": "it", "hl": "it", "num": num_results} for q in queries], timeout=15)
        batch_results = resp.json()
    except Exception: return {label: "Fallita" for label in labels}
    if not isinstance(batch_results, list) or len(batch_results) != len(labels): return {label: "Inattesa" for label in labels}
    
    results_by_label = {}
    for label, data in zip(labels, batch_results):
        organic = data.get("organic", []) if isinstance(data, dict) else []
        if not organic:
            results_by_label[label] = "Nessun risultato trovato."
            continue
        lines = [f"  - {r.get('title', '')}\n    {r.get('snippet', '')}\n    [{r.get('link', '')}]" for r in organic[:num_results]]
        results_by_label[label] = "\n".join(lines)
    return results_by_label

def build_vinted_search_url(brand, modello_o_categoria):
    from urllib.parse import quote
    brand_lower = (brand or "").strip().lower()
    brand_id = VINTED_BRAND_IDS.get(brand_lower)
    if brand_id: return f"https://www.vinted.it/catalog?brand_ids[]={brand_id}&search_text={quote(modello_o_categoria or '')}&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3", True
    return f"https://www.vinted.it/catalog?search_text={quote(f'{brand} {modello_o_categoria}'.strip())}&order=newest_first", False

def search_comps_ebay_sold(brand, modello, categoria):
    from urllib.parse import quote
    q = f"{brand} {modello} {categoria}".strip()
    return f"https://www.ebay.it/sch/i.html?_nkw={quote(q)}&LH_Sold=1&LH_Complete=1&_sop=13" if q else None

def _clean_scraped_markdown(content):
    if not content: return content
    content = re.sub(r"^---\s*\nmeta-[\s\S]*?\n---\s*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^meta-[\w-]+:.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"^title:.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"!\[SVG Image\]\(data:image/svg\+xml;base64,[^)]+\)", "", content)
    content = re.sub(r"\(data:image/svg\+xml;base64,[^)]+\)", "", content)
    content = re.sub(r"\[Vendi un oggetto simile\]\([^)]+\)", "", content)
    content = re.sub(r"\[Logo di Vinted\]\([^)]+\)", "", content)
    content = re.sub(r"\[Passa al contenuto!?\[[^\]]*\]\([^)]+\)\]\([^)]+\)", "", content)
    content = re.sub(r"!\[Catalogo\]\([^)]+\)", "", content)
    return re.sub(r"\n{3,}", "\n\n", content).strip()

def _serper_scrape_page(url, max_chars=2500):
    try:
        resp = requests.post("https://scrape.serper.dev", headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}, json={"url": url, "includeMarkdown": True}, timeout=15)
        data = resp.json()
        content = data.get("markdown") or data.get("text") or ""
        return _clean_scraped_markdown(content)[:max_chars] if content else None
    except: return None

def search_comps_serper(brand, modello, categoria):
    query_specifica = f"{brand} {modello} {categoria}".strip()
    if not query_specifica: return "RICERCA WEB: non eseguita per mancanza dati."

    def esegui_ricerca(query_da_cercare):
        vinted_url, vinted_e_per_id = build_vinted_search_url(brand, query_da_cercare.replace(brand, "").strip())
        ebay_url = search_comps_ebay_sold(brand, query_da_cercare.replace(brand, "").strip(), "")
        serper_queries = [
            ("VESTIAIRE COLLECTIVE", f"{query_da_cercare} site:vestiairecollective.com"),
            ("GOOGLE GENERICO", f"{query_da_cercare} prezzo valore usato"),
        ]

        results_by_label = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_batch = executor.submit(_serper_batch_query, serper_queries)
            future_vinted = executor.submit(_serper_scrape_page, vinted_url)
            future_ebay = executor.submit(_serper_scrape_page, ebay_url)
            futures = {future_batch: "__BATCH__", future_vinted: "VINTED (scrape)", future_ebay: "EBAY SOLD (scrape)"}

            for future in as_completed(futures, timeout=15):
                label = futures[future]
                try:
                    res = future.result()
                    if label == "__BATCH__": results_by_label.update(res)
                    else: results_by_label[label] = res if res else "Nessun risultato"
                except:
                    if label == "__BATCH__":
                        for q_l, _ in serper_queries: results_by_label[q_l] = "Fallita"
                    else: results_by_label[label] = "Fallita"
        return results_by_label

    # 1. TENTATIVO CON QUERY SPECIFICA
    log.info("🔎 Avvio ricerca Serper Specifica: '%s'", query_specifica)
    risultati = esegui_ricerca(query_specifica)
    fallimento_totale = all(any(m in v for m in ("Nessun", "Fallita")) for v in risultati.values())

    # 2. TENTATIVO CON QUERY LARGA (Fallback Emergenza)
    if fallimento_totale and modello:
        query_larga = f"{brand} {categoria}".strip()
        log.info("⚠️ Ricerca specifica fallita. Avvio ricerca WEB Larga: '%s'", query_larga)
        risultati = esegui_ricerca(query_larga)
        query_usata = query_larga
        avviso = "⚠️ NOTA: Ricerca di emergenza larga (il modello specifico non ha dato risultati)."
    else:
        query_usata = query_specifica
        avviso = ""

    lines = [f"RICERCA WEB (base: '{query_usata}'):"]
    if avviso: lines.append(avviso)
    for label, res in risultati.items(): lines.append(f"\n📍 FONTE: {label}\n{res}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLAUDE ORACLE (Con Estrazione Strutturata)
# ---------------------------------------------------------------------------

def call_claude_oracle(listing_info, gemini_analysis_json):
    age_days = listing_info.get("age_days")
    age_text = f"{age_days:.1f} giorni fa" if age_days is not None else "non disponibile"

    try:
        gemini_data = json.loads(gemini_analysis_json)
        ident = gemini_data.get("identificazione", {})
        
        # Estrazione logica strutturata per la ricerca perfetta
        brand_per_ricerca = ident.get("brand_visibile") or listing_info.get("brand") or ""
        categoria_per_ricerca = ident.get("categoria_capo") or ""
        modello_per_ricerca = ident.get("modello_specifico") or ""
        
        if not modello_per_ricerca and listing_info.get("size"):
            modello_per_ricerca = f"taglia {listing_info.get('size')}"
            
    except Exception:
        brand_per_ricerca = listing_info.get("brand") or ""
        modello_per_ricerca = ""
        categoria_per_ricerca = ""

    log.info("🌐 [PASSAGGIO 3] Avvio indagine di mercato tramite Serper API...")
    comps_text = search_comps_serper(brand_per_ricerca, modello_per_ricerca, categoria_per_ricerca)
    
    log.info("--- [SERPER COMPS] DATI DI MERCATO RECUPERATI ---")
    log.info(comps_text)
    log.info("-------------------------------------------------")
    
    user_text = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto dal venditore: {listing_info.get('price')} EUR\n"
        f"Taglia/Condizione: {listing_info.get('size') or 'N/D'} / {listing_info.get('condition') or 'N/D'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"Annuncio pubblicato: {age_text}\n"
        f"URL annuncio: {listing_info.get('url') or 'non disponibile'}\n\n"
        "--- ANALISI VISIVA E LEGIT CHECK PRELIMINARE (JSON GEMINI) ---\n"
        f"{gemini_analysis_json}\n"
        "--- FINE ANALISI VISIVA ---\n\n"
        "--- RISULTATI RICERCA WEB (UNICI dati di mercato disponibili) ---\n"
        f"{comps_text}\n"
        "--- FINE RISULTATI RICERCA WEB ---\n\n"
        "Produci ora il verdetto operativo completo, nel formato compatto richiesto."
    )

    log.info("🧠 [PASSAGGIO 4] Costruzione pacchetto per Claude Sonnet...")
    log.info("--- [CLAUDE CONFIG] SYSTEM PROMPT ---")
    log.info(VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT)
    log.info("--- [CLAUDE CONFIG] USER PROMPT INVIATO ---")
    log.info(user_text)
    log.info("-------------------------------------------")

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1200,
        "system": [{"type": "text", "text": VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_text}]}],
    }

    resp = requests.post(ANTHROPIC_API_URL, headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=payload, timeout=120)
    resp.raise_for_status()
    
    final_text = "".join(b["text"] for b in resp.json().get("content", []) if b.get("type") == "text")
    
    log.info("--- [CLAUDE RESPONSE] REPORT GENERATO ---")
    log.info(final_text)
    log.info("-----------------------------------------")

    verdetto_pos = final_text.find("## Verdetto operativo")
    if verdetto_pos > 0: final_text = final_text[verdetto_pos:]

    decisione_match = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", final_text)
    decisione_text = decisione_match.group(1) if decisione_match else ""
    if "COMPRA" in decisione_text and re.search(r"sotto\s+soglia", final_text, re.IGNORECASE):
        costo_trattato_match = re.search(r"\*\*Costo pieno trattato:\*\*\s*(N/A|€[\d.,]+)", final_text, re.IGNORECASE)
        costo_trattato_valido = bool(costo_trattato_match and costo_trattato_match.group(1).upper() != "N/A")
        nuova_dec = "TRATTA FORTE · HAI TEMPO" if costo_trattato_valido else "NON COMPRARE · N/A"
        final_text = re.sub(r"(\*\*Decisione:\*\*\s*)[^\n]+", r"\1" + nuova_dec + " ⚠️ _(corretto)_", final_text, count=1)

    decisione_match_2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", final_text)
    decisione_text_2 = decisione_match_2.group(1) if decisione_match_2 else ""
    if "COMPRA SUBITO" in decisione_text_2 and re.search(r"\*\*Confidenza:\*\*\s*Bassa", final_text, re.IGNORECASE):
        final_text = re.sub(r"(\*\*Decisione:\*\*\s*)[^\n]+", r"\1COMPRA FORTE · HAI QUALCHE ORA ⚠️ _(corretto)_", final_text, count=1)

    return final_text


# ---------------------------------------------------------------------------
# PIPELINE EARLY EXIT & GESTIONE SCARTI
# ---------------------------------------------------------------------------

def check_skip_pre_claude(gemini_analysis_json):
    try:
        data = json.loads(gemini_analysis_json)
        l_check_sintesi = data.get("legit_check_sintesi", {})
        l_check_dettagli = data.get("legit_check_dettagliato", {})
        v_flipper = data.get("valutazione_flipper_preliminare", {}) 
        
        if (l_check_sintesi.get("verdetto") or "").strip().lower() == "probabilmente falso" and int(l_check_sintesi.get("confidenza_pct", 0)) >= 85:
            return True, f"[FALSO CONCLAMATO] {l_check_dettagli.get('fake_flags_o_incongruenze', '')}"
        if v_flipper.get("categoria_a_basso_valore") is True:
            return True, "[CATEGORIA BASSO VALORE] Articolo fuori target per il flipping."
        if (v_flipper.get("verdetto_grezzo") or "").strip().upper() == "NON COMPRARE":
            return True, f"[VERDETTO GREZZO GEMINI] {v_flipper.get('motivo', '')}"
    except:
        pass
    return False, None

def build_skip_report(listing_info, motivo_falso):
    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        f"- **Costo pieno richiesto:** €{listing_info.get('price')} — bloccato da filtro precoce\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        "- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidità:** Bassa · **Rischio:** ALTO · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_falso[:120]}\n\n"
        "## Legit check\nFiltro automatico pre-Claude attivato per scarto palese.\n\n"
        "## Da chiedere\nNon rilevante.\n\n"
        "## Messaggio da inviare\nNon necessario."
    )

def process_listing(parsed, url, cover_photo_bytes):
    listing_info = dict(parsed)
    listing_info["url"] = url
    photo_bytes_list = []
    successful_urls = [] 

    log.info("=============================================================")
    log.info("🚀 INIZIO VALUTAZIONE NUOVO ANNUNCIO")
    log.info("=============================================================")
    log.info("Dati grezzi ricevuti da Telegram Tracker:\n%s", json.dumps(listing_info, indent=2, ensure_ascii=False))

    if url:
        scraped = scrape_vinted_listing(url)
        listing_info["size"] = scraped.get("size")
        listing_info["condition"] = scraped.get("condition")
        listing_info["description"] = scraped.get("description")
        listing_info["age_days"] = scraped.get("age_days")

        urls_to_download = scraped.get("photo_urls", [])
        if urls_to_download: log.info("[PASSAGGIO 1] Download galleria Vinted HD (%d foto)...", len(urls_to_download))
        for photo_url in urls_to_download:
            img = download_image_bytes(photo_url, referer=url)
            if img: 
                photo_bytes_list.append(img)
                successful_urls.append(photo_url)
            time.sleep(0.4)

    if not photo_bytes_list and cover_photo_bytes:
        log.warning("⚠️ Scraping galleria fallito. Attivazione fallback: copertina Telegram.")
        photo_bytes_list = [cover_photo_bytes]
        successful_urls = ["[Miniatura di Copertina Telegram]"]

    if not photo_bytes_list: return

    log.info("--- [GALLERIA INVIATA A GEMINI] ---")
    for i, img_url in enumerate(successful_urls, start=1): log.info("  Foto %d -> %s", i, img_url)

    gemini_analysis_json = call_gemini_vision(photo_bytes_list, listing_info)

    e_skip, motivo_skip = check_skip_pre_claude(gemini_analysis_json)
    if e_skip:
        log.info(f"⚡ [EARLY EXIT] Claude NON consultato. Motivo: {motivo_skip}")
        final_report = build_skip_report(listing_info, motivo_skip)
    else:
        final_report = call_claude_oracle(listing_info, gemini_analysis_json)

    header = f"🆕 *{listing_info.get('title')}*\n🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n{url or ''}\n{'—'*20}\n"
    
    log.info("📤 [PASSAGGIO 5] Spedizione pacchetto finale su Telegram...")
    telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))
    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + final_report)
    log.info("======================= VALUTAZIONE FINE =======================\n")


# ---------------------------------------------------------------------------
# TELETHON CLIENT E GESTIONE EVENTI
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_MAX_PROCESSED_IDS_TRACKED = 500

@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
async def on_new_message(event):
    try:
        message_id = event.message.id
        if message_id in _processed_message_ids: return
        _processed_message_ids.add(message_id)
        if len(_processed_message_ids) > _MAX_PROCESSED_IDS_TRACKED: _processed_message_ids.discard(min(_processed_message_ids))

        sender = await event.get_sender()
        sender_name = ((getattr(sender, "username", None) or "") + " " + (getattr(sender, "first_name", None) or "")).lower()
        if not any(hint in sender_name for hint in VINTED_TRACKER_NAME_HINTS): return

        text = event.message.message or ""
        if not text.strip(): return

        parsed = parse_vinted_tracker_message(text)
        url = extract_url_from_text(text)

        if not url and event.message.buttons:
            for row in event.message.buttons:
                for button in row:
                    if "vinted." in (getattr(button, "url", None) or ""):
                        url = button.url
                        break

        cover_photo_bytes = None
        if event.message.photo:
            try: cover_photo_bytes = await asyncio.wait_for(event.message.download_media(bytes), timeout=7.0)
            except: pass

        log.info("Nuovo annuncio rilevato: %s | url=%s", parsed.get("title"), url)
        await asyncio.to_thread(process_listing, parsed, url, cover_photo_bytes)
    except Exception:
        log.error("Errore nella pipeline:\n%s", traceback.format_exc())

async def main():
    log.info("Vinted Flip Oracle Bot (Telethon) avviato e ottimizzato. In ascolto sul gruppo %s", TELEGRAM_GROUP_ID)
    await client.start()
    await client.run_until_disconnected()

if __name__ == "__main__":
    with client: client.loop.run_until_complete(main())
