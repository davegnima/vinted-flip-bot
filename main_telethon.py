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


def costo_gemini_token(usage, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT):
    inp = usage.get("promptTokenCount", 0) or 0
    out = usage.get("candidatesTokenCount", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


async def chiama_gemini(system_prompt, user_text, photo_bytes_list=None, grounding=False, max_retries=4,
                        api_url=GEMINI_API_URL_OCCHIO, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT,
                        response_schema=None):
    """response_schema: se valorizzato, la risposta e' JSON conforme allo
    schema invece che prosa libera (usato dall'Occhio con
    OCCHIO_OUTPUT_JSON=true). Il testo ritornato e' il JSON grezzo: a
    deserializzarlo e validarlo ci pensa il chiamante."""
    photo_bytes_list = photo_bytes_list or []
    parts = [{"text": user_text}] + await costruisci_parts_foto(photo_bytes_list)

    generation_config = {
        "temperature": 0.2, "maxOutputTokens": 3000,
        "thinkingConfig": {"thinkingLevel": "low"},
    }
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
        "generationConfig": generation_config,
    }
    if response_schema is not None:
        # L'API rifiuta responseMimeType/responseSchema insieme a "tools"
        # ("Function calling with a response mime type: 'application/json'
        # is unsupported"): e' lo stesso vincolo che ha imposto le due fasi
        # separate nel Cervello. Qui grounding non serve (l'Occhio e' sempre
        # invocato con grounding=False), ma la guardia evita che una futura
        # modifica produca un 400 difficile da diagnosticare.
        if grounding:
            log.warning("chiama_gemini: grounding ignorato, incompatibile con response_schema.")
            grounding = False
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
    if grounding:
        payload["tools"] = [{"google_search": {}}]

    # Retry ridotti se un blackout Gemini e' gia' in corso (vedi
    # _gemini_in_blackout piu' sopra): non ha senso impegnarsi per
    # max_retries pieni quando le ultime chiamate hanno gia' dimostrato che
    # tutte le key sono in errore -- si fallisce prima e si passa al
    # fallback (prosa/skip), invece di aspettare minuti su una chiamata che
    # quasi certamente fallira' comunque.
    max_retries_effettivi = MAX_RETRIES_GEMINI_IN_BLACKOUT if _gemini_in_blackout() else max_retries
    if GEMINI_CASCATA:
        max_retries_effettivi += len(GEMINI_API_KEYS)   # i 429 di quota esaurita sono rapidi: non bruciano il budget

    backoff_seconds = 2
    for attempt in range(1, max_retries_effettivi + 1):
        try:
            # Timeout abbassato da 90 a 30s (richiesto dall'utente il
            # 2026-09-22): 90s era pensato per una risposta lenta ma valida,
            # non per un 503 (che nei log arriva in 10-45s, non per timeout) --
            # ma se Gemini smette proprio di rispondere invece di restituire
            # un errore, 90s per tentativo x piu' tentativi x piu' round del
            # Cervello e' comunque troppo. 30s resta ampio per foto+prompt.
            url_usato = _gemini_url_effettivo(api_url)
            modello_usato = _gemini_modello_da_url(url_usato)
            key_usata = _gemini_key_attuale(modello_usato)
            # Key nell'header e non nella query string (FIX 2026-09-24): come
            # parametro "?key=" finiva in chiaro nei log httpx su Railway.
            resp = await hc._client_generico.post(
                url_usato, headers={"x-goog-api-key": key_usata}, json=payload, timeout=30)
            if not resp.is_success:
                log.warning("Gemini HTTP %d: %s", resp.status_code, resp.text[:500])
                # Modello (non key) non disponibile: niente rotazione key,
                # si passa subito al modello successivo della catena -- vedi
                # GEMINI_MODELLI_RISERVA.
                #
                # FIX 2026-09-26: la marcatura di esclusione (dentro la
                # funzione qui sotto) va SEMPRE eseguita, anche se e' l'ultimo
                # tentativo disponibile -- prima era dietro "attempt <
                # max_retries_effettivi and ...", quindi in cortocircuito non
                # veniva mai chiamata sull'ultimo tentativo. In un blackout
                # (tentativi ridotti a MAX_RETRIES_GEMINI_IN_BLACKOUT) e'
                # proprio li' che capitava quasi sempre il 404 di riserva,
                # cosi' il modello rotto non veniva mai escluso e si
                # ripresentava identico ad ogni chiamata successiva (vedi
                # log 24-25/09: 67 404 su gemini-2.5-flash-lite, 0 marcature).
                # Ora si continua solo se resta budget di tentativi.
                modello_cambiato = _gemini_gestisci_modello_non_disponibile(
                    api_url, url_usato, resp.status_code, resp.text)
                if modello_cambiato and attempt < max_retries_effettivi:
                    continue
            if resp.is_success:
                _gemini_registra_esito(True)
                log.info("GEMINI_USO | generico | %s", modello_usato)
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) or [])
                    usage = data.get("usageMetadata", {})
                    grounding_metadata = candidates[0].get("groundingMetadata", {}) if candidates else {}
                    n_query = len(grounding_metadata.get("webSearchQueries", []) or [])
                    costo = costo_gemini_token(usage, prezzo_input, prezzo_output) + n_query * PREZZO_GROUNDING_PER_QUERY
                    return text, costo, n_query
                return "[ERRORE: risposta Gemini senza candidates]", 0.0, 0
            if resp.status_code == 429 or resp.status_code in {500, 502, 503, 504}:
                # 429: quota del piano free esaurita (RESOURCE_EXHAUSTED), non
                # un rate-limit che passa da solo in pochi secondi -- vedi
                # caso reale del 2026-09-20 (500 richieste/giorno esaurite in
                # poche ore).
                #
                # 500/502/503/504 (FIX 2026-09-21, log utente "vedo tempi
                # biblici": un blackout Gemini di ~9 minuti di 503 "high
                # demand" ha fatto accumulare minuti di backoff su Occhio +
                # fino a 3 chiamate Cervello in sequenza) ruotano ora la key
                # ESATTAMENTE come il 429, invece di aspettare solo il
                # backoff sulla stessa: su Google Cloud la capacita' e'
                # spesso allocata per progetto/key, quindi un 503 puo' essere
                # specifico della key corrente, non un blackout del modello
                # per chiunque -- vale la pena provarne subito un'altra
                # prima di aspettare. Se e' davvero un blackout globale del
                # modello, la key diversa fallira' anch'essa e si cade
                # comunque nel backoff sotto: nessun peggioramento nel caso
                # peggiore, possibile miglioramento in quello buono.
                #
                # In entrambi i casi: se c'e' un'altra key in GEMINI_API_KEYS
                # si passa a quella e si ritenta SUBITO (niente attesa);
                # solo se le key sono finite (o ce n'e' una sola) si torna al
                # backoff come per gli altri errori transitori.
                if _gemini_e_errore_quota_giornaliera(resp.status_code, resp.text):
                    _gemini_segna_key_quota_esaurita(key_usata, modello_usato, _gemini_secondi_retry(resp.text))
                    if GEMINI_CASCATA and _gemini_url_effettivo(api_url) != url_usato:
                        continue   # quota finita su tutte le key di questo modello: si scala subito al successivo
                if _gemini_prossima_key(modello_usato):
                    continue
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries_effettivi:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            _gemini_registra_esito(False)
            return f"[ERRORE: chiamata Gemini fallita dopo {max_retries_effettivi} tentativi. Eccezione: {e}]", 0.0, 0
    _gemini_registra_esito(False)
    return "[ERRORE: tentativi esauriti]", 0.0, 0


# ---------------------------------------------------------------------------
# CERVELLO GEMINI CON FUNCTION CALLING FORZATO
# ---------------------------------------------------------------------------
# Il tool builtin "google_search" di Gemini NON e' forzabile in modo affidabile
# (il modello spesso decide di non chiamarlo mai, anche se il prompt lo chiede
# esplicitamente). Sostituiamo con una function custom che richiama Serper --
# stesso servizio gia' usato per i comp pre-raccolti -- e la forziamo con
# tool_config.function_calling_config.mode = "ANY", che per il function calling
# "vero" (non il retrieval builtin) e' effettivamente vincolante.

def valuta_qualita_comp(comps_text):
    """Stima se i comp pre-raccolti da Serper sono sufficienti a dare un
    verdetto senza bisogno di forzare una ricerca aggiuntiva. Euristica
    semplice: conta quanti prezzi reali compaiono nel blocco, e verifica
    che la categoria non sia stata saltata per mancata rilevazione.

    Soglia abbassata da 5 a 3 (controllo costi, Pareto): i comp pre-raccolti
    sono gia' inclusi nel costo Serper esistente, mentre ogni ricerca extra
    che il Cervello decide di forzare quando questa funzione ritorna False
    e' un giro di chiamata Gemini aggiuntivo (il costo piu' caro e variabile
    del bot, vedi MAX_ROUNDS_FUNZIONE). 3 prezzi reali gia' anticipano quasi
    sempre un range utilizzabile, senza dover pagare per scoprirlo."""
    if not comps_text:
        return False
    if "Categoria non rilevata" in comps_text:
        return False
    n_prezzi = len(re.findall(r"€\s*\d", comps_text)) + len(re.findall(r"EUR\s*[\d.,]+", comps_text))
    return n_prezzi >= 3


# Snippet-placeholder che Google/Serper restituisce quando non riesce a
# generare un estratto reale (pagina JS-rendered, bloccata, o senza testo
# indicizzabile) -- puro rumore, occupa spazio nel contesto del cervello
# senza portare ne' un prezzo ne' informazione utile.
SNIPPET_PLACEHOLDER_INUTILI = [
    "nessuna informazione disponibile per questa pagina",
]

# Simboli di valuta non-EUR il cui prezzo non e' direttamente comparabile
# senza conversione (mercati regionali: baht thailandese, yen, rupia, won,
# ecc.) -- un risultato che ha SOLO questi simboli di prezzo (nessun
# €/EUR/$/USD/£/GBP nello snippet) va scartato perche' il cervello non ha
# modo di convertirlo in modo affidabile e rischia di trattarlo come comp
# diretto.
SIMBOLI_VALUTA_NON_COMPARABILI = ["฿", "¥", "₹", "₩", "₫", "₱"]
SIMBOLI_VALUTA_COMPARABILI = ["€", "eur", "$", "usd", "£", "gbp"]


def _riga_serper_e_rumore(titolo, snippet):
    """True se la riga (titolo+snippet) di un risultato Google/Serper va
    scartata perche' non porta informazione utile al cervello -- vedi
    SNIPPET_PLACEHOLDER_INUTILI e SIMBOLI_VALUTA_NON_COMPARABILI sopra per
    il dettaglio dei due casi coperti, individuati da un caso reale
    (ricerca on-demand 'GU x Undercover Cargo' che restituiva pagine eBay
    senza snippet e annunci in thailandese con prezzi in baht)."""
    testo_completo = f"{titolo} {snippet}".strip()
    if not testo_completo:
        return True
    # .rstrip(".") perche' Google a volte restituisce il placeholder con un
    # punto finale ("...pagina.") e a volte senza -- confermato empiricamente
    # nel caso reale che ha originato questo filtro (vedi log 'gu × undercover').
    snippet_lower = snippet.strip().lower().rstrip(".")
    if snippet_lower in SNIPPET_PLACEHOLDER_INUTILI:
        return True
    ha_valuta_non_comparabile = any(simbolo in testo_completo for simbolo in SIMBOLI_VALUTA_NON_COMPARABILI)
    ha_valuta_comparabile = any(simbolo in testo_completo.lower() for simbolo in SIMBOLI_VALUTA_COMPARABILI)
    if ha_valuta_non_comparabile and not ha_valuta_comparabile:
        return True
    return False


