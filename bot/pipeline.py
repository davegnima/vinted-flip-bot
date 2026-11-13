"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import time
import asyncio
import traceback


from bot.scheda import aggiorna_scheda_jev, testo_avviso_solo_semaforo, _invia_galleria_anticipata, aggiorna_preavviso, invia_galleria_dopo_lampo, invia_preavviso, riga_scarto_preavviso, testo_preavviso
from bot.parsing import _a_float, _estrai_item_id_da_url
from bot.config import TELEGRAM_ALERT_CHAT_ID, TELEGRAM_OWNER_CHAT_ID
from bot.moda_jev import MODA_JEV_DISPERSIONE_MAX, MODA_JEV_SUBITO, serve_ombra, tratteni_per_verifica, verifica as verifica_moda_jev, righe_messaggio as righe_moda_jev, azione_codice, riga_verdetto as riga_verdetto_jev, riga_originalita as riga_originalita_jev, riga_esito_scheda
from bot.fair_value import REGOLA_DA_VERIFICARE, FAIR_VALUE_FILTRA, catalogo_impara, check_skip_fair_value, fv_registra_jev, fv_registra_rapida, stima_fair_value, valuta_preavviso, preavviso_con_suono, PREAVVISO_LAMPO
from bot import db
from bot.tracciamento import SKIP_GIA_VENDUTI, _log_esito, campi_annuncio, tracc_avvia_serie, tracc_registra_gia_venduto
from bot.tempi import parse_caricato_secondi, _calcola_tempi_pipeline, _formatta_tappe_pipeline
from bot.vinted_scrape import scrape_vinted_listing
from bot.filtri import check_skip_pre_gemini
from bot.foto import download_image_bytes
from bot.categorie import estrai_categoria_da_titolo
from bot.logger import log
from bot.telegram_api import telegram_send_message
# ---- fine import ----

_TASK_OMBRA = set()


async def process_listing(parsed, url, cover_photo_bytes, msg_date=None, t_ricevuto_bot=None, stato=None):
    if stato is None:
        stato = {}
    interrotta = False
    try:
        await _process_listing_interno(parsed, url, cover_photo_bytes, msg_date=msg_date,
                                       t_ricevuto_bot=t_ricevuto_bot, stato=stato)
    except BaseException as e:
        interrotta = True
        riavvio = not isinstance(e, Exception)   # CancelledError/KeyboardInterrupt: il bot si sta fermando (deploy), non e' un errore dell'analisi
        stato["_interrotta_da_riavvio"] = riavvio
        raise
    finally:
        # preavviso rimasto senza verdetto (scartato o analisi interrotta): riga finale
        if stato.get("task_preavviso") is not None and not stato.get("preavviso_aggiornato"):
            await aggiorna_preavviso(
                stato, url, riga_finale=riga_scarto_preavviso(
                    (stato.get("listing_info") or {}).get("_motivo_scarto"),
                    stato.get("msg_id_scheda") or stato.get("msg_id_galleria"),
                    interrotta=interrotta,
                    riavvio=bool(stato.get("_interrotta_da_riavvio"))))


LAMPO_SENZA_CATEGORIA_MARGINE_MIN = float(os.environ.get("LAMPO_SENZA_CATEGORIA_MARGINE_MIN", "50"))   # 0 = spento


