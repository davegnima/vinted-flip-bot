"""Radar v2 (non moda), modalita' OMBRA: per ogni annuncio del radar calcola la rivendita verosimile dagli annunci simili
in vendita adesso (valore_mercato) e REGISTRA il verdetto; non manda messaggi. Proposta: docs/proposta-radar-v2-2026-10-23.md.

Attivo con RADAR_V2_OMBRA=1. Log `RADAR V2 OMBRA |` ed evento `radar_v2` nel DB. Tetto di sicurezza: RADAR_V2_MAX_GIORNO ricerche
di comparabili al giorno (le stime si riusano per RADAR_V2_CACHE_ORE ore, per marca e testo).
"""
import json
import os
import re
import time
import asyncio
import traceback
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from bot import db, radar_appreso
from bot.comps import _cerca_vinted_testo_diretto, _miniature_comp
from bot.foto import download_image_bytes, optimize_image_bytes
from bot.jev import JEV_COMPS, JEV_FOTO_COMPS, MAX_COMPS_VERIFICA, MAX_FOTO_COMPS, classifica_comparabili, comparabili_simili as simili_jev, comparabili_stesso_modello, confronta_foto_comparabili, giudica_completo, precontrollo_tipo, prezzi_stesso_modello, riconosci_prodotto, stima_paese
from bot.config import SPEDIZIONE_STIMATA_EUR
from bot.qualita_comps import fascia_numero, guasto_nella_descrizione, product_identity, punteggio_comparabili
from bot.spedizione import UNKNOWN, campi_spedizione_da_html, classe_taglia, costo_spedizione, paese_da_html
from bot.logger import log
from bot.radar import RADAR_SPESA_MAX, parola_vietata, radar_in_pausa
from bot.radar_matrice import buy_max, costo_acquisto
from bot.testo import _normalizza_titolo_per_link
from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot.vinted_http import _vinted_get_con_retry
from bot.vinted_scrape import _decodifica_stringa_json
from bot.valore_mercato import comparabili_simili, e_un_pezzo, nomi_candidati, parse_comp, query_alternative, query_comp, solo_usato, stima_mercato, valuta
# ---- fine import ----

RADAR_V2_OMBRA = os.environ.get("RADAR_V2_OMBRA", "0").strip() in ("1", "true", "si")
# Semafori per cui la foto va a Jev (25/10): di default solo il verde. Per la prova si puo' allargare, es. "verde,giallo".
JEV_FOTO_SEMAFORI = {x.strip() for x in os.environ.get("JEV_FOTO_SEMAFORI", "verde").split(",") if x.strip()}
RADAR_V2_MAX_GIORNO = int(os.environ.get("RADAR_V2_MAX_GIORNO", "3000") or 3000)
RADAR_V2_CACHE_ORE = float(os.environ.get("RADAR_V2_CACHE_ORE", "6") or 6)
RADAR_V2_PARALLELO = int(os.environ.get("RADAR_V2_PARALLELO", "2") or 2)
# Pre-filtro per ricerca (31/10): per le ricerche con testo (un prodotto preciso) il prezzo di riferimento si calcola UNA volta
# ogni RADAR_V2_RIF_ORE ore dalla ricerca stessa senza limite di prezzo; un annuncio sopra il prezzo massimo di acquisto
# calcolato sul 75° percentile (generoso, per non perdere affari) non fa piu' una ricerca di comparabili.
RADAR_V2_PREFILTRO = os.environ.get("RADAR_V2_PREFILTRO", "1").strip() in ("1", "true", "si")
RADAR_V2_RIF_ORE = float(os.environ.get("RADAR_V2_RIF_ORE", "8") or 8)
RIF_MIN_COMPARABILI = 6

_visti = set()
# Prova in ombra (31/10): descrizioni e titoli dei simili per Jev, senza richieste in piu' (la pagina e i comparabili si scaricano comunque).
_descrizioni = {}
_info_pagina = {}  # url -> {paese, campi spedizione}: dalla stessa pagina dell'annuncio, zero richieste in piu'
_titoli_simili = {}
_url_comps = {}  # (testo, catalogo) -> {(titolo normalizzato, prezzo 2 decimali): url dell'annuncio} per i link nei messaggi
_comps_simili = {}  # (testo, catalogo) -> [(titolo, prezzo)] per il giudizio di Jev sui singoli comparabili
_RE_DESCRIZIONE = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _descrizione_da_html(html):
    """Descrizione dell'annuncio dalla pagina (stessa regex di scrape_vinted_listing), o None. Pura."""
    m = _RE_DESCRIZIONE.search(html or "")
    if not m:
        return None
    try:
        return _decodifica_stringa_json(m.group(1)) or None
    except Exception:  # noqa: BLE001
        return None
