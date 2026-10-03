"""
Vinted Flip Oracle Bot (versione Telethon / userbot) -- Scenario G con fallback F
====================================================================================
Pipeline finale, basata sugli scenari di ottimizzazione dei costi e filtro.
Include: categorie multilingua estese, niente fallback "dress" pericoloso su
Vestiaire, e function calling FORZATO per il cervello Gemini (sostituisce
google_search, che su Gemini non e' forzabile in modo affidabile).
"""

import os
import re
import sys
import html
import json
import time
import uuid
import asyncio
import base64
import logging
import statistics
import difflib
import traceback
import zlib
import importlib.util
from io import BytesIO
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx
try:
    # Opzionale (2026-09-29): client con impronta TLS di un browser vero,
    # per ora usato solo dal comando /test_visuale. Se manca, il bot gira
    # uguale e il test lo segnala.
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
except Exception:
    CurlAsyncSession = None
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from PIL import Image

from bot import http_clients as hc
from bot.db import DB_FILE
from bot.gemini_stato import ripristina_stato_gemini
from bot.tracciamento import importa_tracciamento_jsonl
from bot.costanti import (
    BRAND_BLOCKLIST,
    CATEGORIA_KEYWORDS,
    CATEGORIA_TERMINE_EN,
    IMAGE_DOWNLOAD_HEADERS,
    MATERIALI_PREGIATI_PRIORITA,
    MATERIALI_TRADUZIONI,
    VENDITORI_BLOCKLIST,
    VINTED_BRAND_IDS,
    VINTED_HEADERS,
)  # noqa: F401  (re-export)

from bot.schemas import (
    CATEGORIE_CAPO_ENUM,
    CERVELLO_RESPONSE_SCHEMA,
    CERVELLO_RESPONSE_SCHEMA_OPENAI,
    OCCHIO_RESPONSE_SCHEMA,
    OCCHIO_RESPONSE_SCHEMA_GEMINI,
    _rimuovi_maxitems_da_array_di_oggetti,
    _schema_gemini_to_openai,
)  # noqa: F401  (re-export)

from bot.prompts import (
    CERVELLO_PROMPT_COMPATTO,
    GEMINI_CERVELLO_SYSTEM_PROMPT,
    GEMINI_OCCHI_SYSTEM_PROMPT,
    GEMINI_OCCHI_SYSTEM_PROMPT_JSON,
    _costruisci_prompt_occhio_json,
    _schema_scheletro,
    prompt_cervello_compatto,
)  # noqa: F401  (re-export)

from bot.logger import (
    _LOG_FORMATO,
    _SoloSottoWarning,
    _log_err,
    _log_out,
    log,
)  # noqa: F401  (re-export)

from bot.config import (
    BOT_VERSION,
    BRAND_ESCLUSI_ALERT_CHIEDI_FOTO,
    CERVELLO_PROVIDER,
    COMMISSIONE_PROTEZIONE_FISSA,
    COMMISSIONE_PROTEZIONE_PCT,
    COMP_DA_MEMORIA_AMMESSI,
    DEBUG_CONFRONTO_COMP_TELEGRAM,
    GEMINI_API_KEY,
    GEMINI_API_URL_CERVELLO,
    GEMINI_API_URL_OCCHIO,
    GEMINI_MODEL_CERVELLO,
    GEMINI_MODEL_OCCHIO,
    MAX_ANALISI_PARALLELE,
    MAX_GALLERY_PHOTOS,
    OCCHIO_OUTPUT_JSON,
    OPENAI_API_KEY,
    OPENAI_API_URL_CERVELLO,
    OPENAI_MODEL_CERVELLO,
    PREZZO_CERVELLO_INPUT,
    PREZZO_CERVELLO_OPENAI_INPUT,
    PREZZO_CERVELLO_OPENAI_OUTPUT,
    PREZZO_CERVELLO_OUTPUT,
    PREZZO_GROUNDING_PER_QUERY,
    PREZZO_OCCHIO_INPUT,
    PREZZO_OCCHIO_OUTPUT,
    QUOTA_INCASSO_NETTO,
    RAFFREDDAMENTO_SERPER_SECONDI,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USERNAME,
    SCONTO_MAX_TRATTATIVA,
    SCONTO_TIPICO_TRATTATIVA_VENDITA,
    SERPER_API_KEY,
    SOGLIA_FALLIMENTI_PER_FALLBACK_TEMPORANEO,
    SOGLIA_GIORNI_VENDITA_LAMPO,
    SOGLIA_MARGINE_ALERT_CHIEDI_FOTO,
    SOGLIA_MARGINE_ASSOLUTO_NOTIFICA,
    SOGLIA_MARGINE_COMPRA,
    SOGLIA_MARGINE_COMPRA_ALTA,
    SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE,
    SOGLIA_MARGINE_URGENZA,
    SOGLIA_PREZZO_FURTO_ISTANTANEO,
    SOGLIA_ROI_COMPRA,
    SOGLIA_ROI_COMPRA_RIDOTTA,
    SOGLIA_ROI_FURTO_ISTANTANEO,
    SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE,
    SOGLIA_ROI_URGENZA,
    SPEDIZIONE_STIMATA_EUR,
    TELEGRAM_ALERT_CHAT_ID,
    TELEGRAM_API,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_ID,
    TELEGRAM_OWNER_CHAT_ID,
    TELEGRAM_SESSION_STRING,
    TOLLERANZA_COMP_EUR,
    VINTED_ACCESS_TOKEN,
    VINTED_REFRESH_TOKEN,
    VINTED_TRACKER_NAME_HINTS,
    VISUAL_SEARCH_ATTIVA,
    _env_float,
    _serper_fallimenti_consecutivi,
    _serper_notifica_esaurimento_inviata,
    _serper_timestamp_ultimo_fallimento,
)  # noqa: F401  (re-export)

from bot.testo import (
    _RE_ALT_PRODOTTO_VINTED,
    _RE_PRODOTTO_VINTED_CON_ID,
    _escapa_markdown_legacy,
    _etichetta_piattaforma_da_url,
    _normalizza_titolo_per_dedup,
    _normalizza_titolo_per_link,
)  # noqa: F401  (re-export)

from bot.occhio import (
    ETICHETTA_VERDETTO_LEGIT,
    calcola_scarto_occhio,
    render_occhio_da_json,
    valida_payload_occhio,
)  # noqa: F401  (re-export)

from bot.verdetto import (
    CERVELLO_CAMPIONI_EXTRA,
    CERVELLO_SPREAD_MAX,
    EMOJI_DECISIONE,
    ETICHETTA_CONFIDENZA,
    ETICHETTA_FONTE_COMP,
    ETICHETTA_LEGIT,
    ETICHETTA_RISCHIO,
    PREFISSI_FONTE_POOL,
    URGENZA_RICHIEDE_COMP_REALE,
    _a_float,
    _comp_utilizzabili,
    _estrai_item_id_da_url,
    _estrai_prezzi_da_pool_ricerca,
    _etichetta_fonte_pool,
    _filtra_outlier,
    _motivo_nessun_prezzo,
    _percentile,
    _prezzi_per_fonte_da_pool,
    _riepilogo_comp_per_fonte,
    calcola_verdetto,
    classifica_provenienza_comp,
    consolida_target_cervello,
    render_messaggio_verdetto,
    valida_payload_cervello,
)  # noqa: F401  (re-export)

from bot.categorie import (
    _cerca_categoria_in_testo,
    estrai_categoria_da_titolo,
    scegli_materiale_per_ricerca,
)  # noqa: F401  (re-export)

from bot.fair_value import (
    FAIR_VALUE_APPRESO,
    FAIR_VALUE_APPRESO_FILE,
    FAIR_VALUE_BORSE,
    FAIR_VALUE_BRAND,
    FAIR_VALUE_FATTORE_CATEGORIA,
    FAIR_VALUE_FILTRA,
    FAIR_VALUE_FILTRA_ROI_MIN,
    FAIR_VALUE_LIVELLO_BRAND,
    FAIR_VALUE_LOG_FILE,
    FAIR_VALUE_MARGINE_MIN_VERDE,
    FAIR_VALUE_MOLT_CONDIZIONE,
    FAIR_VALUE_MOLT_MATERIALE,
    FAIR_VALUE_ROI_GIALLO,
    FAIR_VALUE_ROI_VERDE,
    FAIR_VALUE_SCONTO_COMP,
    FAIR_VALUE_SOTTOLINEE,
    FAIR_VALUE_TABELLA,
    _DECISIONI_POSITIVE,
    _FV_NUOVE_RIGHE_PER_RICALCOLO,
    _FV_PESO_GEMINI,
    _FV_PESO_PARTENZA,
    _FV_PESO_UMANO,
    _JSONL_CARTELLE_CREATE,
    _brand_fair_value,
    _fv_dopo_scrittura,
    _fv_leggi,
    _fv_righe_da_ricalcolo,
    _fv_scrivi,
    _jsonl_append,
    _jsonl_read,
    _mediana_pesata,
    _moltiplicatore_fair_value,
    _riga_fair_value_testo,
    _riga_fair_value_unica,
    _sottolinea_da_testo,
    check_skip_fair_value,
    fv_carica_appreso,
    fv_classifica_campione,
    fv_rapporto,
    fv_registra_gemini,
    fv_registra_rapida,
    fv_registra_umana,
    fv_ricalibra,
    fv_unisci,
    stima_fair_value,
)  # noqa: F401  (re-export)

