"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
from urllib.parse import quote


from bot.config import SERPER_API_KEY, VISUAL_SEARCH_ATTIVA
from bot.costanti import VINTED_BRAND_IDS
from bot.vinted_http import _VINTED_COOKIES, _jwt_scaduto, _rinnova_token_vinted, _vinted_get_con_retry, _vinted_refresh_lock
from bot.serper_base import _e_errore_crediti_serper
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
def build_vinted_search_url(brand, categoria, materiale=None, catalog_id=None):
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    parti_search_text = [p for p in (categoria, materiale) if p]
    search_text_finale = " ".join(parti_search_text)
    catalog_str = f"&catalog[]={catalog_id}" if catalog_id else ""
    if brand_id:
        url = (
            f"https://www.vinted.it/catalog?brand_ids[]={brand_id}"
            f"{catalog_str}"
            f"&search_text={quote(search_text_finale)}"
            "&order=newest_first&status_ids[]=1&status_ids[]=2&status_ids[]=3"
        )
        return url, True
    query_text = f"{brand} {search_text_finale}".strip()
    url = (
        f"https://www.vinted.it/catalog?search_text={quote(query_text)}"
        f"{catalog_str}"
        "&order=newest_first"
    )
    return url, False


async def _risolvi_search_by_image_id_via_serper(url_intermedio):
    """Fallback aggiunto il 2026-09-20 dopo la prova in produzione che il
    blocco su /search_by_image e' un blocco Datadome a livello di edge (HTTP
    403 diretto, niente redirect, niente pagina) sul fingerprint TLS/HTTP
    del client httpx -- confermato perche' NELLO STESSO log lo scraping
    normale (pagine annuncio/venditore) con lo stesso identico stack
    httpx funziona regolarmente: non e' un blocco generico su Python, e'
    specifico di questo endpoint sensibile.

    Il servizio di scraping di Serper pero' su QUESTO STESSO endpoint
    riceve 200 OK nello stesso log (lo si vede usato subito dopo per altre
    fonti) -- il suo infrastructure/fingerprint passa dove il nostro client
    diretto viene bloccato. Tentativo: fargli scrape-are l'URL intermedio
    di search_by_image e provare a recuperare l'URL finale (dopo il
    redirect 307 a /catalog?search_by_image_id=...) dai metadati o dal
    contenuto che restituisce, invece di fare l'intera catena (che aveva
    dato risultati generici/degradati per il catalogo, vedi
    _scrape_catalogo_vinted_diretto) -- qui serve solo l'ID risolto, non il
    contenuto del catalogo.

    NON VERIFICATO IN PRODUZIONE alla scrittura: non e' confermato che
    Serper esponga l'URL finale dopo un redirect nella sua risposta, ne'
    sotto quale nome di campo. Per questo logga le chiavi di primo livello
    ricevute PRIMA di provare a estrarne uno specifico, cosi' se il
    tentativo fallisce il prossimo log di produzione mostra la forma reale
    della risposta invece di doverla indovinare una seconda volta. Fallisce
    in modo sicuro: ritorna None su qualunque errore o mancata corrispondenza,
    il chiamante si comporta come se il fallback non esistesse."""
    if not SERPER_API_KEY:
        return None
    # "headers" nel payload (tentativo, non documentato/confermato per questo
    # endpoint Serper): se supportato, inoltra i cookie dell'account dedicato
    # cosi' la richiesta arriva a Vinted autenticata anche passando dal
    # fetcher di Serper -- SENZA questo, Serper vede l'URL come richiesta
    # anonima e Vinted la reindirizza correttamente al login/signup (proprio
    # come farebbe con un browser vero non loggato), che e' l'ipotesi piu'
    # probabile per cui il tentativo del 2026-09-20 non ha trovato nessun
    # search_by_image_id nella risposta: non un fallimento di Serper, ma
    # Serper-senza-cookie che raggiunge la STESSA pagina di registrazione.
    # Se il campo non e' supportato, Serper lo ignora e il comportamento
    # resta quello gia' osservato in produzione (nessun peggioramento).
    cookies_auth = {k: v for k, v in _VINTED_COOKIES.items() if v}
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies_auth.items())
    payload = {
        "url": url_intermedio, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True,
        "headers": {"Cookie": cookie_header} if cookie_header else {},
    }
    try:
        resp = await hc._client_generico.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            log.info("_risolvi_search_by_image_id_via_serper: Serper fallito (crediti/HTTP %d).", resp.status_code)
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.info("_risolvi_search_by_image_id_via_serper: chiamata Serper fallita: %s", e)
        return None

    # Diagnostica estesa (aggiunta dopo il primo tentativo in produzione,
    # 2026-09-20, che ha loggato solo le chiavi e non ha permesso di capire
    # SU QUALE pagina Serper sia effettivamente atterrato): metadata per
    # intero (spesso contiene lo status HTTP/URL finale delle API di
    # scraping) e un frammento di testo, cosi' si vede a colpo d'occhio se
    # e' la pagina di registrazione (ipotesi sopra) o qualcos'altro.
    log.info("_risolvi_search_by_image_id_via_serper: chiavi ricevute da Serper: %s", list(data.keys()))
    log.info("_risolvi_search_by_image_id_via_serper: metadata=%r", data.get("metadata"))
    testo_snippet = (data.get("text") or "")[:300]
    log.info("_risolvi_search_by_image_id_via_serper: inizio testo pagina=%r", testo_snippet)

    # Primo tentativo: un campo che indichi esplicitamente l'URL finale
    # raggiunto da Serper dopo aver seguito eventuali redirect.
    candidati_url = [
        data.get("url"), data.get("finalUrl"), data.get("resolvedUrl"),
        (data.get("metadata") or {}).get("url") if isinstance(data.get("metadata"), dict) else None,
    ]
    for candidato in candidati_url:
        if candidato and "search_by_image_id=" in candidato:
            m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", candidato)
            if m:
                log.info(
                    "_risolvi_search_by_image_id_via_serper: OK (da campo URL) -> search_by_image_id=%s (url=%s)",
                    m.group(1), candidato,
                )
                return m.group(1)

    # Secondo tentativo: l'ID potrebbe comparire dentro il contenuto
    # restituito (link canonico, og:url, redirect lato JS) anche se Serper
    # non espone un campo "url" dedicato.
    for chiave in ("markdown", "text", "html", "rawHtml"):
        contenuto = data.get(chiave)
        if not contenuto:
            continue
        m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", contenuto)
        if m:
            log.info(
                "_risolvi_search_by_image_id_via_serper: OK (da campo '%s') -> search_by_image_id=%s",
                chiave, m.group(1),
            )
            return m.group(1)

    log.info(
        "_risolvi_search_by_image_id_via_serper: nessun search_by_image_id trovato nella risposta Serper "
        "(chiavi disponibili: %s) -- formato risposta da rivedere sul prossimo log.",
        list(data.keys()),
    )
    return None


