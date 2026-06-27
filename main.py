"""
Vinted Flip Oracle Bot
=======================
Pipeline:
  1. Polling sul bot Telegram "Vinted Notification" (Bot API, no userbot)
  2. Quando arriva un messaggio da "Vinted Tracker" nel gruppo, estrae
     titolo / prezzo / brand / URL annuncio
  3. Scraping della pagina Vinted per recuperare TUTTE le foto della galleria
     + taglia/condizione/descrizione (se disponibili)
  4. Gemini 3 Flash: analisi visiva pura (identificazione, autenticità,
     condizione) -- NESSUN prezzo, NESSUna ricerca web
  5. Claude Sonnet 4.6: usa l'analisi di Gemini + foto + dati annuncio,
     fa ricerca web (tool web_search) e produce il report Vinted Flip
     Oracle Pro completo (11 sezioni, ma istruito a scrivere sintetico)
  6. Il risultato viene inviato in CHAT PRIVATA con te (non nel gruppo)

Variabili d'ambiente richieste (mai scritte nel codice):
  TELEGRAM_BOT_TOKEN     - token del bot "Vinted Notification"
  TELEGRAM_OWNER_CHAT_ID - il tuo chat id personale (dove ricevere i report)
  TELEGRAM_GROUP_ID      - id del gruppo "Dadegnima, Vinted Notific..." da ascoltare
  ANTHROPIC_API_KEY      - chiave API Claude
  GEMINI_API_KEY         - chiave API Gemini

Note operative:
  - Usa LONG POLLING (getUpdates), non webhook: piu' semplice da hostare
    su Railway/Render senza dominio pubblico.
  - Lo scraping Vinted e' il punto piu' fragile: se Vinted cambia markup
    o blocca le richieste, la funzione scrape_vinted_listing() va aggiornata.
    Il bot comunque NON si blocca: se lo scraping fallisce, usa solo la
    foto di copertina del messaggio Telegram come fallback.
"""

import os
import re
import time
import base64
import logging
import traceback
from io import BytesIO

import requests

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_CHAT_ID = os.environ["TELEGRAM_OWNER_CHAT_ID"]
TELEGRAM_GROUP_ID = os.environ["TELEGRAM_GROUP_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3-flash:generateContent"
)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_GALLERY_PHOTOS = 10  # tetto massimo foto da inviare ai modelli (costo)

POLL_INTERVAL_SECONDS = 4
STATE_FILE = "last_update_id.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("vinted_flip_bot")


# ---------------------------------------------------------------------------
# VINTED FLIP ORACLE PRO -- system prompt (versione integrale, con istruzione
# aggiuntiva di sintesi e di USARE l'analisi visiva fornita da Gemini)
# ---------------------------------------------------------------------------

VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT = r"""
Tu sei **Vinted Flip Oracle Pro**, un esperto d'élite di flipping, resale, arbitraggio second hand, autenticazione visiva, pricing realistico e negoziazione su marketplace peer-to-peer come Vinted, Vestiaire Collective, Grailed, eBay, Depop, Wallapop, StockX/GOAT e community specializzate.

Il tuo compito è analizzare l'annuncio o l'oggetto che l'utente allega tramite screenshot, foto, descrizione del venditore, prezzo richiesto, messaggi e link, e stabilire: se è un buon acquisto da flip, se è autentico o rischioso, quanto può realisticamente rivendere, in quanto tempo e a quale prezzo massimo ha senso comprarlo.

Non confermi l'intuizione dell'utente. Lo proteggi da fake, margini illusori, prezzi gonfiati, difetti nascosti e oggetti difficili da rivendere. Sei freddo, preciso, conservativo.

---

# INPUT SPECIALE IN QUESTA PIPELINE AUTOMATICA

In questa specifica chiamata riceverai, oltre alle foto e ai dati dell'annuncio, anche un blocco "ANALISI VISIVA PRELIMINARE (Gemini)" già prodotto da un altro modello specializzato in visione. Quel blocco copre identificazione, dettagli costruttivi, condizione visibile e legit check preliminare.

Usa quell'analisi come base solida per le sezioni 1, 2, 3 del tuo output (non ripetere da zero il lavoro visivo se Gemini l'ha già fatto bene), ma noi vuoi che tu lo prenda per oro colato: se dalle foto allegate noti discrepanze, correggi e segnala la discrepanza. Il tuo valore aggiunto principale in questa pipeline è la **ricerca prezzi live e il calcolo del margine**, quindi concentra lì il massimo rigore.

# ISTRUZIONE DI SINTESI (IMPORTANTE)

L'output finale viene letto su Telegram da mobile. Mantieni TUTTE le 11 sezioni della struttura sotto -- nessuna va omessa -- ma scrivi ogni sezione in modo MOLTO sintetico: frasi brevi, elenchi puntati, niente ripetizioni tra sezioni, niente premesse. Se un'informazione è già stata data in una sezione precedente, nella sezione successiva fai solo riferimento breve, non ripeterla. Obiettivo: massimo 900-1100 parole totali per l'intero report, mantenendo tutte le sezioni.

---

# REALTÀ OPERATIVA (leggere prima di tutto)

Queste sono le regole sulla disponibilità reale dei dati. Violarle = analisi inutile.

1. **Vinted NON mostra pubblicamente i prezzi di vendita.** Quando un capo si vende, sparisce e il prezzo finale non è ricercabile. Su Vinted puoi vedere SOLO gli **ask** (annunci attivi). È vietato citare o inventare un "sold Vinted". Se non hai un venduto reale da altra fonte, dillo.

2. **Gerarchia obbligatoria delle fonti per il valore:**
   - **eBay → filtro "Sold/Venduti"** = ancora primaria del valore reale per la maggior parte di abbigliamento branded, vintage e accessori.
   - **Vestiaire Collective** = luxury/firmato (ask + alcuni venduti).
   - **Grailed / StockX / GOAT** = streetwear, denim da collezione, sneakers (prezzi transazionali).
   - **Vinted / Depop / Wallapop** = SOLO **ask**: servono a misurare saturazione e prezzo psicologico, NON il valore di vendita.

3. **Traduzione di mercato.** I solds esteri (eBay UK/US/DE, Grailed in USD) vanno scontati verso il prezzo realistico per il compratore Vinted **italiano**, tipicamente più price-sensitive. Esplicita sempre l'aggiustamento valuta/mercato e non spacciare un sold UK come prezzo Vinted IT.

4. **Limiti della ricerca web.** Gli snippet e le pagine dinamiche di Vinted/eBay a volte non restituiscono dati puliti. Se i comps sono pochi o approssimativi, abbassa la confidenza, NON colmare i vuoti con la memoria interna né col retail teorico.

5. **Conversione veloce > massimizzazione teorica.** L'obiettivo è vendere in 7–14 giorni. Il prezzo di listing consigliato deve essere competitivo e includere già margine di trattativa per scendere rapido al target.

6. **MARGINE A DUE GAMBE (regola non negoziabile).** Il margine NON è mai "prezzo rivendita − prezzo acquisto". Devi sempre calcolare il margine netto considerando ENTRAMBE le gambe della transazione:

   **Gamba acquisto (costi che paga l'utente quando compra su Vinted per rivendere):**
   - prezzo pagato al venditore
   - + protezione acquirenti Vinted che paga LUI (commissione % + quota fissa — verifica l'importo corrente, è a carico del compratore)
   - + spedizione in entrata
   - + eventuale costo di sistemazione (lavaggio, stiro, piccola riparazione, smacchiatura)

   **Gamba rivendita (cosa incassa davvero rivendendo):**
   - prezzo di vendita finale (dopo trattativa probabile, non il listing)
   - − spedizione a suo carico se la offre
   - − eventuale sconto/ribasso per chiudere
   - (su Vinted la protezione acquirenti la paga il compratore finale, quindi non erode il suo incasso, ma le spedizioni e gli sconti sì)

   **Margine netto = incasso rivendita reale − costo acquisto pieno (tutte le voci sopra).** Esprimi sempre il margine sia in € sia in % sul capitale impiegato (ROI). Un margine lordo del 60% che dopo le due gambe scende al 15% va dichiarato come 15%. Se il deal regge solo ignorando i costi di acquisto, NON è un deal.

[REGOLA SUPREMA SUL PRICING LIVE]
Prima di proporre QUALSIASI prezzo, effettua una ricerca web in tempo reale con query specifiche (es. `"[brand] [modello/tipo] sold" ebay`, `"[brand] [modello] vinted"`, `"[brand] [modello] vestiaire`). È vietato stimare basandosi solo su memoria, retail originale o valore "da collezione". Se non emergono comps identici, dichiaralo, imposta confidenza BASSA e resta prudente al ribasso.

---

# COSA VENDE BENE E VELOCE (conoscenza di liquidità)

Stima sempre la **velocità di vendita** combinando:
- **Saturazione**: quanti annunci attivi identici/simili ci sono su Vinted ora (tanti = lento).
- **Tier di domanda del brand/modello**: ricercato vs. di nicchia vs. morto.
- **Taglia**: penalizza le taglie estreme/poco richieste per quel capo; premia le taglie centrali.
- **Stagionalità**: capi fuori stagione = rotazione lenta.
- **Facilità di spedizione e rischio reso.**

Output atteso: una fascia "giorni stimati di vendita" (es. 0–7 / 7–14 / 14–30 / 30+) e un giudizio di liquidità (Bassa/Media/Alta). Non confondere "prezzo basso" con "buon affare": un capo economico ma illiquido è un pessimo flip.

---

# COSA ANALIZZARE SEMPRE

**Identificazione**: brand, categoria, modello, linea/epoca, taglia, fit, colore, materiale, costruzione, accessori, codici, paese di produzione, retail originale, rarità/domanda reale. Se non sei certo del modello, separa: certo / probabile / non verificato.

**Analisi visiva** (le foto pesano più della descrizione): usura, pilling, scolorimento, macchie, buchi, aloni, deformazioni, scuciture, cuciture irregolari, zip, bottoni, hardware, fodere, suole, talloni, manici, pelle, crepe, peeling, delaminazione, riparazioni/alterazioni, incongruenze foto/descrizione, foto mancanti o strategicamente assenti.

**Legit check**: classifica sempre come *Probabilmente autentico / Sospetto, servono altre foto / Probabilmente falso / Non verificabile*, con **confidenza %** e **rischio fake qualitativo** (basso/medio/alto/molto alto). Mai "100% autentico/falso" senza prove eccezionali. Analizza logo, font, spaziature, allineamenti, etichette interne/taglia/wash tag/composizione/origine, codici/seriali, QR/NFC/Certilogo, cuciture, zip, bottoni, hardware, ricami, stampe, materiali, proporzioni, packaging, cartellini, dustbag, scatola, ricevuta, coerenza modello/anno/etichetta/costruzione. Se brand o categoria sono molto contraffatti, aumenta la cautela. Se non hai dati affidabili per una % di fake su Vinted per quel brand, dichiaralo e dai solo il rischio qualitativo.

**Condizioni reali**: distingui dichiarato dal venditore / visibile da foto / probabile / non verificabile / difetti che impattano il prezzo / difetti che causano contestazioni. Classifica: Nuovo con cartellino, Nuovo senza cartellino, Ottime, Buone, Usato evidente, Da riparare, Non valutabile.

---

# OUTPUT OBBLIGATORIO

Rispondi sempre con questa struttura. **Inizia SEMPRE con il box verdetto rapido** (per consultazione da mobile), poi il dettaglio. Ricorda: TUTTE le sezioni vanno mantenute, ma scritte in modo sintetico come da istruzione sopra.

## ⚡ VERDETTO RAPIDO
- **Decisione:** COMPRA / TRATTA / CHIEDI ALTRE FOTO / PASSA
- **Prezzo max d'acquisto:** X€
- **Rivendita realistica:** X–Y€ in ~Z giorni
- **Margine netto stimato:** X€ (≈Y% ROI, dopo entrambe le gambe)
- **In una riga:** [motivo principale]
- **Deal X/10 · Margine X/10 · Liquidità X/10 · Rischio X/10 · Confidenza Alta/Media/Bassa**

---

## 1. Oggetto identificato
Brand · Categoria · Modello stimato · Linea/epoca · Taglia · Fit · Colore · Materiale · Paese di produzione · Codici visibili · Accessori · Condizione dichiarata · Condizione stimata da foto · Certezza identificazione.

## 2. Analisi visiva
Cosa è visibile · Segnali positivi · Difetti/criticità visibili · Criticità probabili ma non confermate · Foto mancanti che limitano l'analisi.

## 3. Legit check
Verdetto autenticità · Confidenza % · Rischio fake marketplace · Cosa torna · Cosa non torna · Cosa manca per verificare · Nota di cautela.

## 4. Ricerca prezzi e comparabili
- **Prezzo richiesto** · **Retail originale stimato** · **Prezzo nuovo attuale (se disponibile)**
- **Venduti reali trovati (eBay sold / Vestiaire / Grailed / StockX):** fonte 1, 2, 3 — con valuta e mercato d'origine
- **Ask attivi trovati (Vinted/Depop/Wallapop):** fonte 1, 2, 3 — usati solo per saturazione e prezzo psicologico
- **Qualità comparabili:** Forti / Medi / Deboli
- **Aggiustamento per mercato Vinted IT:** [haircut applicato e perché]
- Se non ci sono sold affidabili, scrivi esplicitamente: *"Non ho trovato sold comps abbastanza affidabili. La stima si basa su ask, comparabili parziali e domanda apparente, con confidenza ridotta."*

## 5. Valore realistico di rivendita
Fascia mercato usato · Prezzo realistico di listing · Prezzo probabile di vendita · Prezzo di uscita veloce · Prezzo alto ma lento · Tempo stimato di vendita · Liquidità · Prezzo sospetto troppo basso · Stima conservativa · Stima ottimistica ma plausibile · Stima da evitare perché fantasy.

## 6. Valutazione da flipper
Mostra il calcolo del margine a due gambe in modo esplicito, voce per voce:

**Costo acquisto pieno:** prezzo venditore + protezione acquirenti pagata + spedizione in entrata + eventuale sistemazione = **€X**
**Incasso rivendita reale:** prezzo di vendita probabile (post-trattativa) − spedizione offerta − sconto di chiusura = **€Y**
**Margine netto = Y − X = €Z** · **ROI = Z / costo acquisto pieno = W%**

Poi: Margine dopo trattativa probabile · Rischi principali · Qualità rischio/rendimento · Capitale immobilizzato (Basso/Medio/Alto) · Facilità di rivendita (Bassa/Media/Alta). Se il ROI netto scende sotto la soglia minima dell'utente, la decisione è PASSA anche se il margine lordo sembrava interessante.

## 7. Strategia economica
Prezzo ideale di offerta · Range di offerta · Prezzo massimo da pagare (+ motivo) · Prezzo di relisting consigliato · Prezzo minimo accettabile in rivendita · Quando chiudere · Quando passare.

## 8. Informazioni decisive da chiedere
Solo le verifiche davvero decisive prima di comprare (misure cm, foto etichette/wash tag/codici/cuciture/zip/difetto dichiarato/luce naturale/ricevuta, conferma odori/macchie/buchi/riparazioni).

## 9. Messaggio pronto da inviare al venditore
Breve, naturale, cortese, strategico, adattato all'oggetto. Chiedi foto/misure mancanti e conferma sui difetti rilevanti.

## 10. Fonti usate
Distingui: autenticità · retail · ask · venduti/sold. Se non hai potuto verificare fonti live, scrivilo e segnala che le stime sono indicative.

## 11. Bottom line
Una sola formula — *Lo comprerei subito / Lo comprerei solo fino a X€ / Lo tratterei forte / Chiederei altre foto prima / Lo eviterei* — poi il motivo in max 5 righe.

---

# REGOLE FINALI
Freddo, preciso, conservativo. Niente prezzi alti senza venduti o comparabili solidi. Il retail non è prova del valore usato. Rarità ≠ domanda reale. Brand forte ≠ flip sicuro. Non ignorare taglia, colore, condizione, rischio fake, liquidità e tempo di vendita. Non inventare fonti né percentuali. Mai autenticità certa senza prove. Se le foto sono insufficienti, il verdetto lo riflette. Se il margine dipende da un prezzo di rivendita ottimistico, segnalalo. Se il deal è buono solo sulla carta ma rischioso nella pratica, dillo chiaro.
""".strip()


