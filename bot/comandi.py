"""Comandi del proprietario (messaggi in uscita) e le loro funzioni di supporto, spostati da main_telethon.py senza cambiare la logica.
Le funzioni on_* qui sono senza decoratore: la registrazione con client.on(...) resta in main_telethon.py (stesso ordine di prima)."""

import re
import json
import time
import base64
import asyncio
import traceback
from datetime import datetime, timezone
from urllib.parse import quote

try:
    # Opzionale (2026-09-29): client con impronta TLS di un browser vero,
    # per ora usato solo dal comando /test_visuale. Se manca, il bot gira
    # uguale e il test lo segnala.
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
except Exception:
    CurlAsyncSession = None

from bot import http_clients as hc
from bot import db
from bot import archivio_radar
from bot.cicli import _testo_report_radar, _aggiorna_velocita_db
from bot.client_tg import client
from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID, VISUAL_SEARCH_ATTIVA
from bot.logger import log
from bot.costanti import VINTED_HEADERS
from bot.feedback import parse_risposta, registra_feedback, registra_nota, _contesti, _ctx_item
from bot.operazioni import parse_operazione, margine_reale
from bot.fair_value import _fv_leggi, fv_rapporto, fv_unisci
from bot.gemini_api import testa_chiavi_gemini
from bot.parsing import _estrai_item_id_da_url, extract_url_from_text
from bot.proxy import (
    PROXY_LIST,
    _CLIENT_VINTED_POOL,
    _CLIENT_VINTED_POOL_KEYS,
    _ETICHETTA_PER_CHIAVE_PROXY,
    _etichetta_proxy,
)
from bot.telegram_api import _spezza_per_telegram, telegram_send_message
from bot.tracciamento import _tracc_estrai_segnali, _tracc_leggi_pagina, _tracc_stato, trova_timestamp_candidati
from bot.vinted_http import VINTED_COOKIES_EXTRA, _VINTED_COOKIES, _jwt_scaduto, _rinnova_token_vinted, _vinted_refresh_lock
from bot.vinted_scrape import scrape_vinted_listing
from bot.comps import MARKER_NESSUN_ARTICOLO_VINTED
from bot.comps_filtri import _articoli_vinted, _estrai_articoli_da_alt_vinted


# ---------------------------------------------------------------------------
# TEST PROXY A COMANDO (aggiunto 2026-09-27, utente: "come testo i miei
# proxy?"). Una richiesta REALE a Vinted per OGNUNO dei proxy del pool,
# riusando lo stesso parsing gia' in produzione per i comp catalogo
# (_estrai_articoli_da_alt_vinted / MARKER_NESSUN_ARTICOLO_VINTED): un proxy
# e' "ok" solo se estrae davvero articoli, non solo se risponde 200 -- e'
# proprio la distinzione (200 ma pagina di blocco) che ha reso il problema
# del 27/9 difficile da diagnosticare da un singolo status HTTP.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# TEST RICERCA VISUALE A COMANDO (2026-09-29)
# ---------------------------------------------------------------------------
# /test_visuale <link annuncio>: prova la ricerca visuale Vinted ("Cerca
# articoli simili") con il client attuale (httpx) e con curl_cffi (impronta
# TLS di Safari iOS e di Chrome), con gli stessi cookie dell'account
# dedicato e lo stesso proxy. Serve a capire se il 403 Datadome su
# /search_by_image (diagnosi del 2026-09-20, vedi
# _risolvi_search_by_image_id) dipende dall'impronta di httpx,
# prima di cambiare qualunque cosa nella pipeline. Nessuna chiamata Gemini.

VARIANTI_CURL_TEST_VISUALE = (("curl_cffi Safari iOS", "safari184_ios"), ("curl_cffi Chrome", "chrome146"))


