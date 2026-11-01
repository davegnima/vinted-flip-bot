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
from bot.config import TELEGRAM_ALERT_CHAT_ID
from bot.telegram_api import telegram_send_with_buttons
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
#  - nessun controllo per gli scartati prima del verdetto (SKIP_*), tranne i 'falso'/'fraudolento' (solo 15 s - 5 min)
#    e l'errore del Cervello (serie completa); stato 'rimosso?' = 200 senza dati (cancellato o in revisione);
#    gli annunci 'spariti' (rimosso, rimosso?, n.d.) si seguono fino a 1 h (righe RICONTROLLO STORIA / RIAPPARSO).
# Solo raccolta: nessuna decisione cambia (SKIP_GIA_VENDUTI=1 interrompe l'analisi dei gia' venduti).
TRACCIAMENTO_ATTIVO = os.environ.get("TRACCIAMENTO_ATTIVO", "1").strip() == "1"
TRACCIAMENTO_FILE = os.environ.get("TRACCIAMENTO_FILE", "/data/tracciamento_esiti.jsonl")
SKIP_GIA_VENDUTI = os.environ.get("SKIP_GIA_VENDUTI", "0").strip() == "1"
TRACCIAMENTO_SERIE_SECONDI = (15, 30, 60, 300, 900, 3600)
_TRACC_FASCE = ((15, "<=15s"), (30, "<=30s"), (60, "<=1min"), (300, "<=5min"), (900, "<=15min"), (3600, "<=60min"))
_tracc_item_visti = set()  # annunci gia' registrati (caricato all'avvio da main)
_tracc_stop = set()  # annunci venduti, rimossi o scartati prima del verdetto: la serie si ferma
# Scartati per "falso"/"fraudolento" (5/10): si seguono lo stesso, ma solo fino a TRACCIAMENTO_SERIE_RIDOTTA_MAX_S
# (60 s e 5 min), per misurare i falsi negativi dell'Occhio spendendo poca banda. ERRORE_CERVELLO: serie completa.
_tracc_ridotti = set()
# Dall'8/10 anche gli altri scartati dopo lo scrape (SKIP_PRE_GEMINI, SKIP_PRE_CERVELLO, SKIP_ROSSO) si seguono con la
# serie ridotta (5 min, 15 min, 1 h): l'utente vuole ragionare su TUTTI gli annunci, e solo cosi' si misurano i falsi
# negativi dei filtri e dell'Occhio. SKIP_PRE_SCRAPE (esclusioni dell'utente su titolo/brand) resta senza serie.
TRACCIAMENTO_SERIE_SKIP_S = (300, 900, 3600)
_SKIP_DA_SEGUIRE = ("SKIP_PRE_GEMINI", "SKIP_PRE_CERVELLO", "SKIP_ROSSO", "SKIP_SOLO_SEMAFORO")
# ALLARME PREFERITI (11/10, caso Margiela 56 EUR: NON COMPRARE del Cervello, 18 preferiti in 3 minuti): i preferiti letti dai
# ricontrolli sono il segnale di domanda piu' forte che abbiamo (10/10, 709 annunci: con 2+ preferiti a 60 s il 50% si vende
# entro 15 min contro il 7% con zero). Se a 60 s ci sono >= ALLARME_PREF_60 preferiti (o a 300 s >= ALLARME_PREF_300), l'annuncio
# e' ancora in vendita, il fair value rapido e' >= ALLARME_PREF_RAPPORTO volte il prezzo e il bot NON aveva detto COMPRA (ne' scartato
# per falso), un messaggio con suono arriva nel gruppo. Sul 10/10: ~16 allarmi al giorno, ~70% venduti entro 1 h dopo l'allarme
# (soglie scelte sugli stessi dati: da riverificare). Spento con ALLARME_PREF_ATTIVO=0.
ALLARME_PREF_ATTIVO = os.environ.get("ALLARME_PREF_ATTIVO", "1").strip() != "0"
ALLARME_PREF_60 = int(float(os.environ.get("ALLARME_PREF_60", "3")))
ALLARME_PREF_300 = int(float(os.environ.get("ALLARME_PREF_300", "6")))
ALLARME_PREF_RAPPORTO = float(os.environ.get("ALLARME_PREF_RAPPORTO", "1.5"))
_ALLARME_ESITI = ("NON COMPRARE", "TRATTA", "CHIEDI ALTRE FOTO", "SKIP_ROSSO")
_tracc_pref = {}   # item_id -> [(offset, preferiti)] letti a ogni controllo: la crescita e' un segnale di domanda
_tracc_ctx = {}   # item_id -> contesto dell'annuncio (esito, margine, semaforo, categoria...) per la riga TRACCIATO
_tracc_attesa_esito = set()   # item_id con serie avviata e verdetto del bot non ancora arrivato (ne' _log_esito)
_tracc_differiti = {}   # item_id -> (brand, prezzo, storia): serie finita (venduto in pochi secondi) prima del verdetto
TRACC_ATTESA_ESITO_MAX_S = 240   # oltre, la riga esce comunque (senza esito del bot)
_STATI_SPARITO = ('rimosso', 'rimosso?', 'n.d.')
TRACCIAMENTO_SERIE_RIDOTTA_MAX_S = 300
_SCARTI_DA_SEGUIRE = ("[FALSO CONCLAMATO", "[ANNUNCIO FRAUDOLENTO")
_tracc_esiti = {}  # item_id -> (esito, target): lo valorizza _log_esito, lo legge la serie nei log
_tracc_sem = asyncio.Semaphore(8)

