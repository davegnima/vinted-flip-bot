"""Sonda dei venduti eBay e Vestiaire (fase 0 del piano 'archivio venduti moda', 14/11).

Una volta all'avvio (VENDUTI_SONDA=1) fa poche richieste lente con il client generico (nessun proxy, PROXY_LIST non si
tocca) e scrive nel log cosa rispondono le due fonti: stato, URL finale, byte, quanti articoli e quali campi si leggono.
Non salva niente e non decide niente: serve a misurare se una fonte regge prima di costruire la raccolta.
Se una fonte blocca (redirect a login o verifica, 403, 429, 503) la sonda lo scrive e passa oltre: niente tentativi di
aggirare le protezioni.

Righe di log: 'SONDA VENDUTI fonte=... status=... esito=...'. Le funzioni di analisi sono pure (testo -> dict) e testate.
"""
import asyncio
import json
import os
import re
import traceback
from urllib.parse import quote_plus

from bot import http_clients as hc
from bot.logger import log

VENDUTI_SONDA = os.environ.get("VENDUTI_SONDA", "0").strip() in ("1", "true", "si")
SONDA_PAUSA_SECONDI = float(os.environ.get("VENDUTI_SONDA_PAUSA", "6") or 6)
SONDA_MAX_RICHIESTE_FONTE = 10

_SEGNI_BLOCCO_URL = ("signin", "challenge", "captcha", "splashui", "login", "consent")
_RE_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# eBay: layout vecchio (s-item) e nuovo (s-card)
_RE_EBAY_ARTICOLO = re.compile(r'class="(?:s-item|s-card)[ "]')
_RE_EBAY_PREZZO = re.compile(r'class="[^"]*(?:s-item__price|s-card__price)[^"]*"')
_RE_EBAY_BARRATO = re.compile(r'(STRIKETHROUGH|strikethrough)')
_RE_EBAY_VENDUTO = re.compile(r'(Venduto|Sold|Verkauft|Vendu)\b')

# Ricerche di prova: un brand e una categoria noti, un solo paese per fonte (poche richieste).
RICERCHE_EBAY = [
    "https://www.ebay.it/sch/i.html?_nkw=prada+giacca&LH_Sold=1&LH_Complete=1&_ipg=60",
    "https://www.ebay.de/sch/i.html?_nkw=prada+jacke&LH_Sold=1&LH_Complete=1&_ipg=60",
]
RICERCHE_VESTIAIRE = [
    "https://it.vestiairecollective.com/search/?q=" + quote_plus("prada giacca") + "&sold=true",
    "https://it.vestiairecollective.com/search/?q=" + quote_plus("prada giacca"),
]


def e_bloccato(status, url_finale):
    """Vero se la risposta non e' una pagina di risultati: status di blocco o redirect a login/verifica (anche con 200)."""
    if status in (401, 403, 407, 429, 503):
        return True
    u = (url_finale or "").lower()
    return any(s in u for s in _SEGNI_BLOCCO_URL)


def analizza_ebay(html, url_finale="", status=200):
    """Conta articoli, prezzi, prezzi barrati (proposta accettata: il prezzo finale non si vede) e segnali 'venduto'."""
    if e_bloccato(status, url_finale):
        return {"fonte": "ebay", "esito": "bloccato", "status": status, "url_finale": url_finale}
    articoli = len(_RE_EBAY_ARTICOLO.findall(html))
    prezzi = len(_RE_EBAY_PREZZO.findall(html))
    barrati = len(_RE_EBAY_BARRATO.findall(html))
    venduti = len(_RE_EBAY_VENDUTO.findall(html))
    esito = "passato" if articoli >= 5 and prezzi >= 5 and venduti >= 1 else "senza_venduti"
    return {"fonte": "ebay", "esito": esito, "status": status, "url_finale": url_finale, "byte": len(html),
            "articoli": articoli, "prezzi": prezzi, "barrati": barrati, "segnali_venduto": venduti}


def _prodotti_json(obj, trovati, profondita=0):
    """Raccoglie i dizionari che sembrano un prodotto (un campo prezzo e uno tra brand/nome/titolo)."""
    if profondita > 12 or len(trovati) > 500:
        return
    if isinstance(obj, dict):
        chiavi = {k.lower() for k in obj}
        if any("price" in k or "prezzo" in k for k in chiavi) and any(k in chiavi for k in ("brand", "name", "title", "model")):
            trovati.append(obj)
        for v in obj.values():
            _prodotti_json(v, trovati, profondita + 1)
    elif isinstance(obj, list):
        for v in obj:
            _prodotti_json(v, trovati, profondita + 1)


def analizza_vestiaire(html, url_finale="", status=200):
    """Cerca i dati dentro __NEXT_DATA__: se i prodotti sono li', il parsing e' deterministico (JSON)."""
    if e_bloccato(status, url_finale):
        return {"fonte": "vestiaire", "esito": "bloccato", "status": status, "url_finale": url_finale}
    m = _RE_NEXT_DATA.search(html)
    out = {"fonte": "vestiaire", "status": status, "url_finale": url_finale, "byte": len(html),
           "next_data": bool(m), "segnali_venduto": len(re.findall(r'\b(sold|venduto)\b', html, re.I))}
    if not m:
        out["esito"] = "senza_next_data"
        return out
    try:
        dati = json.loads(m.group(1))
    except ValueError:
        out["esito"] = "next_data_non_json"
        return out
    prodotti = []
    _prodotti_json(dati, prodotti)
    out["articoli"] = len(prodotti)
    out["campi"] = sorted(prodotti[0].keys())[:30] if prodotti else []
    sold = [p for p in prodotti if any("sold" in k.lower() for k in p)]
    out["con_campo_sold"] = len(sold)
    out["esito"] = "passato" if prodotti and sold else ("senza_venduti" if prodotti else "senza_prodotti")
    return out


async def _scarica(url):
    r = await hc._client_generico.get(url, headers={"Accept-Language": "it-IT,it;q=0.9"})
    return r.status_code, str(r.url), r.text


async def sonda_venduti():
    """Un giro di sonda: poche richieste lente, un log per richiesta e un riepilogo. Non solleva mai."""
    try:
        giri = (("ebay", RICERCHE_EBAY, analizza_ebay), ("vestiaire", RICERCHE_VESTIAIRE, analizza_vestiaire))
        riepilogo = {}
        for fonte, urls, analizza in giri:
            for url in urls[:SONDA_MAX_RICHIESTE_FONTE]:
                try:
                    status, url_finale, html = await _scarica(url)
                    ris = analizza(html, url_finale, status)
                except Exception as e:
                    ris = {"fonte": fonte, "esito": "errore", "errore": f"{type(e).__name__}: {e}"[:160]}
                log.warning("SONDA VENDUTI fonte=%s url=%s esito=%s dettaglio=%s", fonte, url, ris.get("esito"),
                            json.dumps(ris, ensure_ascii=False)[:600])
                riepilogo.setdefault(fonte, []).append(ris.get("esito"))
                await asyncio.sleep(SONDA_PAUSA_SECONDI)
        log.warning("SONDA VENDUTI riepilogo: %s", json.dumps(riepilogo, ensure_ascii=False))
    except Exception:
        log.warning("SONDA VENDUTI fallita:\n%s", traceback.format_exc())