async def _risolvi_search_by_image_id(item_id, photo_id):
    """Il photo_id della foto (estratto dall'URL CDN, es. "06_00506_...")
    NON e' l'ID accettato da search_by_image_id nel catalogo -- verificato
    empiricamente confrontando tre URL reali forniti dall'utente il
    2026-09-18: foto con photo_id "06_00506_96X4vjNZUPdRFP3X2B6rTJMR",
    endpoint "/items/{id}/search_by_image?photo_id=06_00506_..." (stesso
    photo_id in input), che REDIRIGE (HTTP 302, l'utente ha confermato che
    il browser si sposta da solo senza altri click) a
    "/catalog?search_by_image_id=05_020ea_SjsgDv3J1EKG941GCMipbmQc" -- un ID
    completamente diverso, calcolato lato server (probabile embedding
    visivo). Questa funzione replica quel passaggio con una singola GET che
    segue il redirect (requests lo fa di default), poi legge l'ID vero
    dall'URL finale (resp.url). Nessun browser necessario.

    Passa per lo stesso canale "Vinted diretto" di scrape_vinted_listing
    (via _vinted_get_con_retry, stessa pausa minima anti-rate-limit), quindi
    aggiunge una richiesta extra a quel budget -- se in futuro tornano i 403
    osservati in produzione, questa e' una delle prime cose da rivedere o
    rendere disattivabile.

    STATO DEFINITIVO (confermato il 2026-09-19, chiude l'indagine aperta il
    2026-09-18): questa feature RICHIEDE una sessione Vinted autenticata,
    punto. Non e' un problema di Referer/Sec-Fetch/header che si possa
    aggiustare lato codice -- e' un vero requisito del prodotto.

    Prova definitiva raccolta con l'utente via DevTools: la richiesta
    "search_by_image?photo_id=..." che ha prodotto il redirect 307 al
    catalogo aveva nei cookie access_token_web/refresh_token_web (JWT con
    "purpose":"access", account_id valorizzato) -- l'utente era loggato col
    proprio account personale, non anonimo. Per confermare che fosse
    davvero questo e non altro, l'utente ha poi: (1) riaperto lo STESSO URL
    esatto in incognito senza login -> ha funzionato (probabile cache lato
    Vinted/CDN su quell'URL gia' generato in precedenza dalla sessione
    autenticata); (2) provato a generare una ricerca visuale NUOVA (nuovo
    item/photo_id mai richiesto prima) sempre in incognito senza login ->
    Vinted ha richiesto il login. Il primo test da solo sarebbe stato
    ambiguo (poteva sembrare che bastasse l'URL pubblico), il secondo lo
    disambigua: senza sessione autenticata, una ricerca visuale MAI vista
    prima da Vinted non parte.

    Conclusione: il bot NON puo' e non deve usare le credenziali Vinted
    personali dell'utente per autenticarsi (rischio sull'account reale,
    uso improprio delle credenziali per uno scraper automatico, violazione
    diretta dei ToS molto piu' seria di un semplice scraping di pagine
    pubbliche). VISUAL_SEARCH_ATTIVA resta quindi permanentemente
    disattivabile via env var ma la feature va considerata chiusa: non
    investire altro tempo qui a meno che l'utente non decida esplicitamente
    di autenticare il bot con un proprio account dedicato (scelta sua, con
    consapevolezza dei rischi, mai una decisione presa in autonomia dal
    codice).

    RIAPERTA il 2026-09-19 (stesso giorno): l'utente ha scelto di procedere
    con un account Vinted dedicato/sacrificabile (mai il suo account
    principale) per questo solo scopo. VINTED_ACCESS_TOKEN/REFRESH_TOKEN
    (env var, vedi CONFIGURAZIONE in testa al file) portano quella sessione
    autenticata; se assenti la funzione si comporta esattamente come nello
    stato "chiuso" sopra (ritorna None, nessuna rottura del resto della
    pipeline).

    RIAPERTA di nuovo il 2026-09-20: refresh automatico via
    _rinnova_token_vinted() quando l'access token e' scaduto, invece di
    restare inattiva finche' l'utente non lo aggiorna a mano su Railway.
    NON VERIFICATO IN PRODUZIONE alla scrittura (vedi la docstring di
    _rinnova_token_vinted per il dettaglio) -- se il refresh fallisce si
    comporta esattamente come prima di questa modifica: fonte saltata,
    nessuna rottura.

    BUG TROVATO IN PRODUZIONE il 2026-09-20 e corretto: il refresh
    riusciva (HTTP 200, nuovi access_token_web/refresh_token_web ricevuti)
    ma QUESTA chiamata veniva comunque rediretta a /member/register/
    select_type. Causa: sia il refresh sia questa chiamata prendevano un
    client httpx dal pool anonimo condiviso (_prossimo_client_vinted, in
    round-robin con TUTTO lo scraping annunci/venditori) -- ogni client del
    pool accumula nel proprio cookie jar cookie Datadome/sessione da
    traffico anonimo ad alto volume, scorrelati dall'account dedicato, e il
    round-robin poteva far atterrare refresh e search_by_image_id su
    client diversi comunque. Mandare un JWT valido insieme a un cookie
    Datadome di un'altra sessione (anonima) e' un'incoerenza che Vinted
    trattava come sessione sospetta. Corretto usando _CLIENT_VINTED_AUTH,
    un client dedicato SEMPRE riusato per refresh + search_by_image_id (mai
    toccato dal pool anonimo), cosi' il suo cookie jar resta coerente con
    l'account autenticato in entrambe le chiamate."""
    if not VISUAL_SEARCH_ATTIVA:
        return None
    if not item_id or not photo_id:
        return None
    if not _VINTED_COOKIES.get("access_token_web") or _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
        async with _vinted_refresh_lock:
            # Doppio controllo dentro il lock: un altro task in parallelo
            # potrebbe aver gia' rinnovato mentre aspettavamo il lock.
            if not _VINTED_COOKIES.get("access_token_web") or _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
                log.info("_risolvi_search_by_image_id: access token scaduto/assente, tento il refresh automatico...")
                if not await _rinnova_token_vinted():
                    log.info(
                        "_risolvi_search_by_image_id: refresh automatico fallito -- fonte visuale "
                        "saltata per questo item (serve un token fresco dall'account dedicato, "
                        "aggiornabile su Railway)."
                    )
                    return None
    url_intermedio = f"https://www.vinted.it/items/{item_id}/search_by_image?photo_id={quote(photo_id)}"
    headers_referer_annuncio = {
        "Referer": f"https://www.vinted.it/items/{item_id}",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
    }
    # Cookie dell'account dedicato passati SOLO qui (cookies_extra, non piu'
    # sul client condiviso) E client_override=_CLIENT_VINTED_AUTH (non il
    # pool anonimo, aggiunto il 2026-09-20): questa e' l'unica chiamata del
    # bot che ha davvero bisogno di autenticazione (verificato via DevTools
    # il 2026-09-18/19), tutto il resto dello scraping Vinted resta anonimo
    # e passa dal pool round-robin come sempre. Riusare lo STESSO client di
    # _rinnova_token_vinted e' il punto: porta con se' i cookie Datadome/
    # sessione accumulati li', coerenti col JWT appena rinnovato -- prima
    # (client preso dal pool anonimo in round-robin) questa richiesta poteva
    # arrivare con un cookie Datadome di tutt'altra provenienza insieme a un
    # JWT valido, un'incoerenza che Vinted trattava come sessione sospetta e
    # rediriggeva a /member/register anche a refresh riuscito.
    resp = await _vinted_get_con_retry(
        url_intermedio, timeout=12, max_retries=2, headers_extra=headers_referer_annuncio,
        cookies_extra={k: v for k, v in _VINTED_COOKIES.items() if v},
        client_override=hc._CLIENT_VINTED_AUTH,
    )
    esito_diretto = None
    if resp is not None:
        # str(): con httpx resp.url e' un oggetto URL, non una stringa -- un
        # "in" o una re.search direttamente su di esso solleverebbe TypeError
        # (con requests era una stringa e funzionava).
        url_finale = str(resp.url)
        if "/member/register" in url_finale or "/member/login" in url_finale:
            log.info(
                "_risolvi_search_by_image_id: redirect a login/registrazione NONOSTANTE "
                "VINTED_ACCESS_TOKEN impostato e non scaduto (%s) -- possibile token "
                "invalidato lato Vinted prima della scadenza dichiarata, o blocco Datadome "
                "sul fingerprint della richiesta (vedi nota TLS/Datadome nella docstring "
                "sopra). Provo il fallback via Serper prima di arrendermi.",
                url_finale,
            )
        else:
            m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", url_finale)
            if m:
                esito_diretto = m.group(1)
            else:
                log.info(
                    "_risolvi_search_by_image_id: redirect non ha prodotto un search_by_image_id "
                    "nell'URL finale (%s) -- provo il fallback via Serper prima di arrendermi.",
                    url_finale,
                )
    else:
        log.info(
            "_risolvi_search_by_image_id: richiesta diretta fallita (probabile 403 Datadome "
            "sul fingerprint del client -- vedi nota TLS/Datadome nella docstring sopra). "
            "Provo il fallback via Serper prima di arrendermi."
        )

    if esito_diretto:
        log.info(
            "_risolvi_search_by_image_id: OK (diretto) item_id=%s photo_id=%s -> search_by_image_id=%s",
            item_id, photo_id, esito_diretto,
        )
        return esito_diretto

    # Fallback via Serper (aggiunto il 2026-09-20): il client diretto viene
    # bloccato a livello edge su QUESTO endpoint (403 o redirect a signup),
    # ma nello stesso log lo stesso Serper riceve 200 OK dallo stesso host
    # -- vedi _risolvi_search_by_image_id_via_serper per il dettaglio.
    esito_serper = await _risolvi_search_by_image_id_via_serper(url_intermedio)
    if esito_serper:
        log.info(
            "_risolvi_search_by_image_id: OK (fallback Serper) item_id=%s photo_id=%s -> search_by_image_id=%s",
            item_id, photo_id, esito_serper,
        )
        return esito_serper

    log.info(
        "_risolvi_search_by_image_id: nessuna via (diretta o Serper) ha risolto search_by_image_id "
        "per item_id=%s -- fonte visuale saltata per questo item.",
        item_id,
    )
    # Era "return m.group(1)": con richiesta fallita o redirect al login 'm'
    # non esiste (NameError) o e' None (AttributeError) -- corretto il
    # 2026-09-28, nessuna via ha funzionato quindi None.
    return None


