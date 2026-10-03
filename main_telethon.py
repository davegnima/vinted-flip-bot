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


# GALLERIA ANTICIPATA (richiesto dall'utente il 2026-09-28): la galleria
# completa arriva nella chat principale APPENA le foto sono scaricate, prima
# di Occhio e Cervello, invece di restare ferma in memoria per tutta
# l'analisi Gemini. Quando il verdetto e' pronto arriva SOLO il testo, come
# risposta al messaggio della galleria. A questo punto l'annuncio ha gia'
# superato FILTRO PRE-SCRAPE e FILTRO PRE-GEMINI, quindi nessuna galleria
# "inutile" per annunci scartati gratis. La galleria parte sempre SILENZIOSA:
# la decisione non e' ancora nota, e il push resta legato al solo verdetto
# COMPRA come prima. Il canale alert resta invariato (foto + testo insieme a
# fine analisi): li' l'invio dipende proprio dal verdetto.
# GALLERIA_ANTICIPATA=0 per tornare al comportamento precedente.
GALLERIA_ANTICIPATA = os.environ.get("GALLERIA_ANTICIPATA", "1").strip() != "0"

# PAUSA ANALISI GEMINI (richiesto dall'utente il 2026-09-28, durante un
# sovraccarico 503 prolungato di Gemini): ANALISI_GEMINI=0 su Railway ->
# arriva SOLO la galleria (album + scheda), nessuna chiamata a
# Gemini/Serper, nessun verdetto. Restano attivi scrape, foto e i filtri
# gratuiti (pre-scrape, pre-Gemini), quindi le gallerie restano solo per
# annunci pertinenti. Il canale alert in pausa non riceve nulla: dipende dal
# verdetto. Cambiare la variabile su Railway riavvia il servizio, quindi il
# valore letto all'avvio basta.
ANALISI_GEMINI_ATTIVA = os.environ.get("ANALISI_GEMINI", "1").strip() != "0"


STATO_ANALISI_COMPLETATA = "✅ Analisi completata, risposta qui sotto"
STATO_ANALISI_COMPLETATA_UNIFICATA = "✅ Analisi completata"
STATO_ANALISI_INTERROTTA = "⚠️ Analisi interrotta per un errore"


def _stato_analisi_testo(n_foto):
    return (f"⏳ Analisi in corso… · {n_foto} foto" if ANALISI_GEMINI_ATTIVA
            else f"⏸️ Analisi AI in pausa · {n_foto} foto")


def _didascalia_galleria_anticipata(listing_info, url, n_foto):
    """Didascalia CORTA dell'album (solo testo semplice, niente Markdown).
    Il contenuto vero sta nella scheda che segue (_scheda_annuncio_testo):
    la notifica push di un album mostra solo "N foto", quindi prezzo e brand
    devono stare nel messaggio di testo mandato per ultimo."""
    return f"📸 {listing_info.get('title') or 'Annuncio'} · {n_foto} foto"[:1024]


def _eta_annuncio_testo(age_days):
    if age_days is None:
        return None
    minuti = max(0, int(age_days * 24 * 60))
    if minuti < 60:
        return f"online da {max(1, minuti)} min"
    if minuti < 24 * 60:
        return f"online da {minuti // 60} h"
    return f"online da {minuti // (24 * 60)} g"


LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA = 600


def _righe_dettagli_annuncio(listing_info):
    """Riga ✨ condizione · 🧵 materiale · 🎨 colore · 📏 taglia (o None)."""
    esc = _escapa_markdown_legacy
    dettagli = []
    for emoji, chiave in (("📏", "size"), ("✨", "condition"), ("🧵", "material_raw"), ("🎨", "color_raw")):
        valore = (listing_info.get(chiave) or "").strip() if isinstance(listing_info.get(chiave), str) else None
        if valore:
            dettagli.append(f"{emoji} {esc(valore)}")
    return " · ".join(dettagli) or None


def _riga_caricato_annuncio(listing_info):
    """🕒 online da N min / 'Caricato' relativo della pagina (solo il primo pezzo: il campo grezzo contiene
    anche descrizione e hashtag, vedi bug del 2026-10-03)."""
    eta = _eta_annuncio_testo(listing_info.get("age_days"))
    if eta:
        return f"🕒 {eta}"
    if listing_info.get("uploaded_text"):
        relativo = str(listing_info["uploaded_text"]).split(",")[0].strip()
        if relativo:
            return f"🕒 Caricato: {_escapa_markdown_legacy(relativo)}"
    return None