_TRACC_SEGNALI_RE = {
    # La pagina incorpora i dati come JSON dentro una stringa: le virgolette possono arrivare
    # escapate (\\"chiave\\":valore), quindi il backslash prima di ogni virgoletta e' opzionale.
    chiave: re.compile(r'\\?"' + chiave + r'\\?"\s*:\s*\\?("?[A-Za-z0-9_.-]{1,30}"?)')
    for chiave in ("is_closed", "is_reserved", "is_hidden", "is_draft", "can_buy", "item_closing_action")
}
# Preferiti (richiesto dall'utente il 2026-10-04): segnale di domanda letto nello scrape e in ogni ricontrollo lampo.
# Verificato sui log il 2026-10-04: il campo c'e'. Le visualizzazioni non si leggono dalla pagina: tolte.
_TRACC_CONTEGGI_RE = {
    "preferiti": re.compile(r'\\?"(?:favou?rite_count|favou?rites_count|favou?riteCount)\\?"\s*:\s*(\d{1,7})'),
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
    """Unico classificatore dello stato: venduto / rimosso / rimosso? / prenotato / attivo / n.d. Verificato il
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
    if http_status == 200:
        # 5/10: pagina che risponde 200 ma senza prezzo ne' segnali di vendita = di solito annuncio cancellato dal
        # venditore o in revisione (l'utente vede "errore"): NON e' un invenduto ne' un venduto
        return "rimosso?"
    return "n.d."   # nessuna risposta (errore di rete o codice strano): sconosciuto


def _tracc_bucket(offset_s):
    """Fascia di vendita dato l'offset (secondi da t0) del primo controllo che ha trovato il venduto. Pura."""
    for limite, etichetta in _TRACC_FASCE:
        if offset_s <= limite:
            return etichetta
    return ">60min"


def _tracc_classe(offset_s, stato):
    """Classe di mercato (criterio dell'utente): AFFARE se venduto entro 5 min, MEDIO AFFARE entro 15 min,
    NORMALE entro 1h, NON AFFARE se al controllo dell'ora e' ancora invenduto, PRENOTATO se nella prima ora e' stato prenotato (domanda alta,
    conta come veloce nella tabella velocita'). Pura."""
    if stato == "venduto" or (stato == "prenotato" and offset_s <= 3600):
        # prenotato = venduto (utente, 8/10): la vendita e' bloccata da un compratore, conta il momento della prenotazione
        return "AFFARE" if offset_s <= 300 else "MEDIO AFFARE" if offset_s <= 900 else "NORMALE"
    if offset_s >= 3600 and stato == "attivo":   # rimosso?/n.d. non sono invenduti: restano senza classe
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


def _prossima_fascia(secondi):
    """Fascia (offset nominale) che contiene `secondi`: per un controllo fatto in ritardo (dopo un riavvio) la classe
    si attribuisce alla fascia reale, mai a una piu' veloce. Pura."""
    for limite, _ in _TRACC_FASCE:
        if secondi <= limite:
            return limite
    return 3600


def _tracc_prenotato_s(storia):
    """Offset del primo controllo 'prenotato' entro 1 h, None se non c'e'. Pura."""
    return next((o for o, s in storia if s == "prenotato" and o <= 3600), None)


def _tracc_esito_finale(storia):
    """(stato finale, classe, secondi di vendita) dalla storia [(offset, stato)]. Classe None se la serie non e' arrivata in
    fondo o l'annuncio e' sparito. Pura."""
    venduto = next((o for o, s in storia if s == "venduto"), None)
    primo = _tracc_prenotato_s(storia)
    if venduto is not None and (primo is None or venduto < primo):
        primo = venduto
    if primo is not None:
        # la classe e' quella del primo evento (prenotazione o vendita): prenotato a 1 min e venduto a 30 min = AFFARE
        return ("venduto" if venduto is not None else storia[-1][1]), _tracc_classe(primo, "venduto"), venduto
    if storia:
        off, st = storia[-1]
        return st, _tracc_classe(off, st), None
    return "-", None, None


def _riga_tracciato(item_id, brand, prezzo, storia, ctx, incompleto=False, prefisso="TRACCIATO"):
    """Una riga per annuncio con TUTTO (esito del bot, semaforo, caratteristiche, esito di vendita): e' il dataset
    dell'apprendimento (un solo filtro nei log, niente join fra righe sparse)."""
    stato, classe, venduto_s = _tracc_esito_finale(storia)
    pref = _tracc_pref.get(str(item_id)) or []
    campi = {"item": item_id, "brand": f"'{brand or 'n/d'}'", "prezzo": prezzo,
             **{k: v for k, v in (ctx or {}).items() if not k.startswith("_")},
             "prenotato_s": _tracc_prenotato_s(storia),
             "pref_max": max((p for _, p in pref), default=None),
             "pref_serie": ",".join(f"{o}:{p}" for o, p in pref) or None,
             "stato": stato, "classe": classe or "-", "venduto_s": venduto_s if venduto_s is not None else "-",
             "controlli": len(storia), "incompleto": "si" if incompleto else "no",
             "storia": ",".join(f"{o}:{st}" for o, st in storia) or "-"}
    return f"{prefisso} | " + " | ".join(f"{k}={v}" for k, v in campi.items() if v not in (None, ""))


def _tracc_scrivi_finale(item_id, brand, prezzo, storia, radar=False):
    """Scrive la riga TRACCIATO di fine serie e ripulisce lo stato in memoria e nel DB."""
    item_id = str(item_id)
    _tracc_attesa_esito.discard(item_id)
    try:
        ctx = _tracc_ctx.get(item_id, {})
        log.info(_riga_tracciato(item_id, brand, prezzo, storia, ctx, prefisso="TRACCIATO_RADAR" if radar else "TRACCIATO"))
        if not radar:
            db.scrivi_evento("tracciato", item_id, brand, {"prezzo": prezzo, **ctx, "storia": storia})
        db.elimina_serie(item_id)
        _tracc_ctx.pop(item_id, None)
        _tracc_pref.pop(item_id, None)
    except Exception:
        log.warning("TRACCIATO non scritto:\n%s", traceback.format_exc())


def _tracc_scrivi_differita(item_id):
    """Scrive la riga rimasta in attesa del verdetto (arrivato, o scaduto il tempo massimo). Idempotente."""
    d = _tracc_differiti.pop(str(item_id), None)
    if d:
        _tracc_scrivi_finale(item_id, *d)


async def _tracc_serie(item_id, url, brand, prezzo, t0, offsets=None, storia=None, radar=False):
    """Serie di controlli ancorati a t0: attende ciascun offset, rilegge la pagina e si ferma alla prima
    vendita (o se l'annuncio e' scartato). Registra i secondi reali da t0, la fascia e la classe. La serie e' salvata nel
    DB e riprende dopo un riavvio (`tracc_riprendi_serie`); `storia` = controlli gia' fatti prima del riavvio."""
    item_id = str(item_id)
    storia = list(storia or [])   # (offset, stato): serve a capire se uno "sparito" torna online (legit check) o resta sparito (ban)
    finita = False
    try:
        await _tracc_serie_interna(item_id, url, brand, prezzo, t0, storia, offsets)
        finita = True
    except asyncio.CancelledError:
        raise
    finally:
        if finita:
            if (not radar and item_id in _tracc_attesa_esito and not (_tracc_ctx.get(item_id) or {}).get("esito")):
                # venduto prima che il Cervello finisse: la riga aspetta il verdetto (lo scrive _log_esito) cosi' ha esito, margine, roi
                _tracc_differiti[item_id] = (brand, prezzo, storia)
                try:
                    # la serie resta nel DB: se il worker riparte prima del verdetto, tracc_riprendi_serie scrive la riga
                    asyncio.get_running_loop().call_later(TRACC_ATTESA_ESITO_MAX_S, _tracc_scrivi_differita, item_id)
                except Exception:
                    log.warning("TRACCIATO differito non pianificato:\n%s", traceback.format_exc())
            else:
                _tracc_scrivi_finale(item_id, brand, prezzo, storia, radar)
        if any(st in _STATI_SPARITO for _, st in storia):
            log.info("RICONTROLLO STORIA | item=%s | brand='%s' | stati=%s", item_id, brand or "n/d",
                     " ".join(f"{o}s:{st}" for o, st in storia))


def allarme_preferiti_da_inviare(ctx, prezzo, offset_s, preferiti, stato):
    """True se i preferiti letti al controllo `offset_s` giustificano l'allarme (vedi ALLARME_PREF_*). Pura."""
    if not ALLARME_PREF_ATTIVO or stato != "attivo" or not isinstance(preferiti, int) or not ctx or ctx.get("_allarmato"):
        return False
    if ctx.get("esito") not in _ALLARME_ESITI or ctx.get("legit") == "probabilmente_falso":
        return False
    fv, prezzo = _a_float(ctx.get("fv"), None), _a_float(prezzo, None)
    if not fv or not prezzo or prezzo <= 0 or fv / prezzo < ALLARME_PREF_RAPPORTO:
        return False
    return (offset_s == 60 and preferiti >= ALLARME_PREF_60) or (offset_s == 300 and preferiti >= ALLARME_PREF_300)


def testo_allarme_preferiti(item_id, url, brand, prezzo, offset_s, preferiti, ctx):
    """Messaggio Markdown dell'allarme preferiti. Pura."""
    from bot.testo import _escapa_markdown_legacy as esc
    minuti = offset_s / 60
    righe = [f"🔥 *{preferiti} preferiti in {minuti:.0f} min* · 💶 {_a_float(prezzo, 0):.0f} € · 🏷️ {esc(str(brand or 'n/d'))}"]
    if ctx.get("_titolo"):
        righe.append(esc(str(ctx["_titolo"])))
    pezzi = [f"il bot: {ctx.get('esito')}"]
    if ctx.get("target"):
        pezzi.append(f"target {ctx['target']} €")
    if ctx.get("sem"):
        pezzi.append(str(ctx["sem"]))
    if ctx.get("fv"):
        pezzi.append(f"fair value ~{ctx['fv']} €")
    righe.append(esc(" · ".join(pezzi)))
    righe.append(f"[vedi su Vinted]({url})")
    return "\n".join(righe)


async def _invia_allarme_preferiti(item_id, url, brand, prezzo, offset_s, preferiti):
    ctx = _tracc_ctx.get(item_id) or {}
    ctx["_allarmato"] = True
    _tracc_ctx[item_id] = ctx
    log.info("ALLARME PREFERITI | item=%s | brand='%s' | preferiti=%s | offset=%ss | esito=%s | fv=%s | prezzo=%s | target=%s",
             item_id, brand or "n/d", preferiti, offset_s, ctx.get("esito"), ctx.get("fv"), prezzo, ctx.get("target"))
    if TELEGRAM_ALERT_CHAT_ID:
        await telegram_send_with_buttons(TELEGRAM_ALERT_CHAT_ID, testo_allarme_preferiti(item_id, url, brand, prezzo, offset_s, preferiti, ctx),
                                         url, None)


async def _tracc_serie_interna(item_id, url, brand, prezzo, t0, storia, offsets=None):
    fatto_in_ritardo = False
    for s_dopo in (offsets or TRACCIAMENTO_SERIE_SECONDI):
        try:
            if item_id in _tracc_stop:
                return
            if item_id in _tracc_ridotti and s_dopo not in TRACCIAMENTO_SERIE_SKIP_S:
                continue   # serie ridotta: solo 5 min, 15 min e 1 h
            attesa = t0 + s_dopo - time.time()
            if attesa < -90:
                # dopo un riavvio: un solo controllo subito per tutti gli offset scaduti, con la fascia reale
                if fatto_in_ritardo:
                    continue
                fatto_in_ritardo = True
                s_dopo = _prossima_fascia(time.time() - t0)
            elif attesa > 0:
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
                "RICONTROLLO LAMPO | item=%s | brand='%s' | offset=%ss | da_messaggio=%ss | http=%s | stato=%s | bucket=%s | classe=%s | prezzo_valutato=%s | prezzo_ora=%s | esito=%s | target=%s | preferiti=%s",
                item_id, brand or "n/d", s_dopo, reale, http_status, stato, bucket or "-", classe or "-",
                prezzo, prezzo_ora, esito, target, segnali.get("preferiti", "-"),
            )
            if any(st in _STATI_SPARITO for _, st in storia) and stato in ("attivo", "prenotato", "venduto"):
                log.info("RICONTROLLO RIAPPARSO | item=%s | brand='%s' | dopo=%ss | stato=%s | prima=%s", item_id,
                         brand or "n/d", reale, stato, storia[-1][1])
            storia.append((s_dopo, stato))
            if isinstance(segnali.get("preferiti"), int):
                _tracc_pref.setdefault(item_id, []).append((s_dopo, segnali["preferiti"]))
            db.aggiorna_serie(item_id, storia=storia)
            try:
                if allarme_preferiti_da_inviare(_tracc_ctx.get(item_id), prezzo, s_dopo, segnali.get("preferiti"), stato):
                    await _invia_allarme_preferiti(item_id, url, brand, prezzo, s_dopo, segnali["preferiti"])
            except Exception:
                log.warning("Allarme preferiti non inviato:\n%s", traceback.format_exc())
            if _tracc_pref.get(item_id):   # i preferiti restano nel DB con il contesto: un riavvio non li perde
                db.aggiorna_serie(item_id, ctx={**_tracc_ctx.get(item_id, {}), "_pref": _tracc_pref[item_id]})
            if stato == "venduto":
                _tracc_stop.add(item_id)
                return
            # sparito (404, 200 senza dati o nessuna risposta): si continua fino a 1 h per capire se e' un legit
            # check di Vinted che poi torna online o un annuncio bannato/cancellato (richiesto dall'utente il 5/10)
        except Exception:
            log.warning("Ricontrollo lampo fallito:\n%s", traceback.format_exc())
            return


