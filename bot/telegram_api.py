"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import json
import asyncio


from bot.config import TELEGRAM_API
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
def _spezza_per_telegram(text, max_len=3500):
    """Chunking condiviso da telegram_send_message e telegram_send_with_buttons
    (prima duplicato identico in entrambe). Taglia preferibilmente su riga
    vuota, poi su a capo, e solo come ultima risorsa a lunghezza fissa.

    FIX 2026-09-26 (bot congelato in produzione dalle 07:41 UTC, memoria da
    0,3 a 7,3 GB in un'ora): il resto dopo un taglio iniziava con lo stesso
    separatore "\\n\\n" su cui si era tagliato. Se nei successivi max_len
    caratteri non c'era un'altra riga vuota, rfind restituiva 0 (non -1),
    quindi split_at=0: si aggiungeva un chunk vuoto e il resto restava
    identico -> loop infinito sincrono che bloccava l'intero event loop
    (nessun log, nessun messaggio, nessun nuovo annuncio) e riempiva la RAM
    di stringhe vuote. Ora la ricerca parte da 1, il resto viene ripulito
    dagli a capo iniziali e un taglio a 0 non e' piu' possibile."""
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 1, max_len)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 1, max_len)
        if split_at <= 0:
            split_at = max_len
        pezzo = remaining[:split_at]
        if pezzo.strip():
            chunks.append(pezzo)
        remaining = remaining[split_at:].lstrip("\n")
    return chunks or [text]


TELEGRAM_MAX_TENTATIVI = 3
TELEGRAM_MAX_ATTESA_429_SECONDI = 60


async def _telegram_post(metodo, max_tentativi=TELEGRAM_MAX_TENTATIVI, **kwargs):
    """POST alla Bot API con retry su 429 (flood control, rispettando il
    retry_after indicato da Telegram) e su errori di rete. Prima ogni
    chiamata era un singolo post senza controllo dell'esito: un 429 durante
    un burst di annunci, o un timeout, faceva sparire la notifica senza
    nessuna traccia nei log. Ritorna la response (anche se non is_success:
    gli errori 400, es. Markdown non valido, li gestisce il chiamante) oppure
    None se tutti i tentativi sono falliti per errore di rete.

    Nei log NON compare mai l'URL (contiene il token del bot): solo il nome
    del metodo, lo status e il corpo della risposta di Telegram."""
    resp = None
    for tentativo in range(1, max_tentativi + 1):
        try:
            resp = await hc._client_telegram.post(f"{TELEGRAM_API}/{metodo}", **kwargs)
        except Exception as e:
            log.warning("Telegram %s: errore di rete (tentativo %d/%d): %s",
                        metodo, tentativo, max_tentativi, type(e).__name__)
            resp = None
            if tentativo < max_tentativi:
                await asyncio.sleep(2 * tentativo)
            continue
        if resp.status_code == 429 and tentativo < max_tentativi:
            try:
                retry_after = float(resp.json().get("parameters", {}).get("retry_after", 5))
            except Exception:
                retry_after = 5.0
            attesa = min(retry_after, TELEGRAM_MAX_ATTESA_429_SECONDI) + 0.5
            log.warning("Telegram %s: 429 flood control, attendo %.1fs (tentativo %d/%d)",
                        metodo, attesa, tentativo, max_tentativi)
            await asyncio.sleep(attesa)
            continue
        return resp
    return resp


def _telegram_esito_ok(resp, metodo, contesto=""):
    """True se la chiamata e' andata a buon fine, altrimenti logga a ERROR
    (non piu' fallimenti silenziosi) e ritorna False."""
    if resp is not None and resp.is_success:
        return True
    dettaglio = f"HTTP {resp.status_code}: {resp.text[:300]}" if resp is not None else "nessuna risposta (errore di rete)"
    log.error("Telegram %s FALLITA%s -- %s", metodo, f" ({contesto})" if contesto else "", dettaglio)
    return False


def _parametri_reply(reply_to):
    """Campo reply_parameters della Bot API per rispondere a un messaggio
    (usato per agganciare il verdetto alla galleria mandata in anticipo).
    allow_sending_without_reply: se il messaggio originale non esiste piu'
    (cancellato a mano) il verdetto arriva lo stesso, solo non agganciato."""
    if not reply_to:
        return {}
    return {"reply_parameters": {"message_id": int(reply_to), "allow_sending_without_reply": True}}


def _primo_message_id(resp):
    """message_id del (primo) messaggio creato da sendPhoto/sendMediaGroup,
    o None se la chiamata e' fallita. sendMediaGroup ritorna una lista di
    messaggi (uno per foto): si risponde al primo, che porta la didascalia."""
    if resp is None or not resp.is_success:
        return None
    try:
        risultato = resp.json().get("result")
        if isinstance(risultato, list):
            risultato = risultato[0] if risultato else None
        return (risultato or {}).get("message_id")
    except Exception:
        return None


