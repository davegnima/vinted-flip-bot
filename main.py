"""
Vinted Flip Oracle Bot (versione Telethon / userbot)
======================================================
Perche' questa versione: la Telegram Bot API non consegna ai bot i
messaggi scritti da ALTRI bot (e' un limite di piattaforma, non
configurabile). "Vinted Tracker" e' un bot, quindi il tuo bot "Vinted
Notification" non poteva vederne i messaggi nemmeno essendo nello stesso
gruppo. La soluzione e' usare un USERBOT: uno script che si autentica
con il TUO account Telegram personale (numero di telefono), che vede
tutto cio' che vede un utente normale -- bot compresi.

Pipeline:
  1. Telethon (userbot, loggato col tuo numero) ascolta i nuovi messaggi
     nel gruppo/forum "Dadegnima, Vinted Notification e Vinted Tracker"
  2. Quando arriva un messaggio da "Vinted Tracker", estrae
     titolo / prezzo / brand / URL annuncio
  3. Scraping della pagina Vinted per recuperare TUTTE le foto della
     galleria + taglia/condizione/descrizione (se disponibili)
  4. Gemini 3 Flash: analisi visiva pura (identificazione, autenticita',
     condizione) -- NESSUN prezzo, NESSUNA ricerca web
  5. Claude Sonnet 4.6: usa l'analisi di Gemini + foto + dati annuncio,
     fa ricerca web (tool web_search) e produce il report Vinted Flip
     Oracle Pro completo (11 sezioni, sintetico)
  6. L'invio del report avviene con la Bot API normale (il bot PUO'
     sempre scrivere a una chat privata dove tu gli hai scritto prima
     -- l'invio non e' soggetto al limite "bot non vede altri bot")

Variabili d'ambiente richieste (mai scritte nel codice):
  TELEGRAM_API_ID        - da my.telegram.org (vedi DEPLOY_RAILWAY.md)
  TELEGRAM_API_HASH      - da my.telegram.org
  TELEGRAM_PHONE         - il tuo numero con prefisso internazionale (+39...)
  TELEGRAM_SESSION_STRING - generata una tantum con generate_session.py,
                            permette il login senza richiedere il codice
                            SMS ad ogni riavvio del bot
  TELEGRAM_GROUP_ID      - id del gruppo/forum da ascoltare (-100...)
  TELEGRAM_BOT_TOKEN     - token del bot "Vinted Notification" (per INVIARE
                           i report finali in chat privata)
  TELEGRAM_OWNER_CHAT_ID - il tuo chat id personale (dove ricevere i report)
  ANTHROPIC_API_KEY      - chiave API Claude
  GEMINI_API_KEY         - chiave API Gemini

Note operative:
  - Lo scraping Vinted e' il punto piu' fragile: se Vinted cambia markup
    o blocca le richieste, la funzione scrape_vinted_listing() va
    aggiornata. Il bot comunque NON si blocca: se lo scraping fallisce,
    usa solo la foto di copertina del messaggio come fallback.
  - Con i Topics attivi sul gruppo, ogni messaggio porta anche un
    reply_to_top_id (l'ID del topic): non serve filtrarlo, ascoltiamo
    tutto il gruppo indipendentemente dal topic specifico.
"""

import os
import re
import asyncio
import base64
import logging
import traceback

import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession

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

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3-flash:generateContent"
)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_GALLERY_PHOTOS = 10  # tetto massimo foto da inviare ai modelli (costo)

# Adatta questa stringa se il nome/username esatto del bot terzo e' diverso
VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("vinted_flip_bot")


# ---------------------------------------------------------------------------
# VINTED FLIP ORACLE PRO -- system prompt (identico alla versione precedente)
# ---------------------------------------------------------------------------

VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT = r"""
Tu sei **Vinted Flip Oracle Pro**, un esperto d'élite di flipping, resale, arbitraggio second hand, autenticazione visiva, pricing realistico e negoziazione su marketplace peer-to-peer come Vinted, Vestiaire Collective, Grailed, eBay, Depop, Wallapop, StockX/GOAT e community specializzate.

Il tuo compito è analizzare l'annuncio o l'oggetto che l'utente allega tramite screenshot, foto, descrizione del venditore, prezzo richiesto, messaggi e link, e stabilire: se è un buon acquisto da flip, se è autentico o rischioso, quanto può realisticamente rivendere, in quanto tempo e a quale prezzo massimo ha senso comprarlo.

Non confermi l'intuizione dell'utente. Lo proteggi da fake, margini illusori, prezzi gonfiati, difetti nascosti e oggetti difficili da rivendere. Sei freddo, preciso, conservativo.

---

# INPUT SPECIALE IN QUESTA PIPELINE AUTOMATICA

In questa specifica chiamata riceverai, oltre alle foto e ai dati dell'annuncio, anche un blocco "ANALISI VISIVA PRELIMINARE (Gemini)" già prodotto da un altro modello specializzato in visione. Quel blocco copre identificazione, dettagli costruttivi, condizione visibile e legit check preliminare.

Usa quell'analisi come base per il tuo giudizio su identificazione, condizione e autenticità, ma non prenderla per oro colato: se dalle foto allegate noti discrepanze, correggi e segnala la discrepanza nel "Legit check". Il tuo valore aggiunto principale in questa pipeline è la **ricerca prezzi live e il calcolo del margine**, quindi concentra lì il massimo rigore, anche se nell'output finale (vedi istruzione di sintesi sotto) quel lavoro confluisce in una sola riga di verdetto.

# SCALA DI VOTO MARGINE (ANCORATA ALL'EURO, NON AL ROI %)

Il ROI percentuale è ingannevole su capi a basso costo: un "40% ROI" su un capo da 15€ vuol dire 6€ di margine, che è un NO-GO operativo anche se la percentuale sembra ottima. Il voto "Forza del margine" si basa SEMPRE sul margine netto assoluto in euro (dopo entrambe le gambe), secondo questa scala:

- **0-2/10**: margine netto sotto 10€, o negativo. NO-GO quasi sempre, indipendentemente dal ROI%.
- **3-4/10**: margine netto 10-19€. Deal marginale, da fare solo se a rischio/sforzo bassissimo.
- **5-6/10**: margine netto 20-39€. Soglia minima accettabile per un flip "vero".
- **7-8/10**: margine netto 40-99€. Buon flip.
- **9-10/10**: margine netto 100€ o più. Flip da prioritizzare.

La soglia minima accettabile per l'utente è un margine netto di 20€. Sotto quella soglia la decisione di default è NON COMPRARE, anche se il ROI percentuale sembra alto, a meno che il rischio sia eccezionalmente basso e l'esecuzione richieda zero sforzo.

# ISTRUZIONE DI SINTESI (IMPORTANTE, SOSTITUISCE LE 11 SEZIONI CLASSICHE)

L'output finale viene letto su Telegram da mobile, spesso più volte al giorno. NON usare la struttura completa a 11 sezioni. Usa SOLO questa struttura compatta, in italiano, con frasi brevi ed elenchi puntati, MASSIMO 400 PAROLE TOTALI per l'intero messaggio (è un tetto rigido, non un'indicazione):

## Verdetto operativo
- **Decisione:** COMPRA / TRATTA FORTE / TRATTA / CHIEDI ALTRE FOTO / NON COMPRARE
- **Qualità del deal:** X/10
- **Forza del margine:** X/10 *(usa la scala ancorata all'euro sopra — sii esplicito sul margine netto in € prima di dare il voto)*
- **Liquidità:** Bassa / Media / Alta
- **Rischio complessivo:** BASSO / MEDIO / ALTO *(specifica IL TIPO di rischio: autenticità, venditore, prezzo già di realizzo, illiquidità — non limitarti alla parola, dai il motivo in mezza riga)*
- **Confidenza analisi:** Alta / Media / Bassa
- **In una riga:** [motivo operativo principale, con il margine netto in € esplicito]

## Legit check
2-4 righe massimo: verdetto autenticità, confidenza %, il segnale più importante (positivo o negativo) trovato nelle foto.

## Da chiedere prima di comprare
Solo le 2-4 domande davvero decisive (mai di più). Se il margine è già sotto soglia (NO-GO), scrivi "Non rilevante: margine insufficiente" invece di elencare domande inutili.

## Messaggio da inviare
Un solo messaggio pronto, breve. Se la decisione è NON COMPRARE, scrivi "Non necessario in questo caso" invece di inventarne uno.

---

Questa struttura SOSTITUISCE INTEGRALMENTE le 11 sezioni descritte più sotto in questo prompt (Identificazione, Analisi visiva, Ricerca prezzi, Valore di rivendita, Strategia economica, Fonti, Bottom line). Quelle sezioni restano solo come riferimento per IL TUO RAGIONAMENTO INTERNO -- fai comunque tutta l'analisi e tutta la ricerca web richiesta da quelle sezioni, ma nell'output finale al cliente NON scriverle: condensa tutto nelle voci compatte sopra. Il rigore di analisi (ricerca prezzi live, margine a due gambe, cautela su autenticità) resta identico; cambia solo cosa viene scritto in output.

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
# TELEGRAM BOT API HELPERS (solo per INVIARE i report finali)
# ---------------------------------------------------------------------------

def telegram_send_message(chat_id, text):
    """Invia un messaggio, spezzandolo automaticamente se supera 4096 caratteri."""
    MAX_LEN = 4000
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_LEN:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, MAX_LEN)
        if split_at == -1:
            split_at = MAX_LEN
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    for chunk in chunks:
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
    """Estrae titolo, prezzo, brand dal testo del messaggio del bot terzo.

    Formato osservato:
        📌 <titolo>
        💰 Price : <prezzo> EUR
        🏷️ Brand : <brand>
        <hashtags>
    """
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

IMAGE_DOWNLOAD_HEADERS = {
    **VINTED_HEADERS,
    "Referer": "https://www.vinted.it/",
    "Accept": "image/webp,image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5",
}


def scrape_vinted_listing(url):
    """Tenta di recuperare tutte le foto della galleria + dati extra
    (taglia, condizione, descrizione) dalla pagina pubblica Vinted.
    """
    result = {"photo_urls": [], "size": None, "condition": None, "description": None}
    try:
        resp = requests.get(url, headers=VINTED_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # le immagini della galleria Vinted hanno pattern
        # .../t/<id_foto>/<risoluzione>/<file>.webp -- lo stesso scatto
        # appare a piu' risoluzioni (70x100, 150x210, 310x430, f800);
        # raggruppiamo per id_foto e teniamo solo la versione f800.
        matches = re.findall(
            r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/((?:f800|\d+x\d+))/[^\s"\'\\]+\.(?:jpe?g|png|webp)',
            html,
        )
        full_matches = re.findall(
            r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/(?:f800|\d+x\d+)/[^\s"\'\\]+\.(?:jpe?g|png|webp)',
            html,
        )
        best_url_by_photo_id = {}
        for (photo_id, resolution), full_url in zip(matches, full_matches):
            if photo_id not in best_url_by_photo_id or resolution == "f800":
                best_url_by_photo_id[photo_id] = full_url
        clean_urls = list(best_url_by_photo_id.values())
        result["photo_urls"] = clean_urls[:MAX_GALLERY_PHOTOS]

        log.info(
            "SCRAPING %s -> trovate %d foto totali, usate %d (limite %d):\n%s",
            url,
            len(clean_urls),
            len(result["photo_urls"]),
            MAX_GALLERY_PHOTOS,
            "\n".join(f"  - {u}" for u in result["photo_urls"]) or "  (nessuna foto trovata)",
        )

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
        resp = requests.get(url, headers=IMAGE_DOWNLOAD_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception:
        log.warning("Download immagine fallito: %s", url)
        return None


# ---------------------------------------------------------------------------
# GEMINI -- analisi visiva pura
# ---------------------------------------------------------------------------

def call_gemini_vision(photos_bytes_list, listing_info):
    user_text_for_log = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
    )
    log.info(
        "PROMPT TESTUALE -> GEMINI (%d foto allegate):\n%s",
        len(photos_bytes_list),
        user_text_for_log,
    )

    parts = [{"text": (
        user_text_for_log + "\nAnalizza le foto allegate secondo le tue istruzioni."
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

    log.info(
        "PROMPT TESTUALE -> CLAUDE (%d foto allegate):\n%s",
        len(photos_bytes_list),
        user_text,
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

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks) if text_blocks else "[Nessun testo restituito da Claude]"


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE PER UN SINGOLO ANNUNCIO
# ---------------------------------------------------------------------------

def process_listing(parsed, url, cover_photo_bytes):
    """Funzione sincrona (bloccante): viene lanciata in un thread separato
    dall'event handler asincrono di Telethon, per non bloccare il loop
    degli eventi mentre aspettiamo scraping/Gemini/Claude (che possono
    richiedere fino a un minuto)."""
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

    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]

    if not photo_bytes_list:
        telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Impossibile recuperare foto per: {listing_info.get('title')}\n"
            f"URL: {url or 'non trovato'}\nSalto la valutazione.",
        )
        return

    log.info(
        "Foto raccolte per analisi: %d (fonte: %s)",
        len(photo_bytes_list),
        "scraping Vinted" if url and len(photo_bytes_list) > 1 else "fallback copertina Telegram",
    )

    gemini_analysis = call_gemini_vision(photo_bytes_list, listing_info)
    log.info("RISPOSTA GEMINI (%d foto inviate):\n%s", len(photo_bytes_list), gemini_analysis)

    final_report = call_claude_oracle(photo_bytes_list, listing_info, gemini_analysis)
    log.info("RISPOSTA CLAUDE (%d foto inviate):\n%s", len(photo_bytes_list), final_report)

    header = (
        f"🆕 *{listing_info.get('title')}*\n"
        f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
        f"{url or ''}\n"
        f"{'—'*20}\n"
    )

    telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))
    telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + final_report)


# ---------------------------------------------------------------------------
# USERBOT TELETHON -- ricezione messaggi dal gruppo (vede anche i bot)
# ---------------------------------------------------------------------------

client = TelegramClient(
    StringSession(TELEGRAM_SESSION_STRING),
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)


@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
async def on_new_message(event):
    try:
        sender = await event.get_sender()
        sender_name = ((getattr(sender, "username", None) or "") + " " +
                        (getattr(sender, "first_name", None) or "")).lower()

        # filtriamo solo i messaggi che arrivano dal bot "Vinted Tracker"
        if not any(hint in sender_name for hint in VINTED_TRACKER_NAME_HINTS):
            return

        text = event.message.message or ""
        if not text.strip():
            return

        parsed = parse_vinted_tracker_message(text)
        url = extract_url_from_text(text)

        # se l'URL non e' nel testo, alcuni bot lo mettono in un bottone
        # inline -- Telethon lo esp one nei bottoni del messaggio (event.message.buttons)
        if not url and event.message.buttons:
            for row in event.message.buttons:
                for button in row:
                    btn_url = getattr(button, "url", None) or ""
                    if "vinted." in btn_url:
                        url = btn_url
                        break

        cover_photo_bytes = None
        if event.message.photo:
            cover_photo_bytes = await event.message.download_media(bytes)

        log.info("Nuovo annuncio rilevato: %s | url=%s", parsed.get("title"), url)

        # process_listing e' bloccante (richieste HTTP sincrone): la
        # eseguiamo in un thread separato per non bloccare il loop asyncio
        # di Telethon mentre aspettiamo le risposte di Gemini/Claude.
        await asyncio.to_thread(process_listing, parsed, url, cover_photo_bytes)

    except Exception:
        log.error("Errore nella pipeline:\n%s", traceback.format_exc())
        try:
            telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                "⚠️ Errore durante la valutazione di un nuovo annuncio. Controlla i log.",
            )
        except Exception:
            pass


async def main():
    log.info("Vinted Flip Oracle Bot (Telethon) avviato. In ascolto sul gruppo %s", TELEGRAM_GROUP_ID)
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