def _riga_venditore_annuncio(listing_info):
    esc = _escapa_markdown_legacy
    venditore = []
    if listing_info.get("seller_login"):
        venditore.append(esc(str(listing_info["seller_login"])))
    rep = listing_info.get("seller_feedback_reputation")
    n_rec = listing_info.get("seller_feedback_count")
    if n_rec is not None:
        venditore.append(f"⭐ {rep:.1f} ({n_rec})".replace(".", ",") if rep is not None else f"{n_rec} recensioni")
    if listing_info.get("seller_items_count") is not None:
        venditore.append(f"{listing_info['seller_items_count']} articoli")
    if listing_info.get("seller_country"):
        venditore.append(esc(str(listing_info["seller_country"])))
    return ("👤 " + " · ".join(venditore)) if venditore else None


def _descrizione_utile(listing_info):
    """Descrizione compattata e accorciata, oppure None se non aggiunge nulla al titolo (molti venditori
    ripetono il titolo nella descrizione: la riga sarebbe un doppione)."""
    descrizione = " ".join((listing_info.get("description") or "").split())
    if not descrizione:
        return None
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
    d, t = norm(descrizione), norm(listing_info.get("title"))
    if t:
        parole_t, parole_d = t.split(), d.split()
        # doppione: tutte le parole del titolo ci sono anche nella descrizione (anche con un refuso) e la
        # descrizione ha al massimo 4 parole in piu'
        tutte = all(any(w == x or difflib.SequenceMatcher(None, w, x).ratio() >= 0.8 for x in parole_d)
                    for w in parole_t)
        if d in t or (tutte and len(parole_d) <= len(parole_t) + 4):
            return None
    if len(descrizione) > LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA:
        descrizione = descrizione[:LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA].rstrip() + "…"
    return descrizione


def _scheda_annuncio_testo(listing_info, url, n_foto):
    """Scheda dell'annuncio per il messaggio di testo che segue la galleria
    (richiesto dall'utente il 2026-09-29). PREZZO E BRAND SEMPRE IN PRIMA
    RIGA: e' il messaggio piu' recente della chat, quindi quello che compare
    nell'anteprima della notifica, e l'utente vuole vedere prima quelli e
    non "N foto". Solo dati gia' letti dal tracker e dalla pagina annuncio
    (nessuna richiesta in piu' a Vinted); testo libero sempre passato da
    _escapa_markdown_legacy perche' il messaggio va con parse_mode=Markdown."""
    esc = _escapa_markdown_legacy
    righe = []
    testa = _testa_prezzo_brand(listing_info)
    if testa:
        righe.append("*" + testa + "*")
    righe.append(esc(listing_info.get("title") or "Annuncio"))
    righe.append("")
    riga_fv = _riga_fair_value_testo(listing_info.get("fair_value"))
    for riga in (_righe_dettagli_annuncio(listing_info), esc(riga_fv) if riga_fv else None,
                 _riga_caricato_annuncio(listing_info), _riga_venditore_annuncio(listing_info)):
        if riga:
            righe.append(riga)
    descrizione = _descrizione_utile(listing_info)
    if descrizione:
        righe += ["", f"📝 {esc(descrizione)}"]
    righe += ["", _stato_analisi_testo(n_foto)]
    return "\n".join(righe)


def _testa_prezzo_brand(listing_info):
    """'💶 35,00 € · 🏷️ Brand' (o None): la riga piu' vista del messaggio."""
    prezzo = _a_float(listing_info.get("price"), None)
    brand = (listing_info.get("brand") or "").strip()
    testa = []
    if prezzo is not None:
        testa.append(f"💶 {prezzo:.2f} €".replace(".", ","))
    if brand and brand != "?":
        testa.append(f"🏷️ {_escapa_markdown_legacy(brand)}")
    return " · ".join(testa) or None