from bot.filtri import (
    _RE_MIUMIU,
    _RE_TOP_LEGGERO,
    _miumiu_top_economico,
    check_skip_pre_gemini,
)  # noqa: F401  (re-export)

from bot.gemini_stato import (
    GEMINI_API_KEYS,
    GEMINI_CASCATA,
    GEMINI_CASCATA_CERVELLO,
    GEMINI_CASCATA_OCCHIO,
    GEMINI_MODELLI_RISERVA,
    GEMINI_MODEL_FALLBACK,
    MAX_RETRIES_GEMINI_IN_BLACKOUT,
    RAFFREDDAMENTO_GEMINI_SECONDI,
    RAFFREDDAMENTO_MODELLO_INESISTENTE_SECONDI,
    RAFFREDDAMENTO_MODELLO_SOVRACCARICO_SECONDI,
    RAFFREDDAMENTO_QUOTA_ESAURITA_GEMINI_SECONDI,
    SOGLIA_5XX_GEMINI_PER_BLACKOUT,
    _GEMINI_API_KEYS_RAW,
    _gemini_5xx_consecutivi,
    _gemini_e_errore_quota_giornaliera,
    _gemini_e_modello_inesistente,
    _gemini_e_sovraccarico_modello,
    _gemini_gestisci_modello_non_disponibile,
    _gemini_in_blackout,
    _gemini_key_attuale,
    _gemini_key_in_quota_esaurita,
    _gemini_key_index,
    _gemini_key_quota_esaurita_fino,
    _gemini_modello_da_url,
    _gemini_modello_escluso,
    _gemini_modello_escluso_fino,
    _gemini_modello_senza_quota,
    _gemini_prossima_key,
    _gemini_registra_esito,
    _gemini_secondi_retry,
    _gemini_segna_key_quota_esaurita,
    _gemini_segna_modello_non_disponibile,
    _gemini_timestamp_ultimo_5xx,
    _gemini_url_effettivo,
)  # noqa: F401  (re-export)

from bot.proxy import (
    INTERVALLO_RIEPILOGO_BANDA,
    INTERVALLO_RIEPILOGO_PROXY,
    PROXY_LIST,
    PROXY_QUARANTENA_SECONDI,
    PROXY_QUARANTENA_SOGLIA,
    _BANDA_PER_TIPO,
    _BANDA_REGISTRAZIONI,
    _CLIENT_VINTED_POOL,
    _CLIENT_VINTED_POOL_KEYS,
    _ETICHETTA_PER_CHIAVE_PROXY,
    _PROXY_BLOCCHI_DI_FILA,
    _PROXY_ESCLUSI,
    _PROXY_LIST_RAW,
    _PROXY_QUARANTENA_FINO,
    _PROXY_STATS,
    _PROXY_STATS_RICHIESTE_TOTALI,
    _etichetta_proxy,
    _host_porta_proxy,
    _logga_riepilogo_banda,
    _logga_riepilogo_proxy,
    _proxy_in_quarantena,
    _proxy_indice_rotazione,
    _registra_banda,
    _registra_blocco_proxy,
    _registra_esito_proxy,
    _tipo_richiesta_vinted,
)  # noqa: F401  (re-export)

from bot.http_clients import (
    _crea_client_vinted,
    _prossimo_client_vinted,
    _prossimo_indice_vinted,
    chiudi_client_http,
    inizializza_client_http,
)  # noqa: F401  (re-export)

from bot.telegram_api import (
    TELEGRAM_MAX_ATTESA_429_SECONDI,
    TELEGRAM_MAX_TENTATIVI,
    _parametri_reply,
    _primo_message_id,
    _spezza_per_telegram,
    _telegram_esito_ok,
    _telegram_post,
    telegram_edit_message,
    telegram_send_media_group,
    telegram_send_message,
    telegram_send_photo,
    telegram_send_with_buttons,
)  # noqa: F401  (re-export)

from bot.parsing import (
    BRAND_REGEX,
    BRAND_VALORI_VUOTI,
    PRICE_REGEX,
    TITOLO_NON_RILEVATO,
    URL_REGEX,
    _brand_da_titolo,
    extract_url_from_text,
    parse_vinted_tracker_message,
)  # noqa: F401  (re-export)

from bot.tempi import (
    _calcola_tempi_pipeline,
    _formatta_durata,
    _formatta_tappe_pipeline,
    _parse_created_at_dt,
)  # noqa: F401  (re-export)

from bot.vinted_http import (
    PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI,
    TOKEN_FILE,
    VINTED_COOKIES_EXTRA,
    _VINTED_COOKIES,
    _attendi_turno_vinted,
    _jwt_scaduto,
    _lock_rate_limit_vinted,
    _parse_cookie_header,
    _rinnova_token_vinted,
    _vinted_get_con_retry,
    _vinted_rate_limit_locks,
    _vinted_refresh_lock,
    _vinted_timestamp_ultima_richiesta_per_chiave,
)  # noqa: F401  (re-export)

from bot.tracciamento import (
    SKIP_GIA_VENDUTI,
    TRACCIAMENTO_ATTIVO,
    TRACCIAMENTO_FILE,
    TRACCIAMENTO_SERIE_SECONDI,
    _CAND_TS_RE,
    _TRACC_AVAILABILITY_RE,
    _TRACC_BARRA_RE,
    _TRACC_FASCE,
    _TRACC_PREZZO_RES,
    _TRACC_SEGNALI_RE,
    _log_esito,
    _tracc_bucket,
    _tracc_classe,
    _tracc_esiti,
    _tracc_estrai_segnali,
    _tracc_item_visti,
    _tracc_leggi_pagina,
    _tracc_scrivi,
    _tracc_sem,
    _tracc_serie,
    _tracc_stato,
    _tracc_stop,
    tracc_avvia_serie,
    tracc_registra_gia_venduto,
    tracc_registra_valutato,
    trova_timestamp_candidati,
)  # noqa: F401  (re-export)

from bot.vinted_scrape import (
    BROTLI_DISPONIBILE,
    SONDA_BANDA_CAMPIONI,
    _CHIAVI_ATTRIBUTI,
    _DIAGNOSTICA_ATTRIBUTI_RESTANTI,
    _ETICHETTE_ATTRIBUTI,
    _REGEX_FOTO_F800,
    _RE_ATTRIBUTO_ANNUNCIO,
    _SONDA_CAMPI,
    _SONDA_PAROLE_CHIAVE_CAMPI,
    _decodifica_stringa_json,
    _diagnostica_attributi_mancanti,
    _estrai_attributi_annuncio,
    _estrai_foto_gallery,
    _formati_foto_nella_pagina,
    _scrapa_guardaroba_venditore,
    _sonda_analizza_offset,
    _sonda_avvia_se_serve,
    _sonda_campioni_fatti,
    _sonda_composizione,
    _sonda_contesto_campi_mancanti,
    _sonda_e_pagina_vera,
    _sonda_stima_lettura_parziale,
    _sonda_struttura_pagina,
    _sonda_task_attivi,
    _testi_visibili,
    scrape_vinted_listing,
)  # noqa: F401  (re-export)

from bot.foto import (
    FOTO_DIRETTE_ABILITATE,
    FOTO_DIRETTE_PAUSA_SECONDI,
    FOTO_DIRETTE_SOGLIA_FALLIMENTI,
    _costruisci_parts_foto_sync,
    _download_foto_diretta,
    _foto_dirette_attive,
    _foto_dirette_registra,
    _foto_dirette_stato,
    costruisci_parts_foto,
    download_image_bytes,
    optimize_image_bytes,
)  # noqa: F401  (re-export)

from bot.serper_base import (
    SIMBOLI_VALUTA_COMPARABILI,
    SIMBOLI_VALUTA_NON_COMPARABILI,
    SNIPPET_PLACEHOLDER_INUTILI,
    _e_errore_crediti_serper,
    _riga_serper_e_rumore,
    cerca_serper_mirata,
    valuta_qualita_comp,
)  # noqa: F401  (re-export)

from bot.gemini_api import (
    CERVELLO_FUNCTION_DECLARATION,
    ISTRUZIONE_FASE_JSON,
    MAX_ROUNDS_FUNZIONE,
    _estrai_testo_da_parts,
    chiama_gemini,
    chiama_gemini_cervello_forzato,
    costo_gemini_token,
)  # noqa: F401  (re-export)

