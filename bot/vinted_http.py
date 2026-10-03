"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import json
import time
import asyncio
import base64

import httpx

from bot.config import VINTED_ACCESS_TOKEN, VINTED_REFRESH_TOKEN
from bot.costanti import VINTED_HEADERS
from bot.proxy import _CLIENT_VINTED_POOL, _CLIENT_VINTED_POOL_KEYS, _ETICHETTA_PER_CHIAVE_PROXY, _etichetta_proxy, _registra_banda, _registra_esito_proxy
from bot.http_clients import _prossimo_indice_vinted
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
# Rate-limiter tra richieste Vinted consecutive: dopo ~13h di attivita'
# continua Vinted ha iniziato a rispondere 403 Forbidden (probabile blocco
# per volume di richieste). Impone una pausa minima tra una scrape e la
# successiva per restare sotto la soglia che scatena il blocco -- dal
# 2026-09-21 per singolo proxy, non piu' globale (vedi
# _vinted_timestamp_ultima_richiesta_per_chiave, definito vicino a
# _attendi_turno_vinted).
PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI = 3.0


# TOKEN_FILE: dentro /data, il path del Volume Railway ("vinted-tokens")
# creato e agganciato al servizio "worker" il 2026-09-20 apposta per questo.
# Senza quel Volume montato, qualunque path relativo finirebbe sulla parte
# effimera del filesystem e sparirebbe a ogni riavvio/redeploy -- e' successo
# storicamente col tentativo di "log esiti reali", da qui la scelta di
# scrivere esplicitamente sotto /data invece che nella working directory.
# Se in futuro il Volume viene rimosso o rimontato altrove, il fallback su
# VINTED_ACCESS_TOKEN/REFRESH_TOKEN dalla env var resta comunque intatto
# (vedi sotto): un errore di scrittura qui non rompe nulla, semplicemente
# si perde la persistenza tra riavvii.
TOKEN_FILE = "/data/vinted_tokens.json"

_VINTED_COOKIES = {}
if os.path.exists(TOKEN_FILE):
    try:
        with open(TOKEN_FILE, "r") as f:
            _salvati = json.load(f)
        if _salvati.get("access_token_web"):
            _VINTED_COOKIES["access_token_web"] = _salvati["access_token_web"]
        if _salvati.get("refresh_token_web"):
            _VINTED_COOKIES["refresh_token_web"] = _salvati["refresh_token_web"]
    except Exception as e:
        log.warning("Impossibile leggere %s (probabilmente non esiste ancora): %s", TOKEN_FILE, e)
# La env var resta il fallback/seed: se il file non c'e' (primo avvio, o
# container ripartito senza Volume) o non contiene un token, si riparte da
# quello che l'utente ha messo su Railway.
if not _VINTED_COOKIES.get("access_token_web") and VINTED_ACCESS_TOKEN:
    _VINTED_COOKIES["access_token_web"] = VINTED_ACCESS_TOKEN
if not _VINTED_COOKIES.get("refresh_token_web") and VINTED_REFRESH_TOKEN:
    _VINTED_COOKIES["refresh_token_web"] = VINTED_REFRESH_TOKEN

# VINTED_COOKIES_EXTRA (2026-09-29): l'intero header "Cookie" copiato dal
# browser loggato con l'account dedicato (DevTools > Network > una richiesta a
# vinted.it > Request Headers > cookie). Il test /test_visuale ha mostrato che
# con i soli due token il rinnovo riesce (HTTP 200) ma Vinted tratta comunque
# la sessione come anonima (rimandata a /member/register anche su /inbox, con
# e senza proxy, con httpx e curl_cffi): mancano probabilmente gli altri
# cookie di sessione. I token access/refresh restano gestiti a parte (e
# rinnovati da _rinnova_token_vinted): qui si aggiungono SOLO gli altri cookie,
# e i due token vengono usati come seed solo se mancano del tutto.
def _parse_cookie_header(testo):
    cookie = {}
    for pezzo in (testo or "").split(";"):
        if "=" in pezzo:
            nome, valore = pezzo.split("=", 1)
            nome, valore = nome.strip(), valore.strip()
            if nome and valore:
                cookie[nome] = valore
    return cookie


