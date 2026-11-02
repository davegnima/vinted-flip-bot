"""Verifica con Jev degli avvisi dei brand nuovi della moda (richiesta dell'utente, 02/11).

I brand in FAIR_VALUE_BRAND_NUOVI hanno un fair value stimato da me, non misurato. Qui, prima di avvisare, si fa come nel radar:
  1. comparabili cercati su Vinted (brand_ids[] + categoria dell'annuncio + parole del titolo);
  2. Jev giudica ogni titolo (stesso modello / simile / altro) e la rivendita si ricalcola sui comparabili veri;
  3. Jev guarda la prima foto e dice se l'articolo sembra originale del brand (indizio dalla sola foto, non una certificazione).
Esito: 'conferma' (margine >= 50 EUR e ROI >= 100% sui comparabili, foto non sospetta), 'scarta' (i comparabili non reggono il margine
oppure la foto sembra falsa/altra marca), 'non_verificato' (comparabili non trovati o Jev spento: l'avviso parte con l'avvertenza).
Spenta con MODA_JEV=0. Costo: poche chiamate Jev solo per i pochi avvisi dei brand nuovi; tetto MODA_JEV_MAX_GIORNO.
"""
import os
import time
import asyncio
import traceback
from urllib.parse import quote

from bot.comps import _cerca_vinted_testo_diretto
from bot.config import SPEDIZIONE_STIMATA_EUR
from bot.costanti import VINTED_BRAND_IDS
from bot.foto import optimize_image_bytes
from bot.fair_value import FAIR_VALUE_BRAND_NUOVI
from bot.jev import CONF_AUTENTICITA_MIN, classifica_comparabili, comparabili_simili as simili_jev, comparabili_stesso_modello, giudica_autenticita
from bot.logger import log
from bot.valore_mercato import comparabili_simili, parse_comp, query_comp, solo_usato, stima_mercato, valuta
# ---- fine import ----

MODA_JEV = os.environ.get("MODA_JEV", "0").strip() in ("1", "true", "si")
MODA_JEV_MAX_GIORNO = int(os.environ.get("MODA_JEV_MAX_GIORNO", "300") or 300)
MIN_COMPARABILI = 3
_conteggio = {"giorno": None, "n": 0}


def tratteni_per_verifica(fv, regola):
    """True se l'avviso va trattenuto fino alla verifica Jev: brand nuovo, regola brand_nuovo, MODA_JEV acceso. Pura."""
    return bool(MODA_JEV and regola == "brand_nuovo" and (fv or {}).get("brand") in FAIR_VALUE_BRAND_NUOVI)


def id_brand(brand):
    """Id Vinted del brand dalla tabella della moda, o None. Pura."""
    return VINTED_BRAND_IDS.get((brand or "").strip().lower())


def url_comparabili(brand, testo=None, catalogo=None):
    """Ricerca dei simili: brand_ids[] + categoria foglia dell'annuncio + parole del titolo (se ci sono). None senza id brand. Pura."""
    bid = id_brand(brand)
    if not bid:
        return None
    t = f"&search_text={quote(testo)}" if testo else ""
    c = f"&catalog[]={catalogo}" if catalogo else ""
    return f"https://www.vinted.it/catalog?brand_ids[]={bid}{c}{t}&order=newest_first"


def _entro_il_tetto():
    oggi = time.strftime("%Y-%m-%d")
    if _conteggio["giorno"] != oggi:
        _conteggio.update(giorno=oggi, n=0)
    if _conteggio["n"] >= MODA_JEV_MAX_GIORNO:
        return False
    _conteggio["n"] += 1
    return True


def decidi(valutazione, autenticita):
    """(esito, motivo) dalle due verifiche. `valutazione` = dict di valuta() o None se i comparabili mancano; `autenticita` =
    (scelta, confidenza) o None. Il falso scarta sempre; senza comparabili l'avviso parte non verificato. Pura."""
    if autenticita and autenticita[0] in ("replica_probabile", "altra_marca") and (autenticita[1] or 0) >= CONF_AUTENTICITA_MIN:
        return "scarta", "foto:" + autenticita[0]
    if valutazione is None:
        return "non_verificato", "comparabili_non_trovati"
    if not valutazione.get("ok"):
        return "scarta", "comparabili:" + str(valutazione.get("motivo"))
    return "conferma", "ok"


def riga_esito_scheda(ris):
    """Riga (testo semplice) per la scheda della chat principale dopo la verifica: perche' l'avviso e' partito o no. Pura."""
    a = ris.get("autenticita")
    if ris.get("esito") == "scarta":
        if str(ris.get("motivo", "")).startswith("foto:") and a:
            return f"🚫 Jev: non avvisato, la foto sembra {a[0].replace('_', ' ')} ({(a[1] or 0):.0%})"
        if ris.get("rivendita") is not None:
            return (f"🚫 Jev: non avvisato, rivendita sui {ris['n']} comparabili ~{ris['rivendita']:.0f} € "
                    f"(margine ~{ris['margine']:.0f} €, ROI {ris['roi']:.0f}%)")
        return "🚫 Jev: non avvisato (" + str(ris.get("motivo")) + ")"
    if ris.get("esito") == "conferma":
        return f"✅ Jev: confermato, rivendita ~{ris['rivendita']:.0f} € (margine ~{ris['margine']:.0f} €), avviso mandato"
    return "⚠️ Jev: comparabili non trovati, avviso mandato non verificato"


