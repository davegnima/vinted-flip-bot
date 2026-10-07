"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os


# ---- fine import ----
TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELEGRAM_SESSION_STRING = os.environ["TELEGRAM_SESSION_STRING"]
TELEGRAM_GROUP_ID = int(os.environ["TELEGRAM_GROUP_ID"])

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_CHAT_ID = os.environ["TELEGRAM_OWNER_CHAT_ID"]
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET: opzionali, servono SOLO per la
# verifica dei codici prodotto su Reddit (vedi sezione VERIFICA CODICI
# PRODOTTO piu' sotto). App Reddit di tipo "script", autenticazione OAuth
# "application only" (grant_type=client_credentials): sola lettura, non
# richiede MAI la password dell'account Reddit. Se non configurate, la
# verifica si disattiva da sola senza rompere nulla (REDDIT_ABILITATO=False).
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "").strip()
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME", "vinted-flip-oracle").strip()

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
# Su Railway e' lo SHA breve del commit in esecuzione (RAILWAY_GIT_COMMIT_SHA); altrove la stringa fissa.
BOT_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or "2026-10-01-fair-value-sottolinee"

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
QUOTA_INCASSO_NETTO = 0.80             # NON PIU' USATA nel calcolo di calcola_verdetto
                                        # (tolta il 2026-09-20 su richiesta esplicita
                                        # dell'utente: raddoppiava lo sconto gia'
                                        # applicato al target). Lasciata qui solo come
                                        # riferimento storico, nessun codice la legge piu'.
SCONTO_TIPICO_TRATTATIVA_VENDITA = 0.10  # sconto medio che un acquirente strappa in


SOGLIA_MARGINE_COMPRA = 25.0           # EUR netti minimi per un COMPRA (alzata da 20 a 25
                                        # il 2026-09-20 su richiesta esplicita dell'utente).
                                        # Usata sia per la decisione compra/tratta/non-compra
                                        # (insieme a SOGLIA_ROI_COMPRA qui sotto) sia, DA SOLA
                                        # senza il floor ROI, per il "minimo accettabile"
                                        # mostrato in chat.
SOGLIA_ROI_COMPRA = 100.0              # % minima di ROI per la via "standard" della decisione
                                        # COMPRA/TRATTA (margine>=SOGLIA_MARGINE_COMPRA E
                                        # roi>=SOGLIA_ROI_COMPRA). Il 2026-09-22 l'utente aveva
                                        # chiesto di toglierla del tutto ("non guardare le
                                        # percentuali, calcola i soldi in tasca"), ma ha
                                        # corretto subito dopo: il ROI resta rilevante, solo un
                                        # margine molto alto lo puo' compensare -- vedi
                                        # SOGLIA_MARGINE_COMPRA_ALTA / SOGLIA_ROI_COMPRA_RIDOTTA
                                        # qui sotto per la seconda via alternativa.
SOGLIA_MARGINE_COMPRA_ALTA = 75.0      # seconda via alternativa (richiesta dall'utente il
                                        # 2026-09-22): un margine molto alto compensa un ROI%
                                        # piu' basso. Sotto questa soglia di margine resta
                                        # valido solo il floor ROI>=SOGLIA_ROI_COMPRA originale.
                                        # Esempio confermato dall'utente: margine €100/roi 70%
                                        # -> COMPRA (fallisce la via standard, roi<100%, ma
                                        # supera questa via: margine>=€75 e roi>=50%).
SOGLIA_ROI_COMPRA_RIDOTTA = 50.0       # ROI minimo richiesto SOLO quando il margine supera
                                        # SOGLIA_MARGINE_COMPRA_ALTA (vedi sopra).
SOGLIA_MARGINE_URGENZA = 30.0          # EUR netti minimi per "Alta urgenza"
SOGLIA_ROI_URGENZA = 150.0             # % minima di ROI per "Alta urgenza"
SCONTO_MAX_TRATTATIVA = 0.40           # sconto massimo trattabile sul PRODOTTO

# --- Tre regole di calibrazione richieste dall'utente il 2026-09-22 dopo
# revisione dello storico verdetti (228 casi, vedi analisi in chat) --
# vedi i tre punti d'uso in calcola_verdetto per il ragionamento completo.
SOGLIA_GIORNI_VENDITA_LAMPO = 2        # "si vende in 48 ore": eccezione al floor di margine
                                        # assoluto SOGLIA_MARGINE_COMPRA qui sopra -- un capo
                                        # che gira in 2 giorni vale l'acquisto anche con
                                        # margine sotto soglia, il capitale torna quasi subito.
SOGLIA_PREZZO_FURTO_ISTANTANEO = 15.0  # sotto questo prezzo pagato, niente fase di
                                        # trattativa su un ROI enorme (vedi
                                        # SOGLIA_ROI_FURTO_ISTANTANEO) -- rischiare di perdere
                                        # un affare del genere per pochi euro di sconto in piu'
                                        # non vale il tempo della trattativa.
SOGLIA_ROI_FURTO_ISTANTANEO = 300.0    # ROI (sul prezzo pieno) minimo per l'eccezione sopra.

SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE = 50.0  # taglia estrema/non liquida (vedi uso in
SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE = 150.0     # calcola_verdetto): AFFINATA il 2026-09-24 su


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

