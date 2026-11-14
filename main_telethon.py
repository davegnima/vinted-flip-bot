"""
Vinted Flip Oracle Bot (userbot Telethon): riceve gli annunci dai tracker, li valuta e manda l'avviso su Telegram.
Moda: semaforo (stima rapida) -> Jev sui comparabili -> Gemini gratuito sulle foto. Radar: bot/radar.py.
Questo file ha il client Telethon, i comandi, main() e un blocco di re-export (i test usano m.NOME).
"""

import os
import sys
import time
import asyncio
import signal
import logging
import traceback

from telethon import events

from bot.db import DB_FILE
from bot.gemini_stato import ripristina_stato_gemini
from bot.tracciamento import importa_tracciamento_jsonl, tracc_riprendi_serie
from bot.feedback import ciclo_callback
from bot.radar_v2 import analizza as radar_v2_analizza, rivaluta as radar_v2_rivaluta
from bot.radar_messaggi import e_avviso_proprio
from bot.radar import RADAR_CHAT_IDS, RADAR_RISPOSTA_GRUPPO, RADAR_CANCELLA_SCARTI, da_cancellare, testo_risposta_gruppo, radar_in_pausa, e_messaggio_radar, gestisci_annuncio_radar, traccia_verdetto_v2, invia_verdetto_v2, risolvi_gruppo_radar, togli_marcatore
from bot.costanti import (
    VINTED_HEADERS,
)  # noqa: F401  (re-export)

from bot.logger import (
    log,
)  # noqa: F401  (re-export)

from bot.config import (
    VISUAL_SEARCH_ATTIVA,
    VINTED_TRACKER_NAME_HINTS,
    BOT_VERSION,
    GEMINI_API_KEY,
    GEMINI_MODEL_OCCHIO,
    TELEGRAM_ALERT_CHAT_ID,
    TELEGRAM_API,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_ID,
    TELEGRAM_OWNER_CHAT_ID,
    TELEGRAM_SESSION_STRING,
)  # noqa: F401  (re-export)

from bot.testo import (
    _normalizza_titolo_per_dedup,
)  # noqa: F401  (re-export)


from bot.fair_value import (
    FAIR_VALUE_APPRESO,
    FAIR_VALUE_APPRESO_FILE,
    FAIR_VALUE_LOG_FILE,
    _fv_leggi,
    _jsonl_read,
    fv_carica_appreso,
    fv_rapporto,
    fv_ricalibra,
    fv_unisci,
    stima_fair_value,
)  # noqa: F401  (re-export)

from bot.filtri import (
    check_skip_pre_gemini,
)  # noqa: F401  (re-export)

from bot.gemini_stato import (
    GEMINI_API_KEYS,
    GEMINI_CASCATA,
    GEMINI_CASCATA_OCCHIO,
    _gemini_key_attuale,
    _gemini_key_in_quota_esaurita,
    _gemini_key_index,
    _gemini_key_quota_esaurita_fino,
    _gemini_modello_escluso_fino,
    _gemini_secondi_retry,
    _gemini_segna_key_quota_esaurita,
    _gemini_url_effettivo,
)  # noqa: F401  (re-export)

from bot.proxy import (
    PROXY_LIST,
    _CLIENT_VINTED_POOL,
    _CLIENT_VINTED_POOL_KEYS,
    _ETICHETTA_PER_CHIAVE_PROXY,
    _etichetta_proxy,
)  # noqa: F401  (re-export)

from bot.http_clients import (
    chiudi_client_http,
    inizializza_client_http,
)  # noqa: F401  (re-export)

from bot.telegram_api import (
    _spezza_per_telegram,
    telegram_edit_message,
    telegram_send_media_group,
    telegram_send_message,
    telegram_send_photo,
    telegram_send_with_buttons,
)  # noqa: F401  (re-export)

from bot.parsing import (
    _estrai_item_id_da_url,
    TITOLO_NON_RILEVATO,
    _brand_da_titolo,
    extract_url_from_text,
    parse_vinted_tracker_message,
    url_da_bottoni,
    url_da_entita,
)  # noqa: F401  (re-export)