from bot.openai_api import (
    OPENAI_CERVELLO_TOOL,
    OPENAI_RESPONSE_FORMAT_CERVELLO,
    _chiama_openai_raw,
    chiama_openai_cervello_forzato,
    costo_openai_token,
)  # noqa: F401  (re-export)

from bot.vinted_search import (
    _estrai_articoli_vinted,
    _risolvi_search_by_image_id,
    _risolvi_search_by_image_id_via_serper,
    build_vinted_search_url,
    build_vinted_visual_search_url,
)  # noqa: F401  (re-export)

from bot.serper_fonti import (
    TASSO_USD_EUR,
    _cerca_ebay_sold_via_resellbot,
    _query_resellbot_raw,
    _serper_batch_query_ebay_sold,
    _serper_batch_query_vestiaire,
    _serper_scrape_page_diretto,
)  # noqa: F401  (re-export)

from bot.comps_filtri import (
    BRAND_SOTTOLINEE_DA_ESCLUDERE,
    ESCLUSIONI_FALSI_POSITIVI_CATEGORIA,
    LINEA_O_ERA_NON_UTILI_PER_RICERCA,
    RUMORE_GENERICO_COMP,
    _arricchisci_brand_per_ricerca,
    _e_linea_o_era_utile_per_ricerca,
    _estrai_articoli_da_alt_vinted,
    _estrai_mappa_url_comp_vinted,
    _filtra_comp_per_brand_sottolinee,
    _filtra_comp_per_categoria,
    _rimuovi_comp_autoreferenziale,
)  # noqa: F401  (re-export)

from bot.comps import (
    CODICI_REDDIT_CACHE_FILE,
    MARKER_NESSUN_ARTICOLO_VINTED,
    REDDIT_ABILITATO,
    REDDIT_USER_AGENT,
    SOLD_CACHE_FRESCA_SECONDI,
    SOLD_CACHE_MAX_VOCI,
    SOLD_CACHE_STALE_SECONDI,
    TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI,
    TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI,
    _BRAND_NOTI_PER_INCROCIO_REDDIT,
    _cerca_ebay_sold_con_fallback,
    _cerca_vinted_testo_diretto_con_fallback_serper,
    _codici_reddit_cache,
    _estrai_codici_prodotto_da_occhio,
    _recupera_comp_visuali_vinted,
    _reddit_ottieni_token,
    _reddit_token_cache,
    _reddit_verifica_codice,
    _salva_cache_codici_reddit,
    _scrape_catalogo_vinted_diretto,
    _sold_cache,
    _sold_cache_chiave,
    _sold_cache_leggi,
    _sold_cache_scrivi,
    _titoli_menzionano_altro_brand_reddit,
    _titoli_menzionano_categoria_diversa_reddit,
    search_comps_completo,
    verifica_codici_prodotto_reddit,
)  # noqa: F401  (re-export)

from bot.skip_report import (
    _estrai_margine_e_roi_da_blocco,
    build_skip_report,
    check_skip_pre_cervello,
    estrai_margine_preliminare,
)  # noqa: F401  (re-export)

from bot.panel import (
    EXTRA_LLM_KEY,
    EXTRA_LLM_MODEL,
    EXTRA_LLM_URL,
    PANEL_CERVELLO_MODELLI,
    PANEL_MAX_ANNUNCI_ORA,
    PANEL_MAX_FOTO,
    PANEL_MODELLI_PER_ANNUNCIO,
    PANEL_OCCHIO_MODELLI,
    PANEL_PAUSA_QUOTA_MIN,
    PANEL_TIMEOUT,
    _bg_task,
    _campi_occhio_panel,
    _fmt0,
    _panel_ammesso,
    _panel_cervello_modello,
    _panel_chiama,
    _panel_e_modello_principale,
    _panel_giro,
    _panel_ingressi,
    _panel_occhio_modello,
    _panel_pausa,
    _panel_segna_errore,
    _panel_sem,
    _riga_panel,
    _task_bg,
    estrai_json_da_testo_llm,
    estrai_target_da_testo_llm,
    panel_cervello,
    panel_occhio,
    panel_scegli_modelli,
)  # noqa: F401  (re-export)

from bot.scheda import (
    ANALISI_GEMINI_ATTIVA,
    GALLERIA_ANTICIPATA,
    LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA,
    STATO_ANALISI_COMPLETATA,
    STATO_ANALISI_COMPLETATA_UNIFICATA,
    STATO_ANALISI_INTERROTTA,
    _PermessoAnalisi,
    _aggiorna_stato_scheda,
    _descrizione_utile,
    _didascalia_galleria_anticipata,
    _eta_annuncio_testo,
    _invia_galleria_anticipata,
    _invia_risultato_telegram,
    _riga_caricato_annuncio,
    _riga_venditore_annuncio,
    _righe_dettagli_annuncio,
    _scheda_annuncio_testo,
    _stato_analisi_testo,
    _testa_prezzo_brand,
    componi_testi_verdetto,
)  # noqa: F401  (re-export)

from bot.pipeline import (
    _campione_target_cervello,
    _process_listing_interno,
    process_listing,
)  # noqa: F401  (re-export)

# MIGRAZIONE AD ASYNCIO (2026-09-19)
# ----------------------------------
# Telethon e' un framework interamente asincrono: ogni chiamata di rete
# sincrona (requests) e ogni pausa bloccante (time.sleep) eseguite nel suo
# loop fermano TUTTO il bot, compresa la ricezione di nuovi messaggi dal
# tracker. Nella versione precedente process_listing girava dentro
# asyncio.to_thread, il che evitava il blocco del loop ma serializzava di
# fatto la pipeline su un solo thread per annuncio, con decine di secondi
# di attesa passiva (scraping Vinted, Serper, Gemini) durante i quali non
# si poteva iniziare a lavorare l'annuncio successivo.
#
# Ora tutta la rete passa da httpx.AsyncClient e tutte le pause da
# asyncio.sleep, quindi piu' annunci vengono elaborati davvero in
# parallelo e le attese di rete non costano nulla. Il rate-limit verso
# Vinted resta una difesa voluta contro il 403 (vedi _attendi_turno_vinted
# piu' sotto), ma dal 2026-09-21 e' pacata PER PROXY invece che con un
# unico lock globale: con un lock globale, annunci multipli in lavorazione
# contemporanea (proprio il caso normale in un momento di traffico intenso,
# quello in cui perdere tempo costa un affare gia' comprato da qualcun
# altro) si mettevano in coda TUTTI insieme su un'unica pausa minima
# condivisa, anche usando 53 proxy diversi che a quel punto non
# accodavano il traffico, lo attendevano soltanto. La stessa pausa minima
# per singolo IP resta identica (nessuna riduzione della protezione
# anti-403 per-proxy), cambia solo che IP diversi non si aspettano piu'
# a vicenda.
#
# NOTA httpx >= 0.28: il vecchio parametro "proxies" (plurale, dict) e'
# stato rimosso. La rotazione proxy e' quindi implementata con un client
# per proxy, costruiti una volta sola all'avvio (vedi _CLIENT_VINTED_POOL).

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------


# RETI_SICUREZZA_ATTIVE: RITIRATO il 2026-09-19 con il passaggio al
# cervello a output JSON strutturato. Non ha piu' nulla da attivare o
# disattivare: le sei reti di sicurezza che governava
# (verifica_ancoraggio_prezzo_comp, verifica_comp_citati_sono_reali,
# forza_soglia_minima_compra, converti_tratta_senza_obiettivo_valido,
# declassa_urgenza_se_borderline, applica_soglia_trattativa_40_percento)
# esistevano per correggere a posteriori, via regex sul testo, numeri e
# decisioni che il modello scriveva in prosa. Ora quei numeri il modello
# non li scrive affatto: li calcola calcola_verdetto() in Python dai dati
# strutturati, quindi non esiste piu' l'errore da correggere. La domanda
# diagnostica che questo flag doveva risolvere (perche' le reti
# intervenivano sul 94% degli item con CERVELLO_PROVIDER=openai contro lo
# 0% con Gemini) resta senza risposta ed e' diventata priva di oggetto: le
# reti intervenivano sul FORMATO del testo, e quel formato non c'e' piu'.
# La variabile d'ambiente puo' restare impostata su Railway senza alcun
# effetto; questo blocco di commento e' l'unica traccia che ne resta.
#
# Vecchia documentazione del flag, conservata per contesto storico:
# RETI_SICUREZZA_ATTIVE: interruttore diagnostico temporaneo. Log di
# produzione del 18-19/09/2026 hanno mostrato che con CERVELLO_PROVIDER=openai
# le reti di sicurezza post-processing (verifica_ancoraggio_prezzo_comp,
# verifica_comp_citati_sono_reali, forza_soglia_minima_compra,
# converti_tratta_senza_obiettivo_valido, declassa_urgenza_se_borderline,
# applica_soglia_trattativa_40_percento) intervengono su ~94% degli item
# (61/65), contro 0/43 con Gemini nello stesso periodo -- troppo alto per
# essere solo "casi limite corretti", serve vedere l'output NUDO del
# cervello per capire se il problema e' nel prompt o nel provider stesso.
# A False, process_listing salta tutte le correzioni automatiche e manda
# il verdetto cosi' come lo scrive il cervello -- SOLO per diagnosi
# mirata, mai lasciare a False in modo permanente (nessuna rete a
# protezione di falsi COMPRA basati su comp inventati).
# (nessuna lettura della env var: il flag non governa piu' nulla)


                                          # trattativa su Vinted prima di comprare: usato
                                          # SOLO per calcolare "prezzo da listare" (di
                                          # quanto listare sopra alla vendita attesa per
                                          # avere margine di trattativa), NON per la
                                          # decisione COMPRA/TRATTA che resta invariata


