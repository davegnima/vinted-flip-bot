"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import time
from urllib.parse import urlparse


from bot.logger import log
# ---- fine import ----
# ---------------------------------------------------------------------------
# PROXY (opzionale) -- rotazione sulle richieste dirette a Vinted, stesso
# tipo di protezione gia' attiva sul tracker gratuito (Vinted-Notifications).
# Formato variabile d'ambiente PROXY_LIST: URL completi separati da virgola,
# es. "http://utente:password@p.webshare.io:80,http://utente:password@p2..."
# -- lo trovi copiandoli dalla dashboard Webshare (o qualunque provider).
# Se la variabile non e' impostata, il bot funziona esattamente come prima
# (nessuna proxy, richieste dirette) -- nessun rischio di rottura.
_PROXY_LIST_RAW = os.environ.get("PROXY_LIST", "").strip()
PROXY_LIST = [p.strip() for p in _PROXY_LIST_RAW.split(",") if p.strip()] if _PROXY_LIST_RAW else []
_proxy_indice_rotazione = [0]

# PROXY_ESCLUSI (aggiunto 2026-09-27, utente: "elimina quelli in 403"):
# elenco "host:porta" separati da virgola da scartare da PROXY_LIST
# all'avvio, senza dover riscrivere PROXY_LIST (che contiene le credenziali
# e su Railway non e' rileggibile in chiaro dagli strumenti). Stesso formato
# che il comando /test_proxy stampa per ogni proxy, quindi basta copiare gli
# indirizzi dei falliti. Togliere un indirizzo da qui lo rimette in rotazione.
_PROXY_ESCLUSI = {
    p.strip().lower() for p in os.environ.get("PROXY_ESCLUSI", "").split(",") if p.strip()
}


def _host_porta_proxy(proxy_url):
    try:
        p = urlparse(proxy_url)
        return f"{p.hostname}:{p.port}".lower()
    except Exception:
        return ""


if _PROXY_ESCLUSI and PROXY_LIST:
    _prima = len(PROXY_LIST)
    PROXY_LIST = [p for p in PROXY_LIST if _host_porta_proxy(p) not in _PROXY_ESCLUSI]
    _trovati = _prima - len(PROXY_LIST)
    log.info(
        "PROXY_ESCLUSI: scartati %d proxy su %d indicati (%d restano in rotazione)%s.",
        _trovati, len(_PROXY_ESCLUSI), len(PROXY_LIST),
        "" if _trovati == len(_PROXY_ESCLUSI)
        else " -- ATTENZIONE: alcuni indirizzi di PROXY_ESCLUSI non corrispondono a nessun proxy di PROXY_LIST",
    )

if PROXY_LIST:
    log.info("Proxy attivi: %d indirizzi caricati da PROXY_LIST, in rotazione round-robin.", len(PROXY_LIST))
else:
    log.info("Nessun PROXY_LIST impostato -- richieste dirette senza proxy (comportamento originale).")


# ---------------------------------------------------------------------------
# LOGGING PER-PROXY (aggiunto 2026-09-27, utente: "non e' che alcuni miei ip
# sono bruciati?"): prima di questo non esisteva ALCUN modo di sapere, dai
# log, quale proxy/IP avesse gestito una data richiesta -- ogni fallimento
# di scraping era anonimo rispetto al pool di 53 proxy in rotazione. Senza
# questo dato non si puo' distinguere "alcuni IP bruciati" (atteso: un mix
# di successi e fallimenti nella rotazione) da un blocco sistemico che
# colpisce l'intero pool allo stesso modo (osservato oggi: 0 successi su
# centinaia di richieste su TUTTI i proxy per 5+ ore) -- vedi anche il
# commento sul blocco totale del 27/9 in _vinted_get_con_retry piu' sotto.
#
# _etichetta_proxy: identificativo leggibile SENZA credenziali (host:porta),
# cosi' i log restano correlabili proxy-per-proxy senza scrivere utente/
# password in chiaro (i proxy_url in PROXY_LIST li contengono, es.
# "http://utente:password@host:porta").
def _etichetta_proxy(chiave):
    if chiave == "diretto":
        return "diretto"
    try:
        p = urlparse(chiave)
        return f"{p.hostname or '?'}:{p.port or '?'}"
    except Exception:
        return "proxy-sconosciuto"


# Popolato in inizializza_client_http() una volta creato il pool: mappa
# chiave (proxy_url o "diretto", vedi _CLIENT_VINTED_POOL_KEYS) -> etichetta
# leggibile "#indice host:porta", stabile per tutta la vita del processo.
_ETICHETTA_PER_CHIAVE_PROXY = {}

