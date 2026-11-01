"""Radar oltre l'abbigliamento (richiesto dall'utente il 2026-10-07): design/casa, elettronica, giochi, collezionismo.

FASE 0 = SOLO OSSERVAZIONE. Nessun messaggio Telegram, nessuna chiamata AI, nessun verdetto. Per ogni annuncio
che arriva da una ricerca radar:
  1. modulo categoria dal brand / dalle parole del titolo (tabella RADAR_MODULI, dati da tarare);
  2. filtro di livello 1 su titolo + prezzo del messaggio del tracker (gratis: nessuna richiesta in piu');
  3. chi passa (piu' un campione fisso degli scartati, per misurare i falsi negativi) -> visita della pagina
     (descrizione, catalogo, condizione, foto, venditore) e serie di ricontrolli di vendita del tracciamento;
  4. una riga di log `RADAR |` (o `RADAR SCARTO |` senza pagina) e un evento 'radar' nel DB.
Dopo 1-2 settimane questi dati dicono quali brand/modelli vendono in fretta e a che prezzo, quali ricerche
rendono e quanta banda consumano: da li' si costruiscono tabelle, soglie e prompt per categoria (fasi 1-2).

Come arriva un annuncio radar: dal tracker con il marcatore RADAR_MARCATORE in testa al messaggio (template del
tracker) oppure da una chat dedicata RADAR_GROUP_ID (es. una seconda istanza del tracker con i suoi secondi di
lettura e il suo numero di risultati per ricerca). Senza nessuno dei due il radar e' spento e non cambia nulla.
"""
import os
import re
import time
import asyncio
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot import db
from bot.jev import descrizione_jev
from bot import tracciamento as tr
from bot import radar_matrice as rm
from bot.vinted_scrape import scrape_vinted_listing
from bot.logger import log
from bot.config import TELEGRAM_OWNER_CHAT_ID, TELEGRAM_ALERT_CHAT_ID
from bot.telegram_api import telegram_send_message, telegram_send_photo
# ---- fine import ----

RADAR_MARCATORE = os.environ.get("RADAR_MARCATORE", "📡").strip()
# Interruttore generale (10/10: l'utente ferma il test del radar): 0 = messaggi radar ignorati, niente visite ne' matrice.
RADAR_ATTIVO = os.environ.get("RADAR_ATTIVO", "1").strip() not in ("0", "false", "no", "")
RADAR_GROUP_ID = int(os.environ["RADAR_GROUP_ID"]) if os.environ.get("RADAR_GROUP_ID", "").strip() else None
# Gruppo dedicato (7/10: "Radar grezzo", da silenziare): se RADAR_GROUP_ID non c'e', all'avvio lo si cerca per nome tra
# le chat dell'account (risolvi_gruppo_radar). RADAR_CHAT_IDS e' l'insieme delle chat radar ascoltate.
RADAR_GROUP_TITOLO = os.environ.get("RADAR_GROUP_TITOLO", "Radar grezzo").strip()
RADAR_CHAT_IDS = {RADAR_GROUP_ID} if RADAR_GROUP_ID is not None else set()
# Scartati dal livello 1 che si visitano lo stesso (1 su N, scelto dall'item id: deterministico), per misurare
# quanti affari il filtro butta. 0 = nessuno.
RADAR_CAMPIONE_SCARTI_OGNI = int(os.environ.get("RADAR_CAMPIONE_SCARTI_OGNI", "10") or 0)
RADAR_MAX_PARALLELO = int(os.environ.get("RADAR_MAX_PARALLELO", "4") or 4)
# Banda (7/10: ~290 annunci promossi l'ora x 7 letture da ~300 KB = ~20 GB al giorno): sotto questo prezzo un margine
# di 50 EUR e' quasi impossibile, e la serie di ricontrolli del radar e' ridotta (1 min, 15 min, 1 h invece di 6).
RADAR_PREZZO_MIN = float(os.environ.get("RADAR_PREZZO_MIN", "10") or 0)
# Spesa massima per pezzo decisa dall'utente l'8/10 ("spendo massimo 50 EUR per pezzo"): sopra si scarta sempre,
# anche se il buy max del modello sarebbe piu' alto. 0 = nessun tetto.
RADAR_SPESA_MAX = float(os.environ.get("RADAR_SPESA_MAX", "50") or 0)
RADAR_RICONTROLLI_SECONDI = tuple(
    int(x) for x in os.environ.get("RADAR_RICONTROLLI_SECONDI", "60,300,900,3600").split(",") if x.strip())
_radar_sem = asyncio.Semaphore(RADAR_MAX_PARALLELO)
# Pausa notturna (richiesta dall'utente il 7/10): dalle RADAR_PAUSA_DA alle RADAR_PAUSA_A, ora italiana, i messaggi radar
# si ignorano (niente visite ne' ricontrolli: risparmio di banda proxy). Vuoto = nessuna pausa.
RADAR_PAUSA_DA = os.environ.get("RADAR_PAUSA_DA", "23").strip()
RADAR_PAUSA_A = os.environ.get("RADAR_PAUSA_A", "6").strip()
_radar_pausa_saltati = 0
_radar_visti = set()
# Tracciamento del verdetto v2 (31/10): ogni giallo e verde si ricontrolla (1, 5, 15, 60 min), dei rossi 1 ogni N (banda).
RADAR_TRACCIA_ROSSI_1_SU = int(os.environ.get("RADAR_TRACCIA_ROSSI_1_SU", "10") or 0)
# Audit dei falsi negativi (01/11, tappa 4): 1 scartato "non oggetto" (jev_tipo, pezzo_o_accessorio, ...) su N entra nella serie di
# tracciamento solo per misura (mai Telegram). 0 = nessuno. Se sparisce subito, lo scarto era sospetto: `tools/radar_liste/audit_radar.py`.
RADAR_AUDIT_1_SU = int(os.environ.get("RADAR_AUDIT_1_SU", "20") or 0)
_radar_tracciati = set()

