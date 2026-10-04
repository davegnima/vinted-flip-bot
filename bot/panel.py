"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import json
import time
import asyncio
import traceback


from bot.schemas import CERVELLO_RESPONSE_SCHEMA_OPENAI, OCCHIO_RESPONSE_SCHEMA_GEMINI, _schema_gemini_to_openai
from bot.gemini_stato import GEMINI_MODELLI_RISERVA, tutti_i_modelli_cascata
from bot.prompts import GEMINI_CERVELLO_SYSTEM_PROMPT, GEMINI_OCCHI_SYSTEM_PROMPT_JSON, prompt_cervello_compatto
from bot.config import GEMINI_MODEL_CERVELLO, GEMINI_MODEL_OCCHIO, _env_float
from bot.verdetto import calcola_verdetto, valida_payload_cervello
from bot.foto import costruisci_parts_foto
from bot.logger import log
from bot import db
from bot.occhio import valida_payload_occhio
from bot import http_clients as hc
# ---- fine import ----
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
# Modelli di RISERVA del flusso principale (via lo stesso gateway): quando le cascate Gemini sono esaurite, o una
# chiamata Gemini fallisce, la fase passa a questi modelli in ordine (dal migliore). Il suffisso @c usa il prompt
# compatto del Cervello. Vedi riserva_llm. Restano anche nel pannello (richiesto dall'utente: confronto giornaliero di qualita' e costo).
RISERVA_OCCHIO_MODELLI = [m.strip() for m in (os.environ.get("RISERVA_OCCHIO_MODELLI") or "").split(",") if m.strip()]
RISERVA_CERVELLO_MODELLI = [m.strip() for m in (os.environ.get("RISERVA_CERVELLO_MODELLI") or "").split(",") if m.strip()]
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
    principali = {GEMINI_MODEL_OCCHIO, GEMINI_MODEL_CERVELLO, *GEMINI_MODELLI_RISERVA, *tutti_i_modelli_cascata()}
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


_panel_reset_s = {}   # modello -> secondi di attesa dichiarati dal provider nell'ultimo 429 (dal corpo dell'errore)


def secondi_reset_da_corpo(testo):
    """Secondi d'attesa dichiarati in un errore 429: 'reset_seconds' (OmniRoute), 'reset after 4m 40s',
    'try again in 5m23.5s' (Groq), 'reset after 3s'. None se non indicati."""
    if not testo:
        return None
    m = re.search(r'"reset_seconds"\s*:\s*(\d+)', testo)
    if m:
        return float(m.group(1))
    m = re.search(r'(?:reset after|try again in)\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?', testo, re.IGNORECASE)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return None


def _panel_segna_errore(modello, err, adesso=None):
    """Quota/accesso/modello dismesso: pausa, per non sprecare chiamate e riprovare piu' tardi. Sul 429 la pausa
    segue il tempo dichiarato dal provider (3 s di Mistral, 5 min di Groq, mezzanotte di OpenRouter), non un
    valore fisso: prima un 429 da 3 secondi fermava il modello per 30 minuti."""
    adesso = adesso if adesso is not None else time.time()
    nudo = modello.split("@")[0]      # _panel_chiama registra il reset col nome senza suffisso @c
    attesa = (_panel_reset_s.pop(modello, None) or _panel_reset_s.pop(nudo, None)) if err == "http429" else None
    if attesa is not None:
        _panel_pausa[modello] = adesso + min(max(attesa + 5, 10), 6 * 3600)
    elif err in ("http429", "http402", "http403"):
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


async def _panel_chiama(modello, system, user_content, max_tokens, uso=None):
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
                # il corpo dell'errore dice il vero motivo (limite al secondo, quota finita, chiave, modello...)
                log.warning("PANEL HTTP %d da %s: %s", resp.status_code, modello, (resp.text or "")[:300].replace("\n", " "))
                if resp.status_code == 429:
                    attesa = secondi_reset_da_corpo(resp.text)
                    if attesa is not None:
                        _panel_reset_s[modello] = attesa
                return None, ms, f"http{resp.status_code}"
            dati = resp.json()
            testo = (dati.get("choices") or [{}])[0].get("message", {}).get("content")
            if uso is not None:   # token reali consumati (ingresso/uscita): serve a confrontare costo e quota dei modelli
                u = dati.get("usage") or {}
                uso["tok"] = f"{u.get('prompt_tokens', 0)}/{u.get('completion_tokens', 0)}"
            return testo, ms, None
        except Exception as e:
            return None, int((time.time() - t0) * 1000), type(e).__name__