from bot.vinted_http import (
    VINTED_COOKIES_EXTRA,
    _VINTED_COOKIES,
    _jwt_scaduto,
    _rinnova_token_vinted,
    _vinted_get_con_retry,
    _vinted_refresh_lock,
)  # noqa: F401  (re-export)

from bot.tracciamento import (
    TRACCIAMENTO_ATTIVO,
    TRACCIAMENTO_FILE,
    TRACCIAMENTO_SERIE_SECONDI,
    _tracc_bucket,
    _tracc_classe,
    _tracc_estrai_segnali,
    _tracc_item_visti,
    _tracc_leggi_pagina,
    _tracc_scrivi,
    _tracc_serie,
    _tracc_stato,
    _tracc_stop,
    tracc_avvia_serie,
    trova_timestamp_candidati,
)  # noqa: F401  (re-export)

from bot.vinted_scrape import (
    scrape_vinted_listing,
)  # noqa: F401  (re-export)

from bot.foto import (
    optimize_image_bytes,
)  # noqa: F401  (re-export)

from bot.gemini_api import (
    testa_chiavi_gemini,
    chiama_gemini,
)  # noqa: F401  (re-export)


from bot.comps_filtri import (
    _articoli_vinted,
    _estrai_articoli_da_alt_vinted,
)  # noqa: F401  (re-export)

from bot.comps import (
    MARKER_NESSUN_ARTICOLO_VINTED,
    _cerca_vinted_testo_diretto,
)  # noqa: F401  (re-export)

from bot.scheda import (
    _descrizione_utile,
    _riga_caricato_annuncio,
)  # noqa: F401  (re-export)

from bot.pipeline import (
    process_listing,
)  # noqa: F401  (re-export)

from bot.client_tg import client  # noqa: F401  (re-export)

from bot.cicli import (
    ARRESTO_ATTESA_MAX_S,
    BLOCCO_SECONDI,
    _analisi_attive,
    _arresto_ordinato,
    _aggiorna_velocita_db,
    _battito,
    _battito_loop,
    _testo_report_radar,
    _thread_blocco,
    ciclo_report_radar,
    ciclo_velocita,
    processo_bloccato,
)  # noqa: F401  (re-export)

from bot.comandi import (
    URL_TEST_PROXY_DEFAULT,
    _formatta_risultati_test_proxy,
    on_comando_esporta_radar,
    on_comando_operazione,
    on_comando_report_fv,
    on_comando_report_radar,
    on_comando_test_chiavi,
    on_comando_test_proxy,
    on_comando_test_visuale,
    on_comando_velocita,
    on_comando_venduto,
    on_stima_umana,
    testa_pool_proxy,
    testa_ricerca_visuale,
)  # noqa: F401  (re-export)

# MIGRAZIONE AD ASYNCIO (2026-09-19)
# ----------------------------------
# Telethon e' un framework interamente asincrono: ogni chiamata di rete
# sincrona (requests) e ogni pausa bloccante (time.sleep) eseguite nel suo
# loop fermano TUTTO il bot, compresa la ricezione di nuovi messaggi dal
# tracker. Nella versione precedente process_listing girava dentro
# asyncio.to_thread, il che evitava il blocco del loop ma serializzava di
# fatto la pipeline su un solo thread per annuncio, con decine di secondi
# di attesa passiva (scraping Vinted, Gemini) durante i quali non
# si poteva iniziare a lavorare l'annuncio successivo.
#
# Ora tutta la rete passa da httpx.AsyncClient e tutte le pause da
# asyncio.sleep, quindi piu' annunci vengono elaborati davvero in
# parallelo e le attese di rete non costano nulla. Il rate-limit verso
# Vinted resta una difesa voluta contro il 403 (vedi _attendi_turno_vinted
# piu' sotto), ma dal 2026-09-21 e' pacata PER PROXY invece che con un
# unico lock globale: con un lock globale, annunci multipli in lavorazione
# contemporanea (proprio il caso normale in un momento di traffico intenso,
# quello in cui perdere tempo costa un affare gia' comprato da qualcun
# altro) si mettevano in coda TUTTI insieme su un'unica pausa minima
# condivisa, anche usando 53 proxy diversi che a quel punto non
# accodavano il traffico, lo attendevano soltanto. La stessa pausa minima
# per singolo IP resta identica (nessuna riduzione della protezione
# anti-403 per-proxy), cambia solo che IP diversi non si aspettano piu'
# a vicenda.
#
# NOTA httpx >= 0.28: il vecchio parametro "proxies" (plurale, dict) e'
# stato rimosso. La rotazione proxy e' quindi implementata con un client
# per proxy, costruiti una volta sola all'avvio (vedi _CLIENT_VINTED_POOL).

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------


