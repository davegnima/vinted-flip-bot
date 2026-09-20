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
import statistics
import traceback
from io import BytesIO
from urllib.parse import quote

import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from PIL import Image

# MIGRAZIONE AD ASYNCIO (2026-09-19)
# ----------------------------------
# Telethon e' un framework interamente asincrono: ogni chiamata di rete
# sincrona (requests) e ogni pausa bloccante (time.sleep) eseguite nel suo
# loop fermano TUTTO il bot, compresa la ricezione di nuovi messaggi dal
# tracker. Nella versione precedente process_listing girava dentro
# asyncio.to_thread, il che evitava il blocco del loop ma serializzava di
# fatto la pipeline su un solo thread per annuncio, con decine di secondi
# di attesa passiva (scraping Vinted, Serper, Gemini) durante i quali non
# si poteva iniziare a lavorare l'annuncio successivo.
#
# Ora tutta la rete passa da httpx.AsyncClient e tutte le pause da
# asyncio.sleep, quindi piu' annunci vengono elaborati davvero in
# parallelo e le attese di rete non costano nulla. L'unico rate-limit che
# resta volutamente serializzato e' quello verso Vinted, protetto da
# _vinted_rate_limit_lock (vedi sotto): li' la pausa minima tra richieste
# e' una difesa contro il 403, non un collo di bottiglia da eliminare.
#
# NOTA httpx >= 0.28: il vecchio parametro "proxies" (plurale, dict) e'
# stato rimosso. La rotazione proxy e' quindi implementata con un client
# per proxy, costruiti una volta sola all'avvio (vedi _CLIENT_VINTED_POOL).

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
# "openai" per usare GPT-4o-mini al posto di Gemini-3.8-flash sul solo step
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

# RETI_SICUREZZA_ATTIVE: RITIRATO il 2026-09-19 con il passaggio al
# cervello a output JSON strutturato. Non ha piu' nulla da attivare o
# disattivare: le sei reti di sicurezza che governava
# (verifica_ancoraggio_prezzo_comp, verifica_comp_citati_sono_reali,
# forza_soglia_minima_compra, converti_tratta_senza_obiettivo_valido,
# declassa_urgenza_se_borderline, applica_soglia_trattativa_40_percento)
# esistevano per correggere a posteriori, via regex sul testo, numeri e
# decisioni che il modello scriveva in prosa. Ora quei numeri il modello
# non li scrive affatto: li calcola calcola_verdetto() in Python dai dati
# strutturati, quindi non esiste piu' l'errore da correggere. La domanda
# diagnostica che questo flag doveva risolvere (perche' le reti
# intervenivano sul 94% degli item con CERVELLO_PROVIDER=openai contro lo
# 0% con Gemini) resta senza risposta ed e' diventata priva di oggetto: le
# reti intervenivano sul FORMATO del testo, e quel formato non c'e' piu'.
# La variabile d'ambiente puo' restare impostata su Railway senza alcun
# effetto; questo blocco di commento e' l'unica traccia che ne resta.
#
# Vecchia documentazione del flag, conservata per contesto storico:
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
# (nessuna lettura della env var: il flag non governa piu' nulla)

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
# CERVELLO (verdetto finale): DECLASSATO da gemini-3.8-flash a
# gemini-3.5-flash-lite il 2026-09-19, stesso modello dell'Occhio.
#
# Motivo: verificato lo stesso giorno che il free tier di 3.8-flash (come
# quello di 3.5-flash "pieno" e 3.6-flash) concede solo ~20 richieste/giorno
# -- non i 1.500 di una fonte terza rivelatasi sbagliata per questi modelli
# -- mentre gemini-3.5-flash-lite ha un tetto reale di ~500 RPD. Con 200
# annunci/giorno e il Cervello che fa 2-3 chiamate ciascuno (fase ricerca +
# fase verdetto JSON, vedi MAX_ROUNDS_FUNZIONE), restare su un modello a 20
# RPD significa fermarsi dopo ~10 item; con 3.5-flash-lite c'e' margine per
# coprirli quasi tutti, anche se non e' garantito al 100% (Occhio + Cervello
# sullo stesso modello condividono lo stesso tetto giornaliero: vedi il
# calcolo nel commit del 2026-09-19).
#
# Trade-off ACCETTATO esplicitamente dall'utente, non implicito: la scelta
# di aggiornare a un Flash "pieno" (vedi commit precedenti) nasceva da
# quotazioni incoerenti su capi quasi identici (due camicie Our Legacy
# valutate €40 e €60). Con l'output JSON strutturato quell'incoerenza
# SPECIFICA (formato, numeri che si contraddicono nel testo) e' sparita per
# costruzione -- calcola_verdetto fa i conti, non il modello. Cio' che
# un modello Lite puo' ancora fare peggio e' il ragionamento semantico a
# monte del JSON: quale comp escludere, se una discrepanza sull'etichetta
# e' vera o un bias sul prezzo basso, quanto fidarsi di un "Primi articoli
# in vendita" ambiguo. Nessuna rete di sicurezza recupera un giudizio
# sbagliato su QUESTO. Se tornano valutazioni palesemente inconsistenti fra
# capi simili, il primo sospetto e' questo downgrade, non un bug nel calcolo.
GEMINI_MODEL_OCCHIO = "gemini-3.5-flash-lite"
GEMINI_MODEL_CERVELLO = "gemini-3.5-flash-lite"
GEMINI_API_URL_OCCHIO = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_OCCHIO}:generateContent"
GEMINI_API_URL_CERVELLO = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_CERVELLO}:generateContent"

# Prezzi per milione di token -- STESSO modello per Occhio e Cervello da
# oggi, quindi stesso prezzo per entrambi. Verificare su
# https://ai.google.dev/gemini-api/docs/pricing se cambia.
PREZZO_OCCHIO_INPUT = 0.30
PREZZO_OCCHIO_OUTPUT = 2.50
PREZZO_CERVELLO_INPUT = PREZZO_OCCHIO_INPUT
PREZZO_CERVELLO_OUTPUT = PREZZO_OCCHIO_OUTPUT
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
BOT_VERSION = "2026-09-19-cervello-json-strutturato-asyncio"

# ---------------------------------------------------------------------------
# PARAMETRI ECONOMICI -- l'unica fonte di verita' per TUTTI i calcoli
# ---------------------------------------------------------------------------
# Dal 2026-09-19 il cervello IA non calcola piu' nessun numero finanziario:
# restituisce un JSON strutturato con i soli DATI di valutazione (linea
# rilevata, comp trovati, prezzo target di vendita) e margine, ROI, costo
# d'acquisto, obiettivo trattativa, decisione e urgenza vengono calcolati
# qui in Python da calcola_verdetto(). Questi sono i parametri di quel
# calcolo: cambiarli qui cambia il comportamento di tutto il bot, senza
# doverli inseguire dentro un prompt.
COMMISSIONE_PROTEZIONE_PCT = 0.05      # protezione acquisti Vinted, quota sul prezzo
COMMISSIONE_PROTEZIONE_FISSA = 0.70    # protezione acquisti Vinted, quota fissa
SPEDIZIONE_STIMATA_EUR = 2.50          # tariffa IT, la piu' economica
QUOTA_INCASSO_NETTO = 0.80             # incasso reale = prezzo di vendita x 0.80

SOGLIA_MARGINE_COMPRA = 20.0           # EUR netti minimi per un COMPRA
SOGLIA_ROI_COMPRA = 100.0              # % minima di ROI per un COMPRA
SOGLIA_MARGINE_URGENZA = 30.0          # EUR netti minimi per "Alta urgenza"
SOGLIA_ROI_URGENZA = 150.0             # % minima di ROI per "Alta urgenza"
SCONTO_MAX_TRATTATIVA = 0.40           # sconto massimo trattabile sul PRODOTTO

# Tolleranza (EUR) nel confronto tra un prezzo comp dichiarato dal cervello
# e i prezzi realmente presenti nel pool di ricerca -- assorbe arrotondamenti
# (89,99 scritto come 90) senza lasciar passare un numero inventato.
TOLLERANZA_COMP_EUR = 1.0

# COMP_DA_MEMORIA_AMMESSI: scelta esplicita dell'utente il 2026-09-19. Con
# l'output JSON strutturato ogni prezzo comp dichiarato dal cervello e' un
# numero isolato e confrontabile con il pool di ricerca realmente raccolto,
# quindi sapere quali NON vengono dal pool e' ora un controllo esatto (una
# differenza tra insiemi, non piu' un'interpretazione di prosa).
#
# A True (default, comportamento scelto): un comp che non trova riscontro
# nel pool viene comunque USATO nel calcolo, ma marcato come proveniente
# dalla conoscenza propria del modello e mostrato separatamente nel
# messaggio Telegram -- niente item scartati, niente verdetti declassati,
# solo trasparenza su da dove arriva ogni numero.
#
# PRECISAZIONE TECNICA IMPORTANTE (non un'obiezione, un dato di fatto sul
# funzionamento di QUESTO bot): il cervello NON ha il grounding Google
# attivo. Il tool builtin google_search e' stato deliberatamente sostituito
# da cerca_comp_prezzo/Serper perche' non era forzabile in modo affidabile
# (vedi il commento alla sezione CERVELLO GEMINI CON FUNCTION CALLING
# FORZATO), e l'unica funzione che accetta grounding=True e' chiama_gemini,
# invocata per l'Occhio con grounding=False. Un prezzo fuori pool non
# proviene quindi da una ricerca web eseguita in quel momento, ma dalla
# memoria parametrica del modello, con i limiti che questo comporta:
# nessuna data, nessun mercato specifico, nessuna verificabilita'.
#
# A False: i comp senza riscontro nel pool vengono esclusi dal calcolo
# della stima (restano comunque visibili nel messaggio, marcati come
# scartati). Un solo valore da cambiare, nessun'altra modifica al codice.
COMP_DA_MEMORIA_AMMESSI = os.environ.get("COMP_DA_MEMORIA_AMMESSI", "true").strip().lower() == "true"

# OCCHIO_OUTPUT_JSON: interruttore fra i due formati di output dell'Occhio.
#
#   false (DEFAULT)  L'Occhio risponde in prosa, com'e' sempre stato. Lo
#                    skip pre-cervello usa check_skip_pre_cervello, cioe'
#                    una decina di substring match sul testo.
#   true             L'Occhio risponde con OCCHIO_RESPONSE_SCHEMA e lo skip
#                    si calcola da campi tipizzati (calcola_scarto_occhio).
#
# Il default e' false di proposito: gemini-3.5-flash-lite e' un modello
# piccolo e nessuna verifica a tavolino dice se compila bene 28 campi. Il
# confronto va fatto su annunci veri, e questa variabile permette di
# tornare indietro cambiando un valore su Railway, senza ricaricare codice.
#
# In entrambi i rami il resto della pipeline riceve lo STESSO testo: in
# modalita' JSON il dict viene renderizzato da render_occhio_da_json() nel
# formato prosa che build_skip_report e il prompt del Cervello gia'
# consumano. Il raggio della modifica resta cosi' limitato alla sola
# generazione, e il ramo prosa resta bit-per-bit quello di prima.
OCCHIO_OUTPUT_JSON = os.environ.get("OCCHIO_OUTPUT_JSON", "false").strip().lower() == "true"

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

# BLOCKLIST BRAND -- esclusione totale su richiesta esplicita dell'utente,
# indipendentemente da prezzo/margine/ROI stimati. "escludi intrend sempre.
# Non lo comprerò mai" (2026-09-20): a differenza delle regole di linea/era
# sopra (che abbassano il valore di una sottolinea ma valutano comunque il
# capo), un brand in questa lista non viene MAI comprato, quindi non ha
# senso nemmeno stimarne il prezzo di rivendita -- si scarta prima ancora
# di chiamare l'occhio, come un venditore in blocklist.
BRAND_BLOCKLIST = {"intrend"}

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
    # "cardigan" aggiunto il 2026-09-20: assente prima in ogni categoria (ne'
    # qui ne' altrove nel dizionario), quindi un titolo come "Jean Paul
    # Gaultier Blue Cardigan" non veniva classificato in NESSUNA categoria
    # (estrai_categoria_da_titolo tornava None) -- e con categoria=None
    # _filtra_comp_per_categoria e' un no-op per definizione, quindi i comp
    # visuali restavano completamente non filtrati (borse/vestiti/gonne
    # mescolati) anche dopo il fix dell'ordinamento. Osservato in log di
    # produzione reali.
    "maglia": ["maglia", "maglione", "pullover", "sweater", "pull", "jumper", "jersey", "suéter", "trui", "strick", "cardigan"],
    "t-shirt": ["t-shirt", "tshirt", "t shirt", "maglietta", "camiseta", "playera"],
    "canotta": ["canotta", "canottiera", "top", "tank top", "canotte", "débardeur", "tirantes"],
    "felpa": ["felpa", "hoodie", "sweatshirt", "sudadera", "kapuzenpulli"],
    "gonna": ["gonna", "rock", "skirt", "jupe", "falda", "saia"],
    "pantaloni": ["pantaloni", "pantalone", "hose", "trousers", "pants", "pantalon", "pantalón", "calças"],
    "jeans": ["jeans", "denim", "vaqueros", "vaquero"],
    "giacca": ["giacca", "jacke", "jacket", "veste", "chaqueta", "casaco"],
    "gilet": ["gilet", "smanicato", "weste", "vest", "waistcoat", "chaleco", "colete"],
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
    "gilet": "vest",
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


def estrai_categoria_da_titolo(titolo, descrizione=None):
    """Trova la categoria del capo cercando tutte le keyword multilingua nel
    titolo (e, se fornita, nella descrizione), e sceglie quella con il match
    PIU' LUNGO/specifico -- non la prima trovata nell'ordine del dizionario.
    Necessario perche' altrimenti keyword generiche possono "vincere" per
    errore su keyword piu' specifiche che le contengono come sottostringa:
    es. "shirt" (categoria camicia) e' una sottostringa di "t-shirt"
    (categoria t-shirt), quindi con un semplice "primo match" un titolo come
    "T shirt uomo" veniva categorizzato come camicia invece che t-shirt,
    portando a comp di camicie eleganti al posto di magliette basic -- due
    fasce di prezzo completamente diverse.

    La descrizione e' stata aggiunta il 2026-09-19 dopo un caso reale (The
    Row "Ophelia", maglione da oltre 800 EUR di listino) in cui il titolo
    dell'annuncio era solo il nome del modello, senza nessuna parola che
    indicasse il tipo di capo -- la categoria restava "non rilevata" e
    Vestiaire/eBay venivano saltati del tutto, anche se la descrizione
    conteneva "sweater"/"maglione" e l'occhio/cervello lo scoprivano comunque
    in ricerca on-demand, troppo tardi per alimentare la rete di sicurezza
    sui comp.

    Estendere il match alla descrizione (testo libero, molto piu' lungo del
    titolo) ha reso subito evidente in test un bug gia' latente ma raro sul
    solo titolo: alcune keyword corte in CATEGORIA_KEYWORDS sono sottostringhe
    di parole italiane comunissime -- "cap" (cappello) dentro "capo",
    "top" (canotta) dentro "soprattutto", "rock" (gonna) dentro "barocco",
    ecc. Un semplice `in` le faceva scattare per errore su descrizioni
    discorsive. Risolto usando confini di parola (\\b) invece di sottostringa
    libera, mantenendo intatta la logica "match piu' lungo vince" (che
    resta necessaria per casi come "t-shirt" vs "shirt", dove entrambe le
    keyword rispettano il confine di parola).

    IMPORTANTE (bug trovato in test il 2026-09-19, stesso giorno
    dell'estensione alla descrizione): concatenare titolo e descrizione in
    un unico testo prima di cercare il match piu' lungo dava PRIORITA'
    ALLA LUNGHEZZA DELLA KEYWORD invece che alla fonte. Caso reale: annuncio
    "Gilet Max Mara elegante", descrizione "da abbinare con una camicia
    bianca sotto" -- "camicia" (7 char, ma e' solo un capo da ABBINAMENTO
    citato nella descrizione) batteva "gilet" (5 char, ma e' il capo
    IN VENDITA, dichiarato nel titolo dal venditore). Il titolo e' un
    segnale molto piu' affidabile di cosa sia il capo della descrizione
    (che spesso menziona altri capi solo come contesto di stile). Per
    questo ora si cerca PRIMA solo nel titolo, e si usa la descrizione
    SOLO come fallback quando il titolo non da' nessun match -- niente
    piu' concatenazione con pari peso tra le due fonti."""
    migliore_dal_titolo = _cerca_categoria_in_testo(titolo)
    if migliore_dal_titolo:
        return migliore_dal_titolo
    return _cerca_categoria_in_testo(descrizione)


def _cerca_categoria_in_testo(testo):
    """Cerca la categoria con match piu' lungo/specifico in UN SOLO testo
    (vedi estrai_categoria_da_titolo per il perche' titolo e descrizione
    non vengono piu' concatenati)."""
    if not testo:
        return None
    testo_lower = testo.lower()
    migliore_categoria = None
    migliore_lunghezza = 0
    for categoria_it, parole_chiave in CATEGORIA_KEYWORDS.items():
        for parola in parole_chiave:
            if len(parola) <= migliore_lunghezza:
                continue
            if re.search(r'\b' + re.escape(parola) + r'\b', testo_lower):
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

    # 1b. Blocklist brand -- controllo sia sul campo brand strutturato sia sul
    # titolo, perche' non tutti gli annunci hanno il campo brand valorizzato
    # correttamente (es. "brand: altro" con il nome vero solo nel titolo).
    for brand_escluso in BRAND_BLOCKLIST:
        if re.search(r'\b' + re.escape(brand_escluso) + r'\b', brand) or \
           re.search(r'\b' + re.escape(brand_escluso) + r'\b', titolo):
            return True, f"[BRAND IN BLOCKLIST] '{brand_escluso}' e' un brand escluso a prescindere."

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
        "uniqlo",
        "missoni for target", "missoni x target",
    ]
    # Match a PAROLA INTERA (\b), non a sottostringa. Prima questa lista usava
    # un semplice "kw in testo", a differenza dei filtri danni/non-originalita'
    # sotto che gia' usavano \b: e' lo stesso bug di collisione per sottostringa
    # gia' visto con "shirt"/"t-shirt", e scartava silenziosamente annunci buoni.
    for kw in unflippable:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[CATEGORIA GENERICA NON FLIPPABILE] Rilevata keyword: {kw}"

    # 2a-bis. Collab con H&M, forma "h&m" separata dal resto perche' su Vinted
    # (e nello scraping) l'ampersand sparisce spesso dal titolo, lasciando
    # solo "Hm" -- caso reale osservato in produzione: "Marni for Hm trench
    # jacket" e' passato indenne per anni perche' il filtro cercava solo la
    # stringa letterale "h&m" con l'apostrofo. "hm" da solo e' troppo rischioso
    # (collide con l'interiezione "hm"/"hmm" in descrizioni scritte a mano),
    # quindi si controllano solo i pattern di collab espliciti "for hm"/"x hm"/
    # "h & m" (con spazi), oltre alla forma originale con l'ampersand.
    HM_COLLAB_PATTERN = re.compile(r'\b(h\s*&\s*m|for\s+hm|x\s+hm)\b')
    if HM_COLLAB_PATTERN.search(testo_completo):
        return True, "[CATEGORIA GENERICA NON FLIPPABILE] Rilevata keyword: collab H&M"

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

# ---------------------------------------------------------------------------
# OCCHIO: SCHEMA JSON STRUTTURATO (attivo solo con OCCHIO_OUTPUT_JSON=true)
# ---------------------------------------------------------------------------
# Stesso impianto del Cervello, applicato un passo piu' a monte: il modello
# OSSERVA e Python DECIDE.
#
# L'Occhio in prosa produce anche un verdetto finanziario completo (margine,
# ROI, decisione, urgenza, deal score) che il codice ri-estrae con regex in
# estrai_margine_preliminare per decidere se saltare il Cervello. E' la
# stessa classe di errore rimossa dal Cervello il 2026-09-19, sopravvissuta
# nel primo stadio: un annuncio buono puo' morire per un margine allucinato
# prima ancora di essere valutato con comp reali.
#
# In questo schema l'Occhio non produce NESSUN numero economico, e nemmeno
# il flag di scarto: uno scarto e' una decisione, e si calcola in
# calcola_scarto_occhio() dai campi osservativi. La versione calcolata e'
# anche piu' severa di quella dichiarabile a parole, perche' puo' pretendere
# che la controprova anti-bias sia stata eseguita prima di accettare un
# "falso conclamato" (caso reale: Dries Van Noten autentico a EUR 5,95
# scartato come falso con dettagli costruiti a posteriori).
#
# L'ordine dei campi e' una catena di ragionamento forzata: evidenza ->
# trascrizione verbatim -> identificazione -> osservazione fisica ->
# riscontri -> controprova -> verdetto. Il verdetto puo' essere scritto solo
# dopo che i riscontri concreti sono gia' stati messi per iscritto.
#
# maxItems su ogni array. ATTENZIONE (scoperto il 2026-09-20, in produzione):
# su responseJsonSchema Gemini applica un "complexity budget" interno non
# documentato, e maxItems su un array di OGGETTI (etichette, difetti,
# riscontri_autenticita) lo consuma molto piu' di maxItems su un array di
# stringhe. Superato il budget la risposta e' un 400 INVALID_ARGUMENT generico
# ("Request contains an invalid argument"), senza indicare quale campo.
# Lo schema qui sotto resta la fonte di verita' completa (usata per i test e
# per il troncamento locale in valida_payload_occhio); quello REALMENTE
# spedito a Gemini e' OCCHIO_RESPONSE_SCHEMA_GEMINI, derivato piu' sotto
# togliendo maxItems solo dagli array di oggetti.