# richiesta esplicita dell'utente -- il blocco incondizionato del 2026-09-22 ("mai COMPRA a
# prezzo pieno, qualunque sia il brand") si e' rivelato troppo rigido su un caso reale (Rick
# Owens taglia estrema, margine €157.90/ROI 714% declassato comunque a TRATTA): "le taglie
# hanno impatto sui gg di turnover e magari un pochino sul prezzo di vendita ma non devono
# impattare in questa forma cosi' rigida l'esito". Ora la taglia estrema declassa COMPRA a
# TRATTA solo se l'affare NON supera anche questa soglia alternativa (margine E roi, non solo
# uno dei due) -- un margine/ROI davvero fuori scala vale comunque il rischio di liquidita'
# sulla taglia. Sotto questa soglia resta il declassamento automatico di prima.


                                         # invece del default 4 -- si fallisce prima e si passa
                                         # al fallback (prosa/verdetto senza extra) invece di
                                         # aspettare minuti su una chiamata che quasi certamente
                                         # fallira' comunque


# ESCLUSIONI VOLUTE (non mappare per evitare falsi positivi o capi di scarso valore):
# - Maje, John Smedley, Alberta Ferretti, Romeo Gigli, Gianfranco Ferre: rimossi il 2026-10-01
#   dopo aver analizzato i verdetti reali (~7h di log): zero annunci sopra i 50 EUR di margine
#   (Maje 0/22, margine medio ~ -1 EUR). Non sono un errore: dati alla mano non rendono.
# - Sandro: rimosso il 2026-10-01 su indicazione dell'utente (il bot ne sovrastimava il prezzo di
#   rivendita). Tolto anche dalla query 2 di Vinted-Notifications.
# - Ganni, Arc'teryx: rimossi il 2026-10-02 su approvazione dell'utente dopo il primo giorno di log
#   ESITO (Ganni 7 NON COMPRARE su 8, venditori a 85-120 EUR per capi da 55-90; Arc'teryx
#   margini intorno a zero, 1 TRATTA su 5). Tolti anche dalle query 2 e 4 di Vinted-Notifications.
# - Jil Sander, Our Legacy, Drumohr: rimossi il 2026-10-03 su approvazione dell'utente (primo giorno
#   completo di log ESITO: 0 annunci su 29 con margine >=50 EUR e ROI >=100%). Tolti anche dalle query
#   di Vinted-Notifications.
# - "céline"/"celine": l'utente segnala troppo rumore su Vinted -- molti annunci di altri
#   brand vengono taggati per errore come Céline dai venditori, quindi la ricerca comp per
#   brand_id risulterebbe inquinata. Scelta esplicita di non mapparlo, non una dimenticanza.
# - "saint laurent" (post-2012, id 83122): altissimo rischio fake, preferiamo concentrarci su YSL vintage.
# - "McQ" (id 849677): diffusion line di Alexander McQueen, valore di mercato molto inferiore.
# - "See by Chloé" (id 1472883): diffusion line di Chloé, satura e con basso ROI.


# ---------------------------------------------------------------------------
# FILTRO PRE-GEMINI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PROMPT DI SISTEMA
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OCCHIO: SCHEMA JSON STRUTTURATO (attivo solo con OCCHIO_OUTPUT_JSON=true)
# ---------------------------------------------------------------------------
# Stesso impianto del Cervello, applicato un passo piu' a monte: il modello
# OSSERVA e Python DECIDE.
#
# L'Occhio in prosa produce anche un verdetto finanziario completo (margine,
# ROI, decisione, urgenza, deal score) che il codice ri-estrae con regex in
# estrai_margine_preliminare per decidere se saltare il Cervello. E' la
# stessa classe di errore rimossa dal Cervello il 2026-09-19, sopravvissuta
# nel primo stadio: un annuncio buono puo' morire per un margine allucinato
# prima ancora di essere valutato con comp reali.
#
# In questo schema l'Occhio non produce NESSUN numero economico, e nemmeno
# il flag di scarto: uno scarto e' una decisione, e si calcola in
# calcola_scarto_occhio() dai campi osservativi. La versione calcolata e'
# anche piu' severa di quella dichiarabile a parole, perche' puo' pretendere
# che la controprova anti-bias sia stata eseguita prima di accettare un
# "falso conclamato" (caso reale: Dries Van Noten autentico a EUR 5,95
# scartato come falso con dettagli costruiti a posteriori).
#
# L'ordine dei campi e' una catena di ragionamento forzata: evidenza ->
# trascrizione verbatim -> identificazione -> osservazione fisica ->
# riscontri -> controprova -> verdetto. Il verdetto puo' essere scritto solo
# dopo che i riscontri concreti sono gia' stati messi per iscritto.
#
# maxItems su ogni array. ATTENZIONE (scoperto il 2026-09-20, in produzione):
# su responseJsonSchema Gemini applica un "complexity budget" interno non
# documentato, e maxItems su un array di OGGETTI (etichette, difetti,
# riscontri_autenticita) lo consuma molto piu' di maxItems su un array di
# stringhe. Superato il budget la risposta e' un 400 INVALID_ARGUMENT generico
# ("Request contains an invalid argument"), senza indicare quale campo.
# Lo schema qui sotto resta la fonte di verita' completa (usata per i test e
# per il troncamento locale in valida_payload_occhio); quello REALMENTE
# spedito a Gemini e' OCCHIO_RESPONSE_SCHEMA_GEMINI, derivato piu' sotto
# togliendo maxItems solo dagli array di oggetti.


# ==========================================================================
# SCARTO PRE-CERVELLO: calcolato, non dichiarato dal modello.
# Sostituisce check_skip_pre_cervello (~10 substring match su prosa, con due
# bug reali trovati in produzione il 2026-09-19: "Confidenza: Alta" con i due
# punti non matchava mai, e le varianti "falso palese"/"falso evidente" non
# erano previste).
# ==========================================================================


# ---------------------------------------------------------------------------
# TELEGRAM BOT API HELPERS
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PARSING MESSAGGI E SCRAPING VINTED
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GEMINI E TOOLKIT IA
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CERVELLO GEMINI CON FUNCTION CALLING FORZATO
# ---------------------------------------------------------------------------
# Il tool builtin "google_search" di Gemini NON e' forzabile in modo affidabile
# (il modello spesso decide di non chiamarlo mai, anche se il prompt lo chiede
# esplicitamente). Sostituiamo con una function custom che richiama Serper --
# stesso servizio gia' usato per i comp pre-raccolti -- e la forziamo con
# tool_config.function_calling_config.mode = "ANY", che per il function calling
# "vero" (non il retrieval builtin) e' effettivamente vincolante.


# ---------------------------------------------------------------------------
# SCHEMA DI OUTPUT STRUTTURATO DEL CERVELLO (structured output / JSON mode)
# ---------------------------------------------------------------------------
# Sostituisce il verdetto in prosa e tutte le regex che ne estraevano i
# numeri. L'ordine di propertyOrdering NON e' cosmetico: Gemini genera i
# campi in quell'ordine, quindi e' letteralmente la catena di ragionamento
# imposta al modello -- prima si impegna per iscritto su brand e linea,
# poi elenca i comp, e solo alla fine produce il prezzo target. Non puo'
# sparare un numero prima di aver dichiarato su quale linea lo sta
# calcolando.
#
# VINCOLO API (documentato, non aggirabile): Gemini rifiuta una richiesta
# che contenga insieme function_declarations e responseMimeType
# "application/json" con l'errore "Function calling with a response mime
# type: 'application/json' is unsupported". Per questo la chiamata al
# cervello e' divisa in due fasi: i giri di ricerca usano i tools come
# prima, il giro finale toglie i tools dal payload e accende lo schema.
# Vedi chiama_gemini_cervello_forzato.
#
# Nota sui vincoli numerici: responseSchema accetta solo un sottoinsieme di
# OpenAPI, quindi qui non si usano pattern/minimum/maximum -- i limiti
# (sconto 20-30%, deal 1-10, tetti di prezzo) sono applicati in Python da
# valida_payload_cervello/calcola_verdetto, che e' comunque dove devono
# stare: un vincolo dichiarato nello schema verrebbe rispettato "quasi
# sempre", uno applicato in codice sempre.


                         # mostravano che ~1 item su 2 finiva comunque nel
                         # fallback forzato, che nel caso peggiore costa
                         # quanto il vecchio "2 giri" (3 chiamate totali) ma
                         # senza dare al modello la seconda ricerca reale che
                         # chiedeva. Con 2 il caso "un giro basta" costa
                         # uguale a prima, il caso "serve una seconda ricerca"
                         # costa quanto il vecchio fallback ma con una
                         # ricerca vera al posto del rifiuto secco.


