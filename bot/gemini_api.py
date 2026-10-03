"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import json
import asyncio


from bot.schemas import CERVELLO_RESPONSE_SCHEMA
from bot.gemini_stato import GEMINI_API_KEYS, cascata_per, MAX_RETRIES_GEMINI_IN_BLACKOUT, _gemini_e_errore_quota_giornaliera, _gemini_gestisci_modello_non_disponibile, _gemini_in_blackout, _gemini_key_attuale, _gemini_modello_da_url, _gemini_prossima_key, _gemini_registra_esito, _gemini_secondi_retry, _gemini_segna_key_quota_esaurita, _gemini_url_effettivo
from bot.config import GEMINI_API_URL_CERVELLO, GEMINI_API_URL_OCCHIO, PREZZO_CERVELLO_INPUT, PREZZO_CERVELLO_OUTPUT, PREZZO_GROUNDING_PER_QUERY, PREZZO_OCCHIO_INPUT, PREZZO_OCCHIO_OUTPUT
from bot.serper_base import cerca_serper_mirata
from bot.foto import costruisci_parts_foto
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
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
    if cascata_per(ruolo):
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
            url_usato = _gemini_url_effettivo(api_url, ruolo)
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
                    api_url, url_usato, resp.status_code, resp.text, ruolo)
                if modello_cambiato and attempt < max_retries_effettivi:
                    continue
            if resp.is_success:
                _gemini_registra_esito(True)
                log.info("GEMINI_USO | %s | %s", ruolo, modello_usato)
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


MAX_ROUNDS_FUNZIONE = 2  # Rialzato da 1 a 2 il 2026-09-14. Con 1, i log


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
        if cascata_per("cervello"):
            tentativi_effettivi += len(GEMINI_API_KEYS)

        backoff_seconds = 2
        for attempt in range(1, tentativi_effettivi + 1):
            try:
                # Timeout abbassato da 90 a 30s (richiesto dall'utente il
                # 2026-09-22, stesso motivo di chiama_gemini).
                url_usato = _gemini_url_effettivo(api_url, "cervello")
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
                        api_url, url_usato, resp.status_code, resp.text, "cervello")
                    if modello_cambiato and attempt < tentativi_effettivi:
                        continue
                    if _gemini_e_errore_quota_giornaliera(resp.status_code, resp.text):
                        _gemini_segna_key_quota_esaurita(key_usata, modello_usato, _gemini_secondi_retry(resp.text))
                        if (cascata_per("cervello") and attempt < tentativi_effettivi
                                and _gemini_url_effettivo(api_url, "cervello") != url_usato):
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
