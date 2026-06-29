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
  - MODELLO GEMINI (29/06/2026): passato da gemini-3.5-flash a
    gemini-3.1-flash-lite (modello GA stabile, non la preview gia'
    discontinuata) -- ~6x piu' economico sia su input che su output
    ($0.25/$1.50 per 1M token contro $1.50/$9.00), validato con un test
    A/B manuale su un annuncio reale (Patagonia con macchie visibili,
    quindi un caso che richiede un giudizio di condizione non banale):
    identificazione, autenticita', trascrizione etichetta e descrizione
    difetti sostanzialmente equivalenti tra i due modelli; la sola
    differenza osservata era di un gradino sulla scala di classificazione
    condizione ("Usato evidente" vs "Da riparare" sullo stesso identico
    difetto descritto in egual dettaglio da entrambi) -- non un errore di
    percezione visiva, solo una calibrazione leggermente diversa del
    giudizio finale. Risparmio osservato sulla singola chiamata: 83.6%.
    Se in produzione si osservano scostamenti piu' marcati su altri casi
    (es. falsi negativi sull'autenticita', trascrizioni etichetta
    imprecise), il valore di GEMINI_MODEL_NAME va riportato a
    "gemini-3.5-flash" -- e' un cambio di una singola riga, non serve
    altro codice.
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
GEMINI_MODEL_NAME = "gemini-3.1-flash-lite"
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL_NAME}:generateContent"
)
GEMINI_CACHED_CONTENTS_URL = "https://generativelanguage.googleapis.com/v1beta/cachedContents"

# EXPLICIT CACHING GEMINI
GEMINI_CACHE_TTL_SECONDS = 3600 * 6
_gemini_cache_name = None

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_GALLERY_PHOTOS = 10

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

VINTED_BRAND_IDS = {
    "brunello cucinelli": "103740",
    "rick owens": "145654",
    "arc'teryx": "319730",
    "arcteryx": "319730",
    "patagonia": "90804",
    "marni": "12251",
    "missoni": "4463",
    "jean paul gaultier": "4129",
    "jpg": "4129",
    "emilio pucci": "10831",
    "pucci": "10831",
    "issey miyake": "75090",
    "pleats please": "395642",
    "pleats please issey miyake": "395642",
    "claude montana": "121608",
    "miu miu": "1745",
    "thierry mugler": "284",
    "mugler": "284",
    "courreges": "12639",
    "courrèges": "12639",
    "m missoni": "1702343",
    "missoni home": "2776470",
    "missoni mare": "2720679",
    "vivienne westwood": "14217",
    "yohji yamamoto": "200474",
    "dries van noten": "72138",
    "ann demeulemeester": "51445",
    "raf simons": "184436",
    "loewe": "24209",
    "helmut lang": "47829",
    "jil sander": "17991",
    "bottega veneta": "86972",
    "maison margiela": "639289",
    "margiela": "639289",
    "max mara": "5483",
    "veilance": "3388210",
    "nanga": "434286",
    "snow peak": "666350",
    "acronym": "712647",
}

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
    if not material_value_raw:
        return None
    materiali_annuncio = [m.strip().lower() for m in material_value_raw.split(",")]
    for materiale_prioritario in MATERIALI_PREGIATI_PRIORITA:
        if materiale_prioritario in materiali_annuncio:
            return materiale_prioritario
    return None

# ---------------------------------------------------------------------------
# VINTED FLIP ORACLE PRO -- system prompt
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
    "query_di_ricerca_ideale": "Crea una stringa di ricerca BREVISSIMA e letale per eBay (max 3 parole: Brand + Modello/Categoria). NON inserire mai colori, generi (uomo/donna) o materiali, perché azzerano i risultati di eBay.",
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
# SCRAPING VINTED
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
    "Referer": "[https://www.vinted.it/](https://www.vinted.it/)",
    "Accept": "image/webp,image/avif,image/jpeg,image/png,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
}

_vinted_session = requests.Session()
_vinted_session.headers.update(VINTED_HEADERS)


def scrape_vinted_listing(url):
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

        catalog_matches = re.findall(
            r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"',
            html,
        )
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

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


def download_image_bytes(url, referer="[https://www.vinted.it/](https://www.vinted.it/)", max_retries=2):
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
        time.sleep(0.6 * attempt)

    log.warning(
        "Download immagine fallito definitivamente dopo %d tentativi (ultimo status=%s, ultimo errore=%s): %s",
        max_retries, last_status, last_error, url,
    )
    return None