def _jwt_scadenza(token):
    """datetime UTC di scadenza di un JWT Vinted, o None se illeggibile."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload_b64)).get("exp")
        return datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    except Exception:
        return None


def _descrivi_token(nome, token):
    if not token:
        return f"{nome}: assente"
    scad = _jwt_scadenza(token)
    if scad is None:
        return f"{nome}: presente ma illeggibile"
    ore = (scad - datetime.now(timezone.utc)).total_seconds() / 3600
    quando = scad.strftime("%d/%m %H:%M UTC")
    if ore <= 0:
        return f"{nome}: SCADUTO il {quando}"
    return f"{nome}: valido fino al {quando} (tra {ore:.0f}h)" if ore < 72 else \
        f"{nome}: valido fino al {quando} (tra {ore / 24:.0f} giorni)"


def _classifica_esito_visuale(status, url_finale, testo=""):
    """Da status + URL finale dopo i redirect a un esito leggibile e
    all'eventuale search_by_image_id."""
    url_finale = url_finale or ""
    m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", url_finale)
    if m:
        return "OK", m.group(1)
    if "/member/register" in url_finale or "/member/login" in url_finale or "/session-refresh" in url_finale:
        return "rimandato al login (sessione non accettata)", None
    if status == 403:
        return "403 bloccato (Datadome)", None
    if status and status >= 400:
        return f"HTTP {status}", None
    return f"HTTP {status}, nessun search_by_image_id nell'URL finale ({url_finale[:120]})", None


def _conta_articoli_catalogo(html_catalogo):
    """Articoli reali nella pagina catalogo, con la stessa regex della
    ricerca comp testuale."""
    return len(_articoli_vinted(html_catalogo))


async def _prova_visuale_httpx(url_intermedio, headers, cookies):
    t0 = time.time()
    try:
        resp = await hc._CLIENT_VINTED_AUTH.get(url_intermedio, headers=headers, cookies=cookies, timeout=20)
        esito, sbi = _classifica_esito_visuale(resp.status_code, str(resp.url))
        return {"esito": esito, "id": sbi, "durata": time.time() - t0, "articoli": None}
    except Exception as e:
        return {"esito": f"errore {type(e).__name__}: {e}", "id": None, "durata": time.time() - t0, "articoli": None}


async def _prova_visuale_curl(impersonate, url_intermedio, headers, cookies, proxy):
    t0 = time.time()
    # Niente User-Agent/Accept nostri: li imposta curl_cffi coerenti con
    # l'impronta scelta (un UA iPhone sopra un'impronta Chrome sarebbe di
    # nuovo un'incoerenza).
    headers_curl = {k: v for k, v in headers.items() if k.lower() not in ("user-agent", "accept")}
    try:
        async with CurlAsyncSession(impersonate=impersonate, proxy=proxy, timeout=20) as sess:
            resp = await sess.get(url_intermedio, headers=headers_curl, cookies=cookies, allow_redirects=True)
            esito, sbi = _classifica_esito_visuale(resp.status_code, str(resp.url))
            articoli = None
            if sbi:
                # Controprova: la pagina risultati deve contenere articoli veri.
                resp_cat = await sess.get(
                    f"https://www.vinted.it/catalog?search_by_image_id={sbi}",
                    headers={k: v for k, v in headers_curl.items() if not k.lower().startswith("sec-fetch-user")},
                    cookies=cookies, allow_redirects=True,
                )
                articoli = _conta_articoli_catalogo(resp_cat.text) if resp_cat.status_code == 200 else f"HTTP {resp_cat.status_code}"
            return {"esito": esito, "id": sbi, "durata": time.time() - t0, "articoli": articoli}
    except Exception as e:
        return {"esito": f"errore {type(e).__name__}: {e}", "id": None, "durata": time.time() - t0, "articoli": None}