OCCHIO_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": [
        # 1. EVIDENZA: cosa posso davvero vedere
        "qualita_evidenza",
        "segnali_rischio_annuncio",

        # 2. TRASCRIZIONE VERBATIM: prima di interpretare
        "etichette",
        "brand_letto_etichetta",
        "composizione_da_etichetta",
        "taglia_etichetta",

        # 3. IDENTIFICAZIONE: cosa deduco dalle trascrizioni
        "relazione_brand",
        "nome_sottolinea",
        "categoria_capo_osservata",
        "linea_o_era",
        "evidenze_datazione",
        "modello_riconosciuto",

        # 4. OSSERVAZIONE FISICA
        "materiale_osservato_dalle_foto",
        "coerenza_materiale",
        "indicatori_costruzione",
        "livello_fattura",
        "hardware_dettaglio",
        "condizione_osservata",
        "difetti",

        # 5. CONTROPROVE: prima del verdetto, non dopo
        "riscontri_autenticita",
        "controprova_prezzo_eseguita",

        # 6. VERDETTO: solo ora
        "verdetto_legit",
        "confidenza_legit",
        "motivo_sintetico",
        "foto_mancanti_richieste",

        # 7. VENDITORE E SINTESI
        "profilo_venditore",
        "evidenza_profilo",
        "sintesi_visiva",
    ],
    "properties": {

        # =================================================================
        # 1. EVIDENZA
        # =================================================================
        "qualita_evidenza": {
            "type": "STRING",
            "format": "enum",
            "enum": ["sufficiente_per_verdetto", "parziale_servono_altre_foto", "insufficiente"],
            "description": (
                "Quanto le foto permettono un giudizio. Dichiaralo PRIMA di qualsiasi "
                "verdetto: un verdetto netto su evidenza insufficiente e' un errore."
            ),
        },
        "segnali_rischio_annuncio": {
            "type": "ARRAY",
            "maxItems": 4,
            "items": {
                "type": "STRING",
                "format": "enum",
                "enum": [
                    "foto_stock_non_del_capo", "screenshot_di_altro_annuncio",
                    "watermark_di_altro_sito", "capi_diversi_tra_le_foto",
                    "foto_di_uno_schermo", "descrizione_incoerente_con_le_foto",
                ],
            },
            "description": (
                "Frode che riguarda l'ANNUNCIO, non il capo. Vuoto se nessuno."
            ),
        },

        # =================================================================
        # 2. TRASCRIZIONE VERBATIM
        # =================================================================
        "etichette": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": "Una voce per ogni etichetta visibile, anche parziale. Vuoto se nessuna.",
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["tipo", "testo_verbatim", "leggibilita", "osservazioni_tecniche"],
                "properties": {
                    "tipo": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "main_label", "wash_care_tag", "etichetta_taglia",
                            "etichetta_composizione", "codice_prodotto",
                            "etichetta_storica_o_union", "ologramma_autenticita",
                            "etichetta_rivenditore", "altro",
                        ],
                    },
                    "testo_verbatim": {
                        "type": "STRING",
                        "description": (
                            "Testo ESATTO, carattere per carattere, comprese maiuscole, "
                            "apostrofi e simboli. Usa [...] per le parti illeggibili. E' la "
                            "prova su cui si reggono tutte le deduzioni successive."
                        ),
                    },
                    "leggibilita": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["nitida", "parziale", "illeggibile"],
                    },
                    "osservazioni_tecniche": {
                        "type": "STRING",
                        "nullable": True,
                        "description": (
                            "L'etichetta come OGGETTO FISICO: tessuta o stampata, font, "
                            "densita' del ricamo, come e' cucita, materiale del nastro, "
                            "invecchiamento coerente col capo."
                        ),
                    },
                },
                "required": ["tipo", "testo_verbatim", "leggibilita"],
            },
        },
        "brand_letto_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Il brand ESATTAMENTE come letto, senza correggerlo: se l'etichetta dice "
                "'Kapitales' scrivi 'Kapitales', non 'Kapital'."
            ),
        },
        "composizione_da_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Composizione verbatim con le percentuali (es. '100% CASHMERE'). Solo da "
                "etichetta fisica: NON dedurla dal titolo dell'annuncio."
            ),
        },
        "taglia_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": "Taglia come stampata sull'etichetta (es. 'IT 48', 'M', 'US 10').",
        },

        # =================================================================
        # 3. IDENTIFICAZIONE
        # =================================================================
        "relazione_brand": {
            "type": "STRING",
            "format": "enum",
            "enum": ["corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_leggibile"],
            "description": (
                "'sottolinea_stessa_maison' = MM6 per Margiela, See by Chloe per Chloe, "
                "Weekend per Max Mara: ha ancora valore. 'brand_estraneo' = marchio diverso e "
                "NON correlato (es. 'Kapitales' per 'Kapital'): il sistema scarta l'annuncio "
                "senza altre verifiche, quindi usalo solo se sei sicuro. Nel dubbio "
                "'non_leggibile'."
            ),
        },
        "nome_sottolinea": {
            "type": "STRING",
            "nullable": True,
            "description": "Nome della sottolinea se applicabile (es. 'MM6', 'McQ').",
        },
        "categoria_capo_osservata": {
            "type": "STRING",
            "description": (
                "Categoria come si VEDE nelle foto, non come la chiama il titolo "
                "(es. 'giubbotto di jeans'): serve a intercettare i titoli fuorvianti."
            ),
        },
        "linea_o_era": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Linea o era desunta dalle etichette (es. 'Era Lang 1986-2005', 'Era Link "
                "Theory post-2006', 'Linea 10', 'mainline'). null se le etichette non lo "
                "permettono: da qui dipende il valore stimato."
            ),
        },
        "evidenze_datazione": {
            "type": "ARRAY",
            "maxItems": 5,
            "items": {"type": "STRING"},
            "description": (
                "I segnali concreti su cui si basa linea_o_era: formato del wash tag, paese "
                "di produzione, stile del logo, formato del codice, diciture legate a "
                "un'epoca. Un'era senza evidenze elencate qui vale come non dichiarata."
            ),
        },
        "modello_riconosciuto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Nome del modello se riconoscibile come pezzo d'archivio noto. null se non "
                "lo riconosci con certezza: non tirare a indovinare un nome iconico."
            ),
        },

        # =================================================================
        # 4. OSSERVAZIONE FISICA
        # =================================================================
        "materiale_osservato_dalle_foto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Che materiale SEMBRA da drappeggio, riflesso, grana, peluria, pieghe. "
                "Indipendente dall'etichetta: serve proprio a confrontarli."
            ),
        },
        "coerenza_materiale": {
            "type": "STRING",
            "format": "enum",
            "enum": ["coerente", "incoerente", "non_valutabile"],
            "description": (
                "Confronto tra composizione_da_etichetta e materiale osservato. 'incoerente' "
                "= l'aspetto smentisce l'etichetta (possibile etichetta riportata)."
            ),
        },
        "indicatori_costruzione": {
            "type": "ARRAY",
            "maxItems": 6,
            "items": {"type": "STRING"},
            "description": (
                "Dettagli di fattura osservabili: finitura delle cuciture, tipo di fodera, "
                "corrispondenza del disegno alle giunture, asole lavorate, finiture a mano, "
                "interno pulito o grezzo, peso e marchiatura di zip e bottoni. Sono cio' che "
                "distingue la qualita' vera a prescindere dall'etichetta."
            ),
        },
        "livello_fattura": {
            "type": "STRING",
            "format": "enum",
            "enum": ["alta_sartoriale", "buona_industriale", "media", "scadente", "non_valutabile"],
        },
        "hardware_dettaglio": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Marchio e aspetto di zip/bottoni/fibbie se leggibili (es. 'zip Lampo', "
                "'bottoni marchiati HELMUT LANG N.Y.'): insieme indizio di autenticita' e di "
                "datazione."
            ),
        },
        "condizione_osservata": {
            "type": "STRING",
            "format": "enum",
            "enum": ["come_nuovo", "ottime", "buone", "usato_evidente", "danneggiato"],
            "description": "La condizione che vedi TU, non quella dichiarata dal venditore.",
        },
        "difetti": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": (
                "Un oggetto per ogni difetto, sia visto in foto sia dichiarato nel testo. "
                "Vuoto se non ce ne sono. Non accorpare piu' difetti in una voce."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["tipo", "posizione", "gravita", "strutturale", "fonte"],
                "properties": {
                    "tipo": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "macchia", "alone", "buco", "foro_da_spilla", "strappo",
                            "scucitura", "usura_tessuto", "pilling", "scolorimento",
                            "filo_tirato", "zip_difettosa", "bottoni_mancanti",
                            "rammendo_o_riparazione", "alterazione_sartoriale",
                            "deformazione", "odore_dichiarato", "altro",
                        ],
                    },
                    "posizione": {
                        "type": "STRING",
                        "description": "Dove si trova (es. 'manica sinistra vicino al polsino').",
                    },
                    "gravita": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["lieve", "moderata", "grave"],
                    },
                    "strutturale": {
                        "type": "BOOLEAN",
                        "description": (
                            "true se compromette uso o rivendibilita' (strappo, buco aperto, "
                            "zip rotta). false per difetti estetici recuperabili."
                        ),
                    },
                    "fonte": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["visibile_in_foto", "dichiarato_dal_venditore", "entrambi"],
                        "description": (
                            "Distingue cio' che hai VISTO da cio' che ti e' stato DETTO: un "
                            "difetto solo visibile e non dichiarato e' anche un segnale sul "
                            "venditore."
                        ),
                    },
                },
                "required": ["tipo", "posizione", "gravita", "strutturale", "fonte"],
            },
        },

        # =================================================================
        # 5. CONTROPROVE
        # =================================================================
        "riscontri_autenticita": {
            "type": "ARRAY",
            "maxItems": 8,
            "description": (
                "Un oggetto per ogni elemento esaminato. E' la BASE del verdetto: il "
                "verdetto discende da qui, non precede. Elenca anche i riscontri COERENTI: "
                "un giudizio negativo su un solo elemento incoerente, ignorandone cinque "
                "coerenti, e' un errore di metodo."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": ["elemento", "osservazione", "esito", "peso"],
                "properties": {
                    "elemento": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": [
                            "font_etichetta", "tessitura_etichetta", "cucitura_etichetta",
                            "wash_tag", "codice_prodotto", "paese_produzione",
                            "simboli_lavaggio", "hardware", "ricamo_logo",
                            "proporzioni_logo", "qualita_cuciture", "fodera",
                            "asole_e_bottoni", "coerenza_invecchiamento", "altro",
                        ],
                    },
                    "osservazione": {
                        "type": "STRING",
                        "description": (
                            "COSA hai visto, verificabile da chi guarda la stessa foto. "
                            "Vietato 'font grossolano' o 'sembra di bassa qualita'': specifica "
                            "in cosa differisce (spessore delle aste, spaziatura, grazie, "
                            "allineamento, densita' del punto). Se non sai dirlo con "
                            "precisione, l'esito e' 'non_valutabile'."
                        ),
                    },
                    "esito": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["coerente", "incoerente", "non_valutabile"],
                    },
                    "peso": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["forte", "medio", "debole"],
                        "description": (
                            "Quanto sposta il giudizio: un codice wash tag incoerente pesa "
                            "'forte', una cucitura irregolare su un vintage pesa 'debole'."
                        ),
                    },
                },
                "required": ["elemento", "osservazione", "esito", "peso"],
            },
        },
        "controprova_prezzo_eseguita": {
            "type": "BOOLEAN",
            "description": (
                "CONTROLLO ANTI-BIAS. Prima di dichiarare falso: con gli stessi identici "
                "dettagli, lo giudicheresti sospetto anche se il prezzo fosse dieci volte "
                "tanto? true solo se hai fatto la verifica e il giudizio regge. Se la "
                "risposta e' 'forse no', declassa a 'sospetto_servono_altre_foto'."
            ),
        },

        # =================================================================
        # 6. VERDETTO
        # =================================================================
        "verdetto_legit": {
            "type": "STRING",
            "format": "enum",
            "enum": [
                "probabilmente_autentico", "sospetto_servono_altre_foto",
                "probabilmente_falso", "non_verificabile",
            ],
            "description": (
                "Discende da riscontri_autenticita. 'probabilmente_falso' richiede almeno un "
                "riscontro 'incoerente' di peso 'forte' descritto in concreto."
            ),
        },
        "confidenza_legit": {
            "type": "STRING",
            "format": "enum",
            "enum": ["alta", "media", "bassa"],
            "description": (
                "'alta' solo con evidenza nitida e piu' riscontri concordi: falso + alta fa "
                "scartare l'annuncio senza altri controlli."
            ),
        },
        "motivo_sintetico": {
            "type": "STRING",
            "description": (
                "Una riga che nomina l'elemento decisivo e cosa hai visto. Arriva all'utente "
                "cosi' com'e' anche quando il resto della pipeline viene saltato."
            ),
        },
        "foto_mancanti_richieste": {
            "type": "ARRAY",
            "maxItems": 3,
            "items": {"type": "STRING"},
            "description": (
                "Quali foto scioglierebbero il dubbio (es. 'main label al collo in primo "
                "piano'). Obbligatorio se il verdetto e' 'sospetto_servono_altre_foto'."
            ),
        },

        # =================================================================
        # 7. VENDITORE E SINTESI
        # =================================================================
        "profilo_venditore": {
            "type": "STRING",
            "format": "enum",
            "enum": ["privato_genuino", "reseller_esperto", "non_determinabile"],
            "description": (
                "Il numero di recensioni da solo NON decide: conta COSA vende. Guardaroba "
                "misto con fast fashion accanto al lusso = privato genuino anche con "
                "centinaia di recensioni. Solo brand designer = reseller esperto."
            ),
        },
        "evidenza_profilo": {
            "type": "STRING",
            "description": (
                "Deve citare il contenuto di 'Primi articoli in vendita' quando presente, "
                "non il solo numero di recensioni."
            ),
        },
        "sintesi_visiva": {
            "type": "STRING",
            "description": (
                "3-4 righe per l'utente: cosa vedi, cosa dicono le etichette, in che "
                "condizione e'. Nessun numero finanziario, nessuna decisione d'acquisto."
            ),
        },
    },
    "required": [
        "qualita_evidenza", "segnali_rischio_annuncio",
        "etichette",
        "relazione_brand", "categoria_capo_osservata", "evidenze_datazione",
        "coerenza_materiale", "indicatori_costruzione", "livello_fattura",
        "condizione_osservata", "difetti",
        "riscontri_autenticita", "controprova_prezzo_eseguita",
        "verdetto_legit", "confidenza_legit", "motivo_sintetico",
        "foto_mancanti_richieste",
        "profilo_venditore", "evidenza_profilo", "sintesi_visiva",
    ],
}


def _rimuovi_maxitems_da_array_di_oggetti(schema):
    """Deriva lo schema da spedire davvero a Gemini togliendo maxItems SOLO
    dagli array il cui items e' di tipo OBJECT.

    Workaround per il complexity budget di Gemini (vedi commento sopra
    OCCHIO_RESPONSE_SCHEMA): confermato via GitHub issue vercel/ai#21192,
    che riporta lo stesso identico 400 generico risolto rimuovendo maxItems
    dagli array di oggetti mantenendo pero' la validazione (e quindi il
    limite) lato codice. maxItems sugli array di stringhe/numeri resta,
    perche' e' quello a basso costo e non e' la causa del problema.

    Ricorsiva e non distruttiva: ritorna un nuovo dict, OCCHIO_RESPONSE_SCHEMA
    resta intatto come fonte di verita' per i test e per il troncamento
    locale in valida_payload_occhio.
    """
    if not isinstance(schema, dict):
        return schema

    convertito = dict(schema)

    if "properties" in convertito:
        convertito["properties"] = {
            nome: _rimuovi_maxitems_da_array_di_oggetti(sotto)
            for nome, sotto in convertito["properties"].items()
        }

    if "items" in convertito:
        convertito["items"] = _rimuovi_maxitems_da_array_di_oggetti(convertito["items"])

    if (
        convertito.get("type") == "ARRAY"
        and isinstance(convertito.get("items"), dict)
        and convertito["items"].get("type") == "OBJECT"
        and "maxItems" in convertito
    ):
        convertito = {k: v for k, v in convertito.items() if k != "maxItems"}

    return convertito


# Schema REALMENTE spedito a Gemini: senza maxItems sugli array di oggetti,
# per non sforare il complexity budget descritto sopra. Il limite di 8 voci
# per etichette/difetti/riscontri_autenticita resta comunque garantito, ma
# applicato in Python (valida_payload_occhio) invece che dallo schema.
OCCHIO_RESPONSE_SCHEMA_GEMINI = _rimuovi_maxitems_da_array_di_oggetti(OCCHIO_RESPONSE_SCHEMA)


# ==========================================================================
# SCARTO PRE-CERVELLO: calcolato, non dichiarato dal modello.
# Sostituisce check_skip_pre_cervello (~10 substring match su prosa, con due
# bug reali trovati in produzione il 2026-09-19: "Confidenza: Alta" con i due
# punti non matchava mai, e le varianti "falso palese"/"falso evidente" non
# erano previste).
# ==========================================================================

def calcola_scarto_occhio(o, solo_cover_photo=False):
    """Ritorna (scarta: bool, motivo: str|None) dai soli campi osservativi.

    solo_cover_photo: se le foto dell'annuncio non sono state scaricate e
    l'analisi si basa sulla sola cover di Telegram, "nessuna etichetta" e'
    quasi certamente un falso negativo dello scraping, non del capo: in quel
    caso non si scarta (stessa eccezione gia' presente oggi nel codice).

    I confronti passano da _norm() anche se valida_payload_occhio ha gia'
    normalizzato: questa funzione decide se spendere o no le ricerche di
    mercato, e un confronto fallito per una maiuscola di troppo significa
    lasciar passare un capo distrutto o un brand estraneo. Costa nulla,
    e regge anche se un domani viene chiamata su un dict non validato.
    """
    def _norm(valore):
        return valore.strip().lower() if isinstance(valore, str) else valore

    if _norm(o.get("relazione_brand")) == "brand_estraneo":
        return True, (
            "[BRAND NON CORRISPONDENTE] L'etichetta mostra un marchio diverso e non "
            f"correlato ({o.get('brand_letto_etichetta') or 'non leggibile'}) -- cervello "
            "non consultato, il capo non ha valore nel segmento monitorato."
        )

    # Il falso conclamato richiede anche la controprova anti-bias: senza,
    # e' esattamente il caso Dries Van Noten (autentico a 5,95 EUR scartato
    # come falso con dettagli costruiti a posteriori).
    if (_norm(o.get("verdetto_legit")) == "probabilmente_falso"
            and _norm(o.get("confidenza_legit")) == "alta"
            and o.get("controprova_prezzo_eseguita") is True):
        return True, f"[FALSO CONCLAMATO] {o.get('motivo_sintetico') or 'rilevato dall analisi visiva.'}"

    if o.get("segnali_rischio_annuncio"):
        return True, (
            "[ANNUNCIO FRAUDOLENTO] Segnali sulle immagini: "
            + ", ".join(str(s) for s in o["segnali_rischio_annuncio"])
        )

    difetti = o.get("difetti") or []
    if sum(1 for d in difetti
           if d.get("strutturale") and _norm(d.get("gravita")) == "grave") >= 1:
        return True, "[CONDIZIONE DISTRUTTA] Danno strutturale grave rilevato dall'analisi visiva."

    etichette = o.get("etichette") or []
    nessuna_etichetta = not etichette or all(
        _norm(e.get("leggibilita")) == "illeggibile" for e in etichette
    )
    if nessuna_etichetta and not solo_cover_photo:
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] Nessuna etichetta leggibile per verificare "
            "l'autenticita' -- servono piu' foto (main label + wash tag) prima di procedere."
        )

    return False, None


ETICHETTA_VERDETTO_LEGIT = {
    "probabilmente_autentico": "Probabilmente autentico",
    "sospetto_servono_altre_foto": "Sospetto, servono altre foto",
    "probabilmente_falso": "Probabilmente falso",
    "non_verificabile": "Non verificabile",
}


def valida_payload_occhio(occhio):
    """Normalizza il JSON dell'Occhio e ne mette in sicurezza i valori.

    Come valida_payload_cervello: lo schema garantisce la FORMA, non la
    SENSATEZZA. Un enum fuori lista diventa il default piu' prudente, e i
    problemi non bloccano l'elaborazione ma restano visibili.

    Ritorna (dict_normalizzato, elenco_problemi).
    """
    problemi = []
    o = dict(occhio or {})

    def _enum(campo, ammessi, default):
        valore = o.get(campo)
        valore = valore.strip().lower() if isinstance(valore, str) else None
        if valore in ammessi:
            o[campo] = valore
            return
        if o.get(campo) is not None:
            problemi.append(f"{campo}='{o.get(campo)}' non riconosciuto, uso '{default}'")
        o[campo] = default

    _enum("qualita_evidenza",
          {"sufficiente_per_verdetto", "parziale_servono_altre_foto", "insufficiente"},
          "parziale_servono_altre_foto")
    _enum("relazione_brand",
          {"corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_leggibile"},
          "non_leggibile")
    _enum("coerenza_materiale", {"coerente", "incoerente", "non_valutabile"}, "non_valutabile")
    _enum("livello_fattura",
          {"alta_sartoriale", "buona_industriale", "media", "scadente", "non_valutabile"},
          "non_valutabile")
    _enum("condizione_osservata",
          {"come_nuovo", "ottime", "buone", "usato_evidente", "danneggiato"}, "buone")
    _enum("verdetto_legit",
          {"probabilmente_autentico", "sospetto_servono_altre_foto",
           "probabilmente_falso", "non_verificabile"},
          "non_verificabile")
    _enum("confidenza_legit", {"alta", "media", "bassa"}, "bassa")
    _enum("profilo_venditore",
          {"privato_genuino", "reseller_esperto", "non_determinabile"}, "non_determinabile")

    for campo in ("etichette", "difetti", "riscontri_autenticita", "indicatori_costruzione",
                  "evidenze_datazione", "foto_mancanti_richieste", "segnali_rischio_annuncio"):
        if not isinstance(o.get(campo), list):
            o[campo] = []

    # Scarta le voci malformate invece di farle esplodere a valle.
    o["etichette"] = [
        e for e in o["etichette"]
        if isinstance(e, dict) and (e.get("testo_verbatim") or "").strip()
    ]
    o["difetti"] = [d for d in o["difetti"] if isinstance(d, dict) and d.get("tipo")]
    o["riscontri_autenticita"] = [
        r for r in o["riscontri_autenticita"]
        if isinstance(r, dict) and (r.get("osservazione") or "").strip()
    ]

    # OCCHIO_RESPONSE_SCHEMA_GEMINI (lo schema realmente spedito a Gemini)
    # non ha piu' maxItems su questi tre array: il limite ora si applica
    # qui, non piu' lato API. Vedi il commento sopra OCCHIO_RESPONSE_SCHEMA.
    o["etichette"] = o["etichette"][:8]
    o["difetti"] = o["difetti"][:8]
    o["riscontri_autenticita"] = o["riscontri_autenticita"][:8]

    # Normalizzazione degli enum ANNIDATI. Lo schema li dichiara minuscoli ma
    # il modello a volte capitalizza ("Grave" invece di "grave"), e su questi
    # campi non c'e' un default prudente che salvi: un confronto fallito in
    # calcola_scarto_occhio significa un difetto strutturale grave NON
    # riconosciuto, quindi un annuncio distrutto che prosegue come se fosse
    # integro. Si normalizza qui, una volta, invece di ripetere .lower() a
    # ogni confronto sparso nel codice.
    ENUM_ANNIDATI = {
        "etichette": ("tipo", "leggibilita"),
        "difetti": ("tipo", "gravita", "fonte"),
        "riscontri_autenticita": ("elemento", "esito", "peso"),
    }
    for nome_array, campi in ENUM_ANNIDATI.items():
        for voce in o[nome_array]:
            for campo in campi:
                if isinstance(voce.get(campo), str):
                    voce[campo] = voce[campo].strip().lower()
            if nome_array == "difetti":
                voce["strutturale"] = bool(voce.get("strutturale"))

    o["segnali_rischio_annuncio"] = [
        s.strip().lower() for s in o["segnali_rischio_annuncio"] if isinstance(s, str) and s.strip()
    ]

    o["controprova_prezzo_eseguita"] = bool(o.get("controprova_prezzo_eseguita"))

    # Un "probabilmente falso" senza nemmeno un riscontro incoerente e' il
    # sintomo esatto del bias prezzo-basso: la conclusione non discende da
    # nessuna osservazione messa per iscritto. Non si sovrascrive il
    # verdetto (potrebbe essere corretto), ma si toglie la confidenza alta,
    # che e' cio' che fa scattare lo scarto automatico.
    if o["verdetto_legit"] == "probabilmente_falso":
        incoerenti = [r for r in o["riscontri_autenticita"] if r.get("esito") == "incoerente"]
        if not incoerenti:
            problemi.append(
                "verdetto 'probabilmente falso' senza nessun riscontro incoerente: "
                "confidenza declassata, verificare a mano prima di scartare"
            )
            o["confidenza_legit"] = "bassa"

    for campo in ("motivo_sintetico", "sintesi_visiva", "evidenza_profilo",
                  "categoria_capo_osservata"):
        if not isinstance(o.get(campo), str):
            o[campo] = ""
        o[campo] = o[campo].strip()

    return o, problemi


def render_occhio_da_json(occhio, problemi=None):
    """Converte il JSON dell'Occhio nel formato testuale che il resto della
    pipeline gia' consuma.

    E' il punto che tiene piccola la modifica: build_skip_report continua a
    cercare "**Analisi visiva**", "🏷️ Legit:" e "📨 **Messaggio da inviare:**"
    con le stesse regex di sempre, e il prompt del Cervello riceve un blocco
    di testo come prima -- solo piu' ricco e senza numeri inventati.

    Nessuna cifra economica compare qui: in modalita' JSON l'Occhio non
    produce piu' margine/ROI/decisione, quindi non c'e' nulla da estrarre
    con estrai_margine_preliminare (lo skip su margine preliminare non si
    applica a questo ramo, per costruzione).
    """
    o = occhio or {}
    righe = ["**Analisi visiva**", o.get("sintesi_visiva") or "(nessuna sintesi fornita)"]

    etichette = o.get("etichette") or []
    if etichette:
        righe.append("")
        righe.append("Etichette lette:")
        for e in etichette:
            nota = f" [{e['osservazioni_tecniche']}]" if e.get("osservazioni_tecniche") else ""
            righe.append(
                f"- {e.get('tipo', 'altro')}: \"{e.get('testo_verbatim', '')}\" "
                f"({e.get('leggibilita', 'n/d')}){nota}"
            )
    else:
        righe += ["", "Etichette lette: nessuna leggibile nelle foto."]

    if o.get("composizione_da_etichetta"):
        righe.append(f"Composizione da etichetta: {o['composizione_da_etichetta']}")
    if o.get("materiale_osservato_dalle_foto"):
        righe.append(f"Materiale osservato: {o['materiale_osservato_dalle_foto']} "
                     f"(coerenza con l'etichetta: {o.get('coerenza_materiale', 'non_valutabile')})")
    if o.get("taglia_etichetta"):
        righe.append(f"Taglia da etichetta: {o['taglia_etichetta']}")
    if o.get("linea_o_era"):
        evidenze = "; ".join(o.get("evidenze_datazione") or []) or "nessuna evidenza dichiarata"
        righe.append(f"Linea/era: {o['linea_o_era']} (evidenze: {evidenze})")
    if o.get("modello_riconosciuto"):
        righe.append(f"Modello riconosciuto: {o['modello_riconosciuto']}")
    if o.get("indicatori_costruzione"):
        righe.append(f"Fattura ({o.get('livello_fattura', 'n/d')}): "
                     + "; ".join(o["indicatori_costruzione"]))
    if o.get("hardware_dettaglio"):
        righe.append(f"Hardware: {o['hardware_dettaglio']}")

    difetti = o.get("difetti") or []
    if difetti:
        righe.append("")
        righe.append(f"Condizione osservata: {o.get('condizione_osservata', 'n/d')}. Difetti:")
        for d in difetti:
            strutturale = ", STRUTTURALE" if d.get("strutturale") else ""
            righe.append(
                f"- {d.get('tipo')} ({d.get('gravita', 'n/d')}{strutturale}) "
                f"in {d.get('posizione', 'posizione non indicata')} "
                f"[{d.get('fonte', 'n/d')}]"
            )
    else:
        righe.append(f"Condizione osservata: {o.get('condizione_osservata', 'n/d')}, nessun difetto rilevato.")

    riscontri = o.get("riscontri_autenticita") or []
    if riscontri:
        righe.append("")
        righe.append("Riscontri di autenticita':")
        for r in riscontri:
            righe.append(
                f"- {r.get('elemento')}: {r.get('osservazione')} "
                f"-> {r.get('esito')} (peso {r.get('peso')})"
            )

    if o.get("segnali_rischio_annuncio"):
        righe.append("")
        righe.append("⚠️ Segnali di rischio sull'annuncio: "
                     + ", ".join(o["segnali_rischio_annuncio"]))

    legit = ETICHETTA_VERDETTO_LEGIT.get(o.get("verdetto_legit"), o.get("verdetto_legit") or "n/d")
    righe += [
        "",
        "## Verdetto",
        f"🏷️ Legit: {legit} — {o.get('motivo_sintetico') or 'nessun motivo fornito'}",
        f"🕐 Confidenza: {(o.get('confidenza_legit') or 'bassa').capitalize()} · "
        f"Evidenza fotografica: {o.get('qualita_evidenza', 'n/d')} · "
        f"Venditore: {o.get('profilo_venditore', 'n/d')}",
    ]
    if o.get("evidenza_profilo"):
        righe.append(f"👤 {o['evidenza_profilo']}")

    foto_mancanti = o.get("foto_mancanti_richieste") or []
    if foto_mancanti:
        righe += [
            "",
            "---",
            "📨 **Messaggio da inviare:**",
            f'"Ciao! Mi interessa, potresti aggiungere qualche foto? {"; ".join(foto_mancanti)}. Grazie!"',
        ]

    if problemi:
        righe.append("")
        for p in problemi:
            righe.append(f"⚠️ _Dato anomalo dall'analisi visiva: {p}_")

    return "\n".join(righe)


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

# IL NOME DEL TESSUTO NON È IL BRAND DEL CAPO
Caso reale già osservato: un annuncio titolato "Giacca uomo Loro Piana" era in realtà una giacca in pelle **Pineider** — "Loro Piana" indicava solo il FORNITORE del tessuto/materiale usato, non il produttore del capo. Loro Piana (e altri nomi come Zegna, Vitale Barberis Canonico, Scabal, Holland & Sherry, Cerruti) sono spesso citati nei titoli e nelle descrizioni come marchio del TESSUTO impiegato da un'altra maison, non come il brand del capo finito — è una pratica comune specialmente per capispalla in pelle o lana pregiata. Prima di trascrivere questi nomi come `brand_letto_etichetta`, verifica SEMPRE l'etichetta interna, il logo, i bottoni e il tirante della zip: se mostrano un nome diverso, è QUELLO il brand reale, e il nome del tessuto va citato solo come dettaglio di materiale in `materiale_osservato_dalle_foto`/`composizione_da_etichetta`, mai come brand. Se dall'etichetta/hardware non riesci a leggere un brand diverso da quello del tessuto citato nel titolo, dichiara `relazione_brand: "non_leggibile"` invece di assumere che il tessuto e il brand coincidano — un titolo che nomina solo un fornitore di tessuto NON è di per sé una prova di brand.

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

**MARNI:**
- ✅ Mainline → archivio eclettico, valore alto.
- ❌ "Marni for H&M" / "Marni x H&M" (collab 2012, prodotta in serie, NON è mainline) → basso valore, tratta come diffusion mass-market, mai comp da mainline Marni.

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
Difetti strutturali (buchi, strappi, tessuto lacerato) compromettono l'uso o la rivendibilità, ma NON sono tutti uguali: un piccolo foro isolato su una manica di un pezzo d'archivio resta vendibile a forte sconto, un capo con più strappi o un'area ampia compromessa no. Descrivi sempre la DIMENSIONE e la POSIZIONE del difetto (non solo che esiste), così il Cervello può giudicarne la gravità reale invece di trattare ogni foro allo stesso modo di uno strappo esteso.

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


def _costruisci_prompt_occhio_json(prompt_prosa):
    """Deriva il prompt dell'Occhio in modalita' JSON da quello in prosa.

    Derivato e non duplicato, per la stessa ragione per cui lo schema
    OpenAI si genera da quello Gemini con _schema_gemini_to_openai: due
    copie a mano divergono alla prima modifica, e la divergenza silenziosa
    e' proprio l'errore che questo refactor serve a eliminare. Qui si
    tolgono le sezioni che lo schema rende ridondanti e si aggiungono, una
    volta sola, le regole generali che altrimenti andrebbero ripetute nella
    description di ogni campo.

    Restano invece intatte tutte le sezioni di conoscenza di dominio
    (venditore, mainline/diffusion, difetti, cosa guardare nelle foto):
    lo schema descrive la FORMA della risposta, non sa nulla di moda.
    """
    # Le sezioni obsolete: la forma dell'output la impone lo schema, l'elenco
    # dei verdetti e' diventato un enum, e l'obbligo di motivazione e' imposto
    # strutturalmente da riscontri_autenticita (che non accetta un esito senza
    # aver nominato elemento e osservazione).
    OBSOLETE = (
        "# OUTPUT",
        "# VERDETTO LEGIT CHECK",
        "# OBBLIGO DI MOTIVAZIONE ESPLICITA",
    )
    sezioni = re.split(r"\n(?=# )", prompt_prosa)
    tenute = [s for s in sezioni if not s.startswith(OBSOLETE)]

    testa = tenute[0].replace(
        "Fai due cose in un solo passaggio: LEGIT CHECK visivo + valutazione finanziaria preliminare.",
        "Il tuo compito e' UNO SOLO: osservare e descrivere. Il legit check visivo e la "
        "descrizione del capo sono tuoi; la valutazione finanziaria NON e' tua.",
    )
    tenute[0] = testa

    return "\n".join(tenute) + """

# FORMATO DELLA RISPOSTA: SOLO JSON
Rispondi ESCLUSIVAMENTE con un oggetto JSON conforme allo schema fornito. Nessun testo fuori dal JSON, nessun markdown, nessuna emoji di verdetto.

**NON calcolare e non scrivere da nessuna parte**: prezzo di acquisto o di rivendita, margine, ROI, decisione (COMPRA/TRATTA/NON COMPRARE), urgenza, deal score, offerta di trattativa, messaggio al venditore. Non e' una semplificazione del tuo ruolo: senza comp di mercato reali quei numeri sarebbero inventati, e piu' avanti nella pipeline li calcola il sistema sui dati veri. Se li scrivi dentro un campo testuale vengono ignorati.

Dove il prompt qui sopra ti chiede di scrivere una frase o una riga in un certo formato, quella istruzione e' superata dallo schema: la stessa informazione ha ora un campo dedicato. In particolare, il brand completamente estraneo NON si segnala piu' con una frase nel testo, ma con `relazione_brand: "brand_estraneo"`.

# REGOLE GENERALI, VALIDE PER OGNI CAMPO
1. Trascrivi SOLO cio' che e' realmente visibile. Mai completare a memoria una dicitura che conosci ma che nella foto non si legge: usa [...] per le parti illeggibili.
2. Nel dubbio usa null, o il valore "non_valutabile"/"non_leggibile". Un valore inventato e' peggio di un valore assente, perche' il sistema non ha modo di distinguerlo da un'osservazione vera.
3. Descrivi cosa vedi, non dare giudizi generici. "Font con aste piu' spesse e spaziatura irregolare rispetto allo standard del brand" e' un'osservazione; "font grossolano" non lo e'.
4. Il prezzo non e' mai una prova di autenticita', in nessuna direzione.
5. Elenca anche i riscontri COERENTI, non solo quelli sospetti: un verdetto negativo costruito su un solo elemento incoerente, ignorandone cinque coerenti, e' un errore di metodo.
""".rstrip()


