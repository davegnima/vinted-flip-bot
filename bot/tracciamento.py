"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import time
import asyncio
import traceback
from datetime import datetime, timezone

import httpx

from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot.fair_value import _jsonl_append, _jsonl_read
from bot import db
from bot.tempi import _parse_created_at_dt
from bot.vinted_http import _vinted_get_con_retry
from bot.categorie import estrai_categoria_da_titolo
from bot.logger import log
# ---- fine import ----
# ---------------------------------------------------------------------------
# TRACCIAMENTO VENDITE (richiesto dall'utente il 2026-10-02/03)
# ---------------------------------------------------------------------------
# Serve a istruire la stima di fair price e l'urgenza SENZA che l'utente compri o rivenda nulla: per ogni
# annuncio che arriva a un verdetto si controlla se e quanto in fretta viene venduto. Criterio dell'utente:
# AFFARE se venduto entro 5 min, MEDIO AFFARE entro 15 min, NORMALE entro 1h, NON AFFARE se dopo 1h e'
# ancora invenduto (e dopo 1h non si ricontrolla piu'). Una pagina venduta NON sparisce: resta online
# (HTTP 200) con la barra "Venduto" e can_buy=false. La pagina non contiene istanti assoluti (verificato
# con /venduto) e l'utente ha vietato le API Vinted: la velocita' e' una fascia fra controlli, misurata da
# t0 = arrivo del messaggio del tracker (il momento piu' vicino alla pubblicazione che il bot conosce).
#  - al primo scrape (~2-3s da t0) lo stato e' gia' letto -> "istantaneo" (GIA_VENDUTO);
#  - serie di controlli a 15s, 30s, 1min, 5min, 15min, 60min da t0, fermata alla prima vendita;
#  - nessun controllo per gli annunci scartati prima del verdetto (SKIP_*, errore del Cervello).
# Solo raccolta: nessuna decisione cambia (SKIP_GIA_VENDUTI=1 interrompe l'analisi dei gia' venduti).
TRACCIAMENTO_ATTIVO = os.environ.get("TRACCIAMENTO_ATTIVO", "1").strip() == "1"
TRACCIAMENTO_FILE = os.environ.get("TRACCIAMENTO_FILE", "/data/tracciamento_esiti.jsonl")
SKIP_GIA_VENDUTI = os.environ.get("SKIP_GIA_VENDUTI", "0").strip() == "1"
TRACCIAMENTO_SERIE_SECONDI = (15, 30, 60, 300, 900, 3600)
_TRACC_FASCE = ((15, "<=15s"), (30, "<=30s"), (60, "<=1min"), (300, "<=5min"), (900, "<=15min"), (3600, "<=60min"))
_tracc_item_visti = set()  # annunci gia' registrati (caricato all'avvio da main)
_tracc_stop = set()  # annunci venduti, rimossi o scartati prima del verdetto: la serie si ferma
_tracc_esiti = {}  # item_id -> (esito, target): lo valorizza _log_esito, lo legge la serie nei log
_tracc_sem = asyncio.Semaphore(8)