# Contatori cumulativi per proxy (chiave -> {"ok": int, "falliti": int}),
# per poter loggare periodicamente un riepilogo "quali IP stanno fallendo
# sistematicamente" senza dover rileggere migliaia di righe di log grezzi.
_PROXY_STATS = {}
_PROXY_STATS_RICHIESTE_TOTALI = [0]
# Ogni quante richieste totali (su tutti i proxy) stampare il riepilogo --
# abbastanza spesso da essere utile su un pool di 53 proxy senza inondare i
# log a ogni singola chiamata.
INTERVALLO_RIEPILOGO_PROXY = 40


# QUARANTENA AUTOMATICA PROXY (2026-10-01, utente: 21 proxy su 46 bloccati da
# Vinted con 403, escluderli a mano via PROXY_ESCLUSI a ogni blocco e' un lavoro
# continuo). Un proxy che prende PROXY_QUARANTENA_SOGLIA 403/429 di fila esce
# dalla rotazione per PROXY_QUARANTENA_ORE ore, poi viene riprovato: se al primo
# tentativo fallisce di nuovo rientra subito in quarantena, se funziona torna
# normale. Solo 403/429 contano (segnale di blocco): timeout, 404 (annuncio
# rimosso) e altri errori no. Se TUTTI i proxy sono in quarantena la rotazione
# ignora il filtro: meglio provare un proxy sospetto che restare senza.
PROXY_QUARANTENA_SOGLIA = max(1, int(os.environ.get("PROXY_QUARANTENA_SOGLIA", "3")))
PROXY_QUARANTENA_SECONDI = float(os.environ.get("PROXY_QUARANTENA_ORE", "3")) * 3600
_PROXY_BLOCCHI_DI_FILA = {}
_PROXY_QUARANTENA_FINO = {}


def _proxy_in_quarantena(chiave):
    scadenza = _PROXY_QUARANTENA_FINO.get(chiave)
    if scadenza is None:
        return False
    if time.time() >= scadenza:
        del _PROXY_QUARANTENA_FINO[chiave]
        # Primo tentativo dopo la pausa: un solo altro blocco lo rimette fuori.
        _PROXY_BLOCCHI_DI_FILA[chiave] = PROXY_QUARANTENA_SOGLIA - 1
        log.info("Proxy [%s] rientra dalla quarantena, riprovo.",
                 _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave))
        return False
    return True


def _registra_blocco_proxy(chiave, bloccato):
    """Aggiorna il contatore di blocchi consecutivi. bloccato=True per un
    403/429, False per un successo (azzera il contatore)."""
    if not bloccato:
        _PROXY_BLOCCHI_DI_FILA[chiave] = 0
        return
    n = _PROXY_BLOCCHI_DI_FILA.get(chiave, 0) + 1
    _PROXY_BLOCCHI_DI_FILA[chiave] = n
    if n >= PROXY_QUARANTENA_SOGLIA and chiave not in _PROXY_QUARANTENA_FINO:
        _PROXY_QUARANTENA_FINO[chiave] = time.time() + PROXY_QUARANTENA_SECONDI
        log.warning(
            "Proxy [%s] in QUARANTENA per %.0fh dopo %d blocchi (403/429) di fila -- "
            "%d proxy in quarantena su %d.",
            _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave),
            PROXY_QUARANTENA_SECONDI / 3600, n, len(_PROXY_QUARANTENA_FINO), len(_CLIENT_VINTED_POOL),
        )


def _registra_esito_proxy(chiave, ok, bloccato=False):
    # Un successo azzera i blocchi di fila; i fallimenti NON da blocco
    # (timeout, 404...) non toccano il contatore.
    if ok:
        _registra_blocco_proxy(chiave, False)
    elif bloccato:
        _registra_blocco_proxy(chiave, True)
    stats = _PROXY_STATS.setdefault(chiave, {"ok": 0, "falliti": 0})
    stats["ok" if ok else "falliti"] += 1
    _PROXY_STATS_RICHIESTE_TOTALI[0] += 1
    if _PROXY_STATS_RICHIESTE_TOTALI[0] % INTERVALLO_RIEPILOGO_PROXY == 0:
        _logga_riepilogo_proxy()


def _logga_riepilogo_proxy():
    """Una riga per proxy, ordinate dalla piu' problematica: 'X/Y falliti'.
    Uno sguardo a questa riga (grep 'RIEPILOGO PROXY' nei log Railway) basta
    per vedere se il pool e' colpito in modo uniforme (tutti con un tasso di
    fallimento simile, blocco sistemico) o se pochi IP concentrano quasi
    tutti i fallimenti (IP davvero bruciati, da rimuovere da PROXY_LIST)."""
    righe = []
    for chiave, s in _PROXY_STATS.items():
        tot = s["ok"] + s["falliti"]
        tasso = (s["falliti"] / tot * 100) if tot else 0.0
        etichetta = _ETICHETTA_PER_CHIAVE_PROXY.get(chiave, _etichetta_proxy(chiave))
        righe.append((tasso, etichetta, s["falliti"], tot))
    righe.sort(reverse=True)
    log.info(
        "RIEPILOGO PROXY (dopo %d richieste totali): %s",
        _PROXY_STATS_RICHIESTE_TOTALI[0],
        " | ".join(f"{et} {f}/{t} falliti ({tasso:.0f}%)" for tasso, et, f, t in righe),
    )


