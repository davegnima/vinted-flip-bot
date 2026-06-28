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
  4. Gemini 3.5 Flash: analisi visiva pura (identificazione, autenticita',
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
  - Gemini: dal 28/06/2026 la fatturazione e' attiva sul progetto
    "Progetto Vinted", quindi i limiti free tier (5 RPM / 20 RPD) non
    si applicano piu'. La funzione call_gemini_vision() mantiene
    comunque un retry con backoff esponenziale su errori transitori
    (503/429/5xx, timeout di rete), utile contro sovraccarichi
    momentanei lato Google indipendenti dal piano di fatturazione.
"""

import os
import re
import time
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
    "gemini-3.5-flash:generateContent"
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

In questa specifica chiamata NON ricevi le foto originali dell'annuncio. Ricevi invece un JSON strutturato e dettagliato, prodotto da un modello di visione specializzato che ha esaminato tutte le foto dell'annuncio una per una. Il JSON include: la trascrizione letterale di ogni etichetta/tag leggibile (campo "testo_letterale_etichette" -- usa questo come fonte primaria per composizione, taglia, paese di produzione, non basarti solo sui riassunti), identificazione del capo, un elenco di TUTTI i loghi/marchi visibili (con un flag esplicito se coerenti o non coerenti con il brand dichiarato dal venditore), un'analisi visiva foto per foto, un riepilogo dei difetti, e un legit check preliminare.

Tratta questo JSON come la tua unica fonte visiva attendibile. Se il campo "loghi_e_marchi_visibili" contiene un elemento con "coerente_con_brand_dichiarato": false, è un segnale di rischio serio che DEVE riflettersi nel tuo Legit check e nella tua decisione finale -- non minimizzarlo.

REGOLA VINCOLANTE -- ASSENZA TOTALE DI PROVE DI BRAND: se il JSON segnala "ASSENZA TOTALE DI ETICHETTA/LOGO/TAG IN TUTTE LE FOTO FORNITE" (o equivalente: nessun logo, nessuna etichetta, nessun tag visibile in nessuna foto, e la descrizione del venditore non fornisce dettagli verificabili come composizione/codici), la tua decisione operativa NON PUÒ essere "COMPRA" né "TRATTA", a prescindere da quanto il pattern/stile sembri visivamente coerente col brand e a prescindere dal margine teorico. Un pattern o uno stile visivamente simile NON è una prova di autenticità — è il tipo di segnale che un capo contraffatto o mal etichettato condivide facilmente. In questo scenario la decisione corretta è "CHIEDI ALTRE FOTO" (se c'è ancora margine sufficiente da giustificare la richiesta) oppure "NON COMPRARE" (se il margine è già modesto o il venditore non fornisce contesto). Non trattare l'assenza di etichetta come un dettaglio minore da menzionare di passaggio nel Legit check: deve essere il fattore che determina la decisione.

Il tuo valore aggiunto principale in questa pipeline resta la **ricerca prezzi live e il calcolo del margine**, quindi concentra lì il massimo rigore, ma integra sempre quello che il JSON ti segnala sul piano visivo/autenticità -- e quella regola vincolante sopra ha sempre priorità sul margine.

Nota operativa sulla spedizione: rileva la lingua del titolo e della descrizione dell'annuncio (che ti arrivano nel messaggio utente) per stimare il paese del venditore e applicare la tabella di costo spedizione descritta più sotto nella sezione sul margine a due gambe.

# SCALA DI VOTO MARGINE (COMBINATA: EURO ASSOLUTO COME BASE, ROI% COME MODIFICATORE)

Il ROI percentuale da solo è ingannevole su capi a basso costo: un "40% ROI" su un capo da 15€ vuol dire 6€ di margine, che è un NO-GO operativo anche se la percentuale sembra ottima. Il voto "Forza del margine" si basa SEMPRE PRIMA sul margine netto assoluto in euro (dopo entrambe le gambe, scenario al prezzo richiesto salvo se la trattativa è certa), secondo questa scala base:

- **0-2/10**: margine netto sotto 10€, o negativo. NO-GO quasi sempre, indipendentemente dal ROI%.
- **3-4/10**: margine netto 10-19€. Deal marginale, da fare solo se a rischio/sforzo bassissimo.
- **5-6/10**: margine netto 20-39€. Soglia minima accettabile per un flip "vero".
- **7-8/10**: margine netto 40-99€. Buon flip.
- **9-10/10**: margine netto 100€ o più. Flip da prioritizzare.

MODIFICATORE ROI%: una volta determinato il voto base sull'euro, puoi alzarlo o abbassarlo di massimo 1 punto in base al ROI%: ROI sopra 80% → +1 (capitale molto efficiente); ROI 40-80% → nessuna modifica; ROI sotto 20% → -1 (capitale poco efficiente anche se il margine assoluto è dignitoso). Il modificatore non può MAI far salire un voto base di 0-2 (margine sotto 10€) sopra il 3, e non può mai far scendere un voto di 9-10 sotto l'8: il margine assoluto resta sempre il fattore dominante.

La soglia minima accettabile per l'utente è un margine netto di 20€. Sotto quella soglia la decisione di default è NON COMPRARE, anche se il ROI percentuale sembra alto, a meno che il rischio sia eccezionalmente basso e l'esecuzione richieda zero sforzo.

# ISTRUZIONE DI SINTESI (IMPORTANTE, SOSTITUISCE LE 11 SEZIONI CLASSICHE)

L'output finale viene letto su Telegram da mobile. NON usare la struttura completa a 11 sezioni. Usa SOLO questa struttura compatta, in italiano. TETTO RIGIDO: massimo 150 PAROLE TOTALI per l'intero messaggio, dal titolo "Verdetto operativo" fino all'ultima riga. Conta le parole prima di rispondere: se superi 150, tagli aggettivi e spiegazioni, non contenuto decisionale.

REGOLE DI STILE VINCOLANTI (non negoziabili):
- Ogni riga è un'etichetta seguita da un valore SECCO. Niente frasi tra parentesi che spiegano il perché, niente "il problema è che...", niente "non rilevante (vedi sotto)".
- Se un dato non è applicabile, scrivi "N/A" e basta — non spiegare perché in quella stessa riga.
- Il motivo va SOLO nel campo "In una riga" (max 15 parole) e nel Legit check (max 20 parole). Non ripetere il motivo in più punti.
- Numeri e decisioni sempre prima delle spiegazioni. Mai invertire l'ordine.

## Verdetto operativo
- **Decisione:** COMPRA / TRATTA FORTE / TRATTA / CHIEDI ALTRE FOTO / NON COMPRARE
- **Costo pieno richiesto:** €X
- **Costo pieno trattato:** €X o "N/A"
- **Vendita probabile:** €X in ~Z giorni (o "N/A" se non valutabile)
- **Margine netto:** €X (ROI Y%) — richiesto / trattato, su una riga sola separati da " · "
- **Deal:** X/10 · **Margine:** X/10 · **Liquidità:** Bassa/Media/Alta · **Rischio:** BASSO/MEDIO/ALTO (tipo in 3 parole, es. "ALTO — autenticità logo") · **Confidenza:** Alta/Media/Bassa
- **In una riga:** [max 15 parole, il motivo operativo]

## Legit check
Una riga sola, max 20 parole: verdetto + confidenza % + il segnale chiave.

## Da chiedere
Max 3 domande in elenco telegrafico, o "Non rilevante: margine insufficiente".

## Messaggio da inviare
Un messaggio pronto breve, o "Non necessario".

---

Questa struttura SOSTITUISCE INTEGRALMENTE le 11 sezioni descritte più sotto in questo prompt. Quelle sezioni restano solo come riferimento per IL TUO RAGIONAMENTO INTERNO — fai tutta l'analisi e la ricerca web richiesta, ma nell'output finale NON scriverle: condensa tutto nelle voci compatte sopra, rispettando rigidamente i limiti di parole. Il rigore di analisi resta identico; cambia solo quanto scrivi in output.

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
   - + spedizione in entrata — STIMA IN BASE ALLA LINGUA DELL'ANNUNCIO se la spedizione esatta non è indicata o sembra non plausibile (es. tariffa nazionale italiana indicata da un venditore che scrive in tedesco, segno che la cifra mostrata non riflette il costo reale per un acquirente italiano):
     - Annuncio in italiano → venditore IT → **2,50€**
     - Annuncio in francese, spagnolo, portoghese → **4,50€**
     - Annuncio in tedesco, olandese, e lingue nord/centro-Europa simili → **5-6€**
     - Altre lingue (es. inglese, polacco, ecc.) → usa la spedizione indicata sull'annuncio se plausibile, altrimenti stima per analogia geografica (Europa centrale/orientale ~4-5€, UK/extra-UE ~6-8€)
     - Se l'annuncio mostra un costo di spedizione esplicito e coerente con queste fasce, preferiscilo sempre alla stima; usa la tabella solo come fallback o come correzione se il costo indicato sembra irrealistico per la rotta implicita dalla lingua
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

Il tuo output sarà l'UNICA fonte visiva per un secondo modello che non vedrà le foto originali: deve poter ricostruire mentalmente la scena solo dal tuo testo. Sii esaustivo, specifico, e non riassumere: se vedi più elementi della stessa categoria (es. più loghi, più difetti), elencali TUTTI separatamente, non aggregarli in una frase generica.

Rispondi SOLO con un oggetto JSON valido (nessun testo prima o dopo, nessun blocco markdown ```), con questa struttura esatta:

{
  "testo_letterale_etichette": [
    {
      "tipo_etichetta": "brand / composizione-lavaggio / taglia / paese produzione / altro",
      "foto_di_riferimento": "es. foto 4",
      "trascrizione_letterale": "TUTTO il testo leggibile su questa etichetta, parola per parola, inclusi simboli descritti a parole (es. 'simbolo lavaggio a secco', 'simbolo non candeggiare'). Se alcune lettere/numeri non sono leggibili con certezza, scrivili comunque con un punto di domanda (es. '42/4?2') invece di ometterli."
    }
  ],
  "identificazione": {
    "brand_dichiarato_dal_venditore": "...",
    "brand_effettivamente_visibile_sui_loghi": "...",
    "categoria": "...",
    "modello_stimato": "...",
    "linea_o_epoca": "es. vintage anni '90, collezione recente, main line, diffusion line (es. M Missoni vs Missoni, Weekend Max Mara vs Max Mara) -- specifica se riconoscibile",
    "taglia": "...",
    "fit": "...",
    "colore": "...",
    "materiale_apparente": "...",
    "paese_produzione_se_visibile": "...",
    "codici_o_seriali_visibili": "...",
    "accessori_inclusi": "...",
    "certezza_identificazione": "certo / probabile / non verificato",
    "note_identificazione": "qualsiasi ambiguità o incertezza rilevante"
  },
  "loghi_e_marchi_visibili": [
    {
      "testo_o_simbolo": "...",
      "posizione_sul_capo": "...",
      "tecnica": "ricamato / stampato / termoadesivo / patch cucita / inciso su metallo / goffrato / non determinabile",
      "foto_di_riferimento": "es. foto 1, foto 3",
      "coerente_con_brand_dichiarato": true/false,
      "nota": "Segnala qui eventuali sbavature, font non standard, asimmetrie o imperfezioni del logo rispetto a quanto ti aspetteresti da un prodotto originale del brand"
    }
  ],
  "analisi_visiva_per_foto": [
    {
      "numero_foto": 1,
      "cosa_si_vede": "descrizione concreta e specifica di ciò che è visibile in questa foto, inclusi dettagli minori",
      "difetti_o_segni_usura": "...",
      "segnali_positivi": "..."
    }
  ],
  "difetti_riassunto": {
    "usura_generale": "...",
    "pilling_scolorimento_macchie": "...",
    "buchi_strappi_scuciture": "...",
    "zip_bottoni_hardware": "...",
    "altro": "..."
  },
  "foto_mancanti_che_limitano_analisi": "es. etichetta interna non visibile, wash tag assente, ecc.",
  "legit_check_preliminare": {
    "verdetto": "Probabilmente autentico / Sospetto, servono altre foto / Probabilmente falso / Non verificabile",
    "confidenza_percentuale": "...",
    "rischio_fake_qualitativo": "basso / medio / alto / molto alto",
    "cosa_torna_con_autenticita": "...",
    "cosa_non_torna_o_e_dubbio": "...",
    "cosa_manca_per_verificare": "..."
  },
  "condizione_reale": {
    "dichiarata_dal_venditore": "...",
    "visibile_dalle_foto": "...",
    "classificazione": "Nuovo con cartellino / Nuovo senza cartellino / Ottime / Buone / Usato evidente / Da riparare / Non valutabile",
    "difetti_che_impattano_prezzo": "...",
    "difetti_che_potrebbero_causare_contestazioni": "..."
  }
}

REGOLE IMPORTANTI:
- CAMPO "testo_letterale_etichette" -- OBBLIGATORIO E LETTERALE: per OGNI etichetta, tag, cartellino o scritta leggibile visibile in qualsiasi foto (brand, composizione, lavaggio, taglia, paese di produzione, codici, seriali), trascrivi il testo ESATTO e COMPLETO, parola per parola e percentuale per percentuale, come se Claude dovesse rispondere basandosi solo su questo testo senza mai vedere la foto. NON riassumere, NON parafrasare, NON scrivere giudizi qualitativi qui (quelli vanno in "legit_check_preliminare"): questo campo è una trascrizione, non un'opinione. Esempio SBAGLIATO: "etichetta composizione coerente con prodotto di fascia alta". Esempio CORRETTO: "98% Lana vergine, 2% Poliammide. Lavare a secco. Non candeggiare. Taglia 38-40-42". Se il testo è parzialmente illeggibile, riportalo comunque con i caratteri incerti segnalati, non saltare il campo.
- Il campo "loghi_e_marchi_visibili" è critico: se vedi anche un solo logo/marchio/scritta che non corrisponde al brand dichiarato dal venditore, DEVE apparire come elemento separato con "coerente_con_brand_dichiarato": false — non ometterlo, non minimizzarlo, non assumere che sia comunque lo stesso brand.
- CASO CRITICO -- ASSENZA TOTALE DI PROVE: se in NESSUNA delle foto fornite è visibile un logo, etichetta, tag, marchio o qualsiasi elemento che confermi il brand dichiarato (es. solo un pattern/colore/forma generico, senza alcun elemento testuale o grafico brand-specifico), questo NON è un dettaglio minore da annotare di passaggio: è un campanello d'allarme di primo livello. In questo caso, nel campo "legit_check_preliminare", il "verdetto" deve essere "Sospetto, servono altre foto" o "Non verificabile" (mai "Probabilmente autentico"), la "confidenza_percentuale" non deve superare il 40%, e "cosa_non_torna_o_e_dubbio" deve dichiarare esplicitamente e in modo evidente "ASSENZA TOTALE DI ETICHETTA/LOGO/TAG IN TUTTE LE FOTO FORNITE — nessuna prova visiva di brand oltre al pattern/aspetto generico". Un pattern o uno stile visivamente simile al brand dichiarato NON è una prova di autenticità: stili, colori e pattern geometrici sono tra gli elementi più facili da replicare senza replicare etichette o costruzione interna (es. il motivo check di Burberry o il monogram di Louis Vuitton sono entrambi ampiamente replicati su falsi; da soli, senza hardware/etichettatura coerente, non provano nulla).
- "analisi_visiva_per_foto" deve avere una voce per OGNI foto allegata, anche se il contenuto si ripete: se ricevi 6 foto, devono esserci esattamente 6 oggetti distinti (numero_foto da 1 a 6), MAI accorpati in meno voci anche se due foto mostrano dettagli simili.
- NON stimare alcun prezzo, NON parlare di mercato, margini, rivendita o strategia: questo verrà fatto da un altro modello a valle, che non vedrà le foto e si baserà SOLO su questo JSON.
- NON dichiarare mai autenticità al 100% senza prove eccezionali.
- Se le foto sono insufficienti per una valutazione solida, dillo esplicitamente nei campi pertinenti.
- Scrivi tutti i valori testuali in italiano.
- Rispondi ESCLUSIVAMENTE con il JSON, nessun altro testo.
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
    "User-Agent": VINTED_HEADERS["User-Agent"],
    "Accept-Language": VINTED_HEADERS["Accept-Language"],
    "Referer": "https://www.vinted.it/",
    "Accept": "image/webp,image/avif,image/jpeg,image/png,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
}


def scrape_vinted_listing(url):
    """Tenta di recuperare tutte le foto della galleria + dati extra
    (taglia, condizione, descrizione) dalla pagina pubblica Vinted.
    """
    result = {"photo_urls": [], "size": None, "condition": None, "description": None}
    try:
        resp = _vinted_session.get(url, headers=VINTED_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # le immagini della galleria Vinted hanno pattern
        # .../t/<id_foto>/<risoluzione>/<file>.webp?s=<token_firma>
        # -- lo stesso scatto appare a piu' risoluzioni (70x100, 150x210,
        # 310x430, f800); raggruppiamo per id_foto e teniamo solo la
        # versione f800. IMPORTANTE: il parametro ?s=<token> e' una firma
        # temporanea richiesta dal CDN -- senza di esso il download
        # dell'immagine viene rifiutato (403), quindi va sempre incluso.
        matches = re.findall(
            r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/((?:f800|\d+x\d+))/'
            r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?',
            html,
        )
        full_matches = re.findall(
            r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/(?:f800|\d+x\d+)/'
            r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?',
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


# Sessione condivisa: riusa connessione e cookie tra le richieste di
# scraping pagina e download immagini dello stesso annuncio, il che
# aiuta con CDN che si aspettano una sessione "coerente" (stessi cookie
# di tracking della pagina HTML quando poi richiedi le immagini).
_vinted_session = requests.Session()
_vinted_session.headers.update(VINTED_HEADERS)


def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=2):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer

    last_status = None
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = _vinted_session.get(url, headers=headers, timeout=15)
            last_status = resp.status_code
            if resp.ok:
                return resp.content
            log.warning(
                "Download immagine fallito (tentativo %d/%d) -- HTTP %d: %s",
                attempt, max_retries, resp.status_code, url,
            )
        except Exception as exc:
            last_error = exc
            log.warning(
                "Download immagine fallito (tentativo %d/%d) -- eccezione %s: %s",
                attempt, max_retries, type(exc).__name__, url,
            )
        time.sleep(0.6 * attempt)  # piccolo backoff prima del retry

    log.warning(
        "Download immagine fallito definitivamente dopo %d tentativi (ultimo status=%s, ultimo errore=%s): %s",
        max_retries, last_status, last_error, url,
    )
    return None


# ---------------------------------------------------------------------------
# GEMINI -- analisi visiva pura (con retry/backoff su errori transitori)
# ---------------------------------------------------------------------------

def call_gemini_vision(photos_bytes_list, listing_info, max_retries=4):
    """Chiama Gemini per l'analisi visiva. Con la fatturazione attiva sul
    progetto i limiti di rate sono molto piu' alti del free tier, ma questo
    retry resta utile contro sovraccarichi temporanei lato Google (503),
    rate limit residui (429) o problemi di rete transitori -- nessuno di
    questi e' un bug nel codice, sono condizioni esterne da assorbire."""
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
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 3000,
            "responseMimeType": "application/json",
        },
    }

    # Errori transitori (sovraccarico/rate limit lato Google) -> ritentiamo
    # con backoff esponenziale. Altri errori (4xx diversi da 429, es. API
    # key invalida o richiesta malformata) non hanno senso da ritentare e
    # vengono propagati immediatamente.
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    backoff_seconds = 2  # 2s, 4s, 8s, 16s...

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                GEMINI_API_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=60,
            )

            if resp.ok:
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    log.warning("Gemini ha risposto 200 ma senza candidates (risposta vuota).")
                    return "[Analisi visiva Gemini non disponibile: risposta vuota]"
                return "".join(
                    p.get("text", "") for p in candidates[0]["content"]["parts"]
                )

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                log.warning(
                    "Gemini HTTP %d (tentativo %d/%d) -- ritento in %ds. Body: %s",
                    resp.status_code, attempt, max_retries, backoff_seconds, resp.text[:300],
                )
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            # Errore non transitorio, o ultimo tentativo esaurito: propaga.
            resp.raise_for_status()

        except requests.exceptions.HTTPError as exc:
            last_exception = exc
            if attempt >= max_retries:
                break
        except requests.exceptions.RequestException as exc:
            # Timeout, connessione persa, ecc. -- trattali come transitori.
            last_exception = exc
            log.warning(
                "Gemini eccezione di rete (tentativo %d/%d): %s -- ritento in %ds",
                attempt, max_retries, exc, backoff_seconds,
            )
            if attempt < max_retries:
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            break

    # Tutti i tentativi esauriti: non far crashare l'intera pipeline.
    # Logghiamo l'errore e restituiamo un placeholder che Claude può
    # interpretare correttamente (assenza di analisi visiva = cautela massima).
    log.error(
        "Gemini Vision: tutti i %d tentativi falliti. Ultimo errore: %s",
        max_retries, last_exception,
    )
    return (
        "[ERRORE: analisi visiva Gemini non disponibile dopo "
        f"{max_retries} tentativi -- ultimo errore: {last_exception}. "
        "Procedi con MASSIMA cautela: nessun dato visivo affidabile, "
        "tratta come se le foto non fossero analizzabili e applica la "
        "regola su assenza totale di prove di brand dove pertinente.]"
    )


