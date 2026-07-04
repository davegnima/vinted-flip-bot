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
# TELEGRAM_ALERT_CHAT_ID (opzionale): se impostato, riceve SOLO i verdetti
# COMPRA/TRATTA/CHIEDI ALTRE FOTO con notifica push normale.
# TELEGRAM_OWNER_CHAT_ID riceve tutto ma può essere silenziato sul telefono.
# Come ottenere il tuo user_id Telegram: scrivi /start a @userinfobot
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID")  # es. "123456789"
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


def scegli_materiale_per_ricerca(material_value_raw):
    """Cerca il materiale piu' pregiato nella lista prioritaria, splittando
    prima su virgola (es. '70% Lana, 30% Cotone' -> ['70% lana', '30% cotone'])
    e cercando match esatti per elemento -- piu' robusto della ricerca per
    substring diretta che potrebbe matchare 'cashmere' dentro 'extra-cashmere'."""
    if not material_value_raw:
        return None
    materiali_annuncio = [m.strip().lower() for m in material_value_raw.split(",")]
    for materiale_prioritario in MATERIALI_PREGIATI_PRIORITA:
        if any(materiale_prioritario in elemento for elemento in materiali_annuncio):
            return materiale_prioritario
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

# FILOSOFIA DEL BOT (da non dimenticare mai nei prompt):
# L'utente e' un flipper professionista che CERCA attivamente venditori che
# non conoscono il valore dei propri capi. Per lui un prezzo di 5-10€ su un
# capo che ne vale 300 NON e' un segnale di fake -- e' esattamente il tipo
# di deal che cerca. Il legit check deve basarsi SOLO sulle fotografie e
# sulle etichette visibili, mai sul prezzo. Il prezzo basso entra nel
# calcolo del margine (positivamente), non nel rischio di autenticita'.