# ---------------------------------------------------------------------------
# CONTABILITA' BANDA PROXY (aggiunta 2026-09-27, utente: "come faccio a
# consumare meno banda?", in vista del passaggio a proxy residenziali a
# consumo). Misura i byte REALI passati in rete (compressi, quelli che il
# provider fattura: resp.num_bytes_downloaded di httpx) separati per tipo di
# richiesta, cosi' si vede cosa pesa davvero invece di stimarlo. Riga da
# cercare nei log Railway: "RIEPILOGO BANDA".
# ---------------------------------------------------------------------------
_BANDA_PER_TIPO = {}
_BANDA_REGISTRAZIONI = [0]
INTERVALLO_RIEPILOGO_BANDA = 50


def _tipo_richiesta_vinted(url):
    u = url or ""
    if "vinted.net" in u:
        return "foto"
    if "/items/" in u:
        return "pagina_annuncio"
    if "/member/" in u:
        return "profilo_venditore"
    if "/catalog" in u:
        return "catalogo_comp"
    return "altro"


def _registra_banda(url, resp, tipo=None):
    """Registra i byte di UNA risposta gia' letta per intero. Mai bloccante:
    qualunque errore qui viene ignorato, la contabilita' non deve rompere lo
    scraping. tipo="foto_diretta" separa le foto scaricate dall'IP Railway
    (banda proxy NON consumata) da quelle via proxy ("foto")."""
    try:
        tipo = tipo or _tipo_richiesta_vinted(url)
        rete = int(getattr(resp, "num_bytes_downloaded", 0) or 0)
        decodificati = len(resp.content or b"")
        s = _BANDA_PER_TIPO.setdefault(tipo, {"n": 0, "rete": 0, "decod": 0})
        s["n"] += 1
        s["rete"] += rete
        s["decod"] += decodificati
        _BANDA_REGISTRAZIONI[0] += 1
        if _BANDA_REGISTRAZIONI[0] % INTERVALLO_RIEPILOGO_BANDA == 0:
            _logga_riepilogo_banda()
    except Exception:
        pass


def _logga_riepilogo_banda():
    tot_rete = sum(s["rete"] for s in _BANDA_PER_TIPO.values()) or 1
    pezzi = []
    for tipo, s in sorted(_BANDA_PER_TIPO.items(), key=lambda kv: -kv[1]["rete"]):
        media_rete = s["rete"] / s["n"] / 1024 if s["n"] else 0
        media_decod = s["decod"] / s["n"] / 1024 if s["n"] else 0
        pezzi.append(
            f"{tipo}: {s['n']} richieste, {s['rete'] / 1048576:.1f}MB in rete "
            f"({s['rete'] / tot_rete * 100:.0f}% del totale), media {media_rete:.0f}KB/richiesta "
            f"(decompressi {media_decod:.0f}KB)"
        )
    log.info("RIEPILOGO BANDA (dall'avvio, %.1fMB totali in rete): %s",
             tot_rete / 1048576, " | ".join(pezzi))


# ---------------------------------------------------------------------------
# CLIENT HTTP ASINCRONI
# ---------------------------------------------------------------------------
# Un client per ogni destinazione, costruiti una volta sola e riusati per
# tutta la vita del processo: httpx tiene aperte le connessioni (keep-alive),
# quindi si risparmiano handshake TLS su ogni chiamata, cosa che con
# requests.Session avveniva solo per Vinted.
#
# Rotazione proxy: da httpx 0.28 il parametro "proxies" (dict per schema) non
# esiste piu', si passa un solo "proxy" per client. La rotazione round-robin
# diventa quindi una rotazione TRA CLIENT, uno per proxy, costruiti all'avvio.
# Se PROXY_LIST e' vuota il pool contiene un solo client diretto, cioe'
# esattamente il comportamento originale senza proxy.
_CLIENT_VINTED_POOL = []
# Chiave di rate-limit per ogni client del pool, stessa lunghezza/ordine di
# _CLIENT_VINTED_POOL (vedi _attendi_turno_vinted piu' sotto, FIX 2026-09-21
# rate-limit globale -> per-IP): e' il proxy_url usato per costruire quel
# client (o "diretto" se PROXY_LIST e' vuota), NON l'identita' dell'oggetto
# client -- serve perche' _CLIENT_VINTED_AUTH sotto condivide DELIBERATAMENTE
# lo stesso proxy dello slot 0 del pool, quindi deve condividere anche la
# stessa pacatura, altrimenti i due client potrebbero fare burst sullo
# stesso IP fisico senza che l'uno sappia dell'altro.
_CLIENT_VINTED_POOL_KEYS = []