async def cerca_serper_mirata(query):
    """Ricerca aggiuntiva mirata, richiamabile dal cervello quando i comp
    pre-raccolti sono insufficienti o fuori tema.

    Ritorna (testo, mappa_url) dal 2026-09-25 (Punto 3 esteso alla ricerca
    on-demand, richiesto dall'utente): mappa_url e' costruita da r['link']
    (il campo con l'URL della pagina, gia' restituito da Serper ma prima
    scartato qui) SOLO per le righe dove riusciamo anche a isolare un
    prezzo dal titolo+snippet con lo stesso regex €/EUR usato per il pool
    (_estrai_prezzi_da_pool_ricerca) -- a differenza di Vinted/Resellbot, qui
    non c'e' un prezzo strutturato garantito riga per riga (e' testo libero
    di uno snippet Google), quindi il match e' best-effort: se il prezzo non
    si isola in modo univoco, quella riga resta senza link piuttosto che
    rischiare di agganciarne uno sbagliato. L'URL non viene MAI passato al
    Cervello (resta fuori dal testo restituito) -- stesso principio delle
    altre fonti, il link si riattacca in Python al rendering finale."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", {}
    payload = [{"q": query, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await hc._client_generico.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}", {}
    lines = []
    mappa_url = {}
    scartate = 0
    for batch in results:
        for r in batch.get("organic", [])[:8]:
            titolo = r.get("title", "")
            snippet = (r.get("snippet", "") or "")[:150]
            if _riga_serper_e_rumore(titolo, snippet):
                scartate += 1
                continue
            lines.append(f"- {titolo}: {snippet}")
            link = (r.get("link") or "").strip()
            if link:
                prezzi_riga = _estrai_prezzi_da_pool_ricerca(f"{titolo} {snippet}")
                # Solo se il prezzo e' univoco su questa riga: due prezzi
                # diversi nello stesso snippet (es. prezzo originale +
                # scontato) renderebbero la chiave ambigua, meglio nessun
                # link che uno sbagliato.
                if len(prezzi_riga) == 1:
                    prezzo = next(iter(prezzi_riga))
                    chiave = (_normalizza_titolo_per_link(titolo), f"{prezzo:.2f}")
                    mappa_url.setdefault(chiave, link)
    if scartate:
        log.info("cerca_serper_mirata: scartate %d righe di rumore (snippet vuoto/placeholder o valuta non comparabile) per query '%s'.", scartate, query)
    testo = "\n".join(lines) if lines else "Nessun risultato trovato per questa query."
    return testo, mappa_url


CERVELLO_FUNCTION_DECLARATION = {
    "name": "cerca_comp_prezzo",
    "description": (
        "Cerca sul web per due scopi distinti, entrambi validi: (1) trovare comp "
        "di prezzo aggiuntivi quando i dati pre-raccolti sono insufficienti, fuori "
        "tema o troppo scarsi; (2) VERIFICARE la plausibilita' di codici prodotto, "
        "diciture rare ('prototipo', 'campionario', edizione limitata) o altri "
        "claim molto specifici citati nell'analisi visiva, prima di trattarli come "
        "prova di autenticita' o di valore superiore alla media."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Query di ricerca mirata, es. 'YSL camicia vintage uomo venduto eBay' "
                    "oppure 'Miu Miu codice PMMJ-2016 prototipo collezione'. Se il capo "
                    "appartiene a una sottolinea o linea/etichetta specifica (es. 'M Missoni', "
                    "'JPG.JEAN'S', 'Weekend Max Mara'), nominala SEMPRE nella query al posto "
                    "del solo brand madre generico -- es. 'M Missoni maglione zigzag', non "
                    "'Missoni maglione zigzag', per evitare comp del mainline che sovrastimano "
                    "un capo di sottolinea."
                ),
            }
        },
        "required": ["query"],
    },
}


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


MAX_ROUNDS_FUNZIONE = 2  # Rialzato da 1 a 2 il 2026-09-14. Con 1, i log
                         # mostravano che ~1 item su 2 finiva comunque nel
                         # fallback forzato, che nel caso peggiore costa
                         # quanto il vecchio "2 giri" (3 chiamate totali) ma
                         # senza dare al modello la seconda ricerca reale che
                         # chiedeva. Con 2 il caso "un giro basta" costa
                         # uguale a prima, il caso "serve una seconda ricerca"
                         # costa quanto il vecchio fallback ma con una
                         # ricerca vera al posto del rifiuto secco.

ISTRUZIONE_FASE_JSON = (
    "Le ricerche sono terminate. Produci ORA il verdetto come oggetto JSON "
    "conforme allo schema, usando esclusivamente i dati e i comp raccolti in "
    "questa conversazione. Ricorda: non calcolare margine, ROI, decisione, "
    "urgenza o importi di trattativa, e marca fonte='memoria_modello' ogni "
    "prezzo che non compare nei dati ricevuti."
)


def _estrai_testo_da_parts(parts):
    return "".join(p.get("text", "") for p in (parts or []) if isinstance(p, dict))


async def chiama_gemini_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4,
                                         api_url=GEMINI_API_URL_CERVELLO,
                                         prezzo_input=PREZZO_CERVELLO_INPUT,
                                         prezzo_output=PREZZO_CERVELLO_OUTPUT,
                                         mappa_url_ricerche_extra=None):
    """Cervello Gemini in DUE FASI, imposte da un vincolo dell'API.

    FASE 1 -- RICERCA (fino a MAX_ROUNDS_FUNZIONE giri): function calling
    come prima. Con forza_ricerca=True il primo giro DEVE chiamare
    cerca_comp_prezzo (mode ANY), i successivi sono liberi (AUTO).

    FASE 2 -- VERDETTO (un solo giro): "tools" e "tool_config" vengono
    TOLTI dal payload e si accendono responseMimeType="application/json" +
    responseSchema. L'output e' quindi un oggetto conforme a
    CERVELLO_RESPONSE_SCHEMA, non piu' prosa da cui pescare numeri con
    espressioni regolari.

    Perche' due fasi e non una: Gemini rifiuta un payload che contenga
    insieme function_declarations e responseMimeType "application/json"
    ("Function calling with a response mime type: 'application/json' is
    unsupported"). Non e' un bug transitorio ma una limitazione
    documentata, quindi la separazione e' strutturale, non un workaround
    temporaneo.

    Effetto collaterale positivo: sparisce l'intera classe di bug che
    affliggeva la vecchia ultima fase. Prima, per impedire al modello di
    restituire l'ennesima functionCall al posto del verdetto, servivano un
    "mode: NONE" dichiarato esplicitamente, un tentativo di fallback senza
    tools e una diagnostica sul testo vuoto (vedi lo storico dei commenti
    del 2026-09-13). Ora, con responseMimeType="application/json", il
    modello non ha piu' un canale per emettere una functionCall: l'unico
    output sintatticamente valido e' l'oggetto JSON.

    Ritorna una tupla di 5 elementi:
      (verdetto_dict | None, errore | None, costo_totale, n_query_extra,
       ricerche_extra_raw)

    mappa_url_ricerche_extra (aggiunto il 2026-09-25, Punto 3 esteso alla
    ricerca on-demand): dict opzionale fornito dal chiamante, AGGIORNATO IN
    PLACE (non nel valore di ritorno, per non cambiare la tupla usata
    dall'unico chiamante attuale) con la mappa URL di ogni query
    cerca_serper_mirata riuscita in questa chiamata -- vedi cerca_serper_mirata
    per come viene costruita."""
    contents = [{"role": "user", "parts": [{"text": user_text}]}]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []  # testo grezzo di ogni cerca_serper_mirata riuscita,
                             # usato per etichettare i comp che il cervello
                             # dichiara e per il blocco debug Telegram.

    async def _chiama_gemini_raw(tool_mode=None, json_mode=False, tentativi_rimasti=max_retries):
        generation_config = {
            "temperature": 0.2,
            "maxOutputTokens": 10000,
            "thinkingConfig": {"thinkingLevel": "low"},
        }
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "safetySettings": [
                {"category": c, "threshold": "BLOCK_NONE"} for c in (
                    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
            ],
            "generationConfig": generation_config,
        }

        if json_mode:
            # FASE 2. Niente "tools"/"tool_config" nel payload: con lo schema
            # attivo sarebbero rifiutati dall'API. La cronologia in "contents"
            # continua a contenere le coppie functionCall/functionResponse dei
            # giri di ricerca, ed e' accettata senza problemi -- lo stesso
            # schema (history con function parts, payload senza tools) era
            # gia' usato dal vecchio tentativo di fallback finale.
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = CERVELLO_RESPONSE_SCHEMA
        else:
            # FASE 1. maxOutputTokens piu' basso: qui il modello deve solo
            # formulare una query di ricerca, non il verdetto completo.
            generation_config["maxOutputTokens"] = 2000
            function_calling_config = {"mode": tool_mode}
            if tool_mode == "ANY":
                function_calling_config["allowed_function_names"] = ["cerca_comp_prezzo"]
            payload["tools"] = [{"function_declarations": [CERVELLO_FUNCTION_DECLARATION]}]
            payload["tool_config"] = {"function_calling_config": function_calling_config}

        # Stesso ragionamento di chiama_gemini (vedi commento esteso li'):
        # con un blackout gia' rilevato non si spendono tentativi_rimasti
        # pieni ad ogni round -- si fallisce prima, il round FASE 1 passa
        # direttamente al verdetto (vedi "si passa comunque al verdetto" nel
        # chiamante) invece di aspettare minuti in piu' per round.
        tentativi_effettivi = MAX_RETRIES_GEMINI_IN_BLACKOUT if _gemini_in_blackout() else tentativi_rimasti
        if GEMINI_CASCATA:
            tentativi_effettivi += len(GEMINI_API_KEYS)

        backoff_seconds = 2
        for attempt in range(1, tentativi_effettivi + 1):
            try:
                # Timeout abbassato da 90 a 30s (richiesto dall'utente il
                # 2026-09-22, stesso motivo di chiama_gemini).
                url_usato = _gemini_url_effettivo(api_url)
                modello_usato = _gemini_modello_da_url(url_usato)
                key_usata = _gemini_key_attuale(modello_usato)
                resp = await hc._client_generico.post(
                    url_usato, headers={"x-goog-api-key": key_usata}, json=payload, timeout=30)
                if not resp.is_success:
                    log.warning("Gemini (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                    # Stesso fallback di modello di chiama_gemini, stesso FIX
                    # 2026-09-26: la marcatura di esclusione va sempre eseguita,
                    # anche sull'ultimo tentativo (vedi commento esteso li').
                    modello_cambiato = _gemini_gestisci_modello_non_disponibile(
                        api_url, url_usato, resp.status_code, resp.text)
                    if modello_cambiato and attempt < tentativi_effettivi:
                        continue
                    if _gemini_e_errore_quota_giornaliera(resp.status_code, resp.text):
                        _gemini_segna_key_quota_esaurita(key_usata, modello_usato, _gemini_secondi_retry(resp.text))
                        if (GEMINI_CASCATA and attempt < tentativi_effettivi
                                and _gemini_url_effettivo(api_url) != url_usato):
                            continue   # si scala subito al modello successivo della cascata
                    codici_con_rotazione = {429, 500, 502, 503, 504}
                    if resp.status_code in codici_con_rotazione and attempt < tentativi_effettivi:
                        # Stessa logica di rotazione di chiama_gemini (vedi il
                        # commento esteso li'): 429 e' quota esaurita, non un
                        # rate-limit al minuto; 5xx da FIX 2026-09-21 (log
                        # utente "vedo tempi biblici", blackout 503 di ~9
                        # minuti che ha fatto accumulare minuti di backoff su
                        # piu' chiamate Cervello in sequenza) rotano ANCHE
                        # loro ora, perche' su Google Cloud la capacita' e'
                        # spesso per progetto/key -- se c'e' un'altra key si
                        # passa a quella e si ritenta subito, altrimenti
                        # backoff come prima.
                        if _gemini_prossima_key(modello_usato):
                            continue
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    resp.raise_for_status()
                _gemini_registra_esito(True)
                log.info("GEMINI_USO | cervello | %s", modello_usato)
                return resp.json()
            except Exception:
                if attempt < tentativi_effettivi:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                _gemini_registra_esito(False)
                raise
        _gemini_registra_esito(False)
        raise RuntimeError("tentativi esauriti")

    # ---- FASE 1: giri di ricerca ------------------------------------------
    tool_mode = "ANY" if forza_ricerca else "AUTO"

    for round_idx in range(MAX_ROUNDS_FUNZIONE):
        try:
            data = await _chiama_gemini_raw(tool_mode=tool_mode)
        except Exception as e:
            log.warning("Cervello: fase ricerca fallita al giro %d (%s) -- si passa comunque al verdetto.", round_idx + 1, e)
            break

        candidates = data.get("candidates", [])
        if not candidates:
            log.warning("Cervello: nessun candidate nella fase di ricerca (giro %d).", round_idx + 1)
            break

        costo_totale += costo_gemini_token(data.get("usageMetadata", {}), prezzo_input, prezzo_output)

        parts = candidates[0].get("content", {}).get("parts", []) or []
        function_call = next((p.get("functionCall") for p in parts if p.get("functionCall")), None)

        if not function_call:
            # Il modello non vuole (piu') cercare: ha gia' abbastanza per
            # decidere. Si passa direttamente alla fase di verdetto; il testo
            # eventualmente prodotto qui viene scartato, perche' il verdetto
            # valido e' solo quello strutturato della fase 2.
            break

        query_richiesta = function_call.get("args", {}).get("query", "")
        log.info("Cervello Gemini ha richiesto ricerca mirata (giro %d/%d): '%s'",
                 round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
        risultato_ricerca, mappa_url_query = await cerca_serper_mirata(query_richiesta)
        n_query_extra += 1
        ricerche_extra_raw.append(
            f"\n📍 FONTE: RICERCA ON-DEMAND CERVELLO (Serper google search, query: '{query_richiesta}')\n{risultato_ricerca}"
        )
        if mappa_url_ricerche_extra is not None:
            mappa_url_ricerche_extra.update(mappa_url_query)

        contents.append({"role": "model", "parts": parts})
        contents.append({
            "role": "user",
            "parts": [{
                "functionResponse": {
                    "name": "cerca_comp_prezzo",
                    "response": {"result": risultato_ricerca},
                }
            }]
        })
        tool_mode = "AUTO"  # i giri successivi non sono piu' forzati

    # ---- FASE 2: verdetto strutturato -------------------------------------
    contents.append({"role": "user", "parts": [{"text": ISTRUZIONE_FASE_JSON}]})

    try:
        data = await _chiama_gemini_raw(json_mode=True)
    except Exception as e:
        return None, f"chiamata al verdetto strutturato fallita: {e}", costo_totale, n_query_extra, ricerche_extra_raw

    candidates = data.get("candidates", [])
    if not candidates:
        return None, "risposta Gemini senza candidates nella fase di verdetto", costo_totale, n_query_extra, ricerche_extra_raw

    usage = data.get("usageMetadata", {})
    costo_totale += costo_gemini_token(usage, prezzo_input, prezzo_output)

    parts = candidates[0].get("content", {}).get("parts", []) or []
    testo_json = _estrai_testo_da_parts(parts).strip()
    finish_reason = candidates[0].get("finishReason", "?")

    if not testo_json:
        # Con lo schema attivo un output vuoto ha praticamente una sola
        # causa plausibile: troncamento. A differenza della prosa, un JSON
        # troncato non degrada (non e' "un verdetto un po' corto"), e'
        # inutilizzabile -- quindi va distinto e segnalato come tale invece
        # di finire in un generico "nessuna risposta testuale".
        if finish_reason == "MAX_TOKENS":
            return None, (
                "verdetto troncato: il JSON ha superato maxOutputTokens "
                f"(thinking={usage.get('thoughtsTokenCount', '?')} token). "
                "Se ricapita spesso, la causa piu' probabile e' un array "
                "comp_candidati molto lungo: alzare maxOutputTokens o "
                "accorciare titolo_verbatim nello schema."
            ), costo_totale, n_query_extra, ricerche_extra_raw
        log.warning(
            "Cervello: fase verdetto senza testo -- finishReason=%s, usage=%s, n_parts=%d, safetyRatings=%s",
            finish_reason, json.dumps(usage, ensure_ascii=False)[:300], len(parts),
            candidates[0].get("safetyRatings", "assenti"),
        )
        return None, f"il modello non ha prodotto il JSON del verdetto (finishReason={finish_reason})", costo_totale, n_query_extra, ricerche_extra_raw

    try:
        verdetto = json.loads(testo_json)
    except json.JSONDecodeError as e:
        log.warning("Cervello: JSON non parsabile (finishReason=%s): %s\nTESTO GREZZO: %s",
                    finish_reason, e, testo_json[:1000])
        return None, f"JSON del verdetto non parsabile ({e})", costo_totale, n_query_extra, ricerche_extra_raw

    if not isinstance(verdetto, dict):
        return None, "il JSON del verdetto non e' un oggetto", costo_totale, n_query_extra, ricerche_extra_raw

    return verdetto, None, costo_totale, n_query_extra, ricerche_extra_raw


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

OPENAI_CERVELLO_TOOL = {
    "type": "function",
    "function": {
        "name": CERVELLO_FUNCTION_DECLARATION["name"],
        "description": CERVELLO_FUNCTION_DECLARATION["description"],
        "parameters": CERVELLO_FUNCTION_DECLARATION["parameters"],
    },
}


def costo_openai_token(usage, prezzo_input=PREZZO_CERVELLO_OPENAI_INPUT, prezzo_output=PREZZO_CERVELLO_OPENAI_OUTPUT):
    inp = usage.get("prompt_tokens", 0) or 0
    out = usage.get("completion_tokens", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


OPENAI_RESPONSE_FORMAT_CERVELLO = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdetto_flip",
        "strict": True,
        "schema": CERVELLO_RESPONSE_SCHEMA_OPENAI,
    },
}


async def _chiama_openai_raw(messages, tentativi_rimasti, tools=None, tool_choice=None,
                             response_format=None, max_retries=4):
    payload = {
        "model": OPENAI_MODEL_CERVELLO,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    if response_format is not None:
        payload["response_format"] = response_format

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    backoff_seconds = 2
    for attempt in range(1, tentativi_rimasti + 1):
        try:
            resp = await hc._client_generico.post(
                OPENAI_API_URL_CERVELLO, headers=headers, json=payload, timeout=90)
            if not resp.is_success:
                log.warning("OpenAI (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < tentativi_rimasti:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue
                resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt < tentativi_rimasti:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue
            raise
    raise RuntimeError("tentativi esauriti")


async def chiama_openai_cervello_forzato(system_prompt, user_text, forza_ricerca=True, max_retries=4,
                                         mappa_url_ricerche_extra=None):
    """Equivalente OpenAI del cervello Gemini, stessa firma di ritorno a 5
    elementi per restare intercambiabile via CERVELLO_PROVIDER.

    Differenza tecnica rispetto a Gemini: OpenAI NON ha il vincolo
    "function calling incompatibile con structured output", quindi la
    separazione in due fasi qui non sarebbe obbligatoria. La manteniamo
    comunque identica, per tre motivi concreti: un solo flusso logico da
    ragionare e correggere quando qualcosa va storto in produzione, gli
    stessi log e gli stessi punti di fallimento su entrambi i provider, e
    la certezza che cambiare CERVELLO_PROVIDER non cambi nient'altro che
    il modello interrogato.

    Lo schema passato in response_format e' la traduzione automatica di
    CERVELLO_RESPONSE_SCHEMA fatta da _schema_gemini_to_openai: unica
    fonte di verita', nessun rischio che i due schemi divergano.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    costo_totale = 0.0
    n_query_extra = 0
    ricerche_extra_raw = []

    # ---- FASE 1: giri di ricerca ------------------------------------------
    tool_choice = "required" if forza_ricerca else "auto"

    for round_idx in range(MAX_ROUNDS_FUNZIONE):
        try:
            data = await _chiama_openai_raw(
                messages, tentativi_rimasti=max_retries,
                tools=[OPENAI_CERVELLO_TOOL], tool_choice=tool_choice,
            )
        except Exception as e:
            log.warning("Cervello OpenAI: fase ricerca fallita al giro %d (%s) -- si passa al verdetto.", round_idx + 1, e)
            break

        choices = data.get("choices", [])
        if not choices:
            log.warning("Cervello OpenAI: nessuna choice nella fase di ricerca (giro %d).", round_idx + 1)
            break

        costo_totale += costo_openai_token(data.get("usage", {}))

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break  # il modello ha gia' abbastanza dati: si passa al verdetto

        # OpenAI puo' restituire PIU' tool_calls nello stesso turno (parallel
        # tool calling, attivo di default). Va risposto a OGNUNA: lasciare un
        # tool_call_id senza risposta fa rifiutare l'intera history al giro
        # successivo con HTTP 400 ("did not have response messages"), bug
        # osservato ripetutamente in produzione prima del fix del 2026-09-19.
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for call in tool_calls:
            try:
                query_richiesta = json.loads(call.get("function", {}).get("arguments", "{}")).get("query", "")
            except (json.JSONDecodeError, TypeError):
                query_richiesta = ""
            log.info("Cervello OpenAI ha richiesto ricerca mirata (giro %d/%d): '%s'",
                     round_idx + 1, MAX_ROUNDS_FUNZIONE, query_richiesta)
            risultato_ricerca, mappa_url_query = await cerca_serper_mirata(query_richiesta)
            n_query_extra += 1
            ricerche_extra_raw.append(
                f"\n📍 FONTE: RICERCA ON-DEMAND CERVELLO (Serper google search, query: '{query_richiesta}')\n{risultato_ricerca}"
            )
            if mappa_url_ricerche_extra is not None:
                mappa_url_ricerche_extra.update(mappa_url_query)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": risultato_ricerca,
            })
        tool_choice = "auto"

    # ---- FASE 2: verdetto strutturato -------------------------------------
    messages.append({"role": "user", "content": ISTRUZIONE_FASE_JSON})

    try:
        data = await _chiama_openai_raw(
            messages, tentativi_rimasti=max_retries,
            response_format=OPENAI_RESPONSE_FORMAT_CERVELLO,
        )
    except Exception as e:
        return None, f"chiamata al verdetto strutturato fallita: {e}", costo_totale, n_query_extra, ricerche_extra_raw

    choices = data.get("choices", [])
    if not choices:
        return None, "risposta OpenAI senza choices nella fase di verdetto", costo_totale, n_query_extra, ricerche_extra_raw

    costo_totale += costo_openai_token(data.get("usage", {}))

    msg = choices[0].get("message", {})
    finish_reason = choices[0].get("finish_reason", "?")

    # Un rifiuto esplicito del modello (campo "refusal" di structured output)
    # non e' un JSON malformato: e' il modello che dichiara di non voler
    # rispondere. Va distinto, altrimenti finirebbe come "JSON non parsabile"
    # e si perderebbe il motivo reale.
    if msg.get("refusal"):
        return None, f"il modello ha rifiutato di produrre il verdetto: {msg['refusal']}", costo_totale, n_query_extra, ricerche_extra_raw

    testo_json = (msg.get("content") or "").strip()
    if not testo_json:
        if finish_reason == "length":
            return None, (
                "verdetto troncato: il JSON ha superato max_tokens. Se ricapita, "
                "la causa piu' probabile e' un array comp_candidati molto lungo."
            ), costo_totale, n_query_extra, ricerche_extra_raw
        return None, f"il modello non ha prodotto il JSON del verdetto (finish_reason={finish_reason})", costo_totale, n_query_extra, ricerche_extra_raw

    try:
        verdetto = json.loads(testo_json)
    except json.JSONDecodeError as e:
        log.warning("Cervello OpenAI: JSON non parsabile (finish_reason=%s): %s\nTESTO GREZZO: %s",
                    finish_reason, e, testo_json[:1000])
        return None, f"JSON del verdetto non parsabile ({e})", costo_totale, n_query_extra, ricerche_extra_raw

    if not isinstance(verdetto, dict):
        return None, "il JSON del verdetto non e' un oggetto", costo_totale, n_query_extra, ricerche_extra_raw

    return verdetto, None, costo_totale, n_query_extra, ricerche_extra_raw