# ---------------------------------------------------------------------------
# CERVELLO OPENAI CON FUNCTION CALLING (equivalente GPT-4o-mini)
# ---------------------------------------------------------------------------
# Stessa logica del cervello Gemini sopra (multi-round di ricerca via
# cerca_serper_mirata, poi verdetto testuale finale), ma nel formato Chat
# Completions di OpenAI. Molto piu' semplice del gemello Gemini perche'
# "tool_choice": "required" e' vincolante in modo affidabile in OpenAI -- non
# servono i workaround osservati con Gemini (mode "NONE" dichiarato sempre,
# fallback senza tools, diagnostica su testo vuoto): qui un tool_choice
# esplicito basta, e un messaggio senza tool_calls e' sempre una risposta
# testuale vera. Stessa firma di ritorno (testo, costo_totale, n_query_extra)
# della funzione Gemini, per restare intercambiabile nel punto di chiamata.


# ---------------------------------------------------------------------------
# SERPER RICERCA
# ---------------------------------------------------------------------------


# search_comps_ebay_sold_url (URL diretto www.ebay.it/sch/i.html?...&LH_Sold=1)
# RIMOSSA il 2026-09-19: costruiva l'URL per lo scrape diretto della pagina
# eBay, abbandonato dopo conferma che eBay blocca sistematicamente Serper su
# quell'endpoint con la pagina anti-bot "Misura di sicurezza" (vedi
# _serper_batch_query_ebay_sold, che l'ha sostituita passando da una query
# Google invece dello scrape diretto).


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO e VALIDAZIONE POST-GENERAZIONE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RETI DI SICUREZZA REGEX -- RIMOSSE il 2026-09-19
# ---------------------------------------------------------------------------
# Con il cervello a output JSON strutturato queste funzioni non hanno piu'
# un oggetto su cui lavorare, quindi sono state eliminate invece di essere
# lasciate nel file come codice morto (un file lungo pieno di funzioni che
# non vengono mai chiamate e' un costo di lettura permanente, e prima o poi
# qualcuno le riattiva senza accorgersi che parsano un formato che non
# esiste piu'). Elenco di cosa e' sparito e di cosa lo sostituisce:
#
#   _normalizza_emoji_decisione        -> le emoji le scrive render_messaggio_
#                                         verdetto da un dizionario, il modello
#                                         non le produce piu'
#   normalizza_urgenza_wording         -> l'urgenza e' un valore calcolato,
#                                         non una parola da normalizzare
#   forza_soglia_minima_compra         -> calcola_verdetto applica le soglie
#                                         PRIMA di scrivere la decisione
#   declassa_urgenza_se_borderline     -> idem, l'urgenza nasce gia' corretta
#   applica_soglia_trattativa_40_percento -> l'offerta la calcola il codice,
#                                         il modello non la propone piu'
#   converti_tratta_senza_obiettivo_valido -> TRATTA esiste solo se
#                                         l'obiettivo regge, per costruzione
#   valida_contraddizioni_report       -> non esistono piu' contraddizioni
#                                         possibili tra testo e numeri
#   estrai_decisione_da_testo          -> la decisione e' un campo, non si
#                                         estrae da nessuna parte
#   _e_urgenza_alta                    -> verdetto["urgenza"] == "Alta"
#   verifica_falso_ha_motivazione      -> legit_motivo_specifico e' un campo
#                                         obbligatorio dello schema, e la
#                                         lunghezza minima e' controllata in
#                                         valida_payload_cervello
#   verifica_ancoraggio_prezzo_comp    -> diventata un min() in calcola_verdetto
#   verifica_comp_citati_sono_reali    -> diventata una differenza tra insiemi
#                                         in classifica_provenienza_comp
#
# Restano invece _estrai_prezzi_da_pool_ricerca, _prezzi_per_fonte_da_pool,
# _motivo_nessun_prezzo e _riepilogo_comp_per_fonte: servono ancora, sia per
# il blocco debug Telegram sia per il confronto tra i comp dichiarati dal
# cervello e quelli realmente presenti nel pool.
#
# Restano anche _estrai_margine_e_roi_da_blocco e estrai_margine_preliminare:
# NON riguardano il cervello ma l'OCCHIO, che continua a produrre prosa e la
# cui stima preliminare alimenta ancora check_skip_pre_cervello.


# ---------------------------------------------------------------------------
# MOTORE DI VERDETTO DETERMINISTICO
# ---------------------------------------------------------------------------
# Tutto cio' che prima era "il modello scrive un numero, una rete di
# sicurezza controlla via regex se il numero e' plausibile" vive qui, come
# aritmetica su dati strutturati. Il cervello fornisce i DATI della
# valutazione (linea, comp, prezzo target), queste funzioni producono il
# VERDETTO (margine, ROI, decisione, urgenza, offerta di trattativa).
#
# Conseguenza pratica: le violazioni che le vecchie reti inseguivano non
# sono piu' "corrette a posteriori", sono impossibili. Un COMPRA sotto
# soglia non puo' esistere perche' la decisione E' la soglia; un'offerta di
# trattativa oltre il 40% non puo' esistere perche' l'offerta E' il 40%.


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_recent_listings_seen = {}

DEDUP_CONTENUTO_WINDOW_SECONDS = 300

_semaforo_analisi = asyncio.Semaphore(MAX_ANALISI_PARALLELE)


def _chiavi_dedup(parsed, url=None):
    """Chiavi con cui un annuncio viene riconosciuto come gia' visto. Pura,
    testabile senza rete.

    FIX 2026-09-27: prima la chiave era SOLO (titolo normalizzato, brand,
    prezzo). Quando il messaggio del tracker non si parsava, tutti gli
    annunci diventavano ("titolo non", "", "") -- "Titolo non rilevato" meno
    l'ultima parola, brand e prezzo vuoti -- e per 5 minuti solo il PRIMO
    veniva elaborato, gli altri scartati come "varianti". Ora:
    - l'item id Vinted (dall'URL) e' sempre una chiave: lo stesso annuncio
      ricevuto due volte e' un doppione certo;
    - la chiave per contenuto (che serve a riconoscere le varianti dello
      stesso capo ripubblicate con id diversi) si usa solo se il parsing
      ha trovato un titolo vero E almeno brand o prezzo -- altrimenti
      annunci diversi collasserebbero sulla stessa chiave vuota."""
    chiavi = []
    item_id = _estrai_item_id_da_url(url)
    if item_id:
        chiavi.append(("item_id", item_id))
    titolo = parsed.get("title")
    brand = (parsed.get("brand") or "").strip().lower()
    prezzo = (parsed.get("price") or "").strip()
    if titolo and titolo != TITOLO_NON_RILEVATO and (brand or prezzo):
        chiavi.append(("contenuto", _normalizza_titolo_per_dedup(titolo), brand, prezzo))
    return chiavi


def e_variante_recente(parsed, url=None):
    chiavi = _chiavi_dedup(parsed, url)
    now = time.time()
    scadute = [k for k, ts in _recent_listings_seen.items() if now - ts > DEDUP_CONTENUTO_WINDOW_SECONDS]
    for k in scadute:
        del _recent_listings_seen[k]
    if any(k in _recent_listings_seen for k in chiavi):
        return True
    for k in chiavi:
        _recent_listings_seen[k] = now
    return False


# ---------------------------------------------------------------------------
# TEST PROXY A COMANDO (aggiunto 2026-09-27, utente: "come testo i miei
# proxy?"). Una richiesta REALE a Vinted per OGNUNO dei proxy del pool,
# riusando lo stesso parsing gia' in produzione per i comp catalogo
# (_estrai_articoli_da_alt_vinted / MARKER_NESSUN_ARTICOLO_VINTED): un proxy
# e' "ok" solo se estrae davvero articoli, non solo se risponde 200 -- e'
# proprio la distinzione (200 ma pagina di blocco) che ha reso il problema
# del 27/9 difficile da diagnosticare da un singolo status HTTP.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# TEST RICERCA VISUALE A COMANDO (2026-09-29)
# ---------------------------------------------------------------------------
# /test_visuale <link annuncio>: prova la ricerca visuale Vinted ("Cerca
# articoli simili") con il client attuale (httpx) e con curl_cffi (impronta
# TLS di Safari iOS e di Chrome), con gli stessi cookie dell'account
# dedicato e lo stesso proxy. Serve a capire se il 403 Datadome su
# /search_by_image (diagnosi del 2026-09-20, vedi
# _risolvi_search_by_image_id_via_serper) dipende dall'impronta di httpx,
# prima di cambiare qualunque cosa nella pipeline. Nessuna chiamata Gemini.