async def _invia_galleria_anticipata(listing_info, url, photo_bytes_list, stato=None):
    """Manda nella chat principale l'ALBUM con tutte le foto e SUBITO DOPO la
    scheda di testo (prezzo, brand, dettagli, descrizione, bottone "Apri su
    Vinted"). Ordine voluto: la scheda e' l'ultimo messaggio, quindi e' lei
    l'anteprima della notifica. Tutto silenzioso: la decisione non e' ancora
    nota e il push resta legato al solo verdetto COMPRA.

    Ritorna il message_id dell'album, a cui agganciare il verdetto. None se
    disattivata o se l'album non e' partito: in quel caso
    _invia_risultato_telegram rimanda le foto a fine analisi come prima,
    cosi' un problema qui non fa mai perdere le foto."""
    # In pausa la galleria e' l'unico messaggio: parte anche con
    # GALLERIA_ANTICIPATA=0.
    if not photo_bytes_list or not (GALLERIA_ANTICIPATA or not ANALISI_GEMINI_ATTIVA):
        return None
    n_foto = len(photo_bytes_list)
    id_album = None
    try:
        didascalia = _didascalia_galleria_anticipata(listing_info, url, n_foto)
        if n_foto > 1:
            id_album = await telegram_send_media_group(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list, caption=didascalia, disable_notification=True,
            )
        else:
            id_album = await telegram_send_photo(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=didascalia, disable_notification=True,
            )
    except Exception:
        log.warning("Galleria anticipata non inviata, le foto partiranno col verdetto:\n%s", traceback.format_exc())
    # La scheda parte comunque, anche se l'album e' fallito: in pausa e'
    # l'unica informazione che arriva.
    try:
        scheda = _scheda_annuncio_testo(listing_info, url, n_foto)
        if url:
            id_scheda = await telegram_send_with_buttons(
                TELEGRAM_OWNER_CHAT_ID, scheda, url, None, disable_notification=True, reply_to=id_album,
            )
            if stato is not None and id_scheda:
                # Serve a modificare la riga di stato a fine analisi.
                stato["msg_id_scheda"] = id_scheda
                stato["testo_scheda"] = scheda
                stato["url_scheda"] = url
                stato["stato_testo_iniziale"] = _stato_analisi_testo(n_foto)
        else:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID, scheda, disable_notification=True, reply_to=id_album,
            )
    except Exception:
        log.warning("Scheda annuncio non inviata:\n%s", traceback.format_exc())
    return id_album