# ---------------------------------------------------------------------------
# SERPER RICERCA
# ---------------------------------------------------------------------------

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


# search_comps_ebay_sold_url (URL diretto www.ebay.it/sch/i.html?...&LH_Sold=1)
# RIMOSSA il 2026-09-19: costruiva l'URL per lo scrape diretto della pagina
# eBay, abbandonato dopo conferma che eBay blocca sistematicamente Serper su
# quell'endpoint con la pagina anti-bot "Misura di sicurezza" (vedi
# _serper_batch_query_ebay_sold, che l'ha sostituita passando da una query
# Google invece dello scrape diretto).


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


def _e_errore_crediti_serper(resp):
    if resp.status_code in (400, 401, 402, 403, 429):
        testo_body = (resp.text or "").lower()
        if resp.status_code in (401, 402, 403, 429):
            return True
        if any(k in testo_body for k in ("credit", "insufficient", "balance", "payment", "quota")):
            return True
    return False


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


# Falsi positivi idiomatici: "dress" in "dress shirt"/"dress pants" e' un
# aggettivo (capo elegante), non indica un abito. Senza questa esclusione,
# il filtro categoria "abito" li fa passare per errore.
ESCLUSIONI_FALSI_POSITIVI_CATEGORIA = {
    "abito": ["dress shirt", "dress pants", "dress code", "dress shoes"],
}

# Rumore generico da scartare sempre, indipendentemente dalla categoria:
# taglie bambino (non comparabili a un capo adulto), collab diffusion
# economiche (es. "for Target"), e frasi che indicano che il brand e' citato
# solo come RIFERIMENTO/ispirazione, non come brand reale del prodotto.
RUMORE_GENERICO_COMP = [
    # taglie/target bambino
    "girls age", "boys age", "kids size", "toddler", "baby size",
    "girl's", "girls'", "girls ", " girls", "boy's", "boys'", "boys ", " boys",
    "kids ", " kids", "kids logo", "kids cotton",
    "years old", "age 4", "age 6", "age 8", "age 10", "age 12",
    # collab diffusion economiche
    "for target", "x target", "for h&m", "x h&m",
    # brand citato solo come riferimento/ispirazione, non prodotto reale
    "similar to", "similar graphic", "similar style to", "inspired by",
    "reference to", "in the style of", "style of", "style inspired",
    "homage to", "tribute to",
]

# Per ogni brand monitorato, le sue sottolinee/collaborazioni da escludere
# SEMPRE dai comp quando si valuta la linea principale -- condividono il
# nome brand nei titoli ma appartengono a fasce di prezzo completamente
# diverse (es. Y-3 e' streetwear di massa via Adidas, non Yohji Yamamoto
# mainline; See by Chloe' e' diffusion, non Chloe' mainline).
BRAND_SOTTOLINEE_DA_ESCLUDERE = {
    "chloé": ["see by chloé", "see by chloe"],
    "chloe": ["see by chloé", "see by chloe"],
    "yohji yamamoto": ["y-3", "y3 ", " y3", "y-3 adidas", "adidas y-3"],
    "alexander mcqueen": ["mcq alexander mcqueen", " mcq "],
    "maison margiela": ["mm6"],
    "margiela": ["mm6"],
    "missoni": ["missoni sport", "missoni home", "missoni mare", "missoni kids", "missoni junior"],
    "stella mccartney": ["adidas by stella mccartney", "stella mccartney for adidas", "adidas x stella mccartney", "pour adidas"],
    "raf simons": ["fred perry x raf simons", "raf simons x fred perry", "calvin klein x raf simons"],
    # Aggiunti: stessa logica, brand delle watch che hanno sottolinee/collab
    # a fascia di prezzo molto piu' bassa e che contaminano i comp.
    "helmut lang": ["helmut lang jeans"],
    "issey miyake": ["me issey miyake", "haat", "bao bao"],
    "max mara": ["weekend max mara", "max mara weekend", "max mara studio", "sportmax", "marella", "pennyblack", "max&co", "max & co"],
    "jean paul gaultier": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "jpg": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "arc'teryx": ["arc'teryx lt", "arcteryx kids"],
    "moschino": ["love moschino", "moschino jeans", "boutique moschino"],
    "armani": ["emporio armani", "armani exchange", "armani jeans", "a|x"],
    "versace": ["versace jeans", "versus versace", "versace collection"],
    "vivienne westwood": ["vivienne westwood anglomania kids"],
}


