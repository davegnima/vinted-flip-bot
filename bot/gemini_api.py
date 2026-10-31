"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import json
import asyncio
import time

import httpx


from bot.schemas import CERVELLO_RESPONSE_SCHEMA
from bot.gemini_stato import GEMINI_API_KEYS, GEMINI_BACKOFF_MAX_S, GEMINI_BUDGET_CHIAMATA_S, GEMINI_TIMEOUT_S, gemini_in_pausa_timeout, gemini_segna_timeout, gemini_timeout_azzera, cascata_per, MAX_RETRIES_GEMINI_IN_BLACKOUT, _gemini_e_errore_key_non_valida, _gemini_e_errore_quota_giornaliera, _gemini_gestisci_modello_non_disponibile, _gemini_in_blackout, _gemini_key_attuale, _gemini_modello_da_url, _gemini_prossima_key, _gemini_registra_esito, _gemini_secondi_retry, _gemini_segna_key_non_valida, _gemini_segna_key_quota_esaurita, _gemini_url_effettivo
from bot.config import GEMINI_API_URL_CERVELLO, GEMINI_API_URL_OCCHIO, PREZZO_CERVELLO_INPUT, PREZZO_CERVELLO_OUTPUT, PREZZO_GROUNDING_PER_QUERY, PREZZO_OCCHIO_INPUT, PREZZO_OCCHIO_OUTPUT
from bot.foto import costruisci_parts_foto
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
async def testa_chiavi_gemini(chiavi=None):
    """Prova ogni chiave con un elenco modelli (non consuma quota di generazione). Ritorna [(numero, esito)] con esito
    'valida' | 'NON VALIDA' | 'valida, ma 429' | 'errore <codice>'. Le chiavi non vengono mai restituite ne' loggate."""
    chiavi = GEMINI_API_KEYS if chiavi is None else chiavi
    risultati = []
    for i, k in enumerate(chiavi, 1):
        try:
            r = await hc._client_generico.get("https://generativelanguage.googleapis.com/v1beta/models",
                                              headers={"x-goog-api-key": k}, timeout=15)
            c = r.status_code
            esito = "valida" if c == 200 else "NON VALIDA" if c in (400, 401, 403) else "valida, ma 429" if c == 429 else f"errore {c}"
        except Exception as e:
            esito = f"errore di rete ({type(e).__name__})"
        risultati.append((i, esito))
    return risultati


def costo_gemini_token(usage, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT):
    inp = usage.get("promptTokenCount", 0) or 0
    out = usage.get("candidatesTokenCount", 0) or 0
    return (inp * prezzo_input + out * prezzo_output) / 1_000_000