# ---------------------------------------------------------------------------
# Moduli categoria. Brand e parole sono confrontati sul titolo in minuscolo, a parola intera.
# spedizione_eur, rischio_falsi, rischio_guasti e prezzo_max_l1 sono valori di partenza (da tarare con la fase 0):
# prezzo_max_l1 = oltre questo prezzo raggiungere ROI 100% e margine 50 EUR e' improbabile per la categoria.
# Brand: lista dell'utente del 7/10 (92 segmenti, fasce S e A; la fascia B e' in RADAR_BRAND_ESCLUSI).
# 9/10: aggiunti i brand dei modelli della matrice per il tetto di 50 EUR (compatte e obiettivi, walkman, Game & Watch,
# Montblanc, Seiko 6139, Torun, Louis Poulsen, Loewe/Bottega Veneta vintage...).
# ---------------------------------------------------------------------------
RADAR_MODULI = {
    "illuminazione_design": {
        "brand": ("artemide", "flos", "fontanaarte", "fontana arte", "oluce", "kartell", "vitra", "cassina",
                  "zanotta", "alessi", "b&b italia", "b & b italia", "magis", "luceplan", "foscarini", "seletti", "louis poulsen"),
        "parole": ("lampada", "lampade", "applique", "plafoniera", "lampadario", "abat-jour", "abat jour",
                   "piantana", "sedia", "sgabello", "poltrona", "tavolino"),
        "spedizione_eur": 15.0, "rischio_falsi": "basso", "rischio_guasti": "medio", "prezzo_max_l1": 300,
    },
    "ceramiche_oggetti": {
        "brand": ("bitossi", "fornasetti", "richard ginori", "ginori", "iittala", "marimekko", "rosenthal", "kay bojesen",
                  "olivetti"),
        "parole": ("ceramica", "vaso", "piatto", "piatti", "posacenere", "centrotavola"),
        "spedizione_eur": 10.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 200,
    },
    "argento_gioielli": {
        "brand": ("georg jensen", "vivianna torun", "giovanni raspini", "raspini", "swarovski", "pandora"),
        "parole": ("argento 925", "sterling", "spilla", "bracciale argento"),
        "spedizione_eur": 6.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 150,
        "solo_matrice": True,
    },
    "bijoux_vintage": {
        "brand": ("christian dior", "dior", "yves saint laurent", "saint laurent", "ysl", "givenchy",
                  "christian lacroix", "lacroix", "trifari", "monet", "coro", "vivienne westwood"),
        "parole": ("bijoux", "bigiotteria", "orecchini clip", "collana vintage", "spilla vintage"),
        "spedizione_eur": 6.0, "rischio_falsi": "alto", "rischio_guasti": "basso", "prezzo_max_l1": 150,
    },
    "occhiali": {
        "brand": ("persol", "oliver peoples", "matsuda", "jacques marie mage", "cazal", "linda farrow",
                  "cutler and gross", "cutler & gross", "porsche design"),
        "parole": ("occhiali", "montatura", "occhiale"),
        "spedizione_eur": 5.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 200,
    },
    "borse_vintage": {
        "brand": ("mulberry", "roberta di camerino", "coach", "furla", "coccinelle", "lancel", "bally", "fendi",
                  "salvatore ferragamo", "ferragamo", "loewe", "bottega veneta", "longchamp"),
        "parole": ("borsa", "borsetta", "pochette", "tracolla"),
        "spedizione_eur": 6.0, "rischio_falsi": "alto", "rischio_guasti": "basso", "prezzo_max_l1": 200,
    },
    "lego": {
        "brand": ("lego",),
        "parole": ("set lego", "minifigure", "minifig", "technic", "star wars", "ideas"),
        "spedizione_eur": 9.0, "rischio_falsi": "basso", "rischio_guasti": "medio", "prezzo_max_l1": 200,
    },
    "collezionismo": {
        "brand": ("hot toys", "sideshow", "bearbrick", "be@rbrick", "kenner", "transformers", "gundam", "bandai",
                  "tamagotchi", "montblanc", "mont blanc", "seiko"),
        "parole": ("action figure", "statua", "modellino", "vintage toy"),
        "spedizione_eur": 9.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 250,
        "solo_matrice": True,
    },
    "console_retro": {
        "brand": ("nintendo", "game boy", "gameboy", "game & watch", "game and watch", "sega"),
        "parole": ("game boy", "gameboy", "gamecube", "n64", "nintendo 64", "ds", "3ds", "snes", "nes",
                   "cartuccia", "console"),
        "spedizione_eur": 7.0, "rischio_falsi": "medio", "rischio_guasti": "alto", "prezzo_max_l1": 150,
    },
    "fotografia": {
        "brand": ("contax", "leica", "hasselblad", "fujifilm", "olympus", "minolta", "yashica", "kyocera", "ricoh",
                  "nikon", "nikkor", "rollei", "canon", "canonet", "konica", "summicron", "elmarit"),
        "parole": ("fotocamera", "macchina fotografica", "obiettivo", "reflex", "analogica", "compatta 35mm"),
        "spedizione_eur": 8.0, "rischio_falsi": "basso", "rischio_guasti": "alto", "prezzo_max_l1": 400,
        "solo_matrice": True,
    },
    "audio": {
        "brand": ("bang & olufsen", "bang olufsen", "b&o", "beoplay", "beosound", "audeze", "focal", "sennheiser",
                  "beyerdynamic", "walkman", "brionvega"),
        "parole": ("cuffie", "speaker", "cassa", "diffusore", "giradischi", "minidisc"),
        "spedizione_eur": 9.0, "rischio_falsi": "medio", "rischio_guasti": "alto", "prezzo_max_l1": 400,
        "solo_matrice": True,
    },
    "golf": {
        "brand": ("scotty cameron", "titleist"),
        "parole": ("putter",),
        "spedizione_eur": 15.0, "rischio_falsi": "alto", "rischio_guasti": "basso", "prezzo_max_l1": 200,
    },
    "sport": {
        "brand": ("garmin", "wahoo", "rapha"),
        "parole": ("ciclocomputer", "smartwatch sport"),
        "spedizione_eur": 7.0, "rischio_falsi": "medio", "rischio_guasti": "alto", "prezzo_max_l1": 200,
    },
    "libri": {
        "brand": ("taschen", "assouline", "steidl", "aperture"),
        "parole": ("libro", "volume", "monografia"),
        "spedizione_eur": 8.0, "rischio_falsi": "basso", "rischio_guasti": "basso", "prezzo_max_l1": 100,
    },
}
# Fascia B della lista dell'utente (7/10): falsi troppo frequenti o margine troppo basso. Scartati al livello 1.
RADAR_BRAND_ESCLUSI = ("tiffany", "cartier", "bulgari", "bvlgari", "castelli", "phaidon", "rizzoli")

