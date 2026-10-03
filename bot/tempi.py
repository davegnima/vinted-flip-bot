"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import time
from datetime import datetime, timezone


# ---- fine import ----
def _formatta_durata(secondi):
    """'2m 14s' / '43s' -- None o negativo (orologi non allineati) -> None,
    per poter omettere la riga invece di mostrare un numero senza senso."""
    if secondi is None or secondi < 0:
        return None
    secondi = int(round(secondi))
    m, s = divmod(secondi, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _parse_created_at_dt(created_at_raw):
    """Riconverte in datetime tz-aware il 'created_at' prodotto da
    scrape_vinted_listing (stringa ISO grezza di Vinted o isoformat gia'
    normalizzato dal ramo epoch, vedi sopra). None se assente o non
    parsabile -- stesso spirito difensivo del resto dello scraping."""
    if not created_at_raw:
        return None
    try:
        dt = datetime.fromisoformat(created_at_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot, t_riferimento=None):
    """Le tre tappe del footer '⏱ Tempi' del messaggio Telegram (vedi
    process_listing), come funzione a se' per poterle anche LOGGARE nei
    punti in cui process_listing esce presto SENZA notificare (filtro
    pre-Gemini, gate margine assoluto) -- richiesto dall'utente il
    2026-09-21 ("vedo nei log poi?"): sono proprio i casi "persi" (capo gia'
    venduto quando arriva, o mai notificato) piu' interessanti da poter
    controllare a posteriori nei log di Railway, non solo quelli che
    arrivano fino a una notifica Telegram vera e propria.

    Ritorna (pezzi: list[str] gia' pronti per essere uniti con ' · ',
    secondi: dict con le stesse tre misure in secondi grezzi, per chi in
    futuro volesse aggregarle invece di solo leggerle).
    """
    t_riferimento = time.time() if t_riferimento is None else t_riferimento
    created_dt = _parse_created_at_dt(listing_info.get("created_at"))
    pezzi, secondi = [], {}
    if created_dt and msg_date:
        secondi["pub_telegram"] = (msg_date - created_dt).total_seconds()
        pezzi.append(f"pubblicato→telegram {_formatta_durata(secondi['pub_telegram']) or '?'}")
    if t_ricevuto_bot:
        secondi["telegram_notifica"] = t_riferimento - t_ricevuto_bot
        pezzi.append(f"telegram→notifica {_formatta_durata(secondi['telegram_notifica']) or '?'}")
    if created_dt:
        secondi["totale"] = t_riferimento - created_dt.timestamp()
        pezzi.append(f"totale {_formatta_durata(secondi['totale']) or '?'}")
    return pezzi, secondi


def _formatta_tappe_pipeline(t_tappe):
    """Da t_tappe = [(nome, timestamp), ...] in ordine cronologico, la
    durata di ciascuna tappa rispetto alla precedente -- il dettaglio
    dietro al 'telegram->notifica' aggregato di _calcola_tempi_pipeline,
    per capire QUALE chiamata (scrape, Occhio, ricerca comp, Cervello...)
    si sta mangiando il tempo quando il totale sembra troppo alto (richiesto
    dall'utente il 2026-09-21, dopo un caso reale da 27s: "sono tempi
    biblici!!"). Ogni tappa mostrata anche se ~0s: e' piu' onesto di
    ometterla, e su questa pipeline (scrape + Occhio + ricerca comp +
    Cervello, tutte chiamate di rete) un 0s vero e' comunque informativo
    (quello stadio non e' il collo di bottiglia)."""
    # underscore nel nome tappa (es. campioni_target) spezzerebbe il footer in corsivo del messaggio Telegram
    return [f"{nome.replace('_', ' ')} {_formatta_durata(t - t_prec) or '0s'}"
            for (_, t_prec), (nome, t) in zip(t_tappe, t_tappe[1:])]