async def chiama_gemini(system_prompt, user_text, photo_bytes_list=None, grounding=False, max_retries=4,
                        api_url=GEMINI_API_URL_OCCHIO, prezzo_input=PREZZO_OCCHIO_INPUT, prezzo_output=PREZZO_OCCHIO_OUTPUT, ruolo="occhio",
                        response_schema=None):
    """response_schema: se valorizzato, la risposta e' JSON conforme allo
    schema invece che prosa libera (usato dall'Occhio con
    OCCHIO_OUTPUT_JSON=true). Il testo ritornato e' il JSON grezzo: a
    deserializzarlo e validarlo ci pensa il chiamante."""
    photo_bytes_list = photo_bytes_list or []
    parts = [{"text": user_text}] + await costruisci_parts_foto(photo_bytes_list)

    # Niente temperature/top_p/top_k (avviso Google 10/2026: ignorati dai Gemini 3.6+, errore nei prossimi modelli)
    generation_config = {
        "maxOutputTokens": 3000,
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
    if cascata_per(ruolo):
        max_retries_effettivi += len(GEMINI_API_KEYS)   # i 429 di quota esaurita sono rapidi: non bruciano il budget

    backoff_seconds = 2
    t_inizio = time.time()
    modello_usato = None
    for attempt in range(1, max_retries_effettivi + 1):
        if (attempt > 1 and time.time() - t_inizio >= GEMINI_BUDGET_CHIAMATA_S) or gemini_in_pausa_timeout(ruolo):
            break   # budget di tempo finito o fase in pausa per timeout: errore subito, a valle decide la riserva
        t_tentativo = time.time()
        try:
            # Timeout abbassato da 90 a 30s (richiesto dall'utente il
            # 2026-09-22): 90s era pensato per una risposta lenta ma valida,
            # non per un 503 (che nei log arriva in 10-45s, non per timeout) --
            # ma se Gemini smette proprio di rispondere invece di restituire
            # un errore, 90s per tentativo x piu' tentativi x piu' round del
            # Cervello e' comunque troppo. 30s resta ampio per foto+prompt.
            url_usato = _gemini_url_effettivo(api_url, ruolo)
            modello_usato = _gemini_modello_da_url(url_usato)
            key_usata = _gemini_key_attuale(modello_usato)
            # Key nell'header e non nella query string (FIX 2026-09-24): come
            # parametro "?key=" finiva in chiaro nei log httpx su Railway.
            resp = await hc._client_generico.post(
                url_usato, headers={"x-goog-api-key": key_usata}, json=payload, timeout=GEMINI_TIMEOUT_S)
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
                    api_url, url_usato, resp.status_code, resp.text, ruolo)
                if modello_cambiato and attempt < max_retries_effettivi:
                    continue
            if resp.is_success:
                _gemini_registra_esito(True)
                gemini_timeout_azzera(ruolo)
                log.info("GEMINI_USO | %s | %s | %dms | tentativo %d", ruolo, modello_usato, (time.time() - t_tentativo) * 1000, attempt)
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
                    if cascata_per(ruolo) and _gemini_url_effettivo(api_url, ruolo) != url_usato:
                        continue   # quota finita su tutte le key di questo modello: si scala subito al successivo
                if _gemini_prossima_key(modello_usato):
                    continue
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, GEMINI_BACKOFF_MAX_S)
                continue
            if _gemini_e_errore_key_non_valida(resp.status_code, resp.text):
                _gemini_segna_key_non_valida(key_usata)
                if _gemini_prossima_key(modello_usato):
                    continue   # un'altra key valida: si ritenta subito
            resp.raise_for_status()
        except Exception as e:
            if isinstance(e, httpx.TimeoutException):
                log.warning("Gemini TIMEOUT | %s | %s | dopo %ds dall'inizio (tentativo %d/%d)", ruolo, modello_usato,
                            time.time() - t_inizio, attempt, max_retries_effettivi)
                gemini_segna_timeout(ruolo)
            if attempt < max_retries_effettivi:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, GEMINI_BACKOFF_MAX_S)
                continue
            _gemini_registra_esito(False)
            return f"[ERRORE: chiamata Gemini fallita dopo {max_retries_effettivi} tentativi. Eccezione: {e}]", 0.0, 0
    _gemini_registra_esito(False)
    return "[ERRORE: tentativi esauriti]", 0.0, 0


ISTRUZIONE_FASE_JSON = (
    "Produci ORA il verdetto come oggetto JSON "
    "conforme allo schema, usando esclusivamente i dati e i comp raccolti in "
    "questa conversazione. Ricorda: non calcolare margine, ROI, decisione, "
    "urgenza o importi di trattativa, e marca fonte='memoria_modello' ogni "
    "prezzo che non compare nei dati ricevuti."
)


def _estrai_testo_da_parts(parts):
    return "".join(p.get("text", "") for p in (parts or []) if isinstance(p, dict))


