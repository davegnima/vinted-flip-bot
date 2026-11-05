"""API Vinted con token anonimo (5/11): comparabili e foto senza passare dalle pagine HTML.

Dal 3/11 (20:08 UTC) Vinted risponde alle pagine annuncio e catalogo con la shell 'Session refresh' (~19,6 KB, nessun
dato) e a /api/v2/items/<id> con 401. Il tracker (Vinted-Notifications, pyVintedVN/requester.py) legge Vinted senza
problemi con il suo metodo: una richiesta HEAD a www.vinted.it consegna i cookie anonimi `access_token_web` e `anon_id`;
con quel token (Authorization: Bearer + x-anon-id + header Sec-Fetch di una chiamata XHR) si interroga
api.vinted.it/svc-catalogue/items, che risponde in JSON. Qui si fa lo stesso, per proxy del pool.

Le funzioni di parsing sono pure (nessuna rete) e testate; la rete passa da `api_get`. Nessun cookie dell'utente."""
import asyncio
import json
import os
import re
import time
from urllib.parse import parse_qsl, urlsplit

from bot.comps_filtri import _normalizza_titolo_per_link
from bot.costanti import VINTED_HEADERS
from bot.logger import log
from bot.proxy import _CLIENT_VINTED_POOL, _CLIENT_VINTED_POOL_KEYS, _ETICHETTA_PER_CHIAVE_PROXY, _etichetta_proxy, _registra_banda, _registra_esito_proxy
from bot.http_clients import _prossimo_indice_vinted
from bot.vinted_http import _attendi_turno_vinted

# Interruttore: VINTED_API=0 riporta al solo scraping HTML di prima.
VINTED_API_ATTIVA = os.environ.get("VINTED_API", "1").strip().lower() not in ("0", "false", "no", "")
HOST_WWW = "https://www.vinted.it"
HOST_API = "https://api.vinted.it"
PERCORSO_CATALOGO = "/svc-catalogue/items"
SESSIONE_VALIDA_SECONDI = 20 * 60
MAX_ARTICOLI_CATALOGO = 15

# {chiave proxy: (access_token_web, anon_id, istante)}: ogni proxy ha la sua sessione anonima (stesso IP per token e richieste).
_SESSIONI = {}


# ---------------------------------------------------------------------------
# parti pure
# ---------------------------------------------------------------------------
def parametri_da_url_catalogo(url, per_page=20, pagina=1):
    """Parametri dell'API svc-catalogue a partire dall'URL web di una ricerca (stessa traduzione del tracker). Pura.
    I filtri vuoti non si mandano (l'API risponde 400)."""
    coppie = parse_qsl(urlsplit(url or "").query)

    def valori(nome):
        return [v for k, v in coppie if k == nome]

    mappa = {
        "search_text": "+".join(valori("search_text")),
        "attribute_ids[catalog]": ",".join(valori("catalog[]")),
        "attribute_ids[color]": ",".join(valori("color_ids[]")),
        "attribute_ids[brand]": ",".join(valori("brand_ids[]")),
        "attribute_ids[size]": ",".join(valori("size_ids[]")),
        "attribute_ids[material]": ",".join(valori("material_ids[]")),
        "attribute_ids[status]": ",".join(valori("status_ids[]")),
        "currency": ",".join(valori("currency")),
        "price_to": ",".join(valori("price_to")),
        "price_from": ",".join(valori("price_from")),
        "order": ",".join(valori("order")),
        "page": pagina,
        "per_page": per_page,
    }
    return {k: v for k, v in mappa.items() if v not in ("", None)}


def _prezzo(voce):
    p = voce.get("price")
    try:
        return float(p.get("amount") if isinstance(p, dict) else p)
    except (TypeError, ValueError, AttributeError):
        return None