async def _invia_risultato_telegram(listing_info, url, photo_bytes_list, header, output_finale,
                                    decisione, e_compra, scenario_usato, urgenza="Bassa",
                                    margine=None, msg_id_galleria=None, stato=None, testo_unificato=None):
    item_id = _estrai_item_id_da_url(url)
    # L'urgenza ora arriva calcolata da calcola_verdetto invece di essere
    # dedotta dal testo del verdetto (_e_urgenza_alta cercava parole come
    # "alta"/"subito"/"forte" dentro la stringa di decisione, e bastava una
    # variante di wording del modello per sbagliare bersaglio).
    e_compra_urgente = e_compra and urgenza == "Alta" and decisione == "COMPRA"

    # Notifica push solo su COMPRA (richiesto dall'utente il 2026-09-20): il
    # messaggio arriva SEMPRE nella chat (nessun filtro sui contenuti, resta
    # tutto consultabile), ma per TRATTA/CHIEDI ALTRE FOTO/NON COMPRA/SKIP
    # Telegram lo consegna senza suono/vibrazione/badge push -- stesso
    # meccanismo di "muta le notifiche" che Telegram offre gia' di suo,
    # applicato messaggio per messaggio invece che sull'intera chat.
    silenzioso = decisione != "COMPRA"

    # Galleria gia' arrivata in anticipo (vedi GALLERIA_ANTICIPATA): qui solo
    # il testo, in risposta a quel messaggio. Altrimenti foto + testo come prima.
    if msg_id_galleria is None:
        if len(photo_bytes_list) > 1:
            await telegram_send_media_group(
                TELEGRAM_OWNER_CHAT_ID,
                photo_bytes_list,
                caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto",
                disable_notification=silenzioso,
            )
        elif len(photo_bytes_list) == 1:
            await telegram_send_photo(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"),
                disable_notification=silenzioso,
            )

    # Richiesto dall'utente il 2026-10-03: un solo messaggio per annuncio. Se non e' un COMPRA (il push
    # arriva solo con un messaggio NUOVO: una modifica non notifica) l'analisi viene scritta nella scheda
    # "Analisi in corso", la cui riga di stato diventa "Analisi completata". Se non entra in un messaggio
    # o la modifica fallisce, si ricade sul messaggio separato di prima.
    unificato = False
    if (stato and decisione != "COMPRA" and ANALISI_GEMINI_ATTIVA and stato.get("msg_id_scheda")
            and stato.get("url_scheda")):
        try:
            vecchio = stato.get("stato_testo_iniziale")
            testo_scheda = stato.get("testo_scheda") or ""
            if vecchio and vecchio in testo_scheda:
                testo_unico = testo_unificato or (
                    testo_scheda.replace(vecchio, STATO_ANALISI_COMPLETATA_UNIFICATA)
                    + "\n\n" + "—" * 20 + "\n" + header + output_finale)
                if len(testo_unico) <= 3900:
                    unificato = await telegram_edit_message(
                        TELEGRAM_OWNER_CHAT_ID, stato["msg_id_scheda"], testo_unico, stato["url_scheda"])
                    if unificato:
                        stato["scheda_unificata"] = True
        except Exception:
            log.warning("Analisi non unificata alla scheda, invio separato:\n%s", traceback.format_exc())

    if not unificato and url:
        await telegram_send_with_buttons(
            TELEGRAM_OWNER_CHAT_ID, header + output_finale, url, item_id if e_compra_urgente else None,
            disable_notification=silenzioso, reply_to=msg_id_galleria,
        )
    elif not unificato:
        await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, header + output_finale,
                                    disable_notification=silenzioso, reply_to=msg_id_galleria)

    # Ristretto a decisione == "COMPRA" il 2026-09-20, secondo giro (questo
    # alert e' un sendMessage separato che NON passa per silenzioso/
    # disable_notification sopra, quindi finche' il trigger restava
    # "e_compra" (COMPRA O TRATTA O CHIEDI ALTRE FOTO) continuava a suonare a
    # piena voce anche su deal ancora incerti -- probabile causa reale delle
    # notifiche push ricevute su stati diversi da COMPRA, a prescindere dal
    # disable_notification sul messaggio principale, che comunque su Telegram
    # silenzia solo il SUONO, non fa sparire del tutto banner/vibrazione).
    # Richiesto dall'utente il 2026-09-20, terzo giro: niente piu' testo ad
    # hoc ("AZIONE RICHIESTA" riassunto) -- nel gruppo alert deve arrivare
    # LO STESSO messaggio completo (foto + header + output_finale, con gli
    # stessi bottoni) che va nella chat principale, non un duplicato
    # semplificato. E' letteralmente un secondo invio dello stesso
    # contenuto verso una chat diversa, sempre a volume pieno (mai
    # silenzioso: e' l'unico posto dove vuole davvero il push).
    #
    # Riallargato a CHIEDI ALTRE FOTO il 2026-09-21 (caso reale: pull Ann
    # Demeulemeester margine=67.55 EUR ROI=799%, scartato dall'alert solo
    # perche' mancava il wash tag nelle foto -- "un CHIEDI ALTRE FOTO con
    # cotale margine vale la pena essere visto"). Non un blanket come nel
    # 2026-09-20 (quello ha causato il giro di restrizione): solo quando il
    # margine supera (">" stretto) SOGLIA_MARGINE_ALERT_CHIEDI_FOTO, e MAI
    # per i brand in BRAND_ESCLUSI_ALERT_CHIEDI_FOTO -- stessa richiesta,
    # stesso messaggio: su questi brand l'autenticita' ancora "sospetta"
    # pesa piu' del margine, meglio aspettare le foto aggiuntive prima del
    # push.
    brand_annuncio_alert = (listing_info.get("brand") or "").strip().lower()
    e_brand_escluso_alert = any(b in brand_annuncio_alert for b in BRAND_ESCLUSI_ALERT_CHIEDI_FOTO)
    e_chiedi_foto_di_valore = (
        decisione == "CHIEDI ALTRE FOTO"
        and margine is not None
        and margine > SOGLIA_MARGINE_ALERT_CHIEDI_FOTO
        and not e_brand_escluso_alert
    )
    if TELEGRAM_ALERT_CHAT_ID and (decisione == "COMPRA" or e_chiedi_foto_di_valore):
        if len(photo_bytes_list) > 1:
            await telegram_send_media_group(
                TELEGRAM_ALERT_CHAT_ID,
                photo_bytes_list,
                caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto",
            )
        elif len(photo_bytes_list) == 1:
            await telegram_send_photo(
                TELEGRAM_ALERT_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"),
            )

        if url:
            await telegram_send_with_buttons(
                TELEGRAM_ALERT_CHAT_ID, header + output_finale, url,
                item_id if (e_compra_urgente and item_id) else None,
            )
        else:
            await telegram_send_message(TELEGRAM_ALERT_CHAT_ID, header + output_finale)


# ---------------------------------------------------------------------------
# PIPELINE PRINCIPALE
# ---------------------------------------------------------------------------

class _PermessoAnalisi:
    """Posto nel tetto di analisi Gemini parallele, preso a meta' pipeline
    (dopo la galleria) e rilasciato sempre da process_listing, anche su
    return anticipato o eccezione."""

    def __init__(self, semaforo):
        self._semaforo = semaforo
        self._preso = False

    async def acquisisci(self, url=None):
        if self._preso:
            return
        if self._semaforo.locked():
            log.info("Analisi Gemini in coda (%d gia' in corso, max %d), scrape e foto gia' fatti: %s",
                     MAX_ANALISI_PARALLELE, MAX_ANALISI_PARALLELE, url)
        await self._semaforo.acquire()
        self._preso = True

    def rilascia(self):
        if self._preso:
            self._preso = False
            self._semaforo.release()


