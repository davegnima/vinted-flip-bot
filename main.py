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
import json
import time
import asyncio
import base64
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

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
SERPER_API_KEY = os.environ["SERPER_API_KEY"]

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("vinted_flip_bot")


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

ERRORE SPECIFICO DA NON RIPETERE (visto in produzione, vietato esplicitamente): non scrivere mai un ragionamento del tipo "margine sotto soglia 20€, MA la regola velocità a costo minimo si applica: acquisto pieno <15€? No. Soglia non triggerata" seguito comunque da COMPRA SUBITO. Se la tua stessa frase conclude che una regola "non è triggerata" o "non si applica", quella regola non ha effetto sulla decisione, punto — non scrivere la conclusione opposta subito dopo. In quel caso specifico (acquisto pieno ≥15€, margine sotto 20€), la regola velocità NON si applica e la decisione corretta è TRATTA o NON COMPRARE, mai COMPRA SUBITO.

# OUTPUT — formato compatto, italiano. TETTO 150 PAROLE TOTALI. Conta prima di rispondere; se superi, tagli aggettivi non contenuto decisionale.

STILE: etichetta+valore secco, niente parentesi esplicative, niente "il problema è che...". N/A senza spiegare il perché sulla stessa riga. Motivo SOLO in "In una riga" (max15 parole) e Legit check (max20 parole), non ripetuto altrove. Numeri/decisioni prima delle spiegazioni.

VINCOLO CRITICO: la risposta finale viene spedita INTERAMENTE e AUTOMATICAMENTE su Telegram senza revisione umana. Qualsiasi testo che scrivi PRIMA di "## Verdetto operativo" finisce spedito comunque, senza eccezioni — questo include non solo "ricerco i prezzi" o note di ragionamento, ma ANCHE un riepilogo dei dati raccolti dalle ricerche (es. "Sintesi dati raccolti prima di scrivere il verdetto:", elenchi di comps trovati, prezzi retail, confidenza). Quel riepilogo è ESATTAMENTE il tipo di testo vietato: non è il formato richiesto, gonfia il messaggio, e se scritto come blocco separato prima del verdetto rischia di finire fuori ordine. Usa le ricerche per RAGIONARE internamente, non per produrre un resoconto scritto a parte: il primo testo che scrivi nella risposta deve essere il carattere "#" di "## Verdetto operativo", senza alcuna riga, titolo in grassetto, o elenco prima di quello — non un riassunto "pulito", zero.

Senza un tool di ricerca proprio (i dati di mercato sono già nel messaggio sopra), non c'è motivo di produrre testo intermedio prima del verdetto: scrivi in UN SOLO blocco, da "## Verdetto operativo" a "## Messaggio da inviare", senza interromperlo e senza nulla prima.

## Verdetto operativo
- **Decisione:** [qualità] · [urgenza], es. "COMPRA SUBITO · AGISCI ORA"
- **Costo pieno richiesto:** €X (SEMPRE prezzo+protezione+spedizione scomposti, es. "€21,70+€1,80+€2,50=€26" — mai il prezzo nudo)
- **Costo pieno trattato:** €X o N/A
- **Vendita probabile:** €X in ~Z giorni (o N/A)
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
    "motivo_verdetto_grezzo": "max 20 parole, il motivo principale del verdetto grezzo"
  }
}