# SOGLIA_MARGINE_ALERT_CHIEDI_FOTO (richiesto dall'utente il 2026-09-21, caso
# reale: pull Ann Demeulemeester margine=67.55 EUR ROI=799%, "CHIEDI ALTRE
# FOTO" per mancanza del wash tag -- non arrivato nel canale alert perche'
# quel canale era ristretto a decisione=="COMPRA" il 2026-09-20, secondo giro,
# proprio per tagliare il rumore di TRATTA/CHIEDI ALTRE FOTO a bassa qualita').
# Un CHIEDI ALTRE FOTO arriva SEMPRE con margine/ROI gia' sopra la soglia
# minima di COMPRA (vedi calcola_verdetto: e' lo stesso ramo "supera_soglia",
# solo con legit_verdetto incerto) -- quindi puo' comunque valere la pena di
# vederlo nel canale alert, ma non TUTTI i CHIEDI ALTRE FOTO, solo quelli col
# margine abbastanza alto da giustificare l'attenzione extra di chiedere le
# foto e aspettare la risposta del venditore. Soglia separata da
# SOGLIA_MARGINE_COMPRA (25 EUR) apposta: qui il bar e' piu' alto, perche' a
# differenza di un COMPRA qui il deal non e' ancora chiuso. Metti a 0 (o un
# numero molto alto) per tornare al comportamento "mai" di prima.
# Soglia abbassata da 50 a 30 EUR il 2026-09-21, stessa richiesta: il
# confronto e' stretto (">"), non ">=", quindi un margine di esattamente
# 30.00 EUR resta escluso.
SOGLIA_MARGINE_ALERT_CHIEDI_FOTO = 30.0

# Brand esclusi dall'alert su CHIEDI ALTRE FOTO (richiesto dall'utente il
# 2026-09-21, stesso messaggio della soglia sopra): sono brand a rischio fake
# storicamente alto o con mercato dell'usato particolarmente insidioso per un
# capo la cui autenticita' e' ancora "sospetta, servono altre foto" -- vale
# la pena aspettare la conferma delle foto aggiuntive PRIMA di essere
# avvisati col push, non dopo. Match su substring del brand dichiarato
# nell'annuncio (case-insensitive), stessa logica gia' usata altrove nel
# file per i controlli sul brand.
BRAND_ESCLUSI_ALERT_CHIEDI_FOTO = ("miu miu", "loewe", "arc'teryx", "arcteryx", "prada")
# Dal 7/10 (dati reali delle 24 h precedenti, solo CHIEDI ALTRE FOTO con vendita tracciata): i brand esclusi qui sopra con
# margine >= 50 EUR (Prada 78 e 76, Miu Miu 79 e 65) sono venduti in fretta 3 volte su 4 (campione piccolo: 4 annunci).
# Per questi brand l'alert parte solo se il margine raggiunge l'obiettivo dell'utente (50 EUR); sotto resta escluso.
SOGLIA_MARGINE_ALERT_CHIEDI_FOTO_BRAND_ESCLUSI = 50.0

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

_serper_fallimenti_consecutivi = [0]
_serper_timestamp_ultimo_fallimento = [0.0]
SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO = 3
RAFFREDDAMENTO_SERPER_SECONDI = 3600 * 6
_serper_notifica_esaurimento_inviata = [False]


def _env_float(nome, default):
    try:
        return float(os.environ.get(nome, str(default)).replace(",", "."))
    except ValueError:
        return float(default)


MAX_ANALISI_PARALLELE = max(1, int(os.environ.get("MAX_ANALISI_PARALLELE", "4")))

# Due vie in piu' per il COMPRA (richieste dall'utente il 2026-10-07 dopo l'analisi 4-7/10: 1031 annunci con vendita
# tracciata). Venduti entro 15 min per rapporto target/prezzo: <1,5 9%, 2-3 24%, 3-5 53%, >5 65%; i TRATTA a <=20 EUR
# con margine >=20 EUR vendevano veloci il 60% (15 casi), come i COMPRA (54%). Vedi l'uso in calcola_verdetto.
SOGLIA_PREZZO_BASSO_COMPRA = _env_float("SOGLIA_PREZZO_BASSO_COMPRA", 20)      # prezzo pagato massimo...
SOGLIA_MARGINE_PREZZO_BASSO = _env_float("SOGLIA_MARGINE_PREZZO_BASSO", 20)    # ...e margine minimo
SOGLIA_RAPPORTO_TARGET_COMPRA = _env_float("SOGLIA_RAPPORTO_TARGET_COMPRA", 3)  # target >= N volte il prezzo...
SOGLIA_MARGINE_RAPPORTO = _env_float("SOGLIA_MARGINE_RAPPORTO", 15)            # ...e margine minimo
# Legit "sospetto, servono altre foto" con margine molto alto: COMPRA invece di CHIEDI ALTRE FOTO (i CHIEDI ALTRE
# FOTO con margine >=80 EUR vendevano veloci il 53%, 19 casi: si perdevano prima della risposta del venditore).
# "non_verificabile" resta sempre CHIEDI ALTRE FOTO. 0 = regola spenta.
SOGLIA_MARGINE_COMPRA_SOSPETTO = _env_float("SOGLIA_MARGINE_COMPRA_SOSPETTO", 80)


# Resellbot (venduti eBay/Poshmark): DISATTIVATO il 2026-10-03 su richiesta dell'utente -- rispondeva 429/bloccato su
# praticamente ogni ricerca e il bot ripiegava comunque su Google. Con RESELLBOT_ATTIVO=1 torna la fonte primaria.
# Fascia di prezzo per scegliere il modello Gemini PRIMA dell'Occhio (richiesto dall'utente il 2026-10-03): dal prezzo
# richiesto in su l'annuncio usa le cascate "_ALTO" (modelli migliori, quota gratuita di poche richieste al giorno);
# sotto, quelle base (modelli leggeri). Si decide subito dal prezzo del tracker: nessun secondo perso in coda.
GEMINI_SOGLIA_PREZZO_ALTO = _env_float("GEMINI_SOGLIA_PREZZO_ALTO", 50)
RESELLBOT_ATTIVO = os.environ.get("RESELLBOT_ATTIVO", "0").strip().lower() in ("1", "true", "si", "yes")