def articoli_da_json_catalogo(testo_json, max_articoli=MAX_ARTICOLI_CATALOGO):
    """(testo, mappa_url, miniature) dalla risposta JSON del catalogo, negli stessi formati dello scraping HTML:
    testo '- titolo — €prezzo' una riga per articolo, mappa {(titolo normalizzato, prezzo 2f): url}, miniature {id: url}. Pura.
    Senza articoli: ('', {}, {})."""
    try:
        dati = json.loads(testo_json)
    except Exception:
        return "", {}, {}
    voci = dati.get("items") if isinstance(dati, dict) else None
    if not isinstance(voci, list):
        return "", {}, {}
    righe, mappa, miniature, visti = [], {}, {}, set()
    for v in voci:
        if not isinstance(v, dict):
            continue
        titolo = str(v.get("title") or "").strip()
        prezzo = _prezzo(v)
        if len(titolo) < 3 or prezzo is None:
            continue
        chiave = (titolo[:60].lower(), f"{prezzo:.2f}")
        if chiave in visti:
            continue
        visti.add(chiave)
        righe.append(f"- {titolo} — €{prezzo:.2f}")
        id_item = v.get("id")
        if id_item:
            mappa.setdefault((_normalizza_titolo_per_link(titolo), f"{prezzo:.2f}"), f"https://www.vinted.it/items/{id_item}")
            foto = v.get("photo")
            miniatura = foto.get("url") if isinstance(foto, dict) else None
            if isinstance(miniatura, str) and miniatura:
                miniature.setdefault(str(id_item), miniatura)
        if len(righe) >= max_articoli:
            break
    return "\n".join(righe), mappa, miniature


def scheda_da_json_item(testo_json):
    """Dati di un annuncio dalla risposta JSON del dettaglio: {'foto': {photo_id: url}, 'descrizione', 'taglia', 'stato'}. Pura.
    {} se il JSON non e' un annuncio. Le foto: stessa logica di vinted_scrape._estrai_foto_da_json_item (full_size_url prima)."""
    try:
        dati = json.loads(testo_json)
    except Exception:
        return {}
    if not isinstance(dati, dict):
        return {}
    item = dati.get("item") if isinstance(dati.get("item"), dict) else dati
    foto = {}
    for f in item.get("photos") or []:
        if not isinstance(f, dict):
            continue
        u = f.get("full_size_url") or f.get("url")
        if not isinstance(u, str):
            continue
        m = re.search(r"https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/", u)
        if m:
            foto.setdefault(m.group(1), u)
    if not foto and not item.get("description"):
        return {}
    stato = item.get("status")
    return {
        "foto": foto,
        "descrizione": item.get("description") if isinstance(item.get("description"), str) else None,
        "taglia": item.get("size_title") if isinstance(item.get("size_title"), str) else None,
        "stato": stato if isinstance(stato, str) else None,
    }


def _intestazioni(token, anon_id):
    """Intestazioni di una chiamata XHR del sito: senza i Sec-Fetch Cloudflare la scarta anche con token valido (nota del tracker)."""
    h = {k: v for k, v in VINTED_HEADERS.items() if k not in ("Upgrade-Insecure-Requests", "Sec-Fetch-User", "Accept")}
    h.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": HOST_WWW + "/",
        "Origin": HOST_WWW,
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Authorization": f"Bearer {token}",
    })
    if anon_id:
        h["x-anon-id"] = anon_id
    return h


# ---------------------------------------------------------------------------
# rete
# ---------------------------------------------------------------------------
def _cookie(client, nome):
    try:
        for c in client.cookies.jar:
            if c.name == nome and c.value:
                return c.value
    except Exception:
        pass
    return None


async def _sessione(client, chiave, forza=False):
    """(token, anon_id) anonimi per questo proxy: HEAD a www.vinted.it, come il tracker. None se non arrivano."""
    s = _SESSIONI.get(chiave)
    if s and not forza and time.time() - s[2] < SESSIONE_VALIDA_SECONDI:
        return s[0], s[1]
    _SESSIONI.pop(chiave, None)
    try:
        client.cookies.clear()
        r = await client.head(HOST_WWW + "/", headers=VINTED_HEADERS, timeout=10)
    except Exception as e:
        log.info("VINTED API | sessione non ottenuta (%s): %s", _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave), e)
        return None
    token, anon = _cookie(client, "access_token_web"), _cookie(client, "anon_id")
    if not token:
        log.info("VINTED API | HEAD senza access_token_web (proxy=%s status=%s)",
                 _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave), r.status_code)
        return None
    _SESSIONI[chiave] = (token, anon, time.time())
    return token, anon