GEMINI_OCCHI_SYSTEM_PROMPT_JSON = _costruisci_prompt_occhio_json(GEMINI_OCCHI_SYSTEM_PROMPT)


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
| Marni | Mainline | "Marni for H&M" / "Marni x H&M" (collab 2012, mass-market, non mainline) |
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
Comp pre-raccolti scarsi/assenti/fuori tema → cerca_comp_prezzo con query mirata prima di rispondere. Unica fonte comp: Vinted. Gerarchia interna: Ricerca visuale per foto (quando presente: e' lo stesso capo/modello, non solo lo stesso brand, il comp piu' affidabile) > Vinted testo.
Codici prodotto o diciture rare citati dall'occhio ("prototipo", "edizione limitata", ecc.) → verifica che esistano davvero con cerca_comp_prezzo prima di trattarli come prova di valore; se non confermati, tratta come non verificati e abbassa Confidenza, non usarli come giustificazione principale del margine.
La "Confidenza" che l'occhio dichiara su un verdetto "Probabilmente falso" NON è affidabile da sola (bias noto: prezzo molto basso può contaminare il giudizio con dettagli vaghi costruiti a posteriori) — se i dettagli citati sono generici e il prezzo è molto basso, verifica con cerca_comp_prezzo prima di confermare NON COMPRARE per sospetto falso.

# MATERIALE DEI COMP DEVE CORRISPONDERE AL CAPO
Il materiale cambia il valore quasi quanto la linea (es. Cucinelli: cashmere puro >> lana/cotone). Materiale noto → scarta o segnala esplicitamente i comp di materiale diverso. Materiale IGNOTO → il sistema applica un tetto piu' prudente in automatico (75* percentile dei comp invece del piu' caro), ma solo se la tua stima lo supera davvero.
**Cosa conta come "noto" (`materiale_confermato: true`)**: il materiale e' noto ogni volta che compare ESPLICITAMENTE in ALMENO UNO di questi posti, anche senza una foto ravvicinata dell'etichetta di composizione: titolo dell'annuncio, descrizione testuale, categoria/attributo strutturato di Vinted, oppure lettura diretta dell'etichetta nella foto. Esempio: titolo "Kaschmir Pullover" → materiale noto (cashmere), `materiale_confermato: true`, anche se non vedi la percentuale esatta di composizione. Segnala il materiale come IGNOTO (`materiale_confermato: false`) SOLO quando non ne parla nessuno di questi posti e staresti indovinando dalla sola foto generica del capo (es. una semplice foto di un maglione senza nessuna menzione testuale del tessuto). Non abbassarlo per eccesso di prudenza quando l'informazione e' gia' scritta da qualche parte nei dati.

# ANCORAGGIO PREZZI — la regola più violata in produzione, massima attenzione
Tutti i comp Vinted sono **ASK** (annunci attivi, NON necessariamente venduti, spesso sovrastimati rispetto al prezzo di vendita reale) — non hai dati SOLD/venduti confermati per nessuna fonte. Applica SEMPRE uno sconto prudente del 20-30% sul comp ASK scelto prima di trattarlo come stima di vendita realistica, mai citare un ASK come se fosse il prezzo di vendita atteso senza quello sconto.
**Controllo numerico obbligatorio, ogni volta prima di scrivere il prezzo**: la tua stima di vendita non può MAI superare il comp ASK più alto (già scontato 20-30%) che tu stesso citi in Analisi — se lo supera, non è "prudente", è un errore: abbassala.
**Cita SEMPRE almeno 2 prezzi ESATTI verbatim** dai dati ricevuti in Analisi (mai un range parafrasato a memoria) — se il range che stai per scrivere non corrisponde a due prezzi realmente ricevuti, ricontrolla, non l'hai calcolato bene.

**PROCEDURA OBBLIGATORIA DI FILTRO OUTLIER, PRIMA di scrivere qualsiasi stima** — violazione osservata in produzione: un capo di categoria/prezzo minore (es. un singolo capo sartoriale) valutato usando come comp un capo di categoria completamente diversa e molto più costosa (es. un abito completo o un capospalla) comparso per errore nella stessa ricerca, ignorando tutti gli altri comp coerenti disponibili.
1. Elenca TUTTI i prezzi comp ricevuti per la STESSA categoria di capo (pantalone con pantalone, giacca con giacca, mai giacca con abito completo o capospalla con capo singolo).
2. Ordina questi prezzi e individua la mediana.
3. **Scarta ogni comp che supera 3× la mediana o è inferiore a 1/3 della mediana** — quasi sempre appartiene a un capo diverso (categoria, materiale o edizione), a un annuncio ASK irrealistico, o a un risultato di ricerca fuori tema finito per errore nell'elenco.
4. Calcola la stima SOLO sui comp rimasti dopo il filtro. Se dopo il filtro restano meno di 2 comp validi, dichiaralo esplicitamente in Analisi ("comp insufficienti dopo filtro outlier") e resta sulla fascia bassa/prudente, mai su un singolo comp isolato per giustificare una stima alta.
Esempio reale di violazione da evitare: comp per un capo sartoriale con prezzi €11, €40, €47, €75, €160, €170, €499, €600 (quest'ultimo per un ABITO COMPLETO, non il capo singolo in analisi) → mediana ≈ €61, il €499 e il €600 vanno scartati (>3× mediana) insieme all'€11 (<1/3 mediana); la stima corretta si basa solo su €40-170, non su €600.

Range di comp molto ampio (es. €25-200 per lo stesso brand) = quasi sempre stili diversi mescolati (basic vs lavorato/decorato) — usa solo i comp dello stesso stile del capo in analisi, mai la media di tutto il range.
Nessun comp specifico per il modello, solo per il brand in generale → usa la fascia mediana-bassa trovata, mai quella ottimistica. Se la tua stima finale supera nettamente ogni prezzo SOLD citato, stai ragionando sul prezzo retail, non sul second-hand — correggi al ribasso.

# COSA DEVI PRODURRE -- e cosa NON devi calcolare
Restituisci ESCLUSIVAMENTE un oggetto JSON conforme allo schema fornito. Nessun testo fuori dal JSON, nessun markdown, nessuna emoji di verdetto.

**NON calcolare e non scrivere da nessuna parte**: costo d'acquisto, incasso netto, margine, ROI, decisione (COMPRA/TRATTA/NON COMPRARE), urgenza, importo dell'offerta di trattativa. Questi li calcola il sistema, in modo deterministico, a partire dai dati che gli dai. Se li scrivi comunque dentro un campo testuale, verranno ignorati e il messaggio finale risultera' incoerente.

**L'unico numero economico che devi produrre e' `prezzo_target_vendita_eur`**: il prezzo LORDO a cui il capo andrebbe messo in vendita. Da li' il sistema ricava tutto il resto.

# COME COSTRUIRE prezzo_target_vendita_eur
1. Popola `comp_candidati` con OGNI prezzo comp che hai davanti, uno per oggetto, con il prezzo esatto e il titolo copiato alla lettera. Marca `escluso: true` (con motivo) quelli fuori categoria, di sottolinea sbagliata, o palesemente fuori scala. Non riassumere, non fare medie a mente: elencali.
2. Ogni comp Vinted e' un prezzo **ASK** (annuncio attivo, spesso sovrastimato), mai un venduto confermato. Scegli il comp di riferimento tra quelli non esclusi e applica uno sconto prudenziale tra il 20% e il 30% (`sconto_ask_applicato_pct`).
3. `prezzo_target_vendita_eur` non puo' superare il comp di riferimento gia' scontato, ne' un eventuale tetto di linea (`tetto_prezzo_linea_eur`). Il sistema applica comunque entrambi i limiti: se li superi, la tua stima viene abbassata d'ufficio, quindi tanto vale calcolarla giusta.
4. Materiale non confermato (`materiale_confermato: false`, vedi sezione MATERIALE per cosa conta come "noto") -> resta prudente, il sistema comunque abbassa la stima al 75* percentile dei comp validi se la superi.
5. Meno di 2 comp validi dopo le esclusioni -> resta sulla fascia bassa e dichiaralo in `note_analista`, mai una stima alta appoggiata a un solo comp isolato.

# PROVENIENZA DEI COMP -- dichiarala, non nasconderla
Il campo `fonte` di ogni comp distingue i prezzi che hai davvero davanti (`vinted_testo`, `vinted_visuale`) da quelli che stai ricordando tu (`memoria_modello`). Se citi un prezzo che NON compare nei dati ricevuti in questa conversazione, marcalo `memoria_modello`: non e' vietato e non fa scartare nulla, ma va dichiarato per quello che e'. Non spacciare mai un prezzo ricordato per un risultato di ricerca: il sistema confronta comunque ogni numero col pool reale e corregge l'etichetta da solo, quindi mentire qui produce solo un messaggio finale contraddittorio.

# URGENZA -- fornisci i segnali, non la conclusione
Non scrivere "Alta urgenza": compila `domanda_mercato` e `segnali_domanda` con i fatti concreti (piu' annunci simili venduti di recente, segmento ad alta liquidita' secondo la sezione LIQUIDITA', taglia centrale, pezzo iconico). L'urgenza la decide il sistema incrociando quei segnali con margine e ROI calcolati. `domanda_mercato: "alta"` con `segnali_domanda` vuoto viene trattato come "media": senza fatti la dichiarazione non vale.

# MESSAGGIO AL VENDITORE
**Tu non sai quale decisione finale prendera' il sistema** (COMPRA/TRATTA/NON COMPRARE/CHIEDI ALTRE FOTO: la calcola dopo, in base a margine e ROI che tu non calcoli). Il messaggio che scrivi in `messaggio_venditore_template` viene mostrato all'utente SOLO se la decisione finale e' TRATTA o CHIEDI ALTRE FOTO, mai su COMPRA -- quindi non scrivere MAI un messaggio che accetta o conferma l'acquisto a prezzo pieno ("lo prendo subito", "va bene cosi'", ecc.): se il sistema lo mostra, e' perche' sta negoziando o chiedendo chiarimenti, e un messaggio di accettazione piena lo contraddirebbe.
Se pensi che possa servire una trattativa (margine risicato al prezzo pieno, anche solo dubbio), scrivi SEMPRE un messaggio che propone un'offerta con il segnaposto ESATTO {OFFERTA}: il sistema lo sostituisce con l'importo calcolato al massimo sconto consentito. Non scrivere mai tu una cifra in euro, sarebbe diversa da quella reale. Lascia il campo a null solo se davvero non c'e' nulla da mandare al venditore in nessuno scenario (es. rifiuto netto per legit-check).

# TRASPARENZA OBBLIGATORIA
`legit_motivo_specifico` deve sempre dire COSA hai visto: font dell'etichetta e in cosa differisce, proporzioni del logo, cuciture, materiale, wash tag incoerente, hardware. Mai "rischio alto" o "discrepanze evidenti" senza dettaglio: quel testo arriva all'utente cosi' com'e'.

`motivo_profilo_venditore` deve citare esplicitamente il contenuto di "Primi articoli in vendita" quando e' presente nei dati, non il solo numero di recensioni.

# PRIMA DI CHIUDERE IL JSON -- verifica
1. Ogni prezzo in `comp_candidati` e' copiato alla lettera dai dati, o marcato `memoria_modello`?
2. `prezzo_target_vendita_eur` rispetta il comp di riferimento scontato e l'eventuale tetto di linea?
3. Il materiale e' davvero ignoto (nessuna menzione da nessuna parte) prima di mettere `materiale_confermato: false`? Se titolo/descrizione/etichetta lo dichiarano, e' `true`.
4. C'e' un difetto degno di nota sul capo? Se si', `difetto_significativo: true` con `sconto_difetto_pct` proporzionato e `descrizione_difetto` compilata -- e NON gia' scontato a mano dentro `prezzo_target_vendita_eur` (verrebbe scontato due volte). Se il difetto compromette l'uso o la rivendibilita' (buco aperto, strappo, tessuto lacerato, cerniera rotta), aggiungi `difetto_strutturale: true` e valuta `gravita_difetto_strutturale`: SOLO 'grave' porta il verdetto a NON COMPRARE da solo -- 'lieve' (difetto piccolo e localizzato, es. un foro isolato su una manica) e 'moderata' restano un capo normalmente valutabile, scontato tramite `sconto_difetto_pct` come ogni altro difetto. Non confondere "compromette la rivendibilita'" con "e' invendibile": un piccolo foro dichiarato in foto non rende automaticamente invendibile un pezzo d'archivio.
5. `legit_motivo_specifico` e' concreto e descrive una discrepanza reale?
6. Hai evitato di scrivere margine, ROI, decisione, urgenza e importi di trattativa ovunque?
""".strip()


# ---------------------------------------------------------------------------
# TELEGRAM BOT API HELPERS
# ---------------------------------------------------------------------------

def _spezza_per_telegram(text, max_len=3500):
    """Chunking condiviso da telegram_send_message e telegram_send_with_buttons
    (prima duplicato identico in entrambe). Taglia preferibilmente su riga
    vuota, poi su a capo, e solo come ultima risorsa a lunghezza fissa."""
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks or [text]


async def telegram_send_message(chat_id, text):
    MAX_LEN = 3500
    for chunk in _spezza_per_telegram(text, MAX_LEN):
        resp = await _client_telegram.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True},
        )
        if not resp.is_success:
            log.warning("sendMessage Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode", resp.status_code, resp.text[:300])
            await _client_telegram.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
            )


async def telegram_send_photo(chat_id, photo_bytes, caption=None):
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    await _client_telegram.post(f"{TELEGRAM_API}/sendPhoto", data=data, files=files, timeout=30)


async def telegram_send_media_group(chat_id, photos_bytes_list, caption=None):
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
    await _client_telegram.post(
        f"{TELEGRAM_API}/sendMediaGroup",
        data={"chat_id": chat_id, "media": json.dumps(media)},
        files=files,
        timeout=60,
    )


async def telegram_send_with_buttons(chat_id, text, url_annuncio, item_id=None):
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
    chunks = _spezza_per_telegram(text, 3500)

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
        resp = await _client_telegram.post(
            f"{TELEGRAM_API}/sendMessage",
            json={**payload_base, "parse_mode": "Markdown"},
        )
        if not resp.is_success:
            log.warning(
                "telegram_send_with_buttons: Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode",
                resp.status_code, resp.text[:300],
            )
            await _client_telegram.post(f"{TELEGRAM_API}/sendMessage", json=payload_base)


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

# TOKEN_FILE: dentro /data, il path del Volume Railway ("vinted-tokens")
# creato e agganciato al servizio "worker" il 2026-09-20 apposta per questo.
# Senza quel Volume montato, qualunque path relativo finirebbe sulla parte
# effimera del filesystem e sparirebbe a ogni riavvio/redeploy -- e' successo
# storicamente col tentativo di "log esiti reali", da qui la scelta di
# scrivere esplicitamente sotto /data invece che nella working directory.
# Se in futuro il Volume viene rimosso o rimontato altrove, il fallback su
# VINTED_ACCESS_TOKEN/REFRESH_TOKEN dalla env var resta comunque intatto
# (vedi sotto): un errore di scrittura qui non rompe nulla, semplicemente
# si perde la persistenza tra riavvii.
TOKEN_FILE = "/data/vinted_tokens.json"

_VINTED_COOKIES = {}
if os.path.exists(TOKEN_FILE):
    try:
        with open(TOKEN_FILE, "r") as f:
            _salvati = json.load(f)
        if _salvati.get("access_token_web"):
            _VINTED_COOKIES["access_token_web"] = _salvati["access_token_web"]
        if _salvati.get("refresh_token_web"):
            _VINTED_COOKIES["refresh_token_web"] = _salvati["refresh_token_web"]
    except Exception as e:
        log.warning("Impossibile leggere %s (probabilmente non esiste ancora): %s", TOKEN_FILE, e)
# La env var resta il fallback/seed: se il file non c'e' (primo avvio, o
# container ripartito senza Volume) o non contiene un token, si riparte da
# quello che l'utente ha messo su Railway.
if not _VINTED_COOKIES.get("access_token_web") and VINTED_ACCESS_TOKEN:
    _VINTED_COOKIES["access_token_web"] = VINTED_ACCESS_TOKEN
if not _VINTED_COOKIES.get("refresh_token_web") and VINTED_REFRESH_TOKEN:
    _VINTED_COOKIES["refresh_token_web"] = VINTED_REFRESH_TOKEN


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


# ---------------------------------------------------------------------------
# CLIENT HTTP ASINCRONI
# ---------------------------------------------------------------------------
# Un client per ogni destinazione, costruiti una volta sola e riusati per
# tutta la vita del processo: httpx tiene aperte le connessioni (keep-alive),
# quindi si risparmiano handshake TLS su ogni chiamata, cosa che con
# requests.Session avveniva solo per Vinted.
#
# Rotazione proxy: da httpx 0.28 il parametro "proxies" (dict per schema) non
# esiste piu', si passa un solo "proxy" per client. La rotazione round-robin
# diventa quindi una rotazione TRA CLIENT, uno per proxy, costruiti all'avvio.
# Se PROXY_LIST e' vuota il pool contiene un solo client diretto, cioe'
# esattamente il comportamento originale senza proxy.
_CLIENT_VINTED_POOL = []
_client_generico = None   # Gemini/OpenAI/Serper/Resellbot: nessun proxy
_client_telegram = None   # Bot API: timeout piu' corti, chiamate frequenti

# Client HTTP DEDICATO all'account Vinted autenticato (ricerca visuale),
# separato dal pool anonimo _CLIENT_VINTED_POOL -- aggiunto il 2026-09-20
# per chiudere il bug "refresh riuscito ma redirect a /member/register
# comunque": _prossimo_client_vinted() fa round-robin tra client condivisi
# da TUTTO lo scraping anonimo (annunci, venditori), quindi ognuno di quei
# client accumula nel proprio cookie jar cookie Datadome/anti-bot legati a
# traffico anonimo ad alto volume, scorrelati dall'account dedicato. Il
# refresh e la successiva chiamata search_by_image_id finivano cosi' su
# client diversi (round-robin avanza a ogni chiamata) o comunque su un
# client il cui cookie Datadome non corrisponde alla sessione autenticata
# appena rinnovata -- mandare un JWT valido insieme a un cookie Datadome di
# un'altra "sessione anonima" e' esattamente il tipo di incoerenza che fa
# scattare un blocco anti-bot, a prescindere dalla validita' del token.
# Con un client dedicato, riusato SEMPRE per refresh + search_by_image_id,
# httpx accumula da solo (jar persistente normale, nessun parsing manuale)
# i cookie Datadome/sessione ricevuti sulla home page e sul refresh, e la
# chiamata search_by_image_id li porta con se' in modo coerente -- proprio
# come farebbe un browser reale sempre loggato con lo stesso account.
# NON aggiunto a _CLIENT_VINTED_POOL: lo scraping anonimo di annunci/
# venditori non lo vede mai e resta interamente separato, come richiesto
# esplicitamente dall'utente.
_CLIENT_VINTED_AUTH = None


def _crea_client_vinted(proxy_url=None):
    # NIENTE cookies=_VINTED_COOKIES qui (tolto il 2026-09-20, era li' dal
    # giorno prima): i client di questo pool sono condivisi da TUTTO lo
    # scraping Vinted (annunci, venditori, ricerca visuale), quindi
    # allegare qui i cookie dell'account dedicato li rendeva permanenti su
    # OGNI richiesta -- quando il token scadeva, anche lo scraping normale
    # (che prima funzionava benissimo in modo anonimo) veniva rediretto a
    # /session-refresh e si rompeva silenziosamente. Scelta esplicita
    # dell'utente: l'account dedicato va usato SOLO per la ricerca visuale,
    # passando i cookie caso per caso su quella singola chiamata (vedi
    # _risolvi_search_by_image_id) invece che sul client condiviso.
    return httpx.AsyncClient(
        headers=VINTED_HEADERS,
        follow_redirects=True,   # _risolvi_search_by_image_id dipende dal redirect
        proxy=proxy_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


async def inizializza_client_http():
    """Crea i client httpx. Va chiamata DENTRO il loop asyncio (da main()),
    mai a import-time: un AsyncClient costruito fuori dal loop che poi lo
    usera' e' una sorgente classica di 'Event loop is closed' e di
    connessioni che non vengono mai riutilizzate."""
    global _client_generico, _client_telegram, _CLIENT_VINTED_AUTH
    if PROXY_LIST:
        for proxy_url in PROXY_LIST:
            _CLIENT_VINTED_POOL.append(_crea_client_vinted(proxy_url))
    else:
        _CLIENT_VINTED_POOL.append(_crea_client_vinted(None))

    # Client dedicato all'account Vinted autenticato (vedi commento sopra
    # _CLIENT_VINTED_AUTH): pinnato a UN SOLO proxy (il primo della lista, se
    # presente) invece che in rotazione, cosi' anche l'IP resta coerente tra
    # il refresh del token e la chiamata search_by_image_id -- un cambio di
    # IP a meta' sessione autenticata sarebbe un altro segnale anomalo per
    # l'anti-bot, oltre al cookie jar.
    _CLIENT_VINTED_AUTH = _crea_client_vinted(PROXY_LIST[0] if PROXY_LIST else None)

    _client_generico = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(90.0, connect=15.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )
    _client_telegram = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )
    log.info(
        "Client HTTP asincroni pronti: %d client Vinted (%s), 1 generico, 1 Telegram.",
        len(_CLIENT_VINTED_POOL),
        f"{len(PROXY_LIST)} proxy in rotazione" if PROXY_LIST else "nessun proxy, richieste dirette",
    )


async def chiudi_client_http():
    """Chiusura ordinata: senza questa httpx logga warning di socket non
    chiusi allo spegnimento del processo."""
    for client in _CLIENT_VINTED_POOL:
        await client.aclose()
    for client in (_client_generico, _client_telegram, _CLIENT_VINTED_AUTH):
        if client is not None:
            await client.aclose()


def _prossimo_client_vinted():
    """Prossimo client Vinted in rotazione round-robin (uno per proxy).
    Sostituisce _prossimo_proxy: la rotazione ora e' tra client, non tra
    dict di proxy passati alla singola richiesta."""
    client = _CLIENT_VINTED_POOL[_proxy_indice_rotazione[0] % len(_CLIENT_VINTED_POOL)]
    _proxy_indice_rotazione[0] += 1
    return client


_vinted_refresh_lock = asyncio.Lock()


async def _rinnova_token_vinted():
    """Rinnova access_token_web/refresh_token_web chiamando l'endpoint di
    refresh catturato dall'utente via DevTools il 2026-09-20
    (POST /web/api/auth/refresh, richiede un x-csrf-token fresco preso dalla
    home page).

    NON VERIFICATO IN PRODUZIONE al momento della scrittura: non e' confermato
    ne' il formato esatto del meta tag CSRF nella home ne' che la risposta del
    refresh contenga davvero nuovi cookie access_token_web/refresh_token_web
    (l'utente ha catturato solo la richiesta, non la risposta). Per questo la
    funzione logga in dettaglio cosa arriva davvero (status, corpo troncato,
    nomi dei cookie ricevuti) invece di assumerlo -- se il formato reale e'
    diverso, il prossimo log di produzione lo mostra e si corregge il parsing
    senza dover indovinare una seconda volta.

    Fallisce in modo sicuro: in caso di qualunque errore o risposta inattesa
    ritorna False senza toccare _VINTED_COOKIES, quindi il chiamante si
    comporta esattamente come se il refresh automatico non esistesse (fonte
    visuale saltata per questo item, nessuna rottura del resto della
    pipeline)."""
    refresh_token = _VINTED_COOKIES.get("refresh_token_web")
    if not refresh_token or _jwt_scaduto(refresh_token):
        log.warning(
            "_rinnova_token_vinted: refresh_token_web assente o scaduto -- serve un nuovo "
            "VINTED_REFRESH_TOKEN su Railway (nessun refresh automatico possibile da qui)."
        )
        return False

    # Client DEDICATO (_CLIENT_VINTED_AUTH, non il pool anonimo): lo stesso
    # client viene riusato per il refresh e per search_by_image_id, cosi'
    # httpx accumula da solo nel suo jar i cookie Datadome/sessione coerenti
    # con questo account -- vedi il lungo commento sopra la definizione di
    # _CLIENT_VINTED_AUTH per il perche'.
    client = _CLIENT_VINTED_AUTH
    # Cookie JWT passati ESPLICITAMENTE (non allegati a costruzione, vedi
    # _crea_client_vinted): httpx li aggiunge solo alla richiesta corrente
    # (in merge col jar persistente del client, che qui e' voluto: e' proprio
    # quel jar a portare i cookie anti-bot coerenti).
    cookies_auth = {k: v for k, v in _VINTED_COOKIES.items() if v}

    # Passo 1: CSRF token fresco dalla home page -- SENZA cookie (fix
    # 2026-09-20, verificato in produzione: mandare qui l'access_token_web
    # ormai scaduto faceva reindirizzare Vinted a /session-refresh invece di
    # servire la home page vera, quindi il meta tag CSRF non c'era mai e il
    # refresh falliva sempre in loop). La home e' una pagina pubblica, non
    # serve autenticazione per leggerla -- il refresh_token_web va mandato
    # solo sulla POST di refresh qui sotto, dove serve davvero. Pattern del
    # meta tag comunque non confermato al 100% su una risposta reale -- se
    # fallisce ancora lo si vede nel log qui sotto e si aggiusta la regex.
    try:
        resp_home = await client.get("https://www.vinted.it/", timeout=15.0)
        resp_home.raise_for_status()
    except Exception as e:
        log.warning("_rinnova_token_vinted: GET home page fallita: %s", e)
        return False
    # Pattern corretto il 2026-09-20 dopo verifica su HTML reale (view-source
    # fornito dall'utente): NON e' un <meta name="csrf-token">, e' la chiave
    # "CSRF_TOKEN" dentro un blob di config JSON incorporato nella pagina
    # (con virgolette escaped, es. \"CSRF_TOKEN\":\"75f6c9fa-...\"). Il
    # pattern vecchio (meta tag) non ha mai trovato nulla in produzione.
    m_csrf = re.search(r'CSRF_TOKEN\\?"\s*:\s*\\?"([0-9a-fA-F-]{20,40})', resp_home.text)
    if not m_csrf:
        log.warning(
            "_rinnova_token_vinted: CSRF_TOKEN non trovato nella home page -- "
            "il markup potrebbe essere cambiato di nuovo. Refresh annullato."
        )
        return False
    csrf_token = m_csrf.group(1)

    # Passo 2: POST di refresh con il CSRF token.
    headers_refresh = dict(VINTED_HEADERS)
    headers_refresh.update({
        "accept": "application/json, text/plain, */*",
        "referer": "https://www.vinted.it/session-refresh?ref_url=%2F",
        "x-csrf-token": csrf_token,
    })
    try:
        resp = await client.post(
            "https://www.vinted.it/web/api/auth/refresh", headers=headers_refresh, timeout=15.0,
            cookies=cookies_auth,
        )
    except Exception as e:
        log.warning("_rinnova_token_vinted: chiamata all'endpoint di refresh fallita: %s", e)
        return False

    if resp.status_code >= 400:
        log.warning(
            "_rinnova_token_vinted: refresh HTTP %d, corpo: %s",
            resp.status_code, resp.text[:300],
        )
        return False

    # Log dei nomi dei cookie ricevuti PRIMA di assumere quali siano quelli
    # giusti -- e' il punto non verificato di tutta la funzione.
    nomi_cookie_ricevuti = list(resp.cookies.keys())
    log.info("_rinnova_token_vinted: refresh HTTP %d, cookie ricevuti: %s",
              resp.status_code, nomi_cookie_ricevuti)

    nuovo_access = resp.cookies.get("access_token_web")
    nuovo_refresh = resp.cookies.get("refresh_token_web")
    if not nuovo_access:
        log.warning(
            "_rinnova_token_vinted: risposta HTTP %d ma nessun cookie 'access_token_web' "
            "nella risposta (cookie ricevuti: %s) -- il formato reale e' probabilmente "
            "diverso da quello previsto, va corretto guardando questo log.",
            resp.status_code, nomi_cookie_ricevuti,
        )
        return False

    _VINTED_COOKIES["access_token_web"] = nuovo_access
    _VINTED_COOKIES["refresh_token_web"] = nuovo_refresh or refresh_token

    # NIENTE piu' propagazione ai client del pool (rimossa il 2026-09-20):
    # da quando _crea_client_vinted non allega piu' i cookie a costruzione,
    # non c'e' nessun cookie jar condiviso da tenere sincronizzato -- ogni
    # chiamata autenticata (qui e in _risolvi_search_by_image_id) legge
    # _VINTED_COOKIES freschi e li passa esplicitamente sulla propria
    # richiesta, quindi il valore appena aggiornato sopra e' gia' quello
    # che verra' usato dalla prossima chiamata.

    # Persistenza su /data (Volume Railway "vinted-tokens", 2026-09-20):
    # sopravvive ai riavvii/redeploy. Il try/except resta comunque -- se il
    # Volume viene rimosso o il path cambia, un errore qui non deve rompere
    # il refresh appena riuscito, solo la sua persistenza tra un riavvio e
    # l'altro.
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(_VINTED_COOKIES, f)
    except Exception as e:
        log.warning("_rinnova_token_vinted: impossibile salvare %s: %s", TOKEN_FILE, e)

    log.info("_rinnova_token_vinted: access token Vinted rinnovato con successo.")
    return True


# Rate-limit Vinted: la pausa minima tra due richieste consecutive va
# rispettata GLOBALMENTE, anche ora che piu' annunci vengono elaborati in
# parallelo. Senza lock, due task concorrenti leggerebbero lo stesso
# timestamp "ultima richiesta", calcolerebbero la stessa attesa e
# partirebbero insieme -- cioe' esattamente la raffica che ha prodotto i
# 403 dopo ~13h di attivita' continua. Il lock serializza SOLO l'attesa e
# l'aggiornamento del timestamp, non la richiesta vera e propria.
_vinted_rate_limit_lock = asyncio.Lock()


async def _attendi_turno_vinted():
    async with _vinted_rate_limit_lock:
        tempo_trascorso = time.monotonic() - _vinted_timestamp_ultima_richiesta[0]
        attesa = PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI - tempo_trascorso
        if attesa > 0:
            await asyncio.sleep(attesa)
        _vinted_timestamp_ultima_richiesta[0] = time.monotonic()


async def _vinted_get_con_retry(url, timeout=15, max_retries=3, headers_extra=None, cookies_extra=None, client_override=None):
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
    toccano le altre chiamate.

    cookies_extra (aggiunto il 2026-09-20): cookie SOLO per questa singola
    chiamata, passati direttamente a httpx invece che attaccati al client
    condiviso -- scelta esplicita dell'utente per tenere l'account Vinted
    dedicato (usato per la ricerca visuale, vedi _risolvi_search_by_image_id)
    completamente separato dal pool anonimo usato per lo scraping normale
    di annunci/venditori. Nessun impatto sulle altre chiamate: httpx aggiunge
    i cookie solo all'header Cookie di QUESTA richiesta, non li salva nel
    cookie jar persistente del client.

    client_override (aggiunto il 2026-09-20): usa questo client httpx invece
    di farne uno in round-robin dal pool anonimo -- serve per la sessione
    autenticata (_CLIENT_VINTED_AUTH, vedi il commento li' sopra), che deve
    SEMPRE riusare lo stesso client per tenere coerenti IP e cookie jar tra
    il refresh del token e la ricerca visuale vera e propria."""
    headers_richiesta = VINTED_HEADERS if not headers_extra else {**VINTED_HEADERS, **headers_extra}

    ultimo_errore = None
    for tentativo in range(1, max_retries + 1):
        await _attendi_turno_vinted()
        try:
            client = client_override if client_override is not None else _prossimo_client_vinted()
            resp = await client.get(url, headers=headers_richiesta, cookies=cookies_extra, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            ultimo_errore = e
            if tentativo < max_retries:
                # Su 403 (probabile rate-limit) attende piu' a lungo del
                # normale backoff, dando al blocco lato Vinted il tempo di
                # attenuarsi prima del prossimo tentativo. Ora e' un'attesa
                # asincrona: non blocca il resto del bot.
                e_403 = "403" in str(e)
                attesa = (6.0 * tentativo) if e_403 else (1.5 * tentativo)
                await asyncio.sleep(attesa)
                continue
    log.warning("Scraping Vinted fallito dopo %d tentativi per %s: %s", max_retries, url, ultimo_errore)
    return None


async def scrape_vinted_listing(url):
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
        resp = await _vinted_get_con_retry(url, timeout=15, max_retries=3)
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
                resp_profilo = await _vinted_get_con_retry(profilo_url, timeout=12, max_retries=2)
                if resp_profilo is not None and resp_profilo.is_success:
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


async def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=3):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    # TEMP DIAGNOSTIC: this used to swallow every failure silently (bare
    # "except Exception: pass" and no logging even on a non-ok status), so
    # there was no way to tell a 403/429 rate-limit apart from a timeout or
    # a proxy connection failure from the logs alone. Remove once diagnosed.
    ultimo_dettaglio = None
    for attempt in range(1, max_retries + 1):
        try:
            client = _prossimo_client_vinted()
            resp = await client.get(url, headers=headers, timeout=18)
            if resp.is_success:
                return resp.content
            ultimo_dettaglio = f"HTTP {resp.status_code}"
        except Exception as e:
            ultimo_dettaglio = f"{type(e).__name__}: {e}"
        await asyncio.sleep(0.6 * attempt)
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


def _costruisci_parts_foto_sync(photo_bytes_list):
    parts = []
    for img_bytes in photo_bytes_list:
        optimized = optimize_image_bytes(img_bytes)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(optimized).decode("utf-8")}})
    return parts


