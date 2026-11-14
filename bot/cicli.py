"""Cicli periodici e controlli di salute del worker (spostati da main_telethon.py, nessun cambio di logica): report radar giornaliero,
aggiornamento velocita', watchdog dei messaggi, rilevamento del blocco del processo, arresto ordinato su SIGTERM.
Lo stato condiviso con on_new_message (_ultimo_msg_gruppo, _analisi_attive) vive qui e main_telethon lo reimporta (stesso oggetto)."""

import os
import sys
import json
import time
import asyncio
import traceback
from datetime import datetime

from bot import db
from bot import archivio_radar
from bot.client_tg import client
from bot.config import TELEGRAM_OWNER_CHAT_ID
from bot.logger import log
from bot.telegram_api import telegram_send_message


def _testo_report_radar(ore=24):
    dal = time.time() - ore * 3600
    eventi_esito = db.leggi_eventi("radar_esito", dal)
    righe, candidati, velocita = archivio_radar.report_giornaliero(db.leggi_eventi("radar_v2", dal), db.leggi_eventi("tracciato_radar", dal), ore,
                                                                   eventi_esito=eventi_esito)
    gv, inviati, scartati, senza_esito = archivio_radar.funnel(righe, eventi_esito, ore)
    log.info("REPORT RADAR | funnel | gv=%s inviati=%s scartati=%s senza_esito=%s", gv, inviati, scartati, senza_esito)
    for r in righe:
        log.info("REPORT RADAR (%s h) | %s | tot=%s verdi=%s gialli=%s gv_venduti=%s/%s scarto=%s", ore, r["nome"], r["tot"], r["verdi"], r["gialli"], r["gv_venduti"], r["gv"], r["motivo"])
    if candidati:
        log.info("REPORT RADAR (%s h) | da potare: %s", ore, ", ".join(candidati))
    return archivio_radar.testo_report(righe, candidati, velocita, ore)


async def ciclo_report_radar():
    """Ogni giorno alle REPORT_RADAR_ORA_UTC (default 5, 0 = spento con -1) manda al proprietario il report delle ultime 24 h. Non solleva."""
    ora = int(os.environ.get("REPORT_RADAR_ORA_UTC", "5") or 5)
    if ora < 0:
        return
    ultimo = None
    while True:
        await asyncio.sleep(300)
        try:
            adesso = time.gmtime()
            if adesso.tm_hour == ora and ultimo != adesso.tm_yday:
                ultimo = adesso.tm_yday
                await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, _testo_report_radar(24), disable_notification=True)
        except Exception:
            log.warning("REPORT RADAR giornaliero fallito:\n%s", traceback.format_exc())



def _aggiorna_velocita_db():
    from bot import velocita, velocita_aggiorna
    n, t = velocita_aggiorna.aggiorna_da_db(velocita.VELOCITA_APPRESA_FILE)
    sem = " ".join(f"{k} {v['veloci'] / v['n']:.0%} (n={v['n']:.0f})" for k, v in sorted(t["semaforo"].items()) if v["n"])
    top = ", ".join(f"{k} {v['veloci'] / v['n']:.0%} (n={v['n']:.0f})" for k, v in sorted(t["brand"].items(), key=lambda x: -x[1]["n"])[:8])
    riga = f"VELOCITA AGGIORNATA | aggiunti={n} | base={t['base']:.1%} | {sem} | fino_ts={t.get('fino_ts')}"
    log.info(riga)
    return f"Velocita' aggiornata: {n} annunci nuovi, base veloci {t['base']:.1%}.\n{sem}\nBrand: {top}"