VARIANTI_CURL_TEST_VISUALE = (("curl_cffi Safari iOS", "safari184_ios"), ("curl_cffi Chrome", "chrome146"))


def _jwt_scadenza(token):
    """datetime UTC di scadenza di un JWT Vinted, o None se illeggibile."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload_b64)).get("exp")
        return datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    except Exception:
        return None


def _descrivi_token(nome, token):
    if not token:
        return f"{nome}: assente"
    scad = _jwt_scadenza(token)
    if scad is None:
        return f"{nome}: presente ma illeggibile"
    ore = (scad - datetime.now(timezone.utc)).total_seconds() / 3600
    quando = scad.strftime("%d/%m %H:%M UTC")
    if ore <= 0:
        return f"{nome}: SCADUTO il {quando}"
    return f"{nome}: valido fino al {quando} (tra {ore:.0f}h)" if ore < 72 else \
        f"{nome}: valido fino al {quando} (tra {ore / 24:.0f} giorni)"


def _classifica_esito_visuale(status, url_finale, testo=""):
    """Da status + URL finale dopo i redirect a un esito leggibile e
    all'eventuale search_by_image_id."""
    url_finale = url_finale or ""
    m = re.search(r"search_by_image_id=([A-Za-z0-9_]+)", url_finale)
    if m:
        return "OK", m.group(1)
    if "/member/register" in url_finale or "/member/login" in url_finale or "/session-refresh" in url_finale:
        return "rimandato al login (sessione non accettata)", None
    if status == 403:
        return "403 bloccato (Datadome)", None
    if status and status >= 400:
        return f"HTTP {status}", None
    return f"HTTP {status}, nessun search_by_image_id nell'URL finale ({url_finale[:120]})", None


def _conta_articoli_catalogo(html_catalogo):
    """Articoli reali nella pagina catalogo, con la stessa regex della
    ricerca comp testuale."""
    return len(_RE_ALT_PRODOTTO_VINTED.findall(html_catalogo or ""))


async def _prova_visuale_httpx(url_intermedio, headers, cookies):
    t0 = time.time()
    try:
        resp = await hc._CLIENT_VINTED_AUTH.get(url_intermedio, headers=headers, cookies=cookies, timeout=20)
        esito, sbi = _classifica_esito_visuale(resp.status_code, str(resp.url))
        return {"esito": esito, "id": sbi, "durata": time.time() - t0, "articoli": None}
    except Exception as e:
        return {"esito": f"errore {type(e).__name__}: {e}", "id": None, "durata": time.time() - t0, "articoli": None}


async def _prova_visuale_curl(impersonate, url_intermedio, headers, cookies, proxy):
    t0 = time.time()
    # Niente User-Agent/Accept nostri: li imposta curl_cffi coerenti con
    # l'impronta scelta (un UA iPhone sopra un'impronta Chrome sarebbe di
    # nuovo un'incoerenza).
    headers_curl = {k: v for k, v in headers.items() if k.lower() not in ("user-agent", "accept")}
    try:
        async with CurlAsyncSession(impersonate=impersonate, proxy=proxy, timeout=20) as sess:
            resp = await sess.get(url_intermedio, headers=headers_curl, cookies=cookies, allow_redirects=True)
            esito, sbi = _classifica_esito_visuale(resp.status_code, str(resp.url))
            articoli = None
            if sbi:
                # Controprova: la pagina risultati deve contenere articoli veri.
                resp_cat = await sess.get(
                    f"https://www.vinted.it/catalog?search_by_image_id={sbi}",
                    headers={k: v for k, v in headers_curl.items() if not k.lower().startswith("sec-fetch-user")},
                    cookies=cookies, allow_redirects=True,
                )
                articoli = _conta_articoli_catalogo(resp_cat.text) if resp_cat.status_code == 200 else f"HTTP {resp_cat.status_code}"
            return {"esito": esito, "id": sbi, "durata": time.time() - t0, "articoli": articoli}
    except Exception as e:
        return {"esito": f"errore {type(e).__name__}: {e}", "id": None, "durata": time.time() - t0, "articoli": None}


async def _prova_pagina_riservata(nome, url, cookies, impersonate=None, proxy=None):
    """Controllo di riferimento (2026-09-29): una pagina che richiede il login
    (la posta in arrivo) con gli STESSI cookie della ricerca visuale. Serve a
    separare "la sessione dell'account non viene accettata affatto" da "solo
    /search_by_image la rifiuta". impersonate=None -> httpx (client auth)."""
    t0 = time.time()
    try:
        if impersonate is None:
            resp = await hc._CLIENT_VINTED_AUTH.get(url, cookies=cookies, timeout=20)
        else:
            async with CurlAsyncSession(impersonate=impersonate, proxy=proxy, timeout=20) as sess:
                resp = await sess.get(url, cookies=cookies, allow_redirects=True)
        finale = str(resp.url)
        rimandato = any(x in finale for x in ("/member/register", "/member/login", "/session-refresh"))
        esito = f"rimandato al login ({finale[:90]})" if rimandato else f"HTTP {resp.status_code}, pagina caricata (sessione accettata)"
        return f"{'❌' if rimandato else '✅'} {nome}: {esito} ({time.time() - t0:.1f}s)"
    except Exception as e:
        return f"❌ {nome}: errore {type(e).__name__}: {e} ({time.time() - t0:.1f}s)"


async def testa_ricerca_visuale(url_annuncio):
    """Ritorna le righe del resoconto per Telegram."""
    righe = ["🔎 Test ricerca visuale", url_annuncio, ""]
    righe.append(_descrivi_token("Access token", _VINTED_COOKIES.get("access_token_web")))
    righe.append(_descrivi_token("Refresh token", _VINTED_COOKIES.get("refresh_token_web")))
    righe.append(f"VISUAL_SEARCH_ATTIVA in pipeline: {'si' if VISUAL_SEARCH_ATTIVA else 'no'}")
    righe.append(
        f"Cookie di sessione extra (VINTED_COOKIES_EXTRA): "
        f"{', '.join(sorted(n for n in VINTED_COOKIES_EXTRA if n not in ('access_token_web', 'refresh_token_web'))) or 'nessuno'}"
    )

    if _jwt_scaduto(_VINTED_COOKIES.get("access_token_web")):
        if _jwt_scaduto(_VINTED_COOKIES.get("refresh_token_web")):
            righe += ["", "❌ Entrambi i token scaduti o assenti: serve un nuovo login dal browser "
                          "con l'account dedicato (cookie access_token_web e refresh_token_web)."]
            return righe
        async with _vinted_refresh_lock:
            ok_refresh = await _rinnova_token_vinted()
        righe.append(f"Rinnovo automatico dell'access token: {'riuscito' if ok_refresh else 'FALLITO'}")
        if ok_refresh:
            righe.append(_descrivi_token("Nuovo access token", _VINTED_COOKIES.get("access_token_web")))
        else:
            righe.append("(proseguo lo stesso: l'esito sotto dira' se la sessione viene accettata)")

    item_id = _estrai_item_id_da_url(url_annuncio)
    scraped = await scrape_vinted_listing(url_annuncio, includi_guardaroba=False)
    photo_id = scraped.get("cover_photo_id")
    if not item_id or not photo_id:
        righe += ["", f"❌ Non riesco a leggere item id / foto dall'annuncio (item_id={item_id}, "
                      f"photo_id={photo_id}): pagina annuncio non raggiunta?"]
        return righe

    url_intermedio = f"https://www.vinted.it/items/{item_id}/search_by_image?photo_id={quote(photo_id)}"
    headers = {
        "Referer": f"https://www.vinted.it/items/{item_id}",
        "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-User": "?1",
        "Accept-Language": VINTED_HEADERS.get("Accept-Language", "it-IT,it;q=0.9"),
    }
    cookies = {k: v for k, v in _VINTED_COOKIES.items() if v}
    proxy = PROXY_LIST[0] if PROXY_LIST else None
    righe.append(f"Proxy usato da tutti i client: {_etichetta_proxy(proxy) if proxy else 'nessuno (IP Railway)'}")
    righe.append("")

    # Controllo di riferimento: la sessione e' accettata da una pagina
    # riservata qualunque? (vedi _prova_pagina_riservata)
    righe.append("Controllo sessione su pagina riservata (posta in arrivo):")
    righe.append(await _prova_pagina_riservata("httpx + proxy", "https://www.vinted.it/inbox", cookies))
    if CurlAsyncSession is not None:
        righe.append(await _prova_pagina_riservata(
            "curl_cffi Safari + proxy", "https://www.vinted.it/inbox", cookies, "safari184_ios", proxy))
        righe.append(await _prova_pagina_riservata(
            "curl_cffi Safari SENZA proxy (IP Railway)", "https://www.vinted.it/inbox", cookies, "safari184_ios", None))
    righe.append("")
    righe.append("Ricerca visuale:")

    prove = [("httpx (attuale)", _prova_visuale_httpx(url_intermedio, headers, cookies))]
    if CurlAsyncSession is None:
        righe.append("⚠️ curl_cffi non installato: manca in requirements.txt?")
    else:
        prove += [(nome, _prova_visuale_curl(imp, url_intermedio, headers, cookies, proxy))
                  for nome, imp in VARIANTI_CURL_TEST_VISUALE]
    # In sequenza, non in parallelo: tre richieste simultanee dallo stesso
    # proxy con lo stesso account sarebbero gia' di per se' sospette.
    for nome, coro in prove:
        r = await coro
        icona = "✅" if r["id"] else "❌"
        riga = f"{icona} {nome}: {r['esito']} ({r['durata']:.1f}s)"
        if r["articoli"] is not None:
            riga += f" · risultati: {r['articoli']} articoli"
        righe.append(riga)
        await asyncio.sleep(2)
    log.info("TEST VISUALE %s:\n%s", url_annuncio, "\n".join(righe))
    return righe


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/test_?visuale\b'))
async def on_comando_test_visuale(event):
    try:
        url = extract_url_from_text(event.raw_text or "")
        if not url:
            await event.respond("Uso: /test_visuale <link annuncio Vinted>")
            return
        await event.respond("🔎 Provo la ricerca visuale con httpx e curl_cffi, un attimo...")
        righe = await testa_ricerca_visuale(url)
        for pezzo in _spezza_per_telegram("\n".join(righe)):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /test_visuale:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Test visuale fallito per un errore interno, vedi i log Railway.")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# STIMA UMANA E RAPPORTO FAIR VALUE
