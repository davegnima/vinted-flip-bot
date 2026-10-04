"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
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


_UNITA_SECONDI = (("second", 1), ("minut", 60), ("or", 3600), ("giorn", 86400), ("settiman", 604800),
                  ("mese", 2592000), ("mesi", 2592000), ("ann", 31536000))
_NUMERI_PAROLA = {"un": 1, "uno": 1, "una": 1, "un'": 1}


def parse_caricato_secondi(testo):
    """Secondi trascorsi dal 'Caricato' relativo della pagina ("20 secondi fa", "3 minuti fa", "1 ora fa", "un'ora fa",
    "Caricato: 2 ore fa, ..."). Ritorna (secondi, grossolano): grossolano=True se l'unita' non e' il secondo (la
    risoluzione e' di 1 minuto o piu'). None se non interpretabile. Pura."""
    if not testo:
        return None
    t = str(testo).lower().split(",")[0]
    m = re.search(r"(\d+|un'|uno|una|un)\s*(second\w*|minut\w*|or[ae]|giorn\w*|settiman\w*|mes[ei]|ann\w*)", t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _NUMERI_PAROLA.get(m.group(1), 1)
    unita = m.group(2)
    for radice, secondi in _UNITA_SECONDI:
        if unita.startswith(radice):
            return n * secondi, radice != "second"
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
    grossolano = False
    if created_dt is None and listing_info.get("t_scrape"):
        # data di caricamento non esposta dalla pagina: si ricava dal "Caricato N secondi fa" letto al momento dello
        # scrape (richiesto dall'utente il 2026-10-04: tempi da caricato). Errore tipico: 1-2 s (durata dello scrape).
        letto = parse_caricato_secondi(listing_info.get("uploaded_text"))
        if letto and letto[0] <= 6 * 3600:
            created_dt = datetime.fromtimestamp(listing_info["t_scrape"] - letto[0], tz=timezone.utc)
            grossolano = letto[1]
    pref = "~" if grossolano else ""
    pezzi, secondi = [], {}
    if created_dt and msg_date:
        secondi["pub_telegram"] = (msg_date - created_dt).total_seconds()
        pezzi.append(f"pubblicato→telegram {pref}{_formatta_durata(secondi['pub_telegram']) or '?'}")
    if t_ricevuto_bot:
        secondi["telegram_notifica"] = t_riferimento - t_ricevuto_bot
        pezzi.append(f"telegram→notifica {_formatta_durata(secondi['telegram_notifica']) or '?'}")
    if created_dt:
        secondi["totale"] = t_riferimento - created_dt.timestamp()
        pezzi.append(f"totale {pref}{_formatta_durata(secondi['totale']) or '?'}")
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