async def costruisci_parts_foto(photo_bytes_list):
    """Ridimensionamento PIL + base64 di 10 foto e' lavoro CPU puro: dentro
    il loop asyncio bloccherebbe tutto per qualche centinaio di millisecondi
    per annuncio, proprio mentre altri annunci stanno aspettando risposte di
    rete. asyncio.to_thread lo sposta su un thread worker e lascia il loop
    libero. E' l'unico punto del bot dove serve ancora un thread: tutto il
    resto e' attesa di rete, che asyncio gestisce nativamente."""
    if not photo_bytes_list:
        return []
    return await asyncio.to_thread(_costruisci_parts_foto_sync, photo_bytes_list)


def costo_gemini_token(usage, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT):
    inp = usage.get("promptTokenCount", 0) or 0
    out = usage.get("candidatesTokenCount", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


async def chiama_gemini(system_prompt, user_text, photo_bytes_list=None, grounding=False, max_retries=4,
                        api_url=GEMINI_API_URL_OCCHIO, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT,
                        response_schema=None):
    """response_schema: se valorizzato, la risposta e' JSON conforme allo
    schema invece che prosa libera (usato dall'Occhio con
    OCCHIO_OUTPUT_JSON=true). Il testo ritornato e' il JSON grezzo: a
    deserializzarlo e validarlo ci pensa il chiamante."""
    photo_bytes_list = photo_bytes_list or []
    parts = [{"text": user_text}] + await costruisci_parts_foto(photo_bytes_list)

    generation_config = {
        "temperature": 0.2, "maxOutputTokens": 3000,
        "thinkingConfig": {"thinkingLevel": "low"},
    }
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
        "generationConfig": generation_config,
    }
    if response_schema is not None:
        # L'API rifiuta responseMimeType/responseSchema insieme a "tools"
        # ("Function calling with a response mime type: 'application/json'
        # is unsupported"): e' lo stesso vincolo che ha imposto le due fasi
        # separate nel Cervello. Qui grounding non serve (l'Occhio e' sempre
        # invocato con grounding=False), ma la guardia evita che una futura
        # modifica produca un 400 difficile da diagnosticare.
        if grounding:
            log.warning("chiama_gemini: grounding ignorato, incompatibile con response_schema.")
            grounding = False
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
    if grounding:
        payload["tools"] = [{"google_search": {}}]

    backoff_seconds = 2
    for attempt in range(1, max_retries + 1):
        try:
            resp = await _client_generico.post(api_url, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
            if not resp.is_success:
                log.warning("Gemini HTTP %d: %s", resp.status_code, resp.text[:500])
            if resp.is_success:
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
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(backoff_seconds)
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


# Snippet-placeholder che Google/Serper restituisce quando non riesce a
# generare un estratto reale (pagina JS-rendered, bloccata, o senza testo
# indicizzabile) -- puro rumore, occupa spazio nel contesto del cervello
# senza portare ne' un prezzo ne' informazione utile.
SNIPPET_PLACEHOLDER_INUTILI = [
    "nessuna informazione disponibile per questa pagina",
]

# Simboli di valuta non-EUR il cui prezzo non e' direttamente comparabile
# senza conversione (mercati regionali: baht thailandese, yen, rupia, won,
# ecc.) -- un risultato che ha SOLO questi simboli di prezzo (nessun
# €/EUR/$/USD/£/GBP nello snippet) va scartato perche' il cervello non ha
# modo di convertirlo in modo affidabile e rischia di trattarlo come comp
# diretto.
SIMBOLI_VALUTA_NON_COMPARABILI = ["฿", "¥", "₹", "₩", "₫", "₱"]
SIMBOLI_VALUTA_COMPARABILI = ["€", "eur", "$", "usd", "£", "gbp"]


def _riga_serper_e_rumore(titolo, snippet):
    """True se la riga (titolo+snippet) di un risultato Google/Serper va
    scartata perche' non porta informazione utile al cervello -- vedi
    SNIPPET_PLACEHOLDER_INUTILI e SIMBOLI_VALUTA_NON_COMPARABILI sopra per
    il dettaglio dei due casi coperti, individuati da un caso reale
    (ricerca on-demand 'GU x Undercover Cargo' che restituiva pagine eBay
    senza snippet e annunci in thailandese con prezzi in baht)."""
    testo_completo = f"{titolo} {snippet}".strip()
    if not testo_completo:
        return True
    # .rstrip(".") perche' Google a volte restituisce il placeholder con un
    # punto finale ("...pagina.") e a volte senza -- confermato empiricamente
    # nel caso reale che ha originato questo filtro (vedi log 'gu × undercover').
    snippet_lower = snippet.strip().lower().rstrip(".")
    if snippet_lower in SNIPPET_PLACEHOLDER_INUTILI:
        return True
    ha_valuta_non_comparabile = any(simbolo in testo_completo for simbolo in SIMBOLI_VALUTA_NON_COMPARABILI)
    ha_valuta_comparabile = any(simbolo in testo_completo.lower() for simbolo in SIMBOLI_VALUTA_COMPARABILI)
    if ha_valuta_non_comparabile and not ha_valuta_comparabile:
        return True
    return False


async def cerca_serper_mirata(query):
    """Ricerca aggiuntiva mirata, richiamabile dal cervello quando i comp
    pre-raccolti sono insufficienti o fuori tema."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata)."
    payload = [{"q": query, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await _client_generico.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}"
    lines = []
    scartate = 0
    for batch in results:
        for r in batch.get("organic", [])[:8]:
            titolo = r.get("title", "")
            snippet = (r.get("snippet", "") or "")[:150]
            if _riga_serper_e_rumore(titolo, snippet):
                scartate += 1
                continue
            lines.append(f"- {titolo}: {snippet}")
    if scartate:
        log.info("cerca_serper_mirata: scartate %d righe di rumore (snippet vuoto/placeholder o valuta non comparabile) per query '%s'.", scartate, query)
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


# ---------------------------------------------------------------------------
# SCHEMA DI OUTPUT STRUTTURATO DEL CERVELLO (structured output / JSON mode)
# ---------------------------------------------------------------------------
# Sostituisce il verdetto in prosa e tutte le regex che ne estraevano i
# numeri. L'ordine di propertyOrdering NON e' cosmetico: Gemini genera i
# campi in quell'ordine, quindi e' letteralmente la catena di ragionamento
# imposta al modello -- prima si impegna per iscritto su brand e linea,
# poi elenca i comp, e solo alla fine produce il prezzo target. Non puo'
# sparare un numero prima di aver dichiarato su quale linea lo sta
# calcolando.
#
# VINCOLO API (documentato, non aggirabile): Gemini rifiuta una richiesta
# che contenga insieme function_declarations e responseMimeType
# "application/json" con l'errore "Function calling with a response mime
# type: 'application/json' is unsupported". Per questo la chiamata al
# cervello e' divisa in due fasi: i giri di ricerca usano i tools come
# prima, il giro finale toglie i tools dal payload e accende lo schema.
# Vedi chiama_gemini_cervello_forzato.
#
# Nota sui vincoli numerici: responseSchema accetta solo un sottoinsieme di
# OpenAPI, quindi qui non si usano pattern/minimum/maximum -- i limiti
# (sconto 20-30%, deal 1-10, tetti di prezzo) sono applicati in Python da
# valida_payload_cervello/calcola_verdetto, che e' comunque dove devono
# stare: un vincolo dichiarato nello schema verrebbe rispettato "quasi
# sempre", uno applicato in codice sempre.

CATEGORIE_CAPO_ENUM = sorted(CATEGORIA_TERMINE_EN.keys()) + ["non_determinabile"]

CERVELLO_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": [
        "brand_dichiarato_annuncio",
        "brand_reale_etichetta",
        "corrispondenza_brand",
        "linea_o_era_rilevata",
        "tetto_prezzo_linea_eur",
        "categoria_capo",
        "materiale_rilevato",
        "materiale_confermato",
        "taglia_rilevata",
        "fascia_taglia",
        "comp_candidati",
        "comp_riferimento_eur",
        "sconto_ask_applicato_pct",
        "prezzo_target_vendita_eur",
        "difetto_significativo",
        "difetto_strutturale",
        "gravita_difetto_strutturale",
        "sconto_difetto_pct",
        "descrizione_difetto",
        "giorni_stimati_vendita",
        "mese_consigliato_pubblicazione",
        "legit_verdetto",
        "legit_motivo_specifico",
        "rischio_fake",
        "confidenza",
        "profilo_venditore",
        "motivo_profilo_venditore",
        "domanda_mercato",
        "segnali_domanda",
        "deal_score",
        "note_analista",
        "domande_al_venditore",
        "messaggio_venditore_template",
    ],
    "properties": {
        # --- 1. ANCORAGGIO AL BRAND: il modello si impegna PRIMA di vedere numeri
        "brand_dichiarato_annuncio": {
            "type": "STRING",
            "description": "Brand come dichiarato nell'annuncio Vinted.",
        },
        "brand_reale_etichetta": {
            "type": "STRING",
            "nullable": True,
            "description": "Testo ESATTO letto sull'etichetta dall'analisi visiva. null se nessuna etichetta leggibile.",
        },
        "corrispondenza_brand": {
            "type": "STRING",
            "format": "enum",
            "enum": ["corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_verificabile"],
            "description": (
                "'sottolinea_stessa_maison' = MM6 per Margiela, See by Chloe per Chloe, "
                "Weekend per Max Mara: ha ancora valore, si valuta normalmente. "
                "'brand_estraneo' = marchio diverso e non correlato (es. Kapitales invece "
                "di Kapital): verdetto gia' scontato, nessun comp necessario."
            ),
        },
        "linea_o_era_rilevata": {
            "type": "STRING",
            "description": (
                "Linea o era precisa secondo la tabella LINEE E ERE. Esempi validi: "
                "'Era Lang 1986-2005', 'Era Link Theory post-2006', 'Linea 10', 'MM6', "
                "\"JEAN'S PAUL GAULTIER\", \"JPG.JEAN'S\", 'Veilance', 'mainline', "
                "'non determinabile'."
            ),
        },
        "tetto_prezzo_linea_eur": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Tetto di rivendita imposto dalla linea quando la tabella ne prevede uno "
                "(es. 30 per JEAN'S PAUL GAULTIER). null se nessun tetto si applica."
            ),
        },

        # --- 2. IDENTITA' DEL CAPO
        "categoria_capo": {
            "type": "STRING",
            "format": "enum",
            "enum": CATEGORIE_CAPO_ENUM,
        },
        "materiale_rilevato": {"type": "STRING", "nullable": True},
        "materiale_confermato": {
            "type": "BOOLEAN",
            "description": (
                "true se il materiale compare ESPLICITAMENTE nel titolo, nella descrizione, "
                "nei dati strutturati dell'annuncio, o e' leggibile su etichetta -- non serve "
                "una foto ravvicinata della sola etichetta di composizione (es. titolo "
                "'Kaschmir Pullover' = true). false SOLO se il materiale non e' menzionato da "
                "nessuna parte e andrebbe indovinato dalla sola foto generica: in quel caso il "
                "sistema abbassa la stima al 75* percentile dei comp validi invece che al piu' caro."
            ),
        },
        "taglia_rilevata": {"type": "STRING", "nullable": True},
        "fascia_taglia": {
            "type": "STRING",
            "format": "enum",
            "enum": ["centrale", "estrema", "ignota"],
            "description": (
                "centrale = donna IT 40-44 / uomo IT 48-52 (bacino ampio). "
                "estrema = fuori da quelle fasce: riduce liquidita' e domanda."
            ),
        },

        # --- 3. COMP: prezzi verbatim, un oggetto per comp, niente prosa
        "comp_candidati": {
            "type": "ARRAY",
            "minItems": 0,
            "description": (
                "OGNI prezzo comp valutato, anche quelli scartati. I prezzi presi dai dati "
                "ricevuti vanno copiati alla lettera; quelli che vengono dalla tua "
                "conoscenza del brand vanno marcati fonte='memoria_modello'."
            ),
            "items": {
                "type": "OBJECT",
                "propertyOrdering": [
                    "titolo_verbatim", "prezzo_eur", "fonte",
                    "stessa_categoria", "stessa_linea", "corrispondenza_materiale",
                    "escluso", "motivo_esclusione",
                ],
                "properties": {
                    "titolo_verbatim": {
                        "type": "STRING",
                        "description": "Titolo del comp copiato alla lettera dai dati ricevuti.",
                    },
                    "prezzo_eur": {
                        "type": "NUMBER",
                        "description": "Prezzo in euro. Se viene dai dati ricevuti, copiato alla lettera, mai arrotondato.",
                    },
                    "fonte": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["vinted_testo", "vinted_visuale", "memoria_modello"],
                        "description": (
                            "'memoria_modello' = prezzo che ricordi tu, non presente nei dati "
                            "ricevuti in questa conversazione. Dichiararlo e' obbligatorio e non "
                            "comporta alcuna penalizzazione."
                        ),
                    },
                    "stessa_categoria": {"type": "BOOLEAN"},
                    "stessa_linea": {
                        "type": "BOOLEAN",
                        "description": "false per Y-3 su Yohji, McQ su McQueen, See by Chloe su Chloe, MM6 su Margiela mainline.",
                    },
                    "corrispondenza_materiale": {
                        "type": "STRING",
                        "format": "enum",
                        "enum": ["stesso", "diverso", "ignoto"],
                    },
                    "escluso": {"type": "BOOLEAN"},
                    "motivo_esclusione": {"type": "STRING", "nullable": True},
                },
                "required": [
                    "titolo_verbatim", "prezzo_eur", "fonte",
                    "stessa_categoria", "stessa_linea", "corrispondenza_materiale", "escluso",
                ],
            },
        },
        "comp_riferimento_eur": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Il prezzo, tra i comp NON esclusi, su cui ancori la stima. Deve essere uno "
                "dei prezzo_eur dichiarati sopra. null se non c'e' nessun comp valido."
            ),
        },
        "sconto_ask_applicato_pct": {
            "type": "INTEGER",
            "description": "Sconto prudenziale applicato al comp ASK di riferimento, tra 20 e 30.",
        },

        # --- 4. L'UNICO NUMERO ECONOMICO CHE IL MODELLO PRODUCE
        "prezzo_target_vendita_eur": {
            "type": "NUMBER",
            "description": (
                "Prezzo LORDO di listing previsto. NON calcolare margine, ROI, incasso o "
                "costo d'acquisto: li calcola il sistema. Non puo' superare il comp di "
                "riferimento gia' scontato, ne' tetto_prezzo_linea_eur."
            ),
        },
        # --- difetto del capo (NON il materiale, NON lo sconto ASK dei comp):
        # riguarda SOLO le condizioni di QUESTO esemplare specifico. Il
        # sistema applica sconto_difetto_pct come ulteriore riduzione
        # moltiplicativa sul prezzo target, DOPO tutti gli altri limiti --
        # prima non esisteva nessun controllo numerico su questo, un difetto
        # descritto in note_analista poteva non riflettersi affatto nel
        # prezzo finale se il cervello si "dimenticava" di scontarlo da solo.
        "difetto_significativo": {
            "type": "BOOLEAN",
            "description": (
                "true se il capo ha un difetto che un compratore noterebbe e che ne riduce "
                "il valore (macchia, buco, filo tirato, cerniera/bottone rotto, alterazione, "
                "usura marcata, foro di spilla, scolorimento, ecc.). false per normale segno "
                "d'uso di un capo second-hand descritto come 'ottime condizioni' senza difetti "
                "specifici citati."
            ),
        },
        "difetto_strutturale": {
            "type": "BOOLEAN",
            "description": (
                "true se ALMENO UNO dei difetti compromette l'uso o la rivendibilita' del "
                "capo: buco aperto, strappo, tessuto lacerato, cuciture saltate su una "
                "giuntura portante, cerniera rotta non sostituibile, muffa. false per difetti "
                "estetici recuperabili (pilling, macchia lavabile, filo tirato, foro di "
                "spilla, bottone mancante sostituibile). Non decide da solo il blocco: e' "
                "`gravita_difetto_strutturale` che stabilisce se il capo resta vendibile a "
                "forte sconto o se e' invendibile -- vedi sotto."
            ),
        },
        "gravita_difetto_strutturale": {
            "type": "STRING",
            "format": "enum",
            "enum": ["lieve", "moderata", "grave"],
            "nullable": True,
            "description": (
                "Obbligatorio (non null) se difetto_strutturale=true, altrimenti null. Caso "
                "reale che ha corretto questa regola: una t-shirt Jean Paul Gaultier d'archivio "
                "con un piccolo foro isolato sulla manica in tessuto a rete -- il sistema la "
                "scartava sempre come invendibile, ma un difetto cosi' piccolo e localizzato su "
                "un pezzo d'archivio resta perfettamente vendibile a sconto, dichiarato in "
                "descrizione. 'lieve' = difetto strutturale ma PICCOLO e LOCALIZZATO (un foro "
                "isolato, pochi cm di cucitura saltata su una giuntura secondaria): il capo "
                "resta vendibile a forte sconto, NON viene bloccato automaticamente. "
                "'moderata' = piu' esteso o su una giuntura piu' portante, ma il capo e' ancora "
                "indossabile e vendibile dichiarandolo: non bloccato, ma il prezzo deve "
                "riflettere il rischio (sconto_difetto_pct alto, verso il 50%). 'grave' = il "
                "capo e' sostanzialmente invendibile: piu' difetti strutturali combinati, area "
                "ampia compromessa, cerniera principale inutilizzabile, capo che rischia di "
                "peggiorare con il solo indossarlo. SOLO 'grave' fa scattare il blocco "
                "automatico a NON COMPRARE; 'lieve' e 'moderata' restano un capo normalmente "
                "valutabile, scontato tramite sconto_difetto_pct come ogni altro difetto. Nel "
                "dubbio tra 'moderata' e 'grave', scegli 'grave': e' la scelta prudente."
            ),
        },
        "sconto_difetto_pct": {
            "type": "NUMBER",
            "nullable": True,
            "description": (
                "Percentuale di sconto (0-50) da applicare al prezzo target per via del "
                "difetto, proporzionata alla gravita': difetto lieve/quasi invisibile ~5-10%, "
                "difetto visibile ma non strutturale (piccolo foro, filo tirato, macchia "
                "leggera) ~15-25%, difetto strutturale o che compromette l'uso (strappo, "
                "cerniera rotta, macchia estesa) ~30-50%. Pesa anche POSIZIONE e VISIBILITA', "
                "non solo dimensione: lo stesso foro conta meno se e' sotto l'ascella, sul "
                "retro o in un punto normalmente coperto, conta di piu' se e' sul petto, su una "
                "manica in vista o su un bordo. Non serve (e non va fatto) un trattamento "
                "diverso per marchio o rarita' del capo: quello e' gia' incorporato nel prezzo "
                "dei comp che stai scontando, un secondo aggiustamento lo conterebbe due volte. "
                "0 o null se difetto_significativo "
                "e' false. Decidilo tu in base a quanto descritto/visto, il sistema si limita "
                "ad applicarlo: non scontarlo gia' tu dentro prezzo_target_vendita_eur, "
                "altrimenti verrebbe scontato due volte."
            ),
        },
        "descrizione_difetto": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Cosa e' il difetto, in poche parole (es. 'piccolo foro da spilla sulla manica "
                "sinistra'). null se difetto_significativo e' false."
            ),
        },

        "giorni_stimati_vendita": {"type": "INTEGER"},
        "mese_consigliato_pubblicazione": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Solo se il capo e' fuori stagione (capispalla invernali da settembre, "
                "capi estivi da aprile). La stagionalita' allunga i tempi, non abbassa il prezzo."
            ),
        },

        # --- 5. LEGIT E RISCHIO
        "legit_verdetto": {
            "type": "STRING",
            "format": "enum",
            "enum": [
                "probabilmente_autentico",
                "sospetto_servono_altre_foto",
                "probabilmente_falso",
                "non_verificabile",
            ],
        },
        "legit_motivo_specifico": {
            "type": "STRING",
            "description": (
                "Discrepanza concreta: font dell'etichetta e in cosa differisce, proporzioni "
                "del logo, cuciture, materiale, wash tag incoerente, hardware. Vietate le "
                "formule generiche ('font grossolano', 'dettagli generici'). Obbligatorio e "
                "circostanziato quando il verdetto e' probabilmente_falso."
            ),
        },
        "rischio_fake": {
            "type": "STRING", "format": "enum",
            "enum": ["basso", "medio", "alto", "molto_alto"],
        },
        "confidenza": {
            "type": "STRING", "format": "enum",
            "enum": ["alta", "media", "bassa"],
        },

        # --- 6. VENDITORE E DOMANDA (input dell'urgenza, calcolata in Python)
        "profilo_venditore": {
            "type": "STRING", "format": "enum",
            "enum": ["privato_genuino", "reseller_esperto", "non_determinabile"],
        },
        "motivo_profilo_venditore": {
            "type": "STRING",
            "description": (
                "Deve citare esplicitamente il contenuto di 'Primi articoli in vendita' "
                "quando presente nei dati, non il solo numero di recensioni."
            ),
        },
        "domanda_mercato": {
            "type": "STRING", "format": "enum",
            "enum": ["alta", "media", "bassa"],
            "description": (
                "Domanda per QUESTO modello a QUESTA taglia, indipendente da margine e ROI. "
                "'alta' richiede segnali concreti elencati in segnali_domanda."
            ),
        },
        "segnali_domanda": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "Segnali concreti e verificabili. Array vuoto se non ce ne sono.",
        },
        "deal_score": {"type": "INTEGER", "description": "Qualita' complessiva del deal, da 1 a 10."},

        # --- 7. TESTO PER TELEGRAM (nessun numero finanziario qui dentro)
        "note_analista": {
            "type": "STRING",
            "description": (
                "3-5 righe: ragionamento sui comp e commento esplicito sul profilo/guardaroba "
                "del venditore. Non scrivere margine, ROI o decisione: li inserisce il sistema."
            ),
        },
        "domande_al_venditore": {
            "type": "ARRAY",
            "maxItems": 2,
            "items": {"type": "STRING"},
            "description": (
                "Array vuoto se non servono davvero per legit-check, difetti o trattativa. "
                "Non riempirlo per curiosita'."
            ),
        },
        "messaggio_venditore_template": {
            "type": "STRING",
            "nullable": True,
            "description": (
                "Messaggio pronto per il venditore. Se serve indicare un'offerta scrivi "
                "ESATTAMENTE il segnaposto {OFFERTA}: l'importo lo calcola e lo sostituisce "
                "il sistema. Non scrivere mai una cifra in euro qui dentro. null se non serve "
                "nessun messaggio."
            ),
        },
    },
    "required": [
        "brand_dichiarato_annuncio", "corrispondenza_brand", "linea_o_era_rilevata",
        "categoria_capo", "materiale_confermato", "fascia_taglia",
        "comp_candidati", "sconto_ask_applicato_pct", "prezzo_target_vendita_eur",
        "difetto_significativo", "difetto_strutturale", "gravita_difetto_strutturale",
        "giorni_stimati_vendita", "legit_verdetto", "legit_motivo_specifico",
        "rischio_fake", "confidenza", "profilo_venditore", "motivo_profilo_venditore",
        "domanda_mercato", "segnali_domanda", "deal_score", "note_analista",
        "domande_al_venditore",
    ],
}


def _schema_gemini_to_openai(schema):
    """Converte lo schema Gemini (dialetto OpenAPI, tipi MAIUSCOLI, nullable
    booleano, propertyOrdering) nel JSON Schema che OpenAI accetta in
    response_format.json_schema con strict=true.

    Esiste per avere UNA sola fonte di verita': lo schema si scrive una
    volta sopra, e il ramo OpenAI (CERVELLO_PROVIDER=openai) ne riceve
    automaticamente la traduzione. Senza questa funzione i due schemi
    divergerebbero alla prima modifica, ed e' esattamente il tipo di
    disallineamento silenzioso che questo refactor serve a eliminare.

    Regole di strict=true che la conversione deve rispettare:
    - additionalProperties: false su ogni oggetto;
    - OGNI property elencata in "required" (gli opzionali si esprimono con
      un tipo unione che include "null", non omettendoli da required);
    - niente propertyOrdering/format:enum (ignorati o rifiutati da OpenAI).
    """
    if not isinstance(schema, dict):
        return schema

    tipo = schema.get("type")
    convertito = {}

    if isinstance(tipo, str):
        tipo_lower = tipo.lower()
        if tipo_lower == "integer":
            tipo_lower = "integer"
        convertito["type"] = [tipo_lower, "null"] if schema.get("nullable") else tipo_lower

    for chiave in ("description", "enum", "minItems", "maxItems"):
        if chiave in schema:
            convertito[chiave] = schema[chiave]

    if "properties" in schema:
        convertito["properties"] = {
            nome: _schema_gemini_to_openai(sotto_schema)
            for nome, sotto_schema in schema["properties"].items()
        }
        # strict=true pretende che TUTTE le property siano in required.
        convertito["required"] = list(schema["properties"].keys())
        convertito["additionalProperties"] = False

    if "items" in schema:
        convertito["items"] = _schema_gemini_to_openai(schema["items"])

    return convertito


CERVELLO_RESPONSE_SCHEMA_OPENAI = _schema_gemini_to_openai(CERVELLO_RESPONSE_SCHEMA)


MAX_ROUNDS_FUNZIONE = 2  # Rialzato da 1 a 2 il 2026-09-14. Con 1, i log
                         # mostravano che ~1 item su 2 finiva comunque nel
                         # fallback forzato, che nel caso peggiore costa
                         # quanto il vecchio "2 giri" (3 chiamate totali) ma
                         # senza dare al modello la seconda ricerca reale che
                         # chiedeva. Con 2 il caso "un giro basta" costa
                         # uguale a prima, il caso "serve una seconda ricerca"
                         # costa quanto il vecchio fallback ma con una
                         # ricerca vera al posto del rifiuto secco.

ISTRUZIONE_FASE_JSON = (
    "Le ricerche sono terminate. Produci ORA il verdetto come oggetto JSON "
    "conforme allo schema, usando esclusivamente i dati e i comp raccolti in "
    "questa conversazione. Ricorda: non calcolare margine, ROI, decisione, "
    "urgenza o importi di trattativa, e marca fonte='memoria_modello' ogni "
    "prezzo che non compare nei dati ricevuti."
)


def _estrai_testo_da_parts(parts):
    return "".join(p.get("text", "") for p in (parts or []) if isinstance(p, dict))


async def chiama_gemini_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4,
                                         api_url=GEMINI_API_URL_CERVELLO,
                                         prezzo_input=PREZZO_CERVELLO_INPUT,
                                         prezzo_output=PREZZO_CERVELLO_OUTPUT):
    """Cervello Gemini in DUE FASI, imposte da un vincolo dell'API.

    FASE 1 -- RICERCA (fino a MAX_ROUNDS_FUNZIONE giri): function calling
    come prima. Con forza_ricerca=True il primo giro DEVE chiamare
    cerca_comp_prezzo (mode ANY), i successivi sono liberi (AUTO).

    FASE 2 -- VERDETTO (un solo giro): "tools" e "tool_config" vengono
    TOLTI dal payload e si accendono responseMimeType="application/json" +
    responseSchema. L'output e' quindi un oggetto conforme a
    CERVELLO_RESPONSE_SCHEMA, non piu' prosa da cui pescare numeri con
    espressioni regolari.

    Perche' due fasi e non una: Gemini rifiuta un payload che contenga
    insieme function_declarations e responseMimeType "application/json"
    ("Function calling with a response mime type: 'application/json' is
    unsupported"). Non e' un bug transitorio ma una limitazione
    documentata, quindi la separazione e' strutturale, non un workaround
    temporaneo.

    Effetto collaterale positivo: sparisce l'intera classe di bug che
    affliggeva la vecchia ultima fase. Prima, per impedire al modello di
    restituire l'ennesima functionCall al posto del verdetto, servivano un
    "mode: NONE" dichiarato esplicitamente, un tentativo di fallback senza
    tools e una diagnostica sul testo vuoto (vedi lo storico dei commenti
    del 2026-09-13). Ora, con responseMimeType="application/json", il
    modello non ha piu' un canale per emettere una functionCall: l'unico
    output sintatticamente valido e' l'oggetto JSON.

    Ritorna una tupla di 5 elementi:
      (verdetto_dict | None, errore | None, costo_totale, n_query_extra,
       ricerche_extra_raw)
    """
    contents = [{"role": "user", "parts": [{"text": user_text}]}]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []  # testo grezzo di ogni cerca_serper_mirata riuscita,
                             # usato per etichettare i comp che il cervello
                             # dichiara e per il blocco debug Telegram.

    async def _chiama_gemini_raw(tool_mode=None, json_mode=False, tentativi_rimasti=max_retries):
        generation_config = {
            "temperature": 0.2,
            "maxOutputTokens": 10000,
            "thinkingConfig": {"thinkingLevel": "low"},
        }
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "safetySettings": [
                {"category": c, "threshold": "BLOCK_NONE"} for c in (
                    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
            ],
            "generationConfig": generation_config,
        }

        if json_mode:
            # FASE 2. Niente "tools"/"tool_config" nel payload: con lo schema
            # attivo sarebbero rifiutati dall'API. La cronologia in "contents"
            # continua a contenere le coppie functionCall/functionResponse dei
            # giri di ricerca, ed e' accettata senza problemi -- lo stesso
            # schema (history con function parts, payload senza tools) era
            # gia' usato dal vecchio tentativo di fallback finale.
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = CERVELLO_RESPONSE_SCHEMA
        else:
            # FASE 1. maxOutputTokens piu' basso: qui il modello deve solo
            # formulare una query di ricerca, non il verdetto completo.
            generation_config["maxOutputTokens"] = 2000
            function_calling_config = {"mode": tool_mode}
            if tool_mode == "ANY":
                function_calling_config["allowed_function_names"] = ["cerca_comp_prezzo"]
            payload["tools"] = [{"function_declarations": [CERVELLO_FUNCTION_DECLARATION]}]
            payload["tool_config"] = {"function_calling_config": function_calling_config}

        backoff_seconds = 2
        for attempt in range(1, tentativi_rimasti + 1):
            try:
                resp = await _client_generico.post(
                    api_url, params={"key": GEMINI_API_KEY}, json=payload, timeout=90)
                if not resp.is_success:
                    log.warning("Gemini (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                    if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    resp.raise_for_status()
                return resp.json()
            except Exception:
                if attempt < tentativi_rimasti:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                raise
        raise RuntimeError("tentativi esauriti")

    # ---- FASE 1: giri di ricerca ------------------------------------------
    tool_mode = "ANY" if forza_ricerca else "AUTO"

    for round_idx in range(MAX_ROUNDS_FUNZIONE):
        try:
            data = await _chiama_gemini_raw(tool_mode=tool_mode)
        except Exception as e:
            log.warning("Cervello: fase ricerca fallita al giro %d (%s) -- si passa comunque al verdetto.", round_idx + 1, e)
            break

        candidates = data.get("candidates", [])
        if not candidates:
            log.warning("Cervello: nessun candidate nella fase di ricerca (giro %d).", round_idx + 1)
            break

        costo_totale += costo_gemini_token(data.get("usageMetadata", {}), prezzo_input, prezzo_output)

        parts = candidates[0].get("content", {}).get("parts", []) or []
        function_call = next((p.get("functionCall") for p in parts if p.get("functionCall")), None)

        if not function_call:
            # Il modello non vuole (piu') cercare: ha gia' abbastanza per
            # decidere. Si passa direttamente alla fase di verdetto; il testo
            # eventualmente prodotto qui viene scartato, perche' il verdetto
            # valido e' solo quello strutturato della fase 2.
            break

        query_richiesta = function_call.get("args", {}).get("query", "")
        log.info("Cervello Gemini ha richiesto ricerca mirata (giro %d/%d): '%s'",
                 round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
        risultato_ricerca = await cerca_serper_mirata(query_richiesta)
        n_query_extra += 1
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

    # ---- FASE 2: verdetto strutturato -------------------------------------
    contents.append({"role": "user", "parts": [{"text": ISTRUZIONE_FASE_JSON}]})

    try:
        data = await _chiama_gemini_raw(json_mode=True)
    except Exception as e:
        return None, f"chiamata al verdetto strutturato fallita: {e}", costo_totale, n_query_extra, ricerche_extra_raw

    candidates = data.get("candidates", [])
    if not candidates:
        return None, "risposta Gemini senza candidates nella fase di verdetto", costo_totale, n_query_extra, ricerche_extra_raw

    usage = data.get("usageMetadata", {})
    costo_totale += costo_gemini_token(usage, prezzo_input, prezzo_output)

    parts = candidates[0].get("content", {}).get("parts", []) or []
    testo_json = _estrai_testo_da_parts(parts).strip()
    finish_reason = candidates[0].get("finishReason", "?")

    if not testo_json:
        # Con lo schema attivo un output vuoto ha praticamente una sola
        # causa plausibile: troncamento. A differenza della prosa, un JSON
        # troncato non degrada (non e' "un verdetto un po' corto"), e'
        # inutilizzabile -- quindi va distinto e segnalato come tale invece
        # di finire in un generico "nessuna risposta testuale".
        if finish_reason == "MAX_TOKENS":
            return None, (
                "verdetto troncato: il JSON ha superato maxOutputTokens "
                f"(thinking={usage.get('thoughtsTokenCount', '?')} token). "
                "Se ricapita spesso, la causa piu' probabile e' un array "
                "comp_candidati molto lungo: alzare maxOutputTokens o "
                "accorciare titolo_verbatim nello schema."
            ), costo_totale, n_query_extra, ricerche_extra_raw
        log.warning(
            "Cervello: fase verdetto senza testo -- finishReason=%s, usage=%s, n_parts=%d, safetyRatings=%s",
            finish_reason, json.dumps(usage, ensure_ascii=False)[:300], len(parts),
            candidates[0].get("safetyRatings", "assenti"),
        )
        return None, f"il modello non ha prodotto il JSON del verdetto (finishReason={finish_reason})", costo_totale, n_query_extra, ricerche_extra_raw

    try:
        verdetto = json.loads(testo_json)
    except json.JSONDecodeError as e:
        log.warning("Cervello: JSON non parsabile (finishReason=%s): %s\nTESTO GREZZO: %s",
                    finish_reason, e, testo_json[:1000])
        return None, f"JSON del verdetto non parsabile ({e})", costo_totale, n_query_extra, ricerche_extra_raw

    if not isinstance(verdetto, dict):
        return None, "il JSON del verdetto non e' un oggetto", costo_totale, n_query_extra, ricerche_extra_raw

    return verdetto, None, costo_totale, n_query_extra, ricerche_extra_raw


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


OPENAI_RESPONSE_FORMAT_CERVELLO = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdetto_flip",
        "strict": True,
        "schema": CERVELLO_RESPONSE_SCHEMA_OPENAI,
    },
}


async def _chiama_openai_raw(messages, tentativi_rimasti, tools=None, tool_choice=None,
                             response_format=None, max_retries=4):
    payload = {
        "model": OPENAI_MODEL_CERVELLO,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    backoff_seconds = 2
    for attempt in range(1, tentativi_rimasti + 1):
        try:
            resp = await _client_generico.post(
                OPENAI_API_URL_CERVELLO, headers=headers, json=payload, timeout=90)
            if not resp.is_success:
                log.warning("OpenAI (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt < tentativi_rimasti:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            raise
    raise RuntimeError("tentativi esauriti")


async def chiama_openai_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4):
    """Equivalente OpenAI del cervello Gemini, stessa firma di ritorno a 5
    elementi per restare intercambiabile via CERVELLO_PROVIDER.

    Differenza tecnica rispetto a Gemini: OpenAI NON ha il vincolo
    "function calling incompatibile con structured output", quindi la
    separazione in due fasi qui non sarebbe obbligatoria. La manteniamo
    comunque identica, per tre motivi concreti: un solo flusso logico da
    ragionare e correggere quando qualcosa va storto in produzione, gli
    stessi log e gli stessi punti di fallimento su entrambi i provider, e
    la certezza che cambiare CERVELLO_PROVIDER non cambi nient'altro che
    il modello interrogato.

    Lo schema passato in response_format e' la traduzione automatica di
    CERVELLO_RESPONSE_SCHEMA fatta da _schema_gemini_to_openai: unica
    fonte di verita', nessun rischio che i due schemi divergano.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []

    # ---- FASE 1: giri di ricerca ------------------------------------------
    tool_choice = "required" if forza_ricerca else "auto"

    for round_idx in range(MAX_ROUNDS_FUNZIONE):
        try:
            data = await _chiama_openai_raw(
                messages, tentativi_rimasti=max_retries,
                tools=[OPENAI_CERVELLO_TOOL], tool_choice=tool_choice,
            )
        except Exception as e:
            log.warning("Cervello OpenAI: fase ricerca fallita al giro %d (%s) -- si passa al verdetto.", round_idx + 1, e)
            break

        choices = data.get("choices", [])
        if not choices:
            log.warning("Cervello OpenAI: nessuna choice nella fase di ricerca (giro %d).", round_idx + 1)
            break

        costo_totale += costo_openai_token(data.get("usage", {}))

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break  # il modello ha gia' abbastanza dati: si passa al verdetto

        # OpenAI puo' restituire PIU' tool_calls nello stesso turno (parallel
        # tool calling, attivo di default). Va risposto a OGNUNA: lasciare un
        # tool_call_id senza risposta fa rifiutare l'intera history al giro
        # successivo con HTTP 400 ("did not have response messages"), bug
        # osservato ripetutamente in produzione prima del fix del 2026-09-19.
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                query_richiesta = json.loads(call.get("function", {}).get("arguments", "{}")).get("query", "")
            except (json.JSONDecodeError, TypeError):
                query_richiesta = ""
            log.info("Cervello OpenAI ha richiesto ricerca mirata (giro %d/%d): '%s'",
                     round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
            risultato_ricerca = await cerca_serper_mirata(query_richiesta)
            n_query_extra += 1
            ricerche_extra_raw.append(
                f"\n📍 FONTE: RICERCA ON-DEMAND CERVELLO (Serper google search, query: '{query_richiesta}')\n{risultato_ricerca}"
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": risultato_ricerca,
            })
        tool_choice = "auto"

    # ---- FASE 2: verdetto strutturato -------------------------------------
    messages.append({"role": "user", "content": ISTRUZIONE_FASE_JSON})

    try:
        data = await _chiama_openai_raw(
            messages, tentativi_rimasti=max_retries,
            response_format=OPENAI_RESPONSE_FORMAT_CERVELLO,
        )
    except Exception as e:
        return None, f"chiamata al verdetto strutturato fallita: {e}", costo_totale, n_query_extra, ricerche_extra_raw

    choices = data.get("choices", [])
    if not choices:
        return None, "risposta OpenAI senza choices nella fase di verdetto", costo_totale, n_query_extra, ricerche_extra_raw

    costo_totale += costo_openai_token(data.get("usage", {}))

    msg = choices[0].get("message", {})
    finish_reason = choices[0].get("finish_reason", "?")

    # Un rifiuto esplicito del modello (campo "refusal" di structured output)
    # non e' un JSON malformato: e' il modello che dichiara di non voler
    # rispondere. Va distinto, altrimenti finirebbe come "JSON non parsabile"
    # e si perderebbe il motivo reale.
    if msg.get("refusal"):
        return None, f"il modello ha rifiutato di produrre il verdetto: {msg['refusal']}", costo_totale, n_query_extra, ricerche_extra_raw

    testo_json = (msg.get("content") or "").strip()
    if not testo_json:
        if finish_reason == "length":
            return None, (
                "verdetto troncato: il JSON ha superato max_tokens. Se ricapita, "
                "la causa piu' probabile e' un array comp_candidati molto lungo."
            ), costo_totale, n_query_extra, ricerche_extra_raw
        return None, f"il modello non ha prodotto il JSON del verdetto (finish_reason={finish_reason})", costo_totale, n_query_extra, ricerche_extra_raw

    try:
        verdetto = json.loads(testo_json)
    except json.JSONDecodeError as e:
        log.warning("Cervello OpenAI: JSON non parsabile (finish_reason=%s): %s\nTESTO GREZZO: %s",
                    finish_reason, e, testo_json[:1000])
        return None, f"JSON del verdetto non parsabile ({e})", costo_totale, n_query_extra, ricerche_extra_raw

    if not isinstance(verdetto, dict):
        return None, "il JSON del verdetto non e' un oggetto", costo_totale, n_query_extra, ricerche_extra_raw

    return verdetto, None, costo_totale, n_query_extra, ricerche_extra_raw


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


async def _risolvi_search_by_image_id_via_serper(url_intermedio):
    """Fallback aggiunto il 2026-09-20 dopo la prova in produzione che il
    blocco su /search_by_image e' un blocco Datadome a livello di edge (HTTP
    403 diretto, niente redirect, niente pagina) sul fingerprint TLS/HTTP
    del client httpx -- confermato perche' NELLO STESSO log lo scraping
    normale (pagine annuncio/venditore) con lo stesso identico stack
    httpx funziona regolarmente: non e' un blocco generico su Python, e'
    specifico di questo endpoint sensibile.

    Il servizio di scraping di Serper pero' su QUESTO STESSO endpoint
    riceve 200 OK nello stesso log (lo si vede usato subito dopo per altre
    fonti) -- il suo infrastructure/fingerprint passa dove il nostro client
    diretto viene bloccato. Tentativo: fargli scrape-are l'URL intermedio
    di search_by_image e provare a recuperare l'URL finale (dopo il
    redirect 307 a /catalog?search_by_image_id=...) dai metadati o dal
    contenuto che restituisce, invece di fare l'intera catena (che aveva
    dato risultati generici/degradati per il catalogo, vedi
    _scrape_catalogo_vinted_diretto) -- qui serve solo l'ID risolto, non il
    contenuto del catalogo.

    NON VERIFICATO IN PRODUZIONE alla scrittura: non e' confermato che
    Serper esponga l'URL finale dopo un redirect nella sua risposta, ne'
    sotto quale nome di campo. Per questo logga le chiavi di primo livello
    ricevute PRIMA di provare a estrarne uno specifico, cosi' se il
    tentativo fallisce il prossimo log di produzione mostra la forma reale
    della risposta invece di doverla indovinare una seconda volta. Fallisce
    in modo sicuro: ritorna None su qualunque errore o mancata corrispondenza,
    il chiamante si comporta come se il fallback non esistesse."""
    if not SERPER_API_KEY:
        return None
    # "headers" nel payload (tentativo, non documentato/confermato per questo
    # endpoint Serper): se supportato, inoltra i cookie dell'account dedicato
    # cosi' la richiesta arriva a Vinted autenticata anche passando dal
    # fetcher di Serper -- SENZA questo, Serper vede l'URL come richiesta
    # anonima e Vinted la reindirizza correttamente al login/signup (proprio
    # come farebbe con un browser vero non loggato), che e' l'ipotesi piu'
    # probabile per cui il tentativo del 2026-09-20 non ha trovato nessun
    # search_by_image_id nella risposta: non un fallimento di Serper, ma
    # Serper-senza-cookie che raggiunge la STESSA pagina di registrazione.
    # Se il campo non e' supportato, Serper lo ignora e il comportamento
    # resta quello gia' osservato in produzione (nessun peggioramento).
    cookies_auth = {k: v for k, v in _VINTED_COOKIES.items() if v}
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies_auth.items())
    payload = {
        "url": url_intermedio, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True,
        "headers": {"Cookie": cookie_header} if cookie_header else {},
    }
    try:
        resp = await _client_generico.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            log.info("_risolvi_search_by_image_id_via_serper: Serper fallito (crediti/HTTP %d).", resp.status_code)
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.info("_risolvi_search_by_image_id_via_serper: chiamata Serper fallita: %s", e)
        return None

    # Diagnostica estesa (aggiunta dopo il primo tentativo in produzione,
    # 2026-09-20, che ha loggato solo le chiavi e non ha permesso di capire
    # SU QUALE pagina Serper sia effettivamente atterrato): metadata per
    # intero (spesso contiene lo status HTTP/URL finale delle API di
    # scraping) e un frammento di testo, cosi' si vede a colpo d'occhio se
    # e' la pagina di registrazione (ipotesi sopra) o qualcos'altro.
    log.info("_risolvi_search_by_image_id_via_serper: chiavi ricevute da Serper: %s", list(data.keys()))
    log.info("_risolvi_search_by_image_id_via_serper: metadata=%r", data.get("metadata"))
    testo_snippet = (data.get("text") or "")[:300]
    log.info("_risolvi_search_by_image_id_via_serper: inizio testo pagina=%r", testo_snippet)

    # Primo tentativo: un campo che indichi esplicitamente l'URL finale
    # raggiunto da Serper dopo aver seguito eventuali redirect.
    candidati_url = [
        data.get("url"), data.get("finalUrl"), data.get("resolvedUrl"),
        (data.get("metadata") or {}).get("url") if isinstance(data.get("metadata"), dict) else None,
    ]
    for candidato in candidati_url:
        if candidato and "search_by_image_id=" in candidato:
            m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", candidato)
            if m:
                log.info(
                    "_risolvi_search_by_image_id_via_serper: OK (da campo URL) -> search_by_image_id=%s (url=%s)",
                    m.group(1), candidato,
                )
                return m.group(1)

    # Secondo tentativo: l'ID potrebbe comparire dentro il contenuto
    # restituito (link canonico, og:url, redirect lato JS) anche se Serper
    # non espone un campo "url" dedicato.
    for chiave in ("markdown", "text", "html", "rawHtml"):
        contenuto = data.get(chiave)
        if not contenuto:
            continue
        m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", contenuto)
        if m:
            log.info(
                "_risolvi_search_by_image_id_via_serper: OK (da campo '%s') -> search_by_image_id=%s",
                chiave, m.group(1),
            )
            return m.group(1)

    log.info(
        "_risolvi_search_by_image_id_via_serper: nessun search_by_image_id trovato nella risposta Serper "
        "(chiavi disponibili: %s) -- formato risposta da rivedere sul prossimo log.",
        list(data.keys()),
    )
    return None


async def _risolvi_search_by_image_id(item_id, photo_id):
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
    autenticata; se assenti la funzione si comporta esattamente come nello
    stato "chiuso" sopra (ritorna None, nessuna rottura del resto della
    pipeline).

    RIAPERTA di nuovo il 2026-09-20: refresh automatico via
    _rinnova_token_vinted() quando l'access token e' scaduto, invece di
    restare inattiva finche' l'utente non lo aggiorna a mano su Railway.
    NON VERIFICATO IN PRODUZIONE alla scrittura (vedi la docstring di
    _rinnova_token_vinted per il dettaglio) -- se il refresh fallisce si
    comporta esattamente come prima di questa modifica: fonte saltata,
    nessuna rottura.

    BUG TROVATO IN PRODUZIONE il 2026-09-20 e corretto: il refresh
    riusciva (HTTP 200, nuovi access_token_web/refresh_token_web ricevuti)
    ma QUESTA chiamata veniva comunque rediretta a /member/register/
    select_type. Causa: sia il refresh sia questa chiamata prendevano un
    client httpx dal pool anonimo condiviso (_prossimo_client_vinted, in
    round-robin con TUTTO lo scraping annunci/venditori) -- ogni client del
    pool accumula nel proprio cookie jar cookie Datadome/sessione da
    traffico anonimo ad alto volume, scorrelati dall'account dedicato, e il
    round-robin poteva far atterrare refresh e search_by_image_id su
    client diversi comunque. Mandare un JWT valido insieme a un cookie
    Datadome di un'altra sessione (anonima) e' un'incoerenza che Vinted
    trattava come sessione sospetta. Corretto usando _CLIENT_VINTED_AUTH,
    un client dedicato SEMPRE riusato per refresh + search_by_image_id (mai
    toccato dal pool anonimo), cosi' il suo cookie jar resta coerente con
    l'account autenticato in entrambe le chiamate."""
    if not VISUAL_SEARCH_ATTIVA:
        return None
    if not item_id or not photo_id:
        return None
    if not _VINTED_COOKIES.get("access_token_web") or _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
        async with _vinted_refresh_lock:
            # Doppio controllo dentro il lock: un altro task in parallelo
            # potrebbe aver gia' rinnovato mentre aspettavamo il lock.
            if not _VINTED_COOKIES.get("access_token_web") or _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
                log.info("_risolvi_search_by_image_id: access token scaduto/assente, tento il refresh automatico...")
                if not await _rinnova_token_vinted():
                    log.info(
                        "_risolvi_search_by_image_id: refresh automatico fallito -- fonte visuale "
                        "saltata per questo item (serve un token fresco dall'account dedicato, "
                        "aggiornabile su Railway)."
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
    # Cookie dell'account dedicato passati SOLO qui (cookies_extra, non piu'
    # sul client condiviso) E client_override=_CLIENT_VINTED_AUTH (non il
    # pool anonimo, aggiunto il 2026-09-20): questa e' l'unica chiamata del
    # bot che ha davvero bisogno di autenticazione (verificato via DevTools
    # il 2026-09-18/19), tutto il resto dello scraping Vinted resta anonimo
    # e passa dal pool round-robin come sempre. Riusare lo STESSO client di
    # _rinnova_token_vinted e' il punto: porta con se' i cookie Datadome/
    # sessione accumulati li', coerenti col JWT appena rinnovato -- prima
    # (client preso dal pool anonimo in round-robin) questa richiesta poteva
    # arrivare con un cookie Datadome di tutt'altra provenienza insieme a un
    # JWT valido, un'incoerenza che Vinted trattava come sessione sospetta e
    # rediriggeva a /member/register anche a refresh riuscito.
    resp = await _vinted_get_con_retry(
        url_intermedio, timeout=12, max_retries=2, headers_extra=headers_referer_annuncio,
        cookies_extra={k: v for k, v in _VINTED_COOKIES.items() if v},
        client_override=_CLIENT_VINTED_AUTH,
    )
    esito_diretto = None
    if resp is not None:
        # str(): con httpx resp.url e' un oggetto URL, non una stringa -- un
        # "in" o una re.search direttamente su di esso solleverebbe TypeError
        # (con requests era una stringa e funzionava).
        url_finale = str(resp.url)
        if "/member/register" in url_finale or "/member/login" in url_finale:
            log.info(
                "_risolvi_search_by_image_id: redirect a login/registrazione NONOSTANTE "
                "VINTED_ACCESS_TOKEN impostato e non scaduto (%s) -- possibile token "
                "invalidato lato Vinted prima della scadenza dichiarata, o blocco Datadome "
                "sul fingerprint della richiesta (vedi nota TLS/Datadome nella docstring "
                "sopra). Provo il fallback via Serper prima di arrendermi.",
                url_finale,
            )
        else:
            m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", url_finale)
            if m:
                esito_diretto = m.group(1)
            else:
                log.info(
                    "_risolvi_search_by_image_id: redirect non ha prodotto un search_by_image_id "
                    "nell'URL finale (%s) -- provo il fallback via Serper prima di arrendermi.",
                    url_finale,
                )
    else:
        log.info(
            "_risolvi_search_by_image_id: richiesta diretta fallita (probabile 403 Datadome "
            "sul fingerprint del client -- vedi nota TLS/Datadome nella docstring sopra). "
            "Provo il fallback via Serper prima di arrendermi."
        )

    if esito_diretto:
        log.info(
            "_risolvi_search_by_image_id: OK (diretto) item_id=%s photo_id=%s -> search_by_image_id=%s",
            item_id, photo_id, esito_diretto,
        )
        return esito_diretto

    # Fallback via Serper (aggiunto il 2026-09-20): il client diretto viene
    # bloccato a livello edge su QUESTO endpoint (403 o redirect a signup),
    # ma nello stesso log lo stesso Serper riceve 200 OK dallo stesso host
    # -- vedi _risolvi_search_by_image_id_via_serper per il dettaglio.
    esito_serper = await _risolvi_search_by_image_id_via_serper(url_intermedio)
    if esito_serper:
        log.info(
            "_risolvi_search_by_image_id: OK (fallback Serper) item_id=%s photo_id=%s -> search_by_image_id=%s",
            item_id, photo_id, esito_serper,
        )
        return esito_serper

    log.info(
        "_risolvi_search_by_image_id: nessuna via (diretta o Serper) ha risolto search_by_image_id "
        "per item_id=%s -- fonte visuale saltata per questo item.",
        item_id,
    )
    return m.group(1)


async def build_vinted_visual_search_url(item_id, photo_id, brand):
    """URL equivalente al bottone Vinted "Cerca articoli simili" + filtro
    per brand. Risolve prima il vero search_by_image_id (vedi
    _risolvi_search_by_image_id -- il photo_id della foto da solo NON
    basta), poi vi aggiunge il filtro brand. Richiede SEMPRE un brand_id
    mappato: senza filtro brand la ricerca visuale pura e' troppo ampia per
    essere un comp utile (l'utente ha verificato che il filtro brand e'
    quello che rende i risultati "molto verosimili"). Ritorna None se manca
    un ingrediente o la risoluzione fallisce -- il chiamante deve trattarlo
    come fonte assente, non come errore.

    NIENTE order=newest_first qui (fix 2026-09-20, dopo aver osservato in
    log di produzione che i comp visuali erano categorie completamente
    diverse dello stesso brand -- borse/profumi/gioielli mescolati a capi
    d'abbigliamento -- invece di articoli simili alla foto): quel parametro
    era stato copiato per analogia da build_vinted_search_url (ricerca
    testuale, dove ha senso ordinare per data), ma su search_by_image_id
    SOVRASCRIVE l'ordinamento per rilevanza/similarita' visiva che Vinted
    applica di default su quell'endpoint, degradandolo a "ultimi articoli
    del brand" su tutto il catalogo. L'unico URL verificato dall'utente via
    DevTools il 2026-09-18 non aveva questo parametro. Lasciamo l'ordine di
    default (rilevanza) e teniamo solo i filtri che restringono senza
    riordinare (brand, status)."""
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    if not brand_id:
        return None
    search_by_image_id = await _risolvi_search_by_image_id(item_id, photo_id)
    if not search_by_image_id:
        return None
    url = (
        f"https://www.vinted.it/catalog?search_by_image_id={quote(search_by_image_id)}"
        f"&brand_ids[]={brand_id}"
        "&status_ids[]=1&status_ids[]=2&status_ids[]=3"
    )
    log.info("build_vinted_visual_search_url: URL catalogo costruito: %s", url)
    return url


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


async def _serper_scrape_page_diretto(label, url):
    if not SERPER_API_KEY:
        return "Scrape non eseguito (SERPER_API_KEY non impostata).", False

    payload = {"url": url, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True}
    try:
        resp = await _client_generico.post(
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


async def _serper_batch_query_vestiaire(brand, categoria):
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
        resp = await _client_generico.post(
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


async def _query_resellbot_raw(query_testo, timeout):
    """Esegue UNA chiamata a Resellbot con la query testuale gia' costruita e
    ritorna (righe_di_testo, ok). Estratta da _cerca_ebay_sold_via_resellbot
    il 2026-09-19 per permettere il retry senza materiale (vedi sopra)."""
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
    log.info("Resellbot: richiesta in corso -- query='%s'", query_testo)
    try:
        resp = await _client_generico.post(
            "https://scan-api.resellbot.com/api/search",
            headers=headers, json=payload, timeout=timeout,
        )
        if resp.status_code in (401, 403, 429):
            log.info("Resellbot: bloccato/rate-limited (HTTP %d) per query='%s' -- uso fallback Google.", resp.status_code, query_testo)
            return f"  Resellbot bloccato/rate-limited (HTTP {resp.status_code}) -- uso fallback Google.", False
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.info("Resellbot: fallito per query='%s' -- %s -- uso fallback Google.", query_testo, e)
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
        log.info("Resellbot: risposta OK ma 0 listing per query='%s'.", query_testo)
        return None, True  # successo ma zero righe -- distinto da "fallito"
    log.info("Resellbot: risposta OK, %d listing trovati per query='%s'.", len(righe), query_testo)
    return "\n".join(righe[:20]), True


async def _cerca_ebay_sold_via_resellbot(brand, categoria, material_per_ricerca=None, timeout=6):
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
    sotto -- questa fonte non e' un punto di fallimento singolo.

    material_per_ricerca (aggiunto il 2026-09-19) restringe la query
    aggiungendo il materiale dichiarato (es. "cashmere", "lana") quando
    disponibile -- utile soprattutto sui brand di lusso dove il materiale
    sposta molto il prezzo (un maglione Brunello Cucinelli in cashmere vale
    parecchio piu' di uno in cotone). Include un retry automatico SENZA
    materiale se la prima query non trova nulla: la specificity "exact" di
    Resellbot puo' azzerare i risultati quando la query e' troppo stretta,
    soprattutto su brand di nicchia con pochi listing totali -- meglio
    allargare che restituire zero comp per un dettaglio in piu'."""
    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()
    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query eBay "
            "(Resellbot) saltata per evitare risultati fuorvianti."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    query_base = f'{brand_pulito} {termine_en}'.strip() if brand_pulito else termine_en
    materiale_pulito = (material_per_ricerca or "").strip()

    if materiale_pulito:
        query_con_materiale = f'{query_base} {materiale_pulito}'
        testo, ok = await _query_resellbot_raw(query_con_materiale, timeout)
        if not ok:
            return testo, False  # errore di rete/rate-limit: nessun retry, va al fallback Google
        if testo is not None:
            return testo, True  # trovato qualcosa con il materiale incluso
        # Zero risultati con il materiale -- riprova con la query piu' ampia.
        log.info(
            "Resellbot: 0 risultati con materiale ('%s') -- retry senza materiale ('%s').",
            query_con_materiale, query_base,
        )
        testo_ampio, ok_ampio = await _query_resellbot_raw(query_base, timeout)
        if not ok_ampio:
            return testo_ampio, False
        if testo_ampio is not None:
            return testo_ampio, True
        return "  Nessun venduto trovato su Resellbot per questa query.", True

    testo, ok = await _query_resellbot_raw(query_base, timeout)
    if not ok:
        return testo, False
    if testo is None:
        return "  Nessun venduto trovato su Resellbot per questa query.", True
    return testo, True


async def _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca=None):
    """FALLBACK per eBay SOLD (fonte primaria: _cerca_ebay_sold_via_resellbot
    sopra) -- stesso schema di _serper_batch_query_vestiaire (Google search
    via Serper, non scrape diretto della pagina eBay).

    material_per_ricerca (aggiunto il 2026-09-19, per coerenza con la fonte
    primaria Resellbot) viene aggiunto tra virgolette come termine di
    ricerca aggiuntivo quando disponibile -- qui non serve un retry "senza
    materiale" come per Resellbot: Google gestisce query piu' lunghe senza
    azzerare i risultati come farebbe una specificity "exact" letterale, si
    limita a pesarlo come termine di rilevanza in piu'.

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
    materiale_pulito = (material_per_ricerca or "").strip()
    if materiale_pulito:
        base = f'{base} "{materiale_pulito}"'
    query_serper = f'{base} (venduto OR sold) (site:ebay.it OR site:ebay.com)'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await _client_generico.post(
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


# Pattern che estrae titolo+prezzo dall'attributo alt="..." di ogni <img>
# prodotto nella griglia catalogo Vinted -- confermato il 2026-09-20 via
# view-source reale fornito dall'utente:
# alt="Manteau Jean Paul Gaultier, Brand: Jean Paul Gaultier, Condizioni:
# Ottime, Taglia: M / IT 42 / EU 38, 140.00 €, 147.70 €"
# Il primo prezzo (140.00) e' l'ask "nudo", il secondo (147.70) include le
# fee Vinted -- prendiamo il primo per coerenza con le altre fonti comp, che
# lavorano tutte in ASK senza fee. Molto piu' robusto di un parser
# HTML->markdown generico: il dato e' gia' strutturato da Vinted stesso nel
# markup, non va indovinato dalla disposizione visiva del testo.
_RE_ALT_PRODOTTO_VINTED = re.compile(
    r'alt="([^"]+?),\s*Brand:.*?,\s*Condizioni:.*?,\s*Taglia:[^,"]*,\s*([\d]+(?:[.,]\d+)?)\s*€',
    re.IGNORECASE,
)


def _estrai_articoli_da_alt_vinted(html_content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dagli attributi alt= delle immagini
    prodotto nell'HTML grezzo di una pagina catalogo Vinted (vedi
    _RE_ALT_PRODOTTO_VINTED per il pattern esatto). Stesso formato di
    output di _estrai_articoli_vinted ('- titolo — €prezzo', una riga per
    articolo) cosi' il resto della pipeline (filtro autoreferenziale,
    categoria, sottolinea brand) funziona invariato su entrambe le fonti."""
    righe, visti = [], set()
    for m in _RE_ALT_PRODOTTO_VINTED.finditer(html_content or ""):
        titolo = html.unescape(m.group(1)).strip()
        prezzo = m.group(2).replace(",", ".")
        if not titolo or len(titolo) < 3:
            continue
        chiave = (titolo[:60].lower(), prezzo)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe.append(f"- {titolo} — €{prezzo}")
        if len(righe) >= max_articoli:
            break
    if not righe:
        return "  Nessun articolo trovato (pattern alt= senza match -- possibile cambio di markup Vinted, da rivedere)."
    return "\n".join(righe)


async def _scrape_catalogo_vinted_diretto(url):
    """Scarica la pagina catalogo search_by_image_id con il client HTTP GIA'
    autenticato del bot (stesso pool/proxy usato per annunci e profili
    venditore), invece di passare per Serper. Aggiunta il 2026-09-20 dopo
    aver isolato empiricamente (con l'utente, via DevTools) che Vinted
    restituisce contenuto DIVERSO a seconda di chi fa la richiesta: il
    browser dell'utente (anche incognito, senza login) riceve la vera
    griglia filtrata per search_by_image_id renderizzata server-side (SSR,
    confermato: i titoli sono gia' nell'HTML grezzo via view-source, non
    serve JS), mentre Serper riceveva sistematicamente lo stesso mazzo
    generico di articoli del brand (identico su search_by_image_id diversi
    per lo stesso brand) -- quasi certamente un fallback anti-bot (Datadome,
    gia' noto per altri endpoint Vinted) che riconosce il fingerprint di
    Serper e gli serve una versione non personalizzata invece di bloccare.

    Estrazione via _estrai_articoli_da_alt_vinted (regex su alt=, vedi
    sopra) invece che via markdown generico: un primo tentativo con
    markdownify (HTML->markdown) metteva titolo e prezzo su righe separate
    quando erano in tag diversi, rompendo il parser esistente che li vuole
    sulla stessa riga -- scartato prima del deploy."""
    resp = await _vinted_get_con_retry(url, timeout=15, max_retries=2)
    if resp is None:
        return "  Scrape diretto Vinted fallito (nessuna risposta dopo i retry).", False
    return _estrai_articoli_da_alt_vinted(resp.text), True


async def _recupera_comp_visuali_vinted(item_id, photo_id, brand):
    """Wrapper per la fonte visuale, pensato per essere sottomesso come UN
    solo future nello stesso executor delle altre 3 fonti (vedi
    search_comps_completo) cosi' la risoluzione dell'ID (chiamata di rete
    verso Vinted, non istantanea) corre IN PARALLELO alle altre ricerche
    invece di bloccarne l'avvio. Fa due passi in sequenza al suo interno
    (risolvi ID -> scrape del catalogo con quell'ID), ma dal punto di vista
    dell'executor e' un solo task con lo stesso contratto di ritorno
    (testo, ok) degli altri. ok=False (non un'eccezione) quando manca un
    ingrediente o la risoluzione fallisce, cosi' il chiamante lo tratta come
    fonte assente senza differenziare i log dalle altre query fallite.

    Scrape diretto (non Serper) dal 2026-09-20: vedi docstring di
    _scrape_catalogo_vinted_diretto per il perche'."""
    url = await build_vinted_visual_search_url(item_id, photo_id, brand)
    if not url:
        log.info(
            "_recupera_comp_visuali_vinted: fonte non disponibile per item_id=%s "
            "(photo_id/brand mancante o risoluzione ID fallita).", item_id,
        )
        return "  Fonte non disponibile (photo_id/brand mancante o risoluzione ID falsa).", False
    testo, ok = await _scrape_catalogo_vinted_diretto(url)
    log.info(
        "_recupera_comp_visuali_vinted: scrape catalogo grezzo per item_id=%s ok=%s -> %r",
        item_id, ok, testo,
    )
    return testo, ok


async def _cerca_ebay_sold_con_fallback(brand, categoria, material_per_ricerca=None):
    """Wrapper per l'executor: prova prima Resellbot (dati di vendita
    confermati, veri, vedi _cerca_ebay_sold_via_resellbot), e solo se fallisce
    (bloccato, rate-limited, errore di rete, o semplicemente 'nessun venduto
    trovato' con ok=True viene comunque accettato cosi' com'e' -- il fallback
    scatta solo su ok=False) prova la query Google di riserva. Tenute
    sequenziali (non in parallelo) per non raddoppiare le chiamate quando la
    prima fonte funziona, che e' il caso comune.

    material_per_ricerca (aggiunto il 2026-09-19) viene inoltrato a entrambe
    le fonti per restringere la query quando il materiale e' noto (vedi
    docstring di _cerca_ebay_sold_via_resellbot per il dettaglio sul retry
    automatico senza materiale se la query ristretta non trova nulla)."""
    testo, ok = await _cerca_ebay_sold_via_resellbot(brand, categoria, material_per_ricerca)
    if ok:
        return testo, ok
    log.info("_cerca_ebay_sold_con_fallback: Resellbot fallito (%s), tento fallback Google.", testo)
    testo_fallback, ok_fallback = await _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca)
    if ok_fallback:
        return f"{testo_fallback}\n(Nota: fonte primaria Resellbot fallita, questi risultati vengono da Google/eBay.)", True
    return f"{testo} | fallback Google anch'esso fallito: {testo_fallback}", False


async def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None, cover_photo_id=None, item_id=None):
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
    # Se manca l'ingrediente minimo (photo_id o brand mappato) la fonte
    # visuale e' inutile: lo sappiamo gia' qui senza fare rete, quindi non la
    # sottomettiamo affatto all'executor invece di sprecare uno slot/tempo.
    tentare_ricerca_visuale = (
        VISUAL_SEARCH_ATTIVA
        and bool(cover_photo_id)
        and bool(VINTED_BRAND_IDS.get((brand or "").strip().lower()))
    )

    # Corretto il 2026-09-19: eBay (via Resellbot) e Vestiaire Collective
    # rimosse dalla pipeline. Causa root: confermato (dall'utente + verifica
    # web su resellbot.com/ebay-sold-listings) che Resellbot interroga
    # eBay.com US in DOLLARI, ma il codice stampava ogni prezzo col simbolo
    # € senza alcuna conversione -- un $150 USD diventava letteralmente
    # "€150.00" nel pool, sballando ogni comp eBay di circa il 10-15% (cambio)
    # oltre a mescolare un mercato (USA, vintage/resale) con dinamiche di
    # prezzo diverse da quello italiano/europeo. Questo spiegava anche
    # perche' Gemini "sembrava" sottostimare rispetto a eBay/Vestiaire nei
    # log osservati (Loro Piana, Missoni, Jil Sander): non stava sbagliando,
    # stava ragionando su comp gonfiati da un bug di dati a monte. Decisione
    # operativa: tenere solo Vinted (gia' in EUR, mercato italiano reale) +
    # la conoscenza generale di Gemini (grounding). Se in futuro si vuole
    # reintrodurre eBay, va prima risolta la conversione valuta in
    # _cerca_ebay_sold_via_resellbot.
    # Fan-out delle fonti comp con asyncio.gather invece del vecchio
    # ThreadPoolExecutor. Due vantaggi concreti oltre al non bloccare il loop:
    # il timeout e' PER FONTE (prima era complessivo sull'as_completed, quindi
    # una fonte lenta poteva consumare il budget di tutte), e asyncio.wait_for
    # CANCELLA davvero la coroutine scaduta, mentre un thread in timeout
    # restava vivo a consumare connessioni e quota Serper per una risposta
    # che nessuno avrebbe piu' letto.
    TIMEOUT_PER_FONTE_SECONDI = 15

    async def _esegui_fonte(nome, coroutine):
        try:
            testo, ok = await asyncio.wait_for(coroutine, timeout=TIMEOUT_PER_FONTE_SECONDI)
            return nome, testo, ok
        except asyncio.TimeoutError:
            return nome, f"  Timeout (fonte troppo lenta, oltre {TIMEOUT_PER_FONTE_SECONDI}s).", False
        except Exception as e:
            return nome, f"  Query fallita: {e}", False

    lavori = [_esegui_fonte("vinted", _serper_scrape_page_diretto("VINTED", vinted_url))]
    if tentare_ricerca_visuale:
        lavori.append(_esegui_fonte(
            "vinted_visuale", _recupera_comp_visuali_vinted(item_id, cover_photo_id, brand)))

    risultati = {}
    successi = {}
    for nome, testo, ok in await asyncio.gather(*lavori):
        risultati[nome] = testo
        successi[nome] = ok

    serper_ha_funzionato = any(successi.values())

    nota_brand = "" if vinted_per_id else (
        "⚠️ Brand non nella mappa brand_id Vinted -- la ricerca Vinted usa testo libero "
        "(meno precisa, possibili falsi positivi)."
    )

    vinted_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted"), query_base)
    vinted_comp_puliti = _filtra_comp_per_categoria(vinted_comp_puliti, categoria)
    vinted_comp_puliti = _filtra_comp_per_brand_sottolinee(vinted_comp_puliti, brand)
    # La fonte visuale conta come "presente" solo se ha davvero prodotto un
    # risultato (successi["vinted_visuale"] True) -- se photo_id/brand
    # mancavano non e' nemmeno stata sottomessa (tentare_ricerca_visuale
    # False), se e' stata sottomessa ma la risoluzione ID o lo scrape sono
    # falliti risulta un fallimento come le altre query, non un errore raro.
    fonte_visuale_riuscita = tentare_ricerca_visuale and successi.get("vinted_visuale")
    visual_comp_puliti = None
    if fonte_visuale_riuscita:
        visual_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted_visuale"), query_base)
        # _filtra_comp_per_categoria RIATTIVATO qui il 2026-09-20: log di
        # produzione (Jean Paul Gaultier, Max Mara, Vivienne Westwood) hanno
        # mostrato borse/profumi/gioielli/categorie completamente diverse
        # mescolate nei comp "visuali" -- l'assunzione che bastasse il
        # search_by_image_id a restringere per somiglianza visiva era
        # sbagliata (causa reale: order=newest_first sull'URL, appena
        # rimosso in build_vinted_visual_search_url). Finche' non
        # verifichiamo in produzione che il fix dell'ordinamento basta da
        # solo, questo filtro resta come rete di sicurezza anti-categoria-
        # sbagliata anche sulla fonte visuale.
        visual_comp_puliti = _filtra_comp_per_categoria(visual_comp_puliti, categoria)
        visual_comp_puliti = _filtra_comp_per_brand_sottolinee(visual_comp_puliti, brand)
        log.info(
            "search_comps_completo: comp visuali DOPO pulizia (item_id=%s, brand=%s) -> %r",
            item_id, brand, visual_comp_puliti,
        )

    n_fonti = 2 if fonte_visuale_riuscita else 1
    parti = [f"RICERCA WEB PRE-RACCOLTA ({n_fonti} fonti, base: '{query_base}'):"]
    if nota_brand:
        parti.append(nota_brand)
    if categoria:
        parti.append(f"(Comp filtrati per categoria rilevata: '{categoria}' -- risultati fuori tema gia' scartati.)")
    if fonte_visuale_riuscita:
        parti.append(
            "\n📍 FONTE: VINTED — RICERCA VISUALE PER FOTO (stesso identikit visivo dell'annuncio, "
            "filtrato per brand — la piu' precisa delle fonti, prezzi ASK)\n"
            f"{visual_comp_puliti or 'Nessun risultato'}"
        )
    parti.append(
        "\n📍 FONTE: VINTED (prezzi ASK — annunci attivi, NON necessariamente venduti; annuncio in analisi gia' escluso)\n"
        f"{vinted_comp_puliti or 'Nessun risultato'}"
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


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO e VALIDAZIONE POST-GENERAZIONE
# ---------------------------------------------------------------------------

def estrai_margine_preliminare(output_occhi_testo):
    """Estrae margine netto e ROI dalla valutazione finanziaria preliminare
    che l'occhio produce (best-effort: i formati variano leggermente)."""
    return _estrai_margine_e_roi_da_blocco(output_occhi_testo or "")


def check_skip_pre_cervello(output_occhi_testo, listing_info=None, occhio_json=None):
    """occhio_json: presente solo con OCCHIO_OUTPUT_JSON=true. In quel caso
    lo scarto si calcola da campi tipizzati invece che cercando sottostringhe
    nella prosa, e tutto il resto di questa funzione non viene eseguito.

    Il ramo su prosa qui sotto resta invariato: e' il comportamento di
    default, quello che gira oggi in produzione."""
    if occhio_json is not None:
        solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
        return calcola_scarto_occhio(occhio_json, solo_cover_photo=solo_cover)

    testo = (output_occhi_testo or "").lower()

    # NOTA (caso reale osservato): un Dries Van Noten a €5,95 e' stato
    # scartato qui come "falso palese, Confidenza Alta" con dettagli che
    # sembravano inventati, mentre 3 legit check esterni indipendenti sullo
    # stesso capo hanno concluso "Probabilmente autentico" 82-85%. La causa
    # probabile e' un bias "prezzo troppo basso = deve essere falso"
    # nell'occhio. Soluzione scelta: RINFORZARE il prompt dell'occhio (non
    # rimuovere questo filtro, che resta utile per risparmiare token sui
    # falsi genuinamente conclamati).
    # Corretto il 2026-09-19 (caso reale Miu Miu pull cour): DUE bug distinti
    # facevano si' che questo skip non scattasse mai per il formato che
    # l'occhio produce davvero in produzione.
    # 1. Il prompt canonizza solo "Probabilmente falso" tra i 4 verdetti
    #    possibili, ma il modello a volte scrive varianti equivalenti
    #    ("Falso palese", "Falso evidente") per enfatizzare la certezza --
    #    non matchavano nessuna delle stringhe cercate qui sotto.
    # 2. Il template del prompt per la riga finale e' sempre "Confidenza:
    #    [A/M/B]" (vedi riga "Confidenza: [B]"/"Confidenza: [A/M/B]" nel
    #    prompt), cioe' CON i due punti -- "Confidenza: Alta" nel testo
    #    reale, mentre il filtro cercava "confidenza alta" SENZA i due
    #    punti. Il pattern non ha mai potuto matchare il formato standard,
    #    a meno che il testo non contenesse anche "molto alto" o una
    #    percentuale esplicita altrove (raro). Questo era il bug root:
    #    anche un "Probabilmente falso" testuale puro con "Confidenza: Alta"
    #    non veniva riconosciuto. Risultato pratico osservato in produzione:
    #    il cervello veniva comunque consultato e tutte le ricerche di
    #    prezzo (Resellbot/Serper) partivano inutilmente su un verdetto
    #    gia' scontato (NON COMPRARE), sprecando query a pagamento.
    ha_falso_alta_confidenza = (
        "probabilmente falso" in testo
        or "falso conclamato" in testo
        or "falso palese" in testo
        or "falso evidente" in testo
    )
    ha_confidenza_alta = any(c in testo for c in (
        "confidenza alta", "confidenza: alta", "confidenza:alta",
        "90%", "95%", "100%", "molto alto",
    ))
    if ha_falso_alta_confidenza and ha_confidenza_alta:
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
    elif motivo_skip.startswith("[BRAND IN BLOCKLIST"):
        riga_legit = "Brand escluso in modo permanente dalle regole di valutazione."
        riga_rischio = "N/A — brand bloccato su richiesta esplicita (filtro pre-Gemini)"
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


# ---------------------------------------------------------------------------
# RETI DI SICUREZZA REGEX -- RIMOSSE il 2026-09-19
# ---------------------------------------------------------------------------
# Con il cervello a output JSON strutturato queste funzioni non hanno piu'
# un oggetto su cui lavorare, quindi sono state eliminate invece di essere
# lasciate nel file come codice morto (un file lungo pieno di funzioni che
# non vengono mai chiamate e' un costo di lettura permanente, e prima o poi
# qualcuno le riattiva senza accorgersi che parsano un formato che non
# esiste piu'). Elenco di cosa e' sparito e di cosa lo sostituisce:
#
#   _normalizza_emoji_decisione        -> le emoji le scrive render_messaggio_
#                                         verdetto da un dizionario, il modello
#                                         non le produce piu'
#   normalizza_urgenza_wording         -> l'urgenza e' un valore calcolato,
#                                         non una parola da normalizzare
#   forza_soglia_minima_compra         -> calcola_verdetto applica le soglie
#                                         PRIMA di scrivere la decisione
#   declassa_urgenza_se_borderline     -> idem, l'urgenza nasce gia' corretta
#   applica_soglia_trattativa_40_percento -> l'offerta la calcola il codice,
#                                         il modello non la propone piu'
#   converti_tratta_senza_obiettivo_valido -> TRATTA esiste solo se
#                                         l'obiettivo regge, per costruzione
#   valida_contraddizioni_report       -> non esistono piu' contraddizioni
#                                         possibili tra testo e numeri
#   estrai_decisione_da_testo          -> la decisione e' un campo, non si
#                                         estrae da nessuna parte
#   _e_urgenza_alta                    -> verdetto["urgenza"] == "Alta"
#   verifica_falso_ha_motivazione      -> legit_motivo_specifico e' un campo
#                                         obbligatorio dello schema, e la
#                                         lunghezza minima e' controllata in
#                                         valida_payload_cervello
#   verifica_ancoraggio_prezzo_comp    -> diventata un min() in calcola_verdetto
#   verifica_comp_citati_sono_reali    -> diventata una differenza tra insiemi
#                                         in classifica_provenienza_comp
#
# Restano invece _estrai_prezzi_da_pool_ricerca, _prezzi_per_fonte_da_pool,
# _motivo_nessun_prezzo e _riepilogo_comp_per_fonte: servono ancora, sia per
# il blocco debug Telegram sia per il confronto tra i comp dichiarati dal
# cervello e quelli realmente presenti nel pool.
#
# Restano anche _estrai_margine_e_roi_da_blocco e estrai_margine_preliminare:
# NON riguardano il cervello ma l'OCCHIO, che continua a produrre prosa e la
# cui stima preliminare alimenta ancora check_skip_pre_cervello.


def _estrai_item_id_da_url(url):
    if not url:
        return None
    m = re.search(r"/items/(\d+)", url)
    return m.group(1) if m else None


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
    davvero nel pool'.

    Corretto il 2026-09-19 (caso reale Jil Sander): un blocco 'RICERCA
    ON-DEMAND CERVELLO' e' sempre una query Google generica (Serper), mai
    taggata col nome di un marketplace specifico -- ma i suoi risultati
    spesso SONO risultati eBay/Vestiaire/Vinted/Depop/Grailed (lo snippet
    cita il dominio, es. 'ebay.it', o il titolo lo rende ovvio). Quando il
    cervello scrive nell'Analisi 'comp eBay SOLD €100.00' basandosi su un
    risultato che ha visto in quella ricerca on-demand, l'attribuzione e'
    corretta nella sostanza -- ma il controllo di secondo livello la
    respingeva sempre come 'fonte mal attribuita' perche' il prezzo era
    presente solo sotto la chiave 'ricercaondemandcervello', mai sotto
    'ebaysold'. Ora ogni riga del pool (non solo i blocchi RICERCA
    ON-DEMAND) viene scansionata anche per menzioni esplicite di dominio
    marketplace vicino a un prezzo, e quel prezzo viene aggiunto ANCHE
    alla fonte del dominio, in aggiunta alla fonte del blocco."""
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
        blocco_dati = resto or blocco
        if chiave:
            prezzi_fonte = _estrai_prezzi_da_pool_ricerca(blocco_dati)
            risultato.setdefault(chiave, set()).update(prezzi_fonte)

        # Riconoscimento dominio per-riga (vedi nota sopra): per ogni riga
        # del blocco, se compare un dominio marketplace esplicito, i prezzi
        # DI QUELLA RIGA vanno anche sotto la chiave del dominio, non solo
        # sotto la chiave del blocco.
        for riga in blocco_dati.split("\n"):
            riga_lower = riga.lower()
            chiave_dominio = None
            if "ebay." in riga_lower or "ebay.it" in riga_lower or "ebay.com" in riga_lower:
                chiave_dominio = "ebaysold"
            elif "vestiairecollective." in riga_lower:
                chiave_dominio = "vestiairecollective"
            elif "vinted." in riga_lower:
                chiave_dominio = "vinted"
            elif "depop." in riga_lower:
                chiave_dominio = "depop"
            elif "grailed." in riga_lower:
                chiave_dominio = "grailed"
            if chiave_dominio:
                prezzi_riga = _estrai_prezzi_da_pool_ricerca(riga)
                if prezzi_riga:
                    risultato.setdefault(chiave_dominio, set()).update(prezzi_riga)
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


# ---------------------------------------------------------------------------
# MOTORE DI VERDETTO DETERMINISTICO
# ---------------------------------------------------------------------------
# Tutto cio' che prima era "il modello scrive un numero, una rete di
# sicurezza controlla via regex se il numero e' plausibile" vive qui, come
# aritmetica su dati strutturati. Il cervello fornisce i DATI della
# valutazione (linea, comp, prezzo target), queste funzioni producono il
# VERDETTO (margine, ROI, decisione, urgenza, offerta di trattativa).
#
# Conseguenza pratica: le violazioni che le vecchie reti inseguivano non
# sono piu' "corrette a posteriori", sono impossibili. Un COMPRA sotto
# soglia non puo' esistere perche' la decisione E' la soglia; un'offerta di
# trattativa oltre il 40% non puo' esistere perche' l'offerta E' il 40%.

# URGENZA_RICHIEDE_COMP_REALE: "Alta urgenza" e' l'unico livello che fa
# scattare i bottoni di azione rapida su Telegram, cioe' l'unico che chiede
# all'utente di muoversi subito. Per quel livello si pretende almeno un comp
# realmente presente nel pool di ricerca, non solo comp ricordati dal
# modello (vedi COMP_DA_MEMORIA_AMMESSI): i comp da memoria restano validi
# per calcolare la stima e per COMPRA/TRATTA, ma non bastano da soli a
# dichiarare un'urgenza. Mettere a False per togliere anche questo vincolo.
URGENZA_RICHIEDE_COMP_REALE = True

EMOJI_DECISIONE = {
    "COMPRA": "🟢",
    "TRATTA": "🟡",
    "NON COMPRARE": "🔴",
    "CHIEDI ALTRE FOTO": "🔵",
    "DATI INSUFFICIENTI": "🔵",
}

ETICHETTA_LEGIT = {
    "probabilmente_autentico": "Probabilmente autentico",
    "sospetto_servono_altre_foto": "Sospetto, servono altre foto",
    "probabilmente_falso": "Probabilmente falso",
    "non_verificabile": "Non verificabile",
}

ETICHETTA_RISCHIO = {"basso": "B", "medio": "M", "alto": "A", "molto_alto": "MA"}
ETICHETTA_CONFIDENZA = {"alta": "A", "media": "M", "bassa": "B"}
ETICHETTA_FONTE_COMP = {
    "vinted_testo": "Vinted",
    "vinted_visuale": "Vinted visuale",
    "memoria_modello": "memoria modello",
}

# Traduzione dalle chiavi-fonte normalizzate del pool (prodotte da
# _prezzi_per_fonte_da_pool a partire dalle etichette "📍 FONTE: ...") alle
# diciture mostrate accanto a ogni comp nel messaggio Telegram. L'ordine
# conta: si applica il primo prefisso che combacia, e "vintedricercavisuale"
# va controllato PRIMA di "vinted", che ne e' un prefisso.
PREFISSI_FONTE_POOL = [
    ("vintedricercavisuale", "Vinted visuale"),
    ("ricercaondemand", "ricerca on-demand"),
    ("vinted", "Vinted"),
    ("ebaysold", "eBay"),
    ("vestiairecollective", "Vestiaire"),
    ("depop", "Depop"),
    ("grailed", "Grailed"),
]


def _etichetta_fonte_pool(chiave):
    for prefisso, etichetta in PREFISSI_FONTE_POOL:
        if chiave.startswith(prefisso):
            return etichetta
    return "ricerca"


def _a_float(valore, default=None):
    """Conversione tollerante: il JSON strutturato garantisce il TIPO
    dichiarato nello schema, non che il valore sia sensato. Un modello puo'
    comunque restituire una stringa dove lo schema chiede un numero se il
    provider allenta il vincolo, quindi la conversione resta difensiva."""
    if valore is None:
        return default
    if isinstance(valore, bool):
        return default
    if isinstance(valore, (int, float)):
        return float(valore)
    try:
        return float(str(valore).replace("€", "").replace(",", ".").strip())
    except (ValueError, TypeError):
        return default


def valida_payload_cervello(verdetto):
    """Normalizza e mette in sicurezza il JSON ricevuto dal cervello.

    Lo schema garantisce la FORMA (quali campi, di che tipo), non la
    SENSATEZZA dei valori: uno sconto del 95%, un deal score di 47 o un
    prezzo target negativo sono tutti conformi allo schema. I limiti
    numerici si applicano qui, non nello schema, perche' un vincolo
    dichiarato al modello viene rispettato quasi sempre mentre uno
    applicato in codice viene rispettato sempre.

    Ritorna (verdetto_normalizzato, elenco_problemi). I problemi non
    bloccano l'elaborazione: vengono mostrati in coda al messaggio, cosi'
    un campo compilato male resta visibile invece di sparire dietro un
    valore di default silenzioso.
    """
    problemi = []
    v = dict(verdetto or {})

    # --- enum: un valore fuori lista diventa il default piu' prudente
    def _enum(campo, ammessi, default):
        valore = (v.get(campo) or "").strip().lower() if isinstance(v.get(campo), str) else None
        if valore in ammessi:
            v[campo] = valore
            return
        if v.get(campo) is not None:
            problemi.append(f"{campo}='{v.get(campo)}' non riconosciuto, uso '{default}'")
        v[campo] = default

    _enum("corrispondenza_brand",
          {"corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_verificabile"},
          "non_verificabile")
    _enum("legit_verdetto",
          {"probabilmente_autentico", "sospetto_servono_altre_foto", "probabilmente_falso", "non_verificabile"},
          "non_verificabile")
    _enum("rischio_fake", {"basso", "medio", "alto", "molto_alto"}, "medio")
    _enum("confidenza", {"alta", "media", "bassa"}, "bassa")
    _enum("profilo_venditore", {"privato_genuino", "reseller_esperto", "non_determinabile"}, "non_determinabile")
    _enum("domanda_mercato", {"alta", "media", "bassa"}, "media")
    _enum("fascia_taglia", {"centrale", "estrema", "ignota"}, "ignota")

    # --- numeri
    v["prezzo_target_vendita_eur"] = _a_float(v.get("prezzo_target_vendita_eur"), 0.0) or 0.0
    if v["prezzo_target_vendita_eur"] <= 0:
        problemi.append("prezzo_target_vendita_eur assente o non positivo")

    v["comp_riferimento_eur"] = _a_float(v.get("comp_riferimento_eur"), None)
    v["tetto_prezzo_linea_eur"] = _a_float(v.get("tetto_prezzo_linea_eur"), None)

    sconto = _a_float(v.get("sconto_ask_applicato_pct"), 25.0) or 25.0
    if not (20 <= sconto <= 30):
        problemi.append(f"sconto ASK {sconto:.0f}% fuori dal range 20-30, riportato nel range")
        sconto = min(30.0, max(20.0, sconto))
    v["sconto_ask_applicato_pct"] = sconto

    # --- sconto difetto: clamp a 0-50, coerente con difetto_significativo.
    v["difetto_significativo"] = bool(v.get("difetto_significativo"))
    v["difetto_strutturale"] = bool(v.get("difetto_strutturale"))
    if v["difetto_strutturale"] and not v["difetto_significativo"]:
        # Un difetto strutturale e' per definizione significativo: la
        # combinazione opposta e' una contraddizione, si tiene la piu' grave.
        v["difetto_significativo"] = True

    # gravita_difetto_strutturale: solo 'grave' blocca automaticamente (vedi
    # calcola_verdetto). Un difetto_strutturale=true senza gravita' valida e'
    # trattato come 'grave' per prudenza -- e' lo stesso principio degli enum
    # dell'Occhio: il default su un campo di rischio e' sempre quello che
    # blocca di piu', mai quello che lascia passare.
    gravita_struct = v.get("gravita_difetto_strutturale")
    gravita_struct = gravita_struct.strip().lower() if isinstance(gravita_struct, str) else None
    if v["difetto_strutturale"]:
        if gravita_struct not in ("lieve", "moderata", "grave"):
            if gravita_struct is not None:
                problemi.append(
                    f"gravita_difetto_strutturale='{v.get('gravita_difetto_strutturale')}' "
                    "non riconosciuta, uso 'grave' (default prudente)"
                )
            gravita_struct = "grave"
    else:
        gravita_struct = None
    v["gravita_difetto_strutturale"] = gravita_struct

    sconto_difetto = _a_float(v.get("sconto_difetto_pct"), 0.0) or 0.0
    if sconto_difetto < 0 or sconto_difetto > 50:
        problemi.append(f"sconto_difetto_pct {sconto_difetto:.0f}% fuori dal range 0-50, riportato nel range")
        sconto_difetto = min(50.0, max(0.0, sconto_difetto))
    if not v["difetto_significativo"] and sconto_difetto > 0:
        problemi.append(f"sconto_difetto_pct={sconto_difetto:.0f}% ignorato: difetto_significativo=false")
        sconto_difetto = 0.0
    if v["difetto_significativo"] and sconto_difetto == 0:
        # dichiarato un difetto ma nessuno sconto: prudenza minima di default
        # invece di lasciarlo a zero come se il difetto non pesasse nulla.
        sconto_difetto = 10.0
        problemi.append("difetto_significativo=true senza sconto_difetto_pct: applicato 10% di default")
    v["sconto_difetto_pct"] = sconto_difetto
    v["descrizione_difetto"] = (v.get("descrizione_difetto") or "").strip() or None

    giorni = _a_float(v.get("giorni_stimati_vendita"), 30.0) or 30.0
    v["giorni_stimati_vendita"] = int(min(365, max(1, giorni)))

    deal = _a_float(v.get("deal_score"), 5.0) or 5.0
    v["deal_score"] = int(min(10, max(1, deal)))

    # --- legit: il motivo deve essere circostanziato quando accusa un falso.
    # Sostituisce verifica_falso_ha_motivazione, che doveva indovinare dal
    # testo se una motivazione fosse presente: qui il campo e' isolato e si
    # controlla direttamente.
    motivo = (v.get("legit_motivo_specifico") or "").strip()
    if v["legit_verdetto"] == "probabilmente_falso" and len(motivo) < 40:
        problemi.append(
            "verdetto 'probabilmente falso' senza motivazione circostanziata: "
            "verificare a mano le foto prima di scartare l'annuncio"
        )
    v["legit_motivo_specifico"] = motivo or "Nessun dettaglio fornito dall'analisi."

    # --- liste
    comp_validi = []
    for grezzo in (v.get("comp_candidati") or []):
        if not isinstance(grezzo, dict):
            continue
        prezzo = _a_float(grezzo.get("prezzo_eur"), None)
        if prezzo is None or prezzo <= 0:
            continue
        comp = dict(grezzo)
        comp["prezzo_eur"] = round(prezzo, 2)
        fonte = (comp.get("fonte") or "").strip().lower()
        comp["fonte"] = fonte if fonte in ETICHETTA_FONTE_COMP else "memoria_modello"
        comp["escluso"] = bool(comp.get("escluso"))
        comp["stessa_categoria"] = bool(comp.get("stessa_categoria", True))
        comp["stessa_linea"] = bool(comp.get("stessa_linea", True))
        comp["titolo_verbatim"] = (comp.get("titolo_verbatim") or "senza titolo").strip()
        comp_validi.append(comp)
    v["comp_candidati"] = comp_validi

    v["segnali_domanda"] = [s for s in (v.get("segnali_domanda") or []) if isinstance(s, str) and s.strip()]
    v["domande_al_venditore"] = [
        d.strip() for d in (v.get("domande_al_venditore") or [])
        if isinstance(d, str) and d.strip()
    ][:2]

    for campo in ("note_analista", "motivo_profilo_venditore", "linea_o_era_rilevata"):
        if not (v.get(campo) or "").strip():
            v[campo] = "non specificato"

    return v, problemi


def classifica_provenienza_comp(v, pool_ricerca_grezzo):
    """Confronta ogni prezzo dichiarato dal cervello con i prezzi realmente
    presenti nel pool di ricerca e ne stabilisce la provenienza REALE.

    Questa funzione sostituisce verifica_comp_citati_sono_reali, e la
    differenza e' tutta nel tipo di dato su cui lavora. Prima il controllo
    doveva ricostruire, da un paragrafo di prosa, quali numeri fossero comp
    citati e quali invece aritmetica del calcolo (fee, spedizione, margine,
    importi scontati), indovinando la fonte dichiarata dalla vicinanza
    testuale di una parola: 300 righe di euristiche, e comunque 4 falsi
    positivi in poche ore. Ora i comp sono una lista di numeri isolati e
    gia' etichettati, quindi il controllo e' una differenza tra insiemi:
    il prezzo compare nel pool oppure no.

    Cosa NON fa piu', per scelta esplicita dell'utente (2026-09-19): non
    declassa nulla e non scarta l'item. Un prezzo che non risulta nel pool
    viene semplicemente marcato 'memoria_modello' e mostrato come tale nel
    messaggio. Vedi COMP_DA_MEMORIA_AMMESSI per la versione stretta.
    """
    prezzi_pool = _estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo or "")
    # Mappa {chiave_fonte: set(prezzi)}: permette di dire non solo SE un
    # comp e' reale, ma DA QUALE fonte del pool proviene (Vinted testo,
    # ricerca visuale, ricerca on-demand del cervello), cosi' l'etichetta
    # accanto al prezzo nel messaggio Telegram e' quella vera e non quella
    # dichiarata dal modello.
    prezzi_per_fonte = _prezzi_per_fonte_da_pool(pool_ricerca_grezzo or "")

    riclassificati = 0
    for comp in v.get("comp_candidati", []):
        nel_pool = any(
            abs(comp["prezzo_eur"] - reale) <= TOLLERANZA_COMP_EUR for reale in prezzi_pool
        )
        comp["nel_pool"] = nel_pool
        if nel_pool:
            # Se il modello l'aveva marcato come ricordato ma il prezzo c'e'
            # davvero, si fida del dato oggettivo: e' un comp reale.
            comp["fonte_reale"] = comp["fonte"] if comp["fonte"] != "memoria_modello" else "vinted_testo"
            fonti_trovate = [
                _etichetta_fonte_pool(chiave)
                for chiave, prezzi in prezzi_per_fonte.items()
                if any(abs(comp["prezzo_eur"] - prezzo) <= TOLLERANZA_COMP_EUR for prezzo in prezzi)
            ]
            # Lo stesso prezzo puo' comparire in piu' blocchi del pool (es.
            # un risultato Vinted che appare sia nella ricerca testuale sia
            # in quella visuale): si mostrano tutte le fonti in cui e' stato
            # trovato, senza duplicati e in ordine stabile.
            comp["etichetta_fonte"] = " + ".join(dict.fromkeys(fonti_trovate)) or "ricerca"
        else:
            if comp["fonte"] != "memoria_modello":
                riclassificati += 1
            comp["fonte_reale"] = "memoria_modello"
            comp["etichetta_fonte"] = "memoria modello"

    n_memoria = sum(1 for c in v.get("comp_candidati", []) if c["fonte_reale"] == "memoria_modello")
    if riclassificati:
        log.info(
            "classifica_provenienza_comp: %d comp dichiarati come risultati di ricerca non "
            "compaiono nel pool, riclassificati come memoria del modello (pool: %d prezzi).",
            riclassificati, len(prezzi_pool),
        )
    return {
        "n_comp": len(v.get("comp_candidati", [])),
        "n_memoria": n_memoria,
        "n_riclassificati": riclassificati,
        "n_prezzi_pool": len(prezzi_pool),
    }


def _comp_utilizzabili(v):
    """I comp che entrano nel calcolo della stima: non esclusi dal modello,
    stessa categoria, stessa linea, e - solo se COMP_DA_MEMORIA_AMMESSI e'
    False - realmente presenti nel pool."""
    utilizzabili = []
    for comp in v.get("comp_candidati", []):
        if comp.get("escluso") or not comp.get("stessa_categoria") or not comp.get("stessa_linea"):
            continue
        if not COMP_DA_MEMORIA_AMMESSI and comp.get("fonte_reale") == "memoria_modello":
            continue
        utilizzabili.append(comp)
    return utilizzabili


def _percentile(valori_ordinati, p):
    """Percentile p (0-100) su una lista GIA' ordinata, interpolazione
    lineare tra i due valori piu' vicini. Con un solo valore ritorna quello;
    con lista vuota ritorna 0.0 (il chiamante gestisce comunque il caso
    'nessun comp' a monte, qui e' solo per non esplodere)."""
    n = len(valori_ordinati)
    if n == 0:
        return 0.0
    if n == 1:
        return valori_ordinati[0]
    posizione = (p / 100.0) * (n - 1)
    indice_basso = int(posizione)
    indice_alto = min(indice_basso + 1, n - 1)
    frazione = posizione - indice_basso
    return valori_ordinati[indice_basso] + (valori_ordinati[indice_alto] - valori_ordinati[indice_basso]) * frazione


def _filtra_outlier(prezzi):
    """Scarta i comp oltre 3x la mediana o sotto 1/3 della mediana: quasi
    sempre appartengono a un capo diverso (categoria, materiale o edizione)
    o sono un ASK irrealistico finito per errore nei risultati.

    Era una procedura descritta a parole nel prompt e quindi applicata "di
    solito"; ora e' aritmetica e viene applicata sempre. Sotto i 3 prezzi
    non si filtra: con due soli valori la mediana non distingue un outlier
    da un campione piccolo, e scartarne uno lascerebbe la stima appesa a un
    unico comp isolato.
    """
    if len(prezzi) < 3:
        return list(prezzi), []
    mediana = statistics.median(prezzi)
    tenuti = [p for p in prezzi if mediana / 3 <= p <= mediana * 3]
    scartati = [p for p in prezzi if p not in tenuti]
    if len(tenuti) < 2:
        return list(prezzi), []  # il filtro lascerebbe troppo poco: meglio non filtrare
    return tenuti, scartati


def calcola_verdetto(v, prezzo_prodotto):
    """Trasforma i dati del cervello nel verdetto finale. Unico punto del
    bot dove si decide COMPRA/TRATTA/NON COMPRARE e dove si calcolano
    margine, ROI e obiettivo di trattativa."""
    limiti_applicati = []

    if prezzo_prodotto is None or prezzo_prodotto <= 0:
        # Senza il prezzo dell'annuncio non esiste nessun calcolo economico
        # possibile. Meglio dirlo che produrre un NON COMPRARE che sembra un
        # giudizio sul capo quando e' solo un dato mancante.
        return {
            "decisione": "DATI INSUFFICIENTI",
            "urgenza": "Bassa",
            "prezzo_prodotto": prezzo_prodotto,
            "acquisto_pieno": None, "incasso": None, "margine": None, "roi": None,
            "prezzo_target": v.get("prezzo_target_vendita_eur"),
            "tratta_costo": None, "tratta_margine": None, "tratta_roi": None,
            "comp_usati": [], "comp_scartati_outlier": [],
            "limiti_applicati": ["prezzo dell'annuncio non disponibile: nessun calcolo economico eseguito"],
        }

    acquisto_pieno = (
        prezzo_prodotto * (1 + COMMISSIONE_PROTEZIONE_PCT)
        + COMMISSIONE_PROTEZIONE_FISSA
        + SPEDIZIONE_STIMATA_EUR
    )

    target = v["prezzo_target_vendita_eur"]
    target_dichiarato = target

    # --- limite 1: tetto di linea (es. JEAN'S PAUL GAULTIER)
    tetto = v.get("tetto_prezzo_linea_eur")
    if tetto and target > tetto:
        target = tetto
        limiti_applicati.append(f"tetto di linea €{tetto:.2f} ({v.get('linea_o_era_rilevata')})")

    # --- limite 2: ancoraggio al comp di riferimento, gia' scontato
    # (era verifica_ancoraggio_prezzo_comp, 140 righe di regex sul testo)
    fattore_sconto = 1 - v["sconto_ask_applicato_pct"] / 100.0
    riferimento = v.get("comp_riferimento_eur")
    if riferimento and riferimento > 0:
        massimo_consentito = riferimento * fattore_sconto
        if target > massimo_consentito:
            limiti_applicati.append(
                f"ancoraggio al comp di riferimento €{riferimento:.2f} "
                f"scontato {v['sconto_ask_applicato_pct']:.0f}% = €{massimo_consentito:.2f}"
            )
            target = massimo_consentito

    # --- limite 3: filtro outlier sui comp utilizzabili
    utilizzabili = _comp_utilizzabili(v)
    prezzi = sorted(c["prezzo_eur"] for c in utilizzabili)
    prezzi_tenuti, prezzi_scartati = _filtra_outlier(prezzi)

    if prezzi_tenuti:
        if v.get("materiale_confermato"):
            # Materiale noto: il tetto e' il comp piu' alto rimasto dopo il
            # filtro, scontato.
            massimo_consentito = max(prezzi_tenuti) * fattore_sconto
            descrizione_limite = f"comp piu' alto €{max(prezzi_tenuti):.2f}"
        else:
            # Materiale non confermato: tetto sul 75* percentile dei comp
            # validi, non piu' sulla mediana. Storia della regola: prima
            # usava il comp piu' economico (troppo punitiva: bastava che il
            # cervello marcasse materiale_confermato a false per prudenza
            # eccessiva -- anche con titolo/etichetta che lo dichiaravano
            # gia' esplicitamente -- per far crollare la stima su un singolo
            # comp isolato in fondo alla forchetta). Corretta alla mediana,
            # che pero' si e' rivelata a sua volta troppo severa: tagliava
            # fuori meta' dei comp e, sommata allo sconto ASK del 25-30%
            # gia' applicato altrove, portava spesso un affare con margine
            # sano vicino al pareggio (caso reale: gonna Marni, mediana
            # comp €59 -> tetto €44.25, quando la stima ragionata del
            # cervello era €55 e i comp arrivavano fino a €100).
            # Il 75* percentile resta piu' prudente del "comp piu' caro"
            # riservato al materiale confermato (non si fida del singolo
            # comp piu' alto, spesso un outlier residuo), ma non scarta piu'
            # a priori la meta' superiore della forchetta: lascia passare la
            # stima del cervello quando e' gia' in linea con il grosso dei
            # comp, e interviene solo quando la supera davvero.
            percentile_75 = _percentile(prezzi_tenuti, 75)
            massimo_consentito = percentile_75 * fattore_sconto
            descrizione_limite = f"materiale non confermato, 75* percentile comp €{percentile_75:.2f}"
        if target > massimo_consentito:
            limiti_applicati.append(
                f"{descrizione_limite} scontato {v['sconto_ask_applicato_pct']:.0f}% = €{massimo_consentito:.2f}"
            )
            target = massimo_consentito

    # --- limite 4: sconto per difetto dichiarato sul capo. Si applica DOPO
    # tetto di linea/ancoraggio/materiale perche' riguarda le condizioni di
    # QUESTO esemplare, non il valore di mercato del modello in generale --
    # un difetto va scontato sul prezzo gia' corretto per tutto il resto,
    # non al posto degli altri limiti. Prima non esisteva nessun controllo
    # numerico qui: un difetto descritto a parole in note_analista poteva
    # non riflettersi affatto nel prezzo finale.
    sconto_difetto_pct = v.get("sconto_difetto_pct") or 0.0
    if sconto_difetto_pct > 0:
        target_prima_difetto = target
        target = target * (1 - sconto_difetto_pct / 100.0)
        descrizione_difetto = v.get("descrizione_difetto")
        limiti_applicati.append(
            f"difetto dichiarato ({descrizione_difetto or 'non specificato'}): "
            f"sconto {sconto_difetto_pct:.0f}% da €{target_prima_difetto:.2f} a €{target:.2f}"
        )

    # Difetto strutturale 'lieve'/'moderata' (vedi schema): non forza NON
    # COMPRARE (lo fa solo 'grave', piu' sotto), ma la nota resta visibile
    # per una decisione informata invece di sparire dentro il generico
    # "difetto dichiarato" qui sopra.
    if v.get("difetto_strutturale") and v.get("gravita_difetto_strutturale") in ("lieve", "moderata"):
        limiti_applicati.append(
            f"difetto strutturale {v['gravita_difetto_strutturale']} "
            f"({v.get('descrizione_difetto') or 'non specificato'}): non bloccante, "
            "gia' scontato nel prezzo target qui sopra"
        )

    target = max(0.0, round(target, 2))

    incasso = target * QUOTA_INCASSO_NETTO
    margine = incasso - acquisto_pieno
    roi = (margine / acquisto_pieno * 100) if acquisto_pieno > 0 else 0.0

    # --- trattativa: SEMPRE al massimo sconto consentito sul solo prodotto,
    # mai sulla spedizione. Sostituisce applica_soglia_trattativa_40_percento,
    # che correggeva l'offerta ma lasciava dichiaratamente incoerenti margine
    # e ROI della riga corretta (la vecchia nota diceva all'utente di
    # verificarli a mano). Qui sono ricalcolati sullo stesso incasso.
    prezzo_trattato = prezzo_prodotto * (1 - SCONTO_MAX_TRATTATIVA)
    tratta_costo = (
        prezzo_trattato * (1 + COMMISSIONE_PROTEZIONE_PCT)
        + COMMISSIONE_PROTEZIONE_FISSA
        + SPEDIZIONE_STIMATA_EUR
    )
    tratta_margine = incasso - tratta_costo
    tratta_roi = (tratta_margine / tratta_costo * 100) if tratta_costo > 0 else 0.0

    # --- decisione
    supera_soglia = margine >= SOGLIA_MARGINE_COMPRA and roi >= SOGLIA_ROI_COMPRA
    tratta_supera_soglia = tratta_margine >= SOGLIA_MARGINE_COMPRA and tratta_roi >= SOGLIA_ROI_COMPRA

    if v["corrispondenza_brand"] == "brand_estraneo":
        decisione = "NON COMPRARE"
        limiti_applicati.append("brand reale estraneo al segmento monitorato")
    elif v["legit_verdetto"] == "probabilmente_falso":
        decisione = "NON COMPRARE"
    elif v.get("difetto_strutturale") and v.get("gravita_difetto_strutturale") == "grave":
        # Regola di dominio che finora viveva solo come frase nel prompt
        # ("Difetti strutturali = NON COMPRARE sempre, invendibili") e quindi
        # veniva applicata solo se il modello se ne ricordava. Dopo
        # l'introduzione di sconto_difetto_pct il rischio era anzi aumentato:
        # un capo con uno strappo riceveva uno sconto percentuale sul target e,
        # se il prezzo d'acquisto era basso, tornava comunque COMPRA.
        # Qui la regola e' aritmetica e non dipende piu' dal buon senso del
        # modello, a cui resta solo il compito di dire se il difetto c'e'.
        #
        # CORRETTO il 2026-09-20 (caso reale: t-shirt Jean Paul Gaultier
        # d'archivio con un piccolo foro isolato su una manica in tessuto a
        # rete, comprata comunque dall'utente in trattativa): il blocco
        # automatico incondizionato era troppo rigido, stesso difetto della
        # regola "materiale non confermato" prima di essere corretta. Ora
        # blocca solo la gravita' 'grave'; 'lieve' e 'moderata' restano un
        # capo normalmente valutabile, gia' scontato da sconto_difetto_pct
        # qualche riga sopra.
        decisione = "NON COMPRARE"
        limiti_applicati.append(
            f"difetto strutturale grave ({v.get('descrizione_difetto') or 'non specificato'}): "
            "capo invendibile, decisione forzata a NON COMPRARE"
        )
    elif supera_soglia:
        # "non_verificabile" NON puo' cadere nel ramo COMPRA. Significa che
        # non c'e' stata nessuna prova di autenticita' da esaminare (nessuna
        # etichetta leggibile), quindi il margine alto e' calcolato su un capo
        # che potrebbe essere qualsiasi cosa: la risposta giusta e' chiedere
        # altre foto, non comprare.
        #
        # Due percorsi lo rendono raggiungibile, entrambi verificati:
        # 1. scraping foto fallito (fallback_solo_cover_photo): lo skip
        #    "nessuna etichetta" viene deliberatamente bypassato per non
        #    perdere l'annuncio, e il Cervello risponde "non_verificabile";
        # 2. payload malformato: valida_payload_cervello usa proprio
        #    "non_verificabile" come default prudente quando l'enum non e'
        #    riconosciuto -- prima di questa correzione un JSON sformato del
        #    Cervello si trasformava in un COMPRA.
        if v["legit_verdetto"] in ("sospetto_servono_altre_foto", "non_verificabile"):
            decisione = "CHIEDI ALTRE FOTO"
        else:
            decisione = "COMPRA"
    elif tratta_supera_soglia:
        decisione = "TRATTA"
    else:
        decisione = "NON COMPRARE"

    # --- urgenza: mai dedotta dai soli numeri, serve domanda di mercato reale
    comp_reali = [c for c in utilizzabili if c.get("fonte_reale") != "memoria_modello"]
    urgenza = "Bassa"
    if decisione in ("COMPRA", "TRATTA"):
        urgenza = "Media"
    if (
        decisione == "COMPRA"
        and margine >= SOGLIA_MARGINE_URGENZA
        and roi >= SOGLIA_ROI_URGENZA
        and v["domanda_mercato"] == "alta"
        and v["segnali_domanda"]
        and v["fascia_taglia"] != "estrema"
        and len(prezzi_tenuti) >= 2
        and (not URGENZA_RICHIEDE_COMP_REALE or comp_reali)
    ):
        urgenza = "Alta"

    return {
        "decisione": decisione,
        "urgenza": urgenza,
        "prezzo_prodotto": prezzo_prodotto,
        "acquisto_pieno": acquisto_pieno,
        "incasso": incasso,
        "margine": margine,
        "roi": roi,
        "prezzo_target": target,
        "prezzo_target_dichiarato": target_dichiarato,
        "tratta_prezzo_prodotto": prezzo_trattato,
        "tratta_costo": tratta_costo,
        "tratta_margine": tratta_margine,
        "tratta_roi": tratta_roi,
        "comp_usati": prezzi_tenuti,
        "comp_scartati_outlier": prezzi_scartati,
        "n_comp_reali": len(comp_reali),
        "limiti_applicati": limiti_applicati,
    }


def render_messaggio_verdetto(v, verdetto, problemi=None, stats_comp=None):
    """Costruisce il messaggio Telegram dal verdetto calcolato. E' l'unico
    posto del bot dove si scrivono emoji di decisione e cifre: il modello
    non produce piu' nessuna delle due, quindi non esiste piu' il caso
    'testo e numeri si contraddicono'."""
    dec = verdetto["decisione"]
    emoji = EMOJI_DECISIONE.get(dec, "🔵")

    righe = ["## Verdetto", f"{emoji} **{dec}** · {verdetto['urgenza']} urgenza", ""]

    if verdetto["margine"] is None:
        righe.append("💰 Calcolo economico non disponibile: prezzo dell'annuncio non rilevato.")
    else:
        righe.append(
            f"💰 €{verdetto['acquisto_pieno']:.2f} → €{verdetto['incasso']:.2f} → "
            f"**€{verdetto['margine']:.2f} (ROI {verdetto['roi']:.0f}%)**"
        )
        righe.append(f"📈 Vendita stimata: €{verdetto['prezzo_target']:.2f} · Linea: {v.get('linea_o_era_rilevata')}")

    legit = ETICHETTA_LEGIT.get(v["legit_verdetto"], v["legit_verdetto"])
    righe.append(f"🏷️ Legit: {legit} — {v['legit_motivo_specifico']}")
    righe.append(
        f"🕐 ~{v['giorni_stimati_vendita']} giorni · Deal {v['deal_score']}/10 · "
        f"Rischio fake: {ETICHETTA_RISCHIO.get(v['rischio_fake'], '?')} · "
        f"Confidenza: {ETICHETTA_CONFIDENZA.get(v['confidenza'], '?')}"
    )

    if v.get("mese_consigliato_pubblicazione"):
        righe.append(f"📅 Fuori stagione: pubblicare da {v['mese_consigliato_pubblicazione']}")

    # --- obiettivo trattativa: mostrato solo quando e' la decisione presa.
    # L'importo e' quello calcolato al massimo sconto consentito, non una
    # proposta del modello, quindi margine e ROI qui sotto sono coerenti con
    # l'incasso del verdetto principale per costruzione.
    if dec == "TRATTA":
        righe.append("")
        righe.append(
            f"🤝 Obiettivo trattativa: offrire €{verdetto['tratta_prezzo_prodotto']:.2f} sul prodotto "
            f"(costo pieno €{verdetto['tratta_costo']:.2f}) → €{verdetto['incasso']:.2f} → "
            f"**€{verdetto['tratta_margine']:.2f} (ROI {verdetto['tratta_roi']:.0f}%)**"
        )

    # --- messaggio al venditore e domande: solo dove servono davvero.
    # Il vecchio backstop a colpi di regex (rimozione dei blocchi "Messaggio
    # da inviare"/"Da chiedere" da un testo gia' generato) non serve piu':
    # qui i blocchi si aggiungono, non si tolgono.
    serve_messaggio = dec in ("TRATTA", "CHIEDI ALTRE FOTO")
    template = (v.get("messaggio_venditore_template") or "").strip()
    messaggio_sostituito = False
    if serve_messaggio and template:
        if dec == "TRATTA":
            if "{OFFERTA}" in template:
                testo_messaggio = template.replace("{OFFERTA}", f"€{verdetto['tratta_prezzo_prodotto']:.2f}")
            else:
                # Il cervello scrive messaggio_venditore_template SENZA sapere
                # quale decisione prendera' il sistema (la calcola solo dopo,
                # in calcola_verdetto): puo' quindi scrivere un messaggio che
                # da' per scontato l'acquisto a prezzo pieno ("lo prendo
                # subito") anche quando poi la decisione risulta TRATTA.
                # Mandare quel testo contraddirebbe la trattativa mostrata
                # sopra, quindi si sostituisce con un'apertura generica che
                # propone davvero l'offerta calcolata.
                testo_messaggio = (
                    f"Ciao! Molto interessato, te lo prenderei subito a "
                    f"€{verdetto['tratta_prezzo_prodotto']:.2f}. Fammi sapere se puo' andare, grazie!"
                )
                messaggio_sostituito = True
        else:
            # Su CHIEDI ALTRE FOTO non c'e' nessuna offerta da fare: se il
            # modello ha lasciato comunque il segnaposto, va tolto invece di
            # finire nel messaggio come testo letterale.
            testo_messaggio = template.replace("{OFFERTA}", "").strip()
        righe += ["", "---", "📨 **Messaggio da inviare:**", f'"{testo_messaggio}"']
        if messaggio_sostituito:
            righe.append(
                "_⚠️ messaggio del cervello sostituito: proponeva l'acquisto a prezzo pieno "
                "senza nessuna offerta, in contraddizione con la decisione TRATTA._"
            )

    if serve_messaggio and v.get("domande_al_venditore"):
        righe += ["", "---", "❓ **Da chiedere**: " + " ".join(v["domande_al_venditore"])]

    # --- analisi
    righe += ["", "---", "🧠 **Analisi dell'analista:**", v["note_analista"]]
    if v.get("motivo_profilo_venditore") and v["motivo_profilo_venditore"] != "non specificato":
        righe.append(f"👤 Venditore: {v['motivo_profilo_venditore']}")

    # --- comp usati, con la provenienza dichiarata accanto a ogni prezzo
    comp_utilizzabili = [c for c in v.get("comp_candidati", []) if not c.get("escluso")]
    comp_visibili = comp_utilizzabili[:6]
    if comp_visibili:
        righe += ["", "📊 **Comp considerati:**"]
        for comp in comp_visibili:
            etichetta = comp.get("etichetta_fonte") or ETICHETTA_FONTE_COMP.get(
                comp.get("fonte_reale", comp["fonte"]), "?")
            titolo = comp["titolo_verbatim"]
            titolo = titolo[:60] + "…" if len(titolo) > 60 else titolo
            righe.append(f"• €{comp['prezzo_eur']:.2f} — {titolo} _[{etichetta}]_")
        # Split per fonte calcolato su TUTTI i comp utilizzabili (non solo i
        # primi 6 mostrati sopra in dettaglio) -- richiesto dall'utente il
        # 2026-09-20 per vedere a colpo d'occhio quanto pesa ciascuna fonte
        # (Vinted testo/Serper, Vinted ricerca visuale, ragionamento/memoria
        # del modello) senza dover attivare DEBUG_CONFRONTO_COMP_TELEGRAM,
        # che aggiunge un blocco diagnostico molto piu' verboso e pensato
        # per un altro scopo (confrontare i prezzi citati dal Cervello con
        # quelli davvero ricevuti in pool).
        conteggio_fonti = {}
        for c in comp_utilizzabili:
            fonte = c.get("fonte_reale", c["fonte"])
            conteggio_fonti[fonte] = conteggio_fonti.get(fonte, 0) + 1
        split_txt = " · ".join(
            f"{ETICHETTA_FONTE_COMP.get(fonte, fonte)}: {conteggio_fonti[fonte]}"
            for fonte in ("vinted_testo", "vinted_visuale", "memoria_modello")
            if conteggio_fonti.get(fonte)
        )
        if split_txt:
            righe.append(f"_Split fonti: {split_txt}_")

    if stats_comp and stats_comp.get("n_memoria"):
        n_memoria = stats_comp["n_memoria"]
        n_pool = stats_comp["n_prezzi_pool"]
        quanti = "Tutti i" if n_memoria == stats_comp["n_comp"] else f"{n_memoria} dei"
        quanti_comp = "comp" if n_memoria == stats_comp["n_comp"] else f"{stats_comp['n_comp']} comp"
        if n_pool == 0:
            dove = "la ricerca non ha restituito nessun prezzo"
        elif n_pool == 1:
            dove = "l'unico prezzo trovato dalla ricerca e' diverso"
        else:
            dove = f"non compaiono tra i {n_pool} prezzi trovati dalla ricerca"
        righe.append(
            f"\n_ℹ️ {quanti} {quanti_comp} vengono dalla conoscenza del modello, non da annunci "
            f"verificati: {dove}._"
        )

    if verdetto.get("comp_scartati_outlier"):
        scartati = ", ".join(f"€{p:.2f}" for p in verdetto["comp_scartati_outlier"])
        righe.append(f"_🔎 Scartati dal filtro outlier (oltre 3x o sotto 1/3 della mediana): {scartati}_")

    # --- limiti applicati al prezzo: sostituisce le note "⚠️ corretto
    # automaticamente" che le vecchie reti iniettavano nel testo. Stessa
    # informazione, ma dichiarata prima del calcolo invece che rattoppata dopo.
    if verdetto.get("limiti_applicati"):
        righe.append("")
        if verdetto.get("prezzo_target_dichiarato") and verdetto.get("prezzo_target") is not None:
            if verdetto["prezzo_target_dichiarato"] > verdetto["prezzo_target"] + 0.01:
                righe.append(
                    f"⚠️ _Stima del modello €{verdetto['prezzo_target_dichiarato']:.2f} "
                    f"ridotta a €{verdetto['prezzo_target']:.2f}._"
                )
        for limite in verdetto["limiti_applicati"]:
            righe.append(f"⚠️ _{limite}_")

    if problemi:
        righe.append("")
        for problema in problemi:
            righe.append(f"⚠️ _Dato anomalo dal cervello: {problema}_")

    return "\n".join(righe)


async def _invia_risultato_telegram(listing_info, url, photo_bytes_list, header, output_finale,
                                    decisione, e_compra, scenario_usato, urgenza="Bassa"):
    item_id = _estrai_item_id_da_url(url)
    # L'urgenza ora arriva calcolata da calcola_verdetto invece di essere
    # dedotta dal testo del verdetto (_e_urgenza_alta cercava parole come
    # "alta"/"subito"/"forte" dentro la stringa di decisione, e bastava una
    # variante di wording del modello per sbagliare bersaglio).
    e_compra_urgente = e_compra and urgenza == "Alta" and decisione == "COMPRA"

    if len(photo_bytes_list) > 1:
        await telegram_send_media_group(
            TELEGRAM_OWNER_CHAT_ID,
            photo_bytes_list,
            caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto"
        )
    elif len(photo_bytes_list) == 1:
        await telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))

    if url:
        if e_compra_urgente:
            await telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, item_id)
        else:
            await telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, None)
    else:
        await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + output_finale)

    if TELEGRAM_ALERT_CHAT_ID and e_compra:
        alert_text = (
            f"🚨 *AZIONE RICHIESTA*\n"
            f"*{listing_info.get('title')}*\n"
            f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
            f"✅ {decisione}\n"
            f"{url or ''}"
        )
        if e_compra_urgente and item_id:
            await telegram_send_with_buttons(TELEGRAM_ALERT_CHAT_ID, alert_text, url, item_id)
        else:
            await telegram_send_message(TELEGRAM_ALERT_CHAT_ID, alert_text)


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE
# ---------------------------------------------------------------------------

