"""Venduti eBay/Poshmark da Resellbot (ex serper_fonti.py: dal 31/10 Serper non c'e' piu')."""
import uuid


from bot.costanti import CATEGORIA_TERMINE_EN
from bot.testo import _normalizza_titolo_per_link
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
# Tasso di cambio USD->EUR fisso, hardcoded (scelta dell'utente il
# 2026-09-25 discutendo il fix del bug qui sotto): niente chiamata a
# un'API di cambio live, per non aggiungere un'altra dipendenza di rete sul
# percorso critico di ogni item -- un comp e' gia' un segnale di mercato
# indicativo, non un prezzo legale, e il cambio reale oscilla poco (qualche
# punto percentuale l'anno) rispetto all'incertezza gia' presente nei comp
# stessi. Valore preso da un tasso USD/EUR reale del 25/09/2026 (~0.878),
# arrotondato: VA AGGIORNATO A MANO ogni tanto (non automaticamente) se il
# cambio si muove in modo significativo.
TASSO_USD_EUR = 0.88


async def _query_resellbot_raw(varianti_query, timeout):
    """Esegue UNA chiamata a Resellbot con la LISTA di varianti di query
    gia' costruita (dalla piu' specifica alla piu' ampia) e ritorna
    (righe_di_testo, ok, mappa_url) -- mappa_url aggiunta il 2026-09-25
    (Punto 3 esteso a Resellbot), stesso contratto {(titolo_norm, prezzo_2f):
    url} delle fonti Vinted, ma qui costruita direttamente da item['url']
    invece che ricostruita da un ID.

    Riscritta il 2026-09-25 da query singola a lista di varianti: prima
    (dal 19/09) questa funzione prendeva UNA query e _cerca_ebay_sold_via_resellbot
    faceva un retry sequenziale via Python (chiamata con materiale, poi se
    zero risultati una seconda chiamata senza) quando serviva allargare la
    ricerca. Controllando insieme all'utente via DevTools la richiesta VERA
    che il sito resellbot.com manda (25/09), risulta che il payload accetta
    gia' un array 'queries' con piu' varianti e relativa 'specificity'
    ('exact'/'broad'/'fallback') IN UNA SOLA richiesta -- e' il backend di
    Resellbot stesso a restituire i risultati della variante piu' stretta
    che ne trova, marcando ogni listing con 'sourceQuery' (la variante che
    l'ha trovato). Riprodurre lo stesso schema qui elimina la seconda
    chiamata HTTP sequenziale quando la piu' specifica non basta: piu'
    veloce e coerente con come l'endpoint e' pensato di essere usato,
    invece di reinventare lato Python una cascata che il servizio gia' fa
    da solo."""
    payload = {
        "searchId": str(uuid.uuid4()),
        "queries": varianti_query,
        "resultMode": "raw",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://resellbot.com",
        "Referer": "https://resellbot.com/",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36"
        ),
    }
    log.info("Resellbot: richiesta in corso -- varianti=%r", varianti_query)
    try:
        resp = await hc._client_generico.post(
            "https://scan-api.resellbot.com/api/search",
            headers=headers, json=payload, timeout=timeout,
        )
        if resp.status_code in (401, 403, 429):
            log.info("Resellbot: bloccato/rate-limited (HTTP %d) per varianti=%r -- uso fallback Google.", resp.status_code, varianti_query)
            return f"  Resellbot bloccato/rate-limited (HTTP {resp.status_code}) -- uso fallback Google.", False, {}
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.info("Resellbot: fallito per varianti=%r -- %s -- uso fallback Google.", varianti_query, e)
        return f"  Resellbot fallito: {e} -- uso fallback Google.", False, {}

    risultati_per_piattaforma = data.get("results") or []
    righe = []
    mappa_url = {}
    for blocco_piattaforma in risultati_per_piattaforma:
        piattaforma = (blocco_piattaforma.get("platform") or "").strip()
        for item in blocco_piattaforma.get("listings") or []:
            titolo = (item.get("title") or "").strip()
            prezzo_usd = item.get("price")
            if not titolo or prezzo_usd is None:
                continue
            # BUG CORRETTO il 2026-09-25 (causa root del blocco del 19/09):
            # l'API non ha MAI un campo currency -- price arriva sempre in
            # dollari (eBay.com US, Poshmark US, confermato via DevTools con
            # l'utente lo stesso giorno) -- ma qui si stampava il simbolo €
            # davanti al numero grezzo senza nessuna conversione. Un
            # price:278 (dollari) diventava letteralmente "€278.00" nel
            # testo dato al Cervello, gonfiando ogni comp Resellbot di
            # circa il 12-15% (vedi TASSO_USD_EUR sopra per la scelta del
            # tasso fisso). Spedizione convertita allo stesso modo, stessa
            # valuta della fonte.
            prezzo = prezzo_usd * TASSO_USD_EUR
            spedizione_usd = item.get("shipping") or 0
            spedizione = spedizione_usd * TASSO_USD_EUR
            sold_at = (item.get("soldAt") or "")[:10]  # solo YYYY-MM-DD
            condizione = (item.get("condition") or "").strip()
            pezzi = [f"- {titolo} — €{prezzo:.2f}"]
            if spedizione:
                pezzi.append(f"(+€{spedizione:.2f} spedizione)")
            if sold_at:
                pezzi.append(f"[venduto: {sold_at}]")
            if piattaforma:
                pezzi.append(f"[{piattaforma}]")
            if condizione:
                pezzi.append(f"[cond: {condizione}]")
            righe.append(" ".join(pezzi))

            # Mappa URL comp (Punto 3, estesa a Resellbot il 2026-09-25):
            # qui l'URL e' gia' diretto nel JSON (item['url']), niente
            # ricostruzione da ID come per Vinted (_estrai_mappa_url_comp_vinted)
            # -- solo lookup titolo+prezzo normalizzati come le altre fonti,
            # cosi' render_messaggio_verdetto riattacca il link senza sapere
            # da quale fonte viene il comp.
            url_item = (item.get("url") or "").strip()
            if url_item:
                chiave = (_normalizza_titolo_per_link(titolo), f"{prezzo:.2f}")
                mappa_url.setdefault(chiave, url_item)

    if not righe:
        log.info("Resellbot: risposta OK ma 0 listing per varianti=%r.", varianti_query)
        return None, True, {}  # successo ma zero righe -- distinto da "fallito"
    log.info("Resellbot: risposta OK, %d listing trovati per varianti=%r.", len(righe), varianti_query)
    return "\n".join(righe[:20]), True, mappa_url


