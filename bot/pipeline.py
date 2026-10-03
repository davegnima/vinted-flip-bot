"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import json
import time
import asyncio
import traceback
from functools import partial


from bot.scheda import ANALISI_GEMINI_ATTIVA, STATO_ANALISI_COMPLETATA, STATO_ANALISI_INTERROTTA, _PermessoAnalisi, _aggiorna_stato_scheda, _invia_galleria_anticipata, _invia_risultato_telegram, componi_testi_verdetto
from bot.verdetto import CERVELLO_CAMPIONI_EXTRA, _a_float, _estrai_item_id_da_url, _estrai_prezzi_da_pool_ricerca, _riepilogo_comp_per_fonte, calcola_verdetto, classifica_provenienza_comp, consolida_target_cervello, render_messaggio_verdetto, valida_payload_cervello
from bot.config import GEMINI_SOGLIA_PREZZO_ALTO, CERVELLO_PROVIDER, DEBUG_CONFRONTO_COMP_TELEGRAM, OCCHIO_OUTPUT_JSON, RAFFREDDAMENTO_SERPER_SECONDI, SERPER_API_KEY, SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO, SOGLIA_MARGINE_ASSOLUTO_NOTIFICA, TELEGRAM_OWNER_CHAT_ID, _serper_fallimenti_consecutivi, _serper_notifica_esaurimento_inviata, _serper_timestamp_ultimo_fallimento
from bot.panel import EXTRA_LLM_URL, PANEL_CERVELLO_MODELLI, PANEL_OCCHIO_MODELLI, _bg_task, panel_cervello, panel_occhio
from bot.fair_value import FAIR_VALUE_FILTRA, check_skip_fair_value, fv_registra_gemini, fv_registra_rapida, stima_fair_value
from bot.prompts import GEMINI_CERVELLO_SYSTEM_PROMPT, GEMINI_OCCHI_SYSTEM_PROMPT, GEMINI_OCCHI_SYSTEM_PROMPT_JSON
from bot.schemas import OCCHIO_RESPONSE_SCHEMA_GEMINI
from bot.tracciamento import SKIP_GIA_VENDUTI, _log_esito, tracc_avvia_serie, tracc_registra_gia_venduto, tracc_registra_valutato
from bot.comps_filtri import _arricchisci_brand_per_ricerca
from bot.tempi import _calcola_tempi_pipeline, _formatta_durata, _formatta_tappe_pipeline
from bot.testo import _escapa_markdown_legacy
from bot.vinted_scrape import _scrapa_guardaroba_venditore, scrape_vinted_listing
from bot.skip_report import build_skip_report, check_skip_pre_cervello
from bot.filtri import check_skip_pre_gemini
from bot.gemini_api import chiama_gemini, chiama_gemini_cervello_forzato
from bot.openai_api import chiama_openai_cervello_forzato
from bot.foto import download_image_bytes
from bot.categorie import estrai_categoria_da_titolo
from bot.logger import log
from bot.occhio import render_occhio_da_json, valida_payload_occhio
from bot.comps import search_comps_completo, verifica_codici_prodotto_reddit
from bot.telegram_api import telegram_send_message
from bot.serper_base import valuta_qualita_comp
# ---- fine import ----
async def _campione_target_cervello(chiama, user_text, forza_ricerca):
    """Una valutazione in piu' del Cervello. Ritorna (v|None, problemi, costo): v e' il verdetto validato (il
    chiamante usa quello piu' vicino alla mediana, cosi' testo e numeri restano coerenti)."""
    try:
        vj, err, costo, _n, _raw = await chiama(
            GEMINI_CERVELLO_SYSTEM_PROMPT, user_text, forza_ricerca=forza_ricerca, mappa_url_ricerche_extra={})
        if err:
            return None, [], costo or 0.0
        v2, problemi2 = valida_payload_cervello(vj)
        t = v2.get("prezzo_target_vendita_eur")
        if not (isinstance(t, (int, float)) and t > 0):
            return None, [], costo or 0.0
        return v2, problemi2, costo or 0.0
    except Exception:
        log.warning("Campione extra del Cervello fallito:\n%s", traceback.format_exc())
        return None, [], 0.0


async def process_listing(parsed, url, cover_photo_bytes, msg_date=None, t_ricevuto_bot=None, stato=None,
                          semaforo=None):
    permesso = _PermessoAnalisi(semaforo) if semaforo is not None else None
    esito_finale = STATO_ANALISI_COMPLETATA
    try:
        await _process_listing_interno(parsed, url, cover_photo_bytes, msg_date=msg_date,
                                       t_ricevuto_bot=t_ricevuto_bot, stato=stato,
                                       permesso=permesso)
    except BaseException:
        esito_finale = STATO_ANALISI_INTERROTTA
        raise
    finally:
        if permesso is not None:
            permesso.rilascia()
        await _aggiorna_stato_scheda(stato, esito_finale)


def ruoli_gemini(prezzo, stima_rapida, soglia=None):
    """(tier_alto, ruolo_occhio, ruolo_cervello, da_cosa) per scegliere la cascata Gemini PRIMA dell'Occhio.
    Decide la stima rapida di fair value (tabella + appreso, istantanea): semaforo 🟢/🟡 = margine/ROI promettenti ->
    cascate '_alto' (modelli migliori); 🔴 = poco margine -> base, salvo prezzo >= soglia (le eccezioni sono i capi che la
    tabella sottostima). Se la stima manca o ha confidenza bassa (⚪) si
    ripiega sul prezzo richiesto: dalla soglia (GEMINI_SOGLIA_PREZZO_ALTO) in su = alto."""
    soglia = GEMINI_SOGLIA_PREZZO_ALTO if soglia is None else soglia
    semaforo = (stima_rapida or {}).get("semaforo")
    if semaforo in ("🟢", "🟡"):
        alto, da = True, "stima"
    elif semaforo == "🔴":
        # stima rapida bassa: base, MA dalla soglia di prezzo in su alto lo stesso (le eccezioni sono proprio i capi che
        # la tabella sottostima: es. Dries van Noten 50 EUR, stima rossa, poi COMPRA con target 150)
        alto = prezzo is not None and prezzo >= soglia
        da = "prezzo" if alto else "stima"
    else:
        alto, da = (prezzo is not None and prezzo >= soglia), "prezzo"
    return alto, ("occhio_alto" if alto else "occhio"), ("cervello_alto" if alto else "cervello"), da