# ---------------------------------------------------------------------------
_RE_STIMA_UMANA = re.compile(r"^\s*(?:stima\s*)?(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:€|eur|euro)?\s*$", re.IGNORECASE)


def _id_utente_del_bot():
    try:
        return int(str(TELEGRAM_BOT_TOKEN).split(":")[0])
    except (ValueError, TypeError):
        return None


def _url_annuncio_da_messaggio(msg):
    """URL Vinted di un messaggio del bot: dal testo (verdetto) o dal
    bottone 'Apri su Vinted' (scheda)."""
    url = extract_url_from_text(getattr(msg, "raw_text", "") or "")
    if url:
        return url
    for riga in (getattr(msg, "buttons", None) or []):
        for bottone in riga:
            candidato = getattr(bottone, "url", None)
            if candidato and "/items/" in candidato:
                return candidato
    return None


@client.on(events.NewMessage(outgoing=True))
async def on_stima_umana(event):
    """Rispondi alla scheda (o al verdetto) del bot con un numero: e' la tua
    stima di vendita reale, registrata come campione ad alto peso."""
    try:
        if not event.is_reply:
            return
        m = _RE_STIMA_UMANA.match(event.raw_text or "")
        if not m:
            return
        originale = await event.get_reply_message()
        bot_id = _id_utente_del_bot()
        if not originale or bot_id is None or originale.sender_id != bot_id:
            return
        url = _url_annuncio_da_messaggio(originale)
        item_id = _estrai_item_id_da_url(url) if url else None
        if not item_id:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                "⚠️ Non trovo il link dell'annuncio in quel messaggio: rispondi alla scheda o al verdetto.",
                disable_notification=True)
            return
        valore = float(m.group(1).replace(",", "."))
        fv_registra_umana(item_id, valore)
        d = fv_unisci(_fv_leggi()).get(str(item_id), {})
        pezzi = [f"✅ Stima registrata: {valore:.0f} €"]
        rap, gem = d.get("rapida") or {}, d.get("gemini") or {}
        if rap.get("fv"):
            pezzi.append(f"giudizio rapido {rap['fv']} €")
        if gem.get("vendita"):
            pezzi.append(f"Gemini {gem['vendita']:.0f} €")
        await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, " · ".join(pezzi), disable_notification=True)
    except Exception:
        log.error("Errore nella stima umana:\n%s", traceback.format_exc())


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/report_?fv\b'))
async def on_comando_report_fv(event):
    try:
        for pezzo in _spezza_per_telegram(fv_rapporto()):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /report_fv:\n%s", traceback.format_exc())


URL_TEST_PROXY_DEFAULT = "https://www.vinted.it/catalog?order=newest_first"


async def testa_pool_proxy(url_test=None, timeout=15, max_concorrenza=10):
    """Testa OGNI client del pool proxy con una singola richiesta (nessun
    retry: un fallimento qui e' il dato, non un errore da nascondere), con
    una concorrenza limitata (max_concorrenza) per non sparare 53 richieste
    simultanee su Vinted -- oltre a essere piu' prudente, e' anche piu'
    realistico rispetto al traffico normale della pipeline, che non usa mai
    tutti i proxy nello stesso istante.

    Ritorna una lista di dict, uno per proxy, nello stesso ordine del pool:
    {"etichetta", "ok", "status", "durata_s", "len_html", "dettaglio"}."""
    url = url_test or URL_TEST_PROXY_DEFAULT
    sem = asyncio.Semaphore(max_concorrenza)
    risultati = [None] * len(_CLIENT_VINTED_POOL)

    async def _test_uno(indice):
        client_proxy = _CLIENT_VINTED_POOL[indice]
        chiave = _CLIENT_VINTED_POOL_KEYS[indice]
        etichetta = _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave)
        async with sem:
            # t0 DENTRO il semaforo (fix 2026-09-27, primo test reale: 6.8s di
            # media perche' contava anche l'attesa in coda del proprio turno
            # tra i 10 slot paralleli, non la sola risposta del proxy).
            t0 = time.time()
            try:
                resp = await client_proxy.get(url, headers=VINTED_HEADERS, timeout=timeout)
                durata = time.time() - t0
                testo = _estrai_articoli_da_alt_vinted(resp.text)
                ok = resp.status_code == 200 and MARKER_NESSUN_ARTICOLO_VINTED not in testo
                if ok:
                    dettaglio = None
                elif resp.status_code != 200:
                    dettaglio = f"HTTP {resp.status_code}"
                else:
                    dettaglio = "200 ma nessun articolo estratto (probabile pagina di blocco/verifica)"
                risultati[indice] = {
                    "etichetta": etichetta, "ok": ok, "status": resp.status_code,
                    "durata_s": durata, "len_html": len(resp.text), "dettaglio": dettaglio,
                }
            except Exception as e:
                risultati[indice] = {
                    "etichetta": etichetta, "ok": False, "status": None,
                    "durata_s": time.time() - t0, "len_html": 0,
                    "dettaglio": f"{type(e).__name__}: {e}",
                }

    await asyncio.gather(*(_test_uno(i) for i in range(len(_CLIENT_VINTED_POOL))))
    return risultati