# ESCLUSIONI VOLUTE (non mappare per evitare falsi positivi o capi di scarso valore):
# - Maje, John Smedley, Alberta Ferretti, Romeo Gigli, Gianfranco Ferre: rimossi il 2026-10-01
#   dopo aver analizzato i verdetti reali (~7h di log): zero annunci sopra i 50 EUR di margine
#   (Maje 0/22, margine medio ~ -1 EUR). Non sono un errore: dati alla mano non rendono.
# - Sandro: rimosso il 2026-10-01 su indicazione dell'utente (il bot ne sovrastimava il prezzo di
#   rivendita). Tolto anche dalla query 2 di Vinted-Notifications.
# - Ganni, Arc'teryx: rimossi il 2026-10-02 su approvazione dell'utente dopo il primo giorno di log
#   ESITO (Ganni 7 NON COMPRARE su 8, venditori a 85-120 EUR per capi da 55-90; Arc'teryx
#   margini intorno a zero, 1 TRATTA su 5). Tolti anche dalle query 2 e 4 di Vinted-Notifications.
# - Jil Sander, Our Legacy, Drumohr: rimossi il 2026-10-03 su approvazione dell'utente (primo giorno
#   completo di log ESITO: 0 annunci su 29 con margine >=50 EUR e ROI >=100%). Tolti anche dalle query
#   di Vinted-Notifications.
# - "céline"/"celine": l'utente segnala troppo rumore su Vinted -- molti annunci di altri
#   brand vengono taggati per errore come Céline dai venditori, quindi la ricerca comp per
#   brand_id risulterebbe inquinata. Scelta esplicita di non mapparlo, non una dimenticanza.
# - "saint laurent" (post-2012, id 83122): altissimo rischio fake, preferiamo concentrarci su YSL vintage.
# - "McQ" (id 849677): diffusion line di Alexander McQueen, valore di mercato molto inferiore.
# - "See by Chloé" (id 1472883): diffusion line di Chloé, satura e con basso ROI.


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

_processed_message_ids = set()
_recent_listings_seen = {}

DEDUP_CONTENUTO_WINDOW_SECONDS = 300



def _chiavi_dedup(parsed, url=None):
    """Chiavi con cui un annuncio viene riconosciuto come gia' visto. Pura,
    testabile senza rete.

    FIX 2026-09-27: prima la chiave era SOLO (titolo normalizzato, brand,
    prezzo). Quando il messaggio del tracker non si parsava, tutti gli
    annunci diventavano ("titolo non", "", "") -- "Titolo non rilevato" meno
    l'ultima parola, brand e prezzo vuoti -- e per 5 minuti solo il PRIMO
    veniva elaborato, gli altri scartati come "varianti". Ora:
    - l'item id Vinted (dall'URL) e' sempre una chiave: lo stesso annuncio
      ricevuto due volte e' un doppione certo;
    - la chiave per contenuto (che serve a riconoscere le varianti dello
      stesso capo ripubblicate con id diversi) si usa solo se il parsing
      ha trovato un titolo vero E almeno brand o prezzo -- altrimenti
      annunci diversi collasserebbero sulla stessa chiave vuota."""
    chiavi = []
    item_id = _estrai_item_id_da_url(url)
    if item_id:
        chiavi.append(("item_id", item_id))
    titolo = parsed.get("title")
    brand = (parsed.get("brand") or "").strip().lower()
    prezzo = (parsed.get("price") or "").strip()
    if titolo and titolo != TITOLO_NON_RILEVATO and (brand or prezzo):
        chiavi.append(("contenuto", _normalizza_titolo_per_dedup(titolo), brand, prezzo))
    return chiavi