_TRACC_SEGNALI_RE = {
    # La pagina incorpora i dati come JSON dentro una stringa: le virgolette possono arrivare
    # escapate (\\"chiave\\":valore), quindi il backslash prima di ogni virgoletta e' opzionale.
    chiave: re.compile(r'\\?"' + chiave + r'\\?"\s*:\s*\\?("?[A-Za-z0-9_.-]{1,30}"?)')
    for chiave in ("is_closed", "is_reserved", "is_hidden", "is_draft", "can_buy", "item_closing_action")
}
# Preferiti e visualizzazioni (richiesto dall'utente il 2026-10-04): segnale di domanda da leggere nello scrape e in
# ogni ricontrollo lampo. Nomi dei campi incorporati nella pagina non verificati su una pagina reale: si provano
# le varianti piu' comuni; se nessuna c'e' il valore resta assente (lo si vede dai log).
_TRACC_CONTEGGI_RE = {
    "preferiti": re.compile(r'\\?"(?:favou?rite_count|favou?rites_count|favou?riteCount)\\?"\s*:\s*(\d{1,7})'),
    "visite": re.compile(r'\\?"(?:view_count|viewCount|views_count)\\?"\s*:\s*(\d{1,8})'),
}
_TRACC_PREZZO_RES = (
    re.compile(r'property="product:price:amount"\s+content="([\d.,]+)"'),
    re.compile(r'\\?"price\\?"\s*:\s*\{[^{}]{0,80}?\\?"amount\\?"\s*:\s*\\?"?([\d.]+)'),
    re.compile(r'itemprop="price"[^>]*content="([\d.,]+)"'),
)
_TRACC_AVAILABILITY_RE = re.compile(r"schema\.org/(InStock|OutOfStock|SoldOut|Discontinued)")
_TRACC_BARRA_RE = re.compile(r">\s*Venduto\s*<")


def _tracc_scrivi(record):
    db.scrivi_evento("tracciamento", record.get("item_id"), record.get("brand"), dict(record))
    return _jsonl_append(TRACCIAMENTO_FILE, record, "Tracciamento")


def importa_tracciamento_jsonl():
    """Una tantum: se la tabella eventi non ha ancora righe di tracciamento, ci copia lo storico del file JSONL
    (che resta dov'e': si scrive in entrambi). Ritorna quante righe ha importato."""
    if db.conta_eventi("tracciamento"):
        return 0
    n = 0
    for r in _jsonl_read(TRACCIAMENTO_FILE, "Tracciamento"):
        if db.scrivi_evento("tracciamento", r.get("item_id"), r.get("brand"), r, ts=r.get("ts")):
            n += 1
    return n


def _tracc_estrai_segnali(html_pagina):
    """Segnali grezzi di stato/prezzo dalla pagina annuncio. Pura, testabile."""
    segnali = {}
    for chiave, rx in _TRACC_SEGNALI_RE.items():
        m = rx.search(html_pagina)
        if m:
            segnali[chiave] = m.group(1).strip('"')
    for chiave, rx in _TRACC_CONTEGGI_RE.items():
        m = rx.search(html_pagina)
        if m:
            segnali[chiave] = int(m.group(1))
    m = _TRACC_AVAILABILITY_RE.search(html_pagina)
    if m:
        segnali["availability"] = m.group(1)
    # Verificato il 2026-10-03: la barra verde "Venduto" e' il contenuto di un elemento della pagina.
    if _TRACC_BARRA_RE.search(html_pagina):
        segnali["barra_venduto"] = True
    prezzo = None
    for rx in _TRACC_PREZZO_RES:
        m = rx.search(html_pagina)
        if m:
            prezzo = _a_float(m.group(1).replace(",", "."), None)
            if prezzo is not None:
                break
    return segnali, prezzo


def _tracc_stato(http_status, segnali):
    """Unico classificatore dello stato: venduto / rimosso / prenotato / attivo / n.d. Verificato il
    2026-10-03 con /venduto su un annuncio venduto e uno attivo: venduto = HTTP 200 + barra "Venduto" +
    can_buy=false; attivo = can_buy=true. Con can_buy=true la barra non conta (potrebbe essere il badge di
    un altro articolo in pagina)."""
    segnali = segnali or {}
    if http_status in (404, 410):
        return "rimosso"
    can_buy = str(segnali.get("can_buy", "")).lower()
    if (str(segnali.get("is_closed", "")).lower() == "true"
            or segnali.get("availability") in ("OutOfStock", "SoldOut", "Discontinued")
            or (segnali.get("barra_venduto") and can_buy != "true")):
        return "venduto"
    if str(segnali.get("is_reserved", "")).lower() == "true":
        return "prenotato"
    if can_buy == "true":
        return "attivo"
    if http_status is None or http_status == 200:
        return "attivo?"
    return "n.d."