def _filtra_comp_per_brand_sottolinee(testo_comp, brand):
    """Esclude dai comp le righe che appartengono a una sottolinea/collab
    nota del brand (vedi BRAND_SOTTOLINEE_DA_ESCLUDERE), che altrimenti
    contamina la stima con prezzi di una fascia di mercato completamente
    diversa pur condividendo il nome brand nel titolo."""
    if not testo_comp or not brand:
        return testo_comp

    sottolinee = BRAND_SOTTOLINEE_DA_ESCLUDERE.get(brand.strip().lower(), [])
    if not sottolinee:
        return testo_comp

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            if any(sub in riga_lower for sub in sottolinee):
                scartate += 1
                continue
        righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_brand_sottolinee: scartate %d righe di sottolinea/collab per brand '%s'.", scartate, brand)

    return "\n".join(righe_filtrate)


# Valori di linea_o_era che NON sono un'etichetta letterale spendibile come
# testo di ricerca (una descrizione di epoca/generica, non qualcosa che
# compare scritto su un'etichetta o in un titolo Vinted) -- esclusi
# dall'arricchimento della ricerca comp sotto per non aggiungere rumore.
LINEA_O_ERA_NON_UTILI_PER_RICERCA = {"mainline", "non determinabile", "non_determinabile"}


def _e_linea_o_era_utile_per_ricerca(linea_o_era):
    """True se linea_o_era e' un'etichetta letterale spendibile in una query
    di ricerca (es. "JEAN'S PAUL GAULTIER", "JPG.JEAN'S", "Veilance", "Linea
    10"), False se e' una descrizione di era/epoca generica (es. "Era Lang
    1986-2005") o un valore segnaposto ("mainline", "non determinabile") che
    aggiungerebbe solo rumore invece di aiutare la ricerca."""
    if not linea_o_era or not isinstance(linea_o_era, str):
        return False
    testo = linea_o_era.strip()
    if not testo or testo.lower() in LINEA_O_ERA_NON_UTILI_PER_RICERCA:
        return False
    # Una descrizione di era contiene quasi sempre un anno a 4 cifre
    # ("1986-2005", "post-2006", "pre-2012"): utile per il Cervello come
    # informazione (resta in linea_o_era_rilevata), ma inutile come testo di
    # ricerca letterale -- nessuna etichetta reale scrive "post-2006" su un
    # capo, quindi cercarlo alla lettera non trova nulla.
    if re.search(r"\b(19|20)\d{2}\b", testo):
        return False
    return True


def _arricchisci_brand_per_ricerca(brand_annuncio, occhio_json):
    """Brand/etichetta da usare per la ricerca comp (Serper), arricchito con
    la sottolinea o la linea/etichetta specifica lette dall'Occhio quando
    presenti e utili come testo di ricerca. Richiesto dall'utente il
    2026-09-22 ("assicurati che quando la linea e' M Missoni o Jean's Paul
    Gaultier il modello usi quella linea per trovare comp -- cosi' per tutte
    le sottolinee"): generalizza due casi gia' osservati in produzione,
    entrambi con lo stesso sintomo (comp della linea sbagliata, spesso piu'
    cari, trattati come validi perche' la ricerca usava solo il brand madre).

    1. Sottolinee con un nome diverso dal brand principale (Weekend Max
       Mara, M Missoni, MM6...): gia' coperte da nome_sottolinea quando
       relazione_brand == "sottolinea_stessa_maison" (fix del 2026-09-20).
    2. Linee/etichette dello STESSO brand nominale ma con un testo di
       etichetta specifico da cercare alla lettera per non mischiare fasce
       di prezzo diverse (caso reale JPG: "JEAN'S PAUL GAULTIER" con
       apostrofo vs "JPG.JEAN'S" sono due diffusion diverse, ma "Jean Paul
       Gaultier" da solo non fa questa distinzione nella ricerca comp):
       coperte da linea_o_era, indipendentemente da relazione_brand, filtrato
       da _e_linea_o_era_utile_per_ricerca per escludere descrizioni di era
       generiche.

    Il campo brand del listing riflette quasi sempre solo il brand madre
    scelto dal venditore, mai la sottolinea/linea specifica -- senza questo
    arricchimento quel testo e' l'unico usato per la ricerca comp.
    """
    if not occhio_json:
        return brand_annuncio

    brand_annuncio_norm = (brand_annuncio or "").strip().lower()
    etichette_da_aggiungere = []

    if occhio_json.get("relazione_brand") == "sottolinea_stessa_maison":
        nome_sottolinea = str(occhio_json.get("nome_sottolinea") or "").strip()
        if nome_sottolinea and nome_sottolinea.lower() not in brand_annuncio_norm:
            etichette_da_aggiungere.append(nome_sottolinea)

    linea_o_era = str(occhio_json.get("linea_o_era") or "").strip()
    if (
        _e_linea_o_era_utile_per_ricerca(linea_o_era)
        and linea_o_era.lower() not in brand_annuncio_norm
        and linea_o_era.lower() not in (e.lower() for e in etichette_da_aggiungere)
    ):
        etichette_da_aggiungere.append(linea_o_era)

    if not etichette_da_aggiungere:
        return brand_annuncio

    brand_arricchito = " ".join(etichette_da_aggiungere + [brand_annuncio or ""]).strip()
    log.info(
        "process_listing: brand arricchito per la ricerca comp: '%s' -> '%s' "
        "(sottolinea/linea letta dall'Occhio sull'etichetta).",
        brand_annuncio, brand_arricchito,
    )
    return brand_arricchito


def _filtra_comp_per_categoria(testo_comp, categoria):
    """Filtra le righe comp che non contengono nessuna keyword della
    categoria rilevata (in nessuna lingua tra quelle coperte da
    CATEGORIA_KEYWORDS), scartando anche falsi positivi idiomatici e
    rumore generico (taglie bambino, collab diffusion economiche).
    Necessario perche' eBay/Vestiaire a volte restituiscono risultati
    "correlati al brand" fuori categoria nonostante la query includa la
    categoria -- il motore di ricerca della fonte non la rispetta
    rigidamente, quindi il filtro va fatto sui risultati."""
    if not testo_comp or not categoria:
        return testo_comp

    keywords = CATEGORIA_KEYWORDS.get(categoria, [])
    if not keywords:
        return testo_comp

    esclusioni = ESCLUSIONI_FALSI_POSITIVI_CATEGORIA.get(categoria, [])

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            e_rumore = any(kw in riga_lower for kw in RUMORE_GENERICO_COMP)
            e_falso_positivo = any(kw in riga_lower for kw in esclusioni)
            match_categoria = any(kw in riga_lower for kw in keywords)
            if match_categoria and not e_rumore and not e_falso_positivo:
                righe_filtrate.append(riga)
            else:
                scartate += 1
        else:
            righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_categoria: scartate %d righe fuori categoria/rumore '%s'.", scartate, categoria)

    return "\n".join(righe_filtrate)


def _rimuovi_comp_autoreferenziale(testo_comp_vinted, titolo_annuncio):
    """Filtra dai comp Vinted l'annuncio stesso in valutazione, che spesso
    compare tra i risultati di ricerca (stesso titolo) senza essere un dato
    di mercato indipendente -- rischia di essere scambiato per un comp
    reale invece che per l'oggetto stesso."""
    if not testo_comp_vinted or not titolo_annuncio:
        return testo_comp_vinted

    titolo_norm = _normalizza_titolo_per_dedup(html.unescape(titolo_annuncio))
    righe_filtrate = []
    for riga in testo_comp_vinted.split("\n"):
        m = re.match(r"-\s*(.+?)\s*—\s*€", riga)
        if m and _normalizza_titolo_per_dedup(html.unescape(m.group(1))) == titolo_norm:
            continue
        righe_filtrate.append(riga)
    return "\n".join(righe_filtrate)