# ---------------------------------------------------------------------------
# CLAUDE -- prezzi, margine, verdetto finale (con web_search)
# ---------------------------------------------------------------------------

def call_claude_oracle(listing_info, gemini_analysis_json):
    user_text = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto dal venditore: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"URL annuncio: {listing_info.get('url') or 'non disponibile'}\n\n"
        "--- ANALISI VISIVA COMPLETA (JSON prodotto da Gemini dopo aver esaminato\n"
        "tutte le foto dell'annuncio) ---\n"
        f"{gemini_analysis_json}\n"
        "--- FINE ANALISI VISIVA ---\n\n"
        "NOTA: non hai accesso diretto alle foto originali. Il JSON sopra è la "
        "tua UNICA fonte visiva, prodotta da un modello che ha esaminato tutte "
        "le immagini in dettaglio, incluso ogni logo/marchio visibile separatamente. "
        "Fidati di questo JSON per identificazione, condizione e legit check visivo, "
        "ma applica il tuo giudizio critico: se il JSON segnala una incongruenza "
        "(es. un logo non coerente con il brand dichiarato), trattala come un "
        "segnale di rischio serio nel tuo legit check, non ignorarla.\n\n"
        "Produci ora il verdetto operativo completo, nel formato compatto richiesto."
    )

    log.info("PROMPT TESTUALE -> CLAUDE (nessuna immagine, solo JSON Gemini):\n%s", user_text)

    content = [{"type": "text", "text": user_text}]

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1200,
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
            img = download_image_bytes(photo_url, referer=url)
            if img:
                photo_bytes_list.append(img)
            time.sleep(0.4)  # piccola pausa per non sembrare scraping aggressivo

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

    gemini_analysis_json = call_gemini_vision(photo_bytes_list, listing_info)
    log.info("RISPOSTA GEMINI (JSON, %d foto inviate):\n%s", len(photo_bytes_list), gemini_analysis_json)

    final_report = call_claude_oracle(listing_info, gemini_analysis_json)
    log.info("RISPOSTA CLAUDE (senza foto, solo JSON Gemini):\n%s", final_report)

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