async def api_get(url, params=None, max_retries=3, timeout=12):
    """GET JSON all'API Vinted con token anonimo, ruotando i proxy del pool. Risposta httpx con status 200, None se fallisce.
    Mai eccezioni."""
    if not VINTED_API_ATTIVA or not _CLIENT_VINTED_POOL:
        return None
    ultimo = "nessun tentativo"
    for tentativo in range(1, max_retries + 1):
        try:
            indice = _prossimo_indice_vinted()
            client, chiave = _CLIENT_VINTED_POOL[indice], _CLIENT_VINTED_POOL_KEYS[indice]
            etichetta = _ETICHETTA_PER_CHIAVE_PROXY.get(chiave) or _etichetta_proxy(chiave)
            await _attendi_turno_vinted(chiave)
            sess = await _sessione(client, chiave, forza=tentativo > 1 and chiave not in _SESSIONI)
            if not sess:
                ultimo = "sessione non ottenuta"
                continue
            resp = await client.get(url, params=params, headers=_intestazioni(*sess), timeout=timeout)
            _registra_banda(url, resp, tipo="api_vinted")
            if resp.status_code == 200:
                _registra_esito_proxy(chiave, ok=True)
                resp._proxy_etichetta = etichetta
                return resp
            ultimo = f"status {resp.status_code} (proxy {etichetta})"
            if resp.status_code in (401, 403):
                _SESSIONI.pop(chiave, None)  # token rifiutato: al prossimo giro se ne chiede uno nuovo
            _registra_esito_proxy(chiave, ok=False, bloccato=resp.status_code in (403, 429))
        except Exception as e:
            ultimo = f"errore {type(e).__name__}: {e}"
        if tentativo < max_retries:
            await asyncio.sleep(1.0 * tentativo)
    log.info("VINTED API | fallita dopo %d tentativi (%s) -- %s", max_retries, ultimo, url)
    return None


async def cerca_catalogo(url_web, per_page=20):
    """Comparabili dal catalogo via API per un URL di ricerca web. (testo, mappa_url, miniature) oppure None se l'API non risponde
    o non trova articoli (il chiamante ripiega sullo scraping HTML)."""
    resp = await api_get(HOST_API + PERCORSO_CATALOGO, params=parametri_da_url_catalogo(url_web, per_page=per_page))
    if resp is None:
        return None
    testo, mappa, miniature = articoli_da_json_catalogo(resp.text)
    log.info("VINTED API | catalogo articoli=%d proxy=%s -- %s", testo.count("\n") + 1 if testo else 0,
             getattr(resp, "_proxy_etichetta", "?"), url_web)
    return (testo, mappa, miniature) if testo else None


async def scheda_annuncio(id_item):
    """Foto e dati dell'annuncio via API. Prova prima l'endpoint storico con il token, poi quello del nuovo servizio; il log dice quale
    risponde. {} se nessuno dei due."""
    for url in (f"{HOST_WWW}/api/v2/items/{id_item}", f"{HOST_API}{PERCORSO_CATALOGO}/{id_item}"):
        resp = await api_get(url, max_retries=2)
        if resp is None:
            continue
        scheda = scheda_da_json_item(resp.text)
        log.info("VINTED API | scheda item=%s foto=%d endpoint=%s proxy=%s", id_item,
                 len(scheda.get("foto") or {}), url.split("//", 1)[1].split("/", 1)[0] + url[url.find("/", 8):].split(str(id_item))[0],
                 getattr(resp, "_proxy_etichetta", "?"))
        if scheda.get("foto"):
            return scheda
    return {}