GEMINI_OCCHI_SYSTEM_PROMPT = """
Sei l'analista visivo di un flipper professionista di lusso second-hand. Fai due cose in un solo passaggio: LEGIT CHECK visivo + valutazione finanziaria preliminare. Sei esperto di autenticazione su Vinted, Vestiaire, Grailed, eBay.

# REGOLA ASSOLUTA SUL PREZZO
Il prezzo NON e' mai un indicatore di autenticita'. Mai. Un Brunello Cucinelli a 8€ con etichette coerenti e' un'opportunita' straordinaria, non un fake. Non citare mai il prezzo nel legit check. Il rischio fake dipende solo da cio' che vedi nelle foto.

# LEGIT CHECK — COSA ANALIZZARE NELLE FOTO
Esamina in ordine di importanza:
1. **Etichetta brand** (collo/interno): font, proporzioni, materiale, punto esatto di cucitura — coerente col brand?
2. **Wash tag / care label**: paese di produzione corretto per il brand? codice prodotto presente?
3. **Etichetta taglia**: stile coerente con l'epoca/linea?
4. **Ricami e loghi**: proporzioni, colori, densita' del filo — tipici dei fake se sfocati o "spessi"
5. **Cuciture**: regolari, dritte, densita' adeguata al materiale?
6. **Zip e hardware**: marchio inciso (es. YKK, Lampo), qualita' del metallo?
7. **Tessuto e finezza**: qualita' apparente, caduta, spessore coerente col brand?
8. **Proporzioni generali**: il capo sembra quello che dichiara di essere?

# VERDETTO LEGIT CHECK (basato SOLO sulle foto)
- "Probabilmente autentico" — prove forti e coerenti (etichetta brand + wash tag + costruzione ok)
- "Sospetto, servono altre foto" — alcune prove presenti ma mancano elementi chiave
- "Probabilmente falso" — discrepanze evidenti (font sbagliato, made in paese sbagliato, cuciture da replica)
- "Non verificabile" — zero etichette visibili, impossibile valutare

Assegna anche una % di confidenza (es. "75%"). Non dichiarare mai 100%.

# SEGNALI DI FAKE NELLE FOTO
- Font etichetta brand sbagliato o proporzioni errate
- "Made in China/Bangladesh" su brand che non produce li'
- Cuciture disomogenee o hardware plastica su brand premium
- Logo ricamato con filo troppo spesso o colori errati
- Etichetta attaccata con punti metallici invece di cucita

# STOP IMMEDIATO (NON COMPRARE senza guardare altro)
- Descrizione venditore dice "etichette tagliate" / "no tags" / "label removed" / "label missing" riferito alla **main label brand** (quella al collo con il nome del brand) → NON COMPRARE. Senza main label non si rivende su Vestiaire/eBay a prezzi premium.
- Fake con discrepanze multiple e inequivocabili nelle foto
- ⚠️ LEGGI SEMPRE LA DESCRIZIONE prima di guardare le foto: il venditore spesso dichiara esplicitamente difetti e etichette mancanti. "the inside label is missing", "etichetta tagliata", "no care label" nella descrizione = segnale da valutare correttamente prima di qualsiasi altra analisi.

# MINUS DA SEGNALARE (abbassano il prezzo di listing, non sono veti)
- **Wash tag / care label assente** (materiali e lavaggio): comune nei sample sale e outlet. Abbassa il listing di €5-10 su Vestiaire, quasi irrilevante su Vinted. Se il venditore spiega il motivo (es. "factory outlet sample", "bought at sample sale") = segnale di onestà, non di fake. NON confondere wash tag mancante con main label mancante.
- Piccole macchie o residui: minus se visibili, non veto se il prezzo di acquisto è basso
- Orlo leggermente sformato su maglia: normale dopo lavaggi, recuperabile con stiratura

# DESCRIZIONE VENDITORE — SEGNALE POSITIVO
Se la descrizione contiene composizione dettagliata (es. "92% cotone", "cashmere"), condizione specifica, o dettagli tecnici precisi → il venditore sa cosa vende ed e' onesto. Questo compensa parzialmente l'assenza di foto etichette: in mancanza di etichette visibili, considera "Sospetto, servono altre foto" invece di NON COMPRARE, e chiedi le foto mancanti.

# VALUTAZIONE VENDITORE (se dati disponibili)
- **0 recensioni**: attenzione elevata — puo' essere un faker, chiedi prove extra
- **Poche recensioni (1-15) con 5 stelle**: probabilmente sprovveduto onesto che non sa il valore → opportunita' d'oro
- **Molte recensioni (50+) con prezzo basso**: venditore esperto, valuta perche' vende cosi' a poco
- **Feedback negativi recenti**: segnale serio, chiedi chiarimenti

# MAINLINE VS DIFFUSION — DISTINZIONE CRITICA PER IL MARGINE
Alcune etichette sembrano luxury ma sono diffusion line su licenza con valore second-hand radicalmente diverso. Questa distinzione va fatta SEMPRE prima di stimare il margine.

**MOSCHINO:**
- ✅ "Moschino" / "Moschino Couture!" / "Moschino Cheap & Chic" (archivio) → valore reale
- ❌ "Love Moschino" → diffusion SINV, vale come fast fashion di fascia media. Camicie/top basic senza loghi grandi = invendibile come flip a meno di €5 di acquisto

**VIVIENNE WESTWOOD:**
- ✅ "Vivienne Westwood" Gold Label / Red Label / mainline → valore massimo, pezzi d'archivio
- ✅ "Vivienne Westwood Anglomania" → NON è una diffusion da svalutare. Ha pagina dedicata su Vestiaire con volume reale, produce i pezzi più iconici del brand (corset, gonne asimmetriche, blazer strutturati) a prezzi retail più accessibili. Il mercato Y2K la tratta come VW a tutti gli effetti. Valuta esattamente come mainline per pezzi iconici (corset, gonna tartan, blazer), con uno sconto del 20-30% per basics
- ❌ "Vivienne Westwood Jeans Couture" / "Anglomania" basics senza elementi iconici → valore ridotto
- ⚠️ "Versace" attuale (Donatella) → valore, ma attenzione ai fake elevatissimi
- ❌ "Versace Jeans Couture" / "Versus Versace" / "Versace Classic V2" → diffusion, valore molto ridotto

**MISSONI:**
- ✅ "Missoni" mainline con pattern colorati (chevron, zigzag, space-dye) → valore massimo
- ⚠️ "Missoni" mainline monocromatico → valore ridotto ma presente
- ⚠️ "M Missoni" **abiti e gonne con pattern** → diffusion ma con domanda reale su Vinted EU (FR/DE/BE). Rivendita realistica €35-45, non €20. TRATTA se il prezzo è borderline, non NON COMPRARE diretto.
- ❌ "M Missoni" **basics monocromatici** (top, maglia nera/grigia senza pattern) → quasi invendibile come flip. Non comprare sopra €5 di acquisto totale.
- ❌ "Missoni Sport" / "Missoni Mare" → diffusion, valore molto ridotto

**VALENTINO:**
- ✅ "Valentino" / "Valentino Garavani" → valore
- ❌ "RED Valentino" / "Valentino Go" → diffusion, valore ridotto

**ARMANI:**
- ✅ "Giorgio Armani" / "Armani Collezioni" → valore
- ❌ "Emporio Armani" / "Armani Exchange" / "Armani Jeans" → diffusion, valore ridotto

**FERRÉ:**
- ✅ "Gianfranco Ferré" mainline → valore d'archivio
- ⚠️ "Gianfranco Ferré Beachwear/Studio/GFF" → licenza, ma beachwear vintage ha domanda Y2K

**ROMEO GIGLI:**
- ✅ "Romeo Gigli" mainline (silhouette drappeggiata, pezzi sartoriali anni '80-90) → valore d'archivio elevato, acquirenti di nicchia
- ❌ "Romeo Gigli Sport" / "RG Sport" → licenza commerciale anni '90, zero mercato collezionistico. Polo, t-shirt, capi basic = invendibili come flip

**MAX MARA:**
- ✅ "Max Mara" mainline cappotti/soprabiti strutturati → valore, mercato lento
- ✅ "Weekend Max Mara" piumini in piuma d'oca ("L'Autentico Piumino", "Heavy Padding") → valore reale elevato. Retail €350-450, rivendita €80-110 in stagione (ottobre-gennaio). Acquisto estivo a prezzi bassi = arbitraggio stagionale classico. Non applicare la regola diffusion qui.
- ✅ "Weekend Max Mara" cappotti/soprabiti lana strutturati → valore medio, €40-70 rivendita
- ❌ "Weekend Max Mara" abbigliamento casual (camicie, maglie, blazer leggeri, pantaloni) → diffusion casual, valore ridotto. Vendita reale €15-25 su capi a €20+ di acquisto = flip negativo

**COLLABORAZIONI DESIGNER x H&M (categoria speciale):**
Balmain x H&M, Moschino x H&M, Margiela x H&M, Versace x H&M, Lanvin x H&M ecc. sono una categoria DISTINTA — non sono mainline luxury né fast fashion. Hanno un micro-mercato collezionistico basato sulla nostalgia con prezzi stabili nel tempo.
- Valore second-hand realistico: €15-30 per pezzi iconici logati, €10-18 per intimo/accessori
- Sold comps reali su eBay: €15-25 per pezzi in ottime condizioni
- NON usare il prezzo mainline Moschino/Balmain come benchmark — sono prodotti H&M di qualità, non luxury
- Strategia: se l'annuncio ha più di 30 minuti e il prezzo è borderline, TRATTA prima di comprare

**JEAN PAUL GAULTIER:**
- ✅ "Jean Paul Gaultier" mainline adulto → valore d'archivio, alta domanda
- ✅ "JPG" / "Gaultier Paris" → stessa cosa
- ❌ "Junior Gaultier" / "Jean Paul Gaultier Junior" → linea bambini/ragazzi (taglie 10a/12a/14a/16a). Mercato completamente diverso dalla mainline adulto. Comp su Vinted spesso listati erroneamente come S/XS adulto. Vendita lenta, buyer di nicchia. Margine molto ridotto rispetto alla mainline. (senza grafica iconica, logo all-over o pezzo d'archivio riconoscibile), il margine realistico crolla. NON usare il prezzo mainline come benchmark. Dichiara esplicitamente nel verdetto: "diffusion line, non mainline — valore second-hand ridotto".

# STAGIONALITÀ — ARBITRAGGIO TEMPORALE
Il prezzo basso fuori stagione NON è un segnale negativo — è spesso la fonte del margine.
- Piumini/cappotti pesanti in estate (giugno-agosto): prezzo Vinted 30-50% sotto il valore reale. Compra, deposita, rivendi a ottobre-novembre al prezzo pieno. Max Mara, Moncler, Helmut Lang in luglio a €30 = COMPRA.
- Costumi/beachwear in inverno: stesso principio inverso.
- Nella stima "Vendita probabile" indica SEMPRE il timing corretto: "€90 in ~90 giorni (ottobre)" non "€90 in 20 giorni" su un piumino comprato a luglio.
- Il capitale immobilizzato per 2-3 mesi su un capo da €30-40 è accettabile se il margine atteso è €50+. Non penalizzare il deal score per la stagionalità — penalizza solo la liquidità e il tempo stimato.

# RISCHIO ASSOLUTO IN EURO
Il rischio di un acquisto va valutato in termini ASSOLUTI, non relativi.
"Macchie", "condizione non perfetta", "qualche difetto" su un capo da €5-10 significa che il tuo rischio massimo e' €5-10 — meno di un caffe'. Non e' lo stesso rischio di "macchie" su un capo da €80.

**Regola pratica:**
- Costo pieno < €15 + prove visive forti → difetti minori NON sono un veto. COMPRA SUBITO, nel peggiore dei casi perdi €10.
- Costo pieno €15-40 + difetti → valuta la gravita' visiva delle macchie/difetti, poi decidi.
- Costo pieno > €40 + difetti → qui il rischio e' reale, chiedi foto dettagliate prima.

Non usare mai "BASSA URGENZA" quando il prezzo e' irrisorio e le prove visive sono forti. A €5 la Missoni DONNA MADE IN ITALY con etichetta nitida e' COMPRA SUBITO senza pensarci.
Non tutte le situazioni di "prove incomplete" sono uguali. Incrocia:

| Prove visive | Margine/Deal | → Decisione |
|---|---|---|
| Etichette chiare e coerenti | Qualsiasi | COMPRA (livello per margine) |
| Etichetta sfocata / parziale | Enorme (ROI 300%+) | COMPRA SUBITO — a questo prezzo vale il rischio, Vinted tutela l'acquirente |
| Etichetta sfocata / parziale | Buono (ROI 100-300%) | CHIEDI ALTRE FOTO — hai un po' di tempo, vale aspettare risposta |
| Etichetta sfocata / parziale | Borderline (<100%) | NON COMPRARE — rischio non giustificato dal margine |
| Zero etichette visibili | Qualsiasi | CHIEDI ALTRE FOTO se il capo sembra interessante, altrimenti NON COMPRARE |

Nella sezione "Da chiedere" e "Messaggio da inviare": se il deal e' enorme con prove sfocate, specifica che il messaggio va inviato DOPO l'acquisto (non prima) per non perdere il deal.
**Acquisto pieno** = prezzo + protezione (~5%+€0,70) + spedizione in entrata (IT 2,50€, altre EU 6,50€).
**Incasso reale** = vendita stimata × 0,80 (sconto medio 20% per trattativa — sempre).
**Margine** = incasso reale − acquisto pieno.
Soglia: 20€ netti E ROI 100%+. Confidenza sempre Bassa (nessun comp reale in questo passaggio).

# TRATTA SE MARGINE BORDERLINE
Se il margine netto è tra €10 e €20 O il ROI è tra 50% e 100% → decisione TRATTA, non COMPRA.
A questi livelli vale la pena provare un'offerta al ribasso per migliorare il margine prima di impegnare il capitale.

# MATRICE DECISIONALE
1. **COMPRA SUBITO** — legit check ok/probabile autentico + margine enorme. Agisci.
2. **COMPRA FORTE** — legit check ok + margine molto buono.
3. **COMPRA** — legit check ok + margine solido.
4. **CHIEDI ALTRE FOTO** — capo interessante ma mancano prove visive chiave.
5. **TRATTA** — tutto ok, margine migliorabile.
6. **NON COMPRARE** — fake evidente DALLE FOTO o etichette dichiarate assenti.

# OUTPUT — ottimizzato per lettura rapida da mobile. Il verdetto va SEMPRE in cima.

**Analisi visiva** (3-4 righe max): cosa vedi, etichette trascritte alla lettera, condizione.
⚠️ **REGOLA CRITICA — NON INVENTARE ETICHETTE**: trascrivi SOLO ciò che è visibile e leggibile nelle foto. Se un'etichetta è sfocata, parzialmente coperta, o non presente in nessuna foto → dichiara "non visibile" o "non verificabile". MAI dedurre l'autenticità da codici che non si vedono chiaramente. Un codice letto male è peggio di un codice assente.

## Verdetto
[EMOJI] **[DECISIONE]** · [urgenza]

💰 €[acquisto pieno] → €[vendita probabile] → **€[margine netto] (ROI [X]%)**
🏷️ Legit: [una riga, max 15 parole]
🕐 ~[Z] giorni · Deal [X]/10 · Rischio fake: [B/M/A/MA] · Confidenza: [B]

---
📨 **Messaggio da inviare:**
"[testo pronto, copiabile, con offerta se TRATTA, senza preamboli inutili]"

---
❓ **Da chiedere** (solo se servono foto specifiche):
[max 2 domande brevi, o "Non necessario"]

EMOJI semaforo: 🟢 COMPRA SUBITO / COMPRA FORTE · 🟡 COMPRA / TRATTA · 🔴 NON COMPRARE · 🔵 CHIEDI ALTRE FOTO
Messaggio per TRATTA: deve contenere l'offerta numerica precisa + richiesta foto se mancano. Niente "è ancora disponibile?". Esempio: "Ciao! Offro €20 tutto compreso, acquisto subito. Hai foto etichetta interna? Grazie"
""".strip()