async def _aggiorna_stato_scheda(stato, nuovo_stato):
    """A fine analisi sostituisce nella scheda la riga "⏳ Analisi in corso"
    (modificando il messaggio, niente messaggio nuovo). Mai bloccante: se la
    modifica fallisce la scheda resta com'era."""
    if not stato or not ANALISI_GEMINI_ATTIVA or not stato.get("msg_id_scheda"):
        return
    if stato.get("scheda_unificata"):
        return  # la scheda contiene gia' lo stato finale e l'analisi: non riscriverla
    if stato.get("stato_finale_override") and nuovo_stato == STATO_ANALISI_COMPLETATA:
        nuovo_stato = stato["stato_finale_override"]
    try:
        vecchio = stato.get("stato_testo_iniziale")
        testo = stato.get("testo_scheda") or ""
        if not vecchio or vecchio not in testo:
            return
        await telegram_edit_message(
            TELEGRAM_OWNER_CHAT_ID, stato["msg_id_scheda"],
            testo.replace(vecchio, nuovo_stato), stato.get("url_scheda"),
        )
    except Exception:
        log.warning("Aggiornamento riga di stato della scheda non riuscito:\n%s", traceback.format_exc())


# PANNELLO DI MODELLI IN OMBRA (richiesto dall'utente il 2026-10-03). Un gateway OpenAI-compatibile (OmniRoute)
# fa girare in parallelo, per ogni annuncio, N modelli "occhio" (con le foto) e M modelli "cervello" (stesso
# prompt del Cervello): ognuno scrive UNA riga `PANEL | ...` nel log, accanto alla riga PRIMARIO. Nessun
# modello del pannello entra nel verdetto, nessuna attesa: sono task in background con timeout, tetto orario
# e concorrenza limitata (quota gratuita). Il recap mattutino li confronta con vendita rapida e mediana.
# Spento se mancano EXTRA_LLM_URL e le liste di modelli (separati da virgola).
EXTRA_LLM_URL = (os.environ.get("EXTRA_LLM_URL") or "").strip()   # es. http://omniroute.railway.internal:20128/v1/chat/completions
EXTRA_LLM_KEY = (os.environ.get("EXTRA_LLM_KEY") or "").strip()
EXTRA_LLM_MODEL = (os.environ.get("EXTRA_LLM_MODEL") or "").strip()   # retrocompatibile: un solo modello cervello
PANEL_OCCHIO_MODELLI = [m.strip() for m in (os.environ.get("PANEL_OCCHIO_MODELLI") or "").split(",") if m.strip()]
PANEL_CERVELLO_MODELLI = [m.strip() for m in (os.environ.get("PANEL_CERVELLO_MODELLI") or EXTRA_LLM_MODEL).split(",") if m.strip()]
PANEL_TIMEOUT = _env_float("PANEL_TIMEOUT", 60)
PANEL_MAX_ANNUNCI_ORA = int(_env_float("PANEL_MAX_ANNUNCI_ORA", 60))
PANEL_MAX_FOTO = int(_env_float("PANEL_MAX_FOTO", 6))
_panel_sem = asyncio.Semaphore(int(_env_float("PANEL_CONCORRENZA", 8)))
_task_bg = set()   # riferimenti forti: asyncio tiene solo weakref ai task


def _bg_task(coro):
    t = asyncio.create_task(coro)
    _task_bg.add(t)
    t.add_done_callback(_task_bg.discard)


_panel_ingressi = []   # timestamp degli annunci ammessi nell'ultima ora


def _panel_ammesso(adesso=None):
    """Tetto orario per annunci: protegge la quota gratuita condivisa con la pipeline primaria."""
    adesso = adesso if adesso is not None else time.time()
    while _panel_ingressi and adesso - _panel_ingressi[0] > 3600:
        _panel_ingressi.pop(0)
    if len(_panel_ingressi) >= PANEL_MAX_ANNUNCI_ORA:
        return False
    _panel_ingressi.append(adesso)
    return True


PANEL_MODELLI_PER_ANNUNCIO = int(_env_float("PANEL_MODELLI_PER_ANNUNCIO", 0))   # 0 = tutti; N = rotazione a gruppi di N
PANEL_PAUSA_QUOTA_MIN = _env_float("PANEL_PAUSA_QUOTA_MIN", 30)
_panel_pausa = {}    # modello -> timestamp fino a cui e' in pausa (quota finita / non disponibile)
_panel_giro = {"occhio": 0, "cervello": 0}