def righe_messaggio(ris):
    """Righe (testo semplice) da aggiungere all'avviso: rivendita dai comparabili e giudizio sulla foto. Pura."""
    righe = []
    if ris.get("rivendita") is not None:
        righe.append(f"🔎 Comparabili Vinted: {ris['n']} annunci, rivendita ~{ris['rivendita']:.0f} € "
                     f"(margine ~{ris['margine']:.0f} €, ROI {ris['roi']:.0f}%)")
        for t, p in (ris.get("esempi") or [])[:3]:
            righe.append(f"• {p:g} € {t[:50]}")
    else:
        righe.append("🔎 Comparabili Vinted non trovati: la stima resta quella a priori")
    a = ris.get("autenticita")
    if a:
        etichette = {"originale_plausibile": "sembra originale", "non_chiaro": "non si capisce dalla foto"}
        righe.append(f"🔍 Foto (Jev): {etichette.get(a[0], a[0])} ({(a[1] or 0):.0%}). Indizio dalla foto, non certificazione")
    else:
        righe.append("🔍 Autenticita' non verificata")
    return righe


async def verifica(listing_info, foto):
    """Dict {esito, motivo, n, rivendita, margine, roi, link, autenticita}. Mai eccezioni: in caso di errore 'non_verificato'."""
    fv = listing_info.get("fair_value") or {}
    brand = fv.get("brand")
    ris = {"esito": "non_verificato", "motivo": "errore", "n": 0, "rivendita": None, "margine": None, "roi": None, "esempi": [], "autenticita": None}
    try:
        titolo = listing_info.get("title") or ""
        prezzo = float(listing_info.get("price") or 0)
        catalogo = listing_info.get("catalog_id")
        if not _entro_il_tetto():
            ris["motivo"] = "tetto_giornaliero"
            return ris
        # i comparabili cercano brand + categoria + prime parole del titolo; se sono pochi, solo brand + categoria
        testo = " ".join(query_comp(titolo, brand).split()[len((brand or "").split()):][:3])
        comps_pool, usate = [], []
        for t in ([testo, None] if testo else [None]):
            url_c = url_comparabili(brand, t, catalogo)
            if not url_c:
                break
            risposta, ok, _mappa = await _cerca_vinted_testo_diretto(url_c)
            if not ok:
                continue
            comps = [c for c in solo_usato(parse_comp(risposta)) if not (c[0] == titolo and abs(c[1] - prezzo) < 0.01)]
            if t:
                comps = comparabili_simili(comps, t, brand)
            usate = comps
            if len(comps) >= MIN_COMPARABILI:
                break
        comps_pool = usate
        prezzi = [p for _t, p in comps_pool]
        if len(comps_pool) >= MIN_COMPARABILI:
            etichette = await asyncio.to_thread(classifica_comparabili, titolo, [t for t, _ in comps_pool], listing_info.get("description"))
            if etichette:
                veri = comparabili_stesso_modello(comps_pool, etichette) + simili_jev(comps_pool, etichette)
                comps_pool = veri
                prezzi = [p for _t, p in veri]
        stima = stima_mercato(prezzi, min_n=MIN_COMPARABILI)
        v = valuta(prezzo, stima, spedizione_eur=SPEDIZIONE_STIMATA_EUR) if stima else None
        if foto:
            # Vinted serve anche webp: Jev accetta solo png/jpeg, quindi si converte in jpeg (prima la foto non partiva: foto=-)
            foto_jpeg = await asyncio.to_thread(optimize_image_bytes, foto, 768)
            ris["autenticita"] = await asyncio.to_thread(giudica_autenticita, titolo, brand, foto_jpeg)
        ris["esito"], ris["motivo"] = decidi(v, ris["autenticita"])
        if v:
            ris.update(n=v.get("n") or len(prezzi), rivendita=v.get("rivendita"), margine=v.get("margine"), roi=v.get("roi"),
                       esempi=list(comps_pool[:3]))
        log.info("MODA JEV | item=%s | brand=%s | prezzo=%s | esito=%s | motivo=%s | n=%s | rivendita=%s | margine=%s | fv_stima=%s | foto=%s",
                 listing_info.get("item_id") or "-", brand, prezzo, ris["esito"], ris["motivo"], ris["n"], ris["rivendita"], ris["margine"],
                 fv.get("fv"), ris["autenticita"] or "-")
    except Exception:
        log.warning("Moda Jev: verifica non riuscita:\n%s", traceback.format_exc())
    return ris