async def telegram_send_message(chat_id, text, disable_notification=False, reply_to=None):
    MAX_LEN = 3500
    for i, chunk in enumerate(_spezza_per_telegram(text, MAX_LEN)):
        # Solo il primo pezzo risponde alla galleria: i successivi seguono
        # comunque subito sotto, ripetere la citazione sarebbe solo rumore.
        extra_reply = _parametri_reply(reply_to) if i == 0 else {}
        resp = await _telegram_post(
            "sendMessage",
            json={
                "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown",
                "disable_web_page_preview": True, "disable_notification": disable_notification,
                **extra_reply,
            },
        )
        if resp is not None and not resp.is_success:
            log.warning("sendMessage Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode", resp.status_code, resp.text[:300])
            resp = await _telegram_post(
                "sendMessage",
                json={
                    "chat_id": chat_id, "text": chunk,
                    "disable_web_page_preview": True, "disable_notification": disable_notification,
                    **extra_reply,
                },
            )
        _telegram_esito_ok(resp, "sendMessage", "senza parse_mode")


async def telegram_send_photo(chat_id, photo_bytes, caption=None, disable_notification=False):
    """Ritorna il message_id della foto inviata (None se fallita)."""
    files = {"photo": ("photo.jpg", photo_bytes)}
    data = {"chat_id": chat_id, "disable_notification": disable_notification}
    if caption:
        data["caption"] = caption[:1024]
    resp = await _telegram_post("sendPhoto", data=data, files=files, timeout=30)
    _telegram_esito_ok(resp, "sendPhoto")
    return _primo_message_id(resp)


async def telegram_send_photo_con_bottone(chat_id, photo_bytes, caption, url_annuncio, disable_notification=False):
    """Foto con didascalia Markdown (max 1024) e bottone "Apri su Vinted". Se Telegram rifiuta il Markdown ritenta
    senza parse_mode. Ritorna il message_id (None se fallita)."""
    keyboard = json.dumps({"inline_keyboard": [[{"text": "🔗 Apri su Vinted", "url": url_annuncio}]]})
    data = {"chat_id": chat_id, "disable_notification": disable_notification, "caption": (caption or "")[:1024],
            "reply_markup": keyboard}
    resp = await _telegram_post("sendPhoto", data={**data, "parse_mode": "Markdown"},
                                files={"photo": ("photo.jpg", photo_bytes)}, timeout=30)
    if resp is not None and not resp.is_success:
        log.warning("telegram_send_photo_con_bottone: Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode",
                    resp.status_code, resp.text[:300])
        resp = await _telegram_post("sendPhoto", data=data, files={"photo": ("photo.jpg", photo_bytes)}, timeout=30)
    _telegram_esito_ok(resp, "sendPhoto", "con bottone")
    return _primo_message_id(resp)


async def telegram_send_media_group(chat_id, photos_bytes_list, caption=None, disable_notification=False,
                                    parse_mode=None, reply_to=None):
    """Ritorna il message_id della prima foto dell'album (None se fallito). Con parse_mode la didascalia e'
    formattata; se Telegram la rifiuta (400) si ritenta senza formattazione."""
    if not photos_bytes_list:
        return None
    files = {}
    for i, photo_bytes in enumerate(photos_bytes_list[:10]):
        files[f"photo{i}"] = (f"photo{i}.jpg", photo_bytes, "image/jpeg")

    def _media(con_parse):
        media = []
        for i in range(len(files)):
            item = {"type": "photo", "media": f"attach://photo{i}"}
            if i == 0 and caption:
                item["caption"] = caption[:1024]
                if con_parse and parse_mode:
                    item["parse_mode"] = parse_mode
            media.append(item)
        return media

    extra = {"reply_to_message_id": reply_to} if reply_to else {}
    resp = await _telegram_post(
        "sendMediaGroup",
        data={"chat_id": chat_id, "media": json.dumps(_media(True)), "disable_notification": disable_notification, **extra},
        files=files,
        timeout=60,
    )
    if parse_mode and resp is not None and not resp.is_success:
        log.warning("telegram_send_media_group: %s fallita -- HTTP %d: %s -- ritento senza parse_mode",
                    parse_mode, resp.status_code, resp.text[:300])
        resp = await _telegram_post(
            "sendMediaGroup",
            data={"chat_id": chat_id, "media": json.dumps(_media(False)), "disable_notification": disable_notification, **extra},
            files=files,
            timeout=60,
        )
    _telegram_esito_ok(resp, "sendMediaGroup", f"{len(files)} foto")
    return _primo_message_id(resp)