# Il venditore dichiara che e' rotto/incompleto o che non e' l'originale: l'utente non ripara e non compra repliche.
_PAROLE_VIETATE_RE = re.compile(
    r"(?<!\w)(rott[oaie]|non funzion\w*|da riparare|guast[oaie]|difettos[oaie]|per pezzi|per ricambi|ricambi"
    r"|incomplet[oaie]|mancante|mancano|senza pezzi|replica|fake|copia|imitazione|ispirat[oaie]|stile|simil\w*"
    r"|tipo|non original\w*|broken|for parts"
    r"|solo (?:la )?scatola|scatola vuota|verpackung|keine konsole|ohne konsole|empty box|box only)(?!\w)",
    re.I,
)


# "nessun pezzo mancante", "non incompleto": la negazione subito prima annulla la parola vietata
_NEGAZIONE_PRIMA_RE = re.compile(r"(?<!\w)(nessun\w*|niente|non)\s+(\w+\s+)?$", re.I)


def parola_vietata(testo):
    """Prima parola vietata non negata nel testo (minuscola), None se non ce ne sono. Pura."""
    testo = testo or ""
    for m in _PAROLE_VIETATE_RE.finditer(testo):
        if not m.group(0).lower().startswith("non") and _NEGAZIONE_PRIMA_RE.search(testo[max(0, m.start() - 25):m.start()]):
            continue
        return m.group(0).lower()
    return None


def _cerca(frase, testo):
    return re.search(r"(?<!\w)" + re.escape(frase) + r"(?!\w)", testo) is not None


async def risolvi_gruppo_radar(client):
    """Cerca tra le chat dell'account il gruppo RADAR_GROUP_TITOLO e lo aggiunge a RADAR_CHAT_IDS; logga l'id (serve
    anche come chat id nella configurazione del tracker radar). Non solleva mai."""
    if not RADAR_GROUP_TITOLO:
        return None
    try:
        async for dialogo in client.iter_dialogs():
            if (dialogo.name or "").strip().lower() == RADAR_GROUP_TITOLO.lower():
                RADAR_CHAT_IDS.add(dialogo.id)
                log.info("RADAR GRUPPO | titolo='%s' | id=%s", dialogo.name, dialogo.id)
                return dialogo.id
        log.info("RADAR GRUPPO | titolo='%s' non trovato tra le chat", RADAR_GROUP_TITOLO)
    except Exception:
        log.warning("Radar: gruppo non risolto:\n%s", traceback.format_exc())
    return None


def togli_marcatore(testo):
    """Il testo del messaggio senza il marcatore radar in testa (il parser cerca il titolo nella prima riga). Pura."""
    t = (testo or "").lstrip()
    return t[len(RADAR_MARCATORE):].lstrip() if RADAR_MARCATORE and t.startswith(RADAR_MARCATORE) else (testo or "")


def e_messaggio_radar(testo, chat_id=None):
    """True se il messaggio arriva da una ricerca radar: chat dedicata o marcatore in testa. Pura."""
    if chat_id is not None and (chat_id == RADAR_GROUP_ID or chat_id in RADAR_CHAT_IDS):
        return True
    return bool(RADAR_MARCATORE) and (testo or "").lstrip().startswith(RADAR_MARCATORE)


def classifica_radar(titolo, brand=None):
    """(modulo, brand_radar, tipo): tipo 'brand' se titolo o brand nominano un brand radar, 'generico' se c'e' solo
    una parola della categoria, (None, None, 'fuori_radar') altrimenti. Il brand vince sulla parola. Pura."""
    t = " ".join(p for p in ((brand or ""), (titolo or "")) if p).lower()
    for modulo, conf in RADAR_MODULI.items():
        for b in sorted(conf["brand"], key=len, reverse=True):
            if _cerca(b, t):
                return modulo, b, "brand"
    for modulo, conf in RADAR_MODULI.items():
        if any(_cerca(p, t) for p in conf["parole"]):
            return modulo, None, "generico"
    return None, None, "fuori_radar"


