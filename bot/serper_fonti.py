"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
import uuid


from bot.costanti import CATEGORIA_TERMINE_EN
from bot.config import SERPER_API_KEY
from bot.serper_base import _e_errore_crediti_serper
from bot.vinted_search import _estrai_articoli_vinted
from bot.testo import _normalizza_titolo_per_link
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
async def _serper_scrape_page_diretto(label, url):
    if not SERPER_API_KEY:
        return "Scrape non eseguito (SERPER_API_KEY non impostata).", False

    payload = {"url": url, "includeMarkdown": True, "includeRawHtml": True, "includeHtml": True}
    try:
        resp = await hc._client_generico.post(
            "https://scrape.serper.dev",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"  Scrape fallito: {e}", False

    if "VINTED" in label.upper():
        content = data.get("markdown") or data.get("text") or ""
        return _estrai_articoli_vinted(content), True
    return "  Fonte non supportata.", True


async def _serper_batch_query_vestiaire(brand, categoria):
    """Query mirata su Vestiaire Collective. NON usa piu' un fallback generico
    "dress" quando la categoria non e' rilevata: in quel caso salta la query
    ed espone chiaramente al cervello che manca il dato, invece di restituire
    comp completamente fuori tema (es. abiti da sera al posto di camicie)."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", False

    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()

    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query Vestiaire "
            "saltata per evitare risultati fuorvianti (es. abiti al posto di camicie). "
            "Se necessario, usa la function cerca_comp_prezzo con una query piu' mirata."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    query_serper = f'site:vestiairecollective.com "{brand_pulito}" "{termine_en}" €'.strip() if brand_pulito else f'site:vestiairecollective.com "{termine_en}" €'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await hc._client_generico.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if _e_errore_crediti_serper(resp):
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}", False

    lines = []
    for batch in results:
        for r in batch.get("organic", [])[:10]:
            titolo = r.get("title", "")
            snippet = r.get("snippet", "")
            match_prezzo = re.search(r"€\s*[\d.,]+|\d+(?:[.,]\d+)?\s*€|EUR\s*[\d.,]+", snippet, re.IGNORECASE)
            snippet_troncato = snippet[:100].rstrip()
            if match_prezzo and match_prezzo.group(0) not in snippet_troncato:
                snippet_troncato += f"... [PREZZO: {match_prezzo.group(0)}]"
            elif len(snippet) > 100:
                snippet_troncato += "..."
            lines.append(f"- {titolo}\n  {snippet_troncato}")
    return ("\n".join(lines) if lines else "Nessun risultato trovato."), True


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
    HTML classico -- sia il nostro WebFetch che, presumibilmente, Serper senza
    rendering JS -- vede solo la shell vuota).

    A differenza della query Google (_serper_batch_query_ebay_sold, tenuta
    sotto come fallback), questa e' l'API REALE che alimenta il tool: prezzi
    di vendita CONFERMATI con data (soldAt), non uno snippet testuale con la
    parola "sold" che puo' riferirsi a un annuncio ancora attivo.

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


async def _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca=None, dettaglio_distintivo=None):
    """FALLBACK per eBay SOLD (fonte primaria: _cerca_ebay_sold_via_resellbot
    sopra) -- stesso schema di _serper_batch_query_vestiaire (Google search
    via Serper, non scrape diretto della pagina eBay).

    material_per_ricerca (aggiunto il 2026-09-19, per coerenza con la fonte
    primaria Resellbot) viene aggiunto tra virgolette come termine di
    ricerca aggiuntivo quando disponibile -- qui non serve un retry "senza
    materiale" come per Resellbot: Google gestisce query piu' lunghe senza
    azzerare i risultati come farebbe una specificity "exact" letterale, si
    limita a pesarlo come termine di rilevanza in piu'.

    dettaglio_distintivo (aggiunto il 2026-09-25, stessa fonte e stesso
    motivo di material_per_ricerca -- vedi _cerca_ebay_sold_via_resellbot):
    stesso trattamento, un termine tra virgolette in piu'.

    Sostituisce il vecchio approccio (_serper_scrape_page_diretto +
    _estrai_articoli_ebay) che scrapava direttamente l'URL di ricerca eBay
    con LH_Sold=1. Abbandonato il 2026-09-19 dopo conferma diretta nei log
    Railway: OGNI scrape, su item diversi con query diverse, restituiva la
    stessa identica pagina eBay ('metadata': {'title': 'Misura di sicurezza
    | eBay'}, sempre 217 righe di contenuto) -- non un problema di selettori
    CSS o layout cambiato, ma il muro anti-bot di eBay che intercetta
    sistematicamente lo scraper di Serper su quell'endpoint, prima ancora
    che la pagina risultati venga generata. Nessun fix ai selettori
    avrebbe mai funzionato.

    Interrogando invece Google (site:ebay.it/ebay.com) tramite l'endpoint
    /search di Serper, la richiesta non tocca mai eBay direttamente: e' lo
    stesso principio gia' usato per Vestiaire, che infatti non ha mai
    avuto questo problema. Perso il filtro nativo LH_Sold=1 (non
    disponibile fuori dall'URL di ricerca eBay), compensato aggiungendo
    "venduto"/"sold" in query -- lo stesso schema gia' usato con successo
    dalle ricerche on-demand del cervello (cerca_serper_mirata), che infatti
    su eBay trovano spesso dati reali (vedi log 'NWT Brunello Cucinelli...
    1 venduto' nei risultati on-demand) proprio perche' passano da Google
    e non dallo scrape diretto."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", False

    brand_pulito = (brand or "").strip()
    categoria_per_query = (categoria or "").strip()

    if not categoria_per_query:
        return (
            "Categoria non rilevata dal titolo dell'annuncio -- query eBay "
            "saltata per evitare risultati fuorvianti. Se necessario, usa la "
            "function cerca_comp_prezzo con una query piu' mirata."
        ), False

    termine_en = CATEGORIA_TERMINE_EN.get(categoria_per_query, categoria_per_query)
    # Parentesi esplicite sui due OR: senza raggruppamento la sintassi Google
    # ("A OR B OR C" senza parentesi ha precedenza ambigua) rischia di
    # applicare il vincolo site:ebay.* solo a un ramo della query invece che
    # a tutta la ricerca, con risultati fuori da eBay.
    base = f'{brand_pulito} "{termine_en}"'.strip() if brand_pulito else f'"{termine_en}"'
    materiale_pulito = (material_per_ricerca or "").strip()
    if materiale_pulito:
        base = f'{base} "{materiale_pulito}"'
    dettaglio_pulito = (dettaglio_distintivo or "").strip()
    if dettaglio_pulito:
        base = f'{base} "{dettaglio_pulito}"'
    query_serper = f'{base} (venduto OR sold) (site:ebay.it OR site:ebay.com)'

    payload = [{"q": query_serper, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await hc._client_generico.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            # timeout 8s: questa funzione e' anche il FALLBACK di
            # _cerca_ebay_sold_con_fallback, chiamato DOPO il tentativo
            # Resellbot (fino a 12s dal 2026-09-25, vedi
            # _cerca_ebay_sold_via_resellbot) -- il budget totale (12+8=20s)
            # deve restare sotto i 25s di TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI
            # riusato per la fonte "ebay_poshmark" nel fan-out di
            # search_comps_completo, altrimenti la fonte verrebbe scartata
            # come "troppo lenta" anche quando il fallback stava per riuscire.
            json=payload, timeout=8,
        )
        if _e_errore_crediti_serper(resp):
            return f"  Serper fallito (HTTP {resp.status_code}).", False
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}", False

    lines = []
    for batch in results:
        for r in batch.get("organic", [])[:10]:
            titolo = r.get("title", "")
            snippet = r.get("snippet", "")
            match_prezzo = re.search(r"€\s*[\d.,]+|\d+(?:[.,]\d+)?\s*€|EUR\s*[\d.,]+", snippet, re.IGNORECASE)
            snippet_troncato = snippet[:100].rstrip()
            if match_prezzo and match_prezzo.group(0) not in snippet_troncato:
                snippet_troncato += f"... [PREZZO: {match_prezzo.group(0)}]"
            elif len(snippet) > 100:
                snippet_troncato += "..."
            lines.append(f"- {titolo}\n  {snippet_troncato}")
    return ("\n".join(lines) if lines else "Nessun risultato trovato."), True