def _tracc_bucket(offset_s):
    """Fascia di vendita dato l'offset (secondi da t0) del primo controllo che ha trovato il venduto. Pura."""
    for limite, etichetta in _TRACC_FASCE:
        if offset_s <= limite:
            return etichetta
    return ">60min"


def _tracc_classe(offset_s, stato):
    """Classe di mercato (criterio dell'utente): AFFARE se venduto entro 5 min, MEDIO AFFARE entro 15 min,
    NORMALE entro 1h, NON AFFARE se al controllo dell'ora e' ancora invenduto. Pura."""
    if stato == "venduto":
        return "AFFARE" if offset_s <= 300 else "MEDIO AFFARE" if offset_s <= 900 else "NORMALE"
    if offset_s >= 3600 and stato in ("attivo", "attivo?", "prenotato"):
        return "NON AFFARE"
    return None


async def _tracc_leggi_pagina(url, max_retries=1):
    """(http_status, html) della pagina annuncio, con gli errori HTTP/rete ridotti a un codice."""
    try:
        resp = await _vinted_get_con_retry(url, timeout=15, max_retries=max_retries)
        if resp is not None:
            return resp.status_code, resp.text
        return None, ""
    except httpx.HTTPStatusError as e:
        return e.response.status_code, ""
    except Exception as e:
        return f"errore:{type(e).__name__}", ""


def tracc_registra_gia_venduto(listing_info, url, t0):
    """Annuncio gia' venduto quando il bot lo scrapa (secondi dopo l'arrivo del messaggio): il segnale piu'
    forte di un affare."""
    try:
        da_msg = round(time.time() - t0, 1)
        _log_esito(listing_info, "GIA_VENDUTO", dopo_messaggio_s=da_msg, bucket="istantaneo", classe="AFFARE",
                   prezzo=listing_info.get("price"))
        item_id = _estrai_item_id_da_url(url) if url else None
        if TRACCIAMENTO_ATTIVO and item_id:
            _tracc_scrivi({
                "tipo": "gia_venduto", "item_id": str(item_id), "url": url, "brand": listing_info.get("brand"),
                "titolo": listing_info.get("title"), "prezzo": _a_float(listing_info.get("price"), None),
                "categoria": estrai_categoria_da_titolo(listing_info.get("title") or "", listing_info.get("description")),
                "dopo_messaggio_s": da_msg, "bucket": "istantaneo",
            })
    except Exception:
        log.warning("Tracciamento: gia' venduto non registrato:\n%s", traceback.format_exc())


async def _tracc_serie(item_id, url, brand, prezzo, t0):
    """Serie di controlli ancorati a t0: attende ciascun offset, rilegge la pagina e si ferma alla prima
    vendita (o se l'annuncio e' scartato). Registra i secondi reali da t0, la fascia e la classe."""
    item_id = str(item_id)
    for s_dopo in TRACCIAMENTO_SERIE_SECONDI:
        try:
            if item_id in _tracc_stop:
                return
            attesa = t0 + s_dopo - time.time()
            if attesa > 0:
                await asyncio.sleep(attesa)
                if item_id in _tracc_stop:
                    return
            async with _tracc_sem:
                http_status, html_pagina = await _tracc_leggi_pagina(url)
            segnali, prezzo_ora = _tracc_estrai_segnali(html_pagina)
            reale = round(time.time() - t0, 1)
            stato = _tracc_stato(http_status, segnali)
            bucket = _tracc_bucket(s_dopo) if stato == "venduto" else None
            classe = _tracc_classe(s_dopo, stato)
            esito, target = _tracc_esiti.get(item_id, ("n/d", None))
            _tracc_scrivi({
                "tipo": "ricontrollo", "item_id": item_id, "stadio_s": s_dopo, "da_messaggio_s": reale,
                "http": http_status, "segnali": segnali, "prezzo_ora": prezzo_ora, "stato": stato,
                "bucket": bucket, "classe": classe,
            })
            log.info(
                "RICONTROLLO LAMPO | item=%s | brand='%s' | offset=%ss | da_messaggio=%ss | http=%s | stato=%s | bucket=%s | classe=%s | prezzo_valutato=%s | prezzo_ora=%s | esito=%s | target=%s | preferiti=%s | visite=%s",
                item_id, brand or "n/d", s_dopo, reale, http_status, stato, bucket or "-", classe or "-",
                prezzo, prezzo_ora, esito, target, segnali.get("preferiti", "-"), segnali.get("visite", "-"),
            )
            if stato in ("venduto", "rimosso"):
                _tracc_stop.add(item_id)
                return
        except Exception:
            log.warning("Ricontrollo lampo fallito:\n%s", traceback.format_exc())
            return