def tracc_avvia_serie(listing_info, url, t0, offsets=None):
    """Subito dopo il primo scrape: avvia la serie di controlli per l'annuncio (se non gia' venduto). offsets: istanti
    (secondi da t0) diversi da TRACCIAMENTO_SERIE_SECONDI, es. la serie ridotta del radar."""
    if not TRACCIAMENTO_ATTIVO:
        return
    try:
        item_id = _estrai_item_id_da_url(url) if url else None
        if not item_id:
            return
        if listing_info.get("stato_vendita") == "venduto":
            _tracc_stop.add(str(item_id))
            return
        prezzo = _a_float(listing_info.get("price"), None)
        db.salva_serie(item_id, url, listing_info.get("brand"), prezzo, t0, list(offsets or TRACCIAMENTO_SERIE_SECONDI))
        if not offsets:
            _tracc_attesa_esito.add(str(item_id))
        asyncio.get_running_loop().create_task(_tracc_serie(item_id, url, listing_info.get("brand"), prezzo, t0, offsets, radar=bool(offsets)))
    except Exception:
        log.warning("Tracciamento: serie di controlli non avviata:\n%s", traceback.format_exc())


def tracc_riprendi_serie(adesso=None):
    """All'avvio: riprende le serie lasciate a meta' dal riavvio precedente (il deploy le uccideva: nei dati del 7/10 mancava
    l'esito di vendita di meta' degli annunci). Ritorna quante ne ha riprese. Va chiamata con il loop in esecuzione."""
    if not TRACCIAMENTO_ATTIVO:
        return 0
    adesso = adesso if adesso is not None else time.time()
    n = 0
    try:
        for r in db.carica_serie(adesso - 3700):
            item_id = r["item_id"]
            if r["storia"] and r["storia"][-1][1] == "venduto":
                # serie gia' chiusa (venduto) che aspettava il verdetto del bot quando il worker e' ripartito
                _tracc_ctx[item_id] = {k: v for k, v in (r.get("ctx") or {}).items() if k != "_pref"}
                _tracc_scrivi_finale(item_id, r["brand"], r["prezzo"], [tuple(x) for x in r["storia"]])
                continue
            fatti = {o for o, _ in r["storia"]}
            restanti = [o for o in r["offsets"] if o not in fatti]
            if not restanti:
                continue
            ctx = dict(r.get("ctx") or {})
            pref = ctx.pop("_pref", None)
            if pref:
                _tracc_pref[item_id] = [tuple(x) for x in pref]
            _tracc_ctx[item_id] = ctx
            if ctx.get("esito"):
                _tracc_esiti[item_id] = (ctx["esito"], ctx.get("target"))
                if str(ctx["esito"]).startswith(_SKIP_DA_SEGUIRE):
                    _tracc_ridotti.add(item_id)
            asyncio.get_running_loop().create_task(_tracc_serie(
                item_id, r["url"], r["brand"], r["prezzo"], r["t0"], restanti, storia=r["storia"],
                radar=list(r["offsets"]) != list(TRACCIAMENTO_SERIE_SECONDI)))
            n += 1
    except Exception:
        log.warning("Tracciamento: serie non riprese:\n%s", traceback.format_exc())
    return n


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
        "pref": listing_info.get("preferiti"),
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