async def build_vinted_visual_search_url(item_id, photo_id, brand):
    """URL equivalente al bottone Vinted "Cerca articoli simili" + filtro
    per brand. Risolve prima il vero search_by_image_id (vedi
    _risolvi_search_by_image_id -- il photo_id della foto da solo NON
    basta), poi vi aggiunge il filtro brand. Richiede SEMPRE un brand_id
    mappato: senza filtro brand la ricerca visuale pura e' troppo ampia per
    essere un comp utile (l'utente ha verificato che il filtro brand e'
    quello che rende i risultati "molto verosimili"). Ritorna None se manca
    un ingrediente o la risoluzione fallisce -- il chiamante deve trattarlo
    come fonte assente, non come errore.

    NIENTE order=newest_first qui (fix 2026-09-20, dopo aver osservato in
    log di produzione che i comp visuali erano categorie completamente
    diverse dello stesso brand -- borse/profumi/gioielli mescolati a capi
    d'abbigliamento -- invece di articoli simili alla foto): quel parametro
    era stato copiato per analogia da build_vinted_search_url (ricerca
    testuale, dove ha senso ordinare per data), ma su search_by_image_id
    SOVRASCRIVE l'ordinamento per rilevanza/similarita' visiva che Vinted
    applica di default su quell'endpoint, degradandolo a "ultimi articoli
    del brand" su tutto il catalogo. L'unico URL verificato dall'utente via
    DevTools il 2026-09-18 non aveva questo parametro. Lasciamo l'ordine di
    default (rilevanza) e teniamo solo i filtri che restringono senza
    riordinare (brand, status)."""
    brand_id = VINTED_BRAND_IDS.get((brand or "").strip().lower())
    if not brand_id:
        return None
    search_by_image_id = await _risolvi_search_by_image_id(item_id, photo_id)
    if not search_by_image_id:
        return None
    url = (
        f"https://www.vinted.it/catalog?search_by_image_id={quote(search_by_image_id)}"
        f"&brand_ids[]={brand_id}"
        "&status_ids[]=1&status_ids[]=2&status_ids[]=3"
    )
    log.info("build_vinted_visual_search_url: URL catalogo costruito: %s", url)
    return url