async def ciclo_velocita():
    """Ogni ora controlla se la tabella ha piu' di 23 h e in tal caso la aggiorna (decadimento 0,97 al giorno)."""
    await asyncio.sleep(600)
    while True:
        try:
            from bot import velocita, velocita_aggiorna
            try:
                with open(velocita.VELOCITA_APPRESA_FILE, encoding="utf-8") as f:
                    ultimo = json.load(f).get("aggiornato", "")
            except Exception:
                ultimo = ""
            vecchio = True
            if ultimo:
                vecchio = time.time() - datetime.fromisoformat(ultimo.replace("Z", "+00:00")).timestamp() > 23 * 3600
            if vecchio:
                _aggiorna_velocita_db()
        except Exception:
            log.warning("VELOCITA ciclo fallito:\n%s", traceback.format_exc())
        await asyncio.sleep(3600)



# BLOCCO DEL PROCESSO (11/10: due volte il worker e' rimasto muto 2h40 e 25 min, senza nessuna riga di log, mentre il tracker
# continuava a notificare): il watchdog sopra gira nello stesso event loop e non puo' accorgersi di un blocco. Qui un thread
# separato controlla il "battito" scritto dal loop ogni 5 s: se manca da piu' di BLOCCO_SECONDI scrive su stderr lo stack di
# tutti i thread (dove e' bloccato) e termina il processo, Railway lo riavvia. 0 = spento.
BLOCCO_SECONDI = float(os.environ.get("BLOCCO_SECONDI", "120") or 0)
_battito = {"t": time.time()}
# ARRESTO ORDINATO (14/10, richiesta dell'utente: un deploy non deve uccidere le analisi in corso). Railway manda SIGTERM e
# aspetta RAILWAY_DEPLOYMENT_DRAINING_SECONDS prima di SIGKILL: il bot continua a lavorare (anche sui messaggi nuovi) finche'
# le analisi in corso finiscono o passano ARRESTO_ATTESA_MAX_S, poi si disconnette. Il valore va sotto il draining di Railway.
ARRESTO_ATTESA_MAX_S = float(os.environ.get("ARRESTO_ATTESA_MAX_S", "90"))
_analisi_attive = {"n": 0, "arresto": False}


async def _arresto_ordinato(attesa_max=None, passo=1.0):
    """Su SIGTERM: attende che le analisi in corso finiscano (al massimo attesa_max secondi), poi disconnette Telethon
    (run_until_disconnected ritorna e main chiude i client HTTP). Le serie di ricontrolli riprendono dal DB all'avvio."""
    if _analisi_attive["arresto"]:
        return
    _analisi_attive["arresto"] = True
    attesa_max = ARRESTO_ATTESA_MAX_S if attesa_max is None else attesa_max
    t0 = time.time()
    log.info("ARRESTO RICHIESTO (SIGTERM) | analisi_in_corso=%d | attesa_max=%.0fs", _analisi_attive["n"], attesa_max)
    while _analisi_attive["n"] > 0 and time.time() - t0 < attesa_max:
        await asyncio.sleep(passo)
    log.info("ARRESTO ORDINATO | analisi_rimaste=%d | attesa=%.0fs", _analisi_attive["n"], time.time() - t0)
    try:
        from bot.proxy import _salva_contatori_banda
        _salva_contatori_banda(forza=True)
    except Exception:
        pass
    await client.disconnect()


def processo_bloccato(ultimo_battito, adesso, soglia):
    """True se il loop non da' segni di vita da oltre `soglia` secondi (soglia <= 0: controllo spento). Pura."""
    return soglia > 0 and adesso - ultimo_battito > soglia


async def _battito_loop():
    while True:
        _battito["t"] = time.time()
        await asyncio.sleep(5)


def _thread_blocco():
    import faulthandler
    import threading
    def _controllo():
        while True:
            time.sleep(15)
            if processo_bloccato(_battito["t"], time.time(), BLOCCO_SECONDI):
                try:
                    sys.stderr.write(f"BLOCCO PROCESSO | il loop e' fermo da {time.time() - _battito['t']:.0f} s: stack dei thread e riavvio\n")
                    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                    sys.stderr.flush()
                finally:
                    os._exit(1)
    if BLOCCO_SECONDI > 0:
        threading.Thread(target=_controllo, name="blocco-watchdog", daemon=True).start()