def _panel_e_modello_principale(modello):
    """True se il modello e' lo stesso del flusso principale (stessa quota giornaliera): mai nel pannello."""
    nome = modello.split("@")[0]
    principali = {GEMINI_MODEL_OCCHIO, GEMINI_MODEL_CERVELLO, *GEMINI_MODELLI_RISERVA, *GEMINI_CASCATA}
    return nome in {f"gemini/{m}" for m in principali}


def panel_scegli_modelli(tipo, modelli, adesso=None):
    """Modelli da interrogare per questo annuncio: esclude quelli del flusso principale e quelli in pausa
    (quota finita), poi ruota a gruppi di PANEL_MODELLI_PER_ANNUNCIO per distribuire i limiti giornalieri."""
    adesso = adesso if adesso is not None else time.time()
    attivi = [m for m in modelli if not _panel_e_modello_principale(m) and _panel_pausa.get(m, 0) <= adesso]
    n = PANEL_MODELLI_PER_ANNUNCIO
    if n <= 0 or n >= len(attivi):
        return attivi
    inizio = _panel_giro[tipo] % len(attivi)
    _panel_giro[tipo] += n
    return [attivi[(inizio + i) % len(attivi)] for i in range(n)]


def _panel_segna_errore(modello, err, adesso=None):
    """Quota/accesso/modello dismesso: pausa, per non sprecare chiamate e riprovare piu' tardi."""
    adesso = adesso if adesso is not None else time.time()
    if err in ("http429", "http402", "http403"):
        _panel_pausa[modello] = adesso + PANEL_PAUSA_QUOTA_MIN * 60
    elif err in ("http404", "http410"):
        _panel_pausa[modello] = adesso + 6 * 3600


def estrai_json_da_testo_llm(testo):
    """Primo oggetto JSON in una risposta testuale (anche dentro ```), None se non valido."""
    if not isinstance(testo, str):
        return None
    m = re.search(r"\{.*\}", testo, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def estrai_target_da_testo_llm(testo):
    d = estrai_json_da_testo_llm(testo)
    t = d.get("prezzo_target_vendita_eur") if d else None
    return float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None


async def _panel_chiama(modello, system, user_content, max_tokens):
    """Una chiamata al gateway. Ritorna (testo|None, ms, errore|None). Non solleva mai."""
    t0 = time.time()
    async with _panel_sem:
        try:
            headers = {"Content-Type": "application/json"}
            if EXTRA_LLM_KEY:
                headers["Authorization"] = f"Bearer {EXTRA_LLM_KEY}"
            payload = {"model": modello, "temperature": 0.2, "max_tokens": max_tokens,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user_content}]}
            resp = await asyncio.wait_for(
                hc._client_generico.post(EXTRA_LLM_URL, headers=headers, json=payload, timeout=PANEL_TIMEOUT),
                timeout=PANEL_TIMEOUT + 3)
            ms = int((time.time() - t0) * 1000)
            if not resp.is_success:
                return None, ms, f"http{resp.status_code}"
            testo = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content")
            return testo, ms, None
        except Exception as e:
            return None, int((time.time() - t0) * 1000), type(e).__name__


def _riga_panel(tipo, item_id, brand, modello, ok, ms, **campi):
    extra = " | ".join(f"{k}={v}" for k, v in campi.items() if v is not None)
    log.info("PANEL | %s | %s | %s | %s | %s | %dms%s", tipo, item_id, brand or "-", modello,
             "ok" if ok else "ERR", ms, f" | {extra}" if extra else "")


def _campi_occhio_panel(o, problemi):
    return {"problemi": len(problemi), "legit": o.get("verdetto_legit"), "conf": o.get("confidenza_legit"),
            "evid": o.get("qualita_evidenza"), "cond": o.get("condizione_osservata"),
            "brand_letto": str(o.get("brand_letto_etichetta") or "")[:30] or None,
            "capo": str(o.get("modello_riconosciuto") or "")[:40] or None,
            "motivo_legit": str(o.get("motivo_sintetico") or "").replace("|", "/").replace("\n", " ")[:100] or None}