# ---------------------------------------------------------------------------
# GEMINI
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
    except Exception as e:
        log.warning("Ottimizzazione immagine (Pillow) fallita, uso byte originali: %s", e)
        return img_bytes


def assicura_gemini_cache():
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

    cache_name = assicura_gemini_cache()

    payload = {
        "contents": [{"role": "user", "parts": parts}],
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
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }

    if cache_name:
        payload["cachedContent"] = cache_name
    else:
        payload["system_instruction"] = {"parts": [{"text": GEMINI_VISION_SYSTEM_PROMPT}]}

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    backoff_seconds = 2

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

            resp.raise_for_status()

        except requests.exceptions.HTTPError as exc:
            last_exception = exc
            if attempt >= max_retries:
                break
        except requests.exceptions.RequestException as exc:
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
# CLAUDE -- prezzi, margine, verdetto finale
# ---------------------------------------------------------------------------

def strip_per_photo_analysis(gemini_analysis_json):
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


def _serper_batch_query(labeled_queries, num_results=3, max_snippet_chars=80):
    labels = [label for label, _ in labeled_queries]
    queries = [query for _, query in labeled_queries]

    try:
        resp = requests.post(
            "[https://google.serper.dev/search](https://google.serper.dev/search)",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=[{"q": q, "gl": "it", "hl": "it", "num": num_results} for q in queries],
            timeout=15,
        )
        resp.raise_for_status()
        batch_results = resp.json()
    except Exception as e:
        log.warning("Ricerca batch Serper fallita per %d query: %s", len(queries), e)
        return {
            label: f"  Ricerca fallita per errore tecnico ({type(e).__name__}). Nessun dato da questa fonte."
            for label in labels
        }

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
            
            # MAGIA SALVA-PREZZO: Estrae i prezzi prima di tagliare lo snippet
            prezzi = re.findall(r'(?:€|EUR)\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:€|EUR)', snippet, re.IGNORECASE)
            prezzi_unici = list(dict.fromkeys(prezzi))
            
            if len(snippet) > max_snippet_chars:
                snippet = snippet[:max_snippet_chars].rstrip() + "..."
            
            if prezzi_unici:
                snippet += f" [PREZZI TROVATI: {', '.join(prezzi_unici)}]"
                
            lines.append(f"  - {title}\n    {snippet}")
        results_by_label[label] = "\n".join(lines)

    return results_by_label


def build_vinted_search_url(brand, categoria, modello_o_categoria, max_price=None,
                            catalog_id=None, material_per_ricerca=None):
    brand_lower = (brand or "").strip().lower()
    brand_id = VINTED_BRAND_IDS.get(brand_lower)

    catalog_str = f"&catalog[]={catalog_id}" if catalog_id else ""

    if brand_id:
        categoria_breve = (categoria or "").strip()
        parti_search_text = [p for p in (categoria_breve, material_per_ricerca) if p]
        search_text_finale = " ".join(parti_search_text)

        url = (
            f"[https://www.vinted.it/catalog?brand_ids](https://www.vinted.it/catalog?brand_ids)[]={brand_id}"
            f"{catalog_str}"
            f"&search_text={quote(search_text_finale)}"
            "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
        )
        if max_price:
            url += f"&price_to={max_price}"
        return url, True
    else:
        query_text = f"{brand} {modello_o_categoria} {material_per_ricerca or ''}".strip()
        url = (
            f"[https://www.vinted.it/catalog?search_text=](https://www.vinted.it/catalog?search_text=){quote(query_text)}"
            f"{catalog_str}"
            "&order=newest_first"
        )
        return url, False


def search_comps_ebay_sold(brand, modello, categoria):
    """Ricerca diretta su eBay con filtro 'Venduto' (sold) via Serper.
    Ottimizzato con LH_PrefLoc=2 per aggirare il blocco IP americano di Serper."""
    query_base = f"{brand} {modello} {categoria}".strip()
    if not query_base:
        return None

    ebay_search_url = (
        f"[https://www.ebay.it/sch/i.html?_nkw=](https://www.ebay.it/sch/i.html?_nkw=){quote(query_base)}"
        "&LH_Sold=1&LH_Complete=1&rt=nc&LH_PrefLoc=2"
    )
    return ebay_search_url