async def process_listing(parsed, url, cover_photo_bytes):
    listing_info = dict(parsed)
    listing_info["url"] = url
    costo_totale = 0.0

    photo_bytes_list = []
    if url:
        scraped = await scrape_vinted_listing(url)
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
            log.info("FILTRO PRE-GEMINI ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s",
                     listing_info.get("title"), motivo_skip_pre)
            return

        photo_urls = scraped.get("photo_urls", [])
        if not photo_urls:
            log.warning(
                "scrape_vinted_listing non ha restituito nessun photo_url per %s "
                "(pagina annuncio non raggiunta o regex di estrazione foto non ha trovato match).",
                url,
            )
        if photo_urls:
            # Download in parallelo con asyncio.gather al posto del
            # ThreadPoolExecutor: stesso parallelismo, senza thread e senza
            # bloccare il loop mentre le foto arrivano.
            risultati_download = await asyncio.gather(
                *(download_image_bytes(u, referer=url) for u in photo_urls)
            )
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
                retry_risultati = await asyncio.gather(
                    *(download_image_bytes(u, referer=url, max_retries=4) for u in mancanti)
                )
                photo_bytes_list.extend([img for img in retry_risultati if img])
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
        await telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
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

    # --- OCCHIO: due rami, scelti da OCCHIO_OUTPUT_JSON.
    # In entrambi i casi il resto della pipeline riceve `output_occhi` come
    # testo: in modalita' JSON e' il rendering del dict, cosi' build_skip_report
    # e il prompt del Cervello continuano a funzionare senza modifiche.
    occhio_json = None
    problemi_occhio = []
    if OCCHIO_OUTPUT_JSON:
        output_grezzo, costo_occhi, _ = await chiama_gemini(
            GEMINI_OCCHI_SYSTEM_PROMPT_JSON, user_text_occhi, photo_bytes_list,
            grounding=False, response_schema=OCCHIO_RESPONSE_SCHEMA_GEMINI)
        try:
            occhio_json, problemi_occhio = valida_payload_occhio(json.loads(output_grezzo))
            output_occhi = render_occhio_da_json(occhio_json, problemi_occhio)
            if problemi_occhio:
                log.info("Occhio JSON con %d anomalie: %s", len(problemi_occhio), problemi_occhio)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # Fallback esplicito e non silenzioso: se il JSON non e'
            # parsabile si prosegue col testo grezzo sul ramo prosa, cosi'
            # un annuncio non va perso per un problema di formato. Se
            # compare spesso nei log, e' il segnale che flash-lite non
            # regge lo schema e conviene rimettere OCCHIO_OUTPUT_JSON=false.
            log.warning("Occhio: JSON non parsabile (%s), fallback al ramo prosa. Grezzo: %s",
                        e, (output_grezzo or "")[:400])
            occhio_json = None
            output_occhi = output_grezzo
    else:
        output_occhi, costo_occhi, _ = await chiama_gemini(
            GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
    costo_totale += costo_occhi

    # Prezzo del prodotto: base di OGNI calcolo economico a valle.
    prezzo_prodotto = _a_float(listing_info.get("price"), None)

    decisione = "NON COMPRARE"
    urgenza = "Bassa"
    n_query_grounding = 0
    costo_cervello = 0.0
    pool_ricerca_grezzo = ""
    tentare_ricerca_visuale = False
    fonte_visuale_riuscita = False
    forza_ricerca = None
    verdetto_calcolato = None

    e_skip, motivo_skip = check_skip_pre_cervello(output_occhi, listing_info, occhio_json=occhio_json)
    if e_skip:
        log.info("FILTRO PRE-CERVELLO ATTIVATO. Motivo: %s", motivo_skip)
        if motivo_skip.startswith("[FALSO CONCLAMATO"):
            log.info("FALSO CONCLAMATO -- output occhi grezzo per '%s':\n%s", listing_info.get("title"), output_occhi)
        output_finale = build_skip_report(listing_info, motivo_skip, output_occhi_testo=output_occhi)
        scenario_usato = "SKIP"
    else:
        titolo_annuncio = listing_info.get("title") or ""
        brand_annuncio = listing_info.get("brand") or ""
        categoria_per_ricerca = estrai_categoria_da_titolo(
            titolo_annuncio, listing_info.get("description")) or ""
        catalog_id = listing_info.get("catalog_id")
        material_per_ricerca = listing_info.get("material_per_ricerca")
        cover_photo_id = listing_info.get("cover_photo_id")
        item_id_annuncio = _estrai_item_id_da_url(url)

        scenario_usato = "F"
        comps_text = None

        tempo_trascorso = time.time() - _serper_timestamp_ultimo_fallimento[0]
        in_raffreddamento = (
            _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
            and tempo_trascorso < RAFFREDDAMENTO_SERPER_SECONDI
        )
        serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

        if serper_disponibile:
            comps_text, serper_ok, tentare_ricerca_visuale, fonte_visuale_riuscita = await search_comps_completo(
                brand_annuncio, categoria_per_ricerca, titolo_annuncio,
                catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
                cover_photo_id=cover_photo_id, item_id=item_id_annuncio,
            )
            if serper_ok:
                scenario_usato = "G"
                _serper_fallimenti_consecutivi[0] = 0
                if _serper_notifica_esaurimento_inviata[0]:
                    _serper_notifica_esaurimento_inviata[0] = False
                    await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, "✅ Serper e' tornato a funzionare normalmente.")
            else:
                _serper_fallimenti_consecutivi[0] += 1
                _serper_timestamp_ultimo_fallimento[0] = time.time()
                if _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO:
                    if not _serper_notifica_esaurimento_inviata[0]:
                        _serper_notifica_esaurimento_inviata[0] = True
                        await telegram_send_message(
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
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                "NOTA: non ci sono risultati di ricerca pre-raccolti. Chiama la function "
                "cerca_comp_prezzo per ottenere comp reali prima di rispondere."
            )

        chiama_cervello = (
            chiama_openai_cervello_forzato if CERVELLO_PROVIDER == "openai"
            else chiama_gemini_cervello_forzato
        )
        verdetto_json, errore_cervello, costo_cervello, n_query_grounding, ricerche_extra_raw = await chiama_cervello(
            GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, forza_ricerca=forza_ricerca)
        costo_totale += costo_cervello

        # Pool di TUTTO il testo grezzo di ricerca visto dal cervello per
        # questo item: comp pre-raccolti (Scenario G) + eventuali ricerche
        # on-demand. Serve a stabilire la provenienza reale di ogni comp che
        # il cervello dichiara (vedi classifica_provenienza_comp).
        pool_ricerca_grezzo = "\n".join(filter(None, [comps_text] + ricerche_extra_raw))

        if errore_cervello:
            # Un errore qui e' definitivo: senza il JSON non c'e' verdetto da
            # calcolare. Si avvisa invece di restare in silenzio, perche' un
            # annuncio valutato a meta' e' peggio di uno non valutato.
            log.warning("Cervello fallito per '%s': %s", listing_info.get("title"), errore_cervello)
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                f"⚠️ *Valutazione non completata* — {listing_info.get('title')}\n"
                f"{errore_cervello}\n{url or ''}\n"
                f"_Costo comunque sostenuto: ${costo_totale:.4f}_"
            )
            return

        v, problemi = valida_payload_cervello(verdetto_json)
        stats_comp = classifica_provenienza_comp(v, pool_ricerca_grezzo)
        verdetto_calcolato = calcola_verdetto(v, prezzo_prodotto)
        decisione = verdetto_calcolato["decisione"]
        urgenza = verdetto_calcolato["urgenza"]
        output_finale = render_messaggio_verdetto(v, verdetto_calcolato, problemi, stats_comp)

        log.info(
            "Verdetto '%s': %s (%s urgenza) — margine=%s ROI=%s — comp usati=%d (%d da memoria) — limiti=%s",
            listing_info.get("title"), decisione, urgenza,
            f"{verdetto_calcolato['margine']:.2f}" if verdetto_calcolato["margine"] is not None else "n/d",
            f"{verdetto_calcolato['roi']:.0f}%" if verdetto_calcolato["roi"] is not None else "n/d",
            len(verdetto_calcolato["comp_usati"]), stats_comp["n_memoria"],
            verdetto_calcolato["limiti_applicati"] or "nessuno",
        )

    e_compra = decisione in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO")

    # ---- GATE MARGINE ASSOLUTO (qualita' del deal, non sicurezza) ----
    # Sopprime la notifica quando il margine netto resta sotto l'obiettivo
    # operativo, anche se ROI e soglia minima sono superati. Ora legge il
    # margine calcolato invece di riestrarlo con una regex dal testo.
    if verdetto_calcolato and SOGLIA_MARGINE_ASSOLUTO_NOTIFICA > 0:
        margine_finale = verdetto_calcolato["margine"]
        if (
            margine_finale is not None
            and margine_finale < SOGLIA_MARGINE_ASSOLUTO_NOTIFICA
            and decisione != "NON COMPRARE"
        ):
            log.info(
                "GATE MARGINE ASSOLUTO: notifica soppressa per '%s' (margine=%.2f EUR < soglia %d EUR). Decisione: %s",
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

    # ---- BLOCCO DIAGNOSTICO: da dove vengono i comp REALMENTE ricevuti ----
    # Attivo solo con DEBUG_CONFRONTO_COMP_TELEGRAM=true. Puro post-processing
    # su dati gia' raccolti: nessuna chiamata IA aggiuntiva, costo zero.
    if DEBUG_CONFRONTO_COMP_TELEGRAM and scenario_usato != "SKIP":
        n_prezzi_pool_debug = len(_estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo))
        if fonte_visuale_riuscita:
            nota_visuale = "✅ riuscita"
        elif tentare_ricerca_visuale:
            nota_visuale = "❌ fallita per questo item"
        else:
            nota_visuale = "— non tentata"
        output_finale += (
            f"\n\n🔬 *DEBUG* — {n_prezzi_pool_debug} prezzi reali ricevuti, "
            f"visuale: {nota_visuale}\n"
            f"{_riepilogo_comp_per_fonte(pool_ricerca_grezzo)}"
        )

    # ---- FOOTER COSTO IA: recap per-modello, per-messaggio ----
    if scenario_usato == "SKIP":
        footer_costo = (
            f"\n\n💵 _Costo IA: 👁 {GEMINI_MODEL_OCCHIO} ${costo_occhi:.4f} "
            f"· Cervello non consultato · Totale ${costo_occhi:.4f}_"
        )
    else:
        modello_cervello = OPENAI_MODEL_CERVELLO if CERVELLO_PROVIDER == "openai" else GEMINI_MODEL_CERVELLO
        footer_costo = (
            f"\n\n💵 _Costo IA: 👁 {GEMINI_MODEL_OCCHIO} ${costo_occhi:.4f} "
            f"+ 🧠 {modello_cervello} ${costo_cervello:.4f} "
            f"= Totale ${costo_totale:.4f}_"
        )
    output_finale = output_finale + footer_costo

    await _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, urgenza,
    )


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
        # Prima: asyncio.to_thread(process_listing, ...), necessario perche'
        # la pipeline era interamente sincrona e avrebbe bloccato il loop.
        # Ora process_listing e' una coroutine e si attende direttamente:
        # Telethon esegue ogni handler come task separato, quindi piu'
        # annunci vengono elaborati davvero in parallelo, e le lunghe attese
        # di rete (scraping, Serper, Gemini) non occupano piu' un thread
        # ciascuna.
        await process_listing(parsed, url, cover)
    except Exception:
        log.error("Errore generico:\n%s", traceback.format_exc())


async def main():
    log.info("Vinted Oracle avviato su Telethon. Versione: %s", BOT_VERSION)
    log.info(
        "Cervello: %s (output JSON strutturato) · comp da memoria del modello: %s",
        OPENAI_MODEL_CERVELLO if CERVELLO_PROVIDER == "openai" else GEMINI_MODEL_CERVELLO,
        "ammessi" if COMP_DA_MEMORIA_AMMESSI else "esclusi dal calcolo",
    )
    log.info(
        "Occhio: %s · output %s · scarto pre-cervello %s",
        GEMINI_MODEL_OCCHIO,
        "JSON strutturato" if OCCHIO_OUTPUT_JSON else "prosa",
        "calcolato da campi tipizzati" if OCCHIO_OUTPUT_JSON else "da match testuale",
    )
    await inizializza_client_http()
    try:
        await client.start()
        await client.run_until_disconnected()
    finally:
        await chiudi_client_http()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