def filtro_livello1(titolo, prezzo, modulo, brand=None, matrice=None):
    """(passa, motivo) sul solo messaggio del tracker. Se il titolo cita un modello della matrice (`radar_matrice`)
    decide il suo buy_max invece del tetto del modulo. Pura (matrice None = quella caricata all'avvio)."""
    if modulo is None:
        return False, "fuori_radar"
    escluso = next((b for b in RADAR_BRAND_ESCLUSI if _cerca(b, (titolo or "").lower())), None)
    if escluso:
        return False, "brand_escluso:" + escluso
    vietata = parola_vietata(titolo)
    if vietata:
        return False, "parola_vietata:" + vietata.replace(" ", "_")
    if prezzo is None or prezzo <= 0:
        return False, "prezzo_mancante"
    if RADAR_SPESA_MAX and prezzo > RADAR_SPESA_MAX:
        return False, f"sopra_spesa_max:{RADAR_SPESA_MAX:g}"
    esito, riga = rm.valuta_modello(titolo, brand, prezzo, rm.MATRICE if matrice is None else matrice)
    # Sotto il minimo passa solo un modello noto con buy max (8/10, l'utente: "se uno lo vende a 5 EUR per sbaglio"):
    # l'errore di prezzo su un modello che vale e' proprio l'affare; il resto sotto il minimo e' rumore (minifigure, cover).
    if prezzo < RADAR_PREZZO_MIN and esito != "ok":
        return False, f"prezzo_sotto_minimo:{RADAR_PREZZO_MIN:g}"
    if esito == "escluso":
        return False, f"modello_escluso:{_v(riga.get('escluso'))}"
    if esito == "sotto_soglia":
        return False, "modello_sotto_soglia:" + _v(riga.get("id") or riga.get("modello"))
    if esito == "sopra_buy_max":
        return False, f"sopra_buy_max:{riga['buy_max']:g}"
    if esito == "ok":
        return True, "ok"
    # Moduli raggiunti solo da ricerche per modello (10/10: "yashica t4" restituisce 46 compatte qualsiasi, 0 vendute):
    # passa solo cio' che la matrice riconosce.
    if esito == "nessuno" and RADAR_MODULI[modulo].get("solo_matrice"):
        return False, "modello_sconosciuto"
    tetto = RADAR_MODULI[modulo]["prezzo_max_l1"]
    if prezzo > tetto:
        return False, f"prezzo_sopra_tetto:{tetto:g}"
    return True, "ok"


def nel_campione_scarti(item_id):
    """Scartato da visitare lo stesso (1 su RADAR_CAMPIONE_SCARTI_OGNI, dall'item id). Pura."""
    if RADAR_CAMPIONE_SCARTI_OGNI <= 0 or not item_id:
        return False
    try:
        return int(item_id) % RADAR_CAMPIONE_SCARTI_OGNI == 0
    except ValueError:
        return False


def _v(valore):
    return (str(valore).replace("|", "/").replace(" ", "_")[:40]) if valore not in (None, "") else "-"


def radar_in_pausa(adesso=None):
    """True se l'ora italiana cade nella finestra [RADAR_PAUSA_DA, RADAR_PAUSA_A) (anche a cavallo della mezzanotte). Pura."""
    if not RADAR_PAUSA_DA or not RADAR_PAUSA_A:
        return False
    try:
        da, a = int(RADAR_PAUSA_DA), int(RADAR_PAUSA_A)
    except ValueError:
        return False
    ora = (adesso or datetime.now(ZoneInfo("Europe/Rome"))).hour
    return (da <= ora < a) if da < a else (ora >= da or ora < a)


# Verifica a occhio (25/10): ogni annuncio con un modello della matrice va al tuo chat privato col suo semaforo,
# anche sopra il buy max (rosso). Spento con RADAR_MOSTRA_TUTTI=0.
RADAR_MOSTRA_TUTTI = os.environ.get("RADAR_MOSTRA_TUTTI", "1").strip() not in ("0", "false", "")


def semaforo_radar(prezzo, buy_max):
    """Semaforo dal buy max della matrice, stessa tolleranza di radar_matrice. Pura."""
    if prezzo is None or not buy_max or buy_max <= 0:
        return None
    if prezzo <= buy_max:
        return "🟢"
    return "🟡" if prezzo <= buy_max * rm.RADAR_TOLLERANZA_BUY_MAX else "🔴"


# Filtro sul rumore (31/10): al chat degli avvisi arrivano solo i semafori elencati in RADAR_SEMAFORI (default verde,giallo);
# i rossi mai. RADAR_SOLO_VERDI=1 (vecchia variabile) restringe a solo verdi.
RADAR_SEMAFORI = {x.strip() for x in os.environ.get("RADAR_SEMAFORI", "verde,giallo").split(",") if x.strip()}
if os.environ.get("RADAR_SOLO_VERDI", "0").strip() in ("1", "true", "si"):
    RADAR_SEMAFORI = {"verde"}
# Chat dove arrivano gli avvisi del radar (1/11, utente: il gruppo "COMPRA Vinted" dei verdi della moda): RADAR_CHAT_ID, poi
# TELEGRAM_ALERT_CHAT_ID (il gruppo COMPRA), poi l'owner.
RADAR_CHAT_ID = (os.environ.get("RADAR_CHAT_ID") or "").strip() or TELEGRAM_ALERT_CHAT_ID or TELEGRAM_OWNER_CHAT_ID
# Filtro Jev (1/11, utente): si manda solo cio' che Jev dichiara "affare" (niente rotti, ricambi, incompleti) con confidenza minima.
RADAR_JEV_RICHIESTO = os.environ.get("RADAR_JEV_RICHIESTO", "1").strip() not in ("0", "false", "no", "")
try:
    RADAR_JEV_CONF_MIN = float(os.environ.get("RADAR_JEV_CONF_MIN", "0.7"))
except ValueError:
    RADAR_JEV_CONF_MIN = 0.7


SEMAFORO_EMOJI = {"verde": "🟢", "giallo": "🟡", "rosso": "🔴"}