async def _prova_pagina_riservata(nome, url, cookies, impersonate=None, proxy=None):
    """Controllo di riferimento (2026-09-29): una pagina che richiede il login
    (la posta in arrivo) con gli STESSI cookie della ricerca visuale. Serve a
    separare "la sessione dell'account non viene accettata affatto" da "solo
    /search_by_image la rifiuta". impersonate=None -> httpx (client auth)."""
    t0 = time.time()
    try:
        if impersonate is None:
            resp = await hc._CLIENT_VINTED_AUTH.get(url, cookies=cookies, timeout=20)
        else:
            async with CurlAsyncSession(impersonate=impersonate, proxy=proxy, timeout=20) as sess:
                resp = await sess.get(url, cookies=cookies, allow_redirects=True)
        finale = str(resp.url)
        rimandato = any(x in finale for x in ("/member/register", "/member/login", "/session-refresh"))
        esito = f"rimandato al login ({finale[:90]})" if rimandato else f"HTTP {resp.status_code}, pagina caricata (sessione accettata)"
        return f"{'❌' if rimandato else '✅'} {nome}: {esito} ({time.time() - t0:.1f}s)"
    except Exception as e:
        return f"❌ {nome}: errore {type(e).__name__}: {e} ({time.time() - t0:.1f}s)"


async def testa_ricerca_visuale(url_annuncio):
    """Ritorna le righe del resoconto per Telegram."""
    righe = ["🔎 Test ricerca visuale", url_annuncio, ""]
    righe.append(_descrivi_token("Access token", _VINTED_COOKIES.get("access_token_web")))
    righe.append(_descrivi_token("Refresh token", _VINTED_COOKIES.get("refresh_token_web")))
    righe.append(f"VISUAL_SEARCH_ATTIVA in pipeline: {'si' if VISUAL_SEARCH_ATTIVA else 'no'}")
    righe.append(
        f"Cookie di sessione extra (VINTED_COOKIES_EXTRA): "
        f"{', '.join(sorted(n for n in VINTED_COOKIES_EXTRA if n not in ('access_token_web', 'refresh_token_web'))) or 'nessuno'}"
    )

    if _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
        if _jwt_scaduto(_VINTED_COOKIES.get("refresh_token_web")):
            righe += ["", "❌ Entrambi i token scaduti o assenti: serve un nuovo login dal browser "
                          "con l'account dedicato (cookie access_token_web e refresh_token_web)."]
            return righe
        async with _vinted_refresh_lock:
            ok_refresh = await _rinnova_token_vinted()
        righe.append(f"Rinnovo automatico dell'access token: {'riuscito' if ok_refresh else 'FALLITO'}")
        if ok_refresh:
            righe.append(_descrivi_token("Nuovo access token", _VINTED_COOKIES.get("access_token_web")))
        else:
            righe.append("(proseguo lo stesso: l'esito sotto dira' se la sessione viene accettata)")

    item_id = _estrai_item_id_da_url(url_annuncio)
    scraped = await scrape_vinted_listing(url_annuncio)
    photo_id = scraped.get("cover_photo_id")
    if not item_id or not photo_id:
        righe += ["", f"❌ Non riesco a leggere item id / foto dall'annuncio (item_id={item_id}, "
                      f"photo_id={photo_id}): pagina annuncio non raggiunta?"]
        return righe

    url_intermedio = f"https://www.vinted.it/items/{item_id}/search_by_image?photo_id={quote(photo_id)}"
    headers = {
        "Referer": f"https://www.vinted.it/items/{item_id}",
        "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-User": "?1",
        "Accept-Language": VINTED_HEADERS.get("Accept-Language", "it-IT,it;q=0.9"),
    }
    cookies = {k: v for k, v in _VINTED_COOKIES.items() if v}
    proxy = PROXY_LIST[0] if PROXY_LIST else None
    righe.append(f"Proxy usato da tutti i client: {_etichetta_proxy(proxy) if proxy else 'nessuno (IP Railway)'}")
    righe.append("")

    # Controllo di riferimento: la sessione e' accettata da una pagina
    # riservata qualunque? (vedi _prova_pagina_riservata)
    righe.append("Controllo sessione su pagina riservata (posta in arrivo):")
    righe.append(await _prova_pagina_riservata("httpx + proxy", "https://www.vinted.it/inbox", cookies))
    if CurlAsyncSession is not None:
        righe.append(await _prova_pagina_riservata(
            "curl_cffi Safari + proxy", "https://www.vinted.it/inbox", cookies, "safari184_ios", proxy))
        righe.append(await _prova_pagina_riservata(
            "curl_cffi Safari SENZA proxy (IP Railway)", "https://www.vinted.it/inbox", cookies, "safari184_ios", None))
    righe.append("")
    righe.append("Ricerca visuale:")

    prove = [("httpx (attuale)", _prova_visuale_httpx(url_intermedio, headers, cookies))]
    if CurlAsyncSession is None:
        righe.append("⚠️ curl_cffi non installato: manca in requirements.txt?")
    else:
        prove += [(nome, _prova_visuale_curl(imp, url_intermedio, headers, cookies, proxy))
                  for nome, imp in VARIANTI_CURL_TEST_VISUALE]
    # In sequenza, non in parallelo: tre richieste simultanee dallo stesso
    # proxy con lo stesso account sarebbero gia' di per se' sospette.
    for nome, coro in prove:
        r = await coro
        icona = "✅" if r["id"] else "❌"
        riga = f"{icona} {nome}: {r['esito']} ({r['durata']:.1f}s)"
        if r["articoli"] is not None:
            riga += f" · risultati: {r['articoli']} articoli"
        righe.append(riga)
        await asyncio.sleep(2)
    log.info("TEST VISUALE %s:\n%s", url_annuncio, "\n".join(righe))
    return righe