def _preavviso_lampo(listing_info, url, cover_photo_bytes, msg_date, t_ricevuto_bot, stato):
    """Preavviso prima dello scrape (PREAVVISO_LAMPO): usa solo titolo, brand e prezzo del tracker e la foto di copertina.
    Parte solo se la categoria si legge dal titolo (stima affidabile senza pagina) e la regola del preavviso scatta.
    Il messaggio viene poi aggiornato col verdetto come ogni preavviso; quello dopo lo scrape non parte piu'. Non solleva mai."""
    try:
        fv = stima_fair_value(listing_info)
        prezzo = _a_float(listing_info.get("price"), None)
        if not fv:
            return
        attivo, regola = valuta_preavviso(fv, prezzo)
        senza_categoria = fv.get("fonte_categoria") != "titolo"
        if senza_categoria:
            # 9/11 (utente: 'fai partire anche senza categoria nel titolo', preavviso arrivato dopo 22 s): parte lo stesso se la stima rapida
            # e' 🟢 con margine >= LAMPO_SENZA_CATEGORIA_MARGINE_MIN (anche 'da verificare'); il verdetto lo corregge dopo (scartato/confermato).
            marg = _a_float(fv.get("margine"), None)
            if not (LAMPO_SENZA_CATEGORIA_MARGINE_MIN > 0 and attivo and fv.get("semaforo") == "🟢" and marg is not None
                    and marg >= LAMPO_SENZA_CATEGORIA_MARGINE_MIN):
                return
        elif not attivo or regola == REGOLA_DA_VERIFICARE or (tratteni_per_verifica(fv, regola) and not MODA_JEV_SUBITO):
            return   # con MODA_JEV_SUBITO=0 l'avviso aspetta la verifica Jev (comparabili e foto): niente lampo
        info = dict(listing_info, fair_value=fv, preavviso=True, preavviso_suono=preavviso_con_suono(fv, prezzo))
        try:
            pezzi, sec = _calcola_tempi_pipeline(info, msg_date, t_ricevuto_bot)
        except Exception:
            pezzi, sec = [], None
        riga_tempi = ("⏱ " + " · ".join(p.replace("telegram→notifica", "telegram→preavviso").replace("pubblicato", "caricato")
                                       for p in pezzi)) if pezzi else None
        stato["task_preavviso"] = asyncio.create_task(invia_preavviso(info, url, [cover_photo_bytes], riga_tempi=riga_tempi, secondi=sec))
        stato["preavviso_lampo"] = True
        log.info("PREAVVISO LAMPO | item=%s | regola=%s | semaforo=%s | prezzo=%s", _estrai_item_id_da_url(url), regola, fv.get("semaforo"), prezzo)
    except Exception:
        log.warning("Preavviso lampo non inviato:\n%s", traceback.format_exc())