async def chiama_gemini_cervello(system_prompt, user_text, max_retries=4,
                                 api_url=GEMINI_API_URL_CERVELLO,
                                 prezzo_input=PREZZO_CERVELLO_INPUT,
                                 prezzo_output=PREZZO_CERVELLO_OUTPUT,
                                 ruolo="cervello"):
    """Cervello Gemini: UNA sola chiamata, con responseMimeType="application/json"
    e responseSchema. L'output e' un oggetto conforme a CERVELLO_RESPONSE_SCHEMA,
    non prosa da cui pescare numeri con espressioni regolari.

    Dal 31/10 non c'e' piu' la fase di ricerca on-demand (function calling
    cerca_comp_prezzo, che passava per Serper, tolto per scelta dell'utente):
    il Cervello decide solo sui comp pre-raccolti dal bot (Vinted, ricerca
    visuale, eBay/Poshmark) e sul testo dell'Occhio. Una chiamata Gemini in
    meno per annuncio.

    Ritorna una tupla di 3 elementi:
      (verdetto_dict | None, errore | None, costo_totale)"""
    # L'istruzione finale sta nello stesso turno utente: un solo messaggio.
    contents = [{"role": "user", "parts": [{"text": f"{user_text}\n\n{ISTRUZIONE_FASE_JSON}"}]}]
    costo_totale = 0.0

    async def _chiama_gemini_raw(tentativi_rimasti=max_retries):
        generation_config = {
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

        # Niente "tools"/"tool_config" nel payload: con lo schema attivo
        # sarebbero rifiutati dall'API.
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = CERVELLO_RESPONSE_SCHEMA

        # Stesso ragionamento di chiama_gemini (vedi commento esteso li'):
        # con un blackout gia' rilevato non si spendono tentativi_rimasti
        # pieni -- si fallisce prima invece di aspettare minuti in piu'.
        tentativi_effettivi = MAX_RETRIES_GEMINI_IN_BLACKOUT if _gemini_in_blackout() else tentativi_rimasti
        if cascata_per(ruolo):
            tentativi_effettivi += len(GEMINI_API_KEYS)

        backoff_seconds = 2
        t_inizio = time.time()
        modello_usato = None
        for attempt in range(1, tentativi_effettivi + 1):
            if (attempt > 1 and time.time() - t_inizio >= GEMINI_BUDGET_CHIAMATA_S) or gemini_in_pausa_timeout(ruolo):
                break   # budget di tempo finito o fase in pausa per timeout (vedi chiama_gemini)
            t_tentativo = time.time()
            try:
                # Timeout abbassato da 90 a 30s (richiesto dall'utente il
                # 2026-09-22, stesso motivo di chiama_gemini).
                url_usato = _gemini_url_effettivo(api_url, ruolo)
                modello_usato = _gemini_modello_da_url(url_usato)
                key_usata = _gemini_key_attuale(modello_usato)
                resp = await hc._client_generico.post(
                    url_usato, headers={"x-goog-api-key": key_usata}, json=payload, timeout=GEMINI_TIMEOUT_S)
                if not resp.is_success:
                    log.warning("Gemini (cervello) HTTP %d: %s", resp.status_code, resp.text[:500])
                    # Stesso fallback di modello di chiama_gemini, stesso FIX
                    # 2026-09-26: la marcatura di esclusione va sempre eseguita,
                    # anche sull'ultimo tentativo (vedi commento esteso li').
                    modello_cambiato = _gemini_gestisci_modello_non_disponibile(
                        api_url, url_usato, resp.status_code, resp.text, ruolo)
                    if modello_cambiato and attempt < tentativi_effettivi:
                        continue
                    if _gemini_e_errore_quota_giornaliera(resp.status_code, resp.text):
                        _gemini_segna_key_quota_esaurita(key_usata, modello_usato, _gemini_secondi_retry(resp.text))
                        if (cascata_per(ruolo) and attempt < tentativi_effettivi
                                and _gemini_url_effettivo(api_url, ruolo) != url_usato):
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
                        backoff_seconds = min(backoff_seconds * 2, GEMINI_BACKOFF_MAX_S)
                        continue
                    if _gemini_e_errore_key_non_valida(resp.status_code, resp.text):
                        _gemini_segna_key_non_valida(key_usata)
                        if attempt < tentativi_effettivi and _gemini_prossima_key(modello_usato):
                            continue   # un'altra key valida: si ritenta subito
                    resp.raise_for_status()
                _gemini_registra_esito(True)
                gemini_timeout_azzera(ruolo)
                log.info("GEMINI_USO | %s | %s | %dms | tentativo %d", ruolo, modello_usato, (time.time() - t_tentativo) * 1000, attempt)
                return resp.json()
            except Exception as e:
                if isinstance(e, httpx.TimeoutException):
                    log.warning("Gemini TIMEOUT | %s | %s | dopo %ds dall'inizio (tentativo %d/%d)", ruolo, modello_usato,
                                time.time() - t_inizio, attempt, tentativi_effettivi)
                    gemini_segna_timeout(ruolo)
                if attempt < tentativi_effettivi:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, GEMINI_BACKOFF_MAX_S)
                    continue
                _gemini_registra_esito(False)
                raise
        _gemini_registra_esito(False)
        raise RuntimeError("tentativi esauriti")

    try:
        data = await _chiama_gemini_raw()
    except Exception as e:
        return None, f"chiamata al verdetto strutturato fallita: {e}", costo_totale

    candidates = data.get("candidates", [])
    if not candidates:
        return None, "risposta Gemini senza candidates nella fase di verdetto", costo_totale

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
            ), costo_totale
        log.warning(
            "Cervello: fase verdetto senza testo -- finishReason=%s, usage=%s, n_parts=%d, safetyRatings=%s",
            finish_reason, json.dumps(usage, ensure_ascii=False)[:300], len(parts),
            candidates[0].get("safetyRatings", "assenti"),
        )
        return None, f"il modello non ha prodotto il JSON del verdetto (finishReason={finish_reason})", costo_totale

    try:
        verdetto = json.loads(testo_json)
    except json.JSONDecodeError as e:
        log.warning("Cervello: JSON non parsabile (finishReason=%s): %s\nTESTO GREZZO: %s",
                    finish_reason, e, testo_json[:1000])
        return None, f"JSON del verdetto non parsabile ({e})", costo_totale

    if not isinstance(verdetto, dict):
        return None, "il JSON del verdetto non e' un oggetto", costo_totale

    return verdetto, None, costo_totale