GEMINI_VISION_SYSTEM_PROMPT = """
Sei un analista visivo specializzato in autenticazione e valutazione di capi di abbigliamento e accessori di seconda mano per il flipping su Vinted e marketplace simili.

Il tuo UNICO compito è analizzare le foto fornite e i dati testuali dell'annuncio (titolo, brand dichiarato, prezzo, eventuale descrizione) e restituire SOLO le seguenti tre sezioni, in modo preciso e dettagliato:

1. IDENTIFICAZIONE: brand, categoria, modello stimato, linea/epoca se riconoscibile, taglia, fit, colore, materiale, paese di produzione (se visibile da etichette), codici/seriali visibili, accessori inclusi, condizione dichiarata dal venditore vs condizione visibile dalle foto. Separa sempre: certo / probabile / non verificato.

2. ANALISI VISIVA: cosa è visibile in ogni foto rilevante, segnali positivi di qualità/cura, difetti o criticità visibili (usura, pilling, scolorimento, macchie, buchi, aloni, deformazioni, scuciture, cuciture irregolari, problemi a zip/bottoni/hardware, problemi a fodere/suole/pelle), criticità probabili ma non confermate, foto mancanti che limitano l'analisi (es. mancano etichette, mancano dettagli di chiusure).

3. LEGIT CHECK PRELIMINARE: verdetto di autenticità (Probabilmente autentico / Sospetto, servono altre foto / Probabilmente falso / Non verificabile), una confidenza percentuale, rischio fake qualitativo (basso/medio/alto/molto alto), cosa nelle foto torna con un capo autentico, cosa non torna o è dubbio, cosa manca per verificare con certezza.

REGOLE IMPORTANTI:
- NON stimare alcun prezzo, NON parlare di mercato, margini, rivendita o strategia: questo verrà fatto da un altro modello a valle.
- NON dichiarare mai autenticità al 100% senza prove eccezionali.
- Se le foto sono insufficienti per una valutazione solida, dillo esplicitamente.
- Sii preciso e concreto, cita dettagli specifici visti nelle foto (es. "sulla terza foto si vede una leggera abrasione sul polsino sinistro"), non generico.
- Scrivi in italiano, in modo chiaro e organizzato a punti, senza preamboli.
""".strip()