_MOTIVI_LEGGIBILI = {
    "parola_vietata": "parola vietata nel titolo (rotto, replica, solo scatola...)",
    "pezzo_o_accessorio": "accessorio o ricambio, non l'oggetto intero",
    "titolo_generico": "titolo troppo generico",
    "prezzo_segnaposto": "prezzo segnaposto",
    "sopra_riferimento": "prezzo sopra il limite di acquisto della ricerca",
    "comparabili_non_disponibili": "comparabili non disponibili",
    "pochi_comparabili": "pochi comparabili",
    "margine_basso": "margine troppo basso",
    "roi_basso": "ROI troppo basso",
}


def _motivo_leggibile(motivo):
    chiave = (motivo or "").split(":")[0]
    return _MOTIVI_LEGGIBILI.get(chiave, motivo or "motivo non noto")


def pallino_semaforo(v2, predefinito="🔎"):
    """Pallino del semaforo v2 per l'intestazione del messaggio (richiesta dell'utente, 31/10). Pura."""
    return SEMAFORO_EMOJI.get((v2 or {}).get("semaforo"), predefinito)


def _righe_link_comps(v2):
    """Link dei comparabili che reggono la stima (gialli e verdi), per controllarli a occhio. Vuote se non ci sono. Pura."""
    link = (v2 or {}).get("link_comps") or []
    if not link:
        return []
    return ["Comparabili da controllare:"] + [f"• {p:g} € {u}" for _t, p, u in link]


_STATO_SPEDIZIONE = {"VERIFIED": "verificata", "ESTIMATED": "stimata", "UNKNOWN": "sconosciuta, base"}


def _riga_costo_totale(v2):
    """'Costo totale: prezzo + spedizione (stato) + protezione = totale' (01/11). Vuota se il v2 non ha il costo. Pura."""
    tot, sped = v2.get("costo_totale"), v2.get("spedizione_eur")
    if tot is None or sped is None:
        return ""
    stato = _STATO_SPEDIZIONE.get(v2.get("spedizione_stato"), "n.d.")
    paese = f" da {v2['paese']}" if v2.get("paese") else ""
    return f"Costo totale: {tot:.2f} € (spedizione {sped:.2f} € {stato}{paese}, protezione acquisti inclusa)"


def _righe_v2(v2):
    """Righe del messaggio: comparabili (quanti e perche' zero), esito del semaforo (sempre), giudizio Jev.
    Il semaforo non viene dal buy max della matrice: si costruisce dai comparabili (richiesta dell'utente, 25/10)."""
    if v2 is None:
        return ["Comparabili: non calcolati", "Semaforo: non calcolato"]
    n = v2.get("n") or 0
    righe = []
    pallino = pallino_semaforo(v2, "n.d.")
    if v2.get("rivendita") is None:
        righe.append(f"Comparabili: {n} trovati, nessuna stima ({_motivo_leggibile(v2.get('motivo'))})")
        righe.append(f"Semaforo: {pallino} {v2.get('semaforo') or 'n.d.'}, {_motivo_leggibile(v2.get('motivo'))}")
    else:
        righe.append(f"Comparabili: {n} trovati · rivendita {v2.get('rivendita')} € · margine {v2.get('margine')} € "
                     f"· ROI {v2.get('roi')}%")
        righe.append(f"Semaforo: {pallino} {v2.get('semaforo') or 'n.d.'}")
    if v2.get("richiesto_mediano") is not None and v2.get("rivendita") is not None:
        cal = "calibrata" if v2.get("calibrazione") == "calibrato" else "non calibrata sulle vendite reali"
        righe.append(f"Prezzi: richiesto mediano {v2['richiesto_mediano']} € · vendita stimata {v2['rivendita']} € ({cal}) "
                     f"· vendita rapida {v2.get('vendita_rapida')} € (il piu' basso tra i simili)")
    q = v2.get("qualita")
    if q and v2.get("rivendita") is not None:
        righe.append(f"Qualita' comparabili: {q.get('punteggio')}/100 ({q.get('fascia')}, {q.get('n')} usati)")
    riga_costo = _riga_costo_totale(v2)
    if riga_costo:
        righe.append(riga_costo)
    ver = v2.get("verificata")
    frase = v2.get("jev_motivo_frase")
    if ver and RADAR_VERIFICA:
        # i comparabili sono stati verificati uno per uno: la rivendita sopra e' quella grezza, qui quella sul solo stesso modello
        righe.append(f"Verificati: {ver.get('n_stesso')} su {ver.get('n_giudicati')} stesso modello · rivendita {ver.get('rivendita')} € "
                     f"· margine {ver.get('margine')} € · ROI {ver.get('roi')}%")
        frase = _frase_senza_simili(v2)
    if v2.get("jev"):
        righe.append(f"Jev: {descrizione_jev(v2['jev'], v2.get('jev_conf'), frase)}")
    righe += _righe_link_comps(v2)
    return righe


# Risposta sotto il messaggio del tracker nel gruppo radar (richiesta dell'utente, 31/10: "messaggi con semaforo e
# vendita stimata" dove li legge davvero). Silenziosa. 0 = spenta.
RADAR_RISPOSTA_GRUPPO = os.environ.get("RADAR_RISPOSTA_GRUPPO", "1").strip() not in ("0", "false", "no", "")


def _dettaglio_comp(v2):
    """' (X trovati in tutto, ricerca allargata)' per capire dove si perdono i comparabili. Pura."""
    g = v2.get("n_grezzi")
    extra = ", ricerca allargata" if v2.get("allargata") else ""
    return f" ({g} grezzi{extra})" if g is not None else (" (ricerca allargata)" if extra else "")