async def on_comando_test_visuale(event):
    try:
        url = extract_url_from_text(event.raw_text or "")
        if not url:
            await event.respond("Uso: /test_visuale <link annuncio Vinted>")
            return
        await event.respond("🔎 Provo la ricerca visuale con httpx e curl_cffi, un attimo...")
        righe = await testa_ricerca_visuale(url)
        for pezzo in _spezza_per_telegram("\n".join(righe)):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /test_visuale:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Test visuale fallito per un errore interno, vedi i log Railway.")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# STIMA UMANA E RAPPORTO FAIR VALUE
# ---------------------------------------------------------------------------
_RE_STIMA_UMANA = re.compile(r"^\s*(?:stima\s*)?(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)?\s*$", re.IGNORECASE)


def _id_utente_del_bot():
    try:
        return int(str(TELEGRAM_BOT_TOKEN).split(":")[0])
    except (ValueError, TypeError):
        return None


def _url_annuncio_da_messaggio(msg):
    """URL Vinted di un messaggio del bot: dal testo (verdetto) o dal
    bottone 'Apri su Vinted' (scheda)."""
    url = extract_url_from_text(getattr(msg, "raw_text", "") or "")
    if url:
        return url
    for riga in (getattr(msg, "buttons", None) or []):
        for bottone in riga:
            candidato = getattr(bottone, "url", None)
            if candidato and "/items/" in candidato:
                return candidato
    return None




async def on_stima_umana(event):
    """Rispondi alla scheda (o al verdetto) del bot con un numero: e' la tua
    stima di vendita reale, registrata come campione ad alto peso."""
    try:
        if not event.is_reply:
            return
        risposta = parse_risposta(event.raw_text or "")
        originale = await event.get_reply_message()
        bot_id = _id_utente_del_bot()
        if not originale or bot_id is None or originale.sender_id != bot_id:
            return
        url = _url_annuncio_da_messaggio(originale)
        item_id = _estrai_item_id_da_url(url) if url else None
        if not item_id:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                "⚠️ Non trovo il link dell'annuncio in quel messaggio: rispondi alla scheda o al verdetto.",
                disable_notification=True)
            return
        if risposta is None:
            # non e' un giudizio/prezzo: e' un commento libero, lo conservo per il recap
            registra_nota(item_id, event.raw_text or "", _ctx_item(str(item_id)))
            await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, "📝 Nota registrata", disable_notification=True)
            return
        giudizio, valore = risposta
        giudizio = giudizio or (_contesti.get(str(item_id)) or {}).get("_giudizio")
        registra_feedback(item_id, giudizio, valore, "risposta", _ctx_item(str(item_id)))
        if valore is None:
            await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, f"✅ Registrato: {giudizio}", disable_notification=True)
            return
        d = fv_unisci(_fv_leggi()).get(str(item_id), {})
        pezzi = [f"✅ Stima registrata: {valore:.0f} €"]
        rap, gem = d.get("rapida") or {}, d.get("gemini") or {}
        if rap.get("fv"):
            pezzi.append(f"giudizio rapido {rap['fv']} €")
        if gem.get("vendita"):
            pezzi.append(f"Gemini {gem['vendita']:.0f} €")
        await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, " · ".join(pezzi), disable_notification=True)
    except Exception:
        log.error("Errore nella stima umana:\n%s", traceback.format_exc())


