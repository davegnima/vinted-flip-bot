"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import json
import asyncio


from bot.gemini_api import CERVELLO_FUNCTION_DECLARATION, ISTRUZIONE_FASE_JSON, MAX_ROUNDS_FUNZIONE
from bot.schemas import CERVELLO_RESPONSE_SCHEMA_OPENAI
from bot.config import OPENAI_API_KEY, OPENAI_API_URL_CERVELLO, OPENAI_MODEL_CERVELLO, PREZZO_CERVELLO_OPENAI_INPUT, PREZZO_CERVELLO_OPENAI_OUTPUT
from bot.serper_base import cerca_serper_mirata
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
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
