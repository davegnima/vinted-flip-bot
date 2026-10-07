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

from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot import db
from bot import tracciamento as tr
from bot.vinted_scrape import scrape_vinted_listing
from bot.logger import log
# ---- fine import ----

RADAR_MARCATORE = os.environ.get("RADAR_MARCATORE", "📡").strip()
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
RADAR_RICONTROLLI_SECONDI = tuple(
    int(x) for x in os.environ.get("RADAR_RICONTROLLI_SECONDI", "60,900,3600").split(",") if x.strip())
_radar_sem = asyncio.Semaphore(RADAR_MAX_PARALLELO)
_radar_visti = set()

# ---------------------------------------------------------------------------
# Moduli categoria. Brand e parole sono confrontati sul titolo in minuscolo, a parola intera.
# spedizione_eur, rischio_falsi, rischio_guasti e prezzo_max_l1 sono valori di partenza (da tarare con la fase 0):
# prezzo_max_l1 = oltre questo prezzo raggiungere ROI 100% e margine 50 EUR e' improbabile per la categoria.
# I brand sono i 30 radar scelti dall'utente il 2026-10-07.
# ---------------------------------------------------------------------------
RADAR_MODULI = {
    "illuminazione_design": {
        "brand": ("artemide", "flos", "fontanaarte", "fontana arte", "oluce", "kartell", "vitra", "cassina",
                  "zanotta", "alessi"),
        "parole": ("lampada", "lampade", "applique", "plafoniera", "lampadario", "abat-jour", "abat jour",
                   "piantana", "sedia", "sgabello", "poltrona", "tavolino"),
        "spedizione_eur": 15.0, "rischio_falsi": "basso", "rischio_guasti": "medio", "prezzo_max_l1": 250,
    },
    "ceramiche_oggetti": {
        "brand": ("bitossi", "fornasetti"),
        "parole": ("ceramica", "vaso", "piatto", "piatti", "posacenere", "centrotavola"),
        "spedizione_eur": 10.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 150,
    },
    "argento_gioielli": {
        "brand": ("georg jensen",),
        "parole": ("argento 925", "sterling", "spilla", "bracciale argento"),
        "spedizione_eur": 6.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 150,
    },
    "occhiali": {
        "brand": ("persol", "oliver peoples", "matsuda"),
        "parole": ("occhiali", "montatura", "occhiale"),
        "spedizione_eur": 5.0, "rischio_falsi": "medio", "rischio_guasti": "basso", "prezzo_max_l1": 120,
    },
    "borse_vintage": {
        "brand": ("mulberry", "roberta di camerino", "coach"),
        "parole": ("borsa", "borsetta", "pochette", "tracolla"),
        "spedizione_eur": 6.0, "rischio_falsi": "alto", "rischio_guasti": "basso", "prezzo_max_l1": 150,
    },
    "lego": {
        "brand": ("lego",),
        "parole": ("set lego", "minifigure", "minifig", "technic", "star wars", "ideas"),
        "spedizione_eur": 9.0, "rischio_falsi": "basso", "rischio_guasti": "medio", "prezzo_max_l1": 200,
    },
    "console_retro": {
        "brand": ("nintendo", "game boy", "gameboy"),
        "parole": ("game boy", "gameboy", "gamecube", "n64", "nintendo 64", "ds", "3ds", "snes", "nes",
                   "cartuccia", "console"),
        "spedizione_eur": 7.0, "rischio_falsi": "medio", "rischio_guasti": "alto", "prezzo_max_l1": 150,
    },
    "fotografia": {
        "brand": ("contax",),
        "parole": ("fotocamera", "macchina fotografica", "obiettivo", "reflex", "analogica", "compatta 35mm"),
        "spedizione_eur": 8.0, "rischio_falsi": "basso", "rischio_guasti": "alto", "prezzo_max_l1": 300,
    },
    "audio": {
        "brand": ("bang & olufsen", "bang olufsen", "b&o", "beoplay", "beosound", "audeze"),
        "parole": ("cuffie", "speaker", "cassa", "diffusore", "giradischi"),
        "spedizione_eur": 9.0, "rischio_falsi": "medio", "rischio_guasti": "alto", "prezzo_max_l1": 300,
    },
    "golf": {
        "brand": ("scotty cameron",),
        "parole": ("putter",),
        "spedizione_eur": 15.0, "rischio_falsi": "alto", "rischio_guasti": "basso", "prezzo_max_l1": 200,
    },
    "libri": {
        "brand": ("taschen", "assouline", "steidl"),
        "parole": ("libro", "volume", "monografia"),
        "spedizione_eur": 8.0, "rischio_falsi": "basso", "rischio_guasti": "basso", "prezzo_max_l1": 100,
    },
}

