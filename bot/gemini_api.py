"""Chiamate a Gemini (gratuito): cascata di modelli, rotazione chiavi, retry. Usate da moda_gemini e radar_gemini."""
import asyncio
import time

import httpx


from bot.gemini_stato import GEMINI_API_KEYS, GEMINI_BACKOFF_MAX_S, GEMINI_BUDGET_CHIAMATA_S, GEMINI_TIMEOUT_S, gemini_in_pausa_timeout, gemini_segna_timeout, gemini_timeout_azzera, cascata_per, MAX_RETRIES_GEMINI_IN_BLACKOUT, _gemini_e_errore_key_non_valida, _gemini_e_errore_quota_giornaliera, _gemini_gestisci_modello_non_disponibile, _gemini_in_blackout, _gemini_key_attuale, _gemini_modello_da_url, _gemini_prossima_key, _gemini_registra_esito, _gemini_secondi_retry, _gemini_segna_key_non_valida, _gemini_segna_key_quota_esaurita, _gemini_url_effettivo
from bot.config import GEMINI_API_URL_OCCHIO, PREZZO_GROUNDING_PER_QUERY, PREZZO_OCCHIO_INPUT, PREZZO_OCCHIO_OUTPUT
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