async def on_comando_report_fv(event):
    try:
        for pezzo in _spezza_per_telegram(fv_rapporto()):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /report_fv:\n%s", traceback.format_exc())


URL_TEST_PROXY_DEFAULT = "https://www.vinted.it/catalog?order=newest_first"


async def testa_pool_proxy(url_test=None, timeout=15, max_concorrenza=10):
    """Testa OGNI client del pool proxy con una singola richiesta (nessun
    retry: un fallimento qui e' il dato, non un errore da nascondere), con
    una concorrenza limitata (max_concorrenza) per non sparare 53 richieste
    simultanee su Vinted -- oltre a essere piu' prudente, e' anche piu'
    realistico rispetto al traffico normale della pipeline, che non usa mai
    tutti i proxy nello stesso istante.

    Ritorna una lista di dict, uno per proxy, nello stesso ordine del pool:
    {"etichetta", "ok", "status", "durata_s", "len_html", "dettaglio"}."""
    url = url_test or URL_TEST_PROXY_DEFAULT
    sem = asyncio.Semaphore(max_concorrenza)
    risultati = [None] * len(_CLIENT_VINTED_POOL)

    async def _test_uno(indice):
        client_proxy = _CLIENT_VINTED_POOL[indice]
        chiave = _CLIENT_VINTED_POOL_KEYS[indice]
        etichetta = _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave)
        async with sem:
            # t0 DENTRO il semaforo (fix 2026-09-27, primo test reale: 6.8s di
            # media perche' contava anche l'attesa in coda del proprio turno
            # tra i 10 slot paralleli, non la sola risposta del proxy).
            t0 = time.time()
            try:
                resp = await client_proxy.get(url, headers=VINTED_HEADERS, timeout=timeout)
                durata = time.time() - t0
                testo = _estrai_articoli_da_alt_vinted(resp.text)
                ok = resp.status_code == 200 and MARKER_NESSUN_ARTICOLO_VINTED not in testo
                if ok:
                    dettaglio = None
                elif resp.status_code != 200:
                    dettaglio = f"HTTP {resp.status_code}"
                else:
                    dettaglio = "200 ma nessun articolo estratto (probabile pagina di blocco/verifica)"
                risultati[indice] = {
                    "etichetta": etichetta, "ok": ok, "status": resp.status_code,
                    "durata_s": durata, "len_html": len(resp.text), "dettaglio": dettaglio,
                }
            except Exception as e:
                risultati[indice] = {
                    "etichetta": etichetta, "ok": False, "status": None,
                    "durata_s": time.time() - t0, "len_html": 0,
                    "dettaglio": f"{type(e).__name__}: {e}",
                }

    await asyncio.gather(*(_test_uno(i) for i in range(len(_CLIENT_VINTED_POOL))))
    return risultati