def _formatta_risultati_test_proxy(risultati):
    """Testo leggibile per Telegram: totale, poi un elenco -- prima i
    falliti (quelli che servono davvero attenzione), poi i funzionanti in
    breve. Pura, testabile senza rete."""
    if not risultati:
        return "Nessun proxy nel pool (PROXY_LIST vuota -- richieste dirette senza proxy)."
    ok_list = [r for r in risultati if r["ok"]]
    ko_list = [r for r in risultati if not r["ok"]]
    durata_media_ok = (sum(r["durata_s"] for r in ok_list) / len(ok_list)) if ok_list else 0.0
    righe = [
        f"🔍 Test proxy: {len(ok_list)}/{len(risultati)} funzionanti"
        f"{f', tempo medio {durata_media_ok:.1f}s' if ok_list else ''}."
    ]
    if ko_list:
        righe.append(f"\n❌ Falliti ({len(ko_list)}):")
        for r in ko_list:
            righe.append(f"  {r['etichetta']}: {r['dettaglio']}")
    if ok_list:
        righe.append(f"\n✅ Funzionanti ({len(ok_list)}):")
        righe.append("  " + ", ".join(r["etichetta"] for r in ok_list))
    return "\n".join(righe)


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/venduto\s+(https?://\S+)'))
async def on_comando_venduto(event):
    """/venduto <url annuncio Vinted>: legge la pagina con i proxy del bot e mostra stato, prezzo letto,
    segnali e ogni istante recente trovato (diagnostica del tracciamento vendite, 2026-10-03)."""
    try:
        url = event.pattern_match.group(1).strip()
        if "vinted." not in url:
            await event.respond("Mi serve un link di un annuncio vinted.", parse_mode=None)
            return
        await event.respond("Leggo la pagina, un attimo...", parse_mode=None)
        http_status, html_pagina = await _tracc_leggi_pagina(url, max_retries=3)
        segnali, prezzo = _tracc_estrai_segnali(html_pagina)
        candidati = trova_timestamp_candidati(html_pagina)
        adesso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        testo = (f"HTTP {http_status} | stato={_tracc_stato(http_status, segnali)} | prezzo letto={prezzo}\n"
                 f"Segnali: {segnali or 'nessuno'}\n\nIstanti recenti trovati (adesso {adesso} UTC):\n"
                 + ("\n".join(candidati[:25]) or "nessuno"))
        log.info("DIAG VENDUTO | url=%s | http=%s | prezzo=%s | segnali=%s | istanti=%s", url, http_status,
                 prezzo, segnali, " ## ".join(candidati))
        for pezzo in _spezza_per_telegram(testo):
            await event.respond(pezzo, parse_mode=None)
    except Exception:
        log.error("Errore nel comando /venduto:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Comando /venduto fallito, vedi i log Railway.", parse_mode=None)
        except Exception:
            pass


@client.on(events.NewMessage(outgoing=True, pattern=r'(?i)^/test_?proxy\b'))
async def on_comando_test_proxy(event):
    """Comando digitato dal proprietario in QUALSIASI chat (e' il suo stesso
    account Telethon: un messaggio 'outgoing' puo' venire solo da lui, da
    qualunque dispositivo) -- risponde nella STESSA chat via event.respond,
    senza passare dal bot Telegram separato (niente accoppiamento con
    TELEGRAM_OWNER_CHAT_ID, che comunque e' un ID diverso da questo lato).
    NON richiede modifiche a PROXY_LIST ne' deploy: gira sul pool gia'
    attivo in produzione in questo momento."""
    try:
        await event.respond(f"🔍 Test di {len(_CLIENT_VINTED_POOL)} proxy in corso, un attimo...")
        risultati = await testa_pool_proxy()
        testo = _formatta_risultati_test_proxy(risultati)
        for pezzo in _spezza_per_telegram(testo):
            await event.respond(pezzo)
    except Exception:
        log.error("Errore nel comando /test_proxy:\n%s", traceback.format_exc())
        try:
            await event.respond("⚠️ Test proxy fallito per un errore interno, vedi i log Railway.")
        except Exception:
            pass


@client.on(events.NewMessage(chats=TELEGRAM_GROUP_ID))
async def on_new_message(event):
    # Catturati il piu' presto possibile nell'handler (richiesto dall'utente
    # il 2026-09-21, "monitorare il delay tra ogni step"): t_ricevuto_bot e'
    # il riferimento per quanto ci mette la NOSTRA pipeline (scrape, foto,
    # Occhio, Cervello) fino all'invio della notifica; event.message.date e'
    # il timestamp che Telegram assegna al messaggio del tracker esterno,
    # confrontato in process_listing con created_at (data di pubblicazione
    # Vinted, presa dalla pagina annuncio) per isolare il ritardo che sta
    # PRIMA di noi (pubblicazione -> tracker -> messaggio Telegram), su cui
    # non abbiamo controllo ma che vale la pena vedere separato dal nostro.
    t_ricevuto_bot = time.time()
    msg_date = event.message.date
    stato_pipeline = {}
    try:
        msg_id = event.message.id
        if msg_id in _processed_message_ids:
            return
        _processed_message_ids.add(msg_id)
        if len(_processed_message_ids) > 500:
            _processed_message_ids.discard(min(_processed_message_ids))

        sender = await event.get_sender()
        if not any(h in ((getattr(sender, "username", "") or "") + " " + (getattr(sender, "first_name", "") or "")).lower() for h in VINTED_TRACKER_NAME_HINTS):
            return

        text = event.message.message or ""
        parsed = parse_vinted_tracker_message(text)

        # URL estratto PRIMA del dedup (fix 2026-09-27): l'item id e' la
        # chiave di dedup piu' affidabile, vedi _chiavi_dedup.
        url = extract_url_from_text(text)
        if not url and event.message.buttons:
            for row in event.message.buttons:
                for btn in row:
                    if "vinted." in (getattr(btn, "url", None) or ""):
                        url = getattr(btn, "url", None)
                        break

        if e_variante_recente(parsed, url):
            return

        cover = await event.message.download_media(bytes) if event.message.photo else None
        # Prima: asyncio.to_thread(process_listing, ...), necessario perche'
        # la pipeline era interamente sincrona e avrebbe bloccato il loop.
        # Ora process_listing e' una coroutine e si attende direttamente:
        # Telethon esegue ogni handler come task separato, quindi piu'
        # annunci vengono elaborati davvero in parallelo, e le lunghe attese
        # di rete (scraping, Serper, Gemini) non occupano piu' un thread
        # ciascuna.
        # Tetto alle analisi in parallelo (fix 2026-09-27): senza, un burst
        # di N annunci faceva partire N pipeline complete insieme (scrape,
        # Gemini, Serper), bruciando la quota Gemini e la RAM tutto in una
        # volta. Dal 2026-09-28 il posto si prende DENTRO process_listing,
        # dopo scrape + foto + galleria (leggeri, niente Gemini): in un burst
        # le foto arrivano subito e in coda aspetta solo l'analisi Gemini.
        # L'attesa resta visibile nei tempi della pipeline.
        await process_listing(parsed, url, cover, msg_date=msg_date, t_ricevuto_bot=t_ricevuto_bot,
                              stato=stato_pipeline, semaforo=_semaforo_analisi)
    except Exception:
        log.error("Errore generico:\n%s", traceback.format_exc())
        if stato_pipeline.get("msg_id_galleria") is not None:
            try:
                await telegram_send_message(
                    TELEGRAM_OWNER_CHAT_ID,
                    "⚠️ Analisi interrotta per un errore interno, vedi i log Railway.",
                    reply_to=stato_pipeline["msg_id_galleria"],
                )
            except Exception:
                pass


async def main():
    log.info("Vinted Oracle avviato su Telethon. Versione: %s", BOT_VERSION)
    try:
        from importlib.metadata import version as _v
        log.info("Ambiente: python %s · %s", sys.version.split()[0], " · ".join(
            f"{pkg} {_v(pkg)}" for pkg in ("telethon", "httpx", "Pillow", "brotli", "curl_cffi")))
    except Exception:
        log.warning("Versioni delle dipendenze non leggibili:\n%s", traceback.format_exc())
    log.info(
        "Cervello: %s (output JSON strutturato) · comp da memoria del modello: %s",
        OPENAI_MODEL_CERVELLO if CERVELLO_PROVIDER == "openai" else GEMINI_MODEL_CERVELLO,
        "ammessi" if COMP_DA_MEMORIA_AMMESSI else "esclusi dal calcolo",
    )
    log.info(
        "Occhio: %s · output %s · scarto pre-cervello %s",
        GEMINI_MODEL_OCCHIO,
        "JSON strutturato" if OCCHIO_OUTPUT_JSON else "prosa",
        "calcolato da campi tipizzati" if OCCHIO_OUTPUT_JSON else "da match testuale",
    )
    await inizializza_client_http()
    try:
        n_quote, n_esclusi = ripristina_stato_gemini()
        importati = importa_tracciamento_jsonl() if TRACCIAMENTO_ATTIVO else 0
        log.info("DB %s: ripristinati %d cooldown di quota Gemini e %d modelli esclusi; tracciamento importato: %d righe.",
                 DB_FILE, n_quote, n_esclusi, importati)
    except Exception:
        log.warning("DB non inizializzato (il bot prosegue senza persistenza):\n%s", traceback.format_exc())
    if TRACCIAMENTO_ATTIVO:
        _tracc_item_visti.update(str(r.get("item_id")) for r in _jsonl_read(TRACCIAMENTO_FILE, "Tracciamento")
                                 if r.get("tipo") == "valutato")
    try:
        fv_carica_appreso()
        fv_ricalibra()
    except Exception:
        log.warning("Fair value appreso non caricato:\n%s", traceback.format_exc())
    if not ANALISI_GEMINI_ATTIVA:
        log.warning("ANALISI GEMINI IN PAUSA (ANALISI_GEMINI=0): arrivera' solo la galleria, nessun verdetto.")
        try:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID,
                "⏸️ Bot riavviato con l'analisi AI in pausa: riceverai solo le gallerie. "
                "Per riattivarla: ANALISI_GEMINI=1 su Railway.",
                disable_notification=True,
            )
        except Exception:
            pass
    try:
        await client.start()
        await client.run_until_disconnected()
    finally:
        await chiudi_client_http()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