def testo_risposta_gruppo(v2):
    """Riga breve per la risposta nel gruppo: semaforo, rivendita stimata, margine, ROI, comparabili. Pura."""
    if not v2:
        return "⚪ semaforo non calcolato"
    n = v2.get("n") or 0
    colore = v2.get("semaforo") or "n.d."
    if v2.get("rivendita") is None:
        return f"{pallino_semaforo(v2, '⚪')} {colore} · nessuna stima ({_motivo_leggibile(v2.get('motivo'))}, {n} comparabili{_dettaglio_comp(v2)})"
    testo = (f"{pallino_semaforo(v2, '⚪')} {colore} · rivendita stimata {v2.get('rivendita')} € · margine {v2.get('margine')} € "
             f"· ROI {v2.get('roi')}% · {n} comparabili{_dettaglio_comp(v2)}")
    if v2.get("jev"):
        testo += f"\nJev: {descrizione_jev(v2['jev'], v2.get('jev_conf'), _frase_senza_simili(v2))}"
    if v2.get("semaforo") in RADAR_SEMAFORI:
        motivo = perche_non_inviato(v2)
        testo += "\n" + ("Inviato in COMPRA" if motivo is None else f"Non inviato in COMPRA: {motivo}")
        testo += "".join("\n" + r for r in _righe_link_comps(v2))
    return testo


# Scarti che non sono l'oggetto intero (ricambio, accessorio, scatola, parola vietata, prezzo segnaposto, titolo generico):
# il messaggio del tracker nel gruppo si cancella invece di rispondere (richiesta dell'utente, 31/10: niente rumore).
RADAR_CANCELLA_SCARTI = os.environ.get("RADAR_CANCELLA_SCARTI", "1").strip() not in ("0", "false", "no", "")
MOTIVI_NON_OGGETTO = ("parola_vietata", "pezzo_o_accessorio", "prezzo_segnaposto", "titolo_generico", "famiglia_senza_margine", "jev_tipo")


# Anche i rossi economici (margine/ROI bassi, sopra il riferimento, pochi comparabili) si cancellano dal gruppo
# (richiesta dell'utente, 31/10: "mi arriva di tutto, anche i rossi"). Il tracciamento resta: i rossi si validano nei log.
RADAR_CANCELLA_ROSSI = os.environ.get("RADAR_CANCELLA_ROSSI", "1").strip() not in ("0", "false", "no", "")


def da_cancellare(v2):
    """True se il verdetto e' un rosso da togliere dal gruppo: non e' l'oggetto intero, oppure (RADAR_CANCELLA_ROSSI) e' rosso. Pura."""
    if not v2 or v2.get("semaforo") != "rosso":
        return False
    return RADAR_CANCELLA_ROSSI or (v2.get("motivo") or "").split(":")[0] in MOTIVI_NON_OGGETTO


# Verifica dei comparabili (01/11, richiesta dell'utente: "i simili non sono lo stesso modello"): se Jev ha giudicato i comparabili
# e la rivendita sui soli "stesso modello" non da' verde o giallo, l'avviso non parte. Senza verifica (pochi comparabili, Jev spento) resta il vecchio comportamento.
RADAR_VERIFICA = os.environ.get("RADAR_VERIFICA", "1").strip() not in ("0", "false", "no", "")
SUFFISSO_SIMILI = ", ma i simili non sono lo stesso modello"


def _frase_senza_simili(v2):
    """Motivo di Jev senza il suffisso sui simili quando i comparabili sono stati verificati uno per uno."""
    frase = v2.get("jev_motivo_frase")
    if v2.get("verificata") and RADAR_VERIFICA:
        return (frase or "").replace(SUFFISSO_SIMILI, "") or None
    return frase


def perche_non_inviato(v2):
    """None se l'avviso va mandato, altrimenti la frase che dice perche' no (per il gruppo e per i log). Pura."""
    if not v2 or v2.get("semaforo") not in RADAR_SEMAFORI:
        return "semaforo rosso: margine o ROI sotto soglia" if v2 and v2.get("semaforo") == "rosso" else "semaforo non calcolato"
    if RADAR_JEV_RICHIESTO and not (v2.get("jev") == "affare_vero" and (v2.get("jev_conf") or 0) >= RADAR_JEV_CONF_MIN):
        if v2.get("jev") == "affare_vero":
            return f"Jev dice affare ma con confidenza {v2.get('jev_conf')} sotto la soglia {RADAR_JEV_CONF_MIN}"
        return f"Jev non lo da' come affare ({v2.get('jev_motivo_frase') or v2.get('jev') or 'nessun giudizio'})"
    ver = v2.get("verificata")
    if RADAR_VERIFICA and ver and ver.get("semaforo") not in RADAR_SEMAFORI:
        return f"comparabili verificati: solo {ver.get('n_stesso')} su {ver.get('n_giudicati')} sono lo stesso modello"
    return None


def _da_mandare(v2):
    """Solo i semafori in RADAR_SEMAFORI (verde e giallo) e, con RADAR_JEV_RICHIESTO, solo se Jev dice affare con la confidenza
    minima: niente rossi, niente annunci senza verdetto, niente rotti o ricambi."""
    motivo = perche_non_inviato(v2)
    if motivo and v2 and v2.get("semaforo") in RADAR_SEMAFORI:
        log.info("RADAR SCARTATO | semaforo=%s | jev=%s | conf=%s | %s", v2.get("semaforo"), v2.get("jev"), v2.get("jev_conf"), motivo)
    return motivo is None


def _con_suono(v2):
    """Solo i verdi fanno suono nel chat degli avvisi (31/10: il gruppo del tracker e' silenzioso, la notifica deve essere un affare vero)."""
    return bool(v2) and v2.get("semaforo") == "verde"