def tracc_avvia_serie(listing_info, url, t0):
    """Subito dopo il primo scrape: avvia la serie di controlli per l'annuncio (se non gia' venduto)."""
    if not TRACCIAMENTO_ATTIVO:
        return
    try:
        item_id = _estrai_item_id_da_url(url) if url else None
        if not item_id:
            return
        if listing_info.get("stato_vendita") == "venduto":
            _tracc_stop.add(str(item_id))
            return
        asyncio.get_running_loop().create_task(_tracc_serie(
            item_id, url, listing_info.get("brand"), _a_float(listing_info.get("price"), None), t0))
    except Exception:
        log.warning("Tracciamento: serie di controlli non avviata:\n%s", traceback.format_exc())


_LINGUA_MARCATORI = {
    "de": re.compile(r"\b(von|und|mit|damen|herren|gr[oö]ss?e|jacke|mantel|kleid|hose|pullover|neu|wie)\b", re.I),
    "fr": re.compile(r"\b(veste|manteau|robe|pantalon|taille|femme|homme|tr[eè]s|neuf|avec|pull|chemise)\b", re.I),
    "en": re.compile(r"\b(the|with|size|women|men|jacket|coat|dress|trousers|new|vintage authentic)\b", re.I),
}


def lingua_titolo(titolo):
    """'de' / 'fr' / 'en' / 'it' dal titolo (euristica a parole chiave): i titoli esteri sono spesso venditori che
    prezzano male. Pura."""
    t = titolo or ""
    for lingua in ("de", "fr", "en"):
        if _LINGUA_MARCATORI[lingua].search(t):
            return lingua
    return "it"


def campi_annuncio(listing_info, n_foto=None, adesso=None):
    """Caratteristiche dell'annuncio per l'apprendimento dalla rotazione (richiesto dall'utente il 2026-10-04),
    come coppie chiave=valore per la riga PREAVVISO e per l'evento 'annuncio' del DB. Pura (adesso = epoch)."""
    t = time.gmtime(adesso if adesso is not None else time.time())
    titolo = listing_info.get("title") or ""
    campi = {
        "categoria": estrai_categoria_da_titolo(titolo, listing_info.get("description")),
        "cond": listing_info.get("condition"), "mat": listing_info.get("material_raw"),
        "taglia": listing_info.get("size"), "lingua": lingua_titolo(titolo),
        "n_foto": n_foto, "desc_len": len((listing_info.get("description") or "").strip()),
        "v_rec": listing_info.get("seller_feedback_count"), "v_rep": listing_info.get("seller_feedback_reputation"),
        "v_art": listing_info.get("seller_items_count"), "v_paese": listing_info.get("seller_country"),
        "ora_utc": t.tm_hour, "gs": t.tm_wday,
        "pref": listing_info.get("preferiti"), "visite": listing_info.get("visite"),
    }
    return {k: (v.strip().replace("|", "/").replace(" ", "_") if isinstance(v, str) else v)
            for k, v in campi.items() if v not in (None, "")}