REGOLE IMPORTANTI:
- CAMPO "testo_letterale_etichette" -- OBBLIGATORIO E LETTERALE: per OGNI etichetta, tag, cartellino o scritta leggibile visibile in qualsiasi foto (brand, composizione, lavaggio, taglia, paese di produzione, codici, seriali), trascrivi il testo ESATTO e COMPLETO, parola per parola e percentuale per percentuale, come se Claude dovesse rispondere basandosi solo su questo testo senza mai vedere la foto. NON riassumere, NON parafrasare, NON scrivere giudizi qualitativi qui (quelli vanno in "legit_check_preliminare"): questo campo è una trascrizione, non un'opinione. Esempio SBAGLIATO: "etichetta composizione coerente con prodotto di fascia alta". Esempio CORRETTO: "98% Lana vergine, 2% Poliammide. Lavare a secco. Non candeggiare. Taglia 38-40-42". Se il testo è parzialmente illeggibile, riportalo comunque con i caratteri incerti segnalati, non saltare il campo.
- Il campo "loghi_e_marchi_visibili" è critico: se vedi anche un solo logo/marchio/scritta che non corrisponde al brand dichiarato dal venditore, DEVE apparire come elemento separato con "coerente_con_brand_dichiarato": false — non ometterlo, non minimizzarlo, non assumere che sia comunque lo stesso brand.
- CASO CRITICO -- ASSENZA TOTALE DI PROVE: se in NESSUNA delle foto fornite è visibile un logo, etichetta, tag, marchio o qualsiasi elemento che confermi il brand dichiarato (es. solo un pattern/colore/forma generico, senza alcun elemento testuale o grafico brand-specifico), questo NON è un dettaglio minore da annotare di passaggio: è un campanello d'allarme di primo livello. In questo caso, nel campo "legit_check_preliminare", il "verdetto" deve essere "Sospetto, servono altre foto" o "Non verificabile" (mai "Probabilmente autentico"), la "confidenza_percentuale" non deve superare il 40%, e "cosa_non_torna_o_e_dubbio" deve dichiarare esplicitamente e in modo evidente "ASSENZA TOTALE DI ETICHETTA/LOGO/TAG IN TUTTE LE FOTO FORNITE — nessuna prova visiva di brand oltre al pattern/aspetto generico". Un pattern o uno stile visivamente simile al brand dichiarato NON è una prova di autenticità: stili, colori e pattern geometrici sono tra gli elementi più facili da replicare senza replicare etichette o costruzione interna (es. il motivo check di Burberry o il monogram di Louis Vuitton sono entrambi ampiamente replicati su falsi; da soli, senza hardware/etichettatura coerente, non provano nulla).
- "analisi_visiva_per_foto" deve avere una voce per OGNI foto allegata, anche se il contenuto si ripete: se ricevi 6 foto, devono esserci esattamente 6 oggetti distinti (numero_foto da 1 a 6), MAI accorpati in meno voci anche se due foto mostrano dettagli simili.
- NON stimare alcun prezzo specifico in euro, NON parlare di mercato, margini o strategia di rivendita dettagliata: questo verrà fatto da un altro modello a valle con accesso a ricerca web, che non vedrà le foto e si baserà SOLO su questo JSON. L'UNICA eccezione è il campo "valutazione_flipper_preliminare", descritto sotto, che è un giudizio grezzo e intenzionalmente approssimativo, non una stima di prezzo.
- CAMPO "valutazione_flipper_preliminare" -- serve a filtrare i casi più ovvi PRIMA che arrivino al modello di pricing, per risparmiare una chiamata costosa quando è già chiaro che non vale la pena procedere. Compilalo così:
  - "categoria_a_basso_valore": true SOLO se il capo è un PAIO DI CALZINI (o calze/collant in stile sportivo da pochi euro, non lingerie/intimo firmato) — questa è l'UNICA categoria che marchi true, indipendentemente dal brand. NON marcare true per nessun'altra categoria, nemmeno se sembra economica o di poco valore a colpo d'occhio: intimo, costumi da bagno, biancheria, bigiotteria, accessori generici POSSONO valere molto in base al brand specifico (es. La Perla, Eres, Agent Provocateur su intimo/costumi hanno mercato second-hand reale) — il pricing lo fa il modello a valle con ricerca web, non tu. In caso di dubbio su qualsiasi categoria diversa dai calzini, false.
  - "verdetto_grezzo": la tua stima approssimativa, basata SOLO su quello che vedi (non sai il prezzo richiesto né hai accesso a comps di mercato). "NON COMPRARE" solo se hai un motivo visivo forte (categoria a basso valore, OPPURE il legit check è già "Probabilmente falso" con alta confidenza, OPPURE condizione "Da riparare" con danni che probabilmente azzerano la rivendibilità). "COMPRA" solo se il capo sembra chiaramente di valore (brand riconoscibile, condizione ottima, autenticità non in dubbio) E non hai motivi di dubbio. In TUTTI gli altri casi (la maggioranza), scrivi "VALUTA" — il default deve essere VALUTA, non un'estremità: il tuo giudizio è grezzo apposta, lascia il lavoro fine al modello con ricerca prezzi reali. Non avere paura di scrivere VALUTA spesso, è la risposta corretta quando non hai elementi forti in una direzione.
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