def _clean_scraped_markdown(content):
    if not content: return content

    content = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"- \1", content)

    vinted_items = []
    for line in content.split('\n'):
        line_lower = line.lower()
        if "brand:" in line_lower and ("&#x20ac;" in line_lower or "€" in line_lower):
            clean_line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
            clean_line = clean_line.replace('&#x20AC;', '€').replace('&#x20ac;', '€').strip('- *')
            vinted_items.append(f"- {clean_line}")
            
            if len(vinted_items) >= 15:
                break
                
    if vinted_items:
        return "\n".join(vinted_items)

    content = re.sub(r"^---\s*\nmeta-[\s\S]*?\n---\s*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^meta-[\w-]+:.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"^title:.*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"\[Vendi un oggetto simile\]\([^)]+\)", "", content)
    content = re.sub(r"\[Logo di Vinted\]\([^)]+\)", "", content)
    content = re.sub(r"\[Passa al contenuto!?\[[^\]]*\]\([^)]+\)\]\([^)]+\)", "", content)
    content = re.sub(r"!\[Catalogo\]\([^)]+\)", "", content)
    
    # OTTIMIZZAZIONE EBAY: Rimuove TUTTI i link markdown rimasti tenendo solo il testo utile
    content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
    
    content = re.sub(r"\n{3,}", "\n\n", content)
    
    return content.strip()