_appreso_caricato = {"si": False}
RADAR_V2_SCALA_MIN = int(os.environ.get("RADAR_V2_SCALA_MIN", "3") or 3)  # sotto questi comparabili si allarga la ricerca (0 = spenta)
_cache = {}  # testo ricerca -> (ts, [prezzi], n_grezzi)
_riferimenti = {}  # nome ricerca -> (ts, stima o None)
_conteggio = {"giorno": None, "n": 0}
_sem = asyncio.Semaphore(RADAR_V2_PARALLELO)


_MARCHI_ID = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dati", "brand_ids.json"))).get("marchi", {})


def id_marchio(brand):
    """Id Vinted del marchio dalla tabella (es. 'dyson' -> 291992), o None se non c'e'."""
    return _MARCHI_ID.get((brand or "").strip().lower())


def marca_dal_titolo(titolo, brand=None):
    """Marca da usare per i comparabili: se il titolo nomina un marchio noto diverso da quello del tracker, vince il titolo
    (la ricerca 'V2 sony' porta anche cuffie Bose: cercare i comparabili 'sony' darebbe prezzi sbagliati). Pura."""
    t = " " + re.sub(r"\s+", " ", re.sub(r"[&+]", " ", (titolo or "").lower())) + " "
    gia = (brand or "").strip().lower()
    for nome in sorted(_MARCHI_ID, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(nome)}(?![\w])", t):
            return brand if nome == gia else nome
    return brand


def url_comparabili(testo, catalogo=None, brand=None):
    """Ricerca dei simili su Vinted: parole chiave + categoria (catalog[]) + marchio (brand_ids[]), quando noti.
    Senza categoria una ricerca di 'ricoh r1' pesca qualsiasi fotocamera (25/10)."""
    categoria = f"&catalog[]={catalogo}" if catalogo else ""
    marchio = f"&brand_ids[]={id_marchio(brand)}" if id_marchio(brand) else ""
    return f"https://www.vinted.it/catalog?search_text={quote(testo)}{categoria}{marchio}&order=newest_first"


def testo_ricerca(query_url):
    """Parole chiave (search_text) dell'URL di ricerca del tracker, '' se assenti. Pura."""
    for k, v in parse_qsl(urlsplit(query_url or "").query):
        if k == "search_text":
            return v.strip()
    return ""


def url_senza_prezzo(query_url):
    """URL della ricerca del tracker senza limiti di prezzo ne' pagina: il riferimento deve vedere tutto il mercato. Pura."""
    parti = urlsplit(query_url)
    resto = [(k, v) for k, v in parse_qsl(parti.query) if k not in ("price_to", "price_from", "page")]
    return urlunsplit((parti.scheme, parti.netloc, parti.path, urlencode(resto), ""))


def limite_acquisto(stima):
    """Prezzo massimo di acquisto che puo' dare margine e ROI minimi, calcolato sul 75° percentile (generoso). Pura."""
    return buy_max(stima["p75"], SPEDIZIONE_STIMATA_EUR) if stima else None


async def _riferimento_ricerca(nome, query_url, adesso=None):
    """Stima di mercato della ricerca (cache RADAR_V2_RIF_ORE ore), None se non disponibile o con pochi comparabili."""
    adesso = adesso or time.time()
    voce = _riferimenti.get(nome)
    if voce and adesso - voce[0] < RADAR_V2_RIF_ORE * 3600:
        return voce[1]
    if not _entro_il_tetto(adesso):
        return None
    async with _sem:
        risposta, ok, _mappa = await _cerca_vinted_testo_diretto(url_senza_prezzo(query_url))
    stima = None
    if ok:
        # niente filtro sulle parole della ricerca: i titoli hanno sinonimi (PS5 / PlayStation 5) e la ricerca e' gia' stretta
        comps = [(t, p) for t, p in solo_usato(parse_comp(risposta)) if not e_un_pezzo(t)]
        stima = stima_mercato([p for _, p in comps], min_n=RIF_MIN_COMPARABILI)
    # una ricerca fallita si ritenta dopo un'ora, non subito
    _riferimenti[nome] = (adesso if stima else adesso - (RADAR_V2_RIF_ORE - 1) * 3600, stima)
    log.info("RADAR V2 RIFERIMENTO | ricerca=%s | n=%s | p25=%s | mediana=%s | p75=%s | limite=%s", nome,
             stima and stima["n"], stima and stima["p25"], stima and stima["mediana"], stima and stima["p75"], limite_acquisto(stima))
    return stima