def _formatta_risultati_test_proxy(risultati):
    """Testo leggibile per Telegram: totale, poi un elenco -- prima i
    falliti (quelli che servono davvero attenzione), poi i funzionanti in
    breve. Pura, testabile senza rete."""
    if not risultati:
        return "Nessun proxy nel pool (PROXY_LIST vuota -- richieste dirette senza proxy)."
    ok_list = [r for r in risultati if r["ok"]]
    ko_list = [r for r in risultati if not r["ok"]]
    durata_media_ok = (sum(r["durata_s"] for r in ok_list) / len(ok_list)) if ok_list else 0.0
    righe = [
        f"🔍 Test proxy: {len(ok_list)}/{len(risultati)} funzionanti"
        f"{f', tempo medio {durata_media_ok:.1f}s' if ok_list else ''}."
    ]
    if ko_list:
        righe.append(f"\n❌ Falliti ({len(ko_list)}):")
        for r in ko_list:
            righe.append(f"  {r['etichetta']}: {r['dettaglio']}")
    if ok_list:
        righe.append(f"\n✅ Funzionanti ({len(ok_list)}):")
        righe.append("  " + ", ".join(r["etichetta"] for r in ok_list))
    return "\n".join(righe)



async def on_comando_venduto(event):
    """/venduto <url annuncio Vinted>: legge la pagina con i proxy del bot e mostra stato, prezzo letto,
    segnali e ogni istante recente trovato (diagnostica del tracciamento vendite, 2026-10-03)."""
    try:
        url = event.pattern_match.group(1).strip()
        if "vinted." not in url:
            await event.respond("Mi serve un link di un annuncio vinted.", parse_mode=None)
            return
        await event.respond("Leggo la pagina, un attimo...", parse_mode=None)
        http_status, html_pagina = await _tracc_leggi_pagina(url, max_retries=3)
        segnali, prezzo = _tracc_estrai_segnali(html_pagina)
        candidati = trova_timestamp_candidati(html_pagina)
        adesso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        testo = (f"HTTP {http_status} | stato={_tracc_stato(http_status, segnali)} | prezzo letto={prezzo}\n"
                 f"Segnali: {segnali or 'nessuno'}\n\nIstanti recenti trovati (adesso {adesso} UTC):\n"
                 + ("\n".join(candidati[:25]) or "nessuno"))
        log.info("DIAG VENDUTO | url=%s | http=%s | prezzo=%s | segnali=%s | istanti=%s", url, http_status,
                 prezzo, segnali, " ## ".join(candidati))
        for pezzo in _spezza_per_telegram(testo):
            await event.respond(pezzo, parse_mode=None)
    except Exception:
        log.error("Errore nel comando /venduto:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Comando /venduto fallito, vedi i log Railway.", parse_mode=None)
        except Exception:
            pass


async def on_comando_report_radar(event):
    """/report_radar [ore=24]: report per ricerca dal DB (verdetti, gialli/verdi, scarto piu' frequente, candidate alla potatura)."""
    try:
        ore = max(1, int(event.pattern_match.group(1) or 24))
        await event.respond(_testo_report_radar(ore), parse_mode='md')
    except Exception:
        log.warning("REPORT RADAR fallito:\n%s", traceback.format_exc())


async def on_comando_esporta_radar(event):
    """/esporta_radar [giorni=7]: invia il CSV di tutti gli esiti del radar salvati nel DB (volume /data) e scrive nei log
    una riga RIEPILOGO RICERCHE per ricerca (annunci, validi, venduti entro 1 h, gialli/verdi): niente estrazioni dai log."""
    try:
        giorni = int(event.pattern_match.group(1) or 7)
        eventi = db.leggi_eventi("tracciato_radar", time.time() - giorni * 86400)
        for riga in archivio_radar.righe_riepilogo(eventi, giorni):
            log.info(riga)
        from io import BytesIO
        f = BytesIO(archivio_radar.righe_csv(eventi).encode("utf-8"))
        f.name = f"radar_esiti_{giorni}g.csv"
        await client.send_file(event.chat_id, f, caption=f"Esiti radar ultimi {giorni} giorni: {len(eventi)} annunci")
    except Exception:
        log.warning("ESPORTA RADAR fallito:\n%s", traceback.format_exc())