async def _invia_radar(testo, foto=None, suono=False):
    """Messaggio del radar al chat privato: con la foto del tracker se c'e', altrimenti solo testo. Suono solo se `suono`."""
    log.info("RADAR PRIVATO | inviato alla chat privata | foto=%s | testo=%s", "si" if foto else "no", testo.replace("\n", " / "))
    if foto:
        await telegram_send_photo(RADAR_CHAT_ID, foto, caption=testo, disable_notification=not suono)
        log.info("RADAR FOTO | inviata con foto (%d KB)", len(foto) // 1024)
    else:
        await telegram_send_message(RADAR_CHAT_ID, testo, disable_notification=not suono)


_radar_inviati = set()


async def invia_verdetto_v2(parsed, url, v2, foto=None):
    """Manda al chat degli avvisi i verdetti v2 in RADAR_SEMAFORI (verde con suono, giallo silenzioso), subito dopo
    l'analisi: prima l'invio passava solo dal vecchio ramo e i gialli non arrivavano mai. Anti-duplicato per annuncio.
    Ritorna True se ha inviato."""
    if not _da_mandare(v2) or radar_in_pausa():
        return False
    item_id = _estrai_item_id_da_url(url) if url else None
    if not item_id or str(item_id) in _radar_inviati:
        return False
    _radar_inviati.add(str(item_id))
    if len(_radar_inviati) > 20000:
        _radar_inviati.clear()
    try:
        prezzo = _a_float(parsed.get("price"), None)
        intestazione = f"{pallino_semaforo(v2)} {prezzo:g} €" if prezzo is not None else pallino_semaforo(v2)
        testo = "\n".join([intestazione, (parsed.get("title") or "")[:100]] + _righe_v2(v2) + [url])
        await _invia_radar(testo, foto, suono=_con_suono(v2))
        return True
    except Exception:
        log.warning("Radar: verdetto v2 non inviato per %s:\n%s", item_id, traceback.format_exc())
        return False


async def _manda_semaforo_radar(item_id, titolo, prezzo, url, modello, buy_max, v2=None, foto=None):
    if not _da_mandare(v2) or str(item_id) in _radar_inviati:
        return
    try:
        testo = "\n".join([f"{pallino_semaforo(v2)} modello {modello} | {prezzo:g} € (buy max {buy_max:g} €)", titolo[:100]]
                          + _righe_v2(v2) + [url])
        await _invia_radar(testo, foto, suono=_con_suono(v2))
        log.info("RADAR MODELLO | item=%s | modello=%s | prezzo=%s | buy_max=%s", item_id, modello, prezzo, buy_max)
    except Exception:
        log.warning("Radar: semaforo non inviato per %s:\n%s", item_id, traceback.format_exc())


async def _manda_annuncio_senza_modello(item_id, titolo, prezzo, url, v2=None, foto=None):
    if not _da_mandare(v2) or str(item_id) in _radar_inviati:
        return
    try:
        pall = pallino_semaforo(v2)
        intestazione = f"{pall} fuori matrice | {prezzo:g} €" if prezzo is not None else f"{pall} fuori matrice"
        testo = "\n".join([intestazione, titolo[:100]] + _righe_v2(v2) + [url])
        await _invia_radar(testo, foto, suono=_con_suono(v2))
        log.info("RADAR FUORI MATRICE | item=%s | prezzo=%s | titolo=%s", item_id, prezzo, titolo[:60])
    except Exception:
        log.warning("Radar: annuncio fuori matrice non inviato per %s:\n%s", item_id, traceback.format_exc())


def traccia_verdetto_v2(parsed, url, v2, t0=None):
    """Avvia la serie di ricontrolli di vendita per un annuncio col verdetto v2 (semaforo nel contesto della riga
    TRACCIATO_RADAR). Gialli e verdi sempre; rossi 1 ogni RADAR_TRACCIA_ROSSI_1_SU (0 = nessuno), esclusi i non-oggetto.
    Ritorna True se la serie e' partita."""
    if not v2 or not v2.get("semaforo"):
        return False
    item_id = _estrai_item_id_da_url(url) if url else None
    if not item_id or str(item_id) in _radar_tracciati:
        return False
    sem = v2["semaforo"]
    audit = False
    if sem == "rosso":
        non_oggetto = (v2.get("motivo") or "").split(":")[0] in MOTIVI_NON_OGGETTO
        passo = RADAR_AUDIT_1_SU if non_oggetto else RADAR_TRACCIA_ROSSI_1_SU
        if not passo:
            return False
        try:
            if int(item_id) % passo:
                return False
        except ValueError:
            return False
        audit = True
    _radar_tracciati.add(str(item_id))
    if len(_radar_tracciati) > 20000:
        _radar_tracciati.clear()
    prezzo = _a_float(parsed.get("price"), None)
    info = {"title": parsed.get("title"), "price": prezzo, "brand": parsed.get("brand"), "url": url}
    tr._tracc_esiti[str(item_id)] = ("RADAR_V2", None)
    tr._tracc_ctx[str(item_id)] = {k: v for k, v in {
        "semaforo": sem, "motivo": v2.get("motivo"), "rivendita": v2.get("rivendita"), "margine": v2.get("margine"),
        "roi": v2.get("roi"), "n_comp": v2.get("n"), "jev": v2.get("jev"), "jev_motivo": v2.get("jev_motivo"),
        "audit": "si" if audit else None, "vendita_stimata": v2.get("rivendita"), "richiesto_med": v2.get("richiesto_mediano"),
        "qualita": (v2.get("qualita") or {}).get("punteggio"), "costo_tot": v2.get("costo_totale"),
        "sped": v2.get("spedizione_stato"), "calib": v2.get("calibrazione")}.items()
        if v is not None}
    tr.tracc_avvia_serie(info, url, t0 or time.time(), offsets=RADAR_RICONTROLLI_SECONDI)
    log.info("RADAR TRACCIA AVVIO | item=%s | semaforo=%s | prezzo=%s", item_id, sem, prezzo)
    if audit:
        log.info("RADAR AUDIT | item=%s | motivo=%s | margine=%s | roi=%s", item_id, v2.get("motivo"), v2.get("margine"), v2.get("roi"))
    return True


async def gestisci_annuncio_radar(parsed, url, t0=None, v2=None, foto=None):
    """Fase 0: classifica, filtra, visita la pagina se serve, registra. Mai messaggi, mai AI."""
    global _radar_pausa_saltati
    if not RADAR_ATTIVO:
        return
    if radar_in_pausa():
        _radar_pausa_saltati += 1
        if _radar_pausa_saltati % 100 == 1:
            log.info("RADAR PAUSA | notte %s-%s ora italiana: messaggi radar ignorati (%d dall'ultimo avvio)",
                     RADAR_PAUSA_DA, RADAR_PAUSA_A, _radar_pausa_saltati)
        return
    t0 = t0 or time.time()
    item_id = _estrai_item_id_da_url(url)
    if not item_id or item_id in _radar_visti:
        return
    _radar_visti.add(item_id)
    if len(_radar_visti) > 20000:
        _radar_visti.clear()
    titolo = parsed.get("title") or ""
    prezzo = _a_float(parsed.get("price"), None)
    modulo, brand_radar, tipo = classifica_radar(titolo, parsed.get("brand"))
    passa, motivo = filtro_livello1(titolo, prezzo, modulo, parsed.get("brand"))
    riga = rm.trova_modello(titolo, parsed.get("brand"), rm.MATRICE) if modulo else None
    modello = (riga.get("id") or riga.get("modello")) if riga else None
    bm = riga.get("buy_max") if riga else None
    if RADAR_MOSTRA_TUTTI and modello and bm and prezzo is not None:
        await _manda_semaforo_radar(item_id, titolo, prezzo, url, modello, bm, v2, foto)
    elif RADAR_MOSTRA_TUTTI and not modello:
        # Verifica (25/10): annuncio di una lista senza modello riconosciuto: messaggio, poi il flusso di sempre.
        await _manda_annuncio_senza_modello(item_id, titolo, prezzo, url, v2, foto)
    campione = (not passa) and modulo is not None and not motivo.startswith("prezzo_sotto") and nel_campione_scarti(item_id)
    base = {"titolo": titolo[:120], "prezzo": prezzo, "modulo": modulo, "brand_radar": brand_radar,
            "tipo": tipo, "l1": "passa" if passa else "scarto", "motivo": motivo, "campione": campione,
            "modello": modello, "buy_max": bm}
    if not (passa or campione):
        log.info("RADAR SCARTO | item=%s | modulo=%s | tipo=%s | motivo=%s | prezzo=%s | modello=%s | titolo=%s",
                 item_id, modulo or "-", tipo, motivo, prezzo, _v(modello), titolo[:60])
        db.scrivi_evento("radar", item_id, brand_radar, base)
        return
    try:
        async with _radar_sem:
            pagina = await scrape_vinted_listing(url, includi_guardaroba=False)
        info = {**pagina, "title": titolo, "price": prezzo, "brand": brand_radar or parsed.get("brand"),
                "url": url}
        n_foto = len(pagina.get("photo_urls") or [])
        desc = (pagina.get("description") or "").strip()
        # la descrizione puo' contenere le parole vietate anche se il titolo e' pulito: si registra, non si scarta
        vietata_desc = parola_vietata(desc)
        esito = "RADAR_L1_PASSA" if passa else "RADAR_L1_CAMPIONE"
        dati = {**base, "catalog_id": pagina.get("catalog_id"), "cond": pagina.get("condition"),
                "n_foto": n_foto, "desc_len": len(desc),
                "vietata_desc": vietata_desc,
                "stato": pagina.get("stato_vendita"), "pref": pagina.get("preferiti"),
                "v_rec": pagina.get("seller_feedback_count"), "v_art": pagina.get("seller_items_count"),
                "v_paese": pagina.get("seller_country"), "eta_s": round(time.time() - t0, 1)}
        log.info(
            "RADAR | item=%s | esito=%s | modulo=%s | brand=%s | tipo=%s | prezzo=%s | modello=%s | buy_max=%s | "
            "catalogo=%s | cond=%s | "
            "n_foto=%s | desc_len=%s | vietata_desc=%s | stato=%s | pref=%s | v_rec=%s | v_art=%s | v_paese=%s | "
            "titolo=%s",
            item_id, esito, modulo, _v(brand_radar), tipo, prezzo, _v(modello), _v(bm), _v(dati["catalog_id"]),
            _v(dati["cond"]),
            n_foto, len(desc), _v(dati["vietata_desc"]), _v(dati["stato"]), _v(dati["pref"]), _v(dati["v_rec"]),
            _v(dati["v_art"]), _v(dati["v_paese"]), titolo[:60],
        )
        db.scrivi_evento("radar", item_id, brand_radar, dati)
        # Ricontrolli di vendita come per la moda: l'esito RADAR_* li tiene separati nel recap.
        tr._tracc_esiti[str(item_id)] = (esito, None)
        tr.tracc_registra_valutato(info, url, esito)
        if str(item_id) not in _radar_tracciati:
            tr.tracc_avvia_serie(info, url, t0, offsets=RADAR_RICONTROLLI_SECONDI)
    except Exception:
        log.warning("Radar: annuncio %s non registrato:\n%s", item_id, traceback.format_exc())
