"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import time
import asyncio
import base64
from io import BytesIO

from PIL import Image

from bot.costanti import IMAGE_DOWNLOAD_HEADERS
from bot.http_clients import _prossimo_client_vinted
from bot.proxy import _registra_banda
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
# ---------------------------------------------------------------------------
# FOTO VIA IP RAILWAY (aggiunto 2026-09-27, utente: "fai tutte ip railway con
# backup proxies"). La sonda banda ha verificato che il CDN immagini
# (images1.vinted.net, dominio separato dal sito protetto da Datadome) serve
# le foto anche senza proxy. Le foto erano fino a 10 per annuncio via proxy:
# ora passano dal client generico (IP di Railway, nessun costo di banda
# proxy), e i proxy restano solo come riserva.
#
# Interruttore automatico: dopo FOTO_DIRETTE_SOGLIA_FALLIMENTI fallimenti di
# fila "da IP" (403/429/5xx/timeout, NON i 404 che sono foto rimosse) il
# download diretto si spegne per FOTO_DIRETTE_PAUSA_SECONDI e tutte le foto
# vanno via proxy -- senza, un ban dell'IP Railway farebbe provare il diretto
# (e aspettarne il fallimento) su OGNI foto di OGNI annuncio, rallentando
# tutta la pipeline. Dopo la pausa riprova da solo.
# ---------------------------------------------------------------------------
FOTO_DIRETTE_ABILITATE = os.environ.get("FOTO_DIRETTE", "1").strip() != "0"
FOTO_DIRETTE_SOGLIA_FALLIMENTI = 3
FOTO_DIRETTE_PAUSA_SECONDI = 3600
_foto_dirette_stato = {"fallimenti_di_fila": 0, "spente_fino_a": 0.0}


def _foto_dirette_attive():
    return FOTO_DIRETTE_ABILITATE and time.time() >= _foto_dirette_stato["spente_fino_a"]


def _foto_dirette_registra(ok, dettaglio=None):
    if ok:
        if _foto_dirette_stato["fallimenti_di_fila"] >= FOTO_DIRETTE_SOGLIA_FALLIMENTI:
            log.info("Foto via IP Railway di nuovo funzionanti dopo la pausa.")
        _foto_dirette_stato["fallimenti_di_fila"] = 0
        return
    _foto_dirette_stato["fallimenti_di_fila"] += 1
    if _foto_dirette_stato["fallimenti_di_fila"] == FOTO_DIRETTE_SOGLIA_FALLIMENTI:
        _foto_dirette_stato["spente_fino_a"] = time.time() + FOTO_DIRETTE_PAUSA_SECONDI
        log.warning(
            "FOTO DIRETTE SPENTE per %d min dopo %d fallimenti di fila dall'IP Railway "
            "(ultimo: %s) -- possibile blocco del CDN immagini, tutte le foto passano dai proxy.",
            FOTO_DIRETTE_PAUSA_SECONDI // 60, FOTO_DIRETTE_SOGLIA_FALLIMENTI, dettaglio,
        )
    elif _foto_dirette_stato["fallimenti_di_fila"] > FOTO_DIRETTE_SOGLIA_FALLIMENTI:
        # Tentativo di prova dopo la pausa fallito: si rispegne subito.
        _foto_dirette_stato["spente_fino_a"] = time.time() + FOTO_DIRETTE_PAUSA_SECONDI


async def _download_foto_diretta(url, headers):
    """Un solo tentativo dall'IP Railway. Ritorna i byte o None (e in quel
    caso il chiamante passa ai proxy)."""
    try:
        resp = await hc._client_generico.get(url, headers=headers, timeout=12)
        _registra_banda(url, resp, tipo="foto_diretta")
        if resp.is_success and resp.content:
            _foto_dirette_registra(True)
            return resp.content
        if resp.status_code != 404:  # 404 = foto rimossa, non un problema di IP
            _foto_dirette_registra(False, f"HTTP {resp.status_code}")
        log.info("Foto via IP Railway fallita (HTTP %s), passo ai proxy: %s", resp.status_code, url)
    except Exception as e:
        _foto_dirette_registra(False, f"{type(e).__name__}: {e}")
        log.info("Foto via IP Railway fallita (%s), passo ai proxy: %s", type(e).__name__, url)
    return None


async def download_image_bytes(url, referer="https://www.vinted.it/", max_retries=3):
    headers = dict(IMAGE_DOWNLOAD_HEADERS)
    headers["Referer"] = referer
    if hc._client_generico is not None and _foto_dirette_attive():
        diretta = await _download_foto_diretta(url, headers)
        if diretta:
            return diretta
    # TEMP DIAGNOSTIC: this used to swallow every failure silently (bare
    # "except Exception: pass" and no logging even on a non-ok status), so
    # there was no way to tell a 403/429 rate-limit apart from a timeout or
    # a proxy connection failure from the logs alone. Remove once diagnosed.
    ultimo_dettaglio = None
    for attempt in range(1, max_retries + 1):
        try:
            client = _prossimo_client_vinted()
            resp = await client.get(url, headers=headers, timeout=18)
            _registra_banda(url, resp)
            if resp.is_success:
                return resp.content
            ultimo_dettaglio = f"HTTP {resp.status_code}"
        except Exception as e:
            ultimo_dettaglio = f"{type(e).__name__}: {e}"
        await asyncio.sleep(0.6 * attempt)
    log.warning(
        "download_image_bytes: fallito dopo %d tentativi per %s -- ultimo errore: %s",
        max_retries, url, ultimo_dettaglio,
    )
    return None


def optimize_image_bytes(img_bytes, max_size=768):
    try:
        img = Image.open(BytesIO(img_bytes))
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return img_bytes


def _costruisci_parts_foto_sync(photo_bytes_list):
    parts = []
    for img_bytes in photo_bytes_list:
        optimized = optimize_image_bytes(img_bytes)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(optimized).decode("utf-8")}})
    return parts


async def costruisci_parts_foto(photo_bytes_list):
    """Ridimensionamento PIL + base64 di 10 foto e' lavoro CPU puro: dentro
    il loop asyncio bloccherebbe tutto per qualche centinaio di millisecondi
    per annuncio, proprio mentre altri annunci stanno aspettando risposte di
    rete. asyncio.to_thread lo sposta su un thread worker e lascia il loop
    libero. E' l'unico punto del bot dove serve ancora un thread: tutto il
    resto e' attesa di rete, che asyncio gestisce nativamente."""
    if not photo_bytes_list:
        return []
    return await asyncio.to_thread(_costruisci_parts_foto_sync, photo_bytes_list)