def tracc_registra_valutato(listing_info, url, esito, target=None, n_comp=None):
    """Registra un annuncio arrivato a un verdetto, una sola volta per item id."""
    if not TRACCIAMENTO_ATTIVO:
        return
    try:
        item_id = _estrai_item_id_da_url(url) if url else None
        if not item_id or str(item_id) in _tracc_item_visti:
            return
        item_id = str(item_id)
        _tracc_item_visti.add(item_id)
        _tracc_scrivi({
            "tipo": "valutato", "item_id": item_id, "url": url,
            "brand": listing_info.get("brand"), "titolo": listing_info.get("title"),
            "categoria": estrai_categoria_da_titolo(listing_info.get("title") or "", listing_info.get("description")),
            "prezzo": _a_float(listing_info.get("price"), None), "esito": esito,
            "target": target, "n_comp": n_comp, "stato_scrape": listing_info.get("stato_vendita"),
        })
    except Exception:
        log.warning("Tracciamento: registrazione fallita:\n%s", traceback.format_exc())


_CAND_TS_RE = re.compile(
    r'(?<![0-9])(?:1[5-9][0-9]{8}(?:[0-9]{3})?|'
    r'20[0-9]{2}-[01][0-9]-[0-3][0-9][T ][0-2][0-9]:[0-5][0-9](?::[0-5][0-9])?(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)(?![0-9])'
)


def trova_timestamp_candidati(html_pagina, giorni=45, max_voci=40):
    """Cerca nella pagina QUALSIASI valore che sembri un istante recente (epoch in secondi/millisecondi o
    data ISO), con il contesto che lo precede e l'orario UTC leggibile. Indipendente dai nomi delle chiavi:
    serve a scoprire se la pagina espone quando l'articolo e' stato creato/modificato/venduto. Pura."""
    ora = time.time()
    trovati, visti = [], set()
    for m in _CAND_TS_RE.finditer(html_pagina):
        val = m.group(0)
        if val in visti:
            continue
        if val.isdigit():
            ts = int(val) / 1000 if len(val) == 13 else float(val)
        else:
            dt = _parse_created_at_dt(val.replace(" ", "T"))
            if dt is None:
                continue
            ts = dt.timestamp()
        if not (ora - giorni * 86400 <= ts <= ora + 86400):
            continue
        visti.add(val)
        ctx = re.sub(r"\s+", " ", html_pagina[max(0, m.start() - 60):m.start()])
        trovati.append(f"{ctx} -> {val} = {datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        if len(trovati) >= max_voci:
            break
    return trovati


def _log_esito(listing_info, esito, **campi):
    """Una riga greppable per annuncio con il brand del tracker (richiesto
    dall'utente il 2026-10-01) per l'analisi giornaliera per brand dai log."""
    _id = None
    try:
        _id = _estrai_item_id_da_url(listing_info.get("url")) if listing_info.get("url") else None
        if _id:
            _tracc_esiti[str(_id)] = (esito, campi.get("target"))
            if str(esito).startswith("SKIP_") or esito == "ERRORE_CERVELLO":
                _tracc_stop.add(str(_id))
            if len(_tracc_esiti) > 5000:
                for _k in list(_tracc_esiti)[:1000]:
                    _tracc_esiti.pop(_k, None)
    except Exception:
        pass
    try:
        extra = "".join(f" | {k}={v}" for k, v in campi.items() if v not in (None, ""))
        if _id:
            extra += f" | item={_id}"   # permette di incrociare l'esito con PREAVVISO e RICONTROLLO LAMPO
        log.info("ESITO | brand='%s' | titolo='%s' | esito=%s%s",
                 (listing_info.get("brand") or "n/d"), listing_info.get("title"), esito, extra)
        db.scrivi_evento("esito", _id, listing_info.get("brand"),
                         {"titolo": listing_info.get("title"), "esito": esito, **campi})
    except Exception:
        pass