def _riga_panel(tipo, item_id, brand, modello, ok, ms, **campi):
    extra = " | ".join(f"{k}={v}" for k, v in campi.items() if v is not None)
    log.info("PANEL | %s | %s | %s | %s | %s | %dms%s", tipo, item_id, brand or "-", modello,
             "ok" if ok else "ERR", ms, f" | {extra}" if extra else "")
    db.scrivi_evento("panel", item_id, brand, {"tipo": tipo, "modello": modello, "ok": bool(ok), "ms": ms, **campi})


def _campi_occhio_panel(o, problemi):
    return {"problemi": len(problemi), "legit": o.get("verdetto_legit"), "conf": o.get("confidenza_legit"),
            "evid": o.get("qualita_evidenza"), "cond": o.get("condizione_osservata"),
            "brand_letto": str(o.get("brand_letto_etichetta") or "")[:30] or None,
            "capo": str(o.get("modello_riconosciuto") or "")[:40] or None,
            "motivo_legit": str(o.get("motivo_sintetico") or "").replace("|", "/").replace("\n", " ")[:100] or None}


async def _panel_occhio_modello(item_id, brand, modello, system, user_text, immagini):
    contenuto = [{"type": "text", "text": user_text}] + immagini
    uso = {}
    testo, ms, err = await _panel_chiama(modello, system, contenuto, 4000, uso)
    if err:
        _panel_segna_errore(modello, err)
        return _riga_panel("occhio", item_id, brand, modello, False, ms, errore=err)
    d = estrai_json_da_testo_llm(testo)
    if d is None:
        return _riga_panel("occhio", item_id, brand, modello, False, ms, errore="json_non_valido", tok=uso.get("tok"))
    try:
        o, problemi = valida_payload_occhio(d)
        _riga_panel("occhio", item_id, brand, modello, True, ms, tok=uso.get("tok"), **_campi_occhio_panel(o, problemi))
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


# Il prompt del Cervello cita la function cerca_comp_prezzo, che ai modelli del pannello/riserva non viene passata:
# Groq rispondeva 400 "Tool choice is none, but model called a tool" (15+15 volte in 12 ore). Il testo toglie l'invito.
NOTA_SENZA_RICERCA = ("\n\nNOTA: qui NON hai strumenti ne' funzioni: non chiamare cerca_comp_prezzo e ignora ogni invito a "
                      "cercare sul web. Rispondi subito con il JSON usando solo i dati e i comp presenti qui; se sono scarsi "
                      "abbassa la confidenza e marca fonte='memoria_modello' ogni prezzo che non compare nei dati ricevuti.")


async def _panel_cervello_modello(item_id, brand, modello, system, user_text, prezzo, system_compatto=None):
    nome = modello_chiamato = modello
    if modello.endswith("@c"):
        modello, system = modello[:-2], system_compatto or prompt_cervello_compatto()
    uso = {}
    testo, ms, err = await _panel_chiama(modello, system, user_text + NOTA_SENZA_RICERCA, 6000, uso)
    if err:
        _panel_segna_errore(modello_chiamato, err)
        return _riga_panel("cervello", item_id, brand, nome, False, ms, errore=err)
    d = estrai_json_da_testo_llm(testo)
    if d is None:
        return _riga_panel("cervello", item_id, brand, nome, False, ms, errore="json_non_valido", tok=uso.get("tok"))
    try:
        v, problemi = valida_payload_cervello(d)
        vc = calcola_verdetto(v, prezzo)
        _riga_panel("cervello", item_id, brand, nome, True, ms, tok=uso.get("tok"), target=_fmt0(v.get("prezzo_target_vendita_eur")),
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