def _estrai_articoli_vinted(content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dal markdown scrapato di una pagina
    catalogo Vinted. Fix 2026-09-19: il pattern prezzo riconosceva solo
    '€105' (simbolo prima del numero), mai '105€'/'105 €' -- se Vinted
    scrive il prezzo in quel secondo formato (comune altrove, es. Vestiaire),
    questa funzione tornava sistematicamente 'Nessun articolo trovato' anche
    con una pagina piena di risultati validi. Ora riconosce entrambi.

    Aggiunto lo stesso giorno: quando non trova nulla, distingue nel testo
    restituito TRE scenari diversi invece del generico "Nessun articolo
    trovato" -- (a) la pagina scrapata era vuota/senza righe di contenuto,
    (b) c'erano righe di contenuto ma nessuna con un simbolo di prezzo
    riconoscibile, (c) c'era un simbolo € ma la riga e' stata scartata dopo
    (titolo troppo corto o assente). Serve per capire, guardando il debug
    Telegram, se Serper ha davvero trovato la pagina/i risultati oppure no
    -- 'nessun prezzo' da solo non lo diceva."""
    righe_non_vuote = sum(1 for r in content.split("\n") if r.strip())
    righe_con_simbolo_prezzo = sum(1 for r in content.split("\n") if "€" in r or re.search(r"\bEUR\b", r, re.IGNORECASE))
    righe_pulite, visti = [], set()
    for riga in content.split("\n"):
        riga_dec = riga.replace("&#x20AC;", "€").replace("&#x20ac;", "€")
        match_prezzo = re.search(r"€\s*([\d]+(?:\.\d+)?)|([\d]+(?:\.\d+)?)\s*€", riga_dec)
        if not match_prezzo:
            continue
        prezzo = match_prezzo.group(1) or match_prezzo.group(2)
        riga_pulita = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', riga_dec)
        riga_pulita = re.sub(r'!\[', '', riga_pulita)
        riga_pulita = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', riga_pulita).replace('"', '').strip().lstrip('-').strip()
        # Prova entrambi i formati di prezzo ('€105' e '105€'/'105 €') nella
        # riga gia' ripulita dal markdown -- niente calcoli di posizione
        # incrociati tra riga_dec e riga_pulita (fragili: la pulizia
        # markdown cambia le lunghezze/offset in modo non prevedibile).
        pos_prezzo = riga_pulita.find(f"€{prezzo}")
        if pos_prezzo == -1:
            m_dopo = re.search(re.escape(prezzo) + r"\s*€", riga_pulita)
            pos_prezzo = m_dopo.start() if m_dopo else -1
        if pos_prezzo == -1:
            pos_prezzo = riga_pulita.find("€")
        titolo = riga_pulita[:pos_prezzo].rstrip(", ").strip() if pos_prezzo > 0 else riga_pulita
        match_meta = re.search(r",\s*(?:brand|marca|condizioni|condition|taglia|size)\s*:", titolo, re.IGNORECASE)
        if match_meta:
            titolo = titolo[:match_meta.start()].strip()
        if not titolo or len(titolo) < 5 or titolo.startswith("http"):
            continue
        chiave = (titolo[:60].lower(), prezzo)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe_pulite.append(f"- {titolo} — €{prezzo}")
        if len(righe_pulite) >= max_articoli:
            break
    if righe_pulite:
        return "\n".join(righe_pulite)
    if righe_non_vuote == 0:
        return "  Nessun articolo trovato (pagina scrapata vuota/senza contenuto -- probabile scrape fallito o pagina bloccata)."
    if righe_con_simbolo_prezzo == 0:
        return f"  Nessun articolo trovato ({righe_non_vuote} righe di contenuto scrapate, ma NESSUNA conteneva un simbolo di prezzo -- probabile pagina senza risultati catalogo, o layout cambiato)."
    return f"  Nessun articolo trovato ({righe_con_simbolo_prezzo} righe con simbolo di prezzo trovate, ma titolo non estraibile/troppo corto per ciascuna)."