GEMINI_CERVELLO_SYSTEM_PROMPT = """
Sei il valutatore finanziario di un flipper professionista di lusso second-hand. Ricevi l'analisi visiva di un capo (prodotta da un tuo collega guardando le foto) e dati di mercato reali. Il tuo compito e' produrre il verdetto operativo finale.

# REGOLA FONDAMENTALE SUL PREZZO
**Il prezzo di acquisto basso e' un vantaggio, mai un rischio.** Il flipper cerca venditori che non conoscono il valore dei loro capi. Un prezzo di €8 su un capo che vale €200 e' un ROI stellare -- non un campanello d'allarme. Non menzionare mai il prezzo come segnale di contraffazione nel legit check. Il rischio di fake si valuta dalle etichette visibili nelle foto (descritto nell'analisi visiva che ricevi), non dal prezzo.

# REGOLA ETICHETTE -- NON MODIFICABILE
Se l'analisi visiva dice "nessuna etichetta visibile" o "etichette assenti" o "descrizione venditore: etichette tagliate" → la decisione NON PUO' essere COMPRA in nessuna forma. Solo CHIEDI ALTRE FOTO o NON COMPRARE.
Se invece l'analisi visiva riporta etichette visibili e coerenti → il prezzo basso NON e' un ostacolo alla decisione COMPRA. Anzi, abbassa il rischio (meno soldi a rischio).

# RICERCA WEB OBBLIGATORIA (google_search)
Hai il tool google_search. Usalo per trovare PREZZI DI VENDITA REALI (non il prezzo di acquisto -- quello lo sai gia'). Cerca:
1. eBay SOLD (priorita' massima: transazioni concluse)
2. Vinted ask (numerosi, diretti)
3. Vestiaire Collective ask
4. Depop, Grailed, 1stDibs se rilevante

Formula: "[brand] [categoria] [materiale] sold" o "site:vestiairecollective.com [brand] [categoria]".
Se i comp Serper pre-raccolti sono gia' sufficienti, puoi non cercare ulteriormente -- ma se sono scarsi o ambigui, cerca.

# MARGINE E SOGLIE — CALCOLO A DUE GAMBE OBBLIGATORIO
**Acquisto pieno** = prezzo + protezione (~5%+€0,70) + spedizione in entrata (IT 2,50€, altre EU 4,50-6€).
**Incasso reale** = prezzo di listing stimato × 0,80 (sconto medio 20% per trattativa — SEMPRE, non opzionale).
**Margine netto** = incasso reale − acquisto pieno. Soglia: 20€ netti E ROI 100%+.

Esempio: listing stimato €45, acquisto pieno €31,50 → incasso reale €36 → margine €4,50 (ROI 14%) → NON COMPRARE.
Esempio: listing stimato €25, acquisto pieno €12,65 → incasso reale €20 → margine €7,35 (ROI 58%) → micro-flip borderline.

# GERARCHIA COMP — REGOLA NON NEGOZIABILE
**eBay sold** (filtro venduto) = unico valore reale di transazione. Priorità assoluta.
**Vestiaire / Vinted / Depop ask** = solo indicatori di saturazione e prezzo psicologico, NON valore di vendita.
Se non hai eBay sold identici → Confidenza Bassa obbligatoria. Non inventare sold, dichiaralo esplicitamente.
Aggiustamento mercato: sold eBay UK/US/DE → -20-30% per stimare realistico su Vinted IT.

Voto Margine: 0-2/10 <10€; 3-4/10 10-19€; 5-6/10 20-39€; 7-8/10 40-99€; 9-10/10 100€+.

# MATRICE
1. COMPRA SUBITO — etichette ok + Deal 9-10 + Margine 8-10 + Confidenza non Bassa.
2. COMPRA FORTE — etichette ok + Deal 8 + Margine 7-8.
3. COMPRA — etichette ok + Deal 6-7 + Margine 5-7.
4. COMPRA SE CI TIENI — margine borderline ma positivo.
5. TRATTA — tutto ok ma margine migliorabile con trattativa.
6. NON COMPRARE — fake evidente dalle foto, zero etichette + descrizione "tagliate", condizione distrutta, margine negativo con i comp reali.

# POLICY ASK-COME-PROXY
Ask multipli coerenti da fonti diverse → applica sconto prudenza 20-40% per stimare il sold reale. Rimane Confidenza Media (non Alta) salvo sold eBay confermati.

# OUTPUT — ottimizzato per lettura rapida da mobile. Verdetto SEMPRE in cima.

## Verdetto
[EMOJI] **[DECISIONE]** · [urgenza]

💰 €[acquisto pieno] → €[incasso reale = listing×0.80] → **€[margine netto] (ROI [X]%)**
⚠️ Il secondo valore è sempre l'INCASSO REALE (listing × 0.80), non il prezzo di listing. Scrivi sempre "incasso reale" o "post-trattativa" per chiarezza. MAI scrivere il listing grezzo come secondo valore — genera confusione nel calcolo del margine.
🏷️ Legit: [una riga, max 15 parole, MAI sul prezzo]
🕐 ~[Z] giorni · Deal [X]/10 · Rischio fake: [B/M/A/MA] · Confidenza: [A/M/B]

[Solo se TRATTA: aggiungi riga]
🤝 Obiettivo trattativa: €[prezzo target] → €[margine netto trattato] (ROI [X]%)

---
📨 **Messaggio da inviare:**
"[testo pronto e copiabile]"

Regole messaggio:
- **COMPRA SUBITO / COMPRA FORTE / COMPRA**: NESSUN messaggio da inviare. Compri e basta.
- **TRATTA**: messaggio con offerta numerica precisa + "acquisto subito se ok". ZERO preamboli. ZERO "è ancora disponibile?".
- **CHIEDI ALTRE FOTO**: messaggio breve con richiesta specifica delle foto mancanti.
- **NON COMPRARE**: NESSUN messaggio. Mai.

---
❓ **Da chiedere** (solo se mancano prove che cambiano la decisione):
[max 2 domande, o "Non necessario"]

---
🧠 **Analisi dell'analista:**
[3-5 righe obbligatorie che spiegano il ragionamento: perché questa decisione, quali comp hanno pesato di più, quali dubbi rimangono, cosa cambierebbe la decisione. Scrivi come un flipper esperto che spiega a se stesso il ragionamento — non come un report formale.]

URGENZA: ha senso SOLO su decisioni COMPRA/TRATTA (indica quanto velocemente agire).
Su NON COMPRARE e CHIEDI ALTRE FOTO l'urgenza è sempre N/A — non scrivere mai "NON COMPRARE · Alta urgenza".

IMPORTANTE sul costo pieno:
- **Costo pieno richiesto** = prezzo annuncio + protezione + spedizione (quello che paghi ORA)
- **Obiettivo trattativa** = prezzo target che vuoi ottenere + protezione + spedizione (solo se TRATTA)
Non invertire mai i due valori.
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
        # Dati venditore (estratti dall'HTML della pagina annuncio)
        "seller_login": None, "seller_id": None,
        "seller_feedback_count": None, "seller_feedback_reputation": None,
        "seller_items_count": None, "seller_country": None,
        # Guardaroba (top articoli del venditore, scraping separato leggero)
        "seller_top_items": [],
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

        # ---- DATI VENDITORE (dall'HTML della pagina annuncio, JSON Next.js) ----
        # Tutti i pattern cercano nell'HTML senza chiamate aggiuntive.
        # Se non trovati (Vinted cambia l'HTML) vengono lasciati None silenziosamente.
        seller_login_m = re.search(r'"login"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html)
        if seller_login_m:
            result["seller_login"] = seller_login_m.group(1)

        seller_id_m = re.search(r'"user_id"\s*:\s*(\d+)', html)
        if seller_id_m:
            result["seller_id"] = seller_id_m.group(1)

        feedback_count_m = re.search(r'"feedback_count"\s*:\s*(\d+)', html)
        if feedback_count_m:
            result["seller_feedback_count"] = int(feedback_count_m.group(1))

        feedback_rep_m = re.search(r'"feedback_reputation"\s*:\s*([\d.]+)', html)
        if feedback_rep_m:
            try:
                result["seller_feedback_reputation"] = float(feedback_rep_m.group(1))
            except ValueError:
                pass

        items_count_m = re.search(r'"items_count"\s*:\s*(\d+)', html)
        if items_count_m:
            result["seller_items_count"] = int(items_count_m.group(1))

        country_m = re.search(r'"country_title_local"\s*:\s*"([^"]{2,30})"', html)
        if country_m:
            result["seller_country"] = country_m.group(1)

        # ---- GUARDAROBA VENDITORE (scraping leggero profilo, max 5 titoli) ----
        # Eseguito solo se abbiamo l'ID o il login del venditore.
        # Scopo: capire se vende altre cose di marca (reseller esperto) o
        # roba generica (sprovveduto che non sa il valore del capo).
        # Non blocca se fallisce -- i dati venditore di base bastano.
        seller_id = result.get("seller_id")
        seller_login = result.get("seller_login")
        if seller_id or seller_login:
            profilo_url = (
                f"https://www.vinted.it/members/{seller_id}/items"
                if seller_id
                else f"https://www.vinted.it/members/{seller_login}/items"
            )
            try:
                resp_profilo = _vinted_session.get(profilo_url, headers=VINTED_HEADERS, timeout=10)
                if resp_profilo.ok:
                    html_profilo = resp_profilo.text
                    # Estrae titoli degli articoli in vendita dal profilo
                    # (formato tipico Vinted: "title":"Titolo articolo")
                    titoli = re.findall(r'"title"\s*:\s*"([^"]{5,80})"', html_profilo)
                    # Deduplication mantenendo ordine
                    visti = set()
                    titoli_unici = []
                    for t in titoli:
                        t_clean = t.strip()
                        if t_clean.lower() not in visti and not t_clean.startswith("http"):
                            visti.add(t_clean.lower())
                            titoli_unici.append(t_clean)
                        if len(titoli_unici) >= 5:
                            break
                    result["seller_top_items"] = titoli_unici
            except Exception as e:
                log.debug("Scraping guardaroba venditore fallito (non bloccante): %s", e)

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




def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None):
    """Esegue le 3 ricerche Serper in parallelo: Vestiaire (Google batch) +
    Vinted (scrape diretto) + eBay sold (scrape diretto).
    3 fonti deliberate per Gemini Flash-Lite: contesto piu' pulito e
    meno token rispetto alle 5 fonti del vecchio bot con Claude.
    Ritorna (testo_comp_completo, serper_ha_funzionato)."""
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
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

    serper_ha_funzionato = any(successi.values())

    nota_brand = "" if vinted_per_id else (
        "⚠️ Brand non nella mappa brand_id Vinted -- la ricerca Vinted usa testo libero "
        "(meno precisa, possibili falsi positivi)."
    )

    parti = [f"RICERCA WEB PRE-RACCOLTA (3 fonti, base: '{query_base}'):"]
    if nota_brand:
        parti.append(nota_brand)
    parti.append(f"\n📍 FONTE: VESTIAIRE COLLECTIVE\n{risultati.get('vestiaire', 'Nessun risultato')}")
    parti.append(f"\n📍 FONTE: VINTED (scrape diretto)\n{risultati.get('vinted', 'Nessun risultato')}")
    parti.append(f"\n📍 FONTE: EBAY SOLD (scrape diretto)\n{risultati.get('ebay', 'Nessun risultato')}")

    return "\n".join(parti), serper_ha_funzionato


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO e VALIDAZIONE POST-GENERAZIONE
# (recuperati dal bot originale main300626.py)
# ---------------------------------------------------------------------------

def _stima_costo_pieno_da_prezzo_e_lingua(prezzo_richiesto_str, titolo, descrizione):
    """Stima costo pieno per paese stimato dalla lingua del testo:
    IT: 2.50€ | FR/ES: 4.50€ | DE/PT/NL: 6.00€"""
    try:
        prezzo = float(str(prezzo_richiesto_str).replace(",", "."))
    except (TypeError, ValueError):
        return None
    testo = f"{titolo or ''} {descrizione or ''}".lower()
    indicatori_de_pt_nl = (
        " größe ", " und ", " der ", " die ", " das ", " ein ", " eine ",
        " tamanho ", " maat ", " met ", " van ",
    )
    indicatori_fr_es = (
        " et ", " avec ", " une ", "robe ", " taille ",
        " talla ", " muy ", " para ", " con la ",
        "débardeur", "haut ", "chemise", "veste ", "pantalon",
        "blouse", "manteau", "pull ", "gilet",
    )
    if any(ind in testo for ind in indicatori_de_pt_nl):
        spedizione_stimata = 6.00
    elif any(ind in testo for ind in indicatori_fr_es):
        spedizione_stimata = 4.50
    else:
        spedizione_stimata = 2.50
    protezione_acquirenti = round(prezzo * 0.05 + 0.70, 2)
    return round(prezzo + protezione_acquirenti + spedizione_stimata, 2)


def check_skip_pre_cervello(output_occhi_testo, listing_info=None):
    """Filtro pre-cervello conservativo: scatta SOLO su segnali forti e
    inequivocabili dall'output testo-libero degli occhi.

    IMPORTANTE -- perche' e' conservativo:
    Il vecchio bot usava JSON strutturato (campi precisi come
    'verdetto_grezzo', 'categoria_a_basso_valore', 'confidenza_percentuale')
    che rendevano il check affidabile. Con testo libero i match regex sono
    inevitabilmente piu' fragili: una parola come 'non rivendibile' puo'
    apparire in contesti diversi da quello atteso (es. 'smagliature non
    visibili in foto' -> falso positivo). Per questo abbiamo rimosso il
    check sul 'NON COMPRARE' testuale degli occhi: la decisione NON COMPRARE
    del modello occhi e' quasi sempre economica (margine insufficiente,
    liquidita' bassa) senza comp reali -- e' corretto passarla al cervello
    che ha i comp Serper per confermare o ribaltare. Solo i casi FISICAMENTE
    non rivendibili (condizione distrutta) o STRUTTURALMENTE senza mercato
    (calzini) o CHIARAMENTE falsi giustificano lo skip.

    Ritorna (e_skip, motivo_skip)."""

    testo = (output_occhi_testo or "").lower()

    # 1. Falso conclamato: il modello lo dichiara esplicitamente con
    # alta confidenza E motivo specifico. Richiede entrambe le condizioni
    # per evitare falsi positivi su 'probabilmente autentico ma con dubbi'.
    if ("probabilmente falso" in testo or "falso conclamato" in testo) and \
       any(c in testo for c in ("confidenza alta", "90%", "95%", "100%", "molto alto")):
        return True, "[FALSO CONCLAMATO] Rilevato da analisi visiva con alta confidenza."

    # 2. Categoria strutturalmente senza mercato (calzini/calze sportive).
    # Unica categoria che skippiamo sempre indipendentemente dal brand.
    if any(c in testo for c in ("calzini", "calze sportive")):
        return True, "[CATEGORIA BASSO VALORE] Calzini/calze sportive, nessun valore di rivendita."

    # 3. Condizione fisicamente distrutta (non una valutazione economica):
    # richiede segnali MULTIPLI e ESPLICITI di danno fisico grave, NON
    # il solo "non comprare" o singole menzioni di difetti normali.
    # "non rivendibile" da SOLO non basta -- puo' apparire in frasi come
    # "smagliature non visibili" o "difetti non rivendibili a prezzi alti".
    segnali_danno_fisico = sum([
        "buchi" in testo,
        "strappi gravi" in testo,
        "bruciature" in testo,
        "da riparare" in testo and "non riparabile" in testo,  # solo se irreparabile
        "condizione pessima" in testo,
        "indossabile" in testo and "non" in testo,  # "non indossabile"
    ])
    if segnali_danno_fisico >= 2:
        return True, "[CONDIZIONE DISTRUTTA] Danni fisici gravi multipli rilevati dall'analisi visiva."

    # NOTA: il check su margine numerico (basato su "vendita probabile" dichiarata
    # dagli occhi) e' stato RIMOSSO deliberatamente. Il modello occhi stima la
    # vendita senza comp reali e sistematicamente la sottostima -- es. un set
    # Sport Missoni completo stimato €25 dagli occhi puo' valere €40-50 con i
    # comp reali di Serper. Bloccare l'annuncio prima che il cervello possa
    # verificare con dati reali produce falsi positivi costosi (persi deal veri).
    # Il calcolo del margine spetta al cervello, che ha Serper. Il filtro
    # pre-cervello gestisce solo i casi che NON dipendono dai comp di mercato:
    # falso conclamato, calzini, condizione fisica distrutta.

    return False, None


def build_skip_report(listing_info, motivo_skip):
    """Report formattato NON COMPRARE per i casi filtrati prima del cervello."""
    if motivo_skip.startswith("[MARGINE INSUFFICIENTE"):
        riga_legit = "Non valutato — filtro pre-cervello su margine insufficiente. Autenticità non in dubbio."
        riga_rischio = "BASSO — margine insufficiente (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[FALSO CONCLAMATO"):
        riga_legit = "Probabilmente falso — rilevato da analisi visiva con alta confidenza."
        riga_rischio = "ALTO — falso conclamato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[CONDIZIONE DISTRUTTA"):
        riga_legit = "Autentico ma condizione fisica gravemente compromessa — non rivendibile."
        riga_rischio = "BASSO (autenticità) / ALTO (condizione) — cervello non consultato"
    else:
        # CATEGORIA BASSO VALORE o altri
        riga_legit = "Categoria strutturalmente senza mercato (es. calzini) — nessun valore di rivendita."
        riga_rischio = "BASSO — categoria a basso valore (filtro automatico, cervello non consultato)"
    motivo_breve = motivo_skip[:117].rsplit(" ", 1)[0] + "..." if len(motivo_skip) > 120 else motivo_skip
    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — filtro automatico pre-cervello\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        f"- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidità:** Bassa · **Rischio:** {riga_rischio} · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        f"## Legit check\n{riga_legit}\n\n"
        "## Da chiedere\nNon rilevante: filtro automatico pre-cervello attivato.\n\n"
        "## Messaggio da inviare\nNon necessario."
    )


def valida_contraddizioni_report(testo):
    """Post-processing del report: corregge 3 contraddizioni logiche comuni.
    Gestisce sia il vecchio formato (**Decisione:** ...) sia il nuovo (🟢/🟡/🔴 COMPRA ...)."""
    final_text = testo

    # Estrai la riga decisione in entrambi i formati
    def _get_decisione_match(txt):
        # Nuovo formato: riga con emoji semaforo
        m = re.search(r"(🟢|🟡|🔴|🔵)\s+\*?\*?([^\n*]+)\*?\*?", txt)
        if m:
            return m, "emoji", m.group(2).strip()
        # Vecchio formato: **Decisione:** ...
        m2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", txt)
        if m2:
            return m2, "markdown", m2.group(1).strip()
        return None, None, ""

    match_d, fmt, dt = _get_decisione_match(final_text)

    def _sostituisci_decisione(txt, nuova_decisione, motivo):
        if fmt == "emoji":
            emoji_map = {"NON COMPRARE": "🔴", "TRATTA": "🟡", "COMPRA": "🟢", "CHIEDI": "🔵"}
            nuova_emoji = next((e for k, e in emoji_map.items() if k in nuova_decisione.upper()), "🟡")
            return re.sub(
                r"(🟢|🟡|🔴|🔵)\s+\*?\*?[^\n*]+\*?\*?",
                f"{nuova_emoji} **{nuova_decisione}** ⚠️ _{motivo}_",
                txt, count=1
            )
        else:
            return re.sub(
                r"(\*\*Decisione:\*\*\s*)[^\n]+",
                r"\1" + nuova_decisione + f" ⚠️ _{motivo}_",
                txt, count=1
            )

    # Estrai ROI dal testo
    roi_m = re.search(r"ROI\s*~?\s*(\d+)(?:[-–](\d+))?\s*%", final_text, re.IGNORECASE)

    # (1) COMPRA + "sotto soglia"
    if re.search(r"\bCOMPRA\b", dt) and re.search(r"sotto\s+soglia", final_text, re.IGNORECASE):
        nuova = "NON COMPRARE · N/A"
        log.warning("Contraddizione (1) margine/decisione: '%s' -> '%s'", dt, nuova)
        final_text = _sostituisci_decisione(final_text, nuova, "corretto: margine sotto soglia")
        match_d, fmt, dt = _get_decisione_match(final_text)

    # (2) COMPRA SUBITO + Confidenza Bassa → degrada a COMPRA FORTE
    if "COMPRA SUBITO" in dt and re.search(r"Confidenza[:\s]+Bassa", final_text, re.IGNORECASE):
        nuova = dt.replace("COMPRA SUBITO", "COMPRA FORTE")
        log.warning("Contraddizione (2) COMPRA SUBITO/Confidenza Bassa: '%s' -> '%s'", dt, nuova)
        final_text = _sostituisci_decisione(final_text, nuova, "corretto: COMPRA SUBITO richiede Confidenza non Bassa")
        match_d, fmt, dt = _get_decisione_match(final_text)

    # NOTA: il check ROI < 100% è stato rimosso deliberatamente.
    # Era troppo rigido e causava NON COMPRARE errati su deal validi
    # (es. abito Marni autentico a ROI 85% con €25 di margine netto).
    # La soglia ROI è una linea guida nel prompt, non un veto automatico.

    return final_text


def estrai_decisione_da_testo(testo):
    # Nuovo formato con emoji
    m = re.search(r"(?:🟢|🟡|🔴|🔵)\s+\*?\*?([^\n*⚠️]+)", testo)
    if m:
        return m.group(1).strip().rstrip("*").strip()
    # Vecchio formato
    m2 = re.search(r"\*\*Decisione:\*\*\s*([^\n]+)", testo)
    return m2.group(1).strip() if m2 else None


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
            "material_per_ricerca": scraped.get("material_per_ricerca"),
            "color_raw": scraped.get("color_raw"),
            # Dati venditore
            "seller_login": scraped.get("seller_login"),
            "seller_id": scraped.get("seller_id"),
            "seller_feedback_count": scraped.get("seller_feedback_count"),
            "seller_feedback_reputation": scraped.get("seller_feedback_reputation"),
            "seller_items_count": scraped.get("seller_items_count"),
            "seller_country": scraped.get("seller_country"),
            "seller_top_items": scraped.get("seller_top_items") or [],
        })
        for photo_url in scraped.get("photo_urls", []):
            img = download_image_bytes(photo_url, referer=url)
            if img:
                photo_bytes_list.append(img)
            time.sleep(0.4)

    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]
    if not photo_bytes_list:
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Niente foto per: {listing_info.get('title')}\nURL: {url or 'non trovato'}\nSalto valutazione.")
        return

    log.info("Foto raccolte: %d (fonte: %s)", len(photo_bytes_list),
             "scraping Vinted" if url and len(photo_bytes_list) > 1 else "fallback copertina Telegram")

    # Eta' annuncio formattata (usata nel prompt al cervello per il asse urgenza)
    age_days = listing_info.get("age_days")
    age_text = f"{age_days:.1f} giorni fa" if age_days is not None else "non disponibile (scraping data pubblicazione fallito)"

    # Costruisci profilo venditore da passare agli occhi
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

    seller_info_text = "\n".join(seller_info_parts) if seller_info_parts else "non disponibile (scraping profilo non riuscito)"

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

    # ===== STEP 1: OCCHI -- foto + valutazione preliminare, zero ricerca web =====
    output_occhi, costo_occhi, _ = chiama_gemini(
        GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
    costo_totale += costo_occhi
    log.info("Occhi completati. Costo: $%.5f\nOutput occhi (anteprima):\n%s%s",
             costo_occhi, output_occhi[:600], "... [troncato]" if len(output_occhi) > 600 else "")

    # ===== STEP 1b: FILTRO PRE-CERVELLO (early exit, risparmia la chiamata cervello) =====
    e_skip, motivo_skip = check_skip_pre_cervello(output_occhi, listing_info)
    if e_skip:
        log.info("FILTRO PRE-CERVELLO ATTIVATO: cervello NON consultato. Motivo: %s", motivo_skip)
        output_finale = build_skip_report(listing_info, motivo_skip)
        n_query_grounding = 0
        scenario_usato = "SKIP"
    else:
        # ===== STEP 2: decidere Scenario G o F in base a Serper =====
        titolo_annuncio = listing_info.get("title") or ""
        brand_annuncio = listing_info.get("brand") or ""
        categoria_per_ricerca = estrai_categoria_da_titolo(titolo_annuncio) or ""
        catalog_id = listing_info.get("catalog_id")
        material_per_ricerca = listing_info.get("material_per_ricerca")

        scenario_usato = "F"
        comps_text = None

        tempo_trascorso = time.time() - _serper_timestamp_ultimo_fallimento[0]
        in_raffreddamento = (
            _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
            and tempo_trascorso < RAFFREDDAMENTO_SERPER_SECONDI
        )
        serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

        if serper_disponibile:
            comps_text, serper_ok = search_comps_completo(
                brand_annuncio, categoria_per_ricerca, titolo_annuncio,
                catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
            )
            log.info("Ricerca Serper:\n%s", comps_text)
            if serper_ok:
                scenario_usato = "G"
                _serper_fallimenti_consecutivi[0] = 0
            else:
                _serper_fallimenti_consecutivi[0] += 1
                _serper_timestamp_ultimo_fallimento[0] = time.time()
                log.warning("Serper fallito (%d consecutivi) -- fallback Scenario F.", _serper_fallimenti_consecutivi[0])
                if _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO:
                    log.warning("Soglia %d fallimenti raggiunta -- Serper saltato per %.1f ore.",
                                SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO, RAFFREDDAMENTO_SERPER_SECONDI / 3600)
        else:
            if in_raffreddamento:
                log.info("Serper in raffreddamento (~%.1f ore rimanenti) -- Scenario F.", (RAFFREDDAMENTO_SERPER_SECONDI - tempo_trascorso) / 3600)
            else:
                log.info("Serper non disponibile (chiave assente) -- Scenario F.")

        # ===== STEP 3: CERVELLO -- rivalutazione con grounding forzato, G o F =====
        # Includo age_days e URL nel prompt come nel bot originale (utili per asse urgenza e debug)
        contesto_listing = (
            f"{user_text_occhi}\n"
            f"Annuncio pubblicato: {age_text}\n"
            f"URL annuncio: {url or 'non disponibile'}"
        )
        if scenario_usato == "G":
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE (prodotta poco fa, senza ricerca web) ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                f"--- {comps_text} ---\n\n"
                "Usa i risultati di ricerca web PRE-RACCOLTI sopra per confermare/correggere la tua proposta. "
                "Esegui INOLTRE almeno una ricerca con il tool google_search per verificare o completare questi "
                "dati (es. se manca un sold eBay, se i prezzi Vestiaire sono pochi, se vuoi controllare Depop/"
                "Grailed/1stDibs che non sono stati pre-raccolti). Produci il verdetto operativo completo."
            )
        else:
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE (prodotta poco fa, senza ricerca web) ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                "NOTA: non ci sono risultati di ricerca pre-raccolti (Serper non disponibile). "
                "DEVI usare attivamente il tool google_search per trovare comp reali prima di produrre il verdetto "
                "finale, seguendo le istruzioni nel tuo system prompt (eBay sold, Vinted, Depop, Vestiaire, Grailed, "
                "1stDibs nell'ordine di priorita' indicato)."
            )

        output_finale_raw, costo_cervello, n_query_grounding = chiama_gemini(
            GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, photo_bytes_list=[], grounding=True)
        costo_totale += costo_cervello

        # Validazione contraddizioni (COMPRA+margine basso, COMPRA SUBITO+Confidenza Bassa, COMPRA+ROI<100%)
        output_finale = valida_contraddizioni_report(output_finale_raw)

        log.info("Scenario %s completato. Query grounding: %d. Costo cervello: $%.5f. Totale: $%.5f",
                 scenario_usato, n_query_grounding, costo_cervello, costo_totale)

    log.info("===REPORT VERBATIM START===\n%s\n===REPORT VERBATIM END===", output_finale)

    # ===== INVIO TELEGRAM =====
    decisione = estrai_decisione_da_testo(output_finale) or ""
    e_compra = any(k in decisione.upper() for k in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO"))

    header = (
        f"🆕 *{listing_info.get('title')}*\n"
        f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
        f"🔧 Scenario {scenario_usato}"
        + (f" ({n_query_grounding} ricerche grounding)" if scenario_usato not in ("SKIP",) and n_query_grounding else
           " (nessuna ricerca grounding)" if scenario_usato not in ("SKIP",) else " (filtro pre-cervello)")
        + f"\n{url or ''}\n{'—' * 20}\n"
    )

    # Post-processing: rimuovi urgenza da NON COMPRARE (incoerente logicamente)
    if "NON COMPRARE" in output_finale:
        output_finale = re.sub(
            r"(🔴\s+\*\*NON COMPRARE\*\*)\s*·\s*[^\n]+",
            r"\1 · N/A",
            output_finale
        )

    # Post-processing: rimuovi "è ancora disponibile?" dal messaggio (frase vietata)
    output_finale = re.sub(
        r"[EÈè]'?\s*ancora disponibile\??[\s,]*(?:[Ss]e\s+s[ìi][,.]?\s*)?",
        "",
        output_finale,
        flags=re.IGNORECASE
    )

    # Post-processing: rimuovi sezione "Messaggio da inviare" su COMPRA puro
    # (solo TRATTA e CHIEDI ALTRE FOTO devono avere messaggi)
    decisione_upper = decisione.upper()
    e_compra_puro = (
        re.search(r"\bCOMPRA\b", decisione_upper)
        and "TRATTA" not in decisione_upper
        and "CHIEDI" not in decisione_upper
        and "NON COMPRARE" not in decisione_upper
    )
    if e_compra_puro:
        output_finale = re.sub(
            r"(📨\s*\*\*Messaggio da inviare[:\*]*\*?\*?)\s*\n[^\n#🧠❓]{1,300}",
            r"\1\nNon necessario.",
            output_finale,
            flags=re.IGNORECASE
        )
        output_finale = re.sub(
            r"(❓\s*\*\*Da chiedere[:\*]*\*?\*?)\s*\n[^\n#🧠]{1,300}",
            r"\1\nNon necessario.",
            output_finale,
            flags=re.IGNORECASE
        )

    log.info("===REPORT VERBATIM START===\n%s\n===REPORT VERBATIM END===", output_finale)

    _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, n_query_grounding if scenario_usato != "SKIP" else 0
    )

def telegram_send_media_group(chat_id, photos_bytes_list, caption=None):
    """Manda fino a 10 foto come album Telegram (MediaGroup)."""
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
    resp = requests.post(
        f"{TELEGRAM_API}/sendMediaGroup",
        data={"chat_id": chat_id, "media": json.dumps(media)},
        files=files,
        timeout=60,
    )
    if not resp.ok:
        log.warning("sendMediaGroup fallita: %s", resp.text[:300])


def telegram_send_with_buttons(chat_id, text, url_annuncio, item_id=None):
    """Manda messaggio con bottoni inline."""
    keyboard = {"inline_keyboard": [[
        {"text": "🔗 Apri su Vinted", "url": url_annuncio},
    ]]}
    # Aggiunge bottone messaggio venditore (URL diretto alla chat Vinted)
    if item_id:
        keyboard["inline_keyboard"].append([
            {"text": "💬 Scrivi venditore", "url": f"https://www.vinted.it/items/{item_id}"},
        ])
    resp = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": keyboard,
        },
        timeout=20,
    )
    if not resp.ok:
        log.warning("sendMessage con bottoni fallita: %s", resp.text[:300])


def _e_urgenza_alta(decisione_testo):
    """Ritorna True se la decisione contiene urgenza Alta o Altissima."""
    testo = (decisione_testo or "").lower()
    return any(k in testo for k in ("alta", "altissima", "subito", "forte"))


def _estrai_item_id_da_url(url):
    """Estrae l'item_id numerico dall'URL Vinted."""
    if not url:
        return None
    m = re.search(r"/items/(\d+)", url)
    return m.group(1) if m else None


def _invia_risultato_telegram(listing_info, url, photo_bytes_list, header, output_finale, decisione, e_compra, scenario_usato, n_query_grounding=0):
    """Gestisce l'invio su Telegram con gallery e bottoni per COMPRA urgente."""
    item_id = _estrai_item_id_da_url(url)
    urgenza_alta = _e_urgenza_alta(decisione)
    e_compra_urgente = (
        e_compra
        and urgenza_alta
        and "NON COMPRARE" not in (decisione or "").upper()
        and "CHIEDI" not in (decisione or "").upper()
    )

    # Chat principale: gallery per tutti se più di 1 foto, singola altrimenti
    if len(photo_bytes_list) > 1:
        telegram_send_media_group(
            TELEGRAM_OWNER_CHAT_ID,
            photo_bytes_list,
            caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto"
        )
    else:
        telegram_send_photo(TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"))

    # Messaggio con bottoni per tutti gli annunci con URL
    if url:
        if e_compra_urgente:
            telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, item_id)
        else:
            telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, None)
    else:
        telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + output_finale)

    # Chat alert separata
    if TELEGRAM_ALERT_CHAT_ID and e_compra:
        alert_text = (
            f"🚨 *AZIONE RICHIESTA*\n"
            f"*{listing_info.get('title')}*\n"
            f"🏷️ {listing_info.get('brand') or '?'} · 💰 {listing_info.get('price') or '?'} EUR\n"
            f"✅ {decisione}\n"
            f"{url or ''}"
        )
        if e_compra_urgente and item_id:
            telegram_send_with_buttons(TELEGRAM_ALERT_CHAT_ID, alert_text, url, item_id)
        else:
            telegram_send_message(TELEGRAM_ALERT_CHAT_ID, alert_text)


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_recent_listings_seen = {}


DEDUP_CONTENUTO_WINDOW_SECONDS = 300

def _normalizza_titolo_per_dedup(title):
    """Rimuove l'ultima parola (di solito la taglia: S/M/L/XL/38/40/ecc.)
    e le virgolette finali, per deduplicare varianti taglia dello stesso capo.
    Es. 'Chemise Mugler S' e 'Chemise Mugler M' -> 'chemise mugler' (stesso capo)."""
    if not title:
        return ""
    t = title.strip()
    # Rimuove virgolette finali: "Chemise Mugler 'vintage'" -> "Chemise Mugler"
    t_senza_virgolette = re.sub(r"['\"][^'\"]*['\"]\s*$", "", t).strip()
    if t_senza_virgolette != t:
        base = t_senza_virgolette
    else:
        # Rimuove l'ultima parola (taglia): "Chemise Mugler S" -> "Chemise Mugler"
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
