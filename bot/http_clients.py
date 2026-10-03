"""Modulo estratto da main_telethon.py (spostamento meccanico)."""

import httpx

from bot.proxy import PROXY_LIST, _CLIENT_VINTED_POOL, _CLIENT_VINTED_POOL_KEYS, _ETICHETTA_PER_CHIAVE_PROXY, _etichetta_proxy, _proxy_in_quarantena, _proxy_indice_rotazione
from bot.costanti import VINTED_HEADERS
from bot.logger import log
# ---- fine import ----
_client_generico = None   # Gemini/OpenAI/Serper/Resellbot: nessun proxy
_client_telegram = None   # Bot API: timeout piu' corti, chiamate frequenti

# Client HTTP DEDICATO all'account Vinted autenticato (ricerca visuale),
# separato dal pool anonimo _CLIENT_VINTED_POOL -- aggiunto il 2026-09-20
# per chiudere il bug "refresh riuscito ma redirect a /member/register
# comunque": _prossimo_client_vinted() fa round-robin tra client condivisi
# da TUTTO lo scraping anonimo (annunci, venditori), quindi ognuno di quei
# client accumula nel proprio cookie jar cookie Datadome/anti-bot legati a
# traffico anonimo ad alto volume, scorrelati dall'account dedicato. Il
# refresh e la successiva chiamata search_by_image_id finivano cosi' su
# client diversi (round-robin avanza a ogni chiamata) o comunque su un
# client il cui cookie Datadome non corrisponde alla sessione autenticata
# appena rinnovata -- mandare un JWT valido insieme a un cookie Datadome di
# un'altra "sessione anonima" e' esattamente il tipo di incoerenza che fa
# scattare un blocco anti-bot, a prescindere dalla validita' del token.
# Con un client dedicato, riusato SEMPRE per refresh + search_by_image_id,
# httpx accumula da solo (jar persistente normale, nessun parsing manuale)
# i cookie Datadome/sessione ricevuti sulla home page e sul refresh, e la
# chiamata search_by_image_id li porta con se' in modo coerente -- proprio
# come farebbe un browser reale sempre loggato con lo stesso account.
# NON aggiunto a _CLIENT_VINTED_POOL: lo scraping anonimo di annunci/
# venditori non lo vede mai e resta interamente separato, come richiesto
# esplicitamente dall'utente.
_CLIENT_VINTED_AUTH = None
_CLIENT_VINTED_AUTH_KEY = None  # stessa chiave rate-limit dello slot 0 del pool, vedi sopra


def _crea_client_vinted(proxy_url=None):
    # NIENTE cookies=_VINTED_COOKIES qui (tolto il 2026-09-20, era li' dal
    # giorno prima): i client di questo pool sono condivisi da TUTTO lo
    # scraping Vinted (annunci, venditori, ricerca visuale), quindi
    # allegare qui i cookie dell'account dedicato li rendeva permanenti su
    # OGNI richiesta -- quando il token scadeva, anche lo scraping normale
    # (che prima funzionava benissimo in modo anonimo) veniva rediretto a
    # /session-refresh e si rompeva silenziosamente. Scelta esplicita
    # dell'utente: l'account dedicato va usato SOLO per la ricerca visuale,
    # passando i cookie caso per caso su quella singola chiamata (vedi
    # _risolvi_search_by_image_id) invece che sul client condiviso.
    return httpx.AsyncClient(
        headers=VINTED_HEADERS,
        follow_redirects=True,   # _risolvi_search_by_image_id dipende dal redirect
        proxy=proxy_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


async def inizializza_client_http():
    """Crea i client httpx. Va chiamata DENTRO il loop asyncio (da main()),
    mai a import-time: un AsyncClient costruito fuori dal loop che poi lo
    usera' e' una sorgente classica di 'Event loop is closed' e di
    connessioni che non vengono mai riutilizzate."""
    global _client_generico, _client_telegram, _CLIENT_VINTED_AUTH, _CLIENT_VINTED_AUTH_KEY
    if PROXY_LIST:
        for proxy_url in PROXY_LIST:
            _CLIENT_VINTED_POOL.append(_crea_client_vinted(proxy_url))
            _CLIENT_VINTED_POOL_KEYS.append(proxy_url)
    else:
        _CLIENT_VINTED_POOL.append(_crea_client_vinted(None))
        _CLIENT_VINTED_POOL_KEYS.append("diretto")

    # Etichette leggibili per il logging per-proxy (vedi _registra_esito_proxy
    # piu' sopra): "#indice host:porta", costruite una sola volta qui perche'
    # l'ordine di _CLIENT_VINTED_POOL_KEYS e' stabile per tutta la vita del
    # processo.
    for _i, _chiave in enumerate(_CLIENT_VINTED_POOL_KEYS):
        _ETICHETTA_PER_CHIAVE_PROXY[_chiave] = f"#{_i} {_etichetta_proxy(_chiave)}"

    # Client dedicato all'account Vinted autenticato (vedi commento sopra
    # _CLIENT_VINTED_AUTH): pinnato a UN SOLO proxy (il primo della lista, se
    # presente) invece che in rotazione, cosi' anche l'IP resta coerente tra
    # il refresh del token e la chiamata search_by_image_id -- un cambio di
    # IP a meta' sessione autenticata sarebbe un altro segnale anomalo per
    # l'anti-bot, oltre al cookie jar.
    _CLIENT_VINTED_AUTH = _crea_client_vinted(PROXY_LIST[0] if PROXY_LIST else None)
    _CLIENT_VINTED_AUTH_KEY = _CLIENT_VINTED_POOL_KEYS[0]

    _client_generico = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(90.0, connect=15.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )
    _client_telegram = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )
    log.info(
        "Client HTTP asincroni pronti: %d client Vinted (%s), 1 generico, 1 Telegram.",
        len(_CLIENT_VINTED_POOL),
        f"{len(PROXY_LIST)} proxy in rotazione" if PROXY_LIST else "nessun proxy, richieste dirette",
    )


async def chiudi_client_http():
    """Chiusura ordinata: senza questa httpx logga warning di socket non
    chiusi allo spegnimento del processo."""
    for client in _CLIENT_VINTED_POOL:
        await client.aclose()
    for client in (_client_generico, _client_telegram, _CLIENT_VINTED_AUTH):
        if client is not None:
            await client.aclose()


def _prossimo_indice_vinted():
    """Indice del prossimo client Vinted in rotazione round-robin (uno per
    proxy) -- estratto da _prossimo_client_vinted il 2026-09-21 per poter
    ottenere ANCHE la chiave di rate-limit (_CLIENT_VINTED_POOL_KEYS[i])
    corrispondente al client scelto, vedi _vinted_get_con_retry."""
    n = len(_CLIENT_VINTED_POOL)
    for _ in range(n):
        i = _proxy_indice_rotazione[0] % n
        _proxy_indice_rotazione[0] += 1
        if not _proxy_in_quarantena(_CLIENT_VINTED_POOL_KEYS[i]):
            return i
    # Tutti in quarantena: si ignora il filtro invece di restare senza proxy.
    i = _proxy_indice_rotazione[0] % n
    _proxy_indice_rotazione[0] += 1
    return i


def _prossimo_client_vinted():
    """Prossimo client Vinted in rotazione round-robin (uno per proxy).
    Sostituisce _prossimo_proxy: la rotazione ora e' tra client, non tra
    dict di proxy passati alla singola richiesta."""
    return _CLIENT_VINTED_POOL[_prossimo_indice_vinted()]
