"""Scalata dei modelli (richiesto dall'utente il 2026-10-03): Gemini resta il primo della catena (cascate per fase,
dal migliore al piu' leggero); quando la quota di TUTTA la cascata e' finita, o la chiamata Gemini fallisce, la
fase passa ai modelli di riserva in ordine (RISERVA_OCCHIO_MODELLI / RISERVA_CERVELLO_MODELLI, via OmniRoute),
ognuno col suo cooldown dichiarato dal provider (stessa tabella del pannello, cosi' quota e pause sono condivise).

Il verdetto resta deterministico: il modello di riserva produce lo stesso JSON, validato come quello di Gemini.
Differenza: nessuna ricerca on-demand (il Cervello di riserva usa i comp gia' nel prompt)."""
import json
import os

from bot.panel import (EXTRA_LLM_URL, NOTA_SENZA_RICERCA, RISERVA_CERVELLO_MODELLI, RISERVA_OCCHIO_MODELLI, _panel_chiama, _panel_pausa,
                       _panel_segna_errore, estrai_json_da_testo_llm)
from bot.schemas import CERVELLO_RESPONSE_SCHEMA_OPENAI, OCCHIO_RESPONSE_SCHEMA_GEMINI, _schema_gemini_to_openai
from bot.gemini_stato import gemini_cascata_esaurita
from bot.gemini_api import chiama_gemini
from bot.prompts import GEMINI_OCCHI_SYSTEM_PROMPT_JSON, prompt_cervello_compatto
from bot.foto import costruisci_parts_foto
from bot.logger import log
import time

ISTRUZIONE_SOLO_JSON = "\n\nRispondi SOLO con un oggetto JSON valido conforme a questo schema, senza altro testo:\n"


def riserva_attiva(lista):
    return bool(EXTRA_LLM_URL and lista)


def modelli_disponibili(lista, adesso=None):
    adesso = adesso if adesso is not None else time.time()
    return [m for m in lista if _panel_pausa.get(m, 0) <= adesso]


# Fattore sul target dei modelli di riserva, dalla mediana del loro target / target di Gemini sul pannello
# (2-3/10, 38 confronti per Ministral 14B, 8 per gpt-oss-120b, 5 per gpt-oss-20b molto dispersi). Formato env:
# RISERVA_FATTORI_TARGET="ministral-14b=1.0,gpt-oss-120b=0.95,gpt-oss-20b=0.55" (sottostringa del nome del modello).
# Pausa di Gemini dopo un 429 (2026-10-04): se la quota e' finita, ogni annuncio sprecava la chiamata (e secondi) prima
# di cadere sulla riserva. Dopo un 429 la fase salta Gemini per GEMINI_PAUSA_429_SECONDI e va dritta alla riserva;
# poi riprova (cosi' al reset della quota Gemini torna da solo).
GEMINI_PAUSA_429_SECONDI = int(os.environ.get("GEMINI_PAUSA_429_SECONDI", "300"))
_gemini_pausa_fino = {}


def gemini_in_pausa(ruolo):
    return time.time() < _gemini_pausa_fino.get(ruolo, 0)


def segna_gemini_in_pausa_se_429(ruolo, errore):
    """Se l'errore e' un 429 mette in pausa la fase `ruolo`. Ritorna True se l'ha messa."""
    if "429" in str(errore):
        _gemini_pausa_fino[ruolo] = time.time() + GEMINI_PAUSA_429_SECONDI
        return True
    return False


def _carica_fattori(testo):
    out = {}
    for voce in (testo or "").split(","):
        if "=" in voce:
            nome, _, val = voce.partition("=")
            try:
                out[nome.strip()] = float(val)
            except ValueError:
                pass
    return out


RISERVA_FATTORI_TARGET = _carica_fattori(os.environ.get(
    "RISERVA_FATTORI_TARGET", "ministral-14b=1.0,gpt-oss-120b=0.95,gpt-oss-20b=0.55"))


def fattore_target_riserva(modello):
    """Fattore da applicare al target di un modello di riserva (1.0 se sconosciuto). Pura."""
    for nome, f in RISERVA_FATTORI_TARGET.items():
        if nome and nome in (modello or ""):
            return f
    return 1.0