async def _panel_occhio_modello(item_id, brand, modello, system, user_text, immagini):
    contenuto = [{"type": "text", "text": user_text}] + immagini
    testo, ms, err = await _panel_chiama(modello, system, contenuto, 4000)
    if err:
        _panel_segna_errore(modello, err)
        return _riga_panel("occhio", item_id, brand, modello, False, ms, errore=err)
    d = estrai_json_da_testo_llm(testo)
    if d is None:
        return _riga_panel("occhio", item_id, brand, modello, False, ms, errore="json_non_valido")
    try:
        o, problemi = valida_payload_occhio(d)
        _riga_panel("occhio", item_id, brand, modello, True, ms, **_campi_occhio_panel(o, problemi))
    except Exception as e:
        _riga_panel("occhio", item_id, brand, modello, False, ms, errore=type(e).__name__)


async def panel_occhio(item_id, brand, user_text, photo_bytes_list, occhio_json, problemi):
    """Pannello occhio: stessa richiesta del primario, N modelli con visione. Mai bloccante."""
    if not (EXTRA_LLM_URL and PANEL_OCCHIO_MODELLI and photo_bytes_list and _panel_ammesso()):
        return
    try:
        if occhio_json:
            _riga_panel("occhio", item_id, brand, "PRIMARIO", True, 0, **_campi_occhio_panel(occhio_json, problemi or []))
        parts = await costruisci_parts_foto(photo_bytes_list[:PANEL_MAX_FOTO])
        immagini = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + p["inline_data"]["data"]}}
                    for p in parts]
        schema = json.dumps(_schema_gemini_to_openai(OCCHIO_RESPONSE_SCHEMA_GEMINI), ensure_ascii=False)
        system = (GEMINI_OCCHI_SYSTEM_PROMPT_JSON +
                  "\n\nRispondi SOLO con un oggetto JSON valido conforme a questo schema, senza altro testo:\n" + schema)
        await asyncio.gather(*(_panel_occhio_modello(item_id, brand, m, system, user_text, immagini)
                               for m in panel_scegli_modelli("occhio", PANEL_OCCHIO_MODELLI)))
    except Exception:
        log.warning("Pannello occhio fallito:\n%s", traceback.format_exc())


async def _panel_cervello_modello(item_id, brand, modello, system, user_text, prezzo, system_compatto=None):
    nome = modello_chiamato = modello
    if modello.endswith("@c"):
        modello, system = modello[:-2], system_compatto or prompt_cervello_compatto()
    testo, ms, err = await _panel_chiama(modello, system, user_text, 6000)
    if err:
        _panel_segna_errore(modello_chiamato, err)
        return _riga_panel("cervello", item_id, brand, nome, False, ms, errore=err)
    d = estrai_json_da_testo_llm(testo)
    if d is None:
        return _riga_panel("cervello", item_id, brand, nome, False, ms, errore="json_non_valido")
    try:
        v, problemi = valida_payload_cervello(d)
        vc = calcola_verdetto(v, prezzo)
        _riga_panel("cervello", item_id, brand, nome, True, ms, target=_fmt0(v.get("prezzo_target_vendita_eur")),
                    esito=vc["decisione"], margine=_fmt0(vc.get("margine")), roi=_fmt0(vc.get("roi")),
                    legit=v.get("legit_verdetto"), problemi=len(problemi))
    except Exception as e:
        _riga_panel("cervello", item_id, brand, nome, False, ms, errore=type(e).__name__)


def _fmt0(x):
    return f"{x:.0f}" if isinstance(x, (int, float)) and not isinstance(x, bool) else None


async def panel_cervello(item_id, brand, user_text, prezzo, v_primario, verdetto_primario):
    """Pannello cervello: stesso prompt del Cervello a M modelli (senza ricerche: usano il pool gia' nel prompt)."""
    if not (EXTRA_LLM_URL and PANEL_CERVELLO_MODELLI and _panel_ammesso()):
        return
    try:
        _riga_panel("cervello", item_id, brand, "PRIMARIO", True, 0,
                    target=_fmt0(v_primario.get("prezzo_target_vendita_eur")), esito=verdetto_primario["decisione"],
                    margine=_fmt0(verdetto_primario.get("margine")), roi=_fmt0(verdetto_primario.get("roi")),
                    legit=v_primario.get("legit_verdetto"))
        schema = json.dumps(CERVELLO_RESPONSE_SCHEMA_OPENAI, ensure_ascii=False)
        system = (GEMINI_CERVELLO_SYSTEM_PROMPT +
                  "\n\nRispondi SOLO con un oggetto JSON valido conforme a questo schema, senza altro testo:\n" + schema)
        await asyncio.gather(*(_panel_cervello_modello(item_id, brand, m, system, user_text, prezzo)
                               for m in panel_scegli_modelli("cervello", PANEL_CERVELLO_MODELLI)))
    except Exception:
        log.warning("Pannello cervello fallito:\n%s", traceback.format_exc())


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