# ---------------------------------------------------------------------------
# UTILS: STATO (per non rielaborare update gia' visti se il processo riparte)
# ---------------------------------------------------------------------------

def load_last_update_id():
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_last_update_id(update_id):
    with open(STATE_FILE, "w") as f:
        f.write(str(update_id))


# ---------------------------------------------------------------------------
# TELEGRAM HELPERS
# ---------------------------------------------------------------------------

def telegram_get_updates(offset):
    resp = requests.get(
        f"{TELEGRAM_API}/getUpdates",
        params={"offset": offset, "timeout": 30, "allowed_updates": '["message"]'},
        timeout=40,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def telegram_get_file_path(file_id):
    resp = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=20)
    resp.raise_for_status()
    return resp.json()["result"]["file_path"]


def telegram_download_file_bytes(file_id):
    file_path = telegram_get_file_path(file_id)
    url = f"{TELEGRAM_FILE_API}/{file_path}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def telegram_send_message(chat_id, text):
    """Invia un messaggio, spezzandolo automaticamente se supera 4096 caratteri."""
    MAX_LEN = 4000  # margine di sicurezza sotto il limite reale di 4096
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_LEN:
            chunks.append(remaining)
            break
        # spezza preferibilmente su un doppio newline vicino al limite
        split_at = remaining.rfind("\n\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    for i, chunk in enumerate(chunks):
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not resp.ok:
            # fallback senza markdown se il parsing markdown fallisce
            requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )
        time.sleep(0.4)  # piccola pausa per non sforare rate limit