def e_variante_recente(parsed, url=None):
    chiavi = _chiavi_dedup(parsed, url)
    now = time.time()
    scadute = [k for k, ts in _recent_listings_seen.items() if now - ts > DEDUP_CONTENUTO_WINDOW_SECONDS]
    for k in scadute:
        del _recent_listings_seen[k]
    if any(k in _recent_listings_seen for k in chiavi):
        return True
    for k in chiavi:
        _recent_listings_seen[k] = now
    return False


# CONTROLLO DI SALUTE (11/10: il worker ha smesso di ricevere i messaggi del tracker per quasi 3 ore, senza errori): ultimo
# messaggio del gruppo ricevuto e suo id; il watchdog (vedi sotto) riavvia il processo se Telegram ne ha di piu' recenti.
_ultimo_msg_gruppo = {"t": time.time(), "id": 0}
WATCHDOG_MINUTI = float(os.environ.get("WATCHDOG_MINUTI", "10") or 0)


async def watchdog_messaggi():
    """Ogni minuto, se per oltre WATCHDOG_MINUTI (0 = spento) non arriva nulla dal gruppo del tracker (fuori dalla pausa notturna),
    chiede a Telegram l'ultimo messaggio: se e' piu' recente di quello visto, il client Telethon ha perso gli aggiornamenti e
    il processo esce (Railway lo riavvia; le serie di ricontrolli sono nel DB). Mai in pausa notturna. Non solleva."""
    if WATCHDOG_MINUTI <= 0:
        return
    try:
        ultimo = await client.get_messages(TELEGRAM_GROUP_ID, limit=1)
        if ultimo:
            _ultimo_msg_gruppo["id"] = max(_ultimo_msg_gruppo["id"], ultimo[0].id)
    except Exception:
        log.warning("WATCHDOG | ultimo messaggio non letto all'avvio:\n%s", traceback.format_exc())
    while True:
        await asyncio.sleep(60)
        try:
            if radar_in_pausa() or time.time() - _ultimo_msg_gruppo["t"] < WATCHDOG_MINUTI * 60:
                continue
            ultimo = await asyncio.wait_for(client.get_messages(TELEGRAM_GROUP_ID, limit=1), 30)
            if ultimo and ultimo[0].id > _ultimo_msg_gruppo["id"]:
                log.error("WATCHDOG | nessun messaggio ricevuto da %.0f min ma Telegram ne ha di nuovi (id %s > %s): "
                          "aggiornamenti persi, riavvio del processo", (time.time() - _ultimo_msg_gruppo["t"]) / 60,
                          ultimo[0].id, _ultimo_msg_gruppo["id"])
                logging.shutdown()
                os._exit(1)
            _ultimo_msg_gruppo["t"] = time.time()   # davvero silenzio: ricontrolla fra altri WATCHDOG_MINUTI
        except asyncio.TimeoutError:
            log.error("WATCHDOG | Telegram non risponde da 30 s: riavvio del processo")
            logging.shutdown()
            os._exit(1)
        except Exception:
            log.warning("WATCHDOG | controllo fallito:\n%s", traceback.format_exc())


# Registrazione dei gestori dei comandi (le funzioni stanno in bot/comandi.py; stesso ordine di prima).
# Il client esiste gia' (bot/client_tg.py): client.on(...)(f) equivale al decoratore @client.on(...).
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/test_?visuale\b'))(on_comando_test_visuale)
client.on(events.NewMessage(outgoing=True))(on_stima_umana)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/report_?fv\b'))(on_comando_report_fv)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/venduto\s+(https?://\S+)'))(on_comando_venduto)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/report_?radar(?:\s+(\d+))?\s*$'))(on_comando_report_radar)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/esporta_?radar(?:\s+(\d+))?\s*$'))(on_comando_esporta_radar)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/velocita\s*$'))(on_comando_velocita)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/(?:comprato|rivenduto)\s+\S+\s+\d'))(on_comando_operazione)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/test_?proxy\b'))(on_comando_test_proxy)
client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/test_?chiavi\b'))(on_comando_test_chiavi)