VINTED_COOKIES_EXTRA = _parse_cookie_header(os.environ.get("VINTED_COOKIES_EXTRA", ""))
for _nome, _valore in VINTED_COOKIES_EXTRA.items():
    if _nome in ("access_token_web", "refresh_token_web"):
        _VINTED_COOKIES.setdefault(_nome, _valore)
    else:
        _VINTED_COOKIES[_nome] = _valore


def _jwt_scaduto(token, margine_secondi=120):
    """Decodifica (senza verificarne la firma -- non ci serve, ci fidiamo
    della fonte visto che l'ha inserito l'utente stesso in una env var) il
    campo 'exp' di un JWT Vinted (access_token_web/refresh_token_web sono
    entrambi JWT, visto nel payload reale catturato il 2026-09-19: struttura
    header.payload.firma in base64url) per sapere se e' scaduto SENZA fare
    una richiesta di rete a vuoto. Margine di 120s per non rischiare di
    usare un token che scade a meta' di una richiesta in corso. Se il
    parsing fallisce per qualunque motivo (token vuoto, formato inatteso,
    campo mancante), lo tratta come scaduto per sicurezza -- meglio un
    fallback alla ricerca visuale disattivata che un crash o un loop."""
    if not token:
        return True
    try:
        parti = token.split(".")
        if len(parti) != 3:
            return True
        payload_b64 = parti[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # padding base64url
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if not exp:
            return True
        return time.time() >= (exp - margine_secondi)
    except Exception:
        return True


_vinted_refresh_lock = asyncio.Lock()


async def _rinnova_token_vinted():
    """Rinnova access_token_web/refresh_token_web chiamando l'endpoint di
    refresh catturato dall'utente via DevTools il 2026-09-20
    (POST /web/api/auth/refresh, richiede un x-csrf-token fresco preso dalla
    home page).

    NON VERIFICATO IN PRODUZIONE al momento della scrittura: non e' confermato
    ne' il formato esatto del meta tag CSRF nella home ne' che la risposta del
    refresh contenga davvero nuovi cookie access_token_web/refresh_token_web
    (l'utente ha catturato solo la richiesta, non la risposta). Per questo la
    funzione logga in dettaglio cosa arriva davvero (status, corpo troncato,
    nomi dei cookie ricevuti) invece di assumerlo -- se il formato reale e'
    diverso, il prossimo log di produzione lo mostra e si corregge il parsing
    senza dover indovinare una seconda volta.

    Fallisce in modo sicuro: in caso di qualunque errore o risposta inattesa
    ritorna False senza toccare _VINTED_COOKIES, quindi il chiamante si
    comporta esattamente come se il refresh automatico non esistesse (fonte
    visuale saltata per questo item, nessuna rottura del resto della
    pipeline)."""
    refresh_token = _VINTED_COOKIES.get("refresh_token_web")
    if not refresh_token or _jwt_scaduto(refresh_token):
        log.warning(
            "_rinnova_token_vinted: refresh_token_web assente o scaduto -- serve un nuovo "
            "VINTED_REFRESH_TOKEN su Railway (nessun refresh automatico possibile da qui)."
        )
        return False

    # Client DEDICATO (_CLIENT_VINTED_AUTH, non il pool anonimo): lo stesso
    # client viene riusato per il refresh e per search_by_image_id, cosi'
    # httpx accumula da solo nel suo jar i cookie Datadome/sessione coerenti
    # con questo account -- vedi il lungo commento sopra la definizione di
    # _CLIENT_VINTED_AUTH per il perche'.
    client = hc._CLIENT_VINTED_AUTH
    # Cookie JWT passati ESPLICITAMENTE (non allegati a costruzione, vedi
    # _crea_client_vinted): httpx li aggiunge solo alla richiesta corrente
    # (in merge col jar persistente del client, che qui e' voluto: e' proprio
    # quel jar a portare i cookie anti-bot coerenti).
    cookies_auth = {k: v for k, v in _VINTED_COOKIES.items() if v}

    # Passo 1: CSRF token fresco dalla home page -- SENZA cookie (fix
    # 2026-09-20, verificato in produzione: mandare qui l'access_token_web
    # ormai scaduto faceva reindirizzare Vinted a /session-refresh invece di
    # servire la home page vera, quindi il meta tag CSRF non c'era mai e il
    # refresh falliva sempre in loop). La home e' una pagina pubblica, non
    # serve autenticazione per leggerla -- il refresh_token_web va mandato
    # solo sulla POST di refresh qui sotto, dove serve davvero. Pattern del
    # meta tag comunque non confermato al 100% su una risposta reale -- se
    # fallisce ancora lo si vede nel log qui sotto e si aggiusta la regex.
    try:
        resp_home = await client.get("https://www.vinted.it/", timeout=15.0)
        resp_home.raise_for_status()
    except Exception as e:
        log.warning("_rinnova_token_vinted: GET home page fallita: %s", e)
        return False
    # Pattern corretto il 2026-09-20 dopo verifica su HTML reale (view-source
    # fornito dall'utente): NON e' un <meta name="csrf-token">, e' la chiave
    # "CSRF_TOKEN" dentro un blob di config JSON incorporato nella pagina
    # (con virgolette escaped, es. \"CSRF_TOKEN\":\"75f6c9fa-...\"). Il
    # pattern vecchio (meta tag) non ha mai trovato nulla in produzione.
    m_csrf = re.search(r'CSRF_TOKEN\\?"\s*:\s*\\?"([0-9a-fA-F-]{20,40})', resp_home.text)
    if not m_csrf:
        log.warning(
            "_rinnova_token_vinted: CSRF_TOKEN non trovato nella home page -- "
            "il markup potrebbe essere cambiato di nuovo. Refresh annullato."
        )
        return False
    csrf_token = m_csrf.group(1)

    # Passo 2: POST di refresh con il CSRF token.
    headers_refresh = dict(VINTED_HEADERS)
    headers_refresh.update({
        "accept": "application/json, text/plain, */*",
        "referer": "https://www.vinted.it/session-refresh?ref_url=%2F",
        "x-csrf-token": csrf_token,
    })
    try:
        resp = await client.post(
            "https://www.vinted.it/web/api/auth/refresh", headers=headers_refresh, timeout=15.0,
            cookies=cookies_auth,
        )
    except Exception as e:
        log.warning("_rinnova_token_vinted: chiamata all'endpoint di refresh fallita: %s", e)
        return False

    if resp.status_code >= 400:
        log.warning(
            "_rinnova_token_vinted: refresh HTTP %d, corpo: %s",
            resp.status_code, resp.text[:300],
        )
        return False

    # Log dei nomi dei cookie ricevuti PRIMA di assumere quali siano quelli
    # giusti -- e' il punto non verificato di tutta la funzione.
    nomi_cookie_ricevuti = list(resp.cookies.keys())
    log.info("_rinnova_token_vinted: refresh HTTP %d, cookie ricevuti: %s",
              resp.status_code, nomi_cookie_ricevuti)

    nuovo_access = resp.cookies.get("access_token_web")
    nuovo_refresh = resp.cookies.get("refresh_token_web")
    if not nuovo_access:
        log.warning(
            "_rinnova_token_vinted: risposta HTTP %d ma nessun cookie 'access_token_web' "
            "nella risposta (cookie ricevuti: %s) -- il formato reale e' probabilmente "
            "diverso da quello previsto, va corretto guardando questo log.",
            resp.status_code, nomi_cookie_ricevuti,
        )
        return False

    _VINTED_COOKIES["access_token_web"] = nuovo_access
    _VINTED_COOKIES["refresh_token_web"] = nuovo_refresh or refresh_token

    # NIENTE piu' propagazione ai client del pool (rimossa il 2026-09-20):
    # da quando _crea_client_vinted non allega piu' i cookie a costruzione,
    # non c'e' nessun cookie jar condiviso da tenere sincronizzato -- ogni
    # chiamata autenticata (qui e in _risolvi_search_by_image_id) legge
    # _VINTED_COOKIES freschi e li passa esplicitamente sulla propria
    # richiesta, quindi il valore appena aggiornato sopra e' gia' quello
    # che verra' usato dalla prossima chiamata.

    # Persistenza su /data (Volume Railway "vinted-tokens", 2026-09-20):
    # sopravvive ai riavvii/redeploy. Il try/except resta comunque -- se il
    # Volume viene rimosso o il path cambia, un errore qui non deve rompere
    # il refresh appena riuscito, solo la sua persistenza tra un riavvio e
    # l'altro.
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump({k: v for k, v in _VINTED_COOKIES.items() if k in ("access_token_web", "refresh_token_web")}, f)
    except Exception as e:
        log.warning("_rinnova_token_vinted: impossibile salvare %s: %s", TOKEN_FILE, e)

    log.info("_rinnova_token_vinted: access token Vinted rinnovato con successo.")
    return True


# Rate-limit Vinted: la pausa minima tra due richieste consecutive va
# rispettata per ogni IP (proxy) preso singolarmente. Senza lock, due task
# concorrenti sullo STESSO proxy leggerebbero lo stesso timestamp "ultima
# richiesta", calcolerebbero la stessa attesa e partirebbero insieme --
# cioe' esattamente la raffica che ha prodotto i 403 dopo ~13h di attivita'
# continua. Il lock serializza SOLO l'attesa e l'aggiornamento del
# timestamp, non la richiesta vera e propria.
#
# FIX 2026-09-21 (utente, "sono tempi biblici!!" -- 25s da messaggio
# Telegram a notifica): prima un UNICO lock/timestamp globale pacava TUTTE
# le richieste Vinted del bot, di qualsiasi proxy, alla stessa cadenza --
# con 53 proxy in rotazione ma un solo lock, annunci multipli in
# lavorazione contemporanea si accodavano comunque uno alla volta su
# un'unica pausa condivisa, vanificando la rotazione. Ora c'e' un
# lock/timestamp per CHIAVE (il proxy_url, o "diretto" se PROXY_LIST e'
# vuota -- vedi _CLIENT_VINTED_POOL_KEYS), cosi' proxy diversi non si
# aspettano piu' a vicenda: la pausa minima per singolo IP resta la
# stessa di prima, identica protezione anti-403, ma fino a
# len(PROXY_LIST) richieste possono davvero procedere in parallelo.
#
# I due dict crescono al piu' fino a len(PROXY_LIST)+1 chiavi (tutti i
# proxy del pool + "diretto"/l'eventuale chiave dedicata dell'account
# autenticato, che pero' COINCIDE sempre con una chiave gia' nel pool --
# vedi _CLIENT_VINTED_AUTH_KEY), quindi non c'e' crescita illimitata.
_vinted_rate_limit_locks = {}
_vinted_timestamp_ultima_richiesta_per_chiave = {}


def _lock_rate_limit_vinted(chiave):
    """Lock dedicato a una chiave (proxy), creato al primo utilizzo. Nessun
    punto di sospensione (await) tra il controllo e la creazione, quindi e'
    sicuro anche con piu' coroutine che chiamano questa funzione sulla
    stessa chiave 'in parallelo' -- asyncio e' cooperativo a thread singolo,
    non gira mai codice sincrono di due task nello stesso istante."""
    if chiave not in _vinted_rate_limit_locks:
        _vinted_rate_limit_locks[chiave] = asyncio.Lock()
        _vinted_timestamp_ultima_richiesta_per_chiave[chiave] = 0.0
    return _vinted_rate_limit_locks[chiave]


async def _attendi_turno_vinted(chiave):
    async with _lock_rate_limit_vinted(chiave):
        tempo_trascorso = time.monotonic() - _vinted_timestamp_ultima_richiesta_per_chiave[chiave]
        attesa = PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI - tempo_trascorso
        if attesa > 0:
            await asyncio.sleep(attesa)
        _vinted_timestamp_ultima_richiesta_per_chiave[chiave] = time.monotonic()


async def _vinted_get_con_retry(url, timeout=15, max_retries=3, headers_extra=None, cookies_extra=None, client_override=None):
    """GET con retry per lo scraping Vinted. In precedenza un singolo timeout
    faceva fallire l'intero scraping (foto, descrizione, venditore tutti
    vuoti), costringendo il cervello a lavorare quasi alla cieca.

    Impone anche una pausa minima rispetto alla richiesta Vinted precedente
    (qualunque essa fosse): dopo ~13h di attivita' continua, Vinted ha
    iniziato a rispondere 403 Forbidden in modo ricorrente, probabile
    rate-limit per volume di richieste troppo fitte.

    headers_extra: header aggiuntivi/di override per questa singola chiamata
    (es. Referer/Sec-Fetch-Site per simulare un click interno al sito invece
    di un arrivo diretto dall'esterno) -- fusi sopra VINTED_HEADERS, non
    toccano le altre chiamate.

    cookies_extra (aggiunto il 2026-09-20): cookie SOLO per questa singola
    chiamata, passati direttamente a httpx invece che attaccati al client
    condiviso -- scelta esplicita dell'utente per tenere l'account Vinted
    dedicato (usato per la ricerca visuale, vedi _risolvi_search_by_image_id)
    completamente separato dal pool anonimo usato per lo scraping normale
    di annunci/venditori. Nessun impatto sulle altre chiamate: httpx aggiunge
    i cookie solo all'header Cookie di QUESTA richiesta, non li salva nel
    cookie jar persistente del client.

    client_override (aggiunto il 2026-09-20): usa questo client httpx invece
    di farne uno in round-robin dal pool anonimo -- serve per la sessione
    autenticata (_CLIENT_VINTED_AUTH, vedi il commento li' sopra), che deve
    SEMPRE riusare lo stesso client per tenere coerenti IP e cookie jar tra
    il refresh del token e la ricerca visuale vera e propria."""
    headers_richiesta = VINTED_HEADERS if not headers_extra else {**VINTED_HEADERS, **headers_extra}

    ultimo_errore = None
    etichette_provate = []
    for tentativo in range(1, max_retries + 1):
        # Client (e la sua chiave di rate-limit) scelti PRIMA di attendere il
        # turno, non dopo (FIX 2026-09-21): serve a sapere su QUALE proxy
        # pacare l'attesa -- vedi il commento su _vinted_rate_limit_locks.
        if client_override is not None:
            client, chiave_rate_limit = client_override, hc._CLIENT_VINTED_AUTH_KEY
        else:
            indice = _prossimo_indice_vinted()
            client, chiave_rate_limit = _CLIENT_VINTED_POOL[indice], _CLIENT_VINTED_POOL_KEYS[indice]
        etichetta = _ETICHETTA_PER_CHIAVE_PROXY.get(chiave_rate_limit) or _etichetta_proxy(chiave_rate_limit)
        etichette_provate.append(etichetta)
        await _attendi_turno_vinted(chiave_rate_limit)
        try:
            resp = await client.get(url, headers=headers_richiesta, cookies=cookies_extra, timeout=timeout)
            _registra_banda(url, resp)  # anche su 4xx: i byte in rete si pagano comunque
            resp.raise_for_status()
            _registra_esito_proxy(chiave_rate_limit, ok=True)
            # Etichetta proxy attaccata alla response stessa (non al contratto
            # di ritorno della funzione, per non dover toccare tutti i
            # chiamanti): chi vuole correlare un esito applicativo (es. pagina
            # vuota/di blocco pur con HTTP 200, vedi DIAGNOSTICA in
            # scrape_vinted_listing) la legge con getattr(resp,
            # "_proxy_etichetta", None) senza cambiare la propria firma.
            resp._proxy_etichetta = etichetta
            # LOGGING PER-PROXY (2026-09-27): una riga per richiesta riuscita,
            # a livello DEBUG per non gonfiare i log in condizioni normali --
            # con un blocco sistemico in corso non ce ne sono comunque (vedi
            # il warning sotto, che invece resta a WARNING/livello visibile).
            log.debug("Vinted [%s] OK status=%s len=%d -- %s", etichetta, resp.status_code, len(resp.text), url)
            return resp
        except Exception as e:
            ultimo_errore = e
            _registra_esito_proxy(
                chiave_rate_limit, ok=False,
                bloccato=isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (403, 429),
            )
            log.info("Vinted [%s] fallito (tentativo %d/%d): %s -- %s", etichetta, tentativo, max_retries, e, url)
            if tentativo < max_retries:
                # Su 403 (probabile rate-limit) attende piu' a lungo del
                # normale backoff, dando al blocco lato Vinted il tempo di
                # attenuarsi prima del prossimo tentativo. Ora e' un'attesa
                # asincrona: non blocca il resto del bot.
                e_403 = "403" in str(e)
                attesa = (6.0 * tentativo) if e_403 else (1.5 * tentativo)
                await asyncio.sleep(attesa)
                continue
    log.warning(
        "Scraping Vinted fallito dopo %d tentativi (proxy provati: %s) per %s: %s",
        max_retries, ", ".join(etichette_provate), url, ultimo_errore,
    )
    return None