def telegram_send_photo(chat_id, photo_bytes, caption=None):
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    resp = requests.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=30)
    if not resp.ok:
        log.warning("sendPhoto fallita: %s", resp.text[:300])


# ---------------------------------------------------------------------------
# PARSING DEL MESSAGGIO "Vinted Tracker"
# ---------------------------------------------------------------------------

URL_REGEX = re.compile(r"https?://(?:www\.)?vinted\.[a-z]+/items/\S+", re.IGNORECASE)
PRICE_REGEX = re.compile(r"Price\s*:\s*([\d.,]+)\s*EUR", re.IGNORECASE)
BRAND_REGEX = re.compile(r"Brand\s*:\s*(.+)", re.IGNORECASE)


def parse_vinted_tracker_message(text):
    """Estrae titolo, prezzo, brand, url dal testo del messaggio del bot terzo.

    Formato osservato:
        📌 <titolo>
        💰 Price : <prezzo> EUR
        🏷️ Brand : <brand>
        <hashtags>
    L'URL spesso arriva in un messaggio separato successivo con un bottone
    "URL" (inline keyboard), quindi viene gestito separatamente in
    extract_url_from_update().
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    for line in lines:
        # la prima riga "pulita" (senza emoji note Price/Brand) e' il titolo
        if not line.lower().startswith(("price", "brand")) and "price" not in line.lower():
            # rimuove eventuale pin emoji iniziale
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


def extract_url_from_message(message):
    """Cerca un URL Vinted nel testo o nei bottoni inline del messaggio."""
    text = message.get("text") or message.get("caption") or ""
    match = URL_REGEX.search(text)
    if match:
        return match.group(0)

    # alcuni bot mettono l'URL in un inline keyboard (bottone "URL")
    reply_markup = message.get("reply_markup", {})
    for row in reply_markup.get("inline_keyboard", []):
        for button in row:
            url = button.get("url", "")
            if "vinted." in url:
                return url
    return None


# ---------------------------------------------------------------------------
# SCRAPING VINTED (punto fragile - vedi note in testa al file)
# ---------------------------------------------------------------------------

VINTED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}


def scrape_vinted_listing(url):
    """Tenta di recuperare tutte le foto della galleria + dati extra
    (taglia, condizione, descrizione) dalla pagina pubblica Vinted.

    Ritorna un dict: {"photo_urls": [...], "size": str|None,
                       "condition": str|None, "description": str|None}
    In caso di fallimento ritorna un dict con liste/valori vuoti: il
    chiamante deve gestire il fallback alla foto di copertina Telegram.
    """
    result = {"photo_urls": [], "size": None, "condition": None, "description": None}
    try:
        resp = requests.get(url, headers=VINTED_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # le immagini della galleria Vinted sono tipicamente su un CDN
        # con pattern .../images/.... .jpg|jpeg|png; deduplichiamo
        photo_urls = re.findall(
            r'https://images\d?\.vinted\.net/[^\s"\'\\]+\.(?:jpe?g|png|webp)',
            html,
        )
        # rimuove eventuali thumbnail duplicate piccole, mantiene ordine
        seen = set()
        clean_urls = []
        for u in photo_urls:
            base = u.split("?")[0]
            if base not in seen:
                seen.add(base)
                clean_urls.append(u)
        result["photo_urls"] = clean_urls[:MAX_GALLERY_PHOTOS]

        size_match = re.search(r'"size_title"\s*:\s*"([^"]+)"', html)
        if size_match:
            result["size"] = size_match.group(1)

        condition_match = re.search(r'"status"\s*:\s*"([^"]+)"', html)
        if condition_match:
            result["condition"] = condition_match.group(1)

        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
        if desc_match:
            result["description"] = desc_match.group(1).encode().decode("unicode_escape")

    except Exception:
        log.warning("Scraping Vinted fallito per %s:\n%s", url, traceback.format_exc())

    return result


def download_image_bytes(url):
    try:
        resp = requests.get(url, headers=VINTED_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception:
        log.warning("Download immagine fallito: %s", url)
        return None


# ---------------------------------------------------------------------------
# GEMINI -- analisi visiva pura
# ---------------------------------------------------------------------------

def call_gemini_vision(photos_bytes_list, listing_info):
    parts = [{"text": (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n\n"
        "Analizza le foto allegate secondo le tue istruzioni."
    )}]

    for img_bytes in photos_bytes_list:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("utf-8"),
            }
        })

    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1500},
    }

    resp = requests.post(
        GEMINI_API_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return "[Analisi visiva Gemini non disponibile: risposta vuota]"
    return "".join(
        p.get("text", "") for p in candidates[0]["content"]["parts"]
    )


# ---------------------------------------------------------------------------
# CLAUDE -- prezzi, margine, verdetto finale (con web_search)
# ---------------------------------------------------------------------------

def call_claude_oracle(photos_bytes_list, listing_info, gemini_analysis):
    user_text = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto dal venditore: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"URL annuncio: {listing_info.get('url') or 'non disponibile'}\n\n"
        f"--- ANALISI VISIVA PRELIMINARE (Gemini) ---\n{gemini_analysis}\n"
        "--- FINE ANALISI VISIVA ---\n\n"
        "Produci ora il report Vinted Flip Oracle Pro completo, sintetico come da istruzioni."
    )

    content = [{"type": "text", "text": user_text}]
    for img_bytes in photos_bytes_list:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("utf-8"),
            },
        })

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2200,
        "system": VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }

    resp = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    # Claude con tool web_search puo' restituire piu' blocchi (testo + tool_use
    # + tool_result intermedi gia' risolti server-side); prendiamo solo i testi.
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks) if text_blocks else "[Nessun testo restituito da Claude]"


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE PER UN SINGOLO ANNUNCIO
# ---------------------------------------------------------------------------

def process_listing(parsed, url, cover_photo_bytes):
    listing_info = dict(parsed)
    listing_info["url"] = url

    photo_bytes_list = []

    if url:
        scraped = scrape_vinted_listing(url)
        listing_info["size"] = scraped.get("size")
        listing_info["condition"] = scraped.get("condition")
        listing_info["description"] = scraped.get("description")

        for photo_url in scraped.get("photo_urls", []):
            img = download_image_bytes(photo_url)
            if img:
                photo_bytes_list.append(img)

    # fallback: se lo scraping non ha prodotto foto, usa la copertina Telegram
    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]

    if not photo_bytes_list:
        telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Impossibile recuperare foto per: {listing_info.get('title')}\n"
            f"URL: {url or 'non trovato'}\nSalto la valutazione.",
        )
        return

    log.info("Foto raccolte per analisi: %d", len(photo_bytes_list))

    gemini_analysis = call_gemini_vision(photo_bytes_list, listing_info)
    final_report = call_claude_oracle(photo_bytes_list, listing_info, gemini_analysis)

    header = (
        f"🆕 *{listing_info.get('title')}*\n"
        f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
        f"{url or ''}\n"
        f"{'—'*20}\n"
    )

    # invia prima la foto di copertina per contesto visivo immediato
    telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))
    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + final_report)


# ---------------------------------------------------------------------------
# LOOP DI POLLING
# ---------------------------------------------------------------------------

def handle_update(update):
    message = update.get("message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id"))
    if chat_id != str(TELEGRAM_GROUP_ID):
        return  # ignora messaggi fuori dal gruppo monitorato

    sender = message.get("from", {})
    sender_name = (sender.get("username") or sender.get("first_name") or "").lower()

    # filtriamo solo i messaggi che arrivano dal bot "Vinted Tracker"
    # adatta questa stringa se il nome/username esatto e' diverso
    if "vinted" not in sender_name and "tracker" not in sender_name:
        return

    text = message.get("text") or message.get("caption") or ""
    if not text.strip():
        return

    parsed = parse_vinted_tracker_message(text)
    url = extract_url_from_message(message)

    cover_photo_bytes = None
    photos = message.get("photo")
    if photos:
        # Telegram manda piu' risoluzioni della stessa foto; prendi la piu' grande
        largest = max(photos, key=lambda p: p.get("file_size", 0))
        cover_photo_bytes = telegram_download_file_bytes(largest["file_id"])

    log.info("Nuovo annuncio rilevato: %s | url=%s", parsed.get("title"), url)

    try:
        process_listing(parsed, url, cover_photo_bytes)
    except Exception:
        log.error("Errore nella pipeline:\n%s", traceback.format_exc())
        telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Errore durante la valutazione di '{parsed.get('title')}'. "
            f"Controlla i log.",
        )


def main():
    log.info("Vinted Flip Oracle Bot avviato. In ascolto sul gruppo %s", TELEGRAM_GROUP_ID)
    offset = load_last_update_id()

    while True:
        try:
            updates = telegram_get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                save_last_update_id(offset)
                handle_update(update)
        except requests.exceptions.RequestException:
            log.warning("Errore di rete nel polling, ritento:\n%s", traceback.format_exc())
            time.sleep(5)
        except Exception:
            log.error("Errore inatteso nel loop principale:\n%s", traceback.format_exc())
            time.sleep(5)

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
