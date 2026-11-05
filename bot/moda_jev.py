"""Verifica con Jev degli avvisi dei brand nuovi della moda (richiesta dell'utente, 02/11).

I brand in FAIR_VALUE_BRAND_NUOVI hanno un fair value stimato da me, non misurato. Qui, prima di avvisare, si fa come nel radar:
  1. comparabili cercati su Vinted (brand_ids[] + categoria dell'annuncio + parole del titolo);
  2. Jev giudica ogni titolo (stesso modello / simile / altro) e la rivendita si ricalcola sui comparabili veri;
  3. Jev guarda la prima foto e dice se l'articolo sembra originale del brand (indizio dalla sola foto, non una certificazione).
Esito: 'conferma' (margine >= 50 EUR e ROI >= 100% sui comparabili, foto non sospetta), 'scarta' (i comparabili non reggono il margine
oppure la foto sembra falsa/altra marca), 'non_verificato' (comparabili non trovati o Jev spento: l'avviso parte con l'avvertenza).
Spenta con MODA_JEV=0; MODA_JEV_TUTTI=1 la estende a tutti gli avvisi (non solo ai brand nuovi). Costo: poche chiamate Jev solo per i pochi avvisi dei brand nuovi; tetto MODA_JEV_MAX_GIORNO.
"""
import os
import re
import time
import asyncio
import traceback
from urllib.parse import quote

from bot.comps import _cerca_vinted_testo_diretto, _miniature_comp
from bot.config import SPEDIZIONE_STIMATA_EUR
from bot.costanti import VINTED_BRAND_IDS
from bot.foto import download_image_bytes, optimize_image_bytes
from bot.fair_value import FAIR_VALUE_BRAND_NUOVI
from bot.jev import CONF_AUTENTICITA_MIN, MAX_FOTO_AUTENTICITA, DOMANDA_FOTO_COMP_MODA, JEV_FOTO_COMPS, MAX_FOTO_COMPS, confronta_foto_comparabili, giudica_autenticita
from bot.logger import log
from bot.moda_gemini import controlla as controlla_gemini, e_replica, riga_messaggio as riga_gemini, serve_controllo
from bot.testo import _normalizza_titolo_per_link
from bot.valore_mercato import comparabili_simili, parse_comp, query_comp, solo_usato, stima_mercato, valuta
# ---- fine import ----

MODA_JEV = os.environ.get("MODA_JEV", "0").strip() in ("1", "true", "si")
MODA_JEV_MAX_GIORNO = int(os.environ.get("MODA_JEV_MAX_GIORNO", "600") or 600)
# 02/11 (richiesta dell'utente): la verifica vale per TUTTI gli avvisi della moda, non solo per i brand nuovi. 0 = solo brand nuovi.
MODA_JEV_TUTTI = os.environ.get("MODA_JEV_TUTTI", "0").strip() in ("1", "true", "si")
# 02/11 (richiesta dell'utente): l'avviso parte SUBITO (come prima della verifica) e lo stesso messaggio viene aggiornato con l'esito
# Jev (comparabili, foto) o con "scartato dalla verifica". 0 = avviso trattenuto fino alla verifica.
MODA_JEV_SUBITO = os.environ.get("MODA_JEV_SUBITO", "1").strip() not in ("0", "false", "no", "")
MIN_COMPARABILI = 3
# 02/11: la foto dei comparabili conta solo se Jev li trova MOLTO simili (stesso modello, confidenza >= soglia): allora il loro prezzo
# diventa la rivendita; altrimenti resta la ricerca testuale come prima (Jev non scarta piu' i comparabili: era troppo stringente).
CONF_FOTO_MOLTO_SIMILE = 0.6
_conteggio = {"giorno": None, "n": 0}


def tratteni_per_verifica(fv, regola):
    """True se l'avviso va trattenuto fino alla verifica Jev: con MODA_JEV_TUTTI ogni avviso (regola diversa da 'no'); altrimenti solo
    la regola brand_nuovo sui brand nuovi. Pura."""
    if not MODA_JEV or not regola or regola == "no":
        return False
    return bool(MODA_JEV_TUTTI or regola == "da_verificare" or (regola == "brand_nuovo" and (fv or {}).get("brand") in FAIR_VALUE_BRAND_NUOVI))


def id_brand(brand):
    """Id Vinted del brand dalla tabella della moda, o None. Pura."""
    return VINTED_BRAND_IDS.get((brand or "").strip().lower())


def url_comparabili(brand, testo=None, catalogo=None):
    """Ricerca dei simili: brand_ids[] + categoria foglia dell'annuncio + parole del titolo (se ci sono). None senza id brand. Pura."""
    bid = id_brand(brand)
    if not bid and not brand:
        return None
    # senza id (brand storici fuori dalla tabella) il brand entra come parola di ricerca
    t = f"&search_text={quote(testo if bid else ((brand or '') + ' ' + (testo or '')).strip())}" if (testo or not bid) else ""
    c = f"&catalog[]={catalogo}" if catalogo else ""
    b = f"brand_ids[]={bid}" if bid else "order=newest_first"
    return f"https://www.vinted.it/catalog?{b}{c}{t}&order=newest_first"