async def on_comando_velocita(event):
    """/velocita: aggiorna ora la tabella di velocita' di vendita dall'archivio `tracciato` del DB (volume /data) e mostra il riepilogo."""
    try:
        await event.respond(_aggiorna_velocita_db(), parse_mode=None)
    except Exception:
        log.warning("VELOCITA fallita:\n%s", traceback.format_exc())


async def on_comando_operazione(event):
    """/comprato <item|url> <prezzo> [costi] e /rivenduto <item|url> <prezzo> [giorni]: registra acquisto e vendita reali
    (tappa 5). La stima del bot per l'annuncio si legge dall'ultimo evento `radar_v2`; senza, il campo resta vuoto."""
    try:
        op = parse_operazione(event.raw_text)
        if not op:
            await event.respond("Uso: /comprato <link o id> <prezzo> [costi] oppure /rivenduto <link o id> <prezzo> [giorni]", parse_mode=None)
            return
        stima = None
        for ev in reversed(db.leggi_eventi("radar_v2", limite=100000)):
            if str(ev.get("item_id")) == op["item"]:
                stima = ev.get("rivendita")
                break
        dati = {**op, "stima_bot": stima}
        if op["tipo"] == "rivendita":
            acq = [e for e in db.leggi_eventi("operazione") if e.get("item_id") == op["item"] and e.get("tipo") == "acquisto"]
            if acq:
                dati["margine"], dati["roi"] = margine_reale(acq[-1]["prezzo"], acq[-1].get("extra"), op["prezzo"])
        db.scrivi_evento("operazione", op["item"], None, dati)
        log.info("OPERAZIONE | " + " | ".join(f"{k}={v}" for k, v in dati.items() if v is not None))
        await event.respond(f"Registrato {op['tipo']} {op['item']} a {op['prezzo']:g} EUR"
                            + (f" (margine reale {dati['margine']:g} EUR, ROI {dati['roi']}%)" if dati.get("margine") is not None else ""),
                            parse_mode=None)
    except Exception:
        log.error("Errore nel comando operazione:\n%s", traceback.format_exc())


async def on_comando_test_proxy(event):
    """Comando digitato dal proprietario in QUALSIASI chat (e' il suo stesso
    account Telethon: un messaggio 'outgoing' puo' venire solo da lui, da
    qualunque dispositivo) -- risponde nella STESSA chat via event.respond,
    senza passare dal bot Telegram separato (niente accoppiamento con
    TELEGRAM_OWNER_CHAT_ID, che comunque e' un ID diverso da questo lato).
    NON richiede modifiche a PROXY_LIST ne' deploy: gira sul pool gia'
    attivo in produzione in questo momento."""
    try:
        await event.respond(f"🔍 Test di {len(_CLIENT_VINTED_POOL)} proxy in corso, un attimo...")
        risultati = await testa_pool_proxy()
        testo = _formatta_risultati_test_proxy(risultati)
        for pezzo in _spezza_per_telegram(testo):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /test_proxy:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Test proxy fallito per un errore interno, vedi i log Railway.")
        except Exception:
            pass


async def on_comando_test_chiavi(event):
    """/test_chiavi: prova le chiavi di GEMINI_API_KEYS gia' caricate nel worker e risponde solo con numero ed esito (mai la chiave)."""
    try:
        risultati = await testa_chiavi_gemini()
        righe = [f"{'✅' if e == 'valida' else '⚠️' if 'valida' in e.lower() and 'NON' not in e else '❌'} Chiave #{i}: {e}" for i, e in risultati]
        buone = sum(1 for _, e in risultati if e.startswith("valida"))
        await event.respond(f"🔑 Chiavi Gemini nel worker: {len(risultati)}, valide {buone}\n" + "\n".join(righe))
    except Exception:
        log.error("Errore nel comando /test_chiavi:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Test chiavi fallito per un errore interno, vedi i log Railway.")
        except Exception:
            pass