def _estrai_articoli_da_alt_vinted(html_content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dagli attributi alt= delle immagini
    prodotto nell'HTML grezzo di una pagina catalogo Vinted (vedi
    _RE_ALT_PRODOTTO_VINTED per il pattern esatto). Stesso formato di
    output di _estrai_articoli_vinted ('- titolo — €prezzo', una riga per
    articolo) cosi' il resto della pipeline (filtro autoreferenziale,
    categoria, sottolinea brand) funziona invariato su entrambe le fonti."""
    righe, visti = [], set()
    for m in _RE_ALT_PRODOTTO_VINTED.finditer(html_content or ""):
        titolo = html.unescape(m.group(1)).strip()
        prezzo = m.group(2).replace(",", ".")
        if not titolo or len(titolo) < 3:
            continue
        chiave = (titolo[:60].lower(), prezzo)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe.append(f"- {titolo} — €{prezzo}")
        if len(righe) >= max_articoli:
            break
    if not righe:
        return "  Nessun articolo trovato (pattern alt= senza match -- possibile cambio di markup Vinted, da rivedere)."
    return "\n".join(righe)


def _estrai_mappa_url_comp_vinted(html_content):
    """Costruisce {(titolo_normalizzato, prezzo_2f): url} dallo stesso HTML
    grezzo passato a _estrai_articoli_da_alt_vinted (vedi
    _RE_PRODOTTO_VINTED_CON_ID), cosi' il rendering finale del messaggio puo'
    riattaccare un link cliccabile al comp che il Cervello ha ricopiato nel
    suo JSON -- un semplice dict.get() su titolo+prezzo, senza fuzzy
    matching che rischierebbe di agganciare il comp sbagliato. Il prezzo e'
    la chiave nello stesso formato ".2f" prodotto da calcola_verdetto sui
    comp validati (vedi comp['prezzo_eur'] = round(prezzo, 2))."""
    mappa = {}
    for m in _RE_PRODOTTO_VINTED_CON_ID.finditer(html_content or ""):
        item_id, titolo_grezzo, prezzo_grezzo = m.group(1), m.group(2), m.group(3)
        titolo = html.unescape(titolo_grezzo).strip()
        if not titolo or len(titolo) < 3:
            continue
        try:
            prezzo_norm = f"{float(prezzo_grezzo.replace(',', '.')):.2f}"
        except ValueError:
            continue
        chiave = (_normalizza_titolo_per_link(titolo), prezzo_norm)
        mappa.setdefault(chiave, f"https://www.vinted.it/items/{item_id}")
    return mappa


async def _scrape_catalogo_vinted_diretto(url):
    """Scarica la pagina catalogo search_by_image_id con il client HTTP GIA'
    autenticato del bot (stesso pool/proxy usato per annunci e profili
    venditore), invece di passare per Serper. Aggiunta il 2026-09-20 dopo
    aver isolato empiricamente (con l'utente, via DevTools) che Vinted
    restituisce contenuto DIVERSO a seconda di chi fa la richiesta: il
    browser dell'utente (anche incognito, senza login) riceve la vera
    griglia filtrata per search_by_image_id renderizzata server-side (SSR,
    confermato: i titoli sono gia' nell'HTML grezzo via view-source, non
    serve JS), mentre Serper riceveva sistematicamente lo stesso mazzo
    generico di articoli del brand (identico su search_by_image_id diversi
    per lo stesso brand) -- quasi certamente un fallback anti-bot (Datadome,
    gia' noto per altri endpoint Vinted) che riconosce il fingerprint di
    Serper e gli serve una versione non personalizzata invece di bloccare.

    Estrazione via _estrai_articoli_da_alt_vinted (regex su alt=, vedi
    sopra) invece che via markdown generico: un primo tentativo con
    markdownify (HTML->markdown) metteva titolo e prezzo su righe separate
    quando erano in tag diversi, rompendo il parser esistente che li vuole
    sulla stessa riga -- scartato prima del deploy.

    Ritorna (testo, ok, mappa_url) invece del vecchio (testo, ok): la mappa
    (vedi _estrai_mappa_url_comp_vinted) e' costruita dallo stesso HTML gia'
    scaricato qui, a costo zero di richieste aggiuntive, per rimappare i
    link cliccabili al rendering finale (Punto 3, 2026-09-25)."""
    resp = await _vinted_get_con_retry(url, timeout=15, max_retries=2)
    if resp is None:
        return "  Scrape diretto Vinted fallito (nessuna risposta dopo i retry).", False, {}
    return _estrai_articoli_da_alt_vinted(resp.text), True, _estrai_mappa_url_comp_vinted(resp.text)


# Timeout dedicati alla ricerca testuale Vinted con fallback (2026-09-25):
# lo scrape diretto ha un budget corto, cosi' se Vinted e' lento o risponde
# 403 resta tempo per il tentativo Serper dentro il timeout complessivo della
# fonte (TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI in search_comps_completo).
TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI = 8
TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI = 25
MARKER_NESSUN_ARTICOLO_VINTED = "Nessun articolo trovato"


async def _cerca_vinted_testo_diretto_con_fallback_serper(url):
    """Ricerca comp testuale su Vinted: PRIMA lo scrape diretto della pagina
    catalogo (stesso client/proxy e stesso parser su alt= gia' usati per la
    ricerca visuale, vedi _scrape_catalogo_vinted_diretto), POI Serper solo
    se il diretto fallisce o non estrae nessun articolo.

    Aggiunta il 2026-09-25 su richiesta dell'utente per risparmiare crediti
    Serper sulla ricerca testuale (una chiamata a ogni annuncio, piu' una
    per il sarto quando c'e'). Serper resta come rete di sicurezza e non
    viene tolto: lo scrape diretto aggiunge 1-2 richieste a Vinted per
    annuncio dallo stesso IP, e il bot ha gia' preso 403 da Vinted dopo molte
    ore di attivita' (vedi PAUSA_MINIMA_TRA_RICHIESTE_VINTED_SECONDI). Se
    succede, il fallback copre l'annuncio invece di lasciarlo senza comp.

    Stesso contratto di ritorno delle altre fonti: (testo, ok, mappa_url),
    con il testo nel formato '- titolo — €prezzo' una riga per articolo.
    mappa_url (aggiunta il 2026-09-25, vedi _estrai_mappa_url_comp_vinted)
    e' popolata SOLO sul ramo di scrape diretto: l'HTML che arriva da
    Serper (_serper_scrape_page_diretto) e' gia' passato per un'estrazione
    di contenuto che non preserva i data-testid, quindi su quel ramo il
    dizionario resta vuoto -- niente link per quei comp, non un errore."""
    motivo_fallback = None
    try:
        resp = await asyncio.wait_for(
            _vinted_get_con_retry(url, timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI, max_retries=1),
            timeout=TIMEOUT_SCRAPE_DIRETTO_VINTED_TESTO_SECONDI + 4,
        )
    except asyncio.TimeoutError:
        resp = None
        motivo_fallback = "timeout scrape diretto"
    if resp is not None:
        testo = _estrai_articoli_da_alt_vinted(resp.text)
        # Etichetta proxy (2026-09-27, vedi _vinted_get_con_retry) anche qui:
        # stessa logica del catalogo che sopra, applicata al lato testuale
        # "senza articoli estratti" -- e' l'ALTRO caso applicativo (oltre alle
        # foto) in cui Vinted risponde 200 ma con una pagina non utilizzabile.
        etichetta_proxy = getattr(resp, "_proxy_etichetta", "?")
        if MARKER_NESSUN_ARTICOLO_VINTED not in testo:
            log.info("Comp Vinted testo: scrape diretto OK (%d articoli, proxy=%s), Serper non usato -- %s",
                     testo.count("\n") + 1, etichetta_proxy, url)
            return testo, True, _estrai_mappa_url_comp_vinted(resp.text)
        motivo_fallback = (
            f"scrape diretto senza articoli estratti (proxy={etichetta_proxy}, "
            f"status {resp.status_code}, len {len(resp.text)})"
        )
    elif motivo_fallback is None:
        motivo_fallback = "scrape diretto fallito (nessuna risposta)"

    log.info("Comp Vinted testo: %s -- uso Serper come riserva per %s", motivo_fallback, url)
    testo_serper, ok_serper = await _serper_scrape_page_diretto("VINTED", url)
    if ok_serper:
        return testo_serper, True, {}
    return f"  {motivo_fallback}; fallback Serper anch'esso fallito: {testo_serper.strip()}", False, {}


async def _recupera_comp_visuali_vinted(item_id, photo_id, brand):
    """Wrapper per la fonte visuale, pensato per essere sottomesso come UN
    solo future nello stesso executor delle altre 3 fonti (vedi
    search_comps_completo) cosi' la risoluzione dell'ID (chiamata di rete
    verso Vinted, non istantanea) corre IN PARALLELO alle altre ricerche
    invece di bloccarne l'avvio. Fa due passi in sequenza al suo interno
    (risolvi ID -> scrape del catalogo con quell'ID), ma dal punto di vista
    dell'executor e' un solo task con lo stesso contratto di ritorno
    (testo, ok, mappa_url) degli altri (mappa_url aggiunta il 2026-09-25,
    vedi _estrai_mappa_url_comp_vinted). ok=False (non un'eccezione) quando
    manca un ingrediente o la risoluzione fallisce, cosi' il chiamante lo
    tratta come fonte assente senza differenziare i log dalle altre query
    fallite.

    Scrape diretto (non Serper) dal 2026-09-20: vedi docstring di
    _scrape_catalogo_vinted_diretto per il perche'."""
    url = await build_vinted_visual_search_url(item_id, photo_id, brand)
    if not url:
        log.info(
            "_recupera_comp_visuali_vinted: fonte non disponibile per item_id=%s "
            "(photo_id/brand mancante o risoluzione ID fallita).", item_id,
        )
        return "  Fonte non disponibile (photo_id/brand mancante o risoluzione ID falsa).", False, {}
    testo, ok, mappa_url = await _scrape_catalogo_vinted_diretto(url)
    log.info(
        "_recupera_comp_visuali_vinted: scrape catalogo grezzo per item_id=%s ok=%s -> %r",
        item_id, ok, testo,
    )
    return testo, ok, mappa_url


# Cache dei venduti Resellbot (richiesto dall'utente il 2026-10-03): l'analisi del 2026-10-02 ha mostrato
# Resellbot in errore 429 decine di volte da sera, con il bot costretto al fallback Google (meno preciso,
# nessun URL). I prezzi venduti per brand+categoria cambiano lentamente: si riusano per 24h (meno chiamate,
# meno 429) e, se Resellbot e' bloccato, fino a 72h prima di ripiegare su Google.
SOLD_CACHE_FRESCA_SECONDI = 24 * 3600
SOLD_CACHE_STALE_SECONDI = 72 * 3600
SOLD_CACHE_MAX_VOCI = 400
_sold_cache = {}


def _sold_cache_chiave(brand, categoria, material_per_ricerca, dettaglio_distintivo):
    return tuple((str(x or "")).strip().lower() for x in (brand, categoria, material_per_ricerca, dettaglio_distintivo))


def _sold_cache_leggi(chiave, max_eta_secondi):
    voce = _sold_cache.get(chiave)
    if voce and time.time() - voce[0] <= max_eta_secondi:
        return voce[1], voce[2]
    return None


def _sold_cache_scrivi(chiave, testo, mappa_url):
    if len(_sold_cache) >= SOLD_CACHE_MAX_VOCI:
        for k in sorted(_sold_cache, key=lambda k: _sold_cache[k][0])[:SOLD_CACHE_MAX_VOCI // 4]:
            _sold_cache.pop(k, None)
    _sold_cache[chiave] = (time.time(), testo, mappa_url)


async def _cerca_ebay_sold_con_fallback(brand, categoria, material_per_ricerca=None, dettaglio_distintivo=None):
    """Wrapper per l'executor: prova prima Resellbot (dati di vendita
    confermati, veri, vedi _cerca_ebay_sold_via_resellbot), e solo se fallisce
    (bloccato, rate-limited, errore di rete, o semplicemente 'nessun venduto
    trovato' con ok=True viene comunque accettato cosi' com'e' -- il fallback
    scatta solo su ok=False) prova la query Google di riserva. Tenute
    sequenziali (non in parallelo) per non raddoppiare le chiamate quando la
    prima fonte funziona, che e' il caso comune.

    material_per_ricerca (aggiunto il 2026-09-19) e dettaglio_distintivo
    (aggiunto il 2026-09-25, vedi occhio_schema.dettaglio_distintivo_ricerca)
    vengono inoltrati a entrambe le fonti per restringere la query -- vedi
    docstring di _cerca_ebay_sold_via_resellbot per come le varianti vengono
    combinate in una sola chiamata a Resellbot.

    Ritorna (testo, ok, mappa_url) dal 2026-09-25: mappa_url e' popolata solo
    sul ramo Resellbot (fonte primaria), vuota sul ramo fallback Google."""
    chiave_cache = _sold_cache_chiave(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    in_cache = _sold_cache_leggi(chiave_cache, SOLD_CACHE_FRESCA_SECONDI)
    if in_cache:
        return in_cache[0], True, in_cache[1]
    testo, ok, mappa_url = await _cerca_ebay_sold_via_resellbot(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    if ok:
        _sold_cache_scrivi(chiave_cache, testo, mappa_url)
        return testo, ok, mappa_url
    log.info("_cerca_ebay_sold_con_fallback: Resellbot fallito (%s), tento fallback Google.", testo)
    vecchio = _sold_cache_leggi(chiave_cache, SOLD_CACHE_STALE_SECONDI)
    if vecchio:
        log.info("_cerca_ebay_sold_con_fallback: uso i venduti in cache (piu' vecchi di %dh) al posto del fallback Google.",
                 SOLD_CACHE_FRESCA_SECONDI // 3600)
        return vecchio[0] + "\n(Nota: Resellbot non raggiungibile, questi venduti arrivano dalla cache di ore fa.)", True, vecchio[1]
    testo_fallback, ok_fallback = await _serper_batch_query_ebay_sold(brand, categoria, material_per_ricerca, dettaglio_distintivo)
    if ok_fallback:
        # Nessuna mappa_url dal fallback Google (stesso limite del fallback
        # Serper per Vinted, vedi _cerca_vinted_testo_diretto_con_fallback_serper):
        # gli snippet Google non danno un URL diretto all'annuncio abbastanza
        # affidabile per il lookup titolo+prezzo, quindi niente link Punto 3
        # per i comp arrivati da questo ramo.
        return f"{testo_fallback}\n(Nota: fonte primaria Resellbot fallita, questi risultati vengono da Google/eBay.)", True, {}
    return f"{testo} | fallback Google anch'esso fallito: {testo_fallback}", False, {}


# ---------------------------------------------------------------------------
# VERIFICA CODICI PRODOTTO SU REDDIT (aggiunto 2026-09-26, richiesto dall'utente)
# ---------------------------------------------------------------------------
# I contraffattori spesso riusano lo stesso codice prodotto/etichetta su capi
# diversi (altro modello, altro colore, a volte altro brand) perche' e' piu'
# comodo stampare un lotto di etichette identiche che farne una diversa per
# ogni pezzo. Se il codice che l'Occhio ha letto sull'etichetta compare online
# associato a un capo VISIBILMENTE diverso (altro brand noto), e' un segnale
# forte di contraffazione che oggi il pipeline non controlla affatto.
#
# Fonte scelta: ricerca Reddit, non Google/Serper. Motivo (vedi conversazione
# 2026-09-26): l'utente vuole questa parte a costo zero per sempre, e nel
# 2026 le API di ricerca web gratuite sono sparite (Google Custom Search ha
# chiuso il livello gratuito ai nuovi utenti a gennaio 2026, Brave Search ha
# eliminato il suo). Reddit invece resta gratis per uso personale non
# commerciale: 100 query/minuto via OAuth "application only"
# (grant_type=client_credentials), che NON richiede mai la password
# dell'account Reddit, solo client_id/client_secret di un'app di tipo
# "script". Ricerca su TUTTO Reddit, nessun subreddit fisso: restringere a
# pochi subreddit scelti a mano rischierebbe di perdere la discussione giusta
# finita altrove (vedi conversazione, l'utente ha chiesto esplicitamente se
# fosse necessario sceglierli -- non lo e').
#
# Se REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET non sono configurate su Railway,
# tutta questa sezione si disattiva da sola: REDDIT_ABILITATO=False,
# verifica_codici_prodotto_reddit ritorna subito stringa vuota, zero chiamate
# di rete, il resto del bot funziona esattamente come prima.
REDDIT_USER_AGENT = f"python:vinted-flip-oracle-codecheck:v1.0 (by /u/{REDDIT_USERNAME})"
REDDIT_ABILITATO = bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)

_reddit_token_cache = {"token": None, "scadenza": 0.0}

# Cache persistente su Volume (stesso pattern di TOKEN_FILE piu' sopra per i
# token Vinted): un codice gia' verificato non viene mai ricercato una
# seconda volta, ne' dopo un riavvio. Tiene il bot ben sotto le 100 query/min
# concesse gratis e velocizza i codici che ricorrono spesso (stesso lotto di
# contraffazioni rivenduto da piu' venditori).
CODICI_REDDIT_CACHE_FILE = "/data/codici_reddit_cache.json"
_codici_reddit_cache = {}
if os.path.exists(CODICI_REDDIT_CACHE_FILE):
    try:
        with open(CODICI_REDDIT_CACHE_FILE, "r") as f:
            _codici_reddit_cache = json.load(f)
    except Exception as e:
        log.warning("Impossibile leggere %s (probabilmente non esiste ancora): %s", CODICI_REDDIT_CACHE_FILE, e)


def _salva_cache_codici_reddit():
    try:
        os.makedirs(os.path.dirname(CODICI_REDDIT_CACHE_FILE), exist_ok=True)
        with open(CODICI_REDDIT_CACHE_FILE, "w") as f:
            json.dump(_codici_reddit_cache, f)
    except Exception as e:
        log.warning("Impossibile scrivere %s: %s", CODICI_REDDIT_CACHE_FILE, e)


async def _reddit_ottieni_token():
    """Token OAuth 'application only': sola lettura, non serve mai la
    password dell'account Reddit. Valido 1h (di solito), rigenerato solo
    quando serve, con 60s di margine per non usarne uno che scade a meta'
    di una richiesta in corso."""
    if _reddit_token_cache["token"] and time.time() < _reddit_token_cache["scadenza"] - 60:
        return _reddit_token_cache["token"]
    resp = await hc._client_generico.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
        headers={"User-Agent": REDDIT_USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    dati = resp.json()
    _reddit_token_cache["token"] = dati["access_token"]
    _reddit_token_cache["scadenza"] = time.time() + dati.get("expires_in", 3600)
    return _reddit_token_cache["token"]


def _estrai_codici_prodotto_da_occhio(occhio_json):
    """Codici prodotto/etichetta letti dall'Occhio (etichette[].tipo ==
    'codice_prodotto'), filtrati per lunghezza minima e leggibilita' -- un
    codice illeggibile o troppo corto produrrebbe solo rumore in ricerca.
    Al massimo 2 per annuncio, per restare leggeri (in parallelo alla
    ricerca comp, non deve mai diventare lui il collo di bottiglia)."""
    if not occhio_json:
        return []
    etichette = occhio_json.get("etichette") or []
    codici = []
    for e in etichette:
        if e.get("tipo") != "codice_prodotto":
            continue
        if e.get("leggibilita") == "illeggibile":
            continue
        testo = str(e.get("testo_verbatim") or "").strip()
        testo_pulito = re.sub(r"\[.*?\]", "", testo).strip()
        if len(testo_pulito) < 4:
            continue
        if testo_pulito not in codici:
            codici.append(testo_pulito)
    return codici[:2]


# Brand di lusso comuni, usati per rilevare quando un codice compare online
# insieme a un brand DIVERSO dal nostro -- il segnale concreto di "codice
# riciclato su capi diversi". Lista euristica, non esaustiva di proposito:
# aiuta a beccare i casi piu' comuni, non deve essere mantenuta completa.
_BRAND_NOTI_PER_INCROCIO_REDDIT = [
    "gucci", "prada", "chanel", "louis vuitton", "dior", "miu miu", "loewe",
    "balenciaga", "burberry", "fendi", "versace", "valentino", "bottega veneta",
    "saint laurent", "ysl", "brunello cucinelli", "loro piana", "max mara",
    "missoni", "jil sander", "rick owens", "moncler", "stone island",
    "comme des garcons", "issey miyake", "margiela",
]


def _titoli_menzionano_altro_brand_reddit(testi, brand_nostro):
    """True/insieme se tra i risultati Reddit compare un brand noto DIVERSO
    dal nostro accanto al codice cercato. Segnala il caso piu' grossolano
    (codice riciclato tra brand diversi)."""
    brand_nostro_norm = (brand_nostro or "").strip().lower()
    trovati = set()
    for t in testi:
        tl = t.lower()
        for b in _BRAND_NOTI_PER_INCROCIO_REDDIT:
            if b in tl and b not in brand_nostro_norm and brand_nostro_norm not in b:
                trovati.add(b)
    return trovati


# Riusa la stessa mappa IT->EN gia' usata per le query di ricerca comp
# (CATEGORIA_TERMINE_EN, vedi piu' sopra): serve a riconoscere quando un
# risultato Reddit parla di un capo di categoria DIVERSA dalla nostra pur
# citando lo stesso codice E lo stesso brand -- il caso piu' subdolo e piu'
# comune (richiesto esplicitamente dall'utente il 2026-09-26): i
# contraffattori di solito NON usano un codice di un altro brand (troppo
# facile da beccare), usano un codice nel formato giusto per IL brand ma
# preso da un lotto/prodotto diverso (es. lo stesso codice stampato sia su
# una borsa che su un maglione).
def _titoli_menzionano_categoria_diversa_reddit(testi, categoria_en_nostra):
    """Insieme di categorie (in inglese) DIVERSE dalla nostra trovate nei
    risultati Reddit insieme al codice. Richiede categoria_en_nostra (gia'
    tradotta) per sapere quale escludere dal confronto."""
    if not categoria_en_nostra:
        return set()
    categoria_en_nostra = categoria_en_nostra.lower()
    trovate = set()
    for t in testi:
        tl = t.lower()
        for cat_en in set(CATEGORIA_TERMINE_EN.values()):
            if cat_en == categoria_en_nostra:
                continue
            if re.search(r"\b" + re.escape(cat_en) + r"\b", tl):
                trovate.add(cat_en)
    return trovate


async def _reddit_verifica_codice(codice, brand, categoria_en=None):
    """Cerca '"codice" brand' su tutto Reddit. Ritorna una riga di testo
    pronta per il prompt del Cervello, o None se non c'e' niente da
    segnalare (nessun risultato -- il caso piu' comune: e' un esito
    neutro, NON va spacciato per una conferma di autenticita', quindi in
    quel caso non si aggiunge nulla al prompt piuttosto che scrivere un
    falso rassicurante).

    Due controlli distinti, non uno solo (aggiunto il 2026-09-26 su
    richiesta esplicita dell'utente): il codice compare con un BRAND
    diverso (grossolano, raro) o con la stessa marca ma una CATEGORIA di
    prodotto diversa (il caso vero: codice in formato coerente col brand ma
    riciclato da un altro lotto/prodotto). Il secondo e' il controllo che
    conta davvero, il primo resta come rete di sicurezza per il caso
    limite."""
    chiave = f"{codice.lower()}|{(brand or '').lower()}|{(categoria_en or '').lower()}"
    if chiave in _codici_reddit_cache:
        return _codici_reddit_cache[chiave]

    risultato = None
    try:
        token = await _reddit_ottieni_token()
        resp = await hc._client_generico.get(
            "https://oauth.reddit.com/search",
            params={"q": f"\"{codice}\" {brand}", "sort": "relevance", "limit": 10},
            headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
        testi = []
        link_esempio = None
        for p in posts:
            d = p.get("data", {})
            titolo = d.get("title", "")
            corpo = (d.get("selftext", "") or "")[:300]
            if codice.lower() in (titolo + " " + corpo).lower():
                testi.append(f"{titolo} {corpo}")
                if not link_esempio:
                    link_esempio = f"https://reddit.com{d.get('permalink', '')}"
        if not testi:
            risultato = None
        else:
            altri_brand = _titoli_menzionano_altro_brand_reddit(testi, brand)
            altre_categorie = _titoli_menzionano_categoria_diversa_reddit(testi, categoria_en)
            if altri_brand or altre_categorie:
                pezzi = []
                if altre_categorie:
                    pezzi.append(
                        f"su un capo di categoria diversa ({', '.join(sorted(altre_categorie))} "
                        f"invece di {categoria_en})"
                    )
                if altri_brand:
                    pezzi.append(f"anche su un altro brand ({', '.join(sorted(altri_brand))})")
                risultato = (
                    f"[VERIFICA CODICE '{codice}' SU REDDIT] Lo stesso codice, formato coerente "
                    f"col brand dichiarato '{brand}', compare online " + " e ".join(pezzi) +
                    f" -- probabile codice riciclato da contraffattori, NON e' una prova che il "
                    f"codice sia sbagliato per formato ma che e' condiviso tra prodotti diversi. "
                    f"Fonte: {link_esempio}"
                )
            else:
                risultato = (
                    f"[VERIFICA CODICE '{codice}' SU REDDIT] {len(testi)} menzione/i trovate, "
                    f"nessuna su un brand o una categoria diversi da '{brand}'"
                    + (f"/{categoria_en}" if categoria_en else "") +
                    ". Non e' una conferma di autenticita', solo l'assenza del segnale di "
                    "allarme piu' comune."
                )
    except Exception as e:
        log.warning("Verifica codice Reddit fallita per '%s': %s", codice, e)
        risultato = None  # un errore di rete non deve MAI bloccare la pipeline

    _codici_reddit_cache[chiave] = risultato
    _salva_cache_codici_reddit()
    return risultato


async def verifica_codici_prodotto_reddit(occhio_json, brand, categoria_per_ricerca=None):
    """Punto d'ingresso da process_listing. Va lanciata in parallelo alla
    ricerca comp (asyncio.gather nel chiamante), cosi' non aggiunge secondi
    alla pipeline. Ritorna una stringa da accodare a output_occhi, o stringa
    vuota se non c'e' niente da dire (Reddit non configurato, nessun codice
    leggibile sull'etichetta, o nessun riscontro trovato).

    categoria_per_ricerca e' la stessa categoria (in italiano, es. 'maglia')
    gia' calcolata da estrai_categoria_da_titolo per la ricerca comp --
    viene tradotta in inglese con CATEGORIA_TERMINE_EN per il confronto coi
    risultati Reddit (quasi sempre in inglese)."""
    if not REDDIT_ABILITATO:
        return ""
    codici = _estrai_codici_prodotto_da_occhio(occhio_json)
    if not codici:
        return ""
    categoria_en = CATEGORIA_TERMINE_EN.get((categoria_per_ricerca or "").strip().lower())
    log.info("Verifica codici Reddit: interrogo %s per brand='%s' categoria='%s'.", codici, brand, categoria_en)
    righe = []
    for codice in codici:
        riga = await _reddit_verifica_codice(codice, brand, categoria_en=categoria_en)
        if riga:
            righe.append(riga)
    if righe:
        log.info("Verifica codici Reddit: %d segnal/e trovato/i.", len(righe))
    else:
        log.info("Verifica codici Reddit: nessun segnale (nessun risultato o tutto coerente).")
    if not righe:
        return ""
    return "\n\n--- VERIFICA CODICI PRODOTTO (Reddit) ---\n" + "\n".join(righe)


async def search_comps_completo(brand, categoria, query_base, catalog_id=None, material_per_ricerca=None, cover_photo_id=None, item_id=None, nome_sarto=None, dettaglio_distintivo=None):
    vinted_url, vinted_per_id = build_vinted_search_url(brand, categoria, material_per_ricerca, catalog_id)
    # Ricerca extra per nome del sarto/maker (aggiunta il 2026-09-20, vedi il
    # commento in process_listing su nome_sarto_o_maker): SEMPRE testo libero
    # (VINTED_BRAND_IDS quasi certamente non mappa sartorie/maker minori),
    # niente filtro categoria/materiale sul brand_id perche' non ce n'e' uno
    # -- build_vinted_search_url cade gia' da sola nel ramo search_text puro
    # quando il brand non e' in mappa, e' il comportamento voluto qui.
    url_sarto = None
    if nome_sarto:
        url_sarto, _ = build_vinted_search_url(nome_sarto, categoria, material_per_ricerca, catalog_id)
    # Se manca l'ingrediente minimo (photo_id o brand mappato) la fonte
    # visuale e' inutile: lo sappiamo gia' qui senza fare rete, quindi non la
    # sottomettiamo affatto all'executor invece di sprecare uno slot/tempo.
    tentare_ricerca_visuale = (
        VISUAL_SEARCH_ATTIVA
        and bool(cover_photo_id)
        and bool(VINTED_BRAND_IDS.get((brand or "").strip().lower()))
    )

    # Corretto il 2026-09-19: eBay (via Resellbot) e Vestiaire Collective
    # rimosse dalla pipeline. Causa root: confermato (dall'utente + verifica
    # web su resellbot.com/ebay-sold-listings) che Resellbot interroga
    # eBay.com US in DOLLARI, ma il codice stampava ogni prezzo col simbolo
    # € senza alcuna conversione -- un $150 USD diventava letteralmente
    # "€150.00" nel pool, sballando ogni comp eBay di circa il 10-15% (cambio)
    # oltre a mescolare un mercato (USA, vintage/resale) con dinamiche di
    # prezzo diverse da quello italiano/europeo. Questo spiegava anche
    # perche' Gemini "sembrava" sottostimare rispetto a eBay/Vestiaire nei
    # log osservati (Loro Piana, Missoni, Jil Sander): non stava sbagliando,
    # stava ragionando su comp gonfiati da un bug di dati a monte. Decisione
    # operativa: tenere solo Vinted (gia' in EUR, mercato italiano reale) +
    # la conoscenza generale di Gemini (grounding).
    #
    # AGGIORNAMENTO 2026-09-25: la conversione valuta in
    # _cerca_ebay_sold_via_resellbot / _query_resellbot_raw e' stata
    # corretta (vedi TASSO_USD_EUR). Su richiesta esplicita dell'utente,
    # eBay/Poshmark (via Resellbot, con fallback Google) rientra ora nel
    # fan-out qui sotto come fonte SEMPRE tentata (non condizionale come la
    # ricerca visuale) -- stessi filtri di pulizia gia' usati su Vinted
    # (autoreferenziale, categoria, non il filtro sottolinee: non ha senso
    # concettuale su un mercato USA generico). Vedi _cerca_ebay_sold_con_fallback.
    # Fan-out delle fonti comp con asyncio.gather invece del vecchio
    # ThreadPoolExecutor. Due vantaggi concreti oltre al non bloccare il loop:
    # il timeout e' PER FONTE (prima era complessivo sull'as_completed, quindi
    # una fonte lenta poteva consumare il budget di tutte), e asyncio.wait_for
    # CANCELLA davvero la coroutine scaduta, mentre un thread in timeout
    # restava vivo a consumare connessioni e quota Serper per una risposta
    # che nessuno avrebbe piu' letto.
    TIMEOUT_PER_FONTE_SECONDI = 15

    async def _esegui_fonte(nome, coroutine, timeout=TIMEOUT_PER_FONTE_SECONDI):
        try:
            testo, ok, mappa_url = await asyncio.wait_for(coroutine, timeout=timeout)
            return nome, testo, ok, mappa_url
        except asyncio.TimeoutError:
            return nome, f"  Timeout (fonte troppo lenta, oltre {timeout}s).", False, {}
        except Exception as e:
            return nome, f"  Query fallita: {e}", False, {}

    # Ricerca testuale Vinted (e per sarto): scrape diretto con Serper come
    # riserva dal 2026-09-25, vedi _cerca_vinted_testo_diretto_con_fallback_serper.
    # Timeout piu' ampio delle altre fonti perche' nel caso peggiore fa due
    # tentativi in sequenza (diretto, poi Serper).
    lavori = [_esegui_fonte(
        "vinted", _cerca_vinted_testo_diretto_con_fallback_serper(vinted_url),
        timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI)]
    if tentare_ricerca_visuale:
        lavori.append(_esegui_fonte(
            "vinted_visuale", _recupera_comp_visuali_vinted(item_id, cover_photo_id, brand)))
    if url_sarto:
        lavori.append(_esegui_fonte(
            "vinted_sarto", _cerca_vinted_testo_diretto_con_fallback_serper(url_sarto),
            timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI))
    # eBay/Poshmark via Resellbot (con fallback Google), sempre tentata --
    # reintrodotta nel fan-out il 2026-09-25, vedi commento sopra e
    # _cerca_ebay_sold_con_fallback. Timeout piu' ampio delle fonti Vinted
    # semplici per lo stesso motivo (caso peggiore: Resellbot fino a 12s poi
    # fallback Google fino a 8s, vedi il timeout di _cerca_ebay_sold_via_resellbot
    # alzato da 6 a 12s lo stesso giorno dopo l'analisi dei log di produzione).
    lavori.append(_esegui_fonte(
        "ebay_poshmark",
        _cerca_ebay_sold_con_fallback(brand, categoria, material_per_ricerca, dettaglio_distintivo),
        timeout=TIMEOUT_FONTE_VINTED_CON_FALLBACK_SECONDI))

    risultati = {}
    successi = {}
    mappe_url = {}
    for nome, testo, ok, mappa_url in await asyncio.gather(*lavori):
        risultati[nome] = testo
        successi[nome] = ok
        mappe_url[nome] = mappa_url

    serper_ha_funzionato = any(successi.values())

    nota_brand = "" if vinted_per_id else (
        "⚠️ Brand non nella mappa brand_id Vinted -- la ricerca Vinted usa testo libero "
        "(meno precisa, possibili falsi positivi)."
    )

    vinted_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted"), query_base)
    vinted_comp_puliti = _filtra_comp_per_categoria(vinted_comp_puliti, categoria)
    vinted_comp_puliti = _filtra_comp_per_brand_sottolinee(vinted_comp_puliti, brand)
    # La fonte visuale conta come "presente" solo se ha davvero prodotto un
    # risultato (successi["vinted_visuale"] True) -- se photo_id/brand
    # mancavano non e' nemmeno stata sottomessa (tentare_ricerca_visuale
    # False), se e' stata sottomessa ma la risoluzione ID o lo scrape sono
    # falliti risulta un fallimento come le altre query, non un errore raro.
    fonte_visuale_riuscita = tentare_ricerca_visuale and successi.get("vinted_visuale")
    visual_comp_puliti = None
    if fonte_visuale_riuscita:
        visual_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted_visuale"), query_base)
        # _filtra_comp_per_categoria RIATTIVATO qui il 2026-09-20: log di
        # produzione (Jean Paul Gaultier, Max Mara, Vivienne Westwood) hanno
        # mostrato borse/profumi/gioielli/categorie completamente diverse
        # mescolate nei comp "visuali" -- l'assunzione che bastasse il
        # search_by_image_id a restringere per somiglianza visiva era
        # sbagliata (causa reale: order=newest_first sull'URL, appena
        # rimosso in build_vinted_visual_search_url). Finche' non
        # verifichiamo in produzione che il fix dell'ordinamento basta da
        # solo, questo filtro resta come rete di sicurezza anti-categoria-
        # sbagliata anche sulla fonte visuale.
        visual_comp_puliti = _filtra_comp_per_categoria(visual_comp_puliti, categoria)
        visual_comp_puliti = _filtra_comp_per_brand_sottolinee(visual_comp_puliti, brand)
        log.info(
            "search_comps_completo: comp visuali DOPO pulizia (item_id=%s, brand=%s) -> %r",
            item_id, brand, visual_comp_puliti,
        )

    # Fonte extra per nome sarto/maker (aggiunta il 2026-09-20): pulita con
    # le stesse funzioni delle altre fonti Vinted testuali, TRANNE il filtro
    # sottolinee (_filtra_comp_per_brand_sottolinee con un nome di sartoria/
    # maker minore non in BRAND_SOTTOLINEE_DA_ESCLUDERE e' comunque un no-op,
    # ma non ha senso concettuale applicarlo qui).
    sarto_comp_puliti = None
    fonte_sarto_riuscita = bool(url_sarto) and successi.get("vinted_sarto")
    if fonte_sarto_riuscita:
        sarto_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("vinted_sarto"), query_base)
        sarto_comp_puliti = _filtra_comp_per_categoria(sarto_comp_puliti, categoria)
        log.info(
            "search_comps_completo: comp per nome sarto/maker '%s' DOPO pulizia (item_id=%s) -> %r",
            nome_sarto, item_id, sarto_comp_puliti,
        )

    # Fonte eBay/Poshmark (Resellbot, con fallback Google) -- reintrodotta nel
    # fan-out il 2026-09-25. Pulita con le stesse funzioni delle fonti Vinted
    # testuali TRANNE il filtro sottolinee (_filtra_comp_per_brand_sottolinee
    # e' pensato per collab/sottolinee di maison italiane su Vinted, non ha
    # senso concettuale su un pool eBay/Poshmark USA generico).
    ebay_comp_puliti = None
    fonte_ebay_riuscita = successi.get("ebay_poshmark")
    if fonte_ebay_riuscita:
        ebay_comp_puliti = _rimuovi_comp_autoreferenziale(risultati.get("ebay_poshmark"), query_base)
        ebay_comp_puliti = _filtra_comp_per_categoria(ebay_comp_puliti, categoria)
        log.info(
            "search_comps_completo: comp eBay/Poshmark DOPO pulizia (item_id=%s, brand=%s) -> %r",
            item_id, brand, ebay_comp_puliti,
        )

    n_fonti = 1 + int(fonte_visuale_riuscita) + int(fonte_sarto_riuscita) + int(fonte_ebay_riuscita)
    parti = [f"RICERCA WEB PRE-RACCOLTA ({n_fonti} fonti, base: '{query_base}'):"]
    if nota_brand:
        parti.append(nota_brand)
    if categoria:
        parti.append(f"(Comp filtrati per categoria rilevata: '{categoria}' -- risultati fuori tema gia' scartati.)")
    if fonte_visuale_riuscita:
        parti.append(
            "\n📍 FONTE: VINTED — RICERCA VISUALE PER FOTO (stesso identikit visivo dell'annuncio, "
            "filtrato per brand — la piu' precisa delle fonti, prezzi ASK)\n"
            f"{visual_comp_puliti or 'Nessun risultato'}"
        )
    parti.append(
        "\n📍 FONTE: VINTED (prezzi ASK — annunci attivi, NON necessariamente venduti; annuncio in analisi gia' escluso)\n"
        f"{vinted_comp_puliti or 'Nessun risultato'}"
    )
    if url_sarto:
        parti.append(
            f"\n📍 FONTE: VINTED — RICERCA PER NOME SARTORIA/MAKER '{nome_sarto}' (letto dall'etichetta, "
            "diverso dal brand/tessuto dichiarato nell'annuncio -- verifica se il nome del produttore "
            "reale ha un mercato riconoscibile a se', prezzi ASK)\n"
            f"{sarto_comp_puliti or 'Nessun risultato'}"
        )
    if fonte_ebay_riuscita:
        parti.append(
            "\n📍 FONTE: EBAY / POSHMARK (via Resellbot -- prezzi di VENDITA CONFERMATA "
            "quando taggati '[venduto: YYYY-MM-DD]', mercato USA in dollari gia' convertiti "
            "in euro a tasso fisso -- NON il mercato italiano/europeo, usa come riferimento "
            "di prezzo generale del brand, non come comp diretto senza aggiustamento)\n"
            f"{ebay_comp_puliti or 'Nessun risultato'}"
        )

    # Mappa URL comp unita da tutte le fonti che l'hanno popolata (solo
    # scrape diretto, vedi _cerca_vinted_testo_diretto_con_fallback_serper) --
    # usata al rendering finale per riattaccare un link cliccabile al comp
    # che il Cervello cita nel suo JSON, mai passata al prompt (Punto 3,
    # 2026-09-25, esteso a eBay/Poshmark lo stesso giorno). Sull'eventuale,
    # rara collisione di chiave (stesso titolo+prezzo su due fonti diverse)
    # vince l'ultima fonte unita: non ha importanza, l'URL punta comunque a
    # un annuncio con lo stesso titolo/prezzo esatto.
    mappa_url_comp = {}
    for nome in ("vinted", "vinted_visuale", "vinted_sarto", "ebay_poshmark"):
        mappa_url_comp.update(mappe_url.get(nome) or {})

    return (
        "\n".join(parti), serper_ha_funzionato, tentare_ricerca_visuale,
        fonte_visuale_riuscita, mappa_url_comp,
    )


def _estrai_margine_e_roi_da_blocco(blocco_testo):
    """Estrae margine netto e ROI da un blocco di testo. Gestisce anche i
    range (es. '€27-40 (ROI 110-165%)'), prendendo sempre il valore piu'
    basso come stima prudente -- il regex precedente si fermava sul primo
    numero e falliva silenziosamente quando seguito da un range invece che
    direttamente da 'ROI', lasciando margine=None e bypassando le reti di
    sicurezza a valle."""
    margine_m = re.search(r"€\s*(-?[\d.,]+)(?:\s*[-–]\s*[\d.,]+)?\s*\)?\s*\(?ROI", blocco_testo, re.IGNORECASE)
    roi_m = re.search(r"ROI\s*~?\s*(-?\d+)", blocco_testo, re.IGNORECASE)

    margine = None
    if margine_m:
        try:
            margine = float(margine_m.group(1).replace(",", "."))
        except ValueError:
            pass

    roi = None
    if roi_m:
        try:
            roi = int(roi_m.group(1))
        except ValueError:
            pass

    return margine, roi


# ---------------------------------------------------------------------------
# FILTRO PRE-CERVELLO e VALIDAZIONE POST-GENERAZIONE
# ---------------------------------------------------------------------------

def estrai_margine_preliminare(output_occhi_testo):
    """Estrae margine netto e ROI dalla valutazione finanziaria preliminare
    che l'occhio produce (best-effort: i formati variano leggermente)."""
    return _estrai_margine_e_roi_da_blocco(output_occhi_testo or "")


def check_skip_pre_cervello(output_occhi_testo, listing_info=None, occhio_json=None):
    """occhio_json: presente solo con OCCHIO_OUTPUT_JSON=true. In quel caso
    lo scarto si calcola da campi tipizzati invece che cercando sottostringhe
    nella prosa, e tutto il resto di questa funzione non viene eseguito.

    Il ramo su prosa qui sotto resta invariato: e' il comportamento di
    default, quello che gira oggi in produzione."""
    if occhio_json is not None:
        solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
        return calcola_scarto_occhio(occhio_json, solo_cover_photo=solo_cover, listing_info=listing_info)

    testo = (output_occhi_testo or "").lower()

    # NOTA (caso reale osservato): un Dries Van Noten a €5,95 e' stato
    # scartato qui come "falso palese, Confidenza Alta" con dettagli che
    # sembravano inventati, mentre 3 legit check esterni indipendenti sullo
    # stesso capo hanno concluso "Probabilmente autentico" 82-85%. La causa
    # probabile e' un bias "prezzo troppo basso = deve essere falso"
    # nell'occhio. Soluzione scelta: RINFORZARE il prompt dell'occhio (non
    # rimuovere questo filtro, che resta utile per risparmiare token sui
    # falsi genuinamente conclamati).
    # Corretto il 2026-09-19 (caso reale Miu Miu pull cour): DUE bug distinti
    # facevano si' che questo skip non scattasse mai per il formato che
    # l'occhio produce davvero in produzione.
    # 1. Il prompt canonizza solo "Probabilmente falso" tra i 4 verdetti
    #    possibili, ma il modello a volte scrive varianti equivalenti
    #    ("Falso palese", "Falso evidente") per enfatizzare la certezza --
    #    non matchavano nessuna delle stringhe cercate qui sotto.
    # 2. Il template del prompt per la riga finale e' sempre "Confidenza:
    #    [A/M/B]" (vedi riga "Confidenza: [B]"/"Confidenza: [A/M/B]" nel
    #    prompt), cioe' CON i due punti -- "Confidenza: Alta" nel testo
    #    reale, mentre il filtro cercava "confidenza alta" SENZA i due
    #    punti. Il pattern non ha mai potuto matchare il formato standard,
    #    a meno che il testo non contenesse anche "molto alto" o una
    #    percentuale esplicita altrove (raro). Questo era il bug root:
    #    anche un "Probabilmente falso" testuale puro con "Confidenza: Alta"
    #    non veniva riconosciuto. Risultato pratico osservato in produzione:
    #    il cervello veniva comunque consultato e tutte le ricerche di
    #    prezzo (Resellbot/Serper) partivano inutilmente su un verdetto
    #    gia' scontato (NON COMPRARE), sprecando query a pagamento.
    ha_falso_alta_confidenza = (
        "probabilmente falso" in testo
        or "falso conclamato" in testo
        or "falso palese" in testo
        or "falso evidente" in testo
    )
    ha_confidenza_alta = any(c in testo for c in (
        "confidenza alta", "confidenza: alta", "confidenza:alta",
        "90%", "95%", "100%", "molto alto",
    ))
    if ha_falso_alta_confidenza and ha_confidenza_alta:
        return True, "[FALSO CONCLAMATO] Rilevato da analisi visiva con alta confidenza."

    # Skip su brand completamente estraneo (non una sottolinea/diffusion --
    # un marchio diverso e non correlato, es. l'annuncio dichiara "Kapital"
    # ma l'etichetta reale e' "Kapitales", brand francese di souvenir senza
    # alcun legame col Kapital giapponese monitorato). Il prompt dell'occhio
    # istruisce a scrivere la frase esatta "BRAND NON CORRISPONDENTE" solo
    # quando e' sicuro che sia un marchio diverso, non per semplici dubbi --
    # quindi qui e' sicuro fidarsi del match testuale senza ulteriori
    # controlli di confidenza (a differenza del "falso conclamato" sopra,
    # dove il bias prezzo-basso rendeva la sola dichiarazione del modello
    # inaffidabile). Risparmia la ricerca comp del cervello: il verdetto
    # e' gia' scontato (NON COMPRARE) indipendentemente da prezzo/comp.
    if "brand non corrispondente" in testo:
        return True, (
            "[BRAND NON CORRISPONDENTE] L'analisi visiva ha rilevato un marchio diverso "
            "e non correlato rispetto a quello dichiarato nell'annuncio -- cervello non "
            "consultato, il capo non ha valore nel segmento monitorato indipendentemente dal prezzo."
        )

    segnali_danno_fisico = sum([
        "buchi" in testo or "buco" in testo,
        "strappi gravi" in testo or "strappo grave" in testo,
        "bruciature" in testo or "bruciatura" in testo,
        "da riparare" in testo and "non riparabile" in testo,
        "condizione pessima" in testo,
        "indossabile" in testo and "non" in testo,
    ])
    if segnali_danno_fisico >= 2:
        return True, "[CONDIZIONE DISTRUTTA] Danni fisici gravi multipli rilevati dall'analisi visiva."

    # Skip su nessuna etichetta visibile: senza nessuna etichetta il cervello
    # non ha nulla in piu' da aggiungere sull'autenticita' -- l'unico passo
    # utile e' chiedere altre foto, cosa che l'occhio ha gia' suggerito.
    #
    # ECCEZIONE IMPORTANTE: se le foto reali dell'annuncio non sono state
    # scaricate e l'analisi si basa solo sulla cover photo di Telegram, un
    # "nessuna etichetta visibile" e' quasi certamente un falso negativo
    # dovuto allo scraping fallito, non al capo -- in quel caso NON si
    # scarta, si lascia proseguire al cervello.
    solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
    BLOCCO_VERDETTO_INIZIALE = testo[:250]
    ETICHETTA_KEYWORDS_ESPLICITE = [
        "nessuna etichetta visibile", "assenza totale di etichette",
        "etichette non visibili", "zero etichette", "senza etichette visibili",
        "non sono visibili etichette", "nessuna etichetta è visibile",
    ]
    nessuna_etichetta = (
        "non verificabile" in BLOCCO_VERDETTO_INIZIALE
        or any(kw in testo for kw in ETICHETTA_KEYWORDS_ESPLICITE)
    )
    if nessuna_etichetta and not solo_cover:
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] L'analisi visiva non ha trovato etichette "
            "per verificare l'autenticita' -- cervello non consultato, servono piu' foto "
            "(main label + wash tag) prima di procedere."
        )
    if nessuna_etichetta and solo_cover:
        log.info(
            "Skip 'nessuna etichetta' NON applicato: analisi basata solo sulla cover photo "
            "(scraping foto fallito), probabile falso negativo -- si prosegue col cervello."
        )

    # Skip su margine preliminare chiaramente negativo: se anche la stima
    # dell'occhio (di solito ottimistica, senza comp reali) indica gia' una
    # perdita netta o ROI negativo, e' molto improbabile che il cervello,
    # con dati di mercato reali, trovi un risultato migliore.
    margine_prelim, roi_prelim = estrai_margine_preliminare(output_occhi_testo)
    margine_esplicitamente_nullo = any(k in testo for k in (
        "margine nullo", "margine negativo", "nessun valore di rivendita",
        "valore di rivendita non significativo", "non c'è valore di rivendita",
        "non vale il tempo",
    ))
    if margine_esplicitamente_nullo or (margine_prelim is not None and margine_prelim < 0) or (roi_prelim is not None and roi_prelim < 0):
        return True, (
            f"[MARGINE PRELIMINARE NEGATIVO] Stima preliminare dell'occhio indica "
            f"perdita netta (margine={margine_prelim}, ROI={roi_prelim}%) -- "
            "cervello non consultato per risparmiare token."
        )

    return False, None


def build_skip_report(listing_info, motivo_skip, output_occhi_testo=None):
    if motivo_skip.startswith("[MARGINE INSUFFICIENTE"):
        riga_legit = "Non valutato — filtro pre-cervello su margine insufficiente. Autenticita' non in dubbio."
        riga_rischio = "BASSO — margine insufficiente (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[FALSO CONCLAMATO"):
        riga_legit = "Probabilmente falso — rilevato da analisi visiva con alta confidenza."
        if output_occhi_testo:
            dettaglio = None

            # Tentativo 1: formato atteso con intestazione "**Analisi visiva**"
            m_analisi = re.search(
                r"\*\*Analisi visiva\*\*[^\n]*\n+(.+?)(?=\n---|\n##|\n📨|\Z)",
                output_occhi_testo, re.IGNORECASE | re.DOTALL,
            )
            if m_analisi and m_analisi.group(1).strip():
                dettaglio = m_analisi.group(1).strip()

            # Tentativo 2: posizionale -- qualunque cosa segua il primo
            # separatore "---" (che nel template segue sempre il Verdetto).
            if not dettaglio:
                m_pos = re.search(r"\n---\s*\n+(.+?)(?=\n---|\n📨|\Z)", output_occhi_testo, re.DOTALL)
                if m_pos and m_pos.group(1).strip():
                    dettaglio = m_pos.group(1).strip()

            # Tentativo 3 (ultima risorsa): tutto il testo grezzo troncato.
            if not dettaglio:
                testo_grezzo = output_occhi_testo.strip()
                dettaglio = testo_grezzo[:600] + ("..." if len(testo_grezzo) > 600 else "")

            if dettaglio:
                riga_legit = f"Probabilmente falso. Motivo specifico: {dettaglio}"
        riga_rischio = "ALTO — falso conclamato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[BRAND NON CORRISPONDENTE"):
        riga_legit = "Brand non corrispondente — marchio reale sull'etichetta diverso e non correlato a quello dichiarato."
        if output_occhi_testo:
            m_legit = re.search(r"🏷️\s*Legit:\s*([^\n]+)", output_occhi_testo, re.IGNORECASE)
            if m_legit and m_legit.group(1).strip():
                riga_legit = m_legit.group(1).strip()
        riga_rischio = "N/A — brand estraneo al segmento monitorato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[ANNUNCIO FRAUDOLENTO"):
        # BUG reale trovato il 2026-09-22 rileggendo lo storico Telegram: 12
        # skip su 51 (23%) di questo tipo mostravano tutti il placeholder
        # generico "Motivo di skip automatico non categorizzato" nel
        # messaggio finale, perche' mancava questo branch -- il motivo
        # SPECIFICO (i segnali di rischio annuncio elencati da
        # calcola_scarto_occhio, es. "screenshot_di_altro_annuncio",
        # "watermark_di_altro_sito"...) veniva gia' calcolato correttamente
        # ma andava perso al momento di renderizzare il messaggio, cadendo
        # nel ramo "else" generico invece che in un caso dedicato. Qui si
        # riusa motivo_skip stesso, che contiene gia' l'elenco dei segnali.
        riga_legit = motivo_skip.replace("[ANNUNCIO FRAUDOLENTO] ", "", 1)
        riga_rischio = "ALTO — segnali di frode sull'annuncio stesso (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[TESSUTO NON E' IL BRAND"):
        riga_legit = "Nome citato e' il fornitore del tessuto, non il produttore del capo — comp del brand del tessuto non validi per questo capo."
        riga_rischio = "N/A — produttore reale del capo ignoto (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[MAX MARA SOTTOLINEA SENZA VALORE"):
        riga_legit = "Autenticita' non in dubbio — sottolinea Max Mara non-mainline senza modello iconico ne' materiale pregiato dichiarato, valore strutturalmente troppo basso."
        riga_rischio = "N/A — sottolinea Max Mara sotto soglia (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[CONDIZIONE DISTRUTTA"):
        riga_legit = "Autentico ma condizione fisica gravemente compromessa — non rivendibile."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — cervello non consultato"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE"):
        riga_legit = "Nessuna etichetta visibile nelle foto fornite — autenticita' non verificabile allo stato attuale."
        riga_rischio = "ALTO (non verificabile) — servono piu' foto (filtro pre-cervello, risparmio token)"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA INTERNA - MIU MIU T-SHIRT"):
        riga_legit = "Main label (etichetta interna) non leggibile — su questa categoria non si valuta senza, anche con altre etichette visibili."
        riga_rischio = "ALTO (non verificabile) — regola severa Miu Miu t-shirt, servono foto della main label (filtro pre-cervello)"
    elif motivo_skip.startswith("[MARGINE PRELIMINARE NEGATIVO"):
        riga_legit = "Non valutato nel dettaglio — la stima preliminare indicava gia' una perdita netta."
        riga_rischio = "N/A — margine preliminare negativo (cervello non consultato per risparmiare token)"
    elif motivo_skip.startswith("[CATEGORIA GENERICA NON FLIPPABILE"):
        riga_legit = "Categoria strutturalmente senza mercato — nessun valore di rivendita."
        riga_rischio = "BASSO — categoria non flippabile (filtro pre-Gemini)"
    elif motivo_skip.startswith("[DANNO GRAVE DICHIARATO NEL TESTO"):
        riga_legit = "Non valutato — venditore dichiara esplicitamente un danno grave nel testo."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — danno dichiarato dal venditore (filtro pre-Gemini)"
    elif motivo_skip.startswith("[NON ORIGINALE DICHIARATO"):
        riga_legit = "Venditore dichiara esplicitamente che il capo non e' originale."
        riga_rischio = "MOLTO ALTO — non originale per dichiarazione diretta (filtro pre-Gemini)"
    elif motivo_skip.startswith("[TITOLO CON STRINGA DI RICERCA RESIDUA"):
        riga_legit = "Titolo contiene una stringa di ricerca residua ('gilet -blanc') — annuncio non valutato."
        riga_rischio = "BASSO — titolo malformato (filtro pre-Gemini)"
    elif motivo_skip.startswith("[LINEA/VARIANTE ESCLUSA PER BRAND"):
        riga_legit = "Linea o variante esclusa esplicitamente dalle regole di valutazione."
        riga_rischio = "ALTO / SCONVENIENTE — linea esclusa (filtro pre-Gemini)"
    elif motivo_skip.startswith("[VENDITORE IN BLOCKLIST"):
        riga_legit = "Venditore in blocklist (possibile truffatore o perditempo)."
        riga_rischio = "MOLTO ALTO — venditore bloccato (filtro pre-Gemini)"
    elif motivo_skip.startswith("[BRAND IN BLOCKLIST"):
        riga_legit = "Brand escluso in modo permanente dalle regole di valutazione."
        riga_rischio = "N/A — brand bloccato su richiesta esplicita (filtro pre-Gemini)"
    else:
        riga_legit = "Motivo di skip automatico non categorizzato."
        riga_rischio = "N/A — filtro automatico"

    motivo_breve = motivo_skip[:117].rsplit(" ", 1)[0] + "..." if len(motivo_skip) > 120 else motivo_skip

    # Per il caso "nessuna etichetta", riusa il messaggio che l'occhio ha gia'
    # suggerito (di solito chiede foto di main label + wash tag).
    messaggio_skip = "Non necessario."
    if motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE") and output_occhi_testo:
        m = re.search(
            r"📨\s*\*\*Messaggio da inviare:?\*\*\s*\n\"?([^\n\"]+)",
            output_occhi_testo, re.IGNORECASE,
        )
        if m:
            messaggio_skip = m.group(1).strip()

    # Sfuggiti QUI, tutti insieme e appena prima dell'assemblaggio finale,
    # invece che nei singoli punti sopra dove vengono valorizzati: piu'
    # facile garantire che nessun punto di uscita della funzione se ne
    # dimentichi. riga_rischio non serve escaparla (e' sempre una delle
    # stringhe fisse nel blocco elif qui sopra, mai testo del modello).
    riga_legit = _escapa_markdown_legacy(riga_legit)
    motivo_breve = _escapa_markdown_legacy(motivo_breve)
    messaggio_skip = _escapa_markdown_legacy(messaggio_skip)

    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — filtro automatico\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        f"- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidita':** Bassa · **Rischio:** {riga_rischio} · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        f"## Legit check\n{riga_legit}\n\n"
        "## Da chiedere\nNon rilevante: filtro automatico attivato.\n\n"
        f"## Messaggio da inviare\n{messaggio_skip}"
    )


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


def _normalizza_titolo_per_dedup(title):
    if not title:
        return ""
    t = title.strip()
    t_senza_virgolette = re.sub(r"['\"][^'\"]*['\"]\s*$", "", t).strip()
    if t_senza_virgolette != t:
        base = t_senza_virgolette
    else:
        parole = t.split()
        base = " ".join(parole[:-1]) if len(parole) > 1 else t
    return re.sub(r"\s+", " ", base).strip().lower()


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
