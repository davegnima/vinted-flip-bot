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
     galleria + taglia/condizione/descrizione/catalog/materiale (se
     disponibili)
  4. Gemini 3.5 Flash: analisi visiva pura (identificazione, autenticita',
     condizione) -- NESSUN prezzo, NESSUNA ricerca web
  5. Claude Sonnet 4.6: usa l'analisi di Gemini + foto + dati annuncio,
     fa ricerca web (Serper) e produce il report Vinted Flip Oracle Pro
     completo (compatto)
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
  SERPER_API_KEY         - chiave API Serper (ricerca + scrape)

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
  - RICERCA COMP VINTED RAFFINATA (29/06/2026): verificato empiricamente
    che material_ids[]/color_ids[] numerici NON esistono piu' come filtro
    URL sul sito attuale (le vecchie API/wrapper che li esponevano sono
    legacy/deprecate -- Materiale e Colore sono oggi solo stringhe nel
    payload "request_options" della pagina annuncio, senza ID associato).
    catalog_id invece e' ancora un ID numerico valido e filtrabile.
    Strategia adottata, testata a mano sul sito reale (Marni + catalog
    "Abiti" id=10 + search_text="velluto" -> 13 risultati pertinenti,
    range prezzo 25-850 EUR, materiale indicizzato anche se assente dal
    titolo del venditore): brand_ids[] (da mappa) + catalog[] (se
    disponibile) + search_text = categoria breve + UN SOLO materiale,
    quello piu' pregiato tra quelli elencati nell'annuncio (non il primo
    della lista, spesso il piu' economico). Il colore resta solo
    informativo per Claude, non un filtro URL (troppo granulare, rischio
    di azzerare i risultati). Lo status_ids[] resta fisso a 1,2,3 (Nuovo
    con cartellino/Nuovo senza cartellino/Ottime) per scelta esplicita
    dell'utente: serve da benchmark "prezzo in buone condizioni" anche
    quando l'annuncio target e' in condizione peggiore, da scontare nel
    ragionamento di Claude (non da restringere ulteriormente nel filtro).
"""

import os
import re
import json
import time
import asyncio
import base64
import logging
import traceback
import hashlib
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
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERPER_API_KEY = os.environ["SERPER_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_MODEL_NAME = "gemini-3.5-flash"
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL_NAME}:generateContent"
)
GEMINI_CACHED_CONTENTS_URL = "https://generativelanguage.googleapis.com/v1beta/cachedContents"

# EXPLICIT CACHING GEMINI (aggiunto 29/06/2026 dopo verifica spesa reale:
# €4,18 in un giorno, €0,00 di risparmio cache -- il caching IMPLICITO di
# Gemini ("no cost saving guarantee" per documentazione ufficiale) non
# stava scattando in modo affidabile su gemini-3.5-flash, modello molto
# recente (uscito 19/05/2026) potenzialmente non ancora coperto a pieno
# dall'implicit caching. L'EXPLICIT caching (client.caches.create, qui
# replicato via REST puro per restare coerenti con lo stile requests
# del resto del file) garantisce lo sconto 90% sui token cachati,
# indipendentemente da soglie/euristiche interne di Google.
#
# Il GEMINI_VISION_SYSTEM_PROMPT e' enorme e identico ad OGNI chiamata
# (e' il candidato ideale per il caching, esattamente come il system
# prompt di Claude) -- viene cachato UNA VOLTA all'avvio del bot (TTL
# lungo, ricreato automaticamente se scaduto/invalido), poi ogni
# chiamata Gemini lo referenzia con "cachedContent" invece di rimandarlo
# per intero. Le foto restano SEMPRE nel messaggio utente non cachato
# (cambiano ad ogni annuncio, non sono mai cachabili), quindi il
# risparmio si applica solo alla porzione di system prompt, non alle
# foto -- ma su un prompt di migliaia di token ripetuto a ogni chiamata,
# anche questo da solo vale la pena.
GEMINI_CACHE_TTL_SECONDS = 3600 * 6  # 6 ore: ampio margine, costo storage trascurabile vs risparmio
_gemini_cache_name = None  # popolato da assicura_gemini_cache(), None se non ancora creata/fallita

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_GALLERY_PHOTOS = 10  # tetto massimo foto da inviare ai modelli (costo)

# Adatta questa stringa se il nome/username esatto del bot terzo e' diverso
VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

# Mappa NOME BRAND (lowercase, come confrontato dal codice) -> brand_id
# Vinted. Questi ID sono presi DIRETTAMENTE dalle URL dei watch reali
# dell'utente (changedetection.io), non indovinati: Vinted non li indicizza
# pubblicamente, l'unico modo affidabile per ottenerli e' aprire il sito,
# filtrare per brand, e leggere il numero dall'URL risultante.
#
# Usata per costruire ricerche Vinted filtrate per brand_id (precise, zero
# rumore da testo libero) al posto di ricerche Serper generiche su Vinted.
# Se un brand non e' in questa mappa, il codice deve fare fallback su
# ricerca testuale (search_text=) o saltare la query Vinted dedicata --
# MAI inventare un brand_id plausibile, un ID sbagliato filtrerebbe
# risultati del brand sbagliato in modo silenzioso e pericoloso.
#
# STATO: parzialmente popolata. Confermati con certezza da URL reali:
VINTED_BRAND_IDS = {
    "brunello cucinelli": "103740",
    "rick owens": "145654",
    "arc'teryx": "319730",
    "arcteryx": "319730",  # alias senza apostrofo, per matching piu' robusto
    "patagonia": "90804",
    "marni": "12251",
    "missoni": "4463",
    "jean paul gaultier": "4129",
    "jpg": "4129",  # alias comune
    "emilio pucci": "10831",
    "pucci": "10831",  # alias comune
    "issey miyake": "75090",
    "pleats please": "395642",
    "pleats please issey miyake": "395642",
    "claude montana": "121608",
    "miu miu": "1745",
    "thierry mugler": "284",
    "mugler": "284",  # alias comune
    "courreges": "12639",
    "courrèges": "12639",  # alias con accento
    # NOTA: Vivienne Westwood NON ha un brand_id dedicato su Vinted
    # (verificato dall'URL reale: nessun brand_ids[] presente nonostante
    # il filtro applicato) -- per questo il fallback su search_text e'
    # l'unica opzione, non un'omissione. Thierry Mugler e Courreges
    # ERANO inizialmente segnalati come privi di ID, ma sono stati poi
    # confermati con un secondo controllo (vedi sopra) -- la nota
    # originale era quindi imprecisa per questi due.

    # Watch 1 "Visual Icons" -- completato, ultimi 4 confermati:
    "m missoni": "1702343",
    "missoni home": "2776470",
    "missoni mare": "2720679",
    "vivienne westwood": "14217",

    # Watch 3 "Avant-Garde" -- completato, 5 confermati:
    "yohji yamamoto": "200474",
    "dries van noten": "72138",
    "ann demeulemeester": "51445",
    "raf simons": "184436",
    "loewe": "24209",

    # Watch 2 "Cappotti 90s Minimal" -- completato, 5 confermati:
    "helmut lang": "47829",
    "jil sander": "17991",
    "bottega veneta": "86972",
    "maison margiela": "639289",
    "margiela": "639289",  # alias comune
    "max mara": "5483",

    # Watch 4 "Technical Outerwear" -- completato, 4 confermati:
    "veilance": "3388210",
    "nanga": "434286",
    "snow peak": "666350",
    "acronym": "712647",
}

# Priorita' materiali: quando un annuncio elenca piu' materiali (es. "Cotone,
# Denim, Velluto"), scegliamo per il search_text quello piu' indicativo di
# valore/pregio, non il primo della lista (spesso il piu' generico/economico).
# Ordine = priorita' decrescente: il primo materiale annuncio che matcha
# qualsiasi voce qui sotto viene scelto. Se nessun materiale dell'annuncio
# e' in questa lista, non sceglie nulla (meglio nessun filtro extra che uno
# scelto a caso/primo-della-lista senza criterio).
MATERIALI_PREGIATI_PRIORITA = [
    "cashmere", "vicuna", "vigogna", "seta", "velluto", "pelle", "shearling",
    "montone", "renna", "alpaca", "mohair", "lana", "lino", "viscosa", "lurex",
    "denim", "cotone",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("vinted_flip_bot")


def scegli_materiale_per_ricerca(material_value_raw):
    """material_value_raw: stringa grezza vista in pagina, es.
    'Cotone, Denim, Velluto'. Ritorna il materiale con priorita' piu' alta
    tra quelli elencati (lowercase, pronto per search_text), o None se
    nessuno dei materiali elencati e' nella lista di priorita'.

    Definita qui (prima di scrape_vinted_listing, che la usa, e prima di
    build_vinted_search_url) per evitare problemi di ordine di definizione
    in un singolo file eseguito top-to-bottom."""
    if not material_value_raw:
        return None
    materiali_annuncio = [m.strip().lower() for m in material_value_raw.split(",")]
    for materiale_prioritario in MATERIALI_PREGIATI_PRIORITA:
        if materiale_prioritario in materiali_annuncio:
            return materiale_prioritario
    return None


# ---------------------------------------------------------------------------
# VINTED FLIP ORACLE PRO -- system prompt (identico alla versione precedente)
# ---------------------------------------------------------------------------

VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT = r"""
Sei **Vinted Flip Oracle Pro**: valuti annunci second-hand (Vinted, Vestiaire, Grailed, eBay, Depop, Wallapop, StockX/GOAT) per stabilire se conviene comprarli per rivendere. Freddo, preciso, conservativo: proteggi l'utente da fake, margini illusori, prezzi gonfiati, difetti nascosti, capi illiquidi. Non confermi la sua intuizione.

# INPUT
Non vedi le foto originali. Ricevi un JSON di Gemini: trascrizione letterale etichette ("testo_letterale_etichette" = fonte primaria, non riassumere), identificazione, loghi (con flag coerente_con_brand_dichiarato), analisi foto per foto, difetti, legit check preliminare. Fonte visiva unica e attendibile; logo flaggato incoerente = rischio serio nel tuo Legit check.

REGOLA VINCOLANTE — ASSENZA TOTALE PROVE BRAND: zero loghi/etichette/tag in tutte le foto E descrizione senza dettagli verificabili → decisione NON PUÒ essere COMPRA/COMPRA SUBITO/TRATTA (pattern/stile simile NON è prova di autenticità, è ciò che un falso condivide facilmente). Solo CHIEDI ALTRE FOTO (se margine lo giustifica) o NON COMPRARE. Fattore decisivo, non nota di passaggio.

Stima lingua titolo/descrizione → paese venditore → spedizione (tabella sotto).

# MARGINE E SOGLIE
Margine a DUE GAMBE sempre, mai "vendita−acquisto" semplice:
**Acquisto pieno** = prezzo + protezione acquirenti (~5%+€0,70, verifica importo corrente) + spedizione entrata (da lingua se non chiara/plausibile: IT 2,50€, FR/ES/PT 4,50€, DE/NL/nord-centro EU 5-6€, altre→indicata se plausibile altrimenti analogia geografica) + eventuale sistemazione.
**Incasso** = vendita probabile post-trattativa − spedizione offerta − sconto chiusura (protezione la paga il compratore finale, non erode il tuo incasso).
**Margine netto = incasso − acquisto pieno**, sempre € e ROI%. Soglia utente: 20€ netti — sotto, default NON COMPRARE anche con ROI alto, salvo rischio bassissimo e zero sforzo.

SOGLIA ROI MINIMO — SECONDO GATE INDIPENDENTE (non sostituisce la soglia 20€ sopra, si applica IN AGGIUNTA): ROI minimo 100% sul costo pieno richiesto per qualsiasi livello COMPRA (SUBITO/FORTE/COMPRA/SE CI TIENI). Questo vale ANCHE quando il margine € supera abbondantemente i 20€ — un margine assoluto alto con ROI basso (es. €22-27 di margine su un costo pieno di €48, ROI ~46-56%) NON è un COMPRA: è capitale impegnato con rendimento insufficiente rispetto ad altre occasioni che soddisfano entrambe le soglie. I due gate (€ assoluto e ROI%) sono entrambi vincolanti e indipendenti: serve superarli TUTTI E DUE, non basta superarne uno. Sotto soglia ROI ma sopra soglia €: TRATTA (se il margine trattato può plausibilmente portare il ROI sopra 100%, ricalcolando sul costo pieno trattato più basso) o NON COMPRARE (se anche trattando il ROI resterebbe sotto 100%).

Voto Margine (€ assoluto base, ROI% modificatore ±1 max, mai cambia fascia): 0-2/10 <10€/negativo; 3-4/10 10-19€; 5-6/10 20-39€; 7-8/10 40-99€; 9-10/10 100€+. ROI 80%+→+1, 40-80%→0, <20%→-1.

REGOLE COMPRA/TRATTA (applica in ordine):
1. Costo pieno <15€ E legit check non negativo (anche solo "probabile autentico" 70-80%) E margine 80€+ → COMPRA/COMPRA SUBITO sempre (mai TRATTA/CHIEDI FOTO): il downside di pochi euro è trascurabile, il rischio reale è perdere il pezzo aspettando. Taglia/condizione mancanti = domande POST-acquisto. Eccezione solo se legit check davvero negativo.
2. Se margine pieno è già sopra 20€ (e non rientra nel punto 1), MAI scrivere TRATTA — trattare è bonus non condizione, scegli il livello COMPRA della matrice. Errore da evitare: "trattare è inutile" + decisione TRATTA.
3. Eccezione al punto 2: margine sopra soglia ma 20-40€ (non schiacciante) E confidenza Media/Bassa E capo hype/monitorato → TRATTA è accettabile anche qui, perché il margine "sopra soglia" è incerto (motiva il fattore tempo/incertezza in "In una riga"). Se nicchia o confidenza Alta, resta COMPRA.
4. TRATTA/TRATTA FORTE altrimenti solo se margine pieno sotto soglia ma accettabile scontando, o Deal/Margine ≤3 con confidenza non Alta.

# MATRICE DECISIONALE (calcola Deal/Margine/Liquidità/Rischio/Confidenza PRIMA, poi deriva — mai COMPRA solo perché il margine € supera la soglia)

**Asse Qualità (6 livelli, severità crescente; in dubbio tra due, scegli il più basso):**
1. COMPRA SUBITO — Deal 9-10 E Margine 8-10 E Confidenza non Bassa E Rischio non ALTO, tutti insieme. Parsimonia (2-3/giorno).
2. COMPRA FORTE — Deal 8 E Margine 7-8, Rischio BASSO/MEDIO.
3. COMPRA — Deal 6-7 E Margine 5-7, Rischio BASSO/MEDIO.
4. COMPRA SE CI TIENI — Deal 4-5 O Margine 4-5.
5. TRATTA (o FORTE) — vedi regole sopra.
6. NON COMPRARE — margine insufficiente anche scontando, Rischio ALTO, o legit check negativo. CHIEDI ALTRE FOTO invece se il solo problema è dati mancanti (non rischio economico) e legit check non negativo.

**Asse Urgenza (3 livelli, indipendente — solo se qualità è COMPRA*/SE CI TIENI/TRATTA; se NON COMPRARE/CHIEDI FOTO scrivi "N/A"):**
Priorità 1 — scarto prezzo/valore: ROI 150%+ o prezzo palesemente anomalo (pochi euro per brand riconoscibile autentico) → AGISCI ORA da solo, indipendentemente da hype/età (un prezzo così salta all'occhio a chiunque, non serve hype per fare concorrenza).
Priorità 2 — età pubblicazione (solo se scarto prezzo non già estremo): 0-2gg + brand hype → concorrenza reale. 5+gg senza compratori → domanda debole, non "tempo per trattare" (rivedi anche la stima di vendita al ribasso).
- AGISCI ORA: scarto prezzo estremo, o 0-2gg + hype.
- HAI QUALCHE ORA: margine buono non estremo, recente ma non hype, o 3-5gg ancora conteso.
- HAI TEMPO: 5+gg senza compratori, o nicchia con prezzo non anomalo.
Età non disponibile → basati su scarto prezzo/hype, livello più cauto in dubbio.

Scrivi "Decisione: [qualità] · [urgenza]", es. "COMPRA SUBITO · AGISCI ORA" o "NON COMPRARE · N/A".

# PREZZI — RICERCA
1. Vinted mostra solo ASK mai sold — vietato inventare "sold Vinted".
2. Gerarchia: eBay sold > Vestiaire (ask+alcuni venduti) > Grailed/StockX/GOAT (streetwear/sneaker) > Vinted/Depop/Wallapop (solo ask, usa per saturazione/psicologia, non valore).
3. Sold estero (valuta locale) va scontato per Vinted IT, più price-sensitive — dichiara l'aggiustamento.
4. Comps scarsi/sporchi → confidenza bassa, non colmare con memoria/retail.
5. Target vendita 7-14gg: prezzo competitivo con margine trattativa incluso.
6. PRIMA di proporre prezzi, usa i RISULTATI RICERCA WEB già forniti più sotto nel messaggio: sono stati recuperati per te da una ricerca esterna fatta con una query ampia (più fonti insieme — eBay sold, Vestiaire, Vinted). Non hai un tool di ricerca proprio: questi risultati grezzi sono la tua UNICA fonte di dati di mercato, vanno interpretati con giudizio critico (titoli e snippet possono essere ask non sold, prezzi in valute diverse, articoli non comparabili — scartali se non pertinenti; pagine catalogo generiche senza un prezzo specifico — es. "Buy second-hand MARNI t-shirts" — non sono comps, ignorale). Gli snippet possono contenere rumore testuale (sequenze di caratteri sparsi tipo lettere isolate intervallate, residuo di testo "sponsorizzato" corrotto): ignora quei frammenti illeggibili, non provare a interpretarli come dati. Se la sezione dichiara "nessun risultato" o "ricerca fallita", non hai comps disponibili: dichiara confidenza Bassa e resta prudente al ribasso. Mai stimare solo da memoria/retail/valore "da collezione" quando i risultati ci sono ma non li usi.

DIFFUSION LINE (Missoni/Missoni Sport, Prada/Miu Miu, Armani/Emporio-Exchange, Max Mara/Weekend, ecc.): non vale automaticamente come la mainline — dipende dal brand, alcune restano ricercate altre no. Cerca comps SPECIFICI per quella linea esatta. Solo comps mainline trovati → NON usarli come proxy diretto, confidenza bassa, stima al ribasso, dichiaralo.

CONSERVATORISMO CONFIDENZA: il numero in "Vendita probabile" non è mai punto medio/alto se Confidenza non è Alta. Media→quartile basso. Bassa→quartile più basso o sotto, dillo nel motivo (ask online spesso aspirazionali).

ESEMPIO PRATICO "Costo pieno trattato" con decisione CHIEDI ALTRE FOTO: costo richiesto €28 (prezzo €21,70 + protezione + spedizione), capo probabilmente autentico ma servono altre foto per la taglia/composizione → NON scrivere "Costo pieno trattato: N/A". Stima invece un'offerta ragionevole comunque proponibile mentre aspetti le foto, es. "Costo pieno trattato: €24-25 (offerta €18-19)" — la trattativa e la richiesta di foto non sono alternative, puoi fare entrambe nello stesso messaggio.

CHECK PRIMA DI SCRIVERE "Vendita probabile": (1) diffusion line? comps specifici per quella linea o genericamente mainline? Se mainline/generici, taglia indicativamente -30/-50% e dillo. (2) Quanti comps solidi/specifici hai davvero trovato? 0-2 → confidenza non oltre Media, numero al quartile basso (non "quanto sembra valere guardandolo").

# LIQUIDITÀ
Giorni vendita (0-7/7-14/14-30/30+) e liquidità (Bassa/Media/Alta) da: saturazione, tier domanda brand/modello, taglia (penalizza estreme), stagionalità, spedizione/rischio reso. Prezzo basso ≠ buon affare se illiquido.

ERRORE DA NON RIPETERE (visto in produzione): non confondere la liquidità del BRAND con la liquidità del PEZZO SPECIFICO. Brand di lusso molto liquidi su Vinted IT (es. Brunello Cucinelli, Loro Piana, Stone Island, Moncler — capi che vendono quasi sempre, in fretta, a prezzo solido) restano brand liquidi anche quando il PEZZO specifico in valutazione è più lento per altri motivi (taglia fuori stagione, difetti visibili, modello di nicchia dentro quel brand). In questi casi scrivi la liquidità riferendola esplicitamente al pezzo, non al brand: es. "Liquidità: Bassa (pezzo specifico: cardigan estivo taglia S con difetti — il brand Brunello Cucinelli resta tra i più liquidi su Vinted IT)", non "Brunello Cucinelli poco liquido su Vinted IT", che è un'affermazione fattualmente sbagliata sul brand.

# COSA ANALIZZARE
Identificazione: brand, categoria, modello, linea/epoca, taglia, fit, colore, materiale, paese produzione, retail originale, rarità reale (certo/probabile/non verificato).
Visiva: usura, pilling, scolorimento, macchie, buchi, scuciture, hardware, fodere, riparazioni, incongruenze foto/descrizione, foto mancanti.
Legit check: Probabilmente autentico / Sospetto / Probabilmente falso / Non verificabile + confidenza% + rischio fake (basso/medio/alto/molto alto). Mai 100% senza prove eccezionali.
Condizione: dichiarata vs visibile vs probabile vs non verificabile; Nuovo con/senza cartellino, Ottime, Buone, Usato evidente, Da riparare, Non valutabile.

CONTROLLO FINALE OBBLIGATORIO (ultimo passo, prima di scrivere "Decisione" — non saltarlo mai, anche se i punteggi Deal/Margine della matrice sembrano già indicare un livello): guarda il numero esatto che hai appena scritto in "Margine netto al prezzo richiesto" (quello in €, non il ROI%). Fai la domanda diretta: è sotto 20€? Se SÌ, la decisione sull'asse qualità NON PUÒ essere nessun livello COMPRA (SUBITO/FORTE/COMPRA/SE CI TIENI) — deve essere TRATTA o NON COMPRARE, indipendentemente da quanto i punteggi Deal/Margine calcolati con la scala sembrino indicare un livello COMPRA. È un errore vincolare scrivere "margine sotto soglia 20€" nel ragionamento e poi "Decisione: COMPRA" nello stesso report: se questo succede, hai applicato la matrice qualità senza tornare a verificare la soglia assoluta in €, che ha sempre priorità. La matrice a 6 livelli serve per GRADUARE i casi sopra soglia o per individuare TRATTA quando sotto soglia — non sostituisce mai il controllo soglia, lo segue.

SECONDO CONTROLLO FINALE OBBLIGATORIO, STESSO IMPORTANZA DEL PRIMO (entrambi vanno fatti, in qualsiasi ordine, prima di scrivere "Decisione" — non sono alternativi): guarda il numero esatto di ROI% al prezzo richiesto. Fai la domanda diretta: è sotto 100%? Se SÌ, la decisione sull'asse qualità NON PUÒ essere nessun livello COMPRA (SUBITO/FORTE/COMPRA/SE CI TIENI), ANCHE SE il margine in € supera abbondantemente 20€ — deve essere TRATTA (se il ROI trattato può plausibilmente superare 100%) o NON COMPRARE. Caso reale visto in produzione da non ripetere: margine netto €22-27 su costo pieno €48,04 (ROI ~46-56%), Deal 6/10, Margine 5/10, Rischio BASSO — la matrice qualità a 6 livelli aveva indicato COMPRA perché guarda solo Deal/Margine in punti, non il ROI% in modo vincolante; la decisione corretta era invece TRATTA (margine € sopra soglia ma ROI sotto la soglia 100%, quindi la trattativa serve a far scendere il costo pieno e salire il ROI, non a confermare un COMPRA che il ROI da solo già esclude). Il punteggio "Margine: X/10" della matrice misura solo l'ampiezza assoluta in €, MAI il ROI%: i due controlli finali (soglia € e soglia ROI%) restano sempre da fare entrambi sul numero effettivo, indipendentemente da quanto i punteggi della matrice sembrino già decisi.

ERRORE SPECIFICO DA NON RIPETERE (visto in produzione, vietato esplicitamente): non scrivere mai un ragionamento del tipo "margine sotto soglia 20€, MA la regola velocità a costo minimo si applica: acquisto pieno <15€? No. Soglia non triggerata" seguito comunque da COMPRA SUBITO. Se la tua stessa frase conclude che una regola "non è triggerata" o "non si applica", quella regola non ha effetto sulla decisione, punto — non scrivere la conclusione opposta subito dopo. In quel caso specifico (acquisto pieno ≥15€, margine sotto 20€), la regola velocità NON si applica e la decisione corretta è TRATTA o NON COMPRARE, mai COMPRA SUBITO.

# OUTPUT — formato compatto, italiano. TETTO 150 PAROLE TOTALI. Conta prima di rispondere; se superi, tagli aggettivi non contenuto decisionale.

STILE: etichetta+valore secco, niente parentesi esplicative, niente "il problema è che...". N/A senza spiegare il perché sulla stessa riga. Motivo SOLO in "In una riga" (max15 parole) e Legit check (max20 parole), non ripetuto altrove. Numeri/decisioni prima delle spiegazioni.

VINCOLO CRITICO: la risposta finale viene spedita INTERAMENTE e AUTOMATICAMENTE su Telegram senza revisione umana. Qualsiasi testo che scrivi PRIMA di "## Verdetto operativo" finisce spedito comunque, senza eccezioni — questo include non solo "ricerco i prezzi" o note di ragionamento, ma ANCHE un riepilogo dei dati raccolti dalle ricerche (es. "Sintesi dati raccolti prima di scrivere il verdetto:", elenchi di comps trovati, prezzi retail, confidenza). Quel riepilogo è ESATTAMENTE il tipo di testo vietato: non è il formato richiesto, gonfia il messaggio, e se scritto come blocco separato prima del verdetto rischia di finire fuori ordine. Usa le ricerche per RAGIONARE internamente, non per produrre un resoconto scritto a parte: il primo testo che scrivi nella risposta deve essere il carattere "#" di "## Verdetto operativo", senza alcuna riga, titolo in grassetto, o elenco prima di quello — non un riassunto "pulito", zero.

Senza un tool di ricerca proprio (i dati di mercato sono già nel messaggio sopra), non c'è motivo di produrre testo intermedio prima del verdetto: scrivi in UN SOLO blocco, da "## Verdetto operativo" a "## Messaggio da inviare", senza interromperlo e senza nulla prima.

## Verdetto operativo
- **Decisione:** [qualità] · [urgenza], es. "COMPRA SUBITO · AGISCI ORA"
- **Costo pieno richiesto:** €X (SEMPRE prezzo+protezione+spedizione scomposti, es. "€21,70+€1,80+€2,50=€26" — mai il prezzo nudo)
- **Costo pieno trattato:** SEMPRE una stima numerica €X (anche approssimativa, es. "€18-20" se l'offerta esatta non è ancora chiara), MAI N/A — stima un'offerta ragionevole (in genere 10-20% sotto il richiesto, aggiustata per margine di trattativa del capo) anche quando la decisione è CHIEDI ALTRE FOTO o quando servono ancora informazioni: la trattativa è quasi sempre un'opzione concreta, indipendentemente da cosa manca per la decisione finale. L'UNICA eccezione legittima per N/A è quando il legit check ha già bloccato l'intera valutazione (capo probabilmente falso, prezzo non più rilevante) — in quel caso scrivi N/A e basta, senza stimare un'offerta per un capo che non comprerai comunque.
- **Vendita probabile:** €X in ~Z giorni (SEMPRE una stima numerica, anche a Confidenza Bassa — vedi sezione PREZZI sotto, MAI N/A)
- **Margine netto:** €X (ROI Y%) — richiesto · trattato, una riga
- **Deal:** X/10 · **Margine:** X/10 · **Liquidità:** Bassa/Media/Alta · **Rischio:** BASSO/MEDIO/ALTO (tipo in 3 parole) · **Confidenza:** Alta/Media/Bassa
- **In una riga:** [max15 parole]

## Legit check
Una riga, max20 parole: verdetto + confidenza% + segnale chiave.

## Da chiedere
Max3 domande telegrafiche, o "Non rilevante: margine insufficiente".

## Messaggio da inviare
SEMPRE in italiano anche se annuncio in altra lingua. Messaggio pronto breve, o "Non necessario".

Tutto il resto di questo prompt è per il TUO ragionamento interno — non riprodurlo in output, condensa nelle voci sopra.

# REGOLE FINALI
Niente prezzi alti senza sold/comps solidi. Retail ≠ valore usato. Rarità ≠ domanda reale. Brand forte ≠ flip sicuro. Non ignorare taglia/colore/condizione/rischio fake/liquidità/tempo vendita. Non inventare fonti o percentuali. Mai autenticità certa senza prove. Foto insufficienti → verdetto lo riflette. Margine da prezzo ottimistico → segnalalo.
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
    "query_di_ricerca_ideale": "Stringa BREVE e PRECISA (max 5-6 parole) ottimizzata per cercare comps di questo capo esatto su Google/eBay/Vinted. Usa SOLO brand + 2-4 parole chiave davvero distintive (es. 'M Missoni top lurex', 'Patagonia pile Retro-X', 'JPG giacca denim archivio'). NON includere parole generiche di riempimento (es. 'con', 'in', 'di colore', materiali ovvi) e NON ripetere la categoria due volte. Una query troppo lunga o troppo specifica fa fallire la ricerca (un venditore reale raramente scrive titoli cosi' dettagliati) -- meglio una query un po' piu' generica che zero risultati.",
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
  },
  "valutazione_flipper_preliminare": {
    "categoria_a_basso_valore": true/false,
    "motivo_se_basso_valore": "es. 'calzini, categoria a basso valore di rivendita indipendentemente dal brand' -- vuoto se categoria_a_basso_valore e' false",
    "verdetto_grezzo": "NON COMPRARE / VALUTA / COMPRA",
    "motivo_verdetto_grezzo": "max 20 parole, il motivo principale del verdetto grezzo",
    "prezzo_vendita_massimo_plausibile_eur": "numero intero in euro, SENZA simbolo di valuta -- la tua stima dell'ASSOLUTO MIGLIOR CASO per il prezzo di rivendita di questo capo specifico (con questa condizione, questa taglia, questo brand/modello), basata sulla tua conoscenza generale del mercato second-hand. Deve essere deliberatamente OTTIMISTICA, non una media realistica: e' lo scenario piu' favorevole possibile, usato solo per scartare i casi in cui anche l'ipotesi migliore non basta. Se non hai alcuna base per stimarlo (brand non riconosciuto, categoria troppo generica), scrivi null invece di inventare un numero."
  }
}

REGOLE IMPORTANTI:
- CAMPO "testo_letterale_etichette" -- OBBLIGATORIO E LETTERALE: per OGNI etichetta, tag, cartellino o scritta leggibile visibile in qualsiasi foto (brand, composizione, lavaggio, taglia, paese di produzione, codici, seriali), trascrivi il testo ESATTO e COMPLETO, parola per parola e percentuale per percentuale, come se Claude dovesse rispondere basandosi solo su questo testo senza mai vedere la foto. NON riassumere, NON parafrasare, NON scrivere giudizi qualitativi qui (quelli vanno in "legit_check_preliminare"): questo campo è una trascrizione, non un'opinione. Esempio SBAGLIATO: "etichetta composizione coerente con prodotto di fascia alta". Esempio CORRETTO: "98% Lana vergine, 2% Poliammide. Lavare a secco. Non candeggiare. Taglia 38-40-42". Se il testo è parzialmente illeggibile, riportalo comunque con i caratteri incerti segnalati, non saltare il campo.
- CAMPO "query_di_ricerca_ideale" -- questa stringa viene usata DIRETTAMENTE per cercare comps di prezzo su Google/eBay/Vinted: la sua qualità determina se la ricerca a valle trova risultati utili o torna vuota. Regole pratiche: (1) MAX 5-6 parole totali, brand incluso; (2) usa solo le 2-4 parole che un VENDITORE REALE scriverebbe nel titolo del suo annuncio (es. "M Missoni top lurex", non "M Missoni top smanicato in maglia metallica lurex"); (3) NON ripetere la categoria due volte, NON includere dettagli secondari (colore esatto, fit, dettagli di costruzione) che restringono troppo la ricerca; (4) in caso di dubbio tra una query più corta/generica e una più lunga/specifica, scegli SEMPRE quella più corta — una query troppo specifica produce zero risultati più spesso di quanto aiuti a trovare comps pertinenti.
- Il campo "loghi_e_marchi_visibili" è critico: se vedi anche un solo logo/marchio/scritta che non corrisponde al brand dichiarato dal venditore, DEVE apparire come elemento separato con "coerente_con_brand_dichiarato": false — non ometterlo, non minimizzarlo, non assumere che sia comunque lo stesso brand.
- CASO CRITICO -- ASSENZA TOTALE DI PROVE: se in NESSUNA delle foto fornite è visibile un logo, etichetta, tag, marchio o qualsiasi elemento che confermi il brand dichiarato (es. solo un pattern/colore/forma generico, senza alcun elemento testuale o grafico brand-specifico), questo NON è un dettaglio minore da annotare di passaggio: è un campanello d'allarme di primo livello. In questo caso, nel campo "legit_check_preliminare", il "verdetto" deve essere "Sospetto, servono altre foto" o "Non verificabile" (mai "Probabilmente autentico"), la "confidenza_percentuale" non deve superare il 40%, e "cosa_non_torna_o_e_dubbio" deve dichiarare esplicitamente e in modo evidente "ASSENZA TOTALE DI ETICHETTA/LOGO/TAG IN TUTTE LE FOTO FORNITE — nessuna prova visiva di brand oltre al pattern/aspetto generico". Un pattern o uno stile visivamente simile al brand dichiarato NON è una prova di autenticità: stili, colori e pattern geometrici sono tra gli elementi più facili da replicare senza replicare etichette o costruzione interna (es. il motivo check di Burberry o il monogram di Louis Vuitton sono entrambi ampiamente replicati su falsi; da soli, senza hardware/etichettatura coerente, non provano nulla).
- "analisi_visiva_per_foto" deve avere una voce per OGNI foto allegata, anche se il contenuto si ripete: se ricevi 6 foto, devono esserci esattamente 6 oggetti distinti (numero_foto da 1 a 6), MAI accorpati in meno voci anche se due foto mostrano dettagli simili.
- NON stimare alcun prezzo specifico in euro, NON parlare di mercato, margini o strategia di rivendita dettagliata: questo verrà fatto da un altro modello a valle con accesso a ricerca web, che non vedrà le foto e si baserà SOLO su questo JSON. L'UNICA eccezione è il campo "valutazione_flipper_preliminare", descritto sotto, che è un giudizio grezzo e intenzionalmente approssimativo (incluso il suo sotto-campo "prezzo_vendita_massimo_plausibile_eur", che è deliberatamente uno scenario ottimistico estremo per uso come soglia di scarto, non una stima di mercato realistica).
- CAMPO "valutazione_flipper_preliminare" -- serve a filtrare i casi più ovvi PRIMA che arrivino al modello di pricing, per risparmiare una chiamata costosa quando è già chiaro che non vale la pena procedere. Compilalo così:
  - "categoria_a_basso_valore": true SOLO se il capo è un PAIO DI CALZINI (o calze/collant in stile sportivo da pochi euro, non lingerie/intimo firmato) — questa è l'UNICA categoria che marchi true, indipendentemente dal brand. NON marcare true per nessun'altra categoria, nemmeno se sembra economica o di poco valore a colpo d'occhio: intimo, costumi da bagno, biancheria, bigiotteria, accessori generici POSSONO valere molto in base al brand specifico (es. La Perla, Eres, Agent Provocateur su intimo/costumi hanno mercato second-hand reale) — il pricing lo fa il modello a valle con ricerca web, non tu. In caso di dubbio su qualsiasi categoria diversa dai calzini, false.
  - "verdetto_grezzo": la tua stima approssimativa, basata SOLO su quello che vedi (non sai il prezzo richiesto né hai accesso a comps di mercato). "NON COMPRARE" solo se hai un motivo visivo forte (categoria a basso valore, OPPURE il legit check è già "Probabilmente falso" con alta confidenza, OPPURE condizione "Da riparare" con danni che probabilmente azzerano la rivendibilità). "COMPRA" solo se il capo sembra chiaramente di valore (brand riconoscibile, condizione ottima, autenticità non in dubbio) E non hai motivi di dubbio. In TUTTI gli altri casi (la maggioranza), scrivi "VALUTA" — il default deve essere VALUTA, non un'estremità: il tuo giudizio è grezzo apposta, lascia il lavoro fine al modello con ricerca prezzi reali. Non avere paura di scrivere VALUTA spesso, è la risposta corretta quando non hai elementi forti in una direzione.
  - "prezzo_vendita_massimo_plausibile_eur": stima SOLO il miglior caso possibile, non una media. Esempio: per una t-shirt Vivienne Westwood in buone condizioni, se la tua conoscenza generale del mercato second-hand suggerisce che capi simili raramente superano i 45€ anche nei casi più favorevoli, scrivi 45 — non un numero "medio" più basso, non un numero aspirazionale più alto. Questo numero viene usato SOLO per scartare i casi in cui il margine non ci sarebbe nemmeno nello scenario migliore (per questo deve essere generoso, non realistico) — non viene mai usato per confermare un acquisto, quindi un errore per eccesso qui è meno dannoso di un errore per difetto. Se il brand/modello non ti è familiare a sufficienza per avere una base di stima ragionevole, scrivi null: meglio nessuna stima che una inventata senza criterio.
- NON dichiarare mai autenticità al 100% senza prove eccezionali.
- Se le foto sono insufficienti per una valutazione solida, dillo esplicitamente nei campi pertinenti.
- Scrivi tutti i valori testuali in italiano.
- Rispondi ESCLUSIVAMENTE con il JSON, nessun altro testo.
""".strip()


# ---------------------------------------------------------------------------
# TELEGRAM BOT API HELPERS (solo per INVIARE i report finali)
# ---------------------------------------------------------------------------

def telegram_send_message(chat_id, text):
    """Invia un messaggio, spezzandolo automaticamente se supera 4096 caratteri.

    Note di robustezza: lo split prova prima a tagliare su un doppio
    a-capo (separazione tra sezioni), poi su un singolo a-capo, e solo
    come ultima risorsa taglia a metà testo. Se l'invio con Markdown
    fallisce (es. asterischi/blockquote non bilanciati per via del
    taglio), ritenta SENZA parse_mode: in quel caso il testo arriva
    comunque per intero, solo senza la formattazione."""
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
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not resp.ok:
            log.warning(
                "sendMessage con Markdown fallita (chunk %d/%d) -- HTTP %d: %s -- ritento senza parse_mode",
                i, len(chunks), resp.status_code, resp.text[:300],
            )
            resp2 = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=20,
            )
            if not resp2.ok:
                log.error(
                    "sendMessage fallita ANCHE senza Markdown (chunk %d/%d) -- HTTP %d: %s",
                    i, len(chunks), resp2.status_code, resp2.text[:300],
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

# Sessione condivisa: riusa connessione e cookie tra le richieste di
# scraping pagina e download immagini dello stesso annuncio, il che
# aiuta con CDN che si aspettano una sessione "coerente" (stessi cookie
# di tracking della pagina HTML quando poi richiedi le immagini).
_vinted_session = requests.Session()
_vinted_session.headers.update(VINTED_HEADERS)


def scrape_vinted_listing(url):
    """Tenta di recuperare tutte le foto della galleria + dati extra
    (taglia, condizione, descrizione, catalog_id, materiale) dalla
    pagina pubblica Vinted.
    """
    result = {
        "photo_urls": [], "size": None, "condition": None, "description": None,
        "created_at": None, "age_days": None,
        "catalog_id": None, "material_raw": None,
        "material_per_ricerca": None, "color_raw": None,
    }
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

        # Data di pubblicazione: serve per valutare l'urgenza reale (un
        # annuncio online da giorni senza essere stato comprato e' un
        # segnale che altri flipper potrebbero gia' averlo scartato o
        # che la domanda e' piu' bassa di quanto sembri -- molto diverso
        # da un annuncio appena pubblicato dove la corsa e' reale).
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
                log.warning("Impossibile calcolare l'eta' dell'annuncio da created_at_ts=%s", created_match.group(1))

        # CATALOG + MATERIALE/COLORE: per ricerche comp piu' raffinate.
        # CORREZIONE (29/06/2026, dopo verifica diretta sull'HTML reale via
        # DevTools): il pattern precedente cercava un payload JSON
        # "request_options" con {"code":"material","data":{"value":...}}
        # -- VERIFICATO non essere presente nell'HTML scaricato da requests
        # (i log diagnostici mostravano solo testo libero in descrizione o
        # il dizionario di traduzioni i18n {"item.details.color":"Colore"},
        # mai il dato del prodotto specifico). Il dato REALE e' invece
        # marcato con microdata schema.org standard: itemprop="color",
        # itemprop="status", itemprop="size" -- attributi HTML, non un
        # payload JS interno, quindi molto piu' stabili nel tempo. Pattern
        # verificato sul vero HTML di un annuncio (maglione Missoni):
        # <div itemprop="color"><span ...>Marrone, Azzurro</span></div>
        # CATALOG_ID: estratto dalla breadcrumb di navigazione in cima alla
        # pagina annuncio, verificata sul vero HTML il 29/06/2026. La
        # breadcrumb elenca le categorie dalla piu' generica alla piu'
        # specifica come link /catalog/<id>-<slug>, es. "Donna" (1904) ->
        # "Vestiti" (4) -> "Maglioni e pullover" (13) -> "Cardigan" (194),
        # seguita da un ultimo link RIDONDANTE che combina la stessa
        # categoria col brand (es. /catalog/194-cardigans/brand/4463-...) --
        # quel link va escluso (il pattern qui sotto matcha solo link che
        # terminano con "?referrer=item-crumbs", quindi SENZA un "/brand/"
        # nel mezzo). Prendiamo l'ULTIMO link valido = la categoria piu'
        # specifica, esattamente il livello di granularita' voluto per
        # filtrare i comp (es. "Cardigan", non il generico "Vestiti").
        catalog_matches = re.findall(
            r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"',
            html,
        )
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

        # Pattern: trova itemprop="X", poi il testo del primo <span> annidato
        # successivo (il valore reale) -- si ferma al primo tag che segue il
        # testo (es. un <button> di info annidato, visto nel caso "status"),
        # quindi NON cattura testo di elementi figli accidentali.
        material_match = re.search(
            r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)',
            html, re.DOTALL,
        )
        if material_match:
            result["material_raw"] = material_match.group(1).strip()
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(material_match.group(1).strip())

        color_match = re.search(
            r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)',
            html, re.DOTALL,
        )
        if color_match:
            result["color_raw"] = color_match.group(1).strip()

        log.info(
            "CATALOG/MATERIALE/COLORE estratti -- catalog_id=%s, "
            "material_raw='%s' -> scelto per ricerca='%s', color_raw='%s'",
            result["catalog_id"], result["material_raw"],
            result["material_per_ricerca"], result["color_raw"],
        )

        # DIAGNOSTICA TEMPORANEA: se NESSUNO dei tre campi e' stato trovato
        # (catalog_id, material_raw, color_raw tutti None), logghiamo una
        # porzione di HTML grezzo intorno alla prima occorrenza di
        # 'itemprop="color"' (l'ancoraggio verificato il 29/06/2026 sul
        # vero markup -- la versione precedente cercava la stringa
        # "Colore", che pero' matchava anche il dizionario di traduzioni
        # i18n {"item.details.color":"Colore"} e dava falsi indizi). Se
        # anche questo nuovo pattern smette di funzionare in futuro, il
        # log qui sotto mostra direttamente la struttura reale aggiornata.
        if not result["catalog_id"] and not result["material_raw"] and not result["color_raw"]:
            indice_color = html.find('itemprop="color"')
            if indice_color != -1:
                inizio = max(0, indice_color - 100)
                fine = min(len(html), indice_color + 400)
                log.warning(
                    "DIAGNOSTICA PATTERN MATERIAL/COLOR: nessun campo estratto per %s -- "
                    "porzione HTML grezzo intorno a 'itemprop=\"color\"' (offset %d-%d):\n%s",
                    url, inizio, fine, html[inizio:fine],
                )
            else:
                log.warning(
                    "DIAGNOSTICA PATTERN MATERIAL/COLOR: nessun campo estratto per %s -- "
                    "'itemprop=\"color\"' non e' nemmeno presente nell'HTML scaricato "
                    "(lunghezza totale HTML: %d caratteri). Possibile pagina bloccata, "
                    "vuota, o annuncio senza il campo Colore compilato dal venditore.",
                    url, len(html),
                )

    except Exception:
        log.warning("Scraping Vinted fallito per %s:\n%s", url, traceback.format_exc())

    return result


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

def optimize_image_bytes(img_bytes, max_size=768):
    """Ridimensiona e ricomprime l'immagine prima di inviarla a Gemini,
    per ridurre i byte trasferiti (e quindi il costo, dato che Gemini
    fattura anche in base alla dimensione dell'immagine input).

    max_size=768 (non 512 come in altre versioni viste): un compromesso
    deliberato -- 512px rischia di rendere illeggibili etichette piccole,
    codici di produzione o testo fine sulle wash tag, che sono spesso
    decisivi per il legit check (es. il caso reale "M Missoni" dove la
    wash tag conteneva un blocco di testo lungo e denso, leggibile solo
    se l'immagine non e' compressa troppo aggressivamente). 768px tiene
    comunque un risparmio di banda/costo significativo rispetto alle foto
    originali (spesso 1200px+) senza sacrificare la leggibilita'.

    Se l'ottimizzazione fallisce per qualsiasi motivo (formato non
    supportato, immagine corrotta), ritorna i byte originali invariati --
    non vogliamo che un problema di compressione blocchi l'intera
    valutazione."""
    try:
        img = Image.open(BytesIO(img_bytes))
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception as e:
        log.warning("Ottimizzazione immagine (Pillow) fallita, uso byte originali: %s", e)
        return img_bytes


def assicura_gemini_cache():
    """Crea la cache esplicita per GEMINI_VISION_SYSTEM_PROMPT se non
    esiste ancora (prima chiamata del processo) o se la precedente e'
    scaduta/invalida. Ritorna il nome della cache (stringa, da passare
    come "cachedContent" nelle chiamate generateContent) o None se la
    creazione fallisce -- in quel caso il chiamante deve fare fallback
    al comportamento precedente (system_instruction per intero ad ogni
    chiamata), MAI bloccare la pipeline per un problema di caching.

    Usa una variabile globale di modulo (_gemini_cache_name) come cache
    in-process: valida per tutta la durata del processo Railway, fino al
    prossimo restart o alla scadenza del TTL (6 ore, vedi
    GEMINI_CACHE_TTL_SECONDS) -- in quel caso la prossima chiamata che
    fallisce con "cache non trovata" la ricrea automaticamente (vedi
    gestione errori in call_gemini_vision)."""
    global _gemini_cache_name

    if _gemini_cache_name is not None:
        return _gemini_cache_name

    try:
        resp = requests.post(
            GEMINI_CACHED_CONTENTS_URL,
            params={"key": GEMINI_API_KEY},
            json={
                "model": f"models/{GEMINI_MODEL_NAME}",
                "systemInstruction": {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]},
                "ttl": f"{GEMINI_CACHE_TTL_SECONDS}s",
                "displayName": "vinted-flip-oracle-system-prompt",
            },
            timeout=30,
        )
        if resp.ok:
            cache_data = resp.json()
            _gemini_cache_name = cache_data.get("name")
            log.info(
                "Gemini explicit cache CREATA con successo: %s (TTL %ds, scade %s)",
                _gemini_cache_name, GEMINI_CACHE_TTL_SECONDS,
                cache_data.get("expireTime"),
            )
            return _gemini_cache_name
        else:
            log.warning(
                "Creazione Gemini explicit cache fallita (HTTP %d) -- "
                "fallback su system_instruction non cachato per questa "
                "chiamata. Body: %s",
                resp.status_code, resp.text[:300],
            )
            return None
    except Exception as e:
        log.warning(
            "Creazione Gemini explicit cache fallita (eccezione %s: %s) -- "
            "fallback su system_instruction non cachato per questa chiamata.",
            type(e).__name__, e,
        )
        return None


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
        optimized_bytes = optimize_image_bytes(img_bytes)
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(optimized_bytes).decode("utf-8"),
            }
        })

    # EXPLICIT CACHING: proviamo a usare la cache del system prompt se
    # disponibile. Se "cache_name" e' None (creazione cache fallita, o
    # primo avvio in corso), il payload include comunque system_instruction
    # per intero come fallback -- la chiamata Gemini funziona in entrambi
    # i casi, cambia solo se il system prompt viene rimandato per intero
    # (pagato a prezzo pieno) o referenziato dalla cache (scontato 90%).
    cache_name = assicura_gemini_cache()

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        # SAFETY SETTINGS: disattiviamo il blocco automatico di Google sui
        # contenuti delle 4 categorie standard. Motivazione specifica per
        # questo bot: le foto di abbigliamento second-hand (es. capi con
        # stampe particolari, intimo/costumi che POSSONO avere mercato
        # second-hand legittimo come discusso nel prompt) possono talvolta
        # attivare falsi positivi nei filtri di sicurezza generici di
        # Gemini, causando una risposta vuota o troncata che il nostro
        # codice tratterebbe come "analisi non disponibile" anche se il
        # contenuto era completamente innocuo. BLOCK_NONE rimuove questo
        # rischio di falsi positivi sul nostro caso d'uso specifico (non
        # stiamo generando contenuto, solo analizzando foto di vestiti).
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 6000,
            "responseMimeType": "application/json",
            # THINKING LEVEL (aggiunto 29/06/2026, dopo analisi costi reali):
            # gemini-3.5-flash usa di default thinking_level="medium" (il
            # default e' sceso da "high" a "medium" rispetto al precedente
            # gemini-3-flash-preview, ma resta comunque attivo -- per
            # tutti i modelli Gemini 3.x il thinking NON puo' essere
            # disattivato del tutto, a differenza dei modelli 2.5 dove
            # thinking_budget=0 lo azzerava). Osservato su una chiamata
            # reale in log: thoughtsTokenCount=1957, PIU' del JSON di
            # risposta visibile stesso (candidatesTokenCount=1553) --
            # dato che l'output (incluso il thinking, sempre fatturato)
            # costa 6x l'input ($9 vs $1.50 per milione di token), questo
            # singolo numero pesava piu' dell'intero costo di input
            # (testo+immagini) della stessa chiamata.
            #
            # "low" scelto (non "minimal"): il compito di Gemini qui non
            # e' banale -- richiede giudizio reale (coerenza logo/brand,
            # legit check con valutazione di rischio, non solo estrazione
            # meccanica), e la documentazione Google segnala "minimal" come
            # adatto solo a "task a bassa complessita' che non
            # beneficerebbero di un ragionamento estensivo". "low" e' la
            # via di mezzo piu' sicura: riduce sensibilmente il thinking
            # rispetto al default "medium" senza il rischio di "minimal"
            # sui campi piu' delicati del JSON (testo_letterale_etichette,
            # legit_check_preliminare). Se in produzione si osserva un calo
            # di qualita' (es. coerenza_con_brand_dichiarato sbagliata piu'
            # spesso, trascrizioni etichette meno accurate), il valore qui
            # va riportato a "medium" -- e' una scelta riducibile a una
            # singola riga, non serve altro codice.
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }

    if cache_name:
        # "cachedContent" e "system_instruction" sono MUTUAMENTE ESCLUSIVI
        # nell'API Gemini -- il system prompt e' gia' dentro la cache
        # (creato in assicura_gemini_cache), quindi qui va SOLO il
        # riferimento al nome della cache, mai entrambi insieme.
        payload["cachedContent"] = cache_name
    else:
        # Fallback: nessuna cache disponibile, mandiamo il system prompt
        # per intero come si faceva prima di questa modifica.
        payload["system_instruction"] = {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]}

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
                    log.warning(
                        "Gemini ha risposto 200 ma senza candidates (tentativo %d/%d) -- ritento.",
                        attempt, max_retries,
                    )
                    if attempt < max_retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    return "[Analisi visiva Gemini non disponibile: risposta vuota]"

                extracted_text = "".join(
                    p.get("text", "")
                    for p in (candidates[0].get("content", {}) or {}).get("parts", []) or []
                )

                # VALIDAZIONE CONTENUTO: una risposta HTTP 200 non garantisce
                # un JSON utile -- Gemini puo' restituire testo vuoto, troncato
                # a metà (es. per maxOutputTokens insufficiente con molte foto),
                # o un placeholder degenere come "...". Controlliamo lunghezza
                # minima e validità JSON prima di accettare la risposta: se
                # fallisce, trattiamo come errore transitorio e ritentiamo,
                # invece di passare a Claude un'analisi visiva inutilizzabile
                # che lo forzerebbe ad applicare "assenza totale di prove"
                # anche quando le foto in realtà mostravano etichette chiare.
                content_is_valid = False
                if extracted_text and len(extracted_text.strip()) >= 50:
                    try:
                        json.loads(extracted_text)
                        content_is_valid = True
                    except (json.JSONDecodeError, ValueError):
                        content_is_valid = False

                if content_is_valid:
                    return extracted_text

                log.warning(
                    "Gemini ha risposto 200 ma il contenuto e' vuoto/troppo corto/non JSON valido "
                    "(tentativo %d/%d) -- lunghezza testo: %d, anteprima: %r -- ritento.",
                    attempt, max_retries, len(extracted_text), extracted_text[:200],
                )
                if attempt < max_retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                # Ultimo tentativo esaurito con contenuto invalido: meglio
                # un placeholder esplicito che un JSON spazzatura passato a
                # Claude come se fosse analisi visiva valida.
                log.error(
                    "Gemini: contenuto invalido/vuoto persistente dopo %d tentativi. "
                    "Ultima risposta (anteprima): %r",
                    max_retries, extracted_text[:300],
                )
                return (
                    "[ERRORE: Gemini ha risposto ma il contenuto era vuoto, troncato o "
                    "non JSON valido dopo tutti i tentativi. Procedi con MASSIMA cautela: "
                    "nessun dato visivo affidabile, tratta come se le foto non fossero "
                    "analizzabili e applica la regola su assenza totale di prove di brand "
                    "dove pertinente.]"
                )

            # CACHE INVALIDA/SCADUTA: Gemini risponde HTTP 400/404 se il
            # "cachedContent" referenziato non esiste piu' (es. scaduto
            # prima del previsto, o il processo Railway ha avuto un cold
            # restart che ha invalidato la variabile globale _gemini_cache_name
            # in un altro worker). Invalidiamo la cache locale e ritentiamo:
            # il prossimo tentativo chiamera' assicura_gemini_cache(), che
            # la trovera' None e ne creera' una nuova automaticamente.
            if (
                cache_name
                and resp.status_code in (400, 404)
                and "cachedContent" in (resp.text or "")
                and attempt < max_retries
            ):
                log.warning(
                    "Gemini cache '%s' non valida/scaduta (HTTP %d) -- "
                    "invalido la cache locale e ritento (verra' ricreata "
                    "automaticamente). Body: %s",
                    cache_name, resp.status_code, resp.text[:300],
                )
                globals()["_gemini_cache_name"] = None
                payload.pop("cachedContent", None)
                payload["system_instruction"] = {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]}
                time.sleep(1)
                continue

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

def strip_per_photo_analysis(gemini_analysis_json):
    """Rimuove il campo 'analisi_visiva_per_foto' dal JSON di Gemini prima
    di passarlo a Claude. Quel campo e' narrazione descrittiva foto-per-
    foto (es. "Inquadratura frontale del vestito appeso a una gruccia...")
    pensata per dare a Claude una ricostruzione visiva completa, ma in
    pratica e' molto verbosa e ridondante rispetto ai campi di sintesi
    gia' presenti (difetti_riassunto, legit_check_preliminare,
    condizione_reale, testo_letterale_etichette) che contengono le
    informazioni che davvero incidono sul verdetto economico. Su annunci
    con molte foto (8-10) questo campo da solo arriva a pesare 1000+
    token extra nel messaggio a Claude, senza un beneficio proporzionale
    sulla qualita' del verdetto.

    Se il JSON non e' parsabile (es. placeholder di errore tipo "...",
    o un messaggio di errore esplicito da call_gemini_vision), lo
    restituisce invariato: non vogliamo rompere il flusso per un'
    ottimizzazione di costo."""
    try:
        data = json.loads(gemini_analysis_json)
    except (json.JSONDecodeError, ValueError, TypeError):
        return gemini_analysis_json

    if isinstance(data, dict) and "analisi_visiva_per_foto" in data:
        n_foto = len(data["analisi_visiva_per_foto"]) if isinstance(data["analisi_visiva_per_foto"], list) else 0
        del data["analisi_visiva_per_foto"]
        data["_nota_foto_analizzate"] = (
            f"{n_foto} foto analizzate in dettaglio da Gemini (descrizione "
            "narrativa per-foto omessa qui per brevita' -- usa difetti_riassunto, "
            "legit_check_preliminare e condizione_reale come sintesi)."
        )

    return json.dumps(data, ensure_ascii=False, indent=2)


def _serper_batch_query(labeled_queries, num_results=3, max_snippet_chars=150):
    """Esegue PIU' query Serper in UNA SOLA richiesta HTTP, usando il
    formato batch documentato da Serper: un array JSON di oggetti
    {"q": ..., "gl": ...} nel body della stessa POST verso /search.

    Prima facevamo 1 richiesta HTTP per query (3 connessioni separate per
    Vestiaire + 2 Google generiche); con il batch e' una sola connessione,
    che risponde con un array di risultati nello stesso ordine delle
    query inviate. Riduce l'overhead di rete (non i token verso Claude,
    che dipendono dal contenuto dei risultati, non da come li richiediamo).

    RISPARMIO TOKEN (aggiunto dopo richiesta esplicita): rispetto alla
    versione precedente, qui (1) NON includiamo piu' il link nella riga
    di output -- Claude non lo usa mai per stimare prezzi, e i link reali
    osservati in produzione sono spesso lunghi 80-150+ caratteri per via
    di parametri di tracking (es. "?srsltid=AfmBOop..."), puro spreco di
    token; (2) gli snippet vengono troncati a max_snippet_chars (default
    150) -- il prezzo/dato utile e' quasi sempre nelle prime parole dello
    snippet, il resto e' spesso testo descrittivo generico; (3) num_results
    di default sceso da 4 a 3 -- un risultato in meno per fonte, accettabile
    visto che le 3 query batch sono comunque integrate dai 2 scrape diretti
    (Vinted, eBay) per i comps piu' specifici.

    Nota: il batch funziona solo per l'endpoint di RICERCA (/search), non
    per lo SCRAPE di pagina (scrape.serper.dev) -- Vinted ed eBay restano
    quindi chiamate separate, gestite altrove.

    labeled_queries: lista di tuple (label, query_string).
    Ritorna un dict {label: testo_risultati}, nello stesso formato che
    serve a search_comps_serper per assemblare il prompt finale."""
    labels = [label for label, _ in labeled_queries]
    queries = [query for _, query in labeled_queries]

    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=[{"q": q, "gl": "it", "hl": "it", "num": num_results} for q in queries],
            timeout=15,
        )
        resp.raise_for_status()
        batch_results = resp.json()
    except Exception as e:
        log.warning("Ricerca batch Serper fallita per %d query: %s", len(queries), e)
        # Fallback: tutte le label ricevono lo stesso messaggio di fallimento,
        # cosi' il prompt finale a Claude resta coerente anche in caso di errore.
        return {
            label: f"  Ricerca fallita per errore tecnico ({type(e).__name__}). Nessun dato da questa fonte."
            for label in labels
        }

    # La risposta batch e' un array nello stesso ordine delle query inviate.
    if not isinstance(batch_results, list) or len(batch_results) != len(labels):
        log.warning(
            "Risposta batch Serper inattesa (tipo=%s, lunghezza=%s, atteso=%d) -- fallback.",
            type(batch_results).__name__,
            len(batch_results) if isinstance(batch_results, list) else "n/a",
            len(labels),
        )
        return {label: "  Risposta batch inattesa, nessun dato da questa fonte." for label in labels}

    results_by_label = {}
    for label, data in zip(labels, batch_results):
        organic = data.get("organic", []) if isinstance(data, dict) else []
        if not organic:
            results_by_label[label] = "  Nessun risultato trovato per questa fonte/query."
            continue
        lines = []
        for r in organic[:num_results]:
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            if len(snippet) > max_snippet_chars:
                snippet = snippet[:max_snippet_chars].rstrip() + "..."
            # Link OMESSO deliberatamente -- vedi nota sopra: non e' mai
            # usato da Claude per il pricing, e' puro overhead di token.
            lines.append(f"  - {title}\n    {snippet}")
        results_by_label[label] = "\n".join(lines)

    return results_by_label


def build_vinted_search_url(brand, categoria, modello_o_categoria, max_price=None,
                             catalog_id=None, material_per_ricerca=None):
    """Costruisce un URL di ricerca Vinted filtrato per brand_id quando
    disponibile, con fallback su search_text quando il brand non e' nella
    mappa VINTED_BRAND_IDS.

    AGGIUNTE (verificate sul sito reale il 29/06/2026):
    - catalog_id: se disponibile (estratto dalla pagina annuncio target via
      scrape_vinted_listing), applicato come catalog[]=<id> -- filtro
      categoria preciso, riduce rumore tra sottocategorie diverse dello
      stesso brand.
    - material_per_ricerca: una singola parola materiale (es. "velluto",
      "cashmere"), scelta da scegli_materiale_per_ricerca() col criterio
      di priorita' sul materiale piu' pregiato tra quelli elencati
      nell'annuncio. Aggiunta dentro search_text (non un parametro URL a
      parte, perche' material_ids[] numerico NON esiste piu' sul sito
      attuale -- verificato: Materiale e' solo una stringa nel payload
      della pagina, senza ID associato). Test reale: Marni + catalog
      "Abiti" (id=10) + search_text="velluto" -> 13 risultati pertinenti,
      range prezzo 25-850 EUR, NESSUNO necessariamente con "velluto" nel
      titolo scritto dal venditore -- conferma che search_text indicizza
      anche l'attributo strutturato Materiale, non solo il titolo libero.

    NOTA SU COLORE: deliberatamente non incluso nel search_text di
    default -- i colori sono piu' granulari del materiale (es. "blu
    marino" vs "blu" come valori distinti) e il rischio di azzerare i
    risultati combinando brand+categoria+materiale+colore tutti insieme
    e' piu' alto. Resta disponibile come informazione testuale per
    Claude (color_raw in listing_info), non come filtro di ricerca.

    NOTA SU STATUS: NON modificato qui per scelta esplicita dell'utente --
    i comp restano sempre confrontati contro status_ids[]=1,2,3 (Nuovo con
    cartellino, Nuovo senza cartellino, Ottime) indipendentemente dalla
    condizione reale dell'annuncio target. Questo da' il prezzo di
    riferimento "in buone condizioni": se l'annuncio target e' in
    condizione peggiore, il comp funge da tetto massimo da scontare nel
    ragionamento (gia' gestito nel prompt Claude esistente), non va
    restretto ulteriormente per status.

    Ritorna (url, e_filtrato_per_id) dove e_filtrato_per_id indica se il
    filtro brand e' stato fatto con l'ID esatto (piu' affidabile) o solo
    per testo libero."""
    brand_lower = (brand or "").strip().lower()
    brand_id = VINTED_BRAND_IDS.get(brand_lower)

    catalog_str = f"&catalog[]={catalog_id}" if catalog_id else ""

    if brand_id:
        # Solo categoria breve + materiale pregiato (se disponibile) come
        # search_text -- il brand_id e il catalog[] (se presente) gia'
        # fanno il lavoro pesante di restringere correttamente, quindi
        # search_text resta intenzionalmente corto (1-3 parole), MAI il
        # modello stimato per intero (un venditore reale raramente scrive
        # un titolo cosi' dettagliato).
        categoria_breve = (categoria or "").strip()
        parti_search_text = [p for p in (categoria_breve, material_per_ricerca) if p]
        search_text_finale = " ".join(parti_search_text)

        url = (
            f"https://www.vinted.it/catalog?brand_ids[]={brand_id}"
            f"{catalog_str}"
            f"&search_text={quote(search_text_finale)}"
            "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
        )
        if max_price:
            url += f"&price_to={max_price}"
        return url, True
    else:
        # Senza brand_id, serve tutto il contesto possibile per compensare
        # l'assenza del filtro preciso -- qui la query piu' ricca aiuta,
        # non danneggia, perche' non c'e' un filtro a monte da affiancare.
        # Aggiungiamo comunque il materiale pregiato se disponibile.
        query_text = f"{brand} {modello_o_categoria} {material_per_ricerca or ''}".strip()
        url = (
            f"https://www.vinted.it/catalog?search_text={quote(query_text)}"
            f"{catalog_str}"
            "&order=newest_first"
        )
        return url, False


def search_comps_ebay_sold(brand, modello, categoria):
    """Ricerca diretta su eBay con filtro 'Venduto' (sold) via Serper,
    usando il parametro di ricerca eBay nativo invece di un site: generico
    -- piu' preciso perche' restiamo dentro l'interfaccia di ricerca eBay
    con i suoi stessi filtri, non un URL costruito a mano che potrebbe
    non rispettare i parametri reali del sito (es. LH_Sold=1 e' il
    parametro ufficiale eBay per 'solo venduti', verificato dalla
    documentazione pubblica eBay)."""
    query_base = f"{brand} {modello} {categoria}".strip()
    if not query_base:
        return None

    ebay_search_url = (
        f"https://www.ebay.it/sch/i.html?_nkw={quote(query_base)}"
        "&LH_Sold=1&LH_Complete=1&_sop=13"  # LH_Sold+LH_Complete = solo venduti; _sop=13 = piu' recenti
    )
    return ebay_search_url


def _clean_scraped_markdown(content):
    """Pulizia meccanica (nessuna chiamata AI, costo zero) del markdown
    grezzo restituito da scrape.serper.dev per pagine Vinted/eBay.

    Motivazione: osservato nei log reali che lo scrape di queste pagine
    porta con se' molto rumore strutturale che non aggiunge informazione
    utile per Claude (metadata SEO ripetuti, immagini SVG inline codificate
    in base64 lunghissime, link di servizio come "Vendi un oggetto simile"),
    e questo rumore da solo gonfiava il prompt finale a Claude fino a
    ~3x quanto preventivato, anche quando il risultato utile era solo
    "nessun risultato trovato" o 2-3 righe di prezzo reale.

    Questa pulizia e' puramente strutturale via regex (non capisce il
    significato del contenuto, solo riconosce pattern di rumore noti) --
    e' il primo livello di taglio, a costo zero, prima di valutare se
    serve anche un riassunto via AI per i casi in cui il contenuto utile
    resta comunque troppo lungo."""
    if not content:
        return content

    # Rimuove blocchi di metadata SEO/HTML (meta-description, meta-og-*,
    # meta-twitter-*, title, meta-viewport, ecc.) -- spesso appaiono in un
    # blocco delimitato da "---" all'inizio del markdown estratto.
    content = re.sub(
        r"^---\s*\nmeta-[\s\S]*?\n---\s*\n",
        "",
        content,
        flags=re.MULTILINE,
    )
    # Rimuove righe singole "meta-qualcosa: ..." anche se non in un blocco ---
    content = re.sub(r"^meta-[\w-]+:.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"^title:.*$", "", content, flags=re.MULTILINE)

    # Rimuove immagini SVG inline codificate in base64 (data:image/svg+xml;base64,...)
    # -- queste possono essere lunghe centinaia di caratteri per una singola
    # icona decorativa (es. freccia, lente di ricerca) senza alcun valore
    # informativo per il pricing.
    content = re.sub(r"!\[SVG Image\]\(data:image/svg\+xml;base64,[^)]+\)", "", content)
    content = re.sub(r"\(data:image/svg\+xml;base64,[^)]+\)", "", content)

    # Rimuove link di servizio ricorrenti senza valore informativo
    content = re.sub(r"\[Vendi un oggetto simile\]\([^)]+\)", "", content)
    content = re.sub(r"\[Logo di Vinted\]\([^)]+\)", "", content)
    content = re.sub(r"\[Passa al contenuto!?\[[^\]]*\]\([^)]+\)\]\([^)]+\)", "", content)
    content = re.sub(r"!\[Catalogo\]\([^)]+\)", "", content)

    # Estrae l'alt-text dalle immagini prodotto markdown (scartando SOLO
    # l'URL dell'immagine, che e' sempre inutile per il pricing), es.
    # "![T-shirt Marni, brand: Marni, condizioni: Buone, taglia: S, €25.00,
    # €26.95 include la Protezione acquisti](https://images1.vinted.net/...)"
    # -> "- T-shirt Marni, brand: Marni, condizioni: Buone, taglia: S,
    # €25.00, €26.95 include la Protezione acquisti".
    #
    # CORREZIONE IMPORTANTE rispetto a un primo tentativo: NON rimuovere
    # l'intera riga immagine -- verificato su un campione reale (29/06/2026)
    # che il prezzo/titolo/condizione di un risultato Vinted a volte vive
    # SOLO dentro l'alt-text dell'immagine, senza essere ripetuto altrove
    # nel testo circostante. Rimuovere l'intera riga (come fatto per le
    # icone SVG decorative sopra, dove l'alt-text non porta mai dato utile)
    # perderebbe quei prezzi. L'URL invece e' sempre scartabile: anche se
    # contiene un id foto, non e' mai usato da Claude per il pricing, e
    # pesa molto piu' dell'alt-text (spesso 80-150+ caratteri di path/token
    # CDN). Solo l'URL viene tagliato qui, l'informazione testuale resta.
    content = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"- \1", content)

    # Rimuove righe vuote multiple consecutive (residuo della rimozione
    # sopra) per non sprecare token su spazio bianco ripetuto.
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    return content


def _serper_scrape_page(url, max_chars=1300):
    """Scarica e legge il contenuto di una pagina specifica via
    scrape.serper.dev (endpoint diverso da quello di ricerca: qui l'URL
    e' GIA' NOTO, non stiamo cercando, stiamo leggendo). Usato per leggere
    il contenuto reale delle pagine Vinted/eBay costruite con URL precisi
    (filtro brand_id su Vinted, filtro LH_Sold su eBay), che danno
    risultati piu' pertinenti delle query generiche site: passate a
    Google.

    RISPARMIO TOKEN (max_chars sceso da 2500 a 1300): osservato nei log
    reali che il contenuto davvero utile (titolo annuncio, prezzo, data di
    vendita) e' quasi sempre nei primi 800-1000 caratteri del markdown
    pulito -- il resto e' tipicamente paginazione, filtri laterali
    ripetitivi ("Prezzo + spedizione: piu' economici", "Distanza: prima i
    piu' vicini", ecc.) che non aiutano il pricing. 1300 lascia un buon
    margine sopra quella soglia osservata senza sprecare token su rumore
    di navigazione.

    Pagine come Vinted/eBay possono avere protezioni anti-scraping (lo
    sappiamo gia' da Vinted stesso, 403 intermittenti) -- il fallimento
    qui e' previsto e gestito con grazia, non e' un errore di codice."""
    try:
        resp = requests.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"url": url, "includeMarkdown": True},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("Scrape Serper fallito per URL '%s': %s", url, e)
        return None

    content = data.get("markdown") or data.get("text") or ""
    if not content:
        return None

    # PULIZIA PRIMA DEL TRONCAMENTO: importante pulire prima di tagliare
    # a max_chars, altrimenti rischiamo di tagliare via contenuto utile
    # mentre teniamo rumore (es. un blocco SVG enorme) nei primi caratteri.
    content = _clean_scraped_markdown(content)

    return content[:max_chars]


def _esegui_ricerca_serper_completa(brand, modello, categoria, query_base,
                                     catalog_id=None, material_per_ricerca=None):
    """Esegue le 5 ricerche (Vinted scrape, eBay scrape, Vestiaire+2 Google
    in batch) per una data combinazione brand/modello/categoria. Funzione
    interna estratta da search_comps_serper per poter essere richiamata
    DUE VOLTE con parametri diversi (query specifica, poi query larga in
    fallback) senza duplicare tutta la logica di orchestrazione.

    catalog_id/material_per_ricerca: passati a build_vinted_search_url
    per la ricerca comp raffinata su Vinted (vedi note in quella funzione).

    Ritorna (results_by_label, vinted_e_per_id)."""
    results_by_label = {}

    vinted_url, vinted_e_per_id = build_vinted_search_url(
        brand, categoria, f"{modello} {categoria}".strip(),
        catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
    )
    ebay_url = search_comps_ebay_sold(brand, modello, categoria)

    serper_queries = [
        ("VESTIAIRE COLLECTIVE", f"{query_base} site:vestiairecollective.com"),
        ("GOOGLE GENERICO (prezzo/valore)", f"{query_base} prezzo valore second hand"),
        ("GOOGLE GENERICO (retail originale)", f"{query_base} retail price original"),
    ]

    log.info(
        "QUERY/URL SERPER COSTRUITI (base: '%s'):\n"
        "  VINTED (scrape, filtro_per_id=%s): %s\n"
        "  EBAY SOLD (scrape): %s\n"
        "  VESTIAIRE (query): %s\n"
        "  GOOGLE GENERICO 1 (query): %s\n"
        "  GOOGLE GENERICO 2 (query): %s",
        query_base, vinted_e_per_id, vinted_url, ebay_url,
        serper_queries[0][1], serper_queries[1][1], serper_queries[2][1],
    )

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_batch = executor.submit(_serper_batch_query, serper_queries)
        future_vinted = executor.submit(_serper_scrape_page, vinted_url)
        future_ebay = executor.submit(_serper_scrape_page, ebay_url)

        futures = {
            future_batch: "__BATCH__",
            future_vinted: "VINTED (scrape diretto)",
            future_ebay: "EBAY SOLD (scrape diretto)",
        }

        for future in as_completed(futures, timeout=20):
            label = futures[future]
            try:
                result = future.result()
                if label == "__BATCH__":
                    results_by_label.update(result)
                else:
                    results_by_label[label] = (
                        result if result else "  Scrape fallito o pagina vuota/bloccata (anti-bot)."
                    )
            except Exception as e:
                if label == "__BATCH__":
                    log.warning("Batch ricerca Serper non completato: %s", e)
                    for q_label, _ in serper_queries:
                        results_by_label[q_label] = "  Query non completata (timeout o errore)."
                else:
                    log.warning("Scrape Serper '%s' non completato: %s", label, e)
                    results_by_label[label] = "  Query non completata (timeout o errore)."

    return results_by_label, vinted_e_per_id


def search_comps_serper(brand, modello, categoria, catalog_id=None, material_per_ricerca=None):
    """Ricerca comps di prezzo via Serper. Sostituisce il tool web_search
    integrato di Claude per beneficiare del caching pieno sul system prompt.

    FALLBACK SPECIFICA -> LARGA (aggiunto dopo osservazione in produzione):
    una query troppo specifica (l'intero modello stimato da Gemini, spesso
    5-7 parole esatte) fa fallire quasi sempre lo scrape Vinted/eBay, anche
    quando il brand ha sicuramente capi in vendita -- un venditore reale
    raramente scrive un titolo cosi' dettagliato. Se la query specifica
    fallisce TOTALMENTE su tutte le 5 fonti, ritentiamo automaticamente
    con una query piu' larga (solo brand+categoria, senza il modello
    specifico) prima di arrenderci e dichiarare l'assenza di comps.

    catalog_id/material_per_ricerca: propagati dall'annuncio target
    (estratti in scrape_vinted_listing) fino a build_vinted_search_url,
    per la ricerca comp Vinted raffinata su categoria+materiale."""
    query_base = f"{brand} {modello} {categoria}".strip()
    if not query_base or query_base.lower() in ("nessuno", "non disponibile", ""):
        return "RICERCA WEB: non eseguita, brand/modello non identificabile con sufficiente certezza dal JSON visivo."

    results_by_label, vinted_e_per_id = _esegui_ricerca_serper_completa(
        brand, modello, categoria, query_base,
        catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
    )

    fallimento_totale = all(
        any(marker in v for marker in ("Nessun risultato", "fallita", "non completata", "fallito"))
        for v in results_by_label.values()
    )

    nota_fallback = ""
    if fallimento_totale and modello:
        query_larga = f"{brand} {categoria}".strip()
        log.warning(
            "Ricerca specifica '%s' fallita su TUTTE le fonti -- ritento con query larga '%s'.",
            query_base, query_larga,
        )
        results_by_label, vinted_e_per_id = _esegui_ricerca_serper_completa(
            brand, "", categoria, query_larga,
            catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
        )
        query_base = query_larga
        nota_fallback = (
            "⚠️ Nota: la ricerca specifica (con modello dettagliato) non ha dato risultati su nessuna "
            "fonte -- questi sono risultati di una ricerca PIÙ AMPIA (solo brand+categoria), quindi "
            "meno specifici per il modello esatto: usa confidenza Bassa per qualsiasi comp da qui."
        )
        fallimento_totale = all(
            any(marker in v for marker in ("Nessun risultato", "fallita", "non completata", "fallito"))
            for v in results_by_label.values()
        )

    if fallimento_totale:
        return (
            "RICERCA WEB: eseguita su 5 fonti (eBay sold, Vestiaire, Vinted, Google generico x2), "
            "inclusa una query di fallback più ampia, ma NESSUNA ha prodotto risultati utili. "
            "Nessun comp disponibile -- applica confidenza Bassa e non inventare prezzi a memoria."
        )

    serper_queries_labels = [
        "VESTIAIRE COLLECTIVE", "GOOGLE GENERICO (prezzo/valore)", "GOOGLE GENERICO (retail originale)",
    ]
    all_labels = serper_queries_labels + ["VINTED (scrape diretto)", "EBAY SOLD (scrape diretto)"]
    lines = [f"RICERCA WEB (5 fonti, base: '{query_base}'):"]
    if nota_fallback:
        lines.append(nota_fallback)
    if not vinted_e_per_id:
        lines.append(
            "⚠️ Nota: il brand non è nella mappa brand_id Vinted, la ricerca Vinted "
            "sotto usa solo testo libero (search_text) -- meno precisa, può includere "
            "falsi positivi di altri brand che menzionano questo nome nel titolo."
        )
    for label in all_labels:
        lines.append(f"\n📍 FONTE: {label}")
        lines.append(results_by_label.get(label, "  (risultato mancante)"))

    return "\n".join(lines)


def call_claude_oracle(listing_info, gemini_analysis_json):
    age_days = listing_info.get("age_days")
    if age_days is not None:
        age_text = f"{age_days:.1f} giorni fa"
    else:
        age_text = "non disponibile (probabile fallimento scraping data pubblicazione)"

    gemini_analysis_for_claude = strip_per_photo_analysis(gemini_analysis_json)

    # RICERCA WEB ESTERNA (Serper, non tool integrato Claude): estraggo
    # brand/modello/categoria dal JSON Gemini originale (non filtrato) per
    # costruire la query di ricerca, poi inietto i risultati come testo nel
    # messaggio. Questo sostituisce il tool web_search_20250305: niente piu'
    # server tool = niente piu' scritture extra di cache per iterazione del
    # loop agentico (causa identificata del costo elevato in produzione).
    try:
        gemini_data = json.loads(gemini_analysis_json)
        ident = gemini_data.get("identificazione", {}) if isinstance(gemini_data, dict) else {}
        brand_per_ricerca = (
            ident.get("brand_effettivamente_visibile_sui_loghi")
            or ident.get("brand_dichiarato_dal_venditore")
            or listing_info.get("brand")
            or ""
        )

        # QUERY IDEALE: se Gemini ha fornito una query di ricerca gia'
        # ottimizzata (breve, con le parole che un venditore reale
        # userebbe), la usiamo al posto della concatenazione grezza
        # modello+categoria -- piu' probabile che produca risultati
        # utili su Google/eBay/Vinted (vedi note nel prompt Gemini).
        # SAFETY CHECK: ignoriamo la query ideale se e' sospettosamente
        # lunga (oltre 8 parole) -- segno che Gemini non ha rispettato
        # il vincolo "max 5-6 parole" nonostante l'istruzione, nel qual
        # caso il fallback alla logica precedente e' piu' sicuro.
        query_ideale = (ident.get("query_di_ricerca_ideale") or "").strip()
        if query_ideale and len(query_ideale.split()) <= 8:
            # EVITA DUPLICAZIONE BRAND: query_di_ricerca_ideale spesso
            # include già il brand al suo interno (es. "M Missoni top
            # lurex"), ma brand_per_ricerca viene ri-concatenato davanti
            # in search_comps_serper (per il lookup brand_id di Vinted,
            # che richiede il brand come parametro separato) -- senza
            # questa pulizia la query finale duplicherebbe il brand
            # (es. "M Missoni M Missoni top lurex"). Rimuoviamo qui le
            # parole del brand dalla query ideale, lasciando solo il
            # resto (es. "top lurex") come modello_per_ricerca.
            modello_per_ricerca = query_ideale
            if brand_per_ricerca:
                # RIMOZIONE ROBUSTA PAROLA-PER-PAROLA: un confronto esatto
                # della stringa brand (es. re.escape + sub) fallisce quando
                # Gemini scrive il brand in modo leggermente diverso tra
                # "identificazione.brand_effettivamente_visibile_sui_loghi"
                # e dentro "query_di_ricerca_ideale" -- visto in produzione
                # un caso reale dove il primo era "Jean's Paul Gaultier" e
                # il secondo "Jeans Paul Gaultier" (apostrofo presente vs
                # assente): il match esatto non scattava, la rimozione non
                # avveniva, e la query finale duplicava il brand per intero
                # ("Jean's Paul Gaultier Jeans Paul Gaultier gonna righe").
                # Qui normalizziamo togliendo punteggiatura (apostrofi,
                # trattini) da ENTRAMBE le stringhe prima di confrontare
                # parola per parola, cosi' "Jean's" e "Jeans" vengono
                # riconosciuti come la stessa parola e rimossi correttamente.
                def _normalizza_parola(w):
                    return re.sub(r"[''\-.,]", "", w).lower()

                parole_brand_normalizzate = {
                    _normalizza_parola(w) for w in brand_per_ricerca.split()
                }
                parole_query = modello_per_ricerca.split()
                parole_residue = [
                    w for w in parole_query
                    if _normalizza_parola(w) not in parole_brand_normalizzate
                ]
                modello_per_ricerca = " ".join(parole_residue).strip()
            categoria_per_ricerca = ""  # già incluso nella query ideale, evita duplicazione
            log.info(
                "Uso query_di_ricerca_ideale da Gemini: '%s' (brand rimosso, resto: '%s')",
                query_ideale, modello_per_ricerca,
            )
        else:
            if query_ideale:
                log.warning(
                    "query_di_ricerca_ideale scartata (troppo lunga, %d parole): '%s' -- fallback a modello+categoria.",
                    len(query_ideale.split()), query_ideale,
                )
            modello_per_ricerca = ident.get("modello_stimato") or ""
            categoria_per_ricerca = ident.get("categoria") or ""
    except (json.JSONDecodeError, ValueError, TypeError):
        brand_per_ricerca = listing_info.get("brand") or ""
        modello_per_ricerca = ""
        categoria_per_ricerca = ""

    comps_text = search_comps_serper(
        brand_per_ricerca, modello_per_ricerca, categoria_per_ricerca,
        catalog_id=listing_info.get("catalog_id"),
        material_per_ricerca=listing_info.get("material_per_ricerca"),
    )
    log.info("RICERCA SERPER:\n%s", comps_text)

    user_text = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto dal venditore: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Materiale (da pagina annuncio): {listing_info.get('material_raw') or 'non disponibile'}\n"
        f"Colore (da pagina annuncio): {listing_info.get('color_raw') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"Annuncio pubblicato: {age_text}\n"
        f"URL annuncio: {listing_info.get('url') or 'non disponibile'}\n\n"
        "--- ANALISI VISIVA COMPLETA (JSON prodotto da Gemini dopo aver esaminato\n"
        "tutte le foto dell'annuncio) ---\n"
        f"{gemini_analysis_for_claude}\n"
        "--- FINE ANALISI VISIVA ---\n\n"
        "NOTA: non hai accesso diretto alle foto originali. Il JSON sopra è la "
        "tua UNICA fonte visiva, prodotta da un modello che ha esaminato tutte "
        "le immagini in dettaglio, incluso ogni logo/marchio visibile separatamente. "
        "Fidati di questo JSON per identificazione, condizione e legit check visivo, "
        "ma applica il tuo giudizio critico: se il JSON segnala una incongruenza "
        "(es. un logo non coerente con il brand dichiarato), trattala come un "
        "segnale di rischio serio nel tuo legit check, non ignorarla.\n\n"
        "--- RISULTATI RICERCA WEB (gia' eseguita per te, non hai un tool di ricerca:\n"
        "questi sono gli UNICI dati di mercato disponibili, usali per stimare i comps) ---\n"
        f"{comps_text}\n"
        "--- FINE RISULTATI RICERCA WEB ---\n\n"
        "Produci ora il verdetto operativo completo, nel formato compatto richiesto."
    )

    log.info(
        "PROMPT TESTUALE -> CLAUDE (nessuna immagine, JSON Gemini filtrato + comps Serper) -- "
        "lunghezza totale: %d caratteri (contenuto completo già visibile separatamente in "
        "RISPOSTA GEMINI e RICERCA SERPER sopra; qui solo anteprima per evitare di superare "
        "il rate limit di log di Railway):\n%s%s",
        len(user_text),
        user_text[:600],
        "... [troncato]" if len(user_text) > 600 else "",
    )

    content = [{"type": "text", "text": user_text}]

    # PROMPT CACHING: il system prompt (VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT)
    # e' enorme e identico ad ogni chiamata -- senza caching, ogni singola
    # valutazione paga per intero la lettura di tutte le regole (matrice
    # decisionale, regole su diffusion line, ecc). Con cache_control,
    # Anthropic salva il prompt per ~5 minuti: la prima chiamata in quella
    # finestra paga il prezzo "cache write" (poco piu' caro del normale),
    # le chiamate successive entro 5 minuti pagano solo ~10% del costo
    # normale per quei token. Per un bot che riceve notifiche a raffica
    # (piu' annunci nello stesso minuto, come visto nei log reali) questo
    # taglia drasticamente il costo medio per valutazione.
    #
    # NESSUN "tools" qui: la ricerca web e' ora fatta da search_comps_serper()
    # PRIMA di questa chiamata, e i risultati sono gia' dentro user_text.
    # Senza server tools, questa e' un'unica chiamata Claude (non un loop
    # agentico), quindi il caching sul system prompt funziona pienamente
    # senza le scritture extra di cache_creation per iterazione viste prima.
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1200,
        "system": [
            {
                "type": "text",
                "text": VINTED_FLIP_ORACLE_PRO_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": content}],
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

    # Log delle statistiche di cache per monitorare l'efficacia nel tempo:
    # cache_read_input_tokens alto = stiamo risparmiando; cache_creation
    # alto e cache_read basso = la finestra di 5 minuti scade troppo spesso
    # tra una notifica e l'altra (bot poco attivo) e il caching aiuta meno.
    usage = data.get("usage", {})
    log.info(
        "CLAUDE usage -- input: %s, cache_read: %s, cache_creation: %s, output: %s",
        usage.get("input_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cache_creation_input_tokens"),
        usage.get("output_tokens"),
    )

    # text_blocks puo' contenere piu' di un blocco se Claude ha alternato
    # scrittura e ricerca web: li concateniamo senza separatore aggiuntivo
    # (join vuoto, non "\n") perche' un blocco potrebbe finire e l'altro
    # iniziare a meta' della stessa riga markdown -- inserire un \n tra
    # i due peggiorerebbe la leggibilita' anche nel caso "buono".
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    final_text = "".join(text_blocks) if text_blocks else "[Nessun testo restituito da Claude]"

    # FIX ATTIVO (non solo log): se Claude ha scritto testo prima di
    # "## Verdetto operativo" -- es. un "Sintesi dati raccolti prima di
    # scrivere il verdetto:" o note di ricerca -- nonostante il vincolo
    # nel prompt, tagliamo via tutto cio' che precede il marcatore prima
    # di mandarlo a Telegram. Meglio perdere un'eventuale premessa
    # innocua che spedire all'utente un report con un riepilogo grezzo
    # di ricerca prima del formato compatto richiesto.
    verdetto_pos = final_text.find("## Verdetto operativo")
    if verdetto_pos > 0:
        testo_scartato = final_text[:verdetto_pos].strip()
        log.warning(
            "Testo PRIMA di '## Verdetto operativo' rilevato e scartato (%d caratteri). "
            "Il prompt vieta questo, ma Claude lo ha scritto comunque -- testo scartato:\n%s",
            len(testo_scartato), testo_scartato[:500],
        )
        final_text = final_text[verdetto_pos:]
    elif verdetto_pos == -1:
        log.error(
            "Marcatore '## Verdetto operativo' assente dal report Claude -- "
            "il messaggio verra' inviato cosi' com'e', probabilmente malformato. "
            "Testo completo:\n%s",
            final_text,
        )

    # CONTROLLO DI SANITA' SULL'ORDINE: se nonostante il vincolo nel
    # prompt Claude ha comunque alternato scrittura/ricerca, il report
    # arriva con i campi fuori sequenza (es. "## Da chiedere" prima di
    # "## Legit check", o "In una riga" prima di "Decisione"). Lo
    # logghiamo come errore per accorgercene, ma NON blocchiamo l'invio:
    # un report con ordine sbagliato e' comunque meglio di nessun report.
    if len(text_blocks) > 1:
        log.warning(
            "Claude ha prodotto %d blocchi di testo separati (probabile alternanza "
            "scrittura/ricerca web) -- rischio report con campi fuori ordine.",
            len(text_blocks),
        )

    expected_order = ["## Verdetto operativo", "## Legit check", "## Da chiedere", "## Messaggio da inviare"]
    positions = [final_text.find(marker) for marker in expected_order]
    if all(p != -1 for p in positions) and positions != sorted(positions):
        log.error(
            "ORDINE SEZIONI ANOMALO nel report Claude (posizioni trovate: %s per %s) "
            "-- il messaggio inviato a Telegram potrebbe avere campi mischiati. "
            "Testo completo per debug:\n%s",
            positions, expected_order, final_text,
        )

    # CONTROLLO CORRETTIVO SU MARGINE-SOGLIA vs DECISIONE: se il testo
    # contiene una frase tipo "sotto soglia" (il modello stesso lo scrive
    # quando applica correttamente la regola dei 20 euro nel ragionamento)
    # ma la riga "Decisione" contiene comunque un livello COMPRA, e' la
    # stessa contraddizione vista nei casi reali "Mission Minikleid" e
    # "Blouse Marni x Uniqlo" (margine sotto soglia dichiarato esplicita-
    # mente, ma decisione COMPRA SE CI TIENI). Il solo logging non basta
    # piu': qui CORREGGIAMO attivamente la riga Decisione prima dell'invio.
    #
    # Logica di correzione: se il margine scontato (se disponibile nel
    # testo) potrebbe ragionevolmente superare la soglia trattando,
    # forziamo TRATTA FORTE; altrimenti NON COMPRARE. Non potendo fare
    # un parsing robusto del margine scontato in tutti i formati possibili,
    # usiamo un'euristica semplice: se il testo menziona "Costo pieno
    # trattato" con un valore numerico (non "N/A"), assumiamo che trattare
    # sia ancora un'opzione percorribile -> TRATTA FORTE. Se invece il
    # costo trattato e' N/A o il margine e' negativo/quasi nullo, forziamo
    # NON COMPRARE direttamente.
    decisione_match = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", final_text)
    decisione_text = decisione_match.group(1) if decisione_match else ""
    ha_livello_compra = bool(re.search(r"\bCOMPRA\b", decisione_text))
    margine_sotto_soglia_dichiarato = bool(
        re.search(r"sotto\s+soglia", final_text, re.IGNORECASE)
    )

    if ha_livello_compra and margine_sotto_soglia_dichiarato:
        costo_trattato_match = re.search(
            r"\*\*Costo pieno trattato:\*\*\s*(N/A|€[\d.,]+)", final_text, re.IGNORECASE
        )
        costo_trattato_valido = bool(
            costo_trattato_match and costo_trattato_match.group(1).upper() != "N/A"
        )

        nuova_decisione = "TRATTA FORTE" if costo_trattato_valido else "NON COMPRARE"

        # Mantieni l'urgenza originale se presente (es. "· HAI QUALCHE ORA"),
        # ma se la nuova decisione è NON COMPRARE l'urgenza non ha senso (vedi
        # regola nel prompt) quindi la sostituiamo con N/A.
        urgenza_match = re.search(r"·\s*([^\n]+)$", decisione_text.strip())
        urgenza_originale = urgenza_match.group(1).strip() if urgenza_match else None
        if nuova_decisione == "NON COMPRARE":
            decisione_corretta = "NON COMPRARE · N/A"
        elif urgenza_originale:
            decisione_corretta = f"{nuova_decisione} · {urgenza_originale}"
        else:
            decisione_corretta = nuova_decisione

        log.error(
            "CONTRADDIZIONE MARGINE/DECISIONE corretta automaticamente: "
            "Decisione originale '%s' -> corretta in '%s' (margine sotto soglia "
            "dichiarato nel testo, costo trattato %s). Report originale per debug:\n%s",
            decisione_text.strip(), decisione_corretta,
            "valido" if costo_trattato_valido else "N/A o assente", final_text,
        )

        final_text = re.sub(
            r"(\*\*Decisione:\*\*\s*)[^\n]+",
            r"\1" + decisione_corretta + " ⚠️ _(corretto automaticamente: margine sotto soglia)_",
            final_text,
            count=1,
        )

    # CONTROLLO CORRETTIVO SU "COMPRA SUBITO" + CONFIDENZA BASSA: la
    # regola della matrice qualita' richiede esplicitamente "Confidenza
    # non Bassa" per il livello COMPRA SUBITO (insieme a Deal 9-10,
    # Margine 8-10, Rischio non ALTO) -- visto in produzione un caso
    # reale (giacca Gaultier Jean's, margine 92-122EUR stimato da un
    # singolo comp ask non-sold) dove Claude scrive "Confidenza: Bassa"
    # nella stessa riga Deal/Margine/Liquidita'/Rischio/Confidenza e
    # comunque assegna COMPRA SUBITO -- la stessa famiglia di errore
    # del controllo sopra (decisione che contraddice un valore scritto
    # nello stesso report), ma su un asse diverso (confidenza, non
    # margine). Qui retrocediamo a COMPRA FORTE, il livello immediata-
    # mente sotto nella matrice, che non ha il vincolo di confidenza.
    decisione_match_2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", final_text)
    decisione_text_2 = decisione_match_2.group(1) if decisione_match_2 else ""
    e_compra_subito = "COMPRA SUBITO" in decisione_text_2
    confidenza_bassa_dichiarata = bool(
        re.search(r"\*\*Confidenza:\*\*\s*Bassa", final_text, re.IGNORECASE)
    )

    if e_compra_subito and confidenza_bassa_dichiarata:
        urgenza_match_2 = re.search(r"·\s*([^\n⚠️]+)", decisione_text_2.strip())
        urgenza_originale_2 = urgenza_match_2.group(1).strip() if urgenza_match_2 else "HAI QUALCHE ORA"
        decisione_corretta_2 = f"COMPRA FORTE · {urgenza_originale_2}"

        log.error(
            "CONTRADDIZIONE COMPRA SUBITO/CONFIDENZA BASSA corretta automaticamente: "
            "Decisione originale '%s' -> corretta in '%s' (la regola COMPRA SUBITO "
            "richiede Confidenza non Bassa, qui dichiarata Bassa). Report originale "
            "per debug:\n%s",
            decisione_text_2.strip(), decisione_corretta_2, final_text,
        )

        final_text = re.sub(
            r"(\*\*Decisione:\*\*\s*)[^\n]+",
            r"\1" + decisione_corretta_2 + " ⚠️ _(corretto automaticamente: COMPRA SUBITO richiede confidenza non Bassa)_",
            final_text,
            count=1,
        )

    # CONTROLLO CORRETTIVO SU ROI SOTTO SOGLIA 100% + DECISIONE COMPRA: la
    # soglia ROI minimo 100% (vedi prompt) e' un secondo gate INDIPENDENTE
    # dalla soglia margine assoluto 20€ -- un margine € alto con ROI basso
    # non e' un COMPRA, anche se il primo controllo correttivo sopra (sulla
    # soglia 20€) non si attiva perche' il margine assoluto e' comunque
    # sopra soglia. Visto in produzione un caso reale (blazer Max Mara,
    # margine €22-27 su costo pieno €48,04, ROI ~46-56%, Deal 6/10, Margine
    # 5/10, Rischio BASSO) dove Claude assegna COMPRA perche' la matrice
    # qualita' guarda solo Deal/Margine in punti (che misurano l'ampiezza
    # assoluta in €), mai il ROI% in modo vincolante.
    #
    # Estrazione ROI: cerchiamo il primo "ROI ~NN%" o "ROI NN%" nella riga
    # "Margine netto" (formato atteso: "€X (ROI Y%) — richiesto · trattato").
    # Se il testo riporta un range (es. "ROI ~46-56%"), prendiamo il valore
    # PIU' ALTO del range per dare a Claude il beneficio del dubbio --
    # vogliamo correggere solo i casi in cui anche l'estremo piu' favorevole
    # resta sotto soglia, non i casi limite dove il range attraversa 100%.
    decisione_match_3 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", final_text)
    decisione_text_3 = decisione_match_3.group(1) if decisione_match_3 else ""
    ha_livello_compra_3 = bool(re.search(r"\bCOMPRA\b", decisione_text_3))

    roi_match = re.search(r"ROI\s*~?\s*(\d+)(?:[-–](\d+))?\s*%", final_text, re.IGNORECASE)
    roi_massimo_dichiarato = None
    if roi_match:
        valori_roi = [int(roi_match.group(1))]
        if roi_match.group(2):
            valori_roi.append(int(roi_match.group(2)))
        roi_massimo_dichiarato = max(valori_roi)

    SOGLIA_ROI_MINIMO = 100

    if ha_livello_compra_3 and roi_massimo_dichiarato is not None and roi_massimo_dichiarato < SOGLIA_ROI_MINIMO:
        costo_trattato_match_3 = re.search(
            r"\*\*Costo pieno trattato:\*\*\s*(N/A|€[\d.,]+)", final_text, re.IGNORECASE
        )
        costo_trattato_valido_3 = bool(
            costo_trattato_match_3 and costo_trattato_match_3.group(1).upper() != "N/A"
        )
        nuova_decisione_3 = "TRATTA FORTE" if costo_trattato_valido_3 else "NON COMPRARE"

        urgenza_match_3 = re.search(r"·\s*([^\n⚠️]+)", decisione_text_3.strip())
        urgenza_originale_3 = urgenza_match_3.group(1).strip() if urgenza_match_3 else None
        if nuova_decisione_3 == "NON COMPRARE":
            decisione_corretta_3 = "NON COMPRARE · N/A"
        elif urgenza_originale_3:
            decisione_corretta_3 = f"{nuova_decisione_3} · {urgenza_originale_3}"
        else:
            decisione_corretta_3 = nuova_decisione_3

        log.error(
            "CONTRADDIZIONE ROI/DECISIONE corretta automaticamente: "
            "Decisione originale '%s' -> corretta in '%s' (ROI massimo dichiarato "
            "%d%% sotto soglia %d%%, costo trattato %s). Report originale per debug:\n%s",
            decisione_text_3.strip(), decisione_corretta_3, roi_massimo_dichiarato,
            SOGLIA_ROI_MINIMO,
            "valido" if costo_trattato_valido_3 else "N/A o assente", final_text,
        )

        final_text = re.sub(
            r"(\*\*Decisione:\*\*\s*)[^\n]+",
            r"\1" + decisione_corretta_3 + " ⚠️ _(corretto automaticamente: ROI sotto soglia 100%)_",
            final_text,
            count=1,
        )

    return final_text


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE PER UN SINGOLO ANNUNCIO
# ---------------------------------------------------------------------------

def _stima_costo_pieno_da_prezzo_e_lingua(prezzo_richiesto_str, titolo, descrizione):
    """Stima il costo pieno d'acquisto (prezzo + protezione acquirenti +
    spedizione) usando la stessa euristica di lingua->spedizione che il
    prompt Claude applica normalmente (IT 2,50€, FR/ES/PT 4,50€, DE/NL/
    nord-centro EU 5-6€), qui replicata in Python per il filtro pre-Claude
    a costo zero. Una stima volutamente approssimativa -- usata solo per
    decidere se skippare, non per il verdetto finale (quello lo fa sempre
    Claude con piu' contesto, quando arriva a vederlo).

    Rileva la lingua in modo grezzo (poche parole-chiave comuni nei titoli
    Vinted di quei paesi) -- non e' un rilevatore linguistico serio, e non
    deve esserlo: se sbaglia paese, la spedizione stimata e' comunque nello
    stesso ordine di grandezza (2,50-6€), l'errore massimo e' ~3,50€ sul
    costo pieno, che non sposta in modo decisivo la soglia di 20€ netti.

    Ritorna None se il prezzo richiesto non e' un numero valido (non
    possiamo stimare nulla senza un prezzo di partenza)."""
    try:
        prezzo = float(str(prezzo_richiesto_str).replace(",", "."))
    except (TypeError, ValueError):
        return None

    testo = f"{titolo or ''} {descrizione or ''}".lower()
    spedizione_stimata = 2.50  # default IT, la lingua piu' comune nel tuo caso d'uso
    indicatori_non_it = (
        " la ", " et ", " avec ", " une ", " talle ", " size ", " größe ",
        " und ", " met ", " con la ", " der ", " die ", " das ",
    )
    if any(ind in testo for ind in indicatori_non_it):
        spedizione_stimata = 4.50  # FR/ES/PT/altre EU come approssimazione unica

    protezione_acquirenti = round(prezzo * 0.05 + 0.70, 2)
    costo_pieno = round(prezzo + protezione_acquirenti + spedizione_stimata, 2)
    return costo_pieno


def check_skip_pre_claude(gemini_analysis_json, listing_info=None):
    """Controllo a COSTO ZERO (nessuna chiamata API) sul JSON gia' ottenuto
    da Gemini: se uno di QUATTRO segnali distinti indica chiaramente che non
    vale la pena procedere, skippiamo la chiamata Claude (la voce di
    costo piu' alta della pipeline) e rispondiamo subito con NON COMPRARE.

    I quattro segnali, controllati in ordine:
    1. Falso conclamato: legit check "Probabilmente falso" + confidenza
       >=90% + rischio "molto alto".
    2. Categoria a basso valore strutturale (es. calzini, intimo) --
       campo dedicato compilato da Gemini stesso nel prompt.
    3. Verdetto grezzo di Gemini "NON COMPRARE" -- un giudizio preliminare
       intenzionalmente approssimativo che Gemini fa basandosi solo sulla
       foto, senza ricerca prezzi.
    4. Margine insufficiente ANCHE nello scenario migliore: Gemini stima
       un prezzo_vendita_massimo_plausibile_eur (deliberatamente generoso,
       il MIGLIOR caso possibile secondo la sua conoscenza generale, non
       una media) -- se anche quel numero, confrontato col costo pieno
       d'acquisto stimato, non supera la soglia di margine, allora nessuna
       ricerca comp potrebbe salvare il deal: Claude con dati reali
       arriverebbe quasi certamente alla stessa identica conclusione di
       NON COMPRARE, partendo da un'ipotesi gia' piu' favorevole di
       qualsiasi comp reale.

    ASIMMETRIA DELIBERATA SUL SEGNALE 4 (importante, NON rimuovere questa
    nota se si modifica la logica): Gemini e' sistematicamente PIU'
    GENEROSO di Claude nelle stime di prezzo (osservato dall'utente sui
    report reali) -- per questo il segnale 4 e' usato SOLO per SCARTARE
    (quando anche la stima generosa dice "non basta"), mai per CONFERMARE.
    Il bias di Gemini verso l'alto gioca A FAVORE della sicurezza qui: se
    anche essendo generoso il margine non c'e', e' un segnale quasi certo.
    Il contrario (usare la stima di Gemini per dire "compra") sarebbe
    invece pericoloso, perche' il bias lavorerebbe contro la sicurezza --
    e' per questo che questo segnale NON esiste nella direzione opposta,
    e non va aggiunto in futuro senza ripensare l'intera asimmetria.

    listing_info: necessario SOLO per il segnale 4 (serve il prezzo
    richiesto dal venditore, non presente nel JSON di Gemini). Se None o
    senza prezzo valido, il segnale 4 viene semplicemente saltato -- gli
    altri tre restano validi e indipendenti.

    Questo NON sostituisce il giudizio di Claude sui casi dubbi -- e'
    deliberatamente conservativo su ciascun segnale: un falso negativo
    (non skippare un caso ovvio) costa solo la chiamata Claude risparmiata;
    un falso positivo (skippare un deal valido) costerebbe un margine
    perso, molto piu' caro. Per questo i criteri di ciascun segnale sono
    stretti, anche se i quattro segnali tra loro sono in OR (basta che
    scatti uno per skippare).

    Ritorna (True, motivo) se va skippato, (False, None) altrimenti."""
    try:
        data = json.loads(gemini_analysis_json)
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None

    if not isinstance(data, dict):
        return False, None

    legit = data.get("legit_check_preliminare", {})
    if not isinstance(legit, dict):
        legit = {}

    verdetto_legit = (legit.get("verdetto") or "").strip().lower()
    confidenza_raw = str(legit.get("confidenza_percentuale") or "0")
    confidenza_match = re.search(r"(\d+)", confidenza_raw)
    confidenza = int(confidenza_match.group(1)) if confidenza_match else 0
    rischio = (legit.get("rischio_fake_qualitativo") or "").strip().lower()

    # SEGNALE 1: falso conclamato (criteri stretti, tutti e tre insieme)
    e_falso_evidente = (
        verdetto_legit == "probabilmente falso"
        and confidenza >= 90
        and rischio == "molto alto"
    )
    if e_falso_evidente:
        motivo = legit.get("cosa_non_torna_o_e_dubbio") or "Falso conclamato dall'analisi visiva."
        return True, f"[FALSO CONCLAMATO] {motivo}"

    # SEGNALE 2 e 3: dal campo dedicato valutazione_flipper_preliminare
    valutazione = data.get("valutazione_flipper_preliminare", {})
    if isinstance(valutazione, dict):
        if valutazione.get("categoria_a_basso_valore") is True:
            motivo = valutazione.get("motivo_se_basso_valore") or "Categoria a basso valore strutturale (es. calzini, intimo)."
            return True, f"[CATEGORIA BASSO VALORE] {motivo}"

        verdetto_grezzo = (valutazione.get("verdetto_grezzo") or "").strip().upper()
        if verdetto_grezzo == "NON COMPRARE":
            motivo = valutazione.get("motivo_verdetto_grezzo") or "Verdetto preliminare negativo da Gemini."
            return True, f"[VERDETTO GREZZO GEMINI] {motivo}"

        # SEGNALE 4: margine insufficiente anche nel miglior caso secondo Gemini.
        prezzo_massimo_raw = valutazione.get("prezzo_vendita_massimo_plausibile_eur")
        if prezzo_massimo_raw is not None and listing_info is not None:
            try:
                prezzo_massimo_gemini = float(str(prezzo_massimo_raw).replace(",", "."))
            except (TypeError, ValueError):
                prezzo_massimo_gemini = None

            if prezzo_massimo_gemini is not None:
                costo_pieno = _stima_costo_pieno_da_prezzo_e_lingua(
                    listing_info.get("price"),
                    listing_info.get("title"),
                    listing_info.get("description"),
                )
                if costo_pieno is not None:
                    margine_nello_scenario_migliore = prezzo_massimo_gemini - costo_pieno
                    SOGLIA_MARGINE_EUR = 20  # stessa soglia usata da Claude nel prompt
                    if margine_nello_scenario_migliore < SOGLIA_MARGINE_EUR:
                        motivo = (
                            f"Anche nello scenario di rivendita più favorevole "
                            f"(~€{prezzo_massimo_gemini:.0f}, stima generosa Gemini), "
                            f"margine netto stimato €{margine_nello_scenario_migliore:.0f} "
                            f"sotto soglia €{SOGLIA_MARGINE_EUR} (costo pieno ~€{costo_pieno:.2f})."
                        )
                        return True, f"[MARGINE INSUFFICIENTE ANCHE NEL MIGLIOR CASO] {motivo}"

    return False, None


def build_skip_report(listing_info, motivo_skip):
    """Costruisce un report NON COMPRARE nello stesso formato compatto
    usato da Claude, senza fare alcuna chiamata API. Usato quando
    check_skip_pre_claude() rileva un caso chiaro.

    Il testo della sezione "Legit check" si adatta al TIPO di segnale che
    ha attivato lo skip (riconosciuto dal prefisso tra parentesi quadre in
    motivo_skip, impostato da check_skip_pre_claude) -- un margine
    insufficiente non è un problema di autenticità, e il report non deve
    suggerire il contrario."""
    e_segnale_margine = motivo_skip.startswith("[MARGINE INSUFFICIENTE")

    if e_segnale_margine:
        riga_legit_check = (
            "Non valutato — filtro pre-Claude attivato su margine insufficiente "
            "(non un problema di autenticità), risparmio costi."
        )
        riga_rischio = "BASSO — margine insufficiente anche nel miglior caso (filtro automatico, Claude non consultato)"
    else:
        riga_legit_check = (
            "Probabilmente falso — rilevato da Gemini con confidenza ≥90%, "
            "filtro automatico pre-Claude attivato per risparmio costi."
        )
        riga_rischio = "ALTO — falso conclamato (filtro automatico, Claude non consultato)"

    motivo_breve = motivo_skip[:117].rsplit(" ", 1)[0] + "..." if len(motivo_skip) > 120 else motivo_skip

    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — filtro automatico pre-Claude\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        "- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidità:** Bassa · "
        f"**Rischio:** {riga_rischio} · "
        "**Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        "## Legit check\n"
        f"{riga_legit_check}\n\n"
        "## Da chiedere\n"
        "Non rilevante: filtro automatico pre-Claude attivato.\n\n"
        "## Messaggio da inviare\n"
        "Non necessario."
    )


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
        listing_info["age_days"] = scraped.get("age_days")
        listing_info["catalog_id"] = scraped.get("catalog_id")
        listing_info["material_raw"] = scraped.get("material_raw")
        listing_info["material_per_ricerca"] = scraped.get("material_per_ricerca")
        listing_info["color_raw"] = scraped.get("color_raw")

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

    # FILTRO PRE-CLAUDE A COSTO ZERO: se Gemini ha gia' rilevato un segnale
    # chiaro (falso conclamato, categoria a basso valore, o verdetto grezzo
    # negativo), skippiamo la chiamata Claude (la voce di costo piu' alta
    # della pipeline) e rispondiamo direttamente.
    e_skip, motivo_skip = check_skip_pre_claude(gemini_analysis_json, listing_info=listing_info)
    if e_skip:
        log.info(
            "FILTRO PRE-CLAUDE ATTIVATO: Claude NON consultato per questo "
            "annuncio. Motivo: %s",
            motivo_skip,
        )
        final_report = build_skip_report(listing_info, motivo_skip)
    else:
        final_report = call_claude_oracle(listing_info, gemini_analysis_json)

    # VERIFICA DIRETTA DEL CONTENUTO IN MEMORIA: stampiamo un hash e la
    # lunghezza del testo PRIMA di qualsiasi altra cosa, con marcatori
    # espliciti di inizio/fine. Se Railway interlaccia le righe per
    # colpa della sua UI di aggregazione log (come sospettato), questa
    # riga lo confermerebbe comunque, perche' l'hash e la lunghezza sono
    # calcolati su una stringa Python gia' assemblata in memoria, non su
    # come il testo viene poi visualizzato. Se invece il problema e' nei
    # dati (Claude ha davvero scritto i campi fuori ordine), il blocco
    # "===REPORT VERBATIM START===...END===" mostrera' lo stesso identico
    # disordine che vedresti su Telegram, perche' e' un singolo argomento
    # %s passato a log.info -- Railway non puo' "rimescolare" il
    # contenuto di una stringa che gli arriva gia' completa su una riga
    # di stdout (puo' al massimo interlacciare RIGHE diverse tra loro,
    # non il contenuto interno di una singola chiamata di log).
    report_hash = hashlib.md5(final_report.encode()).hexdigest()[:12]
    log.info(
        "VERIFICA REPORT -- lunghezza: %d caratteri, hash: %s, righe: %d",
        len(final_report), report_hash, final_report.count("\n") + 1,
    )
    log.info("===REPORT VERBATIM START (hash %s)===\n%s\n===REPORT VERBATIM END (hash %s)===",
              report_hash, final_report, report_hash)

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

# DEDUPLICAZIONE MESSAGGI: osservato in produzione che lo stesso annuncio
# (stesso message_id) puo' generare DUE eventi NewMessage a distanza di
# meno di 1 secondo -- causa probabile: il bot "Vinted Tracker" modifica
# il proprio messaggio dopo l'invio iniziale (es. aggiunge il bottone con
# l'URL in un secondo momento), e Telethon emette un evento NewMessage
# anche per quell'edit, oppure ci sono piu' "getUpdates" che si sovrap-
# pongono. L'effetto e' GRAVE: stesso annuncio elaborato due volte in
# parallelo, doppio costo Gemini+Serper+Claude, e nei casi osservati
# persino DUE VERDETTI DIVERSI per lo stesso capo (es. "NON COMPRARE" e
# "CHIEDI ALTRE FOTO" sullo stesso identico Top Missoni), che e' confuso
# e potenzialmente dannoso se l'utente agisce sul verdetto sbagliato.
#
# Fix: manteniamo un set dei message_id gia' elaborati (con scadenza
# implicita via dimensione massima, per non crescere all'infinito in un
# processo long-running) e scartiamo silenziosamente i duplicati.
_processed_message_ids = set()
_MAX_PROCESSED_IDS_TRACKED = 500  # tetto per evitare crescita illimitata della memoria


# DEDUPLICAZIONE PER CONTENUTO (stesso oggetto, taglie diverse): un secondo
# problema distinto da quello sopra -- osservato in produzione che lo
# stesso venditore pubblica spesso lo STESSO capo in piu' annunci separati,
# uno per taglia disponibile (es. "Miu Miu short sleeves Talle S/M/L/XL/
# XXL"), ognuno con message_id LEGITTIMAMENTE diverso (sono annunci Vinted
# reali e distinti), stesso titolo/brand/prezzo tranne l'ultima parola
# (la taglia). Il dedup sopra (per message_id) non li intercetta, e il
# bot finisce per valutare 5 volte lo stesso identico capo nel giro di
# pochi secondi -- 5x costo Gemini+Serper+Claude per un'informazione che
# la prima valutazione gia' dava (stesso brand, stesso prezzo, stesso
# margine: la taglia diversa non cambia la decisione economica).
#
# Fix: una seconda chiave di dedup basata sul CONTENUTO (titolo con la
# taglia finale rimossa + brand + prezzo), con finestra temporale di 5
# minuti -- entro quella finestra, una chiave gia' vista viene scartata
# in silenzio (nessun messaggio di errore, e' un comportamento atteso,
# non un fallimento). Dopo 5 minuti la stessa chiave puo' tornare a
# passare (es. il venditore ripubblica lo stesso capo in un secondo
# momento, caso raro ma non impossibile, meglio non bloccarlo per sempre).
DEDUP_CONTENUTO_WINDOW_SECONDS = 300  # 5 minuti
_recent_listings_seen = {}  # chiave_normalizzata (tupla) -> timestamp ultimo avvistamento


def _normalizza_titolo_per_dedup(title):
    """Rimuove dal titolo la parte finale che identifica la taglia, per
    ottenere una chiave di confronto stabile tra varianti taglia dello
    stesso identico annuncio.

    Gestisce due pattern osservati in produzione, in ordine di priorita':
    1. Taglia tra virgolette/apici a fine titolo, es. "Talle L", "Taglia
       42" -- il bot Vinted Tracker riporta il campo as-is da Vinted nella
       lingua scelta dal venditore (visto sia 'Talle' spagnolo che
       'Taglia' italiano), quindi NON proviamo a riconoscere la parola
       taglia in ogni lingua possibile (fragile, lista incompleta):
       rimuoviamo l'intero blocco tra virgolette a fine stringa, a
       prescindere dalla lingua.
    2. Fallback se non ci sono virgolette: rimuove solo l'ultima parola
       spazio-separata (spesso la taglia anche senza virgolette, es. un
       numero "32"/"42" o sigla "XL" a fine titolo).

    Il confronto finale e' case-insensitive e con spazi multipli
    normalizzati, per tollerare piccole variazioni di spaziatura viste
    nei messaggi reali (es. doppio spazio tra parole)."""
    if not title:
        return ""
    t = title.strip()
    t_senza_virgolette_finali = re.sub(r"['\"][^'\"]*['\"]\s*$", "", t).strip()
    if t_senza_virgolette_finali != t:
        base = t_senza_virgolette_finali
    else:
        parole = t.split()
        base = " ".join(parole[:-1]) if len(parole) > 1 else t
    return re.sub(r"\s+", " ", base).strip().lower()


def e_variante_recente_dello_stesso_oggetto(parsed):
    """True se un annuncio con lo stesso titolo normalizzato (taglia
    esclusa) + brand + prezzo e' gia' stato visto negli ultimi
    DEDUP_CONTENUTO_WINDOW_SECONDS. In quel caso, NON registra una nuova
    occorrenza (la finestra resta ancorata al primo avvistamento, non si
    rinnova ad ogni variante taglia che arriva -- altrimenti una serie di
    10 taglie che arrivano a raffica entro 5 minuti l'una dall'altra
    estenderebbe la finestra all'infinito).

    Se non e' un duplicato, registra il nuovo avvistamento e ritorna
    False. Pulisce anche le voci scadute ad ogni chiamata -- manutenzione
    a costo trascurabile, evita crescita illimitata del dizionario in un
    processo long-running su Railway."""
    chiave = (
        _normalizza_titolo_per_dedup(parsed.get("title")),
        (parsed.get("brand") or "").strip().lower(),
        (parsed.get("price") or "").strip(),
    )

    now = time.time()
    scadute = [
        k for k, ts in _recent_listings_seen.items()
        if now - ts > DEDUP_CONTENUTO_WINDOW_SECONDS
    ]
    for k in scadute:
        del _recent_listings_seen[k]

    if chiave in _recent_listings_seen:
        return True

    _recent_listings_seen[chiave] = now
    return False


@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
async def on_new_message(event):
    try:
        message_id = event.message.id
        if message_id in _processed_message_ids:
            log.info(
                "Messaggio %d gia' elaborato (evento duplicato rilevato) -- skip.",
                message_id,
            )
            return
        _processed_message_ids.add(message_id)
        if len(_processed_message_ids) > _MAX_PROCESSED_IDS_TRACKED:
            # Rimuove gli ID piu' vecchi (i message_id di Telegram sono
            # monotonicamente crescenti, quindi min() trova il piu' vecchio)
            _processed_message_ids.discard(min(_processed_message_ids))

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

        # DEDUP PER CONTENUTO (vedi note sopra): se e' una variante taglia
        # di un annuncio gia' valutato negli ultimi 5 minuti, skip silenzioso
        # PRIMA di qualsiasi lavoro costoso (scraping, foto, Gemini, Claude).
        # Nessun messaggio di errore o avviso all'utente -- e' il
        # comportamento desiderato, non un fallimento.
        if e_variante_recente_dello_stesso_oggetto(parsed):
            log.info(
                "Variante taglia di un annuncio gia' valutato di recente -- skip silenzioso. "
                "Titolo: %s",
                parsed.get("title"),
            )
            return

        url = extract_url_from_text(text)

        # se l'URL non e' nel testo, alcuni bot lo mettono in un bottone
        # inline -- Telethon lo espone nei bottoni del messaggio (event.message.buttons)
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