def comparabili_con_link(coppie, mappe, n=MAX_FOTO_COMPS):
    """[(titolo, prezzo, url)] dei `n` comparabili piu' vicini alla mediana dei prezzi che hanno un link noto. `mappe` = dizionari
    {(titolo normalizzato, prezzo 2f): url} delle ricerche. Pura."""
    if not coppie:
        return []
    prezzi = sorted(p for _, p in coppie)
    mediana = prezzi[len(prezzi) // 2]
    out, visti = [], set()
    for t, p in sorted(coppie, key=lambda c: abs(c[1] - mediana)):
        url = next((m[k] for m in mappe if m for k in [(_normalizza_titolo_per_link(t), f"{p:.2f}")] if k in m), None)
        if url and url not in visti:
            visti.add(url)
            out.append((t, p, url))
        if len(out) >= n:
            break
    return out


async def _miniature_dei_comparabili(link_comps):
    """[(comparabile, byte)] delle miniature (ridotte a 512 px) dei comparabili con link noto e foto scaricabile: l'allineamento resta,
    cosi' il confronto di Jev si riferisce al comparabile giusto. Lista vuota se mancano."""
    con_foto = []
    for c in link_comps:
        m = re.search(r"/items/(\d+)", c[2])
        u = _miniature_comp.get(m.group(1)) if m else None
        if u:
            con_foto.append((c, u))
    con_foto = con_foto[:MAX_FOTO_COMPS]
    scaricate = await asyncio.gather(*(download_image_bytes(u) for _c, u in con_foto), return_exceptions=True)
    out = []
    for (c, _u), b in zip(con_foto, scaricate):
        if isinstance(b, bytes) and b:
            out.append((c, await asyncio.to_thread(optimize_image_bytes, b, 512)))
    return out


def molto_simili(coppie, confronti, conf_min=CONF_FOTO_MOLTO_SIMILE):
    """[(titolo, prezzo, url)] dei comparabili che Jev giudica MOLTO simili alla foto dell'annuncio (stesso_modello con confidenza >=
    conf_min). `coppie` = [(comparabile, byte)] come da _miniature_dei_comparabili; `confronti` = [(scelta, conf)] nello stesso ordine. Pura."""
    if not coppie or not confronti:
        return []
    return [c for (c, _b), (sc, cf) in zip(coppie, confronti) if sc == "stesso_modello" and (cf or 0) >= conf_min]


def _entro_il_tetto():
    oggi = time.strftime("%Y-%m-%d")
    if _conteggio["giorno"] != oggi:
        _conteggio.update(giorno=oggi, n=0)
    if _conteggio["n"] >= MODA_JEV_MAX_GIORNO:
        return False
    _conteggio["n"] += 1
    return True


def decidi(valutazione, autenticita, gemini=None):
    """(esito, motivo) dalle due verifiche. `valutazione` = dict di valuta() o None se i comparabili mancano; `autenticita` =
    (scelta, confidenza) o None; `gemini` = dict del controllo Gemini su tutte le foto o None. Il falso scarta sempre; senza comparabili
    l'avviso parte non verificato. Pura."""
    if e_replica(gemini):
        return "scarta", "gemini:replica"
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
        if ris.get("motivo") == "gemini:replica":
            return f"🚫 Gemini: non avvisato, indizi di replica nelle foto ({((ris.get('gemini') or {}).get('confidenza') or 0):.0%})"
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
        righe.append(f"🔎 Comparabili Vinted{' (molto simili alla foto)' if ris.get('da_foto') else ''}: {ris['n']} annunci, rivendita ~{ris['rivendita']:.0f} € "
                     f"(margine ~{ris['margine']:.0f} €, ROI {ris['roi']:.0f}%)")
        link = ris.get("link_comps") or []
        if link:   # comparabili identificati, con il link all'annuncio (richiesta dell'utente, 02/11)
            for t, p, u in link[:3]:
                righe.append(f"• {p:g} € {t[:45]} {u}")
        else:
            for t, p in (ris.get("esempi") or [])[:3]:
                righe.append(f"• {p:g} € {t[:50]}")
    else:
        righe.append("🔎 Comparabili Vinted non trovati: la stima resta quella a priori")
    fc = ris.get("foto_comps")
    if fc:
        nomi = {"stesso_modello": "molto simile", "simile": "simile", "diverso": "diverso", "non_chiaro": "non chiaro"}
        righe.append("🖼 Foto comparabili vs annuncio (Jev): " + ", ".join(nomi.get(sc, str(sc)) for sc, _cf in fc))
    g = riga_gemini(ris.get("gemini"))
    if g:
        righe.append(g)
    a = ris.get("autenticita")
    if a:
        etichette = {"originale_plausibile": "sembra originale", "non_chiaro": "non si capisce dalla foto"}
        righe.append(f"🔍 Foto (Jev): {etichette.get(a[0], a[0])} ({(a[1] or 0):.0%}). Indizio dalla foto, non certificazione")
    else:
        righe.append("🔍 Autenticita' non verificata")
    return righe


async def verifica(listing_info, foto, tutte_le_foto=None):
    """Dict {esito, motivo, n, rivendita, margine, roi, link, autenticita}. Mai eccezioni: in caso di errore 'non_verificato'."""
    fv = listing_info.get("fair_value") or {}
    brand = fv.get("brand")
    ris = {"esito": "non_verificato", "motivo": "errore", "n": 0, "rivendita": None, "margine": None, "roi": None, "esempi": [], "autenticita": None, "foto_comps": None, "gemini": None, "link_comps": [], "da_foto": False}
    try:
        titolo = listing_info.get("title") or ""
        prezzo = float(listing_info.get("price") or 0)
        catalogo = listing_info.get("catalog_id")
        if not _entro_il_tetto():
            ris["motivo"] = "tetto_giornaliero"
            return ris
        # i comparabili cercano brand + categoria + prime parole del titolo; se sono pochi, solo brand + categoria
        testo = " ".join(query_comp(titolo, brand).split()[len((brand or "").split()):][:3])
        comps_pool, usate, mappe = [], [], []
        for t in ([testo, None] if testo else [None]):
            url_c = url_comparabili(brand, t, catalogo)
            if not url_c:
                break
            risposta, ok, _mappa = await _cerca_vinted_testo_diretto(url_c)
            mappe.append(_mappa)
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
        link_comps = comparabili_con_link(comps_pool, mappe)
        stima = stima_mercato(prezzi, min_n=MIN_COMPARABILI)
        v = valuta(prezzo, stima, spedizione_eur=SPEDIZIONE_STIMATA_EUR) if stima else None
        foto_jpeg = None
        if foto:
            # Vinted serve anche webp: Jev accetta solo png/jpeg, quindi si converte in jpeg (prima la foto non partiva: foto=-)
            foto_jpeg = await asyncio.to_thread(optimize_image_bytes, foto, 768)
            # 5/11 (utente): Jev guarda TUTTE le foto (fino a JEV_AUTENTICITA_FOTO), non solo la prima: etichette, wash tag, made in, hardware
            altre = [f for f in (tutte_le_foto or [])[1:MAX_FOTO_AUTENTICITA] if f]
            tutte_jpeg = [foto_jpeg] + [await asyncio.to_thread(optimize_image_bytes, f, 768) for f in altre]
            ris["autenticita"] = await asyncio.to_thread(giudica_autenticita, titolo, brand, tutte_jpeg)
        if JEV_FOTO_COMPS and foto_jpeg and link_comps:
            # foto dell'annuncio contro le miniature dei comparabili piu' vicini alla mediana: se Jev li trova MOLTO simili il loro prezzo
            # diventa la rivendita (anche con pochi comparabili testuali); se no si torna alla stima testuale, senza foto
            coppie = await _miniature_dei_comparabili(link_comps)
            if coppie:
                ris["foto_comps"] = await asyncio.to_thread(confronta_foto_comparabili, titolo, foto_jpeg, [b for _c, b in coppie], DOMANDA_FOTO_COMP_MODA)
                vicini = molto_simili(coppie, ris["foto_comps"])
                if vicini:
                    stima_v = stima_mercato([c[1] for c in vicini], min_n=1)
                    if stima_v:
                        v = valuta(prezzo, stima_v, spedizione_eur=SPEDIZIONE_STIMATA_EUR)
                        link_comps = vicini
                        ris["da_foto"] = True
                        log.info("MODA JEV FOTO | brand=%s | molto_simili=%s/%s | rivendita=%s | titolo=%s", brand, len(vicini), len(coppie), v.get("rivendita"), titolo[:60])
        if serve_controllo(ris["autenticita"], prezzo, (v or {}).get("rivendita")):
            # Jev non e' sicuro dell'originalita' (o il prezzo e' troppo basso): Gemini gratuito guarda tutte le foto
            ris["gemini"] = await controlla_gemini(titolo, brand, prezzo, listing_info.get("description"), tutte_le_foto or ([foto] if foto else []),
                                                   item_id=listing_info.get("item_id"))
        ris["esito"], ris["motivo"] = decidi(v, ris["autenticita"], ris["gemini"])
        if v:
            ris.update(n=v.get("n") or len(prezzi), rivendita=v.get("rivendita"), margine=v.get("margine"), roi=v.get("roi"),
                       esempi=list(comps_pool[:3]), link_comps=link_comps)
        log.info("MODA JEV | item=%s | brand=%s | prezzo=%s | esito=%s | motivo=%s | n=%s | rivendita=%s | margine=%s | fv_stima=%s | foto=%s",
                 listing_info.get("item_id") or "-", brand, prezzo, ris["esito"], ris["motivo"], ris["n"], ris["rivendita"], ris["margine"],
                 fv.get("fv"), ris["autenticita"] or "-")
    except Exception:
        log.warning("Moda Jev: verifica non riuscita:\n%s", traceback.format_exc())
    return ris
