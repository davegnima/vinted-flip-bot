"""Radar v2 (non moda), modalita' OMBRA: per ogni annuncio del radar calcola la rivendita verosimile dagli annunci simili
in vendita adesso (valore_mercato) e REGISTRA il verdetto; non manda messaggi. Proposta: docs/proposta-radar-v2-2026-10-23.md.

Attivo con RADAR_V2_OMBRA=1. Log `RADAR V2 OMBRA |` ed evento `radar_v2` nel DB. Tetto di sicurezza: RADAR_V2_MAX_GIORNO ricerche
di comparabili al giorno (le stime si riusano per RADAR_V2_CACHE_ORE ore, per marca e testo).
"""
import os
import time
import asyncio
import traceback
from urllib.parse import quote

from bot import db
from bot.comps import _cerca_vinted_testo_diretto_con_fallback_serper
from bot.logger import log
from bot.radar import RADAR_SPESA_MAX, parola_vietata, radar_in_pausa
from bot.verdetto import _a_float, _estrai_item_id_da_url
from bot.valore_mercato import comparabili_simili, e_un_pezzo, parse_comp, query_comp, solo_usato, stima_mercato, valuta
# ---- fine import ----

RADAR_V2_OMBRA = os.environ.get("RADAR_V2_OMBRA", "0").strip() in ("1", "true", "si")
RADAR_V2_MAX_GIORNO = int(os.environ.get("RADAR_V2_MAX_GIORNO", "3000") or 3000)
RADAR_V2_CACHE_ORE = float(os.environ.get("RADAR_V2_CACHE_ORE", "6") or 6)
RADAR_V2_PARALLELO = int(os.environ.get("RADAR_V2_PARALLELO", "2") or 2)

_visti = set()
_cache = {}  # testo ricerca -> (ts, [prezzi], n_grezzi)
_conteggio = {"giorno": None, "n": 0}
_sem = asyncio.Semaphore(RADAR_V2_PARALLELO)


def url_comparabili(testo):
    return f"https://www.vinted.it/catalog?search_text={quote(testo)}&order=newest_first"


def _entro_il_tetto(adesso=None):
    """True se si puo' fare un'altra ricerca di comparabili oggi (UTC); conta la chiamata."""
    giorno = time.strftime("%Y-%m-%d", time.gmtime(adesso or time.time()))
    if _conteggio["giorno"] != giorno:
        _conteggio.update(giorno=giorno, n=0)
    if _conteggio["n"] >= RADAR_V2_MAX_GIORNO:
        return False
    _conteggio["n"] += 1
    return True


async def _prezzi_simili(testo, titolo, prezzo, brand=None):
    """(prezzi richiesti di annunci simili usati, n grezzi, dalla_cache) o (None, 0, False) se non disponibile."""
    adesso = time.time()
    voce = _cache.get(testo)
    if voce and adesso - voce[0] < RADAR_V2_CACHE_ORE * 3600:
        return voce[1], voce[2], True
    if not _entro_il_tetto(adesso):
        return None, 0, False
    async with _sem:
        risposta, ok, _mappa = await _cerca_vinted_testo_diretto_con_fallback_serper(url_comparabili(testo))
    if not ok:
        return None, 0, False
    comps = parse_comp(risposta)
    usati = [(t, p) for t, p in comparabili_simili(solo_usato(comps), testo, brand) if not (t == titolo and abs(p - prezzo) < 0.01)]
    prezzi = [p for _, p in usati]
    _cache[testo] = (adesso, prezzi, len(comps))
    return prezzi, len(comps), False


async def ombra(parsed, url):
    """Valuta in silenzio un annuncio del radar e registra il verdetto. Mai messaggi, mai eccezioni verso il chiamante."""
    if not RADAR_V2_OMBRA or radar_in_pausa():
        return
    try:
        item_id = _estrai_item_id_da_url(url)
        if not item_id or item_id in _visti:
            return
        _visti.add(item_id)
        if len(_visti) > 20000:
            _visti.clear()
        titolo = parsed.get("title") or ""
        prezzo = _a_float(parsed.get("price"), None)
        brand = parsed.get("brand")
        base = {"titolo": titolo[:120], "prezzo": prezzo, "brand": brand}
        if prezzo is None or prezzo <= 0 or (RADAR_SPESA_MAX and prezzo > RADAR_SPESA_MAX):
            return
        vietata = parola_vietata(titolo)
        if vietata:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "parola_vietata:" + vietata})
            return
        pezzo = e_un_pezzo(titolo)
        if pezzo:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "pezzo_o_accessorio:" + pezzo})
            return
        testo = query_comp(titolo, brand)
        prezzi, n_grezzi, dalla_cache = await _prezzi_simili(testo, titolo, prezzo, brand)
        if prezzi is None:
            db.scrivi_evento("radar_v2", item_id, brand, {**base, "ok": False, "motivo": "comparabili_non_disponibili", "q": testo})
            return
        v = valuta(prezzo, stima_mercato(prezzi))
        dati = {**base, "q": testo, "n_grezzi": n_grezzi, "n_usati": len(prezzi), "cache": dalla_cache, **v}
        log.info("RADAR V2 OMBRA | item=%s | ok=%s | motivo=%s | prezzo=%s | rivendita=%s | margine=%s | roi=%s | n=%s | aff=%s | q=%s | titolo=%s",
                 item_id, v["ok"], v["motivo"], prezzo, v.get("rivendita"), v.get("margine"), v.get("roi"), len(prezzi),
                 v.get("affidabilita"), testo, titolo[:60])
        db.scrivi_evento("radar_v2", item_id, brand, dati)
    except Exception:
        log.warning("Radar v2 ombra: annuncio non valutato:\n%s", traceback.format_exc())