async def _process_listing_interno(parsed, url, cover_photo_bytes, msg_date=None, t_ricevuto_bot=None, stato=None,
                                   permesso=None):
    listing_info = dict(parsed)
    listing_info["url"] = url
    t0 = t_ricevuto_bot or time.time()  # arrivo del messaggio del tracker: riferimento dei controlli vendite
    costo_totale = 0.0

    # Cronometro a tappe (richiesto dall'utente il 2026-09-21, dopo aver
    # visto un "telegram->notifica 27s" e chiesto dove si perde il tempo):
    # ogni voce e' (nome, timestamp) nell'ordine in cui la pipeline le
    # attraversa davvero, _formatta_tappe_pipeline le trasforma in durate
    # consecutive per il footer del messaggio e i log. Parte da
    # t_ricevuto_bot (quando Telethon ha consegnato il messaggio del
    # tracker) cosi' la prima tappa "scrape" e' gia' la durata reale dello
    # scraping, non un t=0 fittizio.
    t_tappe = [("ricevuto", t_ricevuto_bot if t_ricevuto_bot is not None else time.time())]

    photo_bytes_list = []
    task_guardaroba = None
    if url:
        # FILTRO PRE-SCRAPE (aggiunto 2026-09-27, utente: ridurre il consumo
        # di banda dei proxy in vista del passaggio a proxy residenziali a
        # consumo, dopo il blocco sistemico del pool datacenter). Riusa
        # check_skip_pre_gemini SULLE SOLE INFO GIA' note dal messaggio del
        # tracker Telegram (listing_info ha gia' title/brand/price da
        # 'parsed', ma NESSUNA descrizione ne' venditore -- quelli arrivano
        # solo con lo scrape qui sotto) per scartare i casi ovvi (brand in
        # blocklist, categoria mai flippabile, linea/variante esclusa per
        # brand, "gilet -blanc"...) PRIMA di spendere una richiesta HTTP
        # (in media ~1.7MB per pagina annuncio, vedi DIAGNOSTICA scrape
        # foto vuoto) su un annuncio che verrebbe scartato comunque un
        # attimo dopo. Nessuna perdita di accuratezza: e' lo STESSO
        # controllo, solo con testo_completo limitato al titolo (niente
        # descrizione ancora) -- puo' quindi mancare un match che serve
        # solo la descrizione, mai aggiungerne uno falso. Il controllo
        # invariato di prima (via listing_info aggiornato con lo scrape,
        # poco sotto) resta come rete di sicurezza per quei casi.
        e_skip_ante, motivo_skip_ante = check_skip_pre_gemini(listing_info)
        if e_skip_ante:
            log.info(
                "FILTRO PRE-SCRAPE ATTIVATO (silenzioso, no notifica, NESSUNA richiesta a Vinted): '%s'. Motivo: %s",
                listing_info.get("title"), motivo_skip_ante,
            )
            _log_esito(listing_info, "SKIP_PRE_SCRAPE", motivo=(motivo_skip_ante or "")[:80])
            return

        # Guardaroba venditore escluso qui e lanciato in parallelo alle foto
        # poco sotto (vedi _scrapa_guardaroba_venditore): le foto non lo
        # aspettano piu'.
        scraped = await scrape_vinted_listing(url, includi_guardaroba=False)
        t_tappe.append(("scrape", time.time()))
        listing_info.update({
            "size": scraped.get("size"), "condition": scraped.get("condition"),
            "description": scraped.get("description"), "age_days": scraped.get("age_days"),
            "catalog_id": scraped.get("catalog_id"), "cover_photo_id": scraped.get("cover_photo_id"),
            "uploaded_text": scraped.get("uploaded_text"), "stato_vendita": scraped.get("stato_vendita"),
            "created_at": scraped.get("created_at"),
            "material_raw": scraped.get("material_raw"),
            "material_per_ricerca": scraped.get("material_per_ricerca"),
            "color_raw": scraped.get("color_raw"),
            "seller_login": scraped.get("seller_login"),
            "seller_id": scraped.get("seller_id"),
            "seller_feedback_count": scraped.get("seller_feedback_count"),
            "seller_feedback_reputation": scraped.get("seller_feedback_reputation"),
            "seller_items_count": scraped.get("seller_items_count"),
            "seller_country": scraped.get("seller_country"),
            "seller_top_items": scraped.get("seller_top_items") or [],
            "seller_wardrobe_debug": scraped.get("seller_wardrobe_debug") or "n/d",
        })

        # GIA' VENDUTO ALLO SCRAPE: i veri affari si chiudono in secondi (bot compratori, richiesto
        # dall'utente il 2026-10-03): se la pagina e' gia' venduta quando arriviamo, il capo era un buon
        # flip. Per ora si registra soltanto (verifica del segnale su dati reali); SKIP_GIA_VENDUTI=1
        # interrompe l'analisi (inutile notificare un capo non piu' acquistabile).
        if listing_info.get("stato_vendita") == "venduto":
            tracc_registra_gia_venduto(listing_info, url, t0)
            if SKIP_GIA_VENDUTI:
                return
        tracc_avvia_serie(listing_info, url, t0)

        # FILTRO PRE-GEMINI
        e_skip_pre, motivo_skip_pre = check_skip_pre_gemini(listing_info)
        if e_skip_pre:
            # Silenzioso: nessuna notifica Telegram per le esclusioni pre-Gemini.
            # Rimane visibile solo nei log (Railway) per debug/controllo. I
            # tempi si loggano comunque (richiesto dall'utente il 2026-09-21):
            # anche un annuncio mai notificato puo' interessare capire quanto
            # ci ha messo ad arrivare fin qui.
            pezzi_tempi_skip, _ = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
            log.info("FILTRO PRE-GEMINI ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s%s (%s)",
                     listing_info.get("title"), motivo_skip_pre,
                     f" — Tempi: {' · '.join(pezzi_tempi_skip)}" if pezzi_tempi_skip else "",
                     " · ".join(_formatta_tappe_pipeline(t_tappe)))
            _log_esito(listing_info, "SKIP_PRE_GEMINI", motivo=(motivo_skip_pre or "")[:80])
            return

        # FAIR VALUE A PRIORI (vedi FAIR_VALUE_TABELLA): istantaneo, nessuna
        # chiamata esterna. La stima finisce nella scheda; il filtro vero e
        # proprio (FAIR_VALUE_FILTRA=1) scarta in silenzio prima di foto e
        # Gemini, di default invece solo si logga cosa scarterebbe.
        try:
            listing_info["fair_value"] = stima_fair_value(listing_info)
            e_skip_fv, motivo_skip_fv = check_skip_fair_value(listing_info)
        except Exception:
            log.warning("Fair value a priori non calcolato:\n%s", traceback.format_exc())
            listing_info["fair_value"] = None
            e_skip_fv, motivo_skip_fv = False, None
        fv_registra_rapida(listing_info, url, scartato=bool(e_skip_fv and FAIR_VALUE_FILTRA))
        if e_skip_fv:
            if FAIR_VALUE_FILTRA:
                log.info("FILTRO FAIR VALUE ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s",
                         listing_info.get("title"), motivo_skip_fv)
                _log_esito(listing_info, "SKIP_FAIR_VALUE", motivo=(motivo_skip_fv or "")[:80])
                return
            log.info("FAIR VALUE PROVA (nessuno scarto, FAIR_VALUE_FILTRA=0): avrebbe scartato '%s'. Motivo: %s",
                     listing_info.get("title"), motivo_skip_fv)

        task_guardaroba = asyncio.create_task(_scrapa_guardaroba_venditore(scraped, url))

        photo_urls = scraped.get("photo_urls", [])
        if not photo_urls:
            log.warning(
                "scrape_vinted_listing non ha restituito nessun photo_url per %s "
                "(pagina annuncio non raggiunta o regex di estrazione foto non ha trovato match).",
                url,
            )
        if photo_urls:
            # Download in parallelo con asyncio.gather al posto del
            # ThreadPoolExecutor: stesso parallelismo, senza thread e senza
            # bloccare il loop mentre le foto arrivano.
            risultati_download = await asyncio.gather(
                *(download_image_bytes(u, referer=url) for u in photo_urls)
            )
            photo_bytes_list = [img for img in risultati_download if img]

            # Se alcune foto non sono state scaricate, ritenta specificamente
            # quelle mancanti invece di procedere silenziosamente con meno
            # foto di quelle disponibili -- l'analisi visiva ne risente molto.
            mancanti = [u for u, img in zip(photo_urls, risultati_download) if img is None]
            if mancanti:
                log.warning(
                    "Download foto incompleto per %s: %d/%d riuscite al primo giro, ritento le mancanti...",
                    url, len(photo_bytes_list), len(photo_urls),
                )
                retry_risultati = await asyncio.gather(
                    *(download_image_bytes(u, referer=url, max_retries=4) for u in mancanti)
                )
                photo_bytes_list.extend([img for img in retry_risultati if img])
                if len(photo_bytes_list) < len(photo_urls):
                    log.warning(
                        "Dopo il retry restano %d/%d foto mancanti per %s -- analisi visiva basata su set incompleto.",
                        len(photo_urls) - len(photo_bytes_list), len(photo_urls), url,
                    )

    fallback_solo_cover_photo = False
    if not photo_bytes_list and cover_photo_bytes:
        photo_bytes_list = [cover_photo_bytes]
        fallback_solo_cover_photo = True
        log.warning(
            "Scraping foto fallito del tutto per %s -- uso solo la cover photo Telegram come fallback.",
            url,
        )
    listing_info["fallback_solo_cover_photo"] = fallback_solo_cover_photo
    t_tappe.append(("foto", time.time()))
    if not photo_bytes_list:
        await telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Niente foto per: {listing_info.get('title')}\nURL: {url or 'non trovato'}\nSalto valutazione.")
        if task_guardaroba is not None:
            task_guardaroba.cancel()
        return

    # Galleria subito nella chat principale (vedi GALLERIA_ANTICIPATA), prima
    # di Occhio/Cervello. Il verdetto la raggiungera' come risposta.
    msg_id_galleria = await _invia_galleria_anticipata(listing_info, url, photo_bytes_list, stato=stato)
    if msg_id_galleria is not None:
        t_tappe.append(("galleria", time.time()))
        if stato is not None:
            # Letto dall'handler se la pipeline va in eccezione da qui in poi,
            # per rispondere alla galleria invece di lasciarla appesa.
            stato["msg_id_galleria"] = msg_id_galleria

    if not ANALISI_GEMINI_ATTIVA:
        if task_guardaroba is not None:
            task_guardaroba.cancel()
        pezzi_tempi_pausa, _ = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
        log.info("ANALISI GEMINI IN PAUSA: solo galleria per '%s'%s%s (%s)",
                 listing_info.get("title"),
                 "" if msg_id_galleria is not None else " -- ATTENZIONE: invio galleria fallito",
                 f" — Tempi: {' · '.join(pezzi_tempi_pausa)}" if pezzi_tempi_pausa else "",
                 " · ".join(_formatta_tappe_pipeline(t_tappe)))
        return

    # Da qui in poi Gemini: solo ora si prende il posto nel tetto di analisi
    # parallele (MAX_ANALISI_PARALLELE). Prima il posto si prendeva
    # all'arrivo del messaggio, quindi in un burst anche scrape e galleria
    # restavano in coda dietro alle analisi Gemini degli altri annunci.
    if permesso is not None:
        await permesso.acquisisci(url)

    if task_guardaroba is not None:
        await task_guardaroba
        listing_info["seller_top_items"] = scraped.get("seller_top_items") or []
        listing_info["seller_wardrobe_debug"] = scraped.get("seller_wardrobe_debug") or "n/d"

    age_days = listing_info.get("age_days")
    age_text = f"{age_days:.1f} giorni fa" if age_days is not None else "non disponibile"

    seller_info_parts = []
    feedback_count = listing_info.get("seller_feedback_count")
    feedback_rep = listing_info.get("seller_feedback_reputation")
    items_count = listing_info.get("seller_items_count")
    seller_login = listing_info.get("seller_login")
    seller_country = listing_info.get("seller_country")
    seller_top_items = listing_info.get("seller_top_items") or []

    if seller_login:
        seller_info_parts.append(f"Username: {seller_login}")
    if seller_country:
        seller_info_parts.append(f"Paese: {seller_country}")
    if feedback_count is not None:
        stelle = f"{feedback_rep:.1f}/5" if feedback_rep is not None else "n/d"
        seller_info_parts.append(f"Recensioni: {feedback_count} ({stelle} stelle)")
    if items_count is not None:
        seller_info_parts.append(f"Articoli in vendita: {items_count}")
    if seller_top_items:
        seller_info_parts.append(f"Primi articoli in vendita: {', '.join(seller_top_items)}")

    seller_info_text = "\n".join(seller_info_parts) if seller_info_parts else "non disponibile"

    user_text_occhi = (
        f"Titolo annuncio: {listing_info.get('title')}\n"
        f"Brand dichiarato: {listing_info.get('brand')}\n"
        f"Prezzo richiesto: {listing_info.get('price')} EUR\n"
        f"Taglia: {listing_info.get('size') or 'non disponibile'}\n"
        f"Condizione dichiarata: {listing_info.get('condition') or 'non disponibile'}\n"
        f"Materiale (da pagina annuncio): {listing_info.get('material_raw') or 'non disponibile'}\n"
        f"Colore (da pagina annuncio): {listing_info.get('color_raw') or 'non disponibile'}\n"
        f"Descrizione venditore: {listing_info.get('description') or 'non disponibile'}\n"
        f"\nPROFILO VENDITORE:\n{seller_info_text}"
    )
    if fallback_solo_cover_photo:
        user_text_occhi += (
            "\n\nATTENZIONE: lo scraping delle foto dell'annuncio e' fallito. Stai vedendo "
            "SOLO l'immagine di copertina, non la galleria completa. NON concludere "
            "'nessuna etichetta visibile' o 'non verificabile' come se il venditore non "
            "avesse fotografato le etichette: molto probabilmente le ha fotografate, ma "
            "quelle foto non sono arrivate fino a te. Valuta cio' che vedi e segnala "
            "esplicitamente il limite."
        )

    # Fascia di modello Gemini scelta SUBITO dal prezzo richiesto (dato del tracker, disponibile prima dell'Occhio):
    # dalla soglia in su Occhio e Cervello partono dalle cascate "_alto" (modelli migliori), sotto da quelle base.
    # Nessuna chiamata in piu' ne' in coda: cambia solo quale modello si interroga per primo.
    tier_alto, ruolo_occhio, ruolo_cervello, tier_da = ruoli_gemini(
        _a_float(listing_info.get("price"), None), listing_info.get("fair_value"))

    # --- OCCHIO: due rami, scelti da OCCHIO_OUTPUT_JSON.
    # In entrambi i casi il resto della pipeline riceve `output_occhi` come
    # testo: in modalita' JSON e' il rendering del dict, cosi' build_skip_report
    # e il prompt del Cervello continuano a funzionare senza modifiche.
    occhio_json = None
    problemi_occhio = []
    if OCCHIO_OUTPUT_JSON:
        output_grezzo, costo_occhi, _ = await chiama_gemini(
            GEMINI_OCCHI_SYSTEM_PROMPT_JSON, user_text_occhi, photo_bytes_list,
            grounding=False, response_schema=OCCHIO_RESPONSE_SCHEMA_GEMINI, ruolo=ruolo_occhio)
        try:
            occhio_json, problemi_occhio = valida_payload_occhio(json.loads(output_grezzo))
            output_occhi = render_occhio_da_json(occhio_json, problemi_occhio)
            if problemi_occhio:
                log.info("Occhio JSON con %d anomalie: %s", len(problemi_occhio), problemi_occhio)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # Fallback esplicito e non silenzioso: se il JSON non e'
            # parsabile si prosegue col testo grezzo sul ramo prosa, cosi'
            # un annuncio non va perso per un problema di formato. Se
            # compare spesso nei log, e' il segnale che flash-lite non
            # regge lo schema e conviene rimettere OCCHIO_OUTPUT_JSON=false.
            log.warning("Occhio: JSON non parsabile (%s), fallback al ramo prosa. Grezzo: %s",
                        e, (output_grezzo or "")[:400])
            occhio_json = None
            output_occhi = output_grezzo
    else:
        output_occhi, costo_occhi, _ = await chiama_gemini(
            GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False, ruolo=ruolo_occhio)
    costo_totale += costo_occhi
    t_tappe.append(("occhio", time.time()))
    if EXTRA_LLM_URL and PANEL_OCCHIO_MODELLI:
        _bg_task(panel_occhio(_estrai_item_id_da_url(url), listing_info.get("brand"), user_text_occhi,
                              photo_bytes_list, occhio_json, problemi_occhio))

    # Prezzo del prodotto: base di OGNI calcolo economico a valle.
    prezzo_prodotto = _a_float(listing_info.get("price"), None)

    decisione = "NON COMPRARE"
    urgenza = "Bassa"
    n_query_grounding = 0
    costo_cervello = 0.0
    costo_campioni = 0.0
    campioni_target = None
    stima_instabile = False
    pool_ricerca_grezzo = ""
    tentare_ricerca_visuale = False
    fonte_visuale_riuscita = False
    forza_ricerca = None
    verdetto_calcolato = None
    legit_cervello = None

    e_skip, motivo_skip = check_skip_pre_cervello(output_occhi, listing_info, occhio_json=occhio_json)
    if e_skip:
        log.info("FILTRO PRE-CERVELLO ATTIVATO. Motivo: %s", motivo_skip)
        if motivo_skip.startswith("[FALSO CONCLAMATO"):
            log.info("FALSO CONCLAMATO -- output occhi grezzo per '%s':\n%s", listing_info.get("title"), output_occhi)
        output_finale = build_skip_report(listing_info, motivo_skip, output_occhi_testo=output_occhi)
        scenario_usato = "SKIP"
        _log_esito(listing_info, "SKIP_PRE_CERVELLO", motivo=motivo_skip[:80])
    else:
        titolo_annuncio = listing_info.get("title") or ""
        brand_annuncio = listing_info.get("brand") or ""
        categoria_per_ricerca = estrai_categoria_da_titolo(
            titolo_annuncio, listing_info.get("description")) or ""
        catalog_id = listing_info.get("catalog_id")
        material_per_ricerca = listing_info.get("material_per_ricerca")
        cover_photo_id = listing_info.get("cover_photo_id")
        item_id_annuncio = _estrai_item_id_da_url(url)

        # Brand da usare per la RICERCA comp, arricchito con la sottolinea
        # (nome_sottolinea) e/o la linea/etichetta specifica (linea_o_era)
        # lette dall'Occhio sull'etichetta quando presenti. Vedi il
        # docstring di _arricchisci_brand_per_ricerca per la casistica
        # completa (Weekend Max Mara, M Missoni, JPG "JPG.JEAN'S" ecc.) --
        # generalizzato il 2026-09-22 su richiesta dell'utente per coprire
        # anche i casi in cui la sottolinea/linea vive in linea_o_era
        # anziche' in nome_sottolinea.
        brand_per_ricerca = _arricchisci_brand_per_ricerca(brand_annuncio, occhio_json)

        # Nome del sarto/maker reale, DIVERSO dal brand dichiarato E dalla
        # sottolinea gia' gestita sopra (aggiunto il 2026-09-20, caso reale:
        # annuncio con brand Vinted "Loro Piana" -- in realta' solo il nome
        # del TESSUTO usato -- ma etichetta fisica del vero produttore "I
        # Caracciolo", sartoria terza che ha usato quel tessuto. Il capo
        # NON e' una sottolinea di Loro Piana (non esiste "Loro Piana by
        # Caracciolo"), e' un capo di un maker completamente diverso: la
        # ricerca comp strutturata su "Loro Piana" resta comunque utile (e'
        # il mercato di riferimento per capi in quel tessuto), ma da sola
        # ignora completamente se il nome del sarto abbia un suo valore di
        # mercato riconoscibile -- vedi il fan-out extra sotto in
        # search_comps_completo (parametro nome_sarto).
        nome_sarto_o_maker = None
        if occhio_json:
            brand_letto = str(occhio_json.get("brand_letto_etichetta") or "").strip()
            if (
                brand_letto
                and occhio_json.get("relazione_brand") != "sottolinea_stessa_maison"
                and brand_letto.lower() not in brand_annuncio.lower()
                and brand_annuncio.lower() not in brand_letto.lower()
            ):
                nome_sarto_o_maker = brand_letto
                log.info(
                    "process_listing: nome sarto/maker diverso dal brand dichiarato rilevato "
                    "dall'Occhio: '%s' (brand dichiarato: '%s') -- aggiunta ricerca comp extra.",
                    nome_sarto_o_maker, brand_annuncio,
                )

        # Dettaglio distintivo di taglio/design (aggiunto il 2026-09-25, vedi
        # occhio_schema.dettaglio_distintivo_ricerca): usato per restringere
        # la query eBay/Poshmark su Resellbot oltre a brand+categoria+materiale
        # -- stesso schema di nome_sarto_o_maker sopra, letto qui dal JSON
        # dell'Occhio e inoltrato a search_comps_completo.
        dettaglio_distintivo = None
        if occhio_json:
            dettaglio_distintivo = (str(occhio_json.get("dettaglio_distintivo_ricerca") or "").strip() or None)

        scenario_usato = "F"
        comps_text = None
        mappa_url_comp = {}

        tempo_trascorso = time.time() - _serper_timestamp_ultimo_fallimento[0]
        in_raffreddamento = (
            _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO
            and tempo_trascorso < RAFFREDDAMENTO_SERPER_SECONDI
        )
        serper_disponibile = bool(SERPER_API_KEY) and not in_raffreddamento

        # Verifica codici prodotto su Reddit (aggiunta 2026-09-26): lanciata
        # in parallelo alla ricerca comp con asyncio.gather, cosi' non
        # aggiunge secondi alla pipeline -- gira anche quando Serper non e'
        # disponibile, e' del tutto indipendente da lui. Se REDDIT_ABILITATO
        # e' False (credenziali non configurate) ritorna subito "" senza
        # fare alcuna chiamata di rete.
        if serper_disponibile:
            (comps_text, serper_ok, tentare_ricerca_visuale, fonte_visuale_riuscita, mappa_url_comp), testo_verifica_codici = await asyncio.gather(
                search_comps_completo(
                    brand_per_ricerca, categoria_per_ricerca, titolo_annuncio,
                    catalog_id=catalog_id, material_per_ricerca=material_per_ricerca,
                    cover_photo_id=cover_photo_id, item_id=item_id_annuncio,
                    nome_sarto=nome_sarto_o_maker, dettaglio_distintivo=dettaglio_distintivo,
                ),
                verifica_codici_prodotto_reddit(occhio_json, brand_per_ricerca, categoria_per_ricerca=categoria_per_ricerca),
            )
            t_tappe.append(("comp", time.time()))
            if serper_ok:
                scenario_usato = "G"
                _serper_fallimenti_consecutivi[0] = 0
                if _serper_notifica_esaurimento_inviata[0]:
                    _serper_notifica_esaurimento_inviata[0] = False
                    await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, "✅ Serper e' tornato a funzionare normalmente.")
            else:
                _serper_fallimenti_consecutivi[0] += 1
                _serper_timestamp_ultimo_fallimento[0] = time.time()
                if _serper_fallimenti_consecutivi[0] >= SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO:
                    if not _serper_notifica_esaurimento_inviata[0]:
                        _serper_notifica_esaurimento_inviata[0] = True
                        await telegram_send_message(
                            TELEGRAM_OWNER_CHAT_ID,
                            f"⚠️ *Serper ha esaurito i crediti o non risponde*.\nFallback a Scenario F per {RAFFREDDAMENTO_SERPER_SECONDI/3600:.0f} ore."
                        )
        else:
            testo_verifica_codici = await verifica_codici_prodotto_reddit(occhio_json, brand_per_ricerca, categoria_per_ricerca=categoria_per_ricerca)

        if testo_verifica_codici:
            output_occhi += testo_verifica_codici

        contesto_listing = (
            f"{user_text_occhi}\n"
            f"Annuncio pubblicato: {age_text}\n"
            f"URL annuncio: {url or 'non disponibile'}"
        )
        if scenario_usato == "G":
            comp_sufficienti = valuta_qualita_comp(comps_text)
            forza_ricerca = not comp_sufficienti
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                f"--- {comps_text} ---\n\n"
                "Usa i risultati di ricerca web PRE-RACCOLTI come base. Se sono insufficienti, "
                "assenti o palesemente fuori tema, chiama la function cerca_comp_prezzo con una "
                "query mirata prima di dare il verdetto finale."
            )
        else:
            forza_ricerca = True
            user_text_cervello = (
                f"{contesto_listing}\n\n"
                f"--- LA TUA VALUTAZIONE PRELIMINARE ---\n"
                f"{output_occhi}\n--- FINE ---\n\n"
                "NOTA: non ci sono risultati di ricerca pre-raccolti. Chiama la function "
                "cerca_comp_prezzo per ottenere comp reali prima di rispondere."
            )

        chiama_cervello = (
            chiama_openai_cervello_forzato if CERVELLO_PROVIDER == "openai"
            else partial(chiama_gemini_cervello_forzato, ruolo=ruolo_cervello)
        )
        # Mappa URL delle ricerche on-demand (Punto 3 esteso il 2026-09-25):
        # riempita IN PLACE da chiama_cervello mentre elabora le eventuali
        # chiamate a cerca_comp_prezzo -- vedi mappa_url_ricerche_extra in
        # chiama_gemini_cervello_forzato/chiama_openai_cervello_forzato.
        mappa_url_ricerche_extra = {}
        verdetto_json, errore_cervello, costo_cervello, n_query_grounding, ricerche_extra_raw = await chiama_cervello(
            GEMINI_CERVELLO_SYSTEM_PROMPT, user_text_cervello, forza_ricerca=forza_ricerca,
            mappa_url_ricerche_extra=mappa_url_ricerche_extra)
        costo_totale += costo_cervello
        t_tappe.append(("cervello", time.time()))

        # Unione con la mappa dei comp pre-raccolti (Vinted/Resellbot): in
        # caso di chiave duplicata vince quest'ultima, piu' affidabile (dati
        # strutturati con ID/URL diretto, non un match best-effort su
        # titolo+prezzo estratto da uno snippet Google).
        mappa_url_comp = {**mappa_url_ricerche_extra, **mappa_url_comp}

        # Pool di TUTTO il testo grezzo di ricerca visto dal cervello per
        # questo item: comp pre-raccolti (Scenario G) + eventuali ricerche
        # on-demand. Serve a stabilire la provenienza reale di ogni comp che
        # il cervello dichiara (vedi classifica_provenienza_comp).
        pool_ricerca_grezzo = "\n".join(filter(None, [comps_text] + ricerche_extra_raw))

        if errore_cervello:
            # Un errore qui e' definitivo: senza il JSON non c'e' verdetto da
            # calcolare. Si avvisa invece di restare in silenzio, perche' un
            # annuncio valutato a meta' e' peggio di uno non valutato.
            log.warning("Cervello fallito per '%s': %s", listing_info.get("title"), errore_cervello)
            _log_esito(listing_info, "ERRORE_CERVELLO")
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                f"⚠️ *Valutazione non completata* — {listing_info.get('title')}\n"
                f"{errore_cervello}\n{url or ''}\n"
                f"_Costo comunque sostenuto: ${costo_totale:.4f}_",
                reply_to=msg_id_galleria,
            )
            return

        v, problemi = valida_payload_cervello(verdetto_json)
        stats_comp = classifica_provenienza_comp(v, pool_ricerca_grezzo)
        legit_cervello = v.get("legit_verdetto")
        verdetto_calcolato = calcola_verdetto(v, prezzo_prodotto)
        campioni_target = None
        stima_instabile = False
        if CERVELLO_CAMPIONI_EXTRA > 0 and verdetto_calcolato["decisione"] in ("COMPRA", "TRATTA"):
            # Valutazioni extra in PARALLELO (la latenza e' quella di una sola chiamata). Si usa la mediana dei
            # target e, come verdetto di riferimento, la valutazione piu' vicina alla mediana: testo
            # dell'analista, comparabili e numeri restano coerenti tra loro.
            extra = await asyncio.gather(*(
                _campione_target_cervello(chiama_cervello, user_text_cervello, forza_ricerca)
                for _ in range(CERVELLO_CAMPIONI_EXTRA)))
            costo_campioni = sum(c for _, _, c in extra)
            costo_totale += costo_campioni
            campioni = [(v, problemi)] + [(v2, p2) for v2, p2, _ in extra if v2 is not None]
            targets = [c[0].get("prezzo_target_vendita_eur") for c in campioni]
            valore_c, spread_c, stima_instabile = consolida_target_cervello(targets)
            campioni_target = "/".join(f"{t:.0f}" for t in sorted(t for t in targets if t))
            if valore_c is not None and len(campioni) > 1:
                v, problemi = min(campioni, key=lambda c: abs(c[0]["prezzo_target_vendita_eur"] - valore_c))
                v["prezzo_target_vendita_eur"] = valore_c
                stats_comp = classifica_provenienza_comp(v, pool_ricerca_grezzo)
                legit_cervello = v.get("legit_verdetto")
                verdetto_calcolato = calcola_verdetto(v, prezzo_prodotto)
            t_tappe.append(("campioni_target", time.time()))
        if EXTRA_LLM_URL and PANEL_CERVELLO_MODELLI:
            _bg_task(panel_cervello(item_id_annuncio, brand_per_ricerca, user_text_cervello, prezzo_prodotto,
                                    v, verdetto_calcolato))
        decisione = verdetto_calcolato["decisione"]
        urgenza = verdetto_calcolato["urgenza"]
        output_finale = render_messaggio_verdetto(
            v, verdetto_calcolato, problemi, stats_comp,
            item_id=item_id_annuncio, cover_photo_id=cover_photo_id, brand=brand_per_ricerca,
            catalog_id=catalog_id, mappa_url_comp=mappa_url_comp,
        )

        log.info(
            "Verdetto '%s': %s (%s urgenza) — margine=%s ROI=%s — comp usati=%d (%d da memoria) — limiti=%s",
            listing_info.get("title"), decisione, urgenza,
            f"{verdetto_calcolato['margine']:.2f}" if verdetto_calcolato["margine"] is not None else "n/d",
            f"{verdetto_calcolato['roi']:.0f}%" if verdetto_calcolato["roi"] is not None else "n/d",
            len(verdetto_calcolato["comp_usati"]), stats_comp["n_memoria"],
            verdetto_calcolato["limiti_applicati"] or "nessuno",
        )
        _log_esito(
            listing_info, decisione,
            margine=f"{verdetto_calcolato['margine']:.0f}" if verdetto_calcolato["margine"] is not None else None,
            roi=f"{verdetto_calcolato['roi']:.0f}%" if verdetto_calcolato["roi"] is not None else None,
            legit=legit_cervello,
            acquisto=f"{prezzo_prodotto:.0f}" if isinstance(prezzo_prodotto, (int, float)) else None,
            target=f"{v['prezzo_target_vendita_eur']:.0f}" if isinstance(v.get("prezzo_target_vendita_eur"), (int, float)) else None,
            n_comp=len(verdetto_calcolato["comp_usati"]),
            campioni=campioni_target, instabile="si" if stima_instabile else None,
            tier="alto" if tier_alto else "base", tier_da=tier_da,
        )
        tracc_registra_valutato(
            listing_info, url, decisione,
            target=v.get("prezzo_target_vendita_eur"), n_comp=len(verdetto_calcolato["comp_usati"]),
        )

    e_compra = decisione in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO")

    # ---- GATE MARGINE ASSOLUTO (qualita' del deal, non sicurezza) ----
    # Sopprime la notifica quando il margine netto resta sotto l'obiettivo
    # operativo, anche se ROI e soglia minima sono superati. Ora legge il
    # margine calcolato invece di riestrarlo con una regex dal testo.
    if verdetto_calcolato and SOGLIA_MARGINE_ASSOLUTO_NOTIFICA > 0:
        margine_finale = verdetto_calcolato["margine"]
        if (
            margine_finale is not None
            and margine_finale < SOGLIA_MARGINE_ASSOLUTO_NOTIFICA
            and decisione != "NON COMPRARE"
        ):
            pezzi_tempi_gate, _ = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
            log.info(
                "GATE MARGINE ASSOLUTO: notifica soppressa per '%s' (margine=%.2f EUR < soglia %d EUR). Decisione: %s%s (%s)",
                listing_info.get("title"), margine_finale, SOGLIA_MARGINE_ASSOLUTO_NOTIFICA, decisione,
                f" — Tempi: {' · '.join(pezzi_tempi_gate)}" if pezzi_tempi_gate else "",
                " · ".join(_formatta_tappe_pipeline(t_tappe)),
            )
            if msg_id_galleria is not None:
                # La galleria e' gia' in chat: chiuderla invece di lasciarla appesa su "Analisi in corso...".
                # Dal 2026-10-03 senza un messaggio in piu': si riscrive la riga di stato della scheda.
                testo_gate = (f"🔇 {decisione}: margine {margine_finale:.2f} € sotto la soglia di notifica "
                              f"({SOGLIA_MARGINE_ASSOLUTO_NOTIFICA} €), verdetto non inviato")
                if stato is not None and stato.get("msg_id_scheda"):
                    stato["stato_finale_override"] = testo_gate
                else:
                    await telegram_send_message(
                        TELEGRAM_OWNER_CHAT_ID, testo_gate + ".", disable_notification=True, reply_to=msg_id_galleria,
                    )
            return

    if scenario_usato == "SKIP":
        info_scenario = " · filtro pre-cervello (occhi soli)"
    elif scenario_usato == "F":
        info_scenario = " · nessun comp pre-raccolto, ricerca forzata"
        info_scenario += f" ({n_query_grounding} extra)" if n_query_grounding else ""
    else:  # Scenario G
        if forza_ricerca:
            info_scenario = " · comp pre-raccolti scarsi, ricerca forzata"
        else:
            info_scenario = " · comp pre-raccolti sufficienti"
        info_scenario += f" ({n_query_grounding} extra)" if n_query_grounding else " (nessuna extra)"

    info_foto = ""
    if listing_info.get("fallback_solo_cover_photo"):
        info_foto = (
            "\n⚠️ *Scraping foto Vinted fallito* (probabile blocco/rate-limit) — "
            "analisi basata SOLO sulla cover photo Telegram, non sulle foto reali "
            "dell'annuncio. Un eventuale 'nessuna etichetta visibile' potrebbe "
            "essere un falso negativo dovuto a questo, non ai capi reali."
        )

    # Titolo e brand vengono dallo scraping Vinted, non scritti da noi: un
    # titolo con underscore/asterisco (es. "T_shirt_vintage") rompe il
    # parsing Markdown esattamente come il testo del modello altrove (stesso
    # bug del 2026-09-20, qui pero' sulla RIGA PIU' VISTA del messaggio,
    # dentro *asterischi* di grassetto per giunta -- priorita' alta).
    # Riga "Scenario" spostata in fondo al messaggio (richiesto dall'utente
    # il 2026-09-20): e' un dettaglio diagnostico su come e' stata condotta
    # la ricerca comp, non qualcosa che serve per decidere -- non ha senso
    # occupare una riga in cima, dove il tempo di lettura e' piu' prezioso.
    # Riga esito in cima anche per lo SKIP (richiesto dall'utente il
    # 2026-09-20): stesso principio delle altre decisioni (emoji + esito
    # prima di tutto), qui pero' senza brand/urgenza accodati -- lo SKIP e'
    # un filtro pre-cervello, non un verdetto con margine, e brand/prezzo
    # restano comunque visibili subito sotto nella riga titolo esistente.
    riga_skip = "🚫 *SKIP*\n" if scenario_usato == "SKIP" else ""

    header = (
        riga_skip
        + f"🆕 *{_escapa_markdown_legacy(listing_info.get('title'))}*\n"
        f"🏷️ {_escapa_markdown_legacy(listing_info.get('brand')) or '?'} · 💰 {listing_info.get('price') or '?'} EUR"
        f"{info_foto}"
        + f"\n{'—' * 20}\n"  # niente URL nel testo: c'e' il bottone "Apri su Vinted"
    )

    # ---- BLOCCO DIAGNOSTICO: da dove vengono i comp REALMENTE ricevuti ----
    # Attivo solo con DEBUG_CONFRONTO_COMP_TELEGRAM=true. Puro post-processing
    # su dati gia' raccolti: nessuna chiamata IA aggiuntiva, costo zero.
    if DEBUG_CONFRONTO_COMP_TELEGRAM and scenario_usato != "SKIP":
        n_prezzi_pool_debug = len(_estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo))
        if fonte_visuale_riuscita:
            nota_visuale = "✅ riuscita"
        elif tentare_ricerca_visuale:
            nota_visuale = "❌ fallita per questo item"
        else:
            nota_visuale = "— non tentata"
        output_finale += (
            f"\n\n🔬 *DEBUG* — {n_prezzi_pool_debug} prezzi reali ricevuti, "
            f"visuale: {nota_visuale}\n"
            f"{_riepilogo_comp_per_fonte(pool_ricerca_grezzo)}"
        )

    # ---- FOOTER: scenario + costo IA -- entrambi dettagli diagnostici, non
    # decisionali, quindi in fondo al messaggio (vedi nota sopra su header) ----
    # Lo scenario e' un dettaglio diagnostico: nel log, non nel messaggio.
    log.info("Scenario %s%s per '%s'", scenario_usato, info_scenario, listing_info.get("title"))
    if scenario_usato == "SKIP":
        footer_costo = f"\n💵 _Costo IA: 👁 ${costo_occhi:.4f} · Cervello non consultato_"
    else:
        footer_costo = (
            f"\n💵 _Costo IA: 👁 ${costo_occhi:.4f} + 🧠 ${costo_cervello:.4f}"
            + (f" + campioni ${costo_campioni:.4f}" if costo_campioni else "")
            + f" = ${costo_totale:.4f}_"
        )
    # ---- FOOTER: tempi (richiesto dall'utente il 2026-09-21, "perdo casi
    # perche' gia' acquistati -- vorrei monitorare il delay tra ogni step:
    # pubblicazione annuncio -> scrape/messaggio del tracker -> nostra
    # pipeline -> notifica"). Due tappe misurabili da qui:
    #   pubblicato -> telegram: da created_at (data pubblicazione Vinted,
    #     letta dalla pagina annuncio) a event.message.date (quando il
    #     tracker esterno ha postato l'alert nel gruppo) -- e' il ritardo
    #     PRIMA di noi (scraping+relay del tracker), fuori dal nostro
    #     controllo ma utile da vedere separato dal resto.
    #   telegram -> notifica: da quando il nostro handler ha ricevuto quel
    #     messaggio (t_ricevuto_bot) a ORA, un attimo prima di inviare --
    #     questo e' il nostro overhead (scrape Vinted, download foto,
    #     Occhio, eventuale Cervello) ed e' la parte su cui possiamo agire.
    # Nessuna delle due parti e' garantita disponibile (created_at manca se
    # Vinted non espone la data in pagina; msg_date/t_ricevuto_bot mancano
    # se process_listing viene chiamato da un altro percorso in futuro):
    # ogni pezzo mancante si omette invece di mostrare un numero fasullo.
    # Tappa finale del cronometro: da qui in poi resta solo costruire il
    # messaggio e inviarlo (network verso Telegram, non cronometrato a
    # parte -- e' gia' incluso nel 'totale'/'telegram->notifica' sopra).
    t_tappe.append(("invio", time.time()))
    dettaglio_tappe = _formatta_tappe_pipeline(t_tappe)

    pezzi_tempi, _secondi_tempi = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
    footer_tempi = (f"\n⏱ _✅ completata · {' · '.join(pezzi_tempi + dettaglio_tappe)}_"
                    if (pezzi_tempi or dettaglio_tappe) else "")
    if pezzi_tempi or dettaglio_tappe:
        log.info("Tempi pipeline per '%s': %s (%s)", listing_info.get("title"),
                  " · ".join(pezzi_tempi), " · ".join(dettaglio_tappe))

    output_finale = output_finale + "\n" + footer_costo + footer_tempi
    # Footer del messaggio compatto: costo IA e tempo notifica come emoji + valore (dettaglio per tappa nei log).
    _notifica = _secondi_tempi.get("telegram_notifica")
    footer_compatto = (f"💵 ${costo_totale:.3f}" if scenario_usato != "SKIP" else "") + (
        f" · ⏱ {_formatta_durata(_notifica)}" if _notifica else "")

    # Verdetto + riga economica in cima al messaggio, poi brand accodato alla
    # riga decisione (richiesto dall'utente il 2026-09-20, secondo giro di
    # layout: prima si leggeva emoji/decisione/urgenza, poi titolo, poi
    # prezzo grezzo, poi solo dopo il margine -- troppi salti per un
    # messaggio pensato per ~3 secondi di lettura su notifica). Ordine
    # finale: decisione+brand, margine/ROI, titolo, link. La riga col
    # prezzo grezzo dell'annuncio sparisce come riga a se': e' gia'
    # implicita nella cifra "acquisto pieno" della riga margine (che include
    # anche protezione acquisti e spedizione, quindi e' il numero che conta
    # davvero). render_messaggio_verdetto scrive decisione come prima riga e
    # margine/ROI (o l'avviso "calcolo non disponibile") come seconda, per
    # costruzione: si staccano entrambe e si ricompone l'header da zero.
    # Non tocca lo scenario SKIP: build_skip_report ha un formato diverso
    # (piu' verboso, "## Verdetto operativo" come intestazione di sezione,
    # non righe singole) e non fa parte del layout compatto riprogettato in
    # questa sessione.
    testo_unificato = None
    if scenario_usato != "SKIP" and "\n" in output_finale:
        header, output_finale, testo_unificato = componi_testi_verdetto(
            listing_info, verdetto_calcolato, output_finale, info_foto, campioni_target, stima_instabile, url=url,
            v=v, footer_compatto=footer_compatto)

    try:
        fv_registra_gemini(listing_info, url, decisione, verdetto_calcolato,
                           occhio_json=occhio_json, legit=legit_cervello)
    except Exception:
        log.warning("Esito Gemini non archiviato:\n%s", traceback.format_exc())
    if scenario_usato == "SKIP":
        # Richiesto dall'utente il 2026-10-03: lo SKIP non manda messaggi, resta solo nei log (SKIP_PRE_CERVELLO
        # nell'ESITO). Se la scheda e' gia' in chat, la sua riga di stato dice solo che e' stato scartato.
        log.info("SKIP non inviato su Telegram per '%s': %s", listing_info.get("title"), motivo_skip)
        if stato is not None and stato.get("msg_id_scheda"):
            stato["stato_finale_override"] = f"🚫 Scartato: {(motivo_skip or '')[:120]}"
        return
    await _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, urgenza,
        margine=verdetto_calcolato["margine"] if verdetto_calcolato else None,
        msg_id_galleria=msg_id_galleria, stato=stato, testo_unificato=testo_unificato,
    )