async def _cerca_ebay_sold_via_resellbot(brand, categoria, material_per_ricerca=None, dettaglio_distintivo=None, timeout=12):
    """Fonte PRIMARIA per eBay SOLD, aggiunta il 2026-09-19: interroga
    direttamente l'API pubblica di Resellbot (scan-api.resellbot.com/api/search),
    lo stesso endpoint usato dalla pagina https://resellbot.com/ebay-sold-listings/
    -- individuato ispezionando manualmente il tab Network del browser durante
    una ricerca reale (la pagina in se' non mostra risultati nell'HTML statico,
    li carica via fetch() asincrono dopo il caricamento, per questo uno scrape
    HTML classico, senza rendering JS, vede solo la shell vuota).

    E' l'API REALE che alimenta il tool: prezzi di vendita CONFERMATI con
    data (soldAt), non uno snippet testuale con la parola "sold" che puo'
    riferirsi a un annuncio ancora attivo.

    Ritorna (testo, ok, mappa_url) dal 2026-09-25 -- vedi _query_resellbot_raw
    per il contratto della mappa URL (Punto 3).

    Nessuna autenticazione richiesta (verificato via DevTools: solo header
    CORS standard, Origin/Referer che imitano il browser). Rate limit
    dichiarato dal servizio stesso via header di risposta: 700 richieste/5min,
    140/min -- ampiamente sufficiente per l'uso di questo bot (poche decine
    di item/ora). Se Cloudflare (che protegge l'endpoint) dovesse iniziare a
    bloccare le richieste dirette da Railway (mancando il fingerprint TLS/JS
    di un vero browser), ok=False fa scattare comunque il fallback Google
    sotto -- questa fonte non e' un punto di fallimento singolo.

    timeout alzato da 6 a 12s il 2026-09-25 dopo analisi dei log Railway di
    produzione (richiesta dall'utente, che notava comp eBay/Poshmark quasi
    mai citati nei messaggi Telegram): su un campione di ~85 chiamate reali,
    OGNI fallimento (~18%, sempre "Resellbot fallito:  -- uso fallback
    Google" con messaggio d'errore VUOTO, la firma di un httpx.ReadTimeout)
    cadeva a 5.96-6.14s dalla richiesta -- esattamente il bordo del timeout
    di 6s, non un errore reale del servizio (le risposte riuscite variavano
    0-4.65s). La causa e' quasi certamente il passaggio del 2026-09-25 da
    query singola a 3 varianti in una sola chiamata (vedi _query_resellbot_raw):
    Resellbot impiega piu' tempo a elaborarle tutte e tre, e il vecchio
    timeout tarato sulla query singola e' rimasto troppo stretto. 12s lascia
    margine, e il budget totale (12s Resellbot + 8s fallback Google = 20s)
    resta sotto i 25s di TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI riusato
    per questa fonte nel fan-out di search_comps_completo.

    material_per_ricerca (aggiunto il 2026-09-19) restringe la query
    aggiungendo il materiale dichiarato (es. "cashmere", "lana") quando
    disponibile -- utile soprattutto sui brand di lusso dove il materiale
    sposta molto il prezzo (un maglione Brunello Cucinelli in cashmere vale
    parecchio piu' di uno in cotone).

    dettaglio_distintivo (aggiunto il 2026-09-25, vedi
    occhio_schema.dettaglio_distintivo_ricerca) restringe ulteriormente
    quando l'Occhio ha rilevato un dettaglio di taglio/design che distingue
    questo capo da uno generico dello stesso brand+categoria (es. 'ruffle
    sleeve', 'asymmetric hem') -- richiesto dall'utente il 2026-09-25 per
    ridurre il rumore visto nei risultati reali (Chloe, Max Mara spacciati
    per Missoni; un outlier di prezzo palese).

    Le tre varianti (brand+categoria+materiale+dettaglio, brand+categoria
    +materiale, brand+categoria) vengono mandate in UNA sola richiesta a
    Resellbot con le rispettive specificity ('exact'/'broad'/'fallback') --
    vedi _query_resellbot_raw per il perche' del passaggio da retry
    sequenziale via Python a query multiple nella stessa chiamata."""
    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()
    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query eBay "
            "(Resellbot) saltata per evitare risultati fuorvianti."
        ), False, {}

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    query_fallback = f'{brand_pulito} {termine_en}'.strip() if brand_pulito else termine_en
    materiale_pulito = (material_per_ricerca or "").strip()
    dettaglio_pulito = (dettaglio_distintivo or "").strip()

    query_broad = f'{query_fallback} {materiale_pulito}' if materiale_pulito else None
    if query_broad and dettaglio_pulito:
        query_exact = f'{query_broad} {dettaglio_pulito}'
    elif dettaglio_pulito:
        # Niente materiale ma c'e' un dettaglio: resta comunque piu'
        # specifico del solo fallback, va nello slot "exact".
        query_exact = f'{query_fallback} {dettaglio_pulito}'
    else:
        query_exact = None

    varianti, gia_viste = [], set()
    for query, specificity in ((query_exact, "exact"), (query_broad, "broad"), (query_fallback, "fallback")):
        if not query or query in gia_viste:
            continue
        gia_viste.add(query)
        varianti.append({"query": query, "specificity": specificity})

    testo, ok, mappa_url = await _query_resellbot_raw(varianti, timeout)
    if not ok:
        return testo, False, {}
    if testo is None:
        return "  Nessun venduto trovato su Resellbot per questa query.", True, {}
    return testo, True, mappa_url
