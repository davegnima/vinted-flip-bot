"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import json
import time
import asyncio


from bot.costanti import CATEGORIA_TERMINE_EN, VINTED_BRAND_IDS
from bot.config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, VISUAL_SEARCH_ATTIVA
from bot.config import RESELLBOT_ATTIVO
from bot.serper_fonti import _cerca_ebay_sold_via_resellbot, _serper_batch_query_ebay_sold, _serper_scrape_page_diretto
from bot.comps_filtri import _estrai_articoli_da_alt_vinted, _estrai_mappa_url_comp_vinted, _filtra_comp_per_brand_sottolinee, _filtra_comp_per_categoria, _rimuovi_comp_autoreferenziale
from bot.vinted_http import _vinted_get_con_retry
from bot.vinted_search import build_vinted_search_url, build_vinted_visual_search_url
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
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
    sulla stessa riga -- scartato prima del deploy.

    Ritorna (testo, ok, mappa_url) invece del vecchio (testo, ok): la mappa
    (vedi _estrai_mappa_url_comp_vinted) e' costruita dallo stesso HTML gia'
    scaricato qui, a costo zero di richieste aggiuntive, per rimappare i
    link cliccabili al rendering finale (Punto 3, 2026-09-25)."""
    resp = await _vinted_get_con_retry(url, timeout=15, max_retries=2)
    if resp is None:
        return "  Scrape diretto Vinted fallito (nessuna risposta dopo i retry).", False, {}
    return _estrai_articoli_da_alt_vinted(resp.text), True, _estrai_mappa_url_comp_vinted(resp.text)


# Timeout dedicati alla ricerca testuale Vinted con fallback (2026-09-25):
# lo scrape diretto ha un budget corto, cosi' se Vinted e' lento o risponde
# 403 resta tempo per il tentativo Serper dentro il timeout complessivo della
# fonte (TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI in search_comps_completo).
TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI = 8
TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI = 25
MARKER_NESSUN_ARTICOLO_VINTED = "Nessun articolo trovato"


async def _cerca_vinted_testo_diretto_con_fallback_serper(url):
    """Ricerca comp testuale su Vinted: PRIMA lo scrape diretto della pagina
    catalogo (stesso client/proxy e stesso parser su alt= gia' usati per la
    ricerca visuale, vedi _scrape_catalogo_vinted_diretto), POI Serper solo
    se il diretto fallisce o non estrae nessun articolo.

    Aggiunta il 2026-09-25 su richiesta dell'utente per risparmiare crediti
    Serper sulla ricerca testuale (una chiamata a ogni annuncio, piu' una
    per il sarto quando c'e'). Serper resta come rete di sicurezza e non
    viene tolto: lo scrape diretto aggiunge 1-2 richieste a Vinted per
    annuncio dallo stesso IP, e il bot ha gia' preso 403 da Vinted dopo molte
    ore di attivita' (vedi PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI). Se
    succede, il fallback copre l'annuncio invece di lasciarlo senza comp.

    Stesso contratto di ritorno delle altre fonti: (testo, ok, mappa_url),
    con il testo nel formato '- titolo — €prezzo' una riga per articolo.
    mappa_url (aggiunta il 2026-09-25, vedi _estrai_mappa_url_comp_vinted)
    e' popolata SOLO sul ramo di scrape diretto: l'HTML che arriva da
    Serper (_serper_scrape_page_diretto) e' gia' passato per un'estrazione
    di contenuto che non preserva i data-testid, quindi su quel ramo il
    dizionario resta vuoto -- niente link per quei comp, non un errore."""
    motivo_fallback = None
    try:
        resp = await asyncio.wait_for(
            _vinted_get_con_retry(url, timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI, max_retries=1),
            timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI + 4,
        )
    except asyncio.TimeoutError:
        resp = None
        motivo_fallback = "timeout scrape diretto"
    if resp is not None:
        testo = _estrai_articoli_da_alt_vinted(resp.text)
        # Etichetta proxy (2026-09-27, vedi _vinted_get_con_retry) anche qui:
        # stessa logica del catalogo che sopra, applicata al lato testuale
        # "senza articoli estratti" -- e' l'ALTRO caso applicativo (oltre alle
        # foto) in cui Vinted risponde 200 ma con una pagina non utilizzabile.
        etichetta_proxy = getattr(resp, "_proxy_etichetta", "?")
        if MARKER_NESSUN_ARTICOLO_VINTED not in testo:
            log.info("Comp Vinted testo: scrape diretto OK (%d articoli, proxy=%s), Serper non usato -- %s",
                     testo.count("\n") + 1, etichetta_proxy, url)
            return testo, True, _estrai_mappa_url_comp_vinted(resp.text)
        motivo_fallback = (
            f"scrape diretto senza articoli estratti (proxy={etichetta_proxy}, "
            f"status {resp.status_code}, len {len(resp.text)})"
        )
    elif motivo_fallback is None:
        motivo_fallback = "scrape diretto fallito (nessuna risposta)"

    log.info("Comp Vinted testo: %s -- uso Serper come riserva per %s", motivo_fallback, url)
    testo_serper, ok_serper = await _serper_scrape_page_diretto("VINTED", url)
    if ok_serper:
        return testo_serper, True, {}
    return f"  {motivo_fallback}; fallback Serper anch'esso fallito: {testo_serper.strip()}", False, {}


async def _recupera_comp_visuali_vinted(item_id, photo_id, brand):
    """Wrapper per la fonte visuale, pensato per essere sottomesso come UN
    solo future nello stesso executor delle altre 3 fonti (vedi
    search_comps_completo) cosi' la risoluzione dell'ID (chiamata di rete
    verso Vinted, non istantanea) corre IN PARALLELO alle altre ricerche
    invece di bloccarne l'avvio. Fa due passi in sequenza al suo interno
    (risolvi ID -> scrape del catalogo con quell'ID), ma dal punto di vista
    dell'executor e' un solo task con lo stesso contratto di ritorno
    (testo, ok, mappa_url) degli altri (mappa_url aggiunta il 2026-09-25,
    vedi _estrai_mappa_url_comp_vinted). ok=False (non un'eccezione) quando
    manca un ingrediente o la risoluzione fallisce, cosi' il chiamante lo
    tratta come fonte assente senza differenziare i log dalle altre query
    fallite.

    Scrape diretto (non Serper) dal 2026-09-20: vedi docstring di
    _scrape_catalogo_vinted_diretto per il perche'."""
    url = await build_vinted_visual_search_url(item_id, photo_id, brand)
    if not url:
        log.info(
            "_recupera_comp_visuali_vinted: fonte non disponibile per item_id=%s "
            "(photo_id/brand mancante o risoluzione ID fallita).", item_id,
        )
        return "  Fonte non disponibile (photo_id/brand mancante o risoluzione ID falsa).", False, {}
    testo, ok, mappa_url = await _scrape_catalogo_vinted_diretto(url)
    log.info(
        "_recupera_comp_visuali_vinted: scrape catalogo grezzo per item_id=%s ok=%s -> %r",
        item_id, ok, testo,
    )
    return testo, ok, mappa_url


# Cache dei venduti Resellbot (richiesto dall'utente il 2026-10-03): l'analisi del 2026-10-02 ha mostrato
# Resellbot in errore 429 decine di volte da sera, con il bot costretto al fallback Google (meno preciso,
# nessun URL). I prezzi venduti per brand+categoria cambiano lentamente: si riusano per 24h (meno chiamate,
# meno 429) e, se Resellbot e' bloccato, fino a 72h prima di ripiegare su Google.
SOLD_CACHE_FRESCA_SECONDI = 24 * 3600
SOLD_CACHE_STALE_SECONDI = 72 * 3600
SOLD_CACHE_MAX_VOCI = 400
_sold_cache = {}


def _sold_cache_chiave(brand, categoria, material_per_ricerca, dettaglio_distintivo):
    return tuple((str(x or "")).strip().lower() for x in (brand, categoria, material_per_ricerca, dettaglio_distintivo))


def _sold_cache_leggi(chiave, max_eta_secondi):
    voce = _sold_cache.get(chiave)
    if voce and time.time() - voce[0] <= max_eta_secondi:
        return voce[1], voce[2]
    return None


def _sold_cache_scrivi(chiave, testo, mappa_url):
    if len(_sold_cache) >= SOLD_CACHE_MAX_VOCI:
        for k in sorted(_sold_cache, key=lambda k: _sold_cache[k][0])[:SOLD_CACHE_MAX_VOCI // 4]:
            _sold_cache.pop(k, None)
    _sold_cache[chiave] = (time.time(), testo, mappa_url)


async def _cerca_ebay_sold_con_fallback(brand, categoria, material_per_ricerca=None, dettaglio_distintivo=None):
    """Wrapper per l'executor: prova prima Resellbot (dati di vendita
    confermati, veri, vedi _cerca_ebay_sold_via_resellbot), e solo se fallisce
    (bloccato, rate-limited, errore di rete, o semplicemente 'nessun venduto
    trovato' con ok=True viene comunque accettato cosi' com'e' -- il fallback
    scatta solo su ok=False) prova la query Google di riserva. Tenute
    sequenziali (non in parallelo) per non raddoppiare le chiamate quando la
    prima fonte funziona, che e' il caso comune.

    material_per_ricerca (aggiunto il 2026-09-19) e dettaglio_distintivo
    (aggiunto il 2026-09-25, vedi occhio_schema.dettaglio_distintivo_ricerca)
    vengono inoltrati a entrambe le fonti per restringere la query -- vedi
    docstring di _cerca_ebay_sold_via_resellbot per come le varianti vengono
    combinate in una sola chiamata a Resellbot.

    Ritorna (testo, ok, mappa_url) dal 2026-09-25: mappa_url e' popolata solo
    sul ramo Resellbot (fonte primaria), vuota sul ramo fallback Google."""
    chiave_cache = _sold_cache_chiave(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    in_cache = _sold_cache_leggi(chiave_cache, SOLD_CACHE_FRESCA_SECONDI)
    if in_cache:
        return in_cache[0], True, in_cache[1]
    if not RESELLBOT_ATTIVO:
        # Resellbot disattivato: si va direttamente su Google/eBay, niente chiamate sprecate ne' cache dei venduti.
        testo_fallback, ok_fallback = await _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca, dettaglio_distintivo)
        if ok_fallback:
            return (f"{testo_fallback}\n(Nota: eBay/Poshmark da ricerca Google, non da vendite confermate: "
                    f"trattali come prezzi ASK.)"), True, {}
        return f"ricerca Google eBay/Poshmark fallita: {testo_fallback}", False, {}
    testo, ok, mappa_url = await _cerca_ebay_sold_via_resellbot(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    if ok:
        _sold_cache_scrivi(chiave_cache, testo, mappa_url)
        return testo, ok, mappa_url
    log.info("_cerca_ebay_sold_con_fallback: Resellbot fallito (%s), tento fallback Google.", testo)
    vecchio = _sold_cache_leggi(chiave_cache, SOLD_CACHE_STALE_SECONDI)
    if vecchio:
        log.info("_cerca_ebay_sold_con_fallback: uso i venduti in cache (piu' vecchi di %dh) al posto del fallback Google.",
                 SOLD_CACHE_FRESCA_SECONDI // 3600)
        return vecchio[0] + "\n(Nota: Resellbot non raggiungibile, questi venduti arrivano dalla cache di ore fa.)", True, vecchio[1]
    testo_fallback, ok_fallback = await _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    if ok_fallback:
        # Nessuna mappa_url dal fallback Google (stesso limite del fallback
        # Serper per Vinted, vedi _cerca_vinted_testo_diretto_con_fallback_serper):
        # gli snippet Google non danno un URL diretto all'annuncio abbastanza
        # affidabile per il lookup titolo+prezzo, quindi niente link Punto 3
        # per i comp arrivati da questo ramo.
        return f"{testo_fallback}\n(Nota: fonte primaria Resellbot fallita, questi risultati vengono da Google/eBay.)", True, {}
    return f"{testo} | fallback Google anch'esso fallito: {testo_fallback}", False, {}


# ---------------------------------------------------------------------------
# VERIFICA CODICI PRODOTTO SU REDDIT (aggiunto 2026-09-26, richiesto dall'utente)
# ---------------------------------------------------------------------------
# I contraffattori spesso riusano lo stesso codice prodotto/etichetta su capi
# diversi (altro modello, altro colore, a volte altro brand) perche' e' piu'
# comodo stampare un lotto di etichette identiche che farne una diversa per
# ogni pezzo. Se il codice che l'Occhio ha letto sull'etichetta compare online
# associato a un capo VISIBILMENTE diverso (altro brand noto), e' un segnale
# forte di contraffazione che oggi il pipeline non controlla affatto.
#
# Fonte scelta: ricerca Reddit, non Google/Serper. Motivo (vedi conversazione
# 2026-09-26): l'utente vuole questa parte a costo zero per sempre, e nel
# 2026 le API di ricerca web gratuite sono sparite (Google Custom Search ha
# chiuso il livello gratuito ai nuovi utenti a gennaio 2026, Brave Search ha
# eliminato il suo). Reddit invece resta gratis per uso personale non
# commerciale: 100 query/minuto via OAuth "application only"
# (grant_type=client_credentials), che NON richiede mai la password
# dell'account Reddit, solo client_id/client_secret di un'app di tipo
# "script". Ricerca su TUTTO Reddit, nessun subreddit fisso: restringere a
# pochi subreddit scelti a mano rischierebbe di perdere la discussione giusta
# finita altrove (vedi conversazione, l'utente ha chiesto esplicitamente se
# fosse necessario sceglierli -- non lo e').
#
# Se REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET non sono configurate su Railway,
# tutta questa sezione si disattiva da sola: REDDIT_ABILITATO=False,
# verifica_codici_prodotto_reddit ritorna subito stringa vuota, zero chiamate
# di rete, il resto del bot funziona esattamente come prima.
REDDIT_USER_AGENT = f"python:vinted-flip-oracle-codecheck:v1.0 (by /u/{REDDIT_USERNAME})"
REDDIT_ABILITATO = bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)

_reddit_token_cache = {"token": None, "scadenza": 0.0}

# Cache persistente su Volume (stesso pattern di TOKEN_FILE piu' sopra per i
# token Vinted): un codice gia' verificato non viene mai ricercato una
# seconda volta, ne' dopo un riavvio. Tiene il bot ben sotto le 100 query/min
# concesse gratis e velocizza i codici che ricorrono spesso (stesso lotto di
# contraffazioni rivenduto da piu' venditori).
CODICI_REDDIT_CACHE_FILE = "/data/codici_reddit_cache.json"
_codici_reddit_cache = {}
if os.path.exists(CODICI_REDDIT_CACHE_FILE):
    try:
        with open(CODICI_REDDIT_CACHE_FILE, "r") as f:
            _codici_reddit_cache = json.load(f)
    except Exception as e:
        log.warning("Impossibile leggere %s (probabilmente non esiste ancora): %s", CODICI_REDDIT_CACHE_FILE, e)


def _salva_cache_codici_reddit():
    try:
        os.makedirs(os.path.dirname(CODICI_REDDIT_CACHE_FILE), exist_ok=True)
        with open(CODICI_REDDIT_CACHE_FILE, "w") as f:
            json.dump(_codici_reddit_cache, f)
    except Exception as e:
        log.warning("Impossibile scrivere %s: %s", CODICI_REDDIT_CACHE_FILE, e)


async def _reddit_ottieni_token():
    """Token OAuth 'application only': sola lettura, non serve mai la
    password dell'account Reddit. Valido 1h (di solito), rigenerato solo
    quando serve, con 60s di margine per non usarne uno che scade a meta'
    di una richiesta in corso."""
    if _reddit_token_cache["token"] and time.time() < _reddit_token_cache["scadenza"] - 60:
        return _reddit_token_cache["token"]
    resp = await hc._client_generico.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        headers={"User-Agent": REDDIT_USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    dati = resp.json()
    _reddit_token_cache["token"] = dati["access_token"]
    _reddit_token_cache["scadenza"] = time.time() + dati.get("expires_in", 3600)
    return _reddit_token_cache["token"]


def _estrai_codici_prodotto_da_occhio(occhio_json):
    """Codici prodotto/etichetta letti dall'Occhio (etichette[].tipo ==
    'codice_prodotto'), filtrati per lunghezza minima e leggibilita' -- un
    codice illeggibile o troppo corto produrrebbe solo rumore in ricerca.
    Al massimo 2 per annuncio, per restare leggeri (in parallelo alla
    ricerca comp, non deve mai diventare lui il collo di bottiglia)."""
    if not occhio_json:
        return []
    etichette = occhio_json.get("etichette") or []
    codici = []
    for e in etichette:
        if e.get("tipo") != "codice_prodotto":
            continue
        if e.get("leggibilita") == "illeggibile":
            continue
        testo = str(e.get("testo_verbatim") or "").strip()
        testo_pulito = re.sub(r"\[.*?\]", "", testo).strip()
        if len(testo_pulito) < 4:
            continue
        if testo_pulito not in codici:
            codici.append(testo_pulito)
    return codici[:2]


# Brand di lusso comuni, usati per rilevare quando un codice compare online
# insieme a un brand DIVERSO dal nostro -- il segnale concreto di "codice
# riciclato su capi diversi". Lista euristica, non esaustiva di proposito:
# aiuta a beccare i casi piu' comuni, non deve essere mantenuta completa.
_BRAND_NOTI_PER_INCROCIO_REDDIT = [
    "gucci", "prada", "chanel", "louis vuitton", "dior", "miu miu", "loewe",
    "balenciaga", "burberry", "fendi", "versace", "valentino", "bottega veneta",
    "saint laurent", "ysl", "brunello cucinelli", "loro piana", "max mara",
    "missoni", "jil sander", "rick owens", "moncler", "stone island",
    "comme des garcons", "issey miyake", "margiela",
]


def _titoli_menzionano_altro_brand_reddit(testi, brand_nostro):
    """True/insieme se tra i risultati Reddit compare un brand noto DIVERSO
    dal nostro accanto al codice cercato. Segnala il caso piu' grossolano
    (codice riciclato tra brand diversi)."""
    brand_nostro_norm = (brand_nostro or "").strip().lower()
    trovati = set()
    for t in testi:
        tl = t.lower()
        for b in _BRAND_NOTI_PER_INCROCIO_REDDIT:
            if b in tl and b not in brand_nostro_norm and brand_nostro_norm not in b:
                trovati.add(b)
    return trovati


# Riusa la stessa mappa IT->EN gia' usata per le query di ricerca comp
# (CATEGORIA_TERMINE_EN, vedi piu' sopra): serve a riconoscere quando un
# risultato Reddit parla di un capo di categoria DIVERSA dalla nostra pur
# citando lo stesso codice E lo stesso brand -- il caso piu' subdolo e piu'
# comune (richiesto esplicitamente dall'utente il 2026-09-26): i
# contraffattori di solito NON usano un codice di un altro brand (troppo
# facile da beccare), usano un codice nel formato giusto per IL brand ma
# preso da un lotto/prodotto diverso (es. lo stesso codice stampato sia su
# una borsa che su un maglione).
def _titoli_menzionano_categoria_diversa_reddit(testi, categoria_en_nostra):
    """Insieme di categorie (in inglese) DIVERSE dalla nostra trovate nei
    risultati Reddit insieme al codice. Richiede categoria_en_nostra (gia'
    tradotta) per sapere quale escludere dal confronto."""
    if not categoria_en_nostra:
        return set()
    categoria_en_nostra = categoria_en_nostra.lower()
    trovate = set()
    for t in testi:
        tl = t.lower()
        for cat_en in set(CATEGORIA_TERMINE_EN.values()):
            if cat_en == categoria_en_nostra:
                continue
            if re.search(r"\b" + re.escape(cat_en) + r"\b", tl):
                trovate.add(cat_en)
    return trovate


async def _reddit_verifica_codice(codice, brand, categoria_en=None):
    """Cerca '"codice" brand' su tutto Reddit. Ritorna una riga di testo
    pronta per il prompt del Cervello, o None se non c'e' niente da
    segnalare (nessun risultato -- il caso piu' comune: e' un esito
    neutro, NON va spacciato per una conferma di autenticita', quindi in
    quel caso non si aggiunge nulla al prompt piuttosto che scrivere un
    falso rassicurante).

    Due controlli distinti, non uno solo (aggiunto il 2026-09-26 su
    richiesta esplicita dell'utente): il codice compare con un BRAND
    diverso (grossolano, raro) o con la stessa marca ma una CATEGORIA di
    prodotto diversa (il caso vero: codice in formato coerente col brand ma
    riciclato da un altro lotto/prodotto). Il secondo e' il controllo che
    conta davvero, il primo resta come rete di sicurezza per il caso
    limite."""
    chiave = f"{codice.lower()}|{(brand or '').lower()}|{(categoria_en or '').lower()}"
    if chiave in _codici_reddit_cache:
        return _codici_reddit_cache[chiave]

    risultato = None
    try:
        token = await _reddit_ottieni_token()
        resp = await hc._client_generico.get(
            "https://oauth.reddit.com/search",
            params={"q": f"\"{codice}\" {brand}", "sort": "relevance", "limit": 10},
            headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
        testi = []
        link_esempio = None
        for p in posts:
            d = p.get("data", {})
            titolo = d.get("title", "")
            corpo = (d.get("selftext", "") or "")[:300]
            if codice.lower() in (titolo + " " + corpo).lower():
                testi.append(f"{titolo} {corpo}")
                if not link_esempio:
                    link_esempio = f"https://reddit.com{d.get('permalink', '')}"
        if not testi:
            risultato = None
        else:
            altri_brand = _titoli_menzionano_altro_brand_reddit(testi, brand)
            altre_categorie = _titoli_menzionano_categoria_diversa_reddit(testi, categoria_en)
            if altri_brand or altre_categorie:
                pezzi = []
                if altre_categorie:
                    pezzi.append(
                        f"su un capo di categoria diversa ({', '.join(sorted(altre_categorie))} "
                        f"invece di {categoria_en})"
                    )
                if altri_brand:
                    pezzi.append(f"anche su un altro brand ({', '.join(sorted(altri_brand))})")
                risultato = (
                    f"[VERIFICA CODICE '{codice}' SU REDDIT] Lo stesso codice, formato coerente "
                    f"col brand dichiarato '{brand}', compare online " + " e ".join(pezzi) +
                    f" -- probabile codice riciclato da contraffattori, NON e' una prova che il "
                    f"codice sia sbagliato per formato ma che e' condiviso tra prodotti diversi. "
                    f"Fonte: {link_esempio}"
                )
            else:
                risultato = (
                    f"[VERIFICA CODICE '{codice}' SU REDDIT] {len(testi)} menzione/i trovate, "
                    f"nessuna su un brand o una categoria diversi da '{brand}'"
                    + (f"/{categoria_en}" if categoria_en else "") +
                    ". Non e' una conferma di autenticita', solo l'assenza del segnale di "
                    "allarme piu' comune."
                )
    except Exception as e:
        log.warning("Verifica codice Reddit fallita per '%s': %s", codice, e)
        risultato = None  # un errore di rete non deve MAI bloccare la pipeline

    _codici_reddit_cache[chiave] = risultato
    _salva_cache_codici_reddit()
    return risultato


async def verifica_codici_prodotto_reddit(occhio_json, brand, categoria_per_ricerca=None):
    """Punto d'ingresso da process_listing. Va lanciata in parallelo alla
    ricerca comp (asyncio.gather nel chiamante), cosi' non aggiunge secondi
    alla pipeline. Ritorna una stringa da accodare a output_occhi, o stringa
    vuota se non c'e' niente da dire (Reddit non configurato, nessun codice
    leggibile sull'etichetta, o nessun riscontro trovato).

    categoria_per_ricerca e' la stessa categoria (in italiano, es. 'maglia')
    gia' calcolata da estrai_categoria_da_titolo per la ricerca comp --
    viene tradotta in inglese con CATEGORIA_TERMINE_EN per il confronto coi
    risultati Reddit (quasi sempre in inglese)."""
    if not REDDIT_ABILITATO:
        return ""
    codici = _estrai_codici_prodotto_da_occhio(occhio_json)
    if not codici:
        return ""
    categoria_en = CATEGORIA_TERMINE_EN.get((categoria_per_ricerca or "").strip().lower())
    log.info("Verifica codici Reddit: interrogo %s per brand='%s' categoria='%s'.", codici, brand, categoria_en)
    righe = []
    for codice in codici:
        riga = await _reddit_verifica_codice(codice, brand, categoria_en=categoria_en)
        if riga:
            righe.append(riga)
    if righe:
        log.info("Verifica codici Reddit: %d segnal/e trovato/i.", len(righe))
    else:
        log.info("Verifica codici Reddit: nessun segnale (nessun risultato o tutto coerente).")
    if not righe:
        return ""
    return "\n\n--- VERIFICA CODICI PRODOTTO (Reddit) ---\n" + "\n".join(righe)


async def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None, cover_photo_id=None, item_id=None, nome_sarto=None, dettaglio_distintivo=None):
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
    # Ricerca extra per nome del sarto/maker (aggiunta il 2026-09-20, vedi il
    # commento in process_listing su nome_sarto_o_maker): SEMPRE testo libero
    # (VINTED_BRAND_IDS quasi certamente non mappa sartorie/maker minori),
    # niente filtro categoria/materiale sul brand_id perche' non ce n'e' uno
    # -- build_vinted_search_url cade gia' da sola nel ramo search_text puro
    # quando il brand non e' in mappa, e' il comportamento voluto qui.
    url_sarto = None
    if nome_sarto:
        url_sarto, _ = build_vinted_search_url(nome_sarto, categoria, material_per_ricerca, catalog_id)
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
    # la conoscenza generale di Gemini (grounding).
    #
    # AGGIORNAMENTO 2026-09-25: la conversione valuta in
    # _cerca_ebay_sold_via_resellbot / _query_resellbot_raw e' stata
    # corretta (vedi TASSO_USD_EUR). Su richiesta esplicita dell'utente,
    # eBay/Poshmark (via Resellbot, con fallback Google) rientra ora nel
    # fan-out qui sotto come fonte SEMPRE tentata (non condizionale come la
    # ricerca visuale) -- stessi filtri di pulizia gia' usati su Vinted
    # (autoreferenziale, categoria, non il filtro sottolinee: non ha senso
    # concettuale su un mercato USA generico). Vedi _cerca_ebay_sold_con_fallback.
    # Fan-out delle fonti comp con asyncio.gather invece del vecchio
    # ThreadPoolExecutor. Due vantaggi concreti oltre al non bloccare il loop:
    # il timeout e' PER FONTE (prima era complessivo sull'as_completed, quindi
    # una fonte lenta poteva consumare il budget di tutte), e asyncio.wait_for
    # CANCELLA davvero la coroutine scaduta, mentre un thread in timeout
    # restava vivo a consumare connessioni e quota Serper per una risposta
    # che nessuno avrebbe piu' letto.
    TIMEOUT_PER_FONTE_SECONDI = 15

    async def _esegui_fonte(nome, coroutine, timeout=TIMEOUT_PER_FONTE_SECONDI):
        try:
            testo, ok, mappa_url = await asyncio.wait_for(coroutine, timeout=timeout)
            return nome, testo, ok, mappa_url
        except asyncio.TimeoutError:
            return nome, f"  Timeout (fonte troppo lenta, oltre {timeout}s).", False, {}
        except Exception as e:
            return nome, f"  Query fallita: {e}", False, {}

    # Ricerca testuale Vinted (e per sarto): scrape diretto con Serper come
    # riserva dal 2026-09-25, vedi _cerca_vinted_testo_diretto_con_fallback_serper.
    # Timeout piu' ampio delle altre fonti perche' nel caso peggiore fa due
    # tentativi in sequenza (diretto, poi Serper).
    lavori = [_esegui_fonte(
        "vinted", _cerca_vinted_testo_diretto_con_fallback_serper(vinted_url),
        timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI)]
    if tentare_ricerca_visuale:
        lavori.append(_esegui_fonte(
            "vinted_visuale", _recupera_comp_visuali_vinted(item_id, cover_photo_id, brand)))
    if url_sarto:
        lavori.append(_esegui_fonte(
            "vinted_sarto", _cerca_vinted_testo_diretto_con_fallback_serper(url_sarto),
            timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI))
    # eBay/Poshmark via Resellbot (con fallback Google), sempre tentata --
    # reintrodotta nel fan-out il 2026-09-25, vedi commento sopra e
    # _cerca_ebay_sold_con_fallback. Timeout piu' ampio delle fonti Vinted
    # semplici per lo stesso motivo (caso peggiore: Resellbot fino a 12s poi
    # fallback Google fino a 8s, vedi il timeout di _cerca_ebay_sold_via_resellbot
    # alzato da 6 a 12s lo stesso giorno dopo l'analisi dei log di produzione).
    lavori.append(_esegui_fonte(
        "ebay_poshmark",
        _cerca_ebay_sold_con_fallback(brand, categoria, material_per_ricerca, dettaglio_distintivo),
        timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI))

    risultati = {}
    successi = {}
    mappe_url = {}
    for nome, testo, ok, mappa_url in await asyncio.gather(*lavori):
        risultati[nome] = testo
        successi[nome] = ok
        mappe_url[nome] = mappa_url

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

    # Fonte extra per nome sarto/maker (aggiunta il 2026-09-20): pulita con
    # le stesse funzioni delle altre fonti Vinted testuali, TRANNE il filtro
    # sottolinee (_filtra_comp_per_brand_sottolinee con un nome di sartoria/
    # maker minore non in BRAND_SOTTOLINEE_DA_ESCLUDERE e' comunque un no-op,
    # ma non ha senso concettuale applicarlo qui).
    sarto_comp_puliti = None
    fonte_sarto_riuscita = bool(url_sarto) and successi.get("vinted_sarto")
    if fonte_sarto_riuscita:
        sarto_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted_sarto"), query_base)
        sarto_comp_puliti = _filtra_comp_per_categoria(sarto_comp_puliti, categoria)
        log.info(
            "search_comps_completo: comp per nome sarto/maker '%s' DOPO pulizia (item_id=%s) -> %r",
            nome_sarto, item_id, sarto_comp_puliti,
        )

    # Fonte eBay/Poshmark (Resellbot, con fallback Google) -- reintrodotta nel
    # fan-out il 2026-09-25. Pulita con le stesse funzioni delle fonti Vinted
    # testuali TRANNE il filtro sottolinee (_filtra_comp_per_brand_sottolinee
    # e' pensato per collab/sottolinee di maison italiane su Vinted, non ha
    # senso concettuale su un pool eBay/Poshmark USA generico).
    ebay_comp_puliti = None
    fonte_ebay_riuscita = successi.get("ebay_poshmark")
    if fonte_ebay_riuscita:
        ebay_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("ebay_poshmark"), query_base)
        ebay_comp_puliti = _filtra_comp_per_categoria(ebay_comp_puliti, categoria)
        log.info(
            "search_comps_completo: comp eBay/Poshmark DOPO pulizia (item_id=%s, brand=%s) -> %r",
            item_id, brand, ebay_comp_puliti,
        )

    n_fonti = 1 + int(fonte_visuale_riuscita) + int(fonte_sarto_riuscita) + int(fonte_ebay_riuscita)
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
    if url_sarto:
        parti.append(
            f"\n📍 FONTE: VINTED — RICERCA PER NOME SARTORIA/MAKER '{nome_sarto}' (letto dall'etichetta, "
            "diverso dal brand/tessuto dichiarato nell'annuncio -- verifica se il nome del produttore "
            "reale ha un mercato riconoscibile a se', prezzi ASK)\n"
            f"{sarto_comp_puliti or 'Nessun risultato'}"
        )
    if fonte_ebay_riuscita:
        parti.append(
            "\n📍 FONTE: EBAY / POSHMARK (via Resellbot -- prezzi di VENDITA CONFERMATA "
            "quando taggati '[venduto: YYYY-MM-DD]', mercato USA in dollari gia' convertiti "
            "in euro a tasso fisso -- NON il mercato italiano/europeo, usa come riferimento "
            "di prezzo generale del brand, non come comp diretto senza aggiustamento)\n"
            f"{ebay_comp_puliti or 'Nessun risultato'}"
        )

    # Mappa URL comp unita da tutte le fonti che l'hanno popolata (solo
    # scrape diretto, vedi _cerca_vinted_testo_diretto_con_fallback_serper) --
    # usata al rendering finale per riattaccare un link cliccabile al comp
    # che il Cervello cita nel suo JSON, mai passata al prompt (Punto 3,
    # 2026-09-25, esteso a eBay/Poshmark lo stesso giorno). Sull'eventuale,
    # rara collisione di chiave (stesso titolo+prezzo su due fonti diverse)
    # vince l'ultima fonte unita: non ha importanza, l'URL punta comunque a
    # un annuncio con lo stesso titolo/prezzo esatto.
    mappa_url_comp = {}
    for nome in ("vinted", "vinted_visuale", "vinted_sarto", "ebay_poshmark"):
        mappa_url_comp.update(mappe_url.get(nome) or {})

    return (
        "\n".join(parti), serper_ha_funzionato, tentare_ricerca_visuale,
        fonte_visuale_riuscita, mappa_url_comp,
    )
