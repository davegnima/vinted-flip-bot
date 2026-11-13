"""Ricerca testuale dei comparabili Vinted (usata da Jev: moda e radar)."""
import asyncio


from bot.comps_filtri import campione_pagina_vinted, campione_scheda_vinted, _estrai_articoli_da_alt_vinted, _estrai_mappa_url_comp_vinted, _estrai_miniature_vinted
from bot.vinted_http import _vinted_get_con_retry
from bot import vinted_api
from bot.logger import log
# ---- fine import ----
# Timeout della ricerca testuale Vinted: due tentativi da 8 s al massimo, tetto
# complessivo 16 s.
TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI = 8
TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_TOTALE_SECONDI = 16
MARKER_NESSUN_ARTICOLO_VINTED = "Nessun articolo trovato"


async def _cerca_vinted_testo_diretto(url):
    """Ricerca comp testuale su Vinted: scrape diretto della pagina catalogo
    (stesso client/proxy e stesso parser su alt= gia' usati per la ricerca
    visuale, vedi _scrape_catalogo_vinted_diretto).

    Dal 31/10 e' l'unica via: Serper (che era la riserva) e' stato tolto per
    scelta dell'utente. Se lo scrape fallisce l'annuncio resta senza comp
    Vinted di testo e si va avanti con le altre fonti.

    Contratto di ritorno comune alle fonti: (testo, ok, mappa_url), con il
    testo nel formato '- titolo — €prezzo' una riga per articolo e mappa_url
    (vedi _estrai_mappa_url_comp_vinted) per riattaccare i link ai comp."""
    # 5/11: prima l'API con token anonimo (le pagine HTML danno la shell 'Session refresh'); l'HTML resta come ripiego.
    try:
        via_api = await asyncio.wait_for(vinted_api.cerca_catalogo(url), timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_TOTALE_SECONDI)
    except Exception as e:
        log.info("Comp Vinted testo: API errore %s -- %s", type(e).__name__, url)
        via_api = None
    if via_api:
        testo_api, mappa_api, miniature_api = via_api
        _miniature_comp.update(miniature_api)
        if len(_miniature_comp) > MAX_MINIATURE_COMP:
            _miniature_comp.clear()
        return testo_api, True, mappa_api

    motivo = None
    try:
        resp = await asyncio.wait_for(
            _vinted_get_con_retry(url, timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI, max_retries=2),
            timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_TOTALE_SECONDI,
        )
    except asyncio.TimeoutError:
        resp = None
        motivo = "timeout scrape diretto"
    if resp is not None:
        testo = _estrai_articoli_da_alt_vinted(resp.text)
        # Etichetta proxy (2026-09-27, vedi _vinted_get_con_retry): e' il caso
        # in cui Vinted risponde 200 ma con una pagina non utilizzabile.
        etichetta_proxy = getattr(resp, "_proxy_etichetta", "?")
        if MARKER_NESSUN_ARTICOLO_VINTED not in testo:
            log.info("Comp Vinted testo: scrape diretto OK (%d articoli, proxy=%s) -- %s",
                     testo.count("\n") + 1, etichetta_proxy, url)
            global _schede_scritte
            if _schede_scritte < 2:
                _schede_scritte += 1
                log.info("COMPS SCHEDA CAMPIONE | %s", campione_scheda_vinted(resp.text))
            _miniature_comp.update(_estrai_miniature_vinted(resp.text))
            if len(_miniature_comp) > MAX_MINIATURE_COMP:
                _miniature_comp.clear()
            return testo, True, _estrai_mappa_url_comp_vinted(resp.text)
        motivo = (
            f"scrape diretto senza articoli estratti (proxy={etichetta_proxy}, "
            f"status {resp.status_code}, len {len(resp.text)})"
        )
        # Verifica (25/10): campione del markup quando il parser non trova articoli, per capire il formato cambiato.
        global _campioni_pagina_scritti
        if _campioni_pagina_scritti < 3:
            _campioni_pagina_scritti += 1
            log.info("COMPS PAGINA CAMPIONE | %s", campione_pagina_vinted(resp.text))
    elif motivo is None:
        motivo = "scrape diretto fallito (nessuna risposta)"

    log.info("Comp Vinted testo: %s -- %s", motivo, url)
    return f"  {motivo}", False, {}


_campioni_pagina_scritti = 0
_schede_scritte = 0
# {id annuncio: url miniatura} dei comparabili visti nelle schede catalogo (01/11): serve alla prova "foto dei comparabili a Jev".
_miniature_comp = {}
MAX_MINIATURE_COMP = 3000