# Il venditore dichiara che e' rotto/incompleto o che non e' l'originale: l'utente non ripara e non compra repliche.
_PAROLE_VIETATE_RE = re.compile(
    r"(?<!\w)(rott[oaie]|non funzion\w*|da riparare|guast[oaie]|difettos[oaie]|per pezzi|per ricambi|ricambi"
    r"|incomplet[oaie]|mancante|mancano|senza pezzi|replica|fake|copia|imitazione|ispirat[oaie]|stile|simil\w*"
    r"|tipo|non original\w*|broken|for parts)(?!\w)",
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


def filtro_livello1(titolo, prezzo, modulo):
    """(passa, motivo) sul solo messaggio del tracker. Pura."""
    if modulo is None:
        return False, "fuori_radar"
    vietata = parola_vietata(titolo)
    if vietata:
        return False, "parola_vietata:" + vietata.replace(" ", "_")
    if prezzo is None or prezzo <= 0:
        return False, "prezzo_mancante"
    if prezzo < RADAR_PREZZO_MIN:
        return False, f"prezzo_sotto_minimo:{RADAR_PREZZO_MIN:g}"
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


async def gestisci_annuncio_radar(parsed, url, t0=None):
    """Fase 0: classifica, filtra, visita la pagina se serve, registra. Mai messaggi, mai AI."""
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
    passa, motivo = filtro_livello1(titolo, prezzo, modulo)
    campione = (not passa) and modulo is not None and not motivo.startswith("prezzo_sotto") and nel_campione_scarti(item_id)
    base = {"titolo": titolo[:120], "prezzo": prezzo, "modulo": modulo, "brand_radar": brand_radar,
            "tipo": tipo, "l1": "passa" if passa else "scarto", "motivo": motivo, "campione": campione}
    if not (passa or campione):
        log.info("RADAR SCARTO | item=%s | modulo=%s | tipo=%s | motivo=%s | prezzo=%s | titolo=%s", item_id,
                 modulo or "-", tipo, motivo, prezzo, titolo[:60])
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
            "RADAR | item=%s | esito=%s | modulo=%s | brand=%s | tipo=%s | prezzo=%s | catalogo=%s | cond=%s | "
            "n_foto=%s | desc_len=%s | vietata_desc=%s | stato=%s | pref=%s | v_rec=%s | v_art=%s | v_paese=%s | "
            "titolo=%s",
            item_id, esito, modulo, _v(brand_radar), tipo, prezzo, _v(dati["catalog_id"]), _v(dati["cond"]),
            n_foto, len(desc), _v(dati["vietata_desc"]), _v(dati["stato"]), _v(dati["pref"]), _v(dati["v_rec"]),
            _v(dati["v_art"]), _v(dati["v_paese"]), titolo[:60],
        )
        db.scrivi_evento("radar", item_id, brand_radar, dati)
        # Ricontrolli di vendita come per la moda: l'esito RADAR_* li tiene separati nel recap.
        tr._tracc_esiti[str(item_id)] = (esito, None)
        tr.tracc_registra_valutato(info, url, esito)
        tr.tracc_avvia_serie(info, url, t0, offsets=RADAR_RICONTROLLI_SECONDI)
    except Exception:
        log.warning("Radar: annuncio %s non registrato:\n%s", item_id, traceback.format_exc())