async def telegram_send_with_buttons(chat_id, text, url_annuncio, item_id=None, disable_notification=False,
                                     reply_to=None):
    """Manda 'text' con i bottoni inline in fondo. Bug corretto il 2026-09-19:
    a differenza di telegram_send_message, questa funzione non spezzava mai
    il testo -- oltre 4096 caratteri (limite Telegram per sendMessage) la
    richiesta falliva con lo STESSO errore sia col tentativo Markdown sia col
    retry senza parse_mode (il limite di lunghezza non c'entra col parse_mode),
    quindi l'intero messaggio testuale spariva silenziosamente: le foto
    (mandate prima, in una chiamata separata) arrivavano, il verdetto/analisi
    no. Osservato in produzione con DEBUG_CONFRONTO_COMP_TELEGRAM=true (il
    pool di ricerca grezzo in coda al messaggio spingeva facilmente oltre
    4096), ma il bug esisteva a prescindere per qualunque messaggio
    abbastanza lungo. Ora usa lo stesso chunking di telegram_send_message,
    con i bottoni spostati sull'ULTIMO chunk (dove servono davvero: aprire
    l'annuncio/scrivere al venditore dopo aver letto tutto)."""
    chunks = _spezza_per_telegram(text, 3500)

    keyboard = {"inline_keyboard": [[
        {"text": "🔗 Apri su Vinted", "url": url_annuncio},
    ]]}
    if item_id:
        keyboard["inline_keyboard"].append([
            {"text": "💬 Scrivi venditore", "url": f"https://www.vinted.it/items/{item_id}"},
        ])

    primo_id = None
    for i, chunk in enumerate(chunks):
        e_ultimo_chunk = (i == len(chunks) - 1)
        payload_base = {
            "chat_id": chat_id, "text": chunk, "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }
        if e_ultimo_chunk:
            payload_base["reply_markup"] = keyboard
        if i == 0:
            payload_base.update(_parametri_reply(reply_to))
        resp = await _telegram_post(
            "sendMessage",
            json={**payload_base, "parse_mode": "Markdown"},
        )
        if resp is not None and not resp.is_success:
            log.warning(
                "telegram_send_with_buttons: Markdown fallita -- HTTP %d: %s -- ritento senza parse_mode",
                resp.status_code, resp.text[:300],
            )
            resp = await _telegram_post("sendMessage", json=payload_base)
        _telegram_esito_ok(resp, "sendMessage", f"con bottoni, chunk {i + 1}/{len(chunks)}")
        if i == 0:
            primo_id = _primo_message_id(resp)
    return primo_id


async def telegram_edit_message(chat_id, message_id, text, url_annuncio=None):
    """Modifica un messaggio GIA' inviato dal bot (Bot API editMessageText)
    invece di mandarne un altro: nessuna nuova notifica, la chat non si
    riempie. Punti da conoscere:
     - editMessageText senza reply_markup TOGLIE i bottoni inline, quindi il
       bottone "Apri su Vinted" va rimandato a ogni modifica;
     - Telegram risponde 400 "message is not modified" se il testo e' uguale:
       non e' un errore, si ignora;
     - si possono modificare solo messaggi di testo del bot stesso; la
       notifica push gia' consegnata non cambia (resta il testo originale).
    Ritorna True se la modifica e' andata a buon fine."""
    if not message_id:
        return False
    payload = {"chat_id": chat_id, "message_id": int(message_id), "text": text[:4000],
               "disable_web_page_preview": True}
    if url_annuncio:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "🔗 Apri su Vinted", "url": url_annuncio}]]}
    resp = await _telegram_post("editMessageText", json={**payload, "parse_mode": "Markdown"})
    if resp is not None and not resp.is_success:
        if "not modified" in (resp.text or ""):
            return True
        resp = await _telegram_post("editMessageText", json=payload)
        if resp is not None and not resp.is_success and "not modified" in (resp.text or ""):
            return True
    return bool(resp is not None and resp.is_success)


async def telegram_edit_caption(chat_id, message_id, caption, url_annuncio=None):
    """Modifica la didascalia di una foto (o della prima foto di un album) GIA' inviata dal bot: nessuna nuova
    notifica. Su un album i bottoni non esistono (url_annuncio va passato solo per una foto singola: editMessageCaption
    senza reply_markup toglie il bottone). Ritorna True se la modifica e' andata a buon fine ("not modified" = ok)."""
    if not message_id:
        return False
    payload = {"chat_id": chat_id, "message_id": int(message_id), "caption": (caption or "")[:1024]}
    if url_annuncio:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "🔗 Apri su Vinted", "url": url_annuncio}]]}
    resp = await _telegram_post("editMessageCaption", json={**payload, "parse_mode": "Markdown"})
    if resp is not None and not resp.is_success:
        if "not modified" in (resp.text or ""):
            return True
        resp = await _telegram_post("editMessageCaption", json=payload)
        if resp is not None and not resp.is_success and "not modified" in (resp.text or ""):
            return True
    return bool(resp is not None and resp.is_success)