@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
@client.on(events.NewMessage(func=lambda e: e.chat_id in RADAR_CHAT_IDS and e.chat_id != TELEGRAM_GROUP_ID))
async def on_new_message(event):
    if event.chat_id == TELEGRAM_GROUP_ID:
        _ultimo_msg_gruppo["t"] = time.time()
        _ultimo_msg_gruppo["id"] = max(_ultimo_msg_gruppo["id"], event.message.id)
    # Catturati il piu' presto possibile nell'handler (richiesto dall'utente
    # il 2026-09-21, "monitorare il delay tra ogni step"): t_ricevuto_bot e'
    # il riferimento per quanto ci mette la NOSTRA pipeline (scrape, foto,
    # Occhio, Cervello) fino all'invio della notifica; event.message.date e'
    # il timestamp che Telegram assegna al messaggio del tracker esterno,
    # confrontato in process_listing con created_at (data di pubblicazione
    # Vinted, presa dalla pagina annuncio) per isolare il ritardo che sta
    # PRIMA di noi (pubblicazione -> tracker -> messaggio Telegram), su cui
    # non abbiamo controllo ma che vale la pena vedere separato dal nostro.
    t_ricevuto_bot = time.time()
    msg_date = event.message.date
    stato_pipeline = {}
    try:
        msg_id = event.message.id
        if msg_id in _processed_message_ids:
            log.info("MESSAGGIO SCARTATO | motivo=gia_elaborato | msg_id=%s", msg_id)
            return
        _processed_message_ids.add(msg_id)
        if len(_processed_message_ids) > 500:
            _processed_message_ids.discard(min(_processed_message_ids))

        sender = await event.get_sender()
        if not any(h in ((getattr(sender, "username", "") or "") + " " + (getattr(sender, "first_name", "") or "")).lower() for h in VINTED_TRACKER_NAME_HINTS):
            log.info("MESSAGGIO SCARTATO | motivo=mittente_non_tracker | msg_id=%s | mittente=%s", msg_id,
                     (getattr(sender, "username", "") or getattr(sender, "first_name", "") or "?")[:40])
            return

        text = event.message.message or ""
        # Radar (fase 0, solo osservazione): ricerche fuori dall'abbigliamento, smistate prima della pipeline moda.
        if e_messaggio_radar(text, event.chat_id):
            if e_avviso_proprio(text):
                # Avviso scritto dal bot nel gruppo radar: non e' un annuncio del tracker, resta dov'e'.
                log.info("RADAR AVVISO PROPRIO | msg_id=%s | lasciato nel gruppo", msg_id)
                return
            url_radar = (extract_url_from_text(text) or url_da_bottoni(event.message.buttons, "/items/")
                         or url_da_entita(event.message.entities, "/items/"))
            if not _estrai_item_id_da_url(url_radar):
                # 14/11: a volte Telegram consegna l'annuncio senza i bottoni (Nintendo Switch a 120 EUR rimasta senza verdetto): si rilegge una volta.
                try:
                    await asyncio.sleep(2)
                    riletto = await client.get_messages(event.chat_id, ids=msg_id)
                    url_radar = url_da_bottoni(getattr(riletto, "buttons", None), "/items/") or url_da_entita(getattr(riletto, "entities", None), "/items/")
                except Exception as exc:
                    log.warning("RADAR SENZA ANNUNCIO | rilettura non riuscita msg_id=%s (%s)", msg_id, type(exc).__name__)
            log.info("MESSAGGIO RADAR | msg_id=%s | item=%s", msg_id, _estrai_item_id_da_url(url_radar))
            if not _estrai_item_id_da_url(url_radar):
                # 01/11: messaggi del gruppo radar senza link all'annuncio (non sono annunci) ricevevano la risposta "semaforo non calcolato"
                log.info("RADAR SENZA ANNUNCIO | msg_id=%s | testo=%s", msg_id, text[:200].replace("\n", " / "))
                return
            _analisi_attive["n"] += 1
            try:
                parsed_radar = parse_vinted_tracker_message(togli_marcatore(text))
                # Foto gia' allegata dal tracker al messaggio: niente pagina in piu' da scaricare.
                foto_radar = None
                if event.message.photo:
                    try:
                        foto_radar = await event.message.download_media(file=bytes)
                    except Exception:
                        log.warning("RADAR FOTO | download non riuscito per msg_id=%s", msg_id)
                v2_radar = await radar_v2_analizza(parsed_radar, url_radar, foto=foto_radar,
                                                   query_url=url_da_bottoni(event.message.buttons, "/catalog"))
                traccia_verdetto_v2(parsed_radar, url_radar, v2_radar, t0=t_ricevuto_bot)
                esito_radar = {"saltato": parsed_radar.get("_saltato")} if v2_radar is None else {}
                await invia_verdetto_v2(parsed_radar, url_radar, v2_radar, foto=foto_radar, rivaluta=radar_v2_rivaluta, esito=esito_radar)
                cancellato = False
                if RADAR_CANCELLA_SCARTI and (da_cancellare(v2_radar, esito_radar)):
                    try:
                        await event.delete()
                        cancellato = True
                        log.info("RADAR PULIZIA | cancellato msg_id=%s | item=%s | motivo=%s", msg_id, _estrai_item_id_da_url(url_radar), esito_radar.get("saltato") or (v2_radar or {}).get("motivo") or esito_radar.get("motivo") or "saltato")
                    except Exception as exc:
                        log.warning("RADAR PULIZIA | non cancellabile msg_id=%s (%s): serve il diritto di eliminare messaggi nel gruppo",
                                    msg_id, type(exc).__name__)
                if RADAR_RISPOSTA_GRUPPO and not cancellato:
                    try:
                        testo_gruppo = testo_risposta_gruppo(v2_radar, esito_radar)
                        await event.reply(testo_gruppo, silent=True)
                        log.info("RADAR GRUPPO | risposta msg_id=%s | item=%s | testo=%s", msg_id, _estrai_item_id_da_url(url_radar),
                                 testo_gruppo.replace("\n", " / "))
                    except Exception:
                        log.warning("RADAR RISPOSTA | non inviata per msg_id=%s", msg_id)
                await gestisci_annuncio_radar(parsed_radar, url_radar, t0=t_ricevuto_bot, v2=v2_radar, foto=foto_radar)
            finally:
                _analisi_attive["n"] -= 1
            return
        parsed = parse_vinted_tracker_message(text)

        # URL estratto PRIMA del dedup (fix 2026-09-27): l'item id e' la
        # chiave di dedup piu' affidabile, vedi _chiavi_dedup.
        # solo bottoni /items/: il secondo bottone del tracker ("🔎 Query") porta alla ricerca, non all'annuncio
        url = extract_url_from_text(text) or url_da_bottoni(event.message.buttons, "/items/")
        parsed["query_url"] = (url_da_bottoni(event.message.buttons, "/catalog")
                               or url_da_entita(event.message.entities, "/catalog"))

        # Riga di ricezione: permette di confrontare i messaggi del tracker con gli ESITO e di capire dove si perde
        # un annuncio (ricevuto ma non elaborato, oppure mai ricevuto).
        log.info("MESSAGGIO TRACKER | msg_id=%s | item=%s | titolo=%s | query=%s | link_query=%s", msg_id,
                 _estrai_item_id_da_url(url), (parsed.get("title") or "")[:60], parsed.get("query_name") or "-",
                 "si" if parsed.get("query_url") else "no")
        if e_variante_recente(parsed, url):
            log.info("MESSAGGIO SCARTATO | motivo=variante_recente_5min | msg_id=%s | item=%s | titolo=%s", msg_id,
                     _estrai_item_id_da_url(url), (parsed.get("title") or "")[:60])
            return

        cover = await event.message.download_media(bytes) if event.message.photo else None
        # process_listing e' una coroutine: Telethon esegue ogni handler come task separato, quindi gli annunci
        # si elaborano in parallelo. Il contatore serve all'arresto ordinato (deploy).
        _analisi_attive["n"] += 1
        try:
            await process_listing(parsed, url, cover, msg_date=msg_date, t_ricevuto_bot=t_ricevuto_bot,
                                  stato=stato_pipeline)
        finally:
            _analisi_attive["n"] -= 1
    except Exception:
        log.error("Errore generico:\n%s", traceback.format_exc())
        if stato_pipeline.get("msg_id_galleria") is not None:
            try:
                await telegram_send_message(
                    TELEGRAM_OWNER_CHAT_ID,
                    "⚠️ Analisi interrotta per un errore interno, vedi i log Railway.",
                    reply_to=stato_pipeline["msg_id_galleria"],
                )
            except Exception:
                pass