async def _prova_in_ordine(fase, lista, sistema_per, contenuto, max_tokens, valido):
    """Primo modello (non in pausa) che risponde con un JSON valido. Ritorna (dict, modello) o (None, None)."""
    for m in modelli_disponibili(lista):
        nudo = m.split("@")[0]
        compatto = m.endswith("@c")
        testo, ms, err = await _panel_chiama(nudo, sistema_per(compatto), contenuto, max_tokens)
        if err:
            _panel_segna_errore(m, err)
            log.info("RISERVA | %s | %s | ERR | %dms | errore=%s", fase, m, ms, err)
            continue
        d = estrai_json_da_testo_llm(testo)
        if d is None or not valido(d):
            log.info("RISERVA | %s | %s | ERR | %dms | errore=json_non_valido", fase, m, ms)
            continue
        log.info("RISERVA | %s | %s | ok | %dms", fase, m, ms)
        return d, m
    return None, None


async def occhio_con_riserva(system_prompt, user_text, photo_bytes_list, ruolo, response_schema):
    """Occhio JSON: Gemini per primo; riserva se la cascata e' esaurita o Gemini fallisce. Stesso ritorno di
    chiama_gemini (testo JSON, costo, token)."""
    usa_riserva = riserva_attiva(RISERVA_OCCHIO_MODELLI) and photo_bytes_list
    if usa_riserva and (gemini_cascata_esaurita(ruolo) or gemini_in_pausa(ruolo)):
        log.info("RISERVA | occhio | cascata Gemini '%s' esaurita o in pausa: si passa ai modelli di riserva", ruolo)
        risultato = None
    else:
        risultato = await chiama_gemini(system_prompt, user_text, photo_bytes_list, grounding=False,
                                        response_schema=response_schema, ruolo=ruolo)
        if not (usa_riserva and str(risultato[0]).startswith("[ERRORE")):
            return risultato
        segna_gemini_in_pausa_se_429(ruolo, risultato[0])
    parts = await costruisci_parts_foto(photo_bytes_list[:6])
    immagini = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + p["inline_data"]["data"]}}
                for p in parts]
    schema = json.dumps(_schema_gemini_to_openai(OCCHIO_RESPONSE_SCHEMA_GEMINI), ensure_ascii=False)
    sistema = GEMINI_OCCHI_SYSTEM_PROMPT_JSON + ISTRUZIONE_SOLO_JSON + schema
    d, _modello = await _prova_in_ordine("occhio", RISERVA_OCCHIO_MODELLI, lambda _c: sistema,
                                          [{"type": "text", "text": user_text}] + immagini, 4000,
                                          lambda x: isinstance(x, dict) and bool(x))
    if d is None:
        return risultato or ("[ERRORE: Gemini e modelli di riserva non disponibili]", 0.0, 0)
    return json.dumps(d, ensure_ascii=False), 0.0, 0


async def cervello_con_riserva(chiama_gemini_fn, ruolo, system_prompt, user_text, **kw):
    """Cervello: Gemini per primo (con le sue ricerche); riserva se la cascata e' esaurita o il verdetto manca.
    Ritorna la tupla a 5 elementi di chiama_gemini_cervello_forzato; il dict porta '_riserva' col modello usato."""
    usa_riserva = riserva_attiva(RISERVA_CERVELLO_MODELLI)
    if usa_riserva and (gemini_cascata_esaurita(ruolo) or gemini_in_pausa(ruolo)):
        log.info("RISERVA | cervello | cascata Gemini '%s' esaurita o in pausa: si passa ai modelli di riserva", ruolo)
        risultato = None
    else:
        risultato = await chiama_gemini_fn(system_prompt, user_text, **kw)
        if not (usa_riserva and risultato[0] is None):
            return risultato
        segna_gemini_in_pausa_se_429(ruolo, risultato[1])
    schema = json.dumps(CERVELLO_RESPONSE_SCHEMA_OPENAI, ensure_ascii=False)
    completo = system_prompt + ISTRUZIONE_SOLO_JSON + schema
    d, modello = await _prova_in_ordine(
        "cervello", RISERVA_CERVELLO_MODELLI,
        lambda compatto: prompt_cervello_compatto() if compatto else completo,
        user_text + NOTA_SENZA_RICERCA, 6000,
        lambda x: isinstance(x.get("prezzo_target_vendita_eur"), (int, float)) and x["prezzo_target_vendita_eur"] > 0)
    if d is None:
        return risultato or (None, "Gemini e modelli di riserva non disponibili", 0.0, 0, [])
    d["_riserva"] = modello
    fattore = fattore_target_riserva(modello)
    if fattore != 1.0 and isinstance(d.get("prezzo_target_vendita_eur"), (int, float)):
        log.info("RISERVA | cervello | %s | target %s -> x%.2f", modello, d["prezzo_target_vendita_eur"], fattore)
        d["prezzo_target_vendita_eur"] = round(d["prezzo_target_vendita_eur"] * fattore, 2)
    return d, None, 0.0, 0, []