async def _process_listing_interno(parsed, url, cover_photo_bytes, msg_date=None, t_ricevuto_bot=None, stato=None):
    listing_info = dict(parsed)
    listing_info["url"] = url
    if stato is not None:
        stato["listing_info"] = listing_info   # letto a fine analisi (motivo dello scarto per il preavviso)
    t0 = t_ricevuto_bot or time.time()  # arrivo del messaggio del tracker: riferimento dei controlli vendite

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
            listing_info["_motivo_scarto"] = motivo_skip_ante   # intero, per il messaggio di preavviso
            _log_esito(listing_info, "SKIP_PRE_SCRAPE", motivo=(motivo_skip_ante or "")[:80])
            return

        if PREAVVISO_LAMPO and stato is not None and TELEGRAM_ALERT_CHAT_ID and cover_photo_bytes:
            _preavviso_lampo(listing_info, url, cover_photo_bytes, msg_date, t_ricevuto_bot, stato)

        scraped = await scrape_vinted_listing(url)
        t_tappe.append(("scrape", time.time()))
        listing_info["t_scrape"] = time.time()   # per ricavare l'ora di caricamento dal "Caricato N secondi fa"
        listing_info.update({
            "size": scraped.get("size"), "condition": scraped.get("condition"),
            "description": scraped.get("description"), "age_days": scraped.get("age_days"),
            "catalog_id": scraped.get("catalog_id"), "cover_photo_id": scraped.get("cover_photo_id"),
            "uploaded_text": scraped.get("uploaded_text"), "stato_vendita": scraped.get("stato_vendita"),
            "created_at": scraped.get("created_at"),
            "preferiti": scraped.get("preferiti"),
            "material_raw": scraped.get("material_raw"),
            "material_per_ricerca": scraped.get("material_per_ricerca"),
            "color_raw": scraped.get("color_raw"),
            "seller_login": scraped.get("seller_login"),
            "seller_id": scraped.get("seller_id"),
            "seller_feedback_count": scraped.get("seller_feedback_count"),
            "seller_feedback_reputation": scraped.get("seller_feedback_reputation"),
            "seller_items_count": scraped.get("seller_items_count"),
            "seller_country": scraped.get("seller_country"),
        })
        # ritardo pubblicazione -> messaggio del tracker (18/10): "Caricato N secondi fa" letto allo scrape meno il tempo
        # trascorso dal messaggio; solo se la pagina lo da' in secondi (non grossolano). Va nella riga TRACCIATO (`pub_tg`).
        try:
            _, _sec_pub = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
            _letto_pub = parse_caricato_secondi(listing_info.get("uploaded_text"))
            if _sec_pub.get("pub_telegram") is not None and _letto_pub and not _letto_pub[1]:
                listing_info["pub_tg"] = round(max(_sec_pub["pub_telegram"], 0), 1)
            if _sec_pub.get("pub_telegram") is not None:
                # 10/11 (utente: 'annunci di un'ora fa'): una riga per annuncio con il ritardo pubblicazione -> messaggio del tracker
                # (anche se grossolano, "~"), per contarli in tutte le ricerche e non solo nei casi che arrivano al preavviso
                log.info("RITARDO PUBBLICAZIONE | item=%s | pub_tg=%.0f | grossolano=%s | query=%s", _estrai_item_id_da_url(url),
                         max(_sec_pub["pub_telegram"], 0), "si" if (_letto_pub and _letto_pub[1]) else "no", str(listing_info.get("query_name") or "-")[:40])
        except Exception:
            log.debug("pub_tg non calcolato", exc_info=True)

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
            listing_info["_motivo_scarto"] = motivo_skip_pre   # intero, per il messaggio di preavviso
            _log_esito(listing_info, "SKIP_PRE_GEMINI", motivo=(motivo_skip_pre or "")[:80])
            return

        # FAIR VALUE A PRIORI (vedi FAIR_VALUE_TABELLA): istantaneo, nessuna
        # chiamata esterna. La stima finisce nella scheda; il filtro vero e
        # proprio (FAIR_VALUE_FILTRA=1) scarta in silenzio prima di foto e
        # Gemini, di default invece solo si logga cosa scarterebbe.
        try:
            # un voto alla mappa catalogo->categoria (serve quando un titolo non dice che capo e')
            catalogo_impara(listing_info.get("catalog_id"), estrai_categoria_da_titolo(listing_info.get("title") or "", None))
            listing_info["fair_value"] = stima_fair_value(listing_info)
            e_skip_fv, motivo_skip_fv = check_skip_fair_value(listing_info)
        except Exception:
            log.warning("Fair value a priori non calcolato:\n%s", traceback.format_exc())
            listing_info["fair_value"] = None
            e_skip_fv, motivo_skip_fv = False, None
        fv_registra_rapida(listing_info, url, scartato=bool(e_skip_fv and FAIR_VALUE_FILTRA))
        # Una riga per OGNI annuncio (scatti o no): serve a tarare le soglie del preavviso con RICONTROLLO LAMPO.
        try:
            _fv_pre = listing_info.get("fair_value") or {}
            _prezzo_pre = _a_float(listing_info.get("price"), None)
            listing_info["preavviso"], _regola_pre = valuta_preavviso(listing_info.get("fair_value"), _prezzo_pre)
            listing_info["preavviso_suono"] = preavviso_con_suono(listing_info.get("fair_value"), _prezzo_pre)
            _item_pre = _estrai_item_id_da_url(url) if url else None
            _feat = campi_annuncio(listing_info, n_foto=len(scraped.get("photo_urls") or []))
            if _fv_pre.get("categoria"):
                _feat["categoria"] = _fv_pre["categoria"]   # include la categoria ricavata dal catalogo Vinted
            _feat["fonte_cat"] = _fv_pre.get("fonte_categoria") or "-"   # titolo | descrizione | catalogo | nessuna
            # 10/11: venditore, foto, descrizione e cuori allo scrape nella riga TRACCIATO (dataset per cercare i pattern del primo avviso)
            listing_info["feat_pre"] = {("pref_scrape" if k == "pref" else k): _feat[k]
                                        for k in ("n_foto", "desc_len", "v_rec", "v_rep", "v_art", "v_paese", "lingua", "ora_utc", "gs", "pref")
                                        if k in _feat}
            _feat.update({"prezzo": _prezzo_pre, "semaforo": _fv_pre.get("semaforo") or "-", "fv": _fv_pre.get("fv"),
                          "margine": _fv_pre.get("margine"), "conf": _fv_pre.get("conf") or "-", "regola": _regola_pre,
                          "suono": "si" if listing_info["preavviso_suono"] else "no",
                          "sem_base": _fv_pre.get("semaforo_base") or "-", "lift": _fv_pre.get("lift_velocita", "-"),
                          "brand_n": _fv_pre.get("brand") or "-"})
            log.info("PREAVVISO | item=%s | brand='%s' | prezzo=%s | semaforo=%s | fv=%s | margine=%s | conf=%s | regola=%s%s",
                     _item_pre or "n/d", listing_info.get("brand") or "n/d", _prezzo_pre,
                     _feat["semaforo"], _fv_pre.get("fv"), _fv_pre.get("margine"), _feat["conf"], _regola_pre,
                     "".join(f" | {k}={v}" for k, v in _feat.items()
                             if k not in ("prezzo", "semaforo", "fv", "margine", "conf", "regola")))
            listing_info["verifica_jev"] = bool(listing_info["preavviso"] and tratteni_per_verifica(_fv_pre, _regola_pre))
            listing_info["jev_subito"] = bool((MODA_JEV_SUBITO and _regola_pre != REGOLA_DA_VERIFICARE) or (stato or {}).get("preavviso_lampo"))   # i candidati partono solo se confermati
            if listing_info["preavviso"] and TELEGRAM_ALERT_CHAT_ID and (listing_info["jev_subito"] or not listing_info["verifica_jev"]):
                # l'invio parte appena le foto sono scaricate (album completo nel gruppo COMPRA, vedi sotto)
                listing_info["preavviso_gruppo"] = True
            if _item_pre:
                db.scrivi_evento("annuncio", _item_pre, listing_info.get("brand"),
                                 {**_feat, "titolo": listing_info.get("title")})
        except Exception:
            log.warning("Preavviso non valutato:\n%s", traceback.format_exc())
            listing_info["preavviso"] = False
        if e_skip_fv:
            if FAIR_VALUE_FILTRA:
                log.info("FILTRO FAIR VALUE ATTIVATO (silenzioso, no notifica): '%s'. Motivo: %s",
                         listing_info.get("title"), motivo_skip_fv)
                listing_info["_motivo_scarto"] = motivo_skip_fv   # intero, per il messaggio di preavviso
                _log_esito(listing_info, "SKIP_FAIR_VALUE", motivo=(motivo_skip_fv or "")[:80])
                return
            log.info("FAIR VALUE PROVA (nessuno scarto, FAIR_VALUE_FILTRA=0): avrebbe scartato '%s'. Motivo: %s",
                     listing_info.get("title"), motivo_skip_fv)

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
    if listing_info.get("preavviso_gruppo") and stato is not None and stato.get("task_preavviso") is None:
        # PREAVVISO nel gruppo COMPRA: album con tutte le foto + semaforo, in parallelo al resto; a fine analisi
        # lo stesso messaggio viene aggiornato col verdetto
        _pezzi_pre, _sec_pre = _calcola_tempi_pipeline(listing_info, msg_date, t_ricevuto_bot)
        _riga_tempi_pre = ("⏱ " + " · ".join(p.replace("telegram→notifica", "telegram→preavviso").replace("pubblicato", "caricato")
                                         for p in _pezzi_pre)
                           ) if _pezzi_pre else None
        stato["task_preavviso"] = asyncio.create_task(invia_preavviso(
            dict(listing_info), url, photo_bytes_list, riga_tempi=_riga_tempi_pre, secondi=_sec_pre))
    if stato is not None and stato.get("preavviso_lampo") and len(photo_bytes_list) > 1:
        # il lampo e' partito con la sola copertina: appena scaricate, tutte le foto nel gruppo (10/10, richiesta dell'utente)
        stato["task_album_lampo"] = asyncio.create_task(
            invia_galleria_dopo_lampo(stato, listing_info.get("title") or "Annuncio", photo_bytes_list))
    if not photo_bytes_list:
        await telegram_send_message(
            TELEGRAM_OWNER_CHAT_ID,
            f"⚠️ Niente foto per: {listing_info.get('title')}\nURL: {url or 'non trovato'}\nSalto valutazione.")
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

    # Niente Occhio ne' Cervello: l'avviso e' la regola del preavviso (stima rapida). Chi non scatta resta tracciato
    # (serie ridotta) per misurare quanti veloci si perdono.
    fv_sem = listing_info.get("fair_value") or {}
    if listing_info.get("preavviso") and listing_info.get("verifica_jev"):
        # brand nuovo (stima a priori non misurata): comparabili Vinted + Jev + foto prima di avvisare (bot/moda_jev.py)
        ris_jev = await verifica_moda_jev(listing_info, photo_bytes_list[0] if photo_bytes_list else None, photo_bytes_list)
        fv_registra_jev(listing_info, url, ris_jev)   # 6/11: la rivendita dei comparabili alimenta l'apprendimento del fair value
        await aggiorna_scheda_jev(stato, riga_esito_scheda(ris_jev))
        if ris_jev["esito"] == "scarta":
            listing_info["_motivo_scarto"] = "verifica Jev: " + ris_jev["motivo"]
            _log_esito(listing_info, "SKIP_SOLO_SEMAFORO", sem=fv_sem.get("semaforo"), motivo="jev:" + ris_jev["motivo"], azione=azione_codice(ris_jev))
            if listing_info.get("jev_subito"):   # il messaggio era gia' partito: lo stesso messaggio dice che e' stato scartato, con i passi (5/11)
                _brand_jev = (listing_info.get("fair_value") or {}).get("brand") or listing_info.get("brand")
                listing_info.update(righe_jev=righe_moda_jev(ris_jev, _brand_jev), riga_verdetto_jev=riga_verdetto_jev(ris_jev),
                                    rivendita_jev=None, parti_rivendita=None)
                if not await aggiorna_preavviso(stato, url, testo_verdetto=testo_preavviso(dict(listing_info), url)):
                    await aggiorna_preavviso(stato, url, riga_finale=riga_scarto_preavviso("verifica Jev: " + ris_jev["motivo"], msg_id_galleria))
            return
        _brand_jev = (listing_info.get("fair_value") or {}).get("brand") or listing_info.get("brand")
        listing_info["righe_jev"] = righe_moda_jev(ris_jev, _brand_jev)
        listing_info["riga_verdetto_jev"] = riga_verdetto_jev(ris_jev)
        listing_info["riga_originalita_jev"] = riga_originalita_jev(ris_jev)
        listing_info["rivendita_jev"], listing_info["parti_rivendita"] = ris_jev.get("rivendita_testata") or ris_jev.get("rivendita"), ris_jev.get("parti_rivendita")   # per l'intestazione "prezzo ➜ rivendita" (5/11)
        _log_esito(listing_info, "SOLO_SEMAFORO", sem=fv_sem.get("semaforo"), margine=fv_sem.get("margine"), azione=azione_codice(ris_jev))
        if listing_info.get("jev_subito") and await aggiorna_preavviso(stato, url, testo_verdetto=testo_preavviso(dict(listing_info), url)):
            log.info("AVVISO SOLO SEMAFORO | item=%s | prezzo=%s | sem=%s | jev=%s | aggiornato", _estrai_item_id_da_url(url),
                     listing_info.get("price"), fv_sem.get("semaforo"), ris_jev["esito"])
            return
        if not TELEGRAM_ALERT_CHAT_ID or await invia_preavviso(dict(listing_info), url, photo_bytes_list) is None:
            await telegram_send_message(TELEGRAM_ALERT_CHAT_ID or TELEGRAM_OWNER_CHAT_ID, testo_avviso_solo_semaforo(listing_info, url, msg_id_galleria))
        log.info("AVVISO SOLO SEMAFORO | item=%s | prezzo=%s | sem=%s | jev=%s", _estrai_item_id_da_url(url),
                 listing_info.get("price"), fv_sem.get("semaforo"), ris_jev["esito"])
        return
    if listing_info.get("preavviso"):
        _log_esito(listing_info, "SOLO_SEMAFORO", sem=fv_sem.get("semaforo"), margine=fv_sem.get("margine"))
        testo_sem = testo_avviso_solo_semaforo(listing_info, url, msg_id_galleria)
        if not await aggiorna_preavviso(stato, url, testo_verdetto=testo_sem):
            await telegram_send_message(TELEGRAM_ALERT_CHAT_ID or TELEGRAM_OWNER_CHAT_ID, testo_sem)
        log.info("AVVISO SOLO SEMAFORO | item=%s | prezzo=%s | sem=%s", _estrai_item_id_da_url(url),
                 listing_info.get("price"), fv_sem.get("semaforo"))
    else:
        listing_info["_motivo_scarto"] = "semaforo non promettente (solo semaforo)"
        _log_esito(listing_info, "SKIP_SOLO_SEMAFORO", sem=fv_sem.get("semaforo"))
        if serve_ombra(fv_sem):
            # Jev in ombra (6/11): il semaforo scarta, ma se la stima e' poco sicura i comparabili dicono se sottostima (es. Cult Gaia)
            async def _ombra(li=dict(listing_info), u=url, foto=list(photo_bytes_list or [])):
                ris = await verifica_moda_jev(li, None, None, solo_comparabili=True)
                fv_registra_jev(li, u, ris)
                if not (ris.get("ok_comps") and (ris.get("dispersione") or 0) <= MODA_JEV_DISPERSIONE_MAX):
                    return
                # 6/11 (utente): se i comparabili dicono che il semaforo sbagliava il rosso diventa un avviso con la verifica completa
                # (foto comparabili, legit check Jev e Gemini): solo se Jev conferma parte il messaggio.
                ris = await verifica_moda_jev(li, foto[0] if foto else None, foto)
                fv_registra_jev(li, u, ris)
                if ris["esito"] != "conferma":
                    log.info("RECUPERO JEV | item=%s | esito=%s | motivo=%s | sem_originale=%s", _estrai_item_id_da_url(u), ris["esito"], ris["motivo"], fv_sem.get("semaforo"))
                    return
                marca = (li.get("fair_value") or {}).get("brand") or li.get("brand")
                li.update(righe_jev=righe_moda_jev(ris, marca), riga_verdetto_jev=riga_verdetto_jev(ris),
                          riga_originalita_jev=riga_originalita_jev(ris), rivendita_jev=ris.get("rivendita_testata") or ris.get("rivendita"), parti_rivendita=ris.get("parti_rivendita"))
                li["riga_recupero"] = (f"♻️ Recuperato: il semaforo lo dava {fv_sem.get('semaforo')} (fair value ~{fv_sem.get('fv')} €), "
                                       f"i comparabili dicono ~{ris.get('rivendita'):.0f} €")
                # 7/11 (utente): il messaggio recuperato deve avere le foto come gli altri avvisi (album o foto con bottone), non solo testo
                if not TELEGRAM_ALERT_CHAT_ID or await invia_preavviso(dict(li), u, foto) is None:
                    await telegram_send_message(TELEGRAM_ALERT_CHAT_ID or TELEGRAM_OWNER_CHAT_ID, testo_preavviso(dict(li), u, riga_finale=""))
                log.info("RECUPERO JEV | item=%s | esito=conferma | brand=%s | prezzo=%s | rivendita=%s | sem_originale=%s | fv_stima=%s",
                         _estrai_item_id_da_url(u), marca, li.get("price"), ris.get("rivendita"), fv_sem.get("semaforo"), fv_sem.get("fv"))
            t = asyncio.create_task(_ombra())
            _TASK_OMBRA.add(t)
            t.add_done_callback(_TASK_OMBRA.discard)