def _serper_scrape_page(url, max_chars=1300):
    try:
        resp = requests.post(
            "[https://scrape.serper.dev](https://scrape.serper.dev)",
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

    content = _clean_scraped_markdown(content)
    return content[:max_chars]


def _esegui_ricerca_serper_completa(brand, modello, categoria, query_base,
                                     catalog_id=None, material_per_ricerca=None):
    from urllib.parse import quote
    """Esegue le 5 ricerche in parallelo (3 scrape diretti + 2 Google batch)."""
    results_by_label = {}

    vinted_url, vinted_e_per_id = build_vinted_search_url(
        brand, categoria, f"{modello} {categoria}".strip(),
        catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
    )
    ebay_url = search_comps_ebay_sold(brand, modello, categoria)
    
    # ASSALTO DIRETTO A VESTIAIRE COLLECTIVE
    vestiaire_url = f"https://www.vestiairecollective.com/search/?q={quote(query_base)}"

    serper_queries = [
        ("GOOGLE GENERICO (prezzo/valore)", f"{query_base} prezzo valore second hand"),
        ("GOOGLE GENERICO (retail originale)", f"{query_base} retail price original"),
    ]

    log.info(
        "QUERY/URL SERPER COSTRUITI (base: '%s'):\n"
        "  VINTED (scrape, filtro_per_id=%s): %s\n"
        "  EBAY SOLD (scrape): %s\n"
        "  VESTIAIRE (scrape diretto): %s\n"
        "  GOOGLE GENERICO 1 (query): %s\n"
        "  GOOGLE GENERICO 2 (query): %s",
        query_base, vinted_e_per_id, vinted_url, ebay_url, vestiaire_url,
        serper_queries[0][1], serper_queries[1][1],
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_batch = executor.submit(_serper_batch_query, serper_queries)
        future_vinted = executor.submit(_serper_scrape_page, vinted_url)
        future_ebay = executor.submit(_serper_scrape_page, ebay_url)
        future_vestiaire = executor.submit(_serper_scrape_page, vestiaire_url)

        futures = {
            future_batch: "__BATCH__",
            future_vinted: "VINTED (scrape diretto)",
            future_ebay: "EBAY SOLD (scrape diretto)",
            future_vestiaire: "VESTIAIRE COLLECTIVE (scrape diretto)"
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
    """Ricerca comps di prezzo via Serper. Orchestrazione e fallback."""
    query_base = f"{brand} {modello} {categoria}".strip()
    if not query_base or query_base.lower() in ("nessuno", "non disponibile", ""):
        return "RICERCA WEB: non eseguita, brand/modello non identificabile con sufficiente certezza dal JSON visivo."

    results_by_label, vinted_e_per_id = _esegui_ricerca_serper_completa(
        brand, modello, categoria, query_base,
        catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
    )

    fallimento_totale = all(
        any(marker in v for marker in ("Nessun risultato", "fallita", "non completata", "fallito", "vuota/bloccata"))
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
            any(marker in v for marker in ("Nessun risultato", "fallita", "non completata", "fallito", "vuota/bloccata"))
            for v in results_by_label.values()
        )

    if fallimento_totale:
        return (
            "RICERCA WEB: eseguita su 5 fonti (eBay sold, Vestiaire, Vinted, Google generico x2), "
            "inclusa una query di fallback più ampia, ma NESSUNA ha prodotto risultati utili. "
            "Nessun comp disponibile -- applica confidenza Bassa e non inventare prezzi a memoria."
        )

    serper_queries_labels = [
        "GOOGLE GENERICO (prezzo/valore)", "GOOGLE GENERICO (retail originale)",
    ]
    all_labels = ["VESTIAIRE COLLECTIVE (scrape diretto)", "VINTED (scrape diretto)", "EBAY SOLD (scrape diretto)"] + serper_queries_labels
    
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

    try:
        gemini_data = json.loads(gemini_analysis_json)
        ident = gemini_data.get("identificazione", {}) if isinstance(gemini_data, dict) else {}
        brand_per_ricerca = (
            ident.get("brand_effettivamente_visibile_sui_loghi")
            or ident.get("brand_dichiarato_dal_venditore")
            or listing_info.get("brand")
            or ""
        )

        query_ideale = (ident.get("query_di_ricerca_ideale") or "").strip()
        if query_ideale and len(query_ideale.split()) <= 8:
            modello_per_ricerca = query_ideale
            if brand_per_ricerca:
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
            categoria_per_ricerca = ""
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

    usage = data.get("usage", {})
    log.info(
        "CLAUDE usage -- input: %s, cache_read: %s, cache_creation: %s, output: %s",
        usage.get("input_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cache_creation_input_tokens"),
        usage.get("output_tokens"),
    )

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    final_text = "".join(text_blocks) if text_blocks else "[Nessun testo restituito da Claude]"

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
    try:
        prezzo = float(str(prezzo_richiesto_str).replace(",", "."))
    except (TypeError, ValueError):
        return None

    testo = f"{titolo or ''} {descrizione or ''}".lower()
    spedizione_stimata = 2.50
    indicatori_non_it = (
        " la ", " et ", " avec ", " une ", " talle ", " size ", " größe ",
        " und ", " met ", " con la ", " der ", " die ", " das ",
    )
    if any(ind in testo for ind in indicatori_non_it):
        spedizione_stimata = 4.50

    protezione_acquirenti = round(prezzo * 0.05 + 0.70, 2)
    costo_pieno = round(prezzo + protezione_acquirenti + spedizione_stimata, 2)
    return costo_pieno


def check_skip_pre_claude(gemini_analysis_json, listing_info=None):
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

    e_falso_evidente = (
        verdetto_legit == "probabilmente falso"
        and confidenza >= 90
        and rischio == "molto alto"
    )
    if e_falso_evidente:
        motivo = legit.get("cosa_non_torna_o_e_dubbio") or "Falso conclamato dall'analisi visiva."
        return True, f"[FALSO CONCLAMATO] {motivo}"

    valutazione = data.get("valutazione_flipper_preliminare", {})
    if isinstance(valutazione, dict):
        if valutazione.get("categoria_a_basso_valore") is True:
            motivo = valutazione.get("motivo_se_basso_valore") or "Categoria a basso valore strutturale (es. calzini, intimo)."
            return True, f"[CATEGORIA BASSO VALORE] {motivo}"

        verdetto_grezzo = (valutazione.get("verdetto_grezzo") or "").strip().upper()
        if verdetto_grezzo == "NON COMPRARE":
            motivo = valutazione.get("motivo_verdetto_grezzo") or "Verdetto preliminare negativo da Gemini."
            return True, f"[VERDETTO GREZZO GEMINI] {motivo}"

        prezzo_massimo_raw = (
            valutazione.get("prezzo_vendita_massimo_plausibile_eur")
            if valutazione.get("prezzo_vendita_massimo_plausibile_eur") is not None
            else valutazione.get("prezzo_sale_massimo_plausibile_eur")
        )
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
                    SOGLIA_MARGINE_EUR = 20
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
            time.sleep(0.4)

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

_processed_message_ids = set()
_MAX_PROCESSED_IDS_TRACKED = 500

DEDUP_CONTENUTO_WINDOW_SECONDS = 300
_recent_listings_seen = {}


def _normalizza_titolo_per_dedup(title):
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
            _processed_message_ids.discard(min(_processed_message_ids))

        sender = await event.get_sender()
        sender_name = ((getattr(sender, "username", None) or "") + " " +
                        (getattr(sender, "first_name", None) or "")).lower()

        if not any(hint in sender_name for hint in VINTED_TRACKER_NAME_HINTS):
            return

        text = event.message.message or ""
        if not text.strip():
            return

        parsed = parse_vinted_tracker_message(text)

        if e_variante_recente_dello_stesso_oggetto(parsed):
            log.info(
                "Variante taglia di un annuncio gia' valutato di recente -- skip silenzioso. "
                "Titolo: %s",
                parsed.get("title"),
            )
            return

        url = extract_url_from_text(text)

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