def _entro_il_tetto(adesso=None):
    """True se si puo' fare un'altra ricerca di comparabili oggi (UTC); conta la chiamata."""
    giorno = time.strftime("%Y-%m-%d", time.gmtime(adesso or time.time()))
    if _conteggio["giorno"] != giorno:
        _conteggio.update(giorno=giorno, n=0)
    if _conteggio["n"] >= RADAR_V2_MAX_GIORNO:
        return False
    _conteggio["n"] += 1
    return True


_RE_CATALOGO_ANNUNCIO = re.compile(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"')


def _catalogo_da_html(html):
    """Id della categoria dal breadcrumb della pagina annuncio (stessa regex di scrape_vinted_listing). Pura."""
    trovati = _RE_CATALOGO_ANNUNCIO.findall(html or "")
    return trovati[-1] if trovati else None


async def _catalogo_annuncio(url):
    """Id della categoria Vinted dell'annuncio, o None se la pagina non si legge. Una sola richiesta a Vinted (25/10):
    scrape_vinted_listing ritentava fino a 3 volte e rifaceva la pagina leggera, e con i 403 di adesso era solo rumore
    di richieste. Senza categoria la ricerca resta sul testo."""
    try:
        resp = await _vinted_get_con_retry(url, timeout=10, max_retries=1)
        if resp is None:
            return None
        _info_pagina[url] = {"paese": paese_da_html(resp.text), "campi": campi_spedizione_da_html(resp.text)}
        if len(_info_pagina) > 500:
            _info_pagina.clear()
        desc = _descrizione_da_html(resp.text)
        if desc:
            if len(_descrizioni) > 500:
                _descrizioni.clear()
            _descrizioni[url] = desc
        return _catalogo_da_html(resp.text)
    except Exception:  # noqa: BLE001 - senza categoria la ricerca resta solo sul testo
        return None


async def _prezzi_simili(testo, titolo, prezzo, brand=None, catalogo=None):
    """(prezzi richiesti di annunci simili usati, n grezzi, dalla_cache) o (None, 0, False) se non disponibile."""
    adesso = time.time()
    chiave = (testo, catalogo)
    voce = _cache.get(chiave)
    if voce and adesso - voce[0] < RADAR_V2_CACHE_ORE * 3600:
        return voce[1], voce[2], True
    if not _entro_il_tetto(adesso):
        return None, 0, False
    async with _sem:
        risposta, ok, mappa = await _cerca_vinted_testo_diretto(url_comparabili(testo, catalogo, brand))
    if not ok:
        return None, 0, False
    comps = parse_comp(risposta)
    usati = [(t, p) for t, p in comparabili_simili(solo_usato(comps), testo, brand) if not (t == titolo and abs(p - prezzo) < 0.01)]
    prezzi = [p for _, p in usati]
    _cache[chiave] = (adesso, prezzi, len(comps))
    if len(_titoli_simili) > 500:
        _titoli_simili.clear()
        _comps_simili.clear()
        _url_comps.clear()
    _url_comps[chiave] = mappa or {}
    _titoli_simili[chiave] = [t for t, _ in usati]
    _comps_simili[chiave] = list(usati)
    return prezzi, len(comps), False


def link_comparabili(coppie, mappe, n=4):
    """[(titolo, prezzo, url)] dei comparabili con un link noto, i `n` piu' vicini alla mediana dei prezzi (quelli che reggono
    la stima, non gli estremi). `mappe` = dizionari {(titolo normalizzato, prezzo 2f): url}. Pura (richiesta dell'utente, 01/11)."""
    if not coppie:
        return []
    prezzi = sorted(p for _, p in coppie)
    mediana = prezzi[len(prezzi) // 2]
    out, visti = [], set()
    for t, p in sorted(coppie, key=lambda c: abs(c[1] - mediana)):
        chiave = (_normalizza_titolo_per_link(t), f"{p:.2f}")
        url = next((m[chiave] for m in mappe if m and chiave in m), None)
        if url and url not in visti:
            visti.add(url)
            out.append((t, p, url))
        if len(out) >= n:
            break
    return out


def id_da_url_comp(url):
    """Id numerico dell'annuncio da 'https://www.vinted.it/items/<ID>...'. None se non c'e'. Pura."""
    m = re.search(r"/items/(\d+)", url or "")
    return m.group(1) if m else None


async def _foto_comparabili(link_comps):
    """Byte delle miniature (al massimo MAX_FOTO_COMPS) dei comparabili con link noto, ridotte a 512 px. Lista vuota se mancano."""
    urls = [u for u in (_miniature_comp.get(id_da_url_comp(c[2])) for c in link_comps) if u][:MAX_FOTO_COMPS]
    scaricate = await asyncio.gather(*(download_image_bytes(u) for u in urls), return_exceptions=True)
    return [await asyncio.to_thread(optimize_image_bytes, b, 512) for b in scaricate if isinstance(b, bytes) and b]


def testi_piu_larghi(testo, brand=None):
    """Ricerca piu' corta da provare quando i comparabili sono pochi: marca + 2 parole (mai la sola marca). Pura."""
    parole = (testo or "").split()
    b = (brand or "").lower().split()
    resto = parole[len(b):] if b and parole[:len(b)] == b else parole
    out = []
    if len(resto) > 2:
        out.append(" ".join(b + resto[:2]))
    # Niente ricerca con la sola marca (01/11): "nintendo" per uno Skylanders dava 14 console da 160-220 EUR come comparabili.
    return [t for i, t in enumerate(out) if t and t != testo and t not in out[:i]]


async def _verifica_comparabili(titolo, prezzo, brand, catalogo, testo, descrizione=None):
    """Cerca comparabili SERI: Jev giudica ogni titolo (stesso modello / simile / altro); se gli stessi modelli sono meno di 3 si
    provano le ricerche dalla sigla del modello (query_alternative) e si giudica l'insieme. Ritorna (info, prezzi dello stesso modello)
    o (None, []) se non c'e' niente da giudicare."""
    pool = list(_comps_simili.get((testo, catalogo)) or [])
    usate = [testo]
    ok = []
    etichette = None
    n_ut = 0  # comparabili utilizzabili: stesso modello + simili della stessa famiglia
    if len(pool) >= 3:
        etichette = await asyncio.to_thread(classifica_comparabili, titolo, [t for t, _ in pool], descrizione)
        ok = prezzi_stesso_modello(pool, etichette)
        n_ut = len(ok) + len(simili_jev(pool, etichette))
    # Se i comparabili veri restano pochi si cerca ancora (richiesta dell'utente, 01/11): prima dalla sigla del modello,
    # poi con ricerche piu' larghe (marca + 2 parole); Jev rigiudica ogni titolo. Al massimo 3 ricerche in piu'.
    ricerche = []
    if n_ut < 3:
        # Riconoscimento del prodotto dal titolo (01/11): Jev sceglie il nome del prodotto, si cerca con marca + categoria + quel nome,
        # poi con la sua prima parola ("skylanders swap force", poi "skylanders"); mai la sola marca.
        riconosciuto = await asyncio.to_thread(riconosci_prodotto, titolo, nomi_candidati(titolo, brand), descrizione)
        if riconosciuto:
            parole = riconosciuto[0].split()
            ricerche += [" ".join(([brand.lower()] if brand and brand.lower() not in riconosciuto[0] else []) + parole[:3]), parole[0]]
    ricerche = list(dict.fromkeys(ricerche + query_alternative(titolo, brand) + testi_piu_larghi(testo, brand)))
    ricerche = [q for q in ricerche if q and q.lower() != (brand or "").lower() and q not in usate][:4]
    for q in ricerche:
        if n_ut >= 3:
            break
        await _prezzi_simili(q, titolo, prezzo, brand, catalogo)
        nuovi = [c for c in (_comps_simili.get((q, catalogo)) or []) if c not in pool]
        if not nuovi:
            continue
        usate.append(q)
        pool = (pool + nuovi)[:MAX_COMPS_VERIFICA]
        if len(pool) >= 3:
            etichette = await asyncio.to_thread(classifica_comparabili, titolo, [t for t, _ in pool], descrizione)
            ok = prezzi_stesso_modello(pool, etichette)
            n_ut = len(ok) + len(simili_jev(pool, etichette))
    if not etichette:
        return None, []
    stessi = comparabili_stesso_modello(pool, etichette)
    simili = simili_jev(pool, etichette)
    # Buon senso (01/11): con meno di 3 "stesso modello" si aggiungono i "simile" (stessa famiglia) se insieme arrivano a 3 o piu';
    # mai gli "altro". Con simili dentro il verde non e' possibile (vedi analizza).
    usati = stessi if len(stessi) >= 3 else (stessi + simili if len(stessi) + len(simili) >= 3 else stessi)
    link = link_comparabili(usati, [_url_comps.get((q, catalogo)) for q in usate])
    n_simili_usati = len(usati) - len(stessi)
    return {"n_giudicati": len(etichette), "n_stesso": len(stessi), "n_simili": n_simili_usati, "n_usabili": len(usati),
            "query": usate, "link": link}, [p for _t, p in usati]


def _rosso(motivo, n=0):
    """Risultato per un annuncio scartato: il messaggio mostra comunque il motivo dei comparabili."""
    return {"semaforo": "rosso", "rivendita": None, "margine": None, "roi": None, "n": n, "motivo": motivo,
            "jev": None, "jev_conf": None}


_saltati = {}


def _log_saltato(motivo, url):
    """Riga di log per gli annunci che il radar v2 non valuta (31/10): prima erano ritorni silenziosi. Una riga ogni 20 per motivo."""
    n = _saltati[motivo] = _saltati.get(motivo, 0) + 1
    if n == 1 or n % 20 == 0:
        log.info("RADAR V2 SALTATO | motivo=%s | n=%s | url=%s", motivo, n, (url or "-")[:80])


async def analizza(parsed, url, foto=None, query_url=None):
    """Valuta un annuncio del radar con i comparabili, chiede il giudizio di Jev e registra il verdetto.
    Ritorna dict {semaforo, rivendita, margine, roi, n, jev, jev_conf} o None. Mai eccezioni verso il chiamante."""
    if not RADAR_V2_OMBRA or radar_in_pausa():
        _log_saltato("ombra_spenta" if not RADAR_V2_OMBRA else "pausa_notturna", url)
        return
    try:
        item_id = _estrai_item_id_da_url(url)
        if not item_id or item_id in _visti:
            _log_saltato("senza_id" if not item_id else "gia_visto", url)
            return
        _visti.add(item_id)
        if len(_visti) > 20000:
            _visti.clear()
        titolo = parsed.get("title") or ""
        prezzo = _a_float(parsed.get("price"), None)
        brand = parsed.get("brand")
        base = {"titolo": titolo[:120], "prezzo": prezzo, "brand": brand}
        if prezzo is None or prezzo <= 0 or (RADAR_SPESA_MAX and prezzo > RADAR_SPESA_MAX):
            _log_saltato("prezzo_assente" if prezzo is None else f"prezzo_fuori:{prezzo:g}", url)
            return
        if prezzo <= 1:
            # 31/10: "Bugaboo Fox 5 ... 1000€ VB" a 1 EUR: prezzo segnaposto, non un affare
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "prezzo_segnaposto"})
            return _rosso("prezzo_segnaposto")
        vietata = parola_vietata(titolo)
        if vietata:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "parola_vietata:" + vietata})
            return _rosso("parola_vietata:")
        pezzo = e_un_pezzo(titolo)
        if pezzo:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "pezzo_o_accessorio:" + pezzo})
            return _rosso("pezzo_o_accessorio:")
        brand = marca_dal_titolo(titolo, brand)
        testo = query_comp(titolo, brand)
        if len(testo.split()) < 2:
            # titolo di una parola ("Dyson"): il modello non si capisce, i comparabili sarebbero ricambi e accessori
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "titolo_generico", "q": testo})
            return _rosso("titolo_generico")
        if not _appreso_caricato["si"]:
            _appreso_caricato["si"] = True
            radar_appreso.carica_dal_db()
        fam = testo
        limite_appreso = radar_appreso.da_saltare(fam, prezzo)
        if limite_appreso is not None:
            # filtro appreso (31/10): la famiglia non ha mai dato margine a questo prezzo, niente richiesta a Vinted
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "famiglia_senza_margine", "fam": fam, "limite": limite_appreso})
            log.info("RADAR V2 APPRESO SALTATO | item=%s | famiglia=%s | prezzo=%s | limite=%.0f | ricerca=%s | titolo=%s",
                     item_id, fam, prezzo, limite_appreso, parsed.get("query_name") or "-", titolo[:60])
            return _rosso("famiglia_senza_margine")
        if RADAR_V2_PREFILTRO and query_url and parsed.get("query_name") and testo_ricerca(query_url):
            rif = await _riferimento_ricerca(parsed["query_name"], query_url)
            limite = limite_acquisto(rif)
            if limite is not None and prezzo > limite:
                db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "sopra_riferimento", "limite": limite, "n": rif["n"]})
                log.info("RADAR V2 OMBRA | item=%s | semaforo=rosso | ok=False | motivo=sopra_riferimento | prezzo=%s | limite=%s | n=%s | ricerca=%s",
                         item_id, prezzo, limite, rif["n"], parsed["query_name"])
                return _rosso("sopra_riferimento", rif["n"])
        # Ricambio, lotto, replica o rotto dal titolo (01/11): niente ricerca di comparabili (ne' banda ne' chiamate in piu').
        scarto_tipo = await asyncio.to_thread(precontrollo_tipo, titolo)
        if scarto_tipo:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "jev_tipo:" + scarto_tipo})
            log.info("RADAR V2 OMBRA | item=%s | semaforo=rosso | ok=False | motivo=jev_tipo:%s | prezzo=%s | ricerca=%s | titolo=%s",
                     item_id, scarto_tipo, prezzo, parsed.get("query_name") or "-", titolo[:60])
            return _rosso("jev_tipo:" + scarto_tipo)
        catalogo = await _catalogo_annuncio(url)
        frase_guasto = guasto_nella_descrizione(_descrizioni.get(url))
        if frase_guasto:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "descrizione_guasto", "frase": frase_guasto})
            log.info("RADAR V2 OMBRA | item=%s | semaforo=rosso | ok=False | motivo=descrizione_guasto(%s) | prezzo=%s | ricerca=%s | titolo=%s",
                     item_id, frase_guasto, prezzo, parsed.get("query_name") or "-", titolo[:60])
            return _rosso("descrizione_guasto")
        info_pag = _info_pagina.pop(url, None) or {}
        paese = info_pag.get("paese")
        paese_fonte = "pagina" if paese else None
        if not paese:
            # Paese non nell'HTML: lo stima Jev da titolo e descrizione (01/11, richiesta dell'utente); resta una stima dichiarata.
            stimato = await asyncio.to_thread(stima_paese, titolo, _descrizioni.get(url))
            if stimato:
                paese, paese_fonte = stimato[0], "jev"
        classe = classe_taglia(titolo)
        sped_eur, sped_stato = costo_spedizione(paese, classe)
        log.info("SPEDIZIONE PAGINA | item=%s | paese=%s(%s) | classe=%s | stato=%s | eur=%s | campi=%s", item_id, paese or "-", paese_fonte or "-", classe, sped_stato,
                 sped_eur, ";".join(f"{k}={x}" for k, x in info_pag.get("campi") or []) or "-")
        prezzi, n_grezzi, dalla_cache = await _prezzi_simili(testo, titolo, prezzo, brand, catalogo)
        if prezzi is None:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "comparabili_non_disponibili", "q": testo})
            return _rosso("comparabili_non_disponibili")
        # Scala di allargamento (31/10): con pochi comparabili si riprova con ricerche piu' corte (modello, poi solo marca nella
        # stessa categoria). Stima meno precisa: il semaforo non supera il giallo (niente suono).
        allargata = None
        if len(prezzi) < RADAR_V2_SCALA_MIN:
            for passo, testo_largo in enumerate(testi_piu_larghi(testo, brand), 1):
                p2, g2, _c2 = await _prezzi_simili(testo_largo, titolo, prezzo, brand, catalogo)
                if p2 and len(p2) > len(prezzi):
                    prezzi, n_grezzi, allargata, testo = p2, g2, passo, testo_largo
                if len(prezzi) >= RADAR_V2_SCALA_MIN:
                    break
        stima = stima_mercato(prezzi, min_n=2)
        v = valuta(prezzo, stima, spedizione_eur=sped_eur)
        limite = limite_acquisto(stima)
        radar_appreso.registra(fam, limite, len(prezzi), allargata)
        if allargata and v.get("semaforo") == "verde":
            v["semaforo"] = "giallo"
        dati = {**base, "q": testo, "fam": fam, "limite": limite, "n_grezzi": n_grezzi, "n_usati": len(prezzi), "cache": dalla_cache, "allargata": allargata, **v}
        log.info("RADAR V2 OMBRA | item=%s | semaforo=%s | ok=%s | motivo=%s | prezzo=%s | rivendita=%s | margine=%s | roi=%s | n=%s | grezzi=%s | largo=%s | aff=%s | cache=%s | q=%s | ricerca=%s | titolo=%s",
                 item_id, v["semaforo"], v["ok"], v["motivo"], prezzo, v.get("rivendita"), v.get("margine"), v.get("roi"), len(prezzi),
                 n_grezzi, allargata or 0, v.get("affidabilita"), int(bool(dalla_cache)), testo, parsed.get("query_name") or "-", titolo[:60])
        # Comparabili seri (01/11): Jev giudica ogni comparabile e, se gli stessi modelli sono pochi, si cerca dalla sigla del modello.
        # La rivendita finale e' sul solo "stesso modello"; un rosso per pochi comparabili puo' diventare giallo (mai verde, niente suono).
        verificata = None
        titoli_jev = _titoli_simili.get((testo, catalogo))
        if JEV_COMPS and (v.get("semaforo") in ("verde", "giallo") or v.get("motivo") == "pochi_comparabili"):
            info, ok_prezzi = await _verifica_comparabili(titolo, prezzo, brand, catalogo, testo, _descrizioni.get(url))
            if info:
                v_ver = valuta(prezzo, stima_mercato(ok_prezzi, min_n=3), spedizione_eur=sped_eur)
                verificata = {**info, "rivendita": v_ver.get("rivendita"), "margine": v_ver.get("margine"), "roi": v_ver.get("roi"),
                              "semaforo": v_ver.get("semaforo")}
                log.info("RADAR V2 VERIFICATA | item=%s | prima=%s rivendita=%s | dopo=%s rivendita=%s margine=%s | stesso=%s/%s | q=%s | titolo=%s",
                         item_id, v["semaforo"], v.get("rivendita"), v_ver.get("semaforo"), v_ver.get("rivendita"), v_ver.get("margine"),
                         info["n_stesso"], info["n_giudicati"], "+".join(info["query"]), titolo[:60])
                if info["n_usabili"] >= 3:
                    cap = v.get("semaforo") != "verde" or allargata or len(info["query"]) > 1 or info["n_simili"] > 0
                    v = {**v, **v_ver}
                    if cap and v.get("semaforo") == "verde":
                        v["semaforo"] = "giallo"
                    prezzi, titoli_jev = ok_prezzi, None
        # Costo totale (01/11): con spedizione sconosciuta il semaforo non supera il giallo (niente suono); il verde dipende dal costo totale.
        v["spedizione_eur"], v["spedizione_stato"] = sped_eur, sped_stato
        v["costo_totale"] = round(costo_acquisto(prezzo, sped_eur), 2)
        if sped_stato == UNKNOWN and v.get("semaforo") == "verde":
            v["semaforo"] = "giallo"
        # Link dei comparabili nei messaggi (01/11): quelli verificati se ci sono, altrimenti i grezzi della ricerca usata.
        link_comps = []
        if v.get("semaforo") in ("verde", "giallo"):
            if verificata and verificata["n_usabili"] >= 3:
                link_comps = verificata.get("link") or []
            else:
                link_comps = link_comparabili(_comps_simili.get((testo, catalogo)) or [], [_url_comps.get((testo, catalogo))])
        # Qualita' dei comparabili (01/11, solo misura): pool usato per la stima finale e identita' del prodotto.
        pool_q = list(_comps_simili.get((testo, catalogo)) or [])
        ver_ok = verificata and verificata["n_usabili"] >= 3
        qualita = punteggio_comparabili(pool_q if not ver_ok else [(t, p) for t, p, _u in (verificata.get("link") or [])] or pool_q,
                                        verificata["n_stesso"] if verificata else None, verificata["n_giudicati"] if verificata else None)
        qualita["n"] = len(prezzi)
        qualita["fascia"] = fascia_numero(len(prezzi))
        identita = product_identity(titolo, brand, catalogo, "+".join(verificata["query"]) if verificata else testo)
        log.info("RADAR V2 QUALITA | item=%s | punteggio=%s | fascia=%s | n=%s | stesso=%s | dup=%s | disp=%s | codice=%s | titolo=%s", item_id,
                 qualita["punteggio"], qualita["fascia"], qualita["n"], qualita["quota_stesso"], qualita["duplicati"], qualita["dispersione"],
                 identita["codice_modello"], titolo[:60])
        # Prova foto (25/10): la foto va a Jev solo con i semafori di JEV_FOTO_SEMAFORI (di default il verde).
        foto_jev = foto if v.get("semaforo") in JEV_FOTO_SEMAFORI else None
        jev, jev_conf, jev_simili, jev_motivo = await asyncio.to_thread(
            giudica_completo, titolo, prezzo, prezzi, v.get("rivendita"), foto_jev, _descrizioni.pop(url, None), titoli_jev)
        if jev:
            log.info("RADAR V2 JEV | item=%s | giudizio=%s | confidenza=%s | simili=%s(%s) | motivo=%s | largo=%s | n=%s | titolo=%s", item_id, jev,
                     jev_conf, jev_simili[0] if jev_simili else "-", jev_simili[1] if jev_simili else "-", jev_motivo[0] if jev_motivo else "-", allargata or 0,
                     len(prezzi), titolo[:60])
        # Foto dei comparabili (01/11), solo ombra: foto annuncio contro 3 miniature; nessun effetto sull'esito.
        jev_foto_comps = None
        if JEV_FOTO_COMPS and foto and link_comps and v.get("semaforo") in ("verde", "giallo"):
            miniature = await _foto_comparabili(link_comps)
            if miniature:
                jev_foto_comps = await asyncio.to_thread(confronta_foto_comparabili, titolo, foto, miniature)
                log.info("RADAR V2 FOTO COMPS | item=%s | semaforo=%s | byte=%s | esito=%s | titolo=%s", item_id, v.get("semaforo"),
                         sum(len(m) for m in miniature), jev_foto_comps, titolo[:60])
                # Buon senso (01/11, caso Sony H1: 11 'simili' da 190-270 EUR per una compatta da 30): se la stima poggia anche sui
                # simili e la maggior parte delle foto dei comparabili e' 'diversa' (conf >= 0,5), i comparabili non sono verificati: rosso.
                if verificata and verificata["n_simili"] > 0 and jev_foto_comps:
                    diversi = sum(1 for sc, cf in jev_foto_comps if sc == "diverso" and (cf or 0) >= 0.5)
                    if diversi * 2 > len(jev_foto_comps):
                        v = {**v, "semaforo": "rosso", "ok": False, "motivo": "comparabili_diversi"}
                        log.info("RADAR V2 COMPARABILI DIVERSI | item=%s | diversi=%s/%s | titolo=%s", item_id, diversi, len(jev_foto_comps), titolo[:60])
        db.scrivi_evento("radar_v2", item_id, brand, {**dati, "qualita": qualita, "identita": identita, "paese": paese, "classe": classe, "paese_fonte": paese_fonte, "spedizione_eur": sped_eur, "spedizione_stato": sped_stato,
                                                      "costo_totale": v.get("costo_totale"), "jev_foto_comps": jev_foto_comps, "verificata": verificata, "link_comps": [list(c) for c in link_comps], "jev": jev, "jev_conf": jev_conf,
                                                      "jev_simili": jev_simili[0] if jev_simili else None,
                                                      "jev_simili_conf": jev_simili[1] if jev_simili else None,
                                                      "jev_motivo": jev_motivo[0] if jev_motivo else None,
                                                      "jev_motivo_frase": jev_motivo[1] if jev_motivo else None})
        return {"semaforo": v.get("semaforo"), "rivendita": v.get("rivendita"), "margine": v.get("margine"),
                "spedizione_eur": sped_eur, "spedizione_stato": sped_stato, "costo_totale": v.get("costo_totale"), "paese": paese, "paese_fonte": paese_fonte,
                "qualita": qualita, "richiesto_mediano": v.get("richiesto_mediano"), "vendita_rapida": v.get("vendita_rapida"), "calibrazione": v.get("calibrazione"),
                "roi": v.get("roi"), "n": len(prezzi), "n_grezzi": n_grezzi, "allargata": allargata, "motivo": v.get("motivo"),
                "jev": jev, "jev_conf": jev_conf, "jev_motivo": jev_motivo[0] if jev_motivo else None,
                "jev_motivo_frase": jev_motivo[1] if jev_motivo else None, "verificata": verificata, "link_comps": link_comps}
    except Exception:
        log.warning("Radar v2 ombra: annuncio non valutato:\n%s", traceback.format_exc())