def scrape_vinted_listing(url):
    """Tenta di recuperare tutte le foto della galleria + dati extra
    (taglia, condizione, descrizione) dalla pagina pubblica Vinted.
    """
    result = {
        "photo_urls": [], "size": None, "condition": None, "description": None,
        "created_at": None, "age_days": None,
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
            "maxOutputTokens": 6000,
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
                    p.get("text", "") for p in candidates[0]["content"]["parts"]
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


def _serper_single_query(label, query, num_results=4):
    """Esegue una singola query Serper e ritorna (label, testo_risultati).
    Helper interno usato da search_comps_serper per le query parallele."""
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "gl": "it", "hl": "it", "num": num_results},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("Ricerca Serper fallita per '%s' (query: '%s'): %s", label, query, e)
        return label, f"  Ricerca fallita per errore tecnico ({type(e).__name__}). Nessun dato da questa fonte."

    organic = data.get("organic", [])
    if not organic:
        return label, "  Nessun risultato trovato per questa fonte/query."

    lines = []
    for r in organic[:num_results]:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        link = r.get("link", "")
        lines.append(f"  - {title}\n    {snippet}\n    [{link}]")
    return label, "\n".join(lines)


def build_vinted_search_url(brand, modello_o_categoria, max_price=None):
    """Costruisce un URL di ricerca Vinted filtrato per brand_id quando
    disponibile (preciso, zero rumore da testo libero), con fallback su
    search_text quando il brand non e' nella mappa VINTED_BRAND_IDS.

    Ritorna (url, e_filtrato_per_id) dove e_filtrato_per_id indica se il
    filtro e' stato fatto con l'ID esatto (piu' affidabile) o solo per
    testo libero (puo' includere falsi positivi, es. capi di altri brand
    che menzionano il brand cercato nel titolo)."""
    from urllib.parse import quote

    brand_lower = (brand or "").strip().lower()
    brand_id = VINTED_BRAND_IDS.get(brand_lower)

    query_text = f"{brand} {modello_o_categoria}".strip()

    if brand_id:
        url = (
            f"https://www.vinted.it/catalog?brand_ids[]={brand_id}"
            f"&search_text={quote(modello_o_categoria or '')}"
            "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
        )
        if max_price:
            url += f"&price_to={max_price}"
        return url, True
    else:
        url = (
            f"https://www.vinted.it/catalog?search_text={quote(query_text)}"
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
    from urllib.parse import quote

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

    # Rimuove righe vuote multiple consecutive (residuo della rimozione
    # sopra) per non sprecare token su spazio bianco ripetuto.
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    return content


def _serper_scrape_page(url, max_chars=2500):
    """Scarica e legge il contenuto di una pagina specifica via
    scrape.serper.dev (endpoint diverso da quello di ricerca: qui l'URL
    e' GIA' NOTO, non stiamo cercando, stiamo leggendo). Usato per leggere
    il contenuto reale delle pagine Vinted/eBay costruite con URL precisi
    (filtro brand_id su Vinted, filtro LH_Sold su eBay), che danno
    risultati piu' pertinenti delle query generiche site: passate a
    Google.

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



def search_comps_serper(brand, modello, categoria):
    """Ricerca comps di prezzo via Serper (Google SERP scraping commerciale,
    stabile a differenza di DuckDuckGo non ufficiale -- vedi discussione).
    Sostituisce il tool web_search integrato di Claude: chiamando Claude
    SENZA server tools, l'intera chiamata torna a beneficiare del caching
    pieno sul system prompt (niente piu' scritture extra di cache per
    iterazione del loop agentico, che era la causa del costo elevato
    osservato in produzione).

    Fa 5 query SEPARATE E MIRATE per fonte specifica (eBay sold, Vestiaire,
    Vinted, + 2 generiche Google) invece di una sola query ampia: risultati
    piu' pertinenti per fonte, a fronte di un costo Serper ancora trascura-
    bile (5x una frazione di centesimo resta una frazione di centesimo) e
    di un prompt Claude leggermente piu' lungo (piu' token di input, ma
    senza il problema delle iterazioni multiple di cache che avevamo con
    il tool web_search integrato).

    Le 5 query sono eseguite IN PARALLELO (non in sequenza) per non
    moltiplicare la latenza totale per 5.

    Ritorna una stringa di testo pronta da inserire nel prompt Claude,
    organizzata per fonte, oppure un messaggio che dichiara l'assenza di
    risultati (mai un 'finto successo' silenzioso: se la ricerca fallisce,
    Claude deve saperlo per applicare correttamente confidenza Bassa)."""
    query_base = f"{brand} {modello} {categoria}".strip()
    if not query_base or query_base.lower() in ("nessuno", "non disponibile", ""):
        return "RICERCA WEB: non eseguita, brand/modello non identificabile con sufficiente certezza dal JSON visivo."

    results_by_label = {}

    # VINTED ed EBAY: non usiamo query Serper generiche (site:...), ma
    # costruiamo URL precisi (brand_id quando disponibile per Vinted,
    # filtro LH_Sold per eBay) e ne leggiamo il contenuto reale via
    # scrape.serper.dev. Piu' preciso di una ricerca Google indiretta.
    vinted_url, vinted_e_per_id = build_vinted_search_url(brand, f"{modello} {categoria}".strip())
    ebay_url = search_comps_ebay_sold(brand, modello, categoria)

    # VESTIAIRE e le 2 ricerche Google generiche restano query Serper
    # normali (non esiste un filtro-per-ID altrettanto preciso per loro
    # con i dati che abbiamo, e il sito Vestiaire e' meno aggressivo nel
    # bloccare lo scraping diretto rispetto a Vinted/eBay).
    serper_queries = [
        ("VESTIAIRE COLLECTIVE", f"{query_base} site:vestiairecollective.com"),
        ("GOOGLE GENERICO (prezzo/valore)", f"{query_base} prezzo valore second hand"),
        ("GOOGLE GENERICO (retail originale)", f"{query_base} retail price original"),
    ]

    log.info(
        "QUERY/URL SERPER COSTRUITI per questa valutazione:\n"
        "  VINTED (scrape, filtro_per_id=%s): %s\n"
        "  EBAY SOLD (scrape): %s\n"
        "  VESTIAIRE (query): %s\n"
        "  GOOGLE GENERICO 1 (query): %s\n"
        "  GOOGLE GENERICO 2 (query): %s",
        vinted_e_per_id, vinted_url, ebay_url,
        serper_queries[0][1], serper_queries[1][1], serper_queries[2][1],
    )

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_serper_single_query, label, q): label
            for label, q in serper_queries
        }
        futures[executor.submit(_serper_scrape_page, vinted_url)] = "VINTED (scrape diretto)"
        futures[executor.submit(_serper_scrape_page, ebay_url)] = "EBAY SOLD (scrape diretto)"

        for future in as_completed(futures, timeout=20):
            label = futures[future]
            try:
                result = future.result()
                if isinstance(result, tuple):
                    # _serper_single_query ritorna (label, text)
                    _, text = result
                    results_by_label[label] = text
                else:
                    # _serper_scrape_page ritorna direttamente il testo, o None
                    results_by_label[label] = (
                        result if result else "  Scrape fallito o pagina vuota/bloccata (anti-bot)."
                    )
            except Exception as e:
                log.warning("Query/scrape Serper '%s' non completata: %s", label, e)
                results_by_label[label] = "  Query non completata (timeout o errore)."

    if all(
        any(marker in v for marker in ("Nessun risultato", "fallita", "non completata", "fallito"))
        for v in results_by_label.values()
    ):
        return (
            "RICERCA WEB: eseguita su 5 fonti (eBay sold, Vestiaire, Vinted, Google generico x2) "
            "ma NESSUNA ha prodotto risultati utili. Nessun comp disponibile -- applica "
            "confidenza Bassa e non inventare prezzi a memoria."
        )

    all_labels = [label for label, _ in serper_queries] + ["VINTED (scrape diretto)", "EBAY SOLD (scrape diretto)"]
    lines = [f"RICERCA WEB (5 fonti, base: '{query_base}'):"]
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
        modello_per_ricerca = ident.get("modello_stimato") or ""
        categoria_per_ricerca = ident.get("categoria") or ""
    except (json.JSONDecodeError, ValueError, TypeError):
        brand_per_ricerca = listing_info.get("brand") or ""
        modello_per_ricerca = ""
        categoria_per_ricerca = ""

    comps_text = search_comps_serper(brand_per_ricerca, modello_per_ricerca, categoria_per_ricerca)
    log.info("RICERCA SERPER:\n%s", comps_text)

    user_text = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto dal venditore: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
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

    log.info("PROMPT TESTUALE -> CLAUDE (nessuna immagine, JSON Gemini filtrato + comps Serper):\n%s", user_text)

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

    return final_text


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE PER UN SINGOLO ANNUNCIO
# ---------------------------------------------------------------------------

def check_skip_pre_claude(gemini_analysis_json):
    """Controllo a COSTO ZERO (nessuna chiamata API) sul JSON gia' ottenuto
    da Gemini: se uno di TRE segnali distinti indica chiaramente che non
    vale la pena procedere, skippiamo la chiamata Claude (la voce di
    costo piu' alta della pipeline) e rispondiamo subito con NON COMPRARE.

    I tre segnali, controllati in ordine:
    1. Falso conclamato: legit check "Probabilmente falso" + confidenza
       >=90% + rischio "molto alto".
    2. Categoria a basso valore strutturale (es. calzini, intimo) --
       campo dedicato compilato da Gemini stesso nel prompt.
    3. Verdetto grezzo di Gemini "NON COMPRARE" -- un giudizio preliminare
       intenzionalmente approssimativo che Gemini fa basandosi solo sulla
       foto, senza ricerca prezzi.

    Questo NON sostituisce il giudizio di Claude sui casi dubbi -- e'
    deliberatamente conservativo su ciascun segnale: un falso negativo
    (non skippare un caso ovvio) costa solo la chiamata Claude risparmiata;
    un falso positivo (skippare un deal valido) costerebbe un margine
    perso, molto piu' caro. Per questo i criteri di ciascun segnale sono
    stretti (AND di piu' condizioni, non OR), anche se i tre segnali tra
    loro sono in OR (basta che scatti uno per skippare).

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

    return False, None


def build_skip_report(listing_info, motivo_falso):
    """Costruisce un report NON COMPRARE nello stesso formato compatto
    usato da Claude, senza fare alcuna chiamata API. Usato quando
    check_skip_pre_claude() rileva un caso chiaro."""
    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — rischio autenticità blocca la valutazione\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        "- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidità:** Bassa · "
        "**Rischio:** ALTO — falso conclamato (filtro automatico, Claude non consultato) · "
        "**Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_falso[:120]}\n\n"
        "## Legit check\n"
        f"Probabilmente falso — rilevato da Gemini con confidenza ≥90%, "
        "filtro automatico pre-Claude attivato per risparmio costi.\n\n"
        "## Da chiedere\n"
        "Non rilevante: falso conclamato.\n\n"
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
    e_skip, motivo_skip = check_skip_pre_claude(gemini_analysis_json)
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
    import hashlib
    report_hash = hashlib.md5(final_report.encode()).hexdigest()[:12]
    log.info(
        "VERIFICA REPORT -- lunghezza: %d caratteri, hash: %s, righe: %d",
        len(final_report), report_hash, final_report.count("\n") + 1,
    )
    log.info("===REPORT VERBATIM START (hash %s)===\n%s\n===REPORT VERBATIM END (hash %s)===",
              report_hash, final_report, report_hash)

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