def _contesto_tracciato(listing_info, esito, campi):
    """Campi dell'annuncio da riportare nella riga TRACCIATO: esito del bot e stima rapida (semaforo, lift del brand)."""
    fv = listing_info.get("fair_value") or {}
    ctx = {
        "esito": esito, "margine": campi.get("margine"), "roi": campi.get("roi"), "target": campi.get("target"),
        "legit": campi.get("legit"), "n_comp": campi.get("n_comp"),
        "sem": fv.get("semaforo"), "sem_base": fv.get("semaforo_base"), "lift": fv.get("lift_velocita"),
        "fv": fv.get("fv"), "conf": fv.get("conf"), "brand_n": fv.get("brand"),
        "categoria": fv.get("categoria") or estrai_categoria_da_titolo(listing_info.get("title") or "", listing_info.get("description")),
        "cond": listing_info.get("condition"), "preavviso": "si" if listing_info.get("preavviso") else "no",
        # campi per costruire la matrice del semaforo (12/10): catalogo Vinted, materiale, colore, taglia e inizio del titolo
        "catalogo": listing_info.get("catalog_id"), "mat": (str(listing_info.get("material_raw") or "")[:30] or None),
        "colore": (str(listing_info.get("color_raw") or "")[:30] or None), "taglia": listing_info.get("size"),
        "tit": (str(listing_info.get("title") or "")[:50] or None),
        "query": (str(listing_info.get("query_name") or "")[:60] or None),   # ricerca del tracker (17/10)
        "caricato": (str(listing_info.get("uploaded_text") or "").split(",")[0].strip()[:24] or None),   # "Proprio adesso", "2 minuti fa"...
        "pub_tg": listing_info.get("pub_tg"),   # secondi fra pubblicazione su Vinted e messaggio del tracker (18/10)
        "motivo": (str(campi.get("motivo") or "")[:60].replace("|", "/") or None),
        "_prezzo": _a_float(listing_info.get("price"), None),
        "_titolo": (str(listing_info.get("title") or "")[:80] or None),   # chiavi con "_": non finiscono nella riga TRACCIATO
    }
    return {k: (v.replace("|", "/") if isinstance(v, str) else v) for k, v in ctx.items() if v not in (None, "")}


def _log_esito(listing_info, esito, **campi):
    """Una riga greppable per annuncio con il brand del tracker (richiesto
    dall'utente il 2026-10-01) per l'analisi giornaliera per brand dai log."""
    _id = None
    try:
        _id = _estrai_item_id_da_url(listing_info.get("url")) if listing_info.get("url") else None
        if _id:
            _tracc_esiti[str(_id)] = (esito, campi.get("target"))
            if str(esito) in _SKIP_DA_SEGUIRE:
                _tracc_ridotti.add(str(_id))     # scartato dopo lo scrape: serie ridotta (5 min, 15 min, 1 h)
            elif str(esito).startswith("SKIP_"):
                _tracc_stop.add(str(_id))
            _tracc_ctx[str(_id)] = _contesto_tracciato(listing_info, esito, campi)
            _tracc_attesa_esito.discard(str(_id))
            if str(_id) in _tracc_differiti:
                _tracc_scrivi_differita(_id)   # era gia' venduto: la riga esce ora, con il verdetto
            else:
                db.aggiorna_serie(_id, ctx=_tracc_ctx[str(_id)])
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