def componi_testi_verdetto(listing_info, verdetto_calcolato, output_finale, info_foto="", campioni_target=None,
                           stima_instabile=False):
    """Dal testo di render_messaggio_verdetto (prima riga = decisione, seconda = margine, poi il resto) costruisce:
    - header: intestazione del messaggio STANDALONE (COMPRA, che deve restare un messaggio nuovo per il push);
    - resto: il corpo senza le prime due righe;
    - unificato: il messaggio unico che sostituisce la scheda "Analisi in corso" (tutti gli altri esiti):
      verdetto + prezzo + brand in prima riga, poi ogni dato UNA volta sola (richiesto dall'utente il 2026-10-03).
    Pura, testabile."""
    righe_output = output_finale.split("\n", 2)
    riga_verdetto = righe_output[0]
    riga_margine = righe_output[1] if len(righe_output) > 1 else ""
    resto_output = righe_output[2] if len(righe_output) > 2 else ""

    brand_escapato = _escapa_markdown_legacy(listing_info.get("brand"))
    riga_verdetto_con_brand = riga_verdetto + (f" · {brand_escapato}" if brand_escapato else "")
    riga_fv = _riga_fair_value_unica(listing_info.get("fair_value"), verdetto_calcolato, campioni_target, stima_instabile)

    header = (
        riga_verdetto_con_brand + "\n"
        + (riga_margine + "\n" if riga_margine else "")
        + (riga_fv + "\n" if riga_fv else "")
        + f"🆕 *{_escapa_markdown_legacy(listing_info.get('title'))}*"
        + info_foto
        + f"\n{'—' * 20}\n"
    )

    testa = _testa_prezzo_brand(listing_info)
    deal, _, resto = resto_output.partition("\n\n")
    blocchi = [
        riga_verdetto + (f" · {testa}" if testa else ""),
        _escapa_markdown_legacy(listing_info.get("title") or "Annuncio"),
        _righe_dettagli_annuncio(listing_info),
        _riga_caricato_annuncio(listing_info),
        info_foto.strip() or None,
        "",
        riga_margine or None,
        deal or None,
        riga_fv or None,
        _riga_venditore_annuncio(listing_info),
    ]
    descrizione = _descrizione_utile(listing_info)
    if descrizione:
        blocchi.append(f"📝 {_escapa_markdown_legacy(descrizione)}")
    unificato = "\n".join(b for b in blocchi if b is not None) + "\n\n" + resto
    return header, resto_output, unificato


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

    # --- OCCHIO: due rami, scelti da OCCHIO_OUTPUT_JSON.
    # In entrambi i casi il resto della pipeline riceve `output_occhi` come
    # testo: in modalita' JSON e' il rendering del dict, cosi' build_skip_report
    # e il prompt del Cervello continuano a funzionare senza modifiche.
    occhio_json = None
    problemi_occhio = []
    if OCCHIO_OUTPUT_JSON:
        output_grezzo, costo_occhi, _ = await chiama_gemini(
            GEMINI_OCCHI_SYSTEM_PROMPT_JSON, user_text_occhi, photo_bytes_list,
            grounding=False, response_schema=OCCHIO_RESPONSE_SCHEMA_GEMINI)
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
            GEMINI_OCCHI_SYSTEM_PROMPT, user_text_occhi, photo_bytes_list, grounding=False)
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
            else chiama_gemini_cervello_forzato
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
            listing_info, verdetto_calcolato, output_finale, info_foto, campioni_target, stima_instabile)

    try:
        fv_registra_gemini(listing_info, url, decisione, verdetto_calcolato,
                           occhio_json=occhio_json, legit=legit_cervello)
    except Exception:
        log.warning("Esito Gemini non archiviato:\n%s", traceback.format_exc())
    await _invia_risultato_telegram(
        listing_info, url, photo_bytes_list,
        header, output_finale, decisione, e_compra,
        scenario_usato, urgenza,
        margine=verdetto_calcolato["margine"] if verdetto_calcolato else None,
        msg_id_galleria=msg_id_galleria, stato=stato, testo_unificato=testo_unificato,
    )


# ---------------------------------------------------------------------------
# TELETHON CLIENT
# ---------------------------------------------------------------------------

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
_processed_message_ids = set()
_recent_listings_seen = {}

DEDUP_CONTENUTO_WINDOW_SECONDS = 300

MAX_ANALISI_PARALLELE = max(1, int(os.environ.get("MAX_ANALISI_PARALLELE", "4")))
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