async def main():
    log.info("Vinted Oracle avviato su Telethon. Versione: %s", BOT_VERSION)
    try:
        from importlib.metadata import version as _v
        log.info("Ambiente: python %s · %s", sys.version.split()[0], " · ".join(
            f"{pkg} {_v(pkg)}" for pkg in ("telethon", "httpx", "Pillow", "brotli", "curl_cffi")))
    except Exception:
        log.warning("Versioni delle dipendenze non leggibili:\n%s", traceback.format_exc())
    log.info("Gemini (foto, moda e radar): %s", GEMINI_MODEL_OCCHIO)
    await inizializza_client_http()
    try:
        from bot import log_db
        if log_db.avvia():
            log.info("LOG DB | storico righe strutturate attivo (tabella log_righe in %s)", DB_FILE)
    except Exception:
        log.warning("Storico log su DB non avviato:\n%s", traceback.format_exc())
    try:
        n_quote, n_esclusi = ripristina_stato_gemini()
        importati = importa_tracciamento_jsonl() if TRACCIAMENTO_ATTIVO else 0
        log.info("DB %s: ripristinati %d cooldown di quota Gemini e %d modelli esclusi; tracciamento importato: %d righe.",
                 DB_FILE, n_quote, n_esclusi, importati)
        riprese = tracc_riprendi_serie()
        if riprese:
            log.info("Tracciamento: riprese %d serie di ricontrolli lasciate a meta' dal riavvio.", riprese)
    except Exception:
        log.warning("DB non inizializzato (il bot prosegue senza persistenza):\n%s", traceback.format_exc())
    if TRACCIAMENTO_ATTIVO:
        _tracc_item_visti.update(str(r.get("item_id")) for r in _jsonl_read(TRACCIAMENTO_FILE, "Tracciamento")
                                 if r.get("tipo") == "valutato")
    try:
        fv_carica_appreso()
        fv_ricalibra()
    except Exception:
        log.warning("Fair value appreso non caricato:\n%s", traceback.format_exc())
    try:
        await client.start()
        await risolvi_gruppo_radar(client)
        asyncio.get_event_loop().create_task(watchdog_messaggi())
        asyncio.get_event_loop().create_task(ciclo_callback())
        asyncio.get_event_loop().create_task(ciclo_report_radar())
        asyncio.get_event_loop().create_task(ciclo_velocita())
        _battito["t"] = time.time()
        asyncio.get_event_loop().create_task(_battito_loop())
        _thread_blocco()
        try:
            _loop = asyncio.get_running_loop()
            _loop.add_signal_handler(signal.SIGTERM, lambda: _loop.create_task(_arresto_ordinato()))
        except (NotImplementedError, RuntimeError):
            log.warning("Arresto ordinato non attivo: SIGTERM non intercettabile su questa piattaforma.")
        await client.run_until_disconnected()
    finally:
        await chiudi_client_http()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
