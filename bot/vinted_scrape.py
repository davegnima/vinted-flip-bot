"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import html
import json
import asyncio
import traceback
import zlib
import importlib.util
from datetime import datetime, timezone


from bot.config import MAX_GALLERY_PHOTOS
from bot.proxy import _logga_riepilogo_banda
from bot.tracciamento import _tracc_estrai_segnali, _tracc_stato
from bot.vinted_http import _vinted_get_con_retry
from bot.logger import log
from bot.categorie import scegli_materiale_per_ricerca
# ---- fine import ----
# ---------------------------------------------------------------------------
# SONDA STRUTTURA PAGINA (aggiunta 2026-09-27, utente: "voglio testare sia
# brotli che leggere solo l'inizio della pagina, e capire cosa pesa").
# Sulle prime SONDA_BANDA_CAMPIONI pagine annuncio VERE (non pagine di
# blocco) dall'avvio, in background senza rallentare la pipeline, misura:
#   1. dove stanno nell'HTML i dati che estraiamo davvero (offset in KB di
#      foto, taglia, descrizione, venditore...) -> quanto inizio di pagina
#      basterebbe leggere, e quanta banda si risparmierebbe;
#   2. di cosa e' fatto il peso della pagina (script inline, payload React,
#      stili, SVG, resto) -> il bot scarica SOLO il documento HTML, mai
#      CSS/JS/immagini collegati, quindi ogni risparmio possibile e' dentro
#      questo documento;
#   3. brotli: stessa pagina richiesta anche con Accept-Encoding "br" (solo
#      se il pacchetto brotli e' installato), confronto dei byte in rete;
#   4. foto senza proxy: la prima foto scaricata DIRETTA (IP Railway,
#      nessun proxy) per vedere se il CDN immagini la serve comunque -- se
#      si', le foto potrebbero non consumare piu' banda proxy.
# SONDA_BANDA_CAMPIONI=0 su Railway la disattiva del tutto.
# ---------------------------------------------------------------------------
SONDA_BANDA_CAMPIONI = int(os.environ.get("SONDA_BANDA_CAMPIONI", "10"))
_sonda_campioni_fatti = [0]
_sonda_task_attivi = set()
BROTLI_DISPONIBILE = (importlib.util.find_spec("brotli") is not None
                      or importlib.util.find_spec("brotlicffi") is not None)

_REGEX_FOTO_F800 = re.compile(
    r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/f800/'
    r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?')

# (nome, regex, prendi_ultima_occorrenza) -- STESSI pattern usati in
# scrape_vinted_listing, cosi' gli offset misurati sono quelli reali.
_SONDA_CAMPI = [
    ("taglia", re.compile(r'"size_title"\s*:\s*"([^"]+)"'), False),
    ("condizione", re.compile(r'itemprop="status"[^>]*>.*?<span[^>]*>([^<]+)', re.DOTALL), False),
    ("descrizione", re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"'), False),
    ("data_pubblicazione", re.compile(r'\\?"(?:created_at_ts|created_at|createdAt)\\?"\s*:\s*\\?"?[^",\\]+'), False),
    ("categoria", re.compile(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"'), True),
    ("materiale", re.compile(r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)', re.DOTALL), False),
    ("colore", re.compile(r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)', re.DOTALL), False),
    ("venditore_login", re.compile(r'data-testid="profile-username"[^>]*>([^<]{2,40})<'), False),
    ("venditore_id", re.compile(r'href="/member/(\d+)"'), False),
    ("venditore_rating", re.compile(r'valutazione di\s+([\d.,]+)\s+su\s+5\s+stelle', re.IGNORECASE), False),
    ("venditore_n_feedback", re.compile(r'web_ui__Rating__label[^>]*>\s*<span[^>]*>\s*(\d+)\s*<'), False),
    ("venditore_n_articoli", re.compile(r'"items_count"\s*:\s*(\d+)'), False),
    ("venditore_paese", re.compile(r'"country_title_local"\s*:\s*"([^"]{2,30})"'), False),
]


def _sonda_e_pagina_vera(html_pagina):
    """Le pagine di blocco osservate il 27/9 pesano ~21KB, quelle vere
    ~1.7MB: sotto i 200KB o senza nessun marker tipico non la si analizza
    (misurerebbe la pagina di blocco, non l'annuncio)."""
    return len(html_pagina) > 200_000 and (
        'data-testid="profile-username"' in html_pagina or '"size_title"' in html_pagina)


def _sonda_analizza_offset(html_pagina):
    """Offset (fine del match, in caratteri) di ogni campo estratto, piu' la
    fine dell'ultima foto galleria prima del blocco venditore. Pura, testabile."""
    offset = {}
    marker = re.search(r'data-testid="profile-username"', html_pagina)
    zona_galleria = html_pagina[:marker.start()] if marker else html_pagina
    fine_ultima_foto = None
    for m in _REGEX_FOTO_F800.finditer(zona_galleria):
        fine_ultima_foto = m.end()
    offset["foto_galleria"] = fine_ultima_foto
    for nome, rx, ultima in _SONDA_CAMPI:
        fine = None
        if ultima:
            for m in rx.finditer(html_pagina):
                fine = m.end()
        else:
            m = rx.search(html_pagina)
            fine = m.end() if m else None
        offset[nome] = fine
    return offset


def _sonda_composizione(html_pagina):
    """Quanto pesa ogni tipo di blocco dentro il documento HTML (caratteri)."""
    comp = {"script_payload_react": 0, "script_altri": 0, "json_ld": 0, "style": 0, "svg": 0}
    for m in re.finditer(r'<script\b([^>]*)>(.*?)</script>', html_pagina, re.DOTALL | re.IGNORECASE):
        attrs, corpo = m.group(1), m.group(2)
        if "ld+json" in attrs:
            comp["json_ld"] += len(m.group(0))
        elif "self.__next_f" in corpo or "__NEXT_DATA__" in attrs:
            comp["script_payload_react"] += len(m.group(0))
        else:
            comp["script_altri"] += len(m.group(0))
    for m in re.finditer(r'<style\b.*?</style>', html_pagina, re.DOTALL | re.IGNORECASE):
        comp["style"] += len(m.group(0))
    for m in re.finditer(r'<svg\b.*?</svg>', html_pagina, re.DOTALL | re.IGNORECASE):
        comp["svg"] += len(m.group(0))
    comp["resto_html"] = max(0, len(html_pagina) - sum(comp.values()))
    return comp


def _sonda_stima_lettura_parziale(html_pagina, offset, byte_rete_reali):
    """Quanti caratteri iniziali servirebbero (ultimo campo trovato + 10% di
    margine) e quanta banda in rete si risparmierebbe, stimata comprimendo
    in gzip il prefisso e la pagina intera (stesso algoritmo del server)."""
    trovati = [v for v in offset.values() if v]
    if not trovati:
        return None
    necessari = min(len(html_pagina), int(max(trovati) * 1.10))
    full_gz = len(zlib.compress(html_pagina.encode("utf-8", "ignore"), 6)) or 1
    pref_gz = len(zlib.compress(html_pagina[:necessari].encode("utf-8", "ignore"), 6))
    rete_stimata_prefisso = byte_rete_reali * pref_gz / full_gz if byte_rete_reali else pref_gz
    return {
        "caratteri_necessari": necessari,
        "percentuale_pagina": necessari / len(html_pagina) * 100,
        "rete_stimata_prefisso": rete_stimata_prefisso,
        "risparmio_stimato": max(0.0, (byte_rete_reali or full_gz) - rete_stimata_prefisso),
    }


# Parola chiave "larga" da cercare quando la regex precisa di un campo non
# trova nulla (vedi _sonda_contesto_campi_mancanti).
_SONDA_PAROLE_CHIAVE_CAMPI = {
    "taglia": "size_title",
    "condizione": "status",
    "data_pubblicazione": "created_at",
    "materiale": "material",
    "colore": "color",
    "venditore_n_articoli": "items_count",
    "venditore_paese": "country",
}


def _sonda_contesto_campi_mancanti(html_pagina, offset, larghezza=160):
    """Per ogni campo che la regex di estrazione NON ha trovato, il testo
    attorno alla prima occorrenza della sua parola chiave (repr, cosi' le
    virgolette escapate \\" restano visibili nei log). Pura, testabile."""
    righe = []
    for campo, parola in _SONDA_PAROLE_CHIAVE_CAMPI.items():
        if offset.get(campo):
            continue
        i = html_pagina.find(parola)
        if i == -1:
            righe.append(f"{campo}: parola '{parola}' assente dalla pagina")
        else:
            righe.append(f"{campo} (a {i // 1024}KB): {html_pagina[max(0, i - 40):i + larghezza]!r}")
    return righe


def _formati_foto_nella_pagina(html_pagina):
    """Conteggio dei segmenti di risoluzione negli URL images.vinted.net
    (es. {'f800': 6, '310x430': 12}) -- per capire perche' la galleria esce
    vuota su pagine vere: se non c'e' 'f800' ma ci sono altri formati, Vinted
    sta servendo le foto in un formato che _estrai_foto_gallery scarta."""
    conteggio = {}
    # \\? tollera anche gli slash escapati (\/) tipici dei payload JSON/React.
    for m in re.finditer(r'images\d?\.vinted\.net\\?/t\\?/[a-zA-Z0-9_]+\\?/([a-zA-Z0-9]+)\\?/', html_pagina):
        conteggio[m.group(1)] = conteggio.get(m.group(1), 0) + 1
    return conteggio


def _sonda_avvia_se_serve(url, resp, html_pagina):
    """Chiamata da scrape_vinted_listing. Non attende nulla: se il campione
    serve, lancia la sonda in background e ritorna subito."""
    if SONDA_BANDA_CAMPIONI <= 0 or _sonda_campioni_fatti[0] >= SONDA_BANDA_CAMPIONI:
        return
    if not _sonda_e_pagina_vera(html_pagina):
        return
    _sonda_campioni_fatti[0] += 1
    n = _sonda_campioni_fatti[0]
    task = asyncio.create_task(_sonda_struttura_pagina(n, url, resp, html_pagina))
    _sonda_task_attivi.add(task)
    task.add_done_callback(_sonda_task_attivi.discard)


async def _sonda_struttura_pagina(n, url, resp, html_pagina):
    try:
        kb = lambda x: f"{x / 1024:.0f}KB" if x is not None else "non trovato"
        byte_rete = int(getattr(resp, "num_bytes_downloaded", 0) or 0)
        encoding = resp.headers.get("content-encoding", "nessuna")

        offset = _sonda_analizza_offset(html_pagina)
        comp = _sonda_composizione(html_pagina)
        stima = _sonda_stima_lettura_parziale(html_pagina, offset, byte_rete)

        log.info(
            "SONDA BANDA %d/%d [%s] pagina: %s decompressa, %s in rete (compressione '%s', x%.1f) -- %s",
            n, SONDA_BANDA_CAMPIONI, getattr(resp, "_proxy_etichetta", "?"),
            kb(len(html_pagina)), kb(byte_rete), encoding,
            (len(resp.content) / byte_rete) if byte_rete else 0, url,
        )
        log.info(
            "SONDA BANDA %d posizione dei dati nella pagina (KB dall'inizio, su %s): %s",
            n, kb(len(html_pagina)),
            ", ".join(f"{k}={kb(v)}" for k, v in sorted(offset.items(), key=lambda kv: kv[1] or 10**12)),
        )
        log.info(
            "SONDA BANDA %d composizione pagina: %s",
            n, ", ".join(f"{k} {kb(v)} ({v / len(html_pagina) * 100:.0f}%)"
                         for k, v in sorted(comp.items(), key=lambda kv: -kv[1])),
        )
        if stima:
            log.info(
                "SONDA BANDA %d lettura parziale: basterebbero i primi %s (%.0f%% della pagina) -> "
                "~%s in rete invece di %s, risparmio stimato ~%s per pagina annuncio",
                n, kb(stima["caratteri_necessari"]), stima["percentuale_pagina"],
                kb(stima["rete_stimata_prefisso"]), kb(byte_rete), kb(stima["risparmio_stimato"]),
            )

        # Brotli e foto senza proxy: test RIMOSSI il 2026-09-27 dopo il primo
        # campione reale (Vinted risponde sempre gzip anche chiedendo br --
        # nessun guadagno e una pagina extra per prova; il CDN foto risponde
        # dall'IP Railway -- ora usato di default, vedi download_image_bytes).

        # Campi non trovati: il testo reale attorno alla parola chiave, per
        # correggere le regex su dati veri invece di indovinare il formato.
        for riga in _sonda_contesto_campi_mancanti(html_pagina, offset):
            log.info("SONDA BANDA %d campo mancante %s", n, riga)
        if n == SONDA_BANDA_CAMPIONI:
            _logga_riepilogo_banda()
    except Exception:
        log.warning("SONDA BANDA %d: errore interno (ignorato):\n%s", n, traceback.format_exc())


def _estrai_foto_gallery(html_sorgente):
    """Estrae {photo_id: url} delle foto galleria capo da un frammento HTML
    di una pagina annuncio Vinted. Funzione pura (nessuna rete), spostata a
    livello di modulo il 2026-09-21 per poterla testare in isolamento da
    scrape_vinted_listing (vedi test_verdetto.py).

    FIX 2026-09-21 (utente, "Dries Van Noten" segnalato ancora come
    capi_diversi_tra_le_foto dopo il fix del 2026-09-20 sotto): il taglio
    per posizione (prima/dopo il marker venditore, in scrape_vinted_listing)
    presume che l'avatar compaia SEMPRE dopo il marker nell'HTML grezzo. Non
    e' garantito -- se l'avatar (o altri URL images.vinted.net non legati al
    capo) compare ANCHE prima del marker (es. dentro un blob di stato/JSON
    di idratazione della pagina, che su molte SPA moderne sta piu' in alto
    nell'HTML del blocco venditore renderizzato), il taglio "prima del
    marker" lo include comunque e nessuno dei due rami in
    scrape_vinted_listing lo scarta. Le foto vere della galleria capo,
    osservate su TUTTI i download reali finora loggati (nessuna eccezione),
    sono sempre servite in risoluzione "f800"; avatar/thumbnail extra usano
    altre risoluzioni. Si scartano quindi qui, a monte e indipendentemente
    dalla posizione, i photo_id che non compaiono MAI in f800 -- non si
    accetta piu' una foto vista solo in risoluzione WIDTHxHEIGHT.
    """
    m1 = re.findall(
        r'https://images\d?\.vinted\.net/t/([a-zA-Z0-9_]+)/(f800)/'
        r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html_sorgente)
    m2 = re.findall(
        r'https://images\d?\.vinted\.net/t/[a-zA-Z0-9_]+/f800/'
        r'[^\s"\'\\]+?\.(?:jpe?g|png|webp)(?:\?s=[a-f0-9]+)?', html_sorgente)
    diz = {}
    for (photo_id, resolution), full_url in zip(m1, m2):
        diz[photo_id] = full_url
    return diz


def _decodifica_stringa_json(contenuto):
    """Decodifica il contenuto (senza virgolette esterne) di una stringa
    JSON gia' estratta con regex. Sostituisce
    contenuto.encode().decode("unicode_escape"), che rompeva OGNI carattere
    non ASCII: encode() produce byte UTF-8 e unicode_escape li rilegge come
    latin-1, quindi "e'" con accento diventava "Ã¨" (visto in produzione il
    2026-09-29 nella descrizione mostrata in Telegram, e finiva cosi' anche
    nel testo dato all'Occhio). json.loads gestisce sia gli escape \\uXXXX sia
    i caratteri UTF-8 diretti. Se non e' JSON valido, testo cosi' com'e'."""
    try:
        return json.loads('"' + contenuto + '"')
    except Exception:
        return contenuto


_RE_ATTRIBUTO_ANNUNCIO = re.compile(r'data-testid="item-attributes-([A-Za-z0-9_\-]+)"')
_ETICHETTE_ATTRIBUTI = {
    "condizioni": "condition", "condizione": "condition", "stato": "condition",
    "taglia": "size", "colore": "color", "colori": "color", "materiale": "material",
    "caricato": "uploaded", "caricamento": "uploaded",
}
_CHIAVI_ATTRIBUTI = {
    "status": "condition", "size": "size", "color": "color", "material": "material",
    "upload_date": "uploaded", "uploaded": "uploaded",
}


def _testi_visibili(frammento_html):
    testi = []
    for t in re.findall(r">([^<>]+)<", frammento_html):
        t = html.unescape(t).replace("\u200c", "").strip()
        if t:
            testi.append(t)
    return testi


def _estrai_attributi_annuncio(html_pagina):
    """Legge i blocchi data-testid="item-attributes-*" della pagina annuncio
    (struttura confermata dal log della sonda: un contenitore con il testo
    dell'etichetta, es. "Condizioni", seguito dal contenitore col valore).
    Indipendente dai nomi delle classi CSS: si prendono i testi visibili del
    blocco, il primo e' l'etichetta, i successivi (brevi) il valore. Ritorna
    {"condition", "size", "color", "material", "uploaded"} solo per i campi
    trovati. Volutamente tollerante: e' scritto senza aver visto una pagina
    intera, quindi in caso di dubbio non ritorna nulla (vedi
    _diagnostica_attributi_mancanti)."""
    posizioni = [(m.start(), m.group(1)) for m in _RE_ATTRIBUTO_ANNUNCIO.finditer(html_pagina or "")]
    trovati = {}
    for i, (pos, chiave_html) in enumerate(posizioni):
        fine = min(posizioni[i + 1][0] if i + 1 < len(posizioni) else pos + 3000, pos + 3000)
        testi = _testi_visibili(html_pagina[pos:fine])
        if len(testi) < 2:
            continue
        campo = _ETICHETTE_ATTRIBUTI.get(testi[0].lower().rstrip(":")) or _CHIAVI_ATTRIBUTI.get(chiave_html.lower())
        if not campo or campo in trovati:
            continue
        valori = [t for t in testi[1:] if len(t) <= 40][:3]
        if valori:
            trovati[campo] = ", ".join(valori)
    return trovati


_DIAGNOSTICA_ATTRIBUTI_RESTANTI = [3]


def _diagnostica_attributi_mancanti(html_pagina, result, attributi, url):
    """Se dopo tutti i tentativi taglia/condizione restano vuote, logga (max 3
    volte per processo) il testo grezzo dei blocchi item-attributes: cosi' il
    prossimo log mostra il markup vero invece di doverlo indovinare."""
    if _DIAGNOSTICA_ATTRIBUTI_RESTANTI[0] <= 0 or (result.get("size") and result.get("condition")):
        return
    _DIAGNOSTICA_ATTRIBUTI_RESTANTI[0] -= 1
    blocchi = []
    for m in list(_RE_ATTRIBUTO_ANNUNCIO.finditer(html_pagina or ""))[:8]:
        blocchi.append(f"{m.group(1)}={_testi_visibili(html_pagina[m.start():m.start() + 1200])[:6]}")
    log.warning(
        "DIAGNOSTICA attributi annuncio incompleti per %s: size=%r condition=%r trovati=%s blocchi item-attributes=%s",
        url, result.get("size"), result.get("condition"), attributi or "nessuno", blocchi or "nessuno",
    )


async def scrape_vinted_listing(url, includi_guardaroba=True):
    result = {
        "photo_urls": [], "cover_photo_id": None, "size": None, "condition": None, "description": None,
        "created_at": None, "age_days": None, "catalog_id": None,
        "material_raw": None, "material_per_ricerca": None, "color_raw": None,
        "seller_login": None, "seller_id": None,
        "seller_feedback_count": None, "seller_feedback_reputation": None,
        "seller_items_count": None, "seller_country": None,
        "seller_top_items": [],
        "seller_wardrobe_debug": "non tentato", "uploaded_text": None, "stato_vendita": None,
        "preferiti": None, "visite": None,
    }
    try:
        resp = await _vinted_get_con_retry(url, timeout=15, max_retries=3)
        if resp is None:
            return result
        html_pagina = resp.text
        _sonda_avvia_se_serve(url, resp, html_pagina)  # in background, non rallenta
        try:
            _segnali_pagina = _tracc_estrai_segnali(html_pagina)[0]
            result["stato_vendita"] = _tracc_stato(resp.status_code, _segnali_pagina)
            result["preferiti"] = _segnali_pagina.get("preferiti")
            result["visite"] = _segnali_pagina.get("visite")
        except Exception:
            log.warning("Stato vendita non letto per %s:\n%s", url, traceback.format_exc())

        marker_venditore = re.search(r'data-testid="profile-username"', html_pagina)

        foto_complete = _estrai_foto_gallery(html_pagina)
        if marker_venditore:
            foto_tagliate = _estrai_foto_gallery(html_pagina[:marker_venditore.start()])
            if 0 < len(foto_tagliate) and len(foto_complete) - len(foto_tagliate) <= 2:
                best_url_by_photo_id = foto_tagliate
            else:
                # BUG TROVATO IN PRODUZIONE il 2026-09-20 (utente): quando il
                # taglio sopra viene scartato, foto_complete include TUTTO
                # cio' che sta sul dominio images.vinted.net nella pagina --
                # anche altri thumbnail dopo la sezione venditore (es.
                # "consigliati per te", che SONO in f800 perche' sono foto
                # vere di ALTRI annunci, quindi non piu' filtrabili dal fix
                # per risoluzione applicato in _estrai_foto_gallery). Caso
                # reale: 4 foto vere di un top Marni + l'avatar del
                # venditore (una foto di una moto) passate insieme
                # all'Occhio, che ha letto la moto come "capo diverso" e
                # scartato l'annuncio come FRAUDOLENTO. Fix: si ricalcola
                # cosa compare SOLO dopo il marker (mai prima) ed escludi
                # SOLO quelle foto da foto_complete -- il ramo foto_tagliate
                # sopra non ha questo problema per costruzione (contiene
                # solo HTML precedente al marker).
                foto_dopo_marker = _estrai_foto_gallery(html_pagina[marker_venditore.start():])
                ids_solo_dopo_marker = set(foto_dopo_marker) - set(foto_tagliate)
                best_url_by_photo_id = {
                    k: v for k, v in foto_complete.items() if k not in ids_solo_dopo_marker
                }
        else:
            best_url_by_photo_id = foto_complete

        result["photo_urls"] = list(best_url_by_photo_id.values())[:MAX_GALLERY_PHOTOS]

        # --- diagnostica temporanea (aggiunta 2026-09-24, utente): dal
        # 23/09 pomeriggio TUTTI gli scrape restituiscono 0 foto pur senza
        # nessun errore HTTP (_vinted_get_con_retry non solleva mai
        # eccezione -- risposta sempre 2xx). Il regex di _estrai_foto_gallery
        # e' stato verificato a mano contro un vero URL/frammento HTML
        # forniti dall'utente (copiati dal SUO browser, con sessione/cookie
        # reali) e funziona correttamente su quel testo. Questo suggerisce
        # che la pagina scaricata dal bot (client anonimo, nessun cookie di
        # sessione reale) sia DIVERSA da quella che vede un browser vero --
        # non una rottura del regex. Log temporaneo per confermarlo dai
        # prossimi run reali: lunghezza pagina, status HTTP, se "f800"
        # compare comunque da qualche parte nel testo grezzo (regex
        # troppo stretto sul contesto) o se manca del tutto (pagina
        # diversa/bloccata), e i primi 200 caratteri per riconoscere una
        # eventuale pagina di verifica/blocco al posto dell'annuncio vero.
        # Va tolto una volta capita la causa.
        if not result["photo_urls"]:
            # Etichetta proxy aggiunta il 2026-09-27 (vedi _vinted_get_con_retry):
            # correla il fallimento "applicativo" (pagina 200 ma senza foto vere)
            # allo specifico IP che l'ha servito, cosa impossibile prima -- se
            # nei log e' sempre un piccolo sottoinsieme di proxy a comparire
            # qui, sono davvero quei pochi IP a essere compromessi; se compaiono
            # (quasi) tutti indistintamente, e' un blocco sistemico e non ha
            # senso rimuoverli uno per uno da PROXY_LIST.
            formati = _formati_foto_nella_pagina(html_pagina)
            esempio = re.search(r'https?:?[/\\]*images\d?\.vinted\.net[^"\s]{0,160}', html_pagina)
            log.warning(
                "DIAGNOSTICA scrape foto vuoto per %s: proxy=%s status=%s len(html)=%d "
                "'f800' presente nel testo grezzo=%s formati foto trovati=%s esempio URL=%r primi 200 char=%r",
                url, getattr(resp, "_proxy_etichetta", "?"), resp.status_code, len(html_pagina),
                "f800" in html_pagina, formati or "nessuno",
                esempio.group(0) if esempio else None, html_pagina[:200],
            )

        # Il photo_id della cover (prima foto) e' potenzialmente lo stesso ID
        # accettato dal parametro "search_by_image_id" del bottone Vinted
        # "Cerca articoli simili" (stesso formato osservato in produzione:
        # es. "02_015a4_6DEmrNgrJhNwjhWvNPecp79k"). NON confermato in modo
        # definitivo (nessun accesso di rete a Vinted da qui per testarlo),
        # ma se corretto permette di ottenere comp per-foto (non solo per
        # brand/categoria testuale) riusando tutta l'infrastruttura Serper
        # gia' esistente, senza browser. Vedi build_vinted_visual_search_url.
        if best_url_by_photo_id:
            result["cover_photo_id"] = next(iter(best_url_by_photo_id.keys()), None)

        size_match = re.search(r'"size_title"\s*:\s*"([^"]+)"', html_pagina)
        if size_match:
            result["size"] = size_match.group(1)

        condition_match = re.search(r'itemprop="status"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if condition_match:
            result["condition"] = condition_match.group(1).strip()

        desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html_pagina)
        if desc_match:
            result["description"] = _decodifica_stringa_json(desc_match.group(1))

        # Tentativi multipli per la data di pubblicazione. Vinted ha cambiato
        # formato: i pattern "classici" non matchano piu' in modo affidabile.
        # Aggiunte varianti con virgolette ESCAPATE (\"created_at\":...), tipiche
        # del payload React Server Components -- stesso trucco gia' usato con
        # successo per seller_id.
        created_match = re.search(r'\\?"created_at_ts\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)
        if not created_match:
            created_match = re.search(r'\\?"created_at\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)
        if not created_match:
            created_match = re.search(r'\\?"createdAt\\?"\s*:\s*\\?"([^"\\]+)\\?"', html_pagina)

        epoch_match = None
        if not created_match:
            epoch_match = re.search(r'\\?"created_at_ts\\?"\s*:\s*(\d{10,13})', html_pagina)
            if not epoch_match:
                epoch_match = re.search(r'\\?"createdAtTs\\?"\s*:\s*(\d{10,13})', html_pagina)
            if not epoch_match:
                epoch_match = re.search(r'\\?"created_at\\?"\s*:\s*(\d{10,13})', html_pagina)

        if created_match:
            result["created_at"] = created_match.group(1)
            try:
                created_dt = datetime.fromisoformat(created_match.group(1))
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                result["age_days"] = round(age_days, 1)
            except Exception:
                log.warning("Impossibile calcolare l'eta' dell'annuncio (formato data inatteso: %s).", created_match.group(1))
        elif epoch_match:
            try:
                ts = int(epoch_match.group(1))
                if ts > 10**12:  # timestamp in millisecondi
                    ts = ts / 1000
                created_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                result["created_at"] = created_dt.isoformat()
                age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
                result["age_days"] = round(age_days, 1)
            except Exception:
                log.warning("Impossibile interpretare il timestamp epoch trovato per la data di pubblicazione.")
        else:
            # Declassato da WARNING a DEBUG: e' diventato sistematico su ogni
            # annuncio (Vinted rende la pagina lato client), quindi come
            # WARNING inondava i log senza aggiungere informazione. L'eta'
            # dell'annuncio e' comunque un dato secondario: il tracker
            # notifica entro ~25s dalla pubblicazione, quindi in pratica
            # ogni annuncio che arriva qui e' "appena pubblicato".
            log.debug(
                "Data di pubblicazione non trovata per %s (rendering lato client Vinted, atteso).",
                url,
            )

        catalog_matches = re.findall(r'/catalog/(\d+)-[a-z0-9-]+?\?referrer=item-crumbs"', html_pagina)
        if catalog_matches:
            result["catalog_id"] = catalog_matches[-1]

        material_match = re.search(r'itemprop="material"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if material_match:
            result["material_raw"] = material_match.group(1).strip()
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(material_match.group(1).strip())

        if not result["material_per_ricerca"] and result.get("description"):
            result["material_per_ricerca"] = scegli_materiale_per_ricerca(result["description"])

        color_match = re.search(r'itemprop="color"[^>]*>.*?<span[^>]*>([^<]+)', html_pagina, re.DOTALL)
        if color_match:
            result["color_raw"] = color_match.group(1).strip()

        # Fallback sul markup attuale (2026-09-29): i vecchi pattern
        # (size_title, itemprop=...) non trovano piu' nulla -- la sonda del
        # 2026-09-28 riportava taglia/condizione/materiale/colore "non
        # trovato" -- perche' Vinted ora mette le caratteristiche in blocchi
        # data-testid="item-attributes-...". Vale solo per i campi rimasti
        # vuoti, quindi se il vecchio markup torna funziona come prima.
        attributi = _estrai_attributi_annuncio(html_pagina)
        if attributi:
            for campo, chiave_attr in (("size", "size"), ("condition", "condition"), ("color_raw", "color"),
                                       ("material_raw", "material"), ("uploaded_text", "uploaded")):
                if not result.get(campo) and attributi.get(chiave_attr):
                    result[campo] = attributi[chiave_attr]
            if result.get("material_raw") and not result["material_per_ricerca"]:
                result["material_per_ricerca"] = scegli_materiale_per_ricerca(result["material_raw"])
            if not result["material_per_ricerca"] and result.get("description"):
                result["material_per_ricerca"] = scegli_materiale_per_ricerca(result["description"])
        _diagnostica_attributi_mancanti(html_pagina, result, attributi, url)

        # ---- DATI VENDITORE E SELLER_LOGIN (con blocklist compatibility) ----
        seller_login_m = re.search(r'data-testid="profile-username"[^>]*>([^<]{2,40})<', html_pagina)
        if seller_login_m:
            result["seller_login"] = seller_login_m.group(1).strip()
        else:
            seller_login_m2 = re.search(r'"(?:user|seller)"\s*:\s*\{[^}]*"login"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html_pagina)
            if not seller_login_m2:
                seller_login_m2 = re.search(r'"(?:login|user_login)"\s*:\s*"([a-zA-Z0-9_.]{2,40})"', html_pagina)
            if seller_login_m2:
                result["seller_login"] = seller_login_m2.group(1)

        seller_id_m = re.search(r'href="/member/(\d+)"', html_pagina)
        if seller_id_m:
            result["seller_id"] = seller_id_m.group(1)
        else:
            seller_id_m2 = re.search(r'"user_id"\s*:\s*(\d+)', html_pagina)
            if seller_id_m2:
                result["seller_id"] = seller_id_m2.group(1)
            else:
                # Formato React Server Components scoperto in produzione:
                # \"seller_id\":49465070 -- chiave diversa da "user_id" E
                # valore numerico puro (non tra virgolette). Gestisce sia
                # la variante con virgolette escapate (\") sia quella normale.
                seller_id_m3 = re.search(r'\\?"seller_id\\?"\s*:\s*(\d+)', html_pagina)
                if seller_id_m3:
                    result["seller_id"] = seller_id_m3.group(1)

        rating_m = re.search(r'valutazione di\s+([\d.,]+)\s+su\s+5\s+stelle', html_pagina, re.IGNORECASE)
        if rating_m:
            try:
                result["seller_feedback_reputation"] = float(rating_m.group(1).replace(",", "."))
            except ValueError:
                pass
        else:
            feedback_rep_m2 = re.search(r'"feedback_reputation"\s*:\s*([\d.]+)', html_pagina)
            if feedback_rep_m2:
                try:
                    result["seller_feedback_reputation"] = float(feedback_rep_m2.group(1))
                except ValueError:
                    pass

        count_m = re.search(r'web_ui__Rating__label[^>]*>\s*<span[^>]*>\s*(\d+)\s*<', html_pagina)
        if count_m:
            result["seller_feedback_count"] = int(count_m.group(1))
        else:
            feedback_count_m2 = re.search(r'"feedback_count"\s*:\s*(\d+)', html_pagina)
            if feedback_count_m2:
                result["seller_feedback_count"] = int(feedback_count_m2.group(1))

        items_count_m = re.search(r'"items_count"\s*:\s*(\d+)', html_pagina)
        if items_count_m:
            result["seller_items_count"] = int(items_count_m.group(1))

        country_m = re.search(r'"country_title_local"\s*:\s*"([^"]{2,30})"', html_pagina)
        if country_m:
            result["seller_country"] = country_m.group(1)

        if includi_guardaroba:
            await _scrapa_guardaroba_venditore(result, url)

    except Exception as e:
        log.warning("Scraping Vinted fallito per %s: %s", url, e)

    return result


async def _scrapa_guardaroba_venditore(result, url):
    """Scarica il profilo venditore e riempie result["seller_top_items"] /
    result["seller_wardrobe_debug"]. Separata da scrape_vinted_listing il
    2026-09-28 (galleria il prima possibile): era una seconda richiesta
    SEQUENZIALE dopo la pagina annuncio, e le foto aspettavano anche lei
    (spesso con retry su 403) pur non servendole. Ora process_listing la
    lancia in parallelo al download foto e la attende solo prima di Occhio,
    l'unico che usa i primi articoli del venditore. Mai solleva: su errore
    lascia i campi di default e annota seller_wardrobe_debug."""
    try:
        seller_id = result.get("seller_id")
        seller_login = result.get("seller_login")
        if seller_id or seller_login:
            profilo_url = (
                f"https://www.vinted.it/member/{seller_id}"
                if seller_id
                else f"https://www.vinted.it/member/{seller_login}"
            )
            try:
                resp_profilo = await _vinted_get_con_retry(profilo_url, timeout=12, max_retries=2)
                if resp_profilo is not None and resp_profilo.is_success:
                    html_profilo = resp_profilo.text
                    # SOLO questo pattern e' verificato su HTML reale:
                    # data-testid="other_user_items-N--description-title">Brand</p>.
                    # I fallback generici su "title":"..." erano un problema
                    # serio: estraevano nomi di CATEGORIE del menu invece degli
                    # articoli reali -- dato sbagliato ma plausibile, piu'
                    # pericoloso di nessun dato perche' alimentava il giudizio
                    # sul venditore con informazioni false.
                    titoli = re.findall(
                        r'data-testid="other_user_items-\d+--description-title">([^<]+)<',
                        html_profilo
                    )

                    diagnostica_markup = ""
                    if not titoli:
                        idx = html_profilo.find("other_user_items")
                        if idx == -1:
                            diagnostica_markup = " [stringa 'other_user_items' assente dalla risposta HTTP grezza -- rendering lato client via JS, non catturabile senza browser headless]"
                        else:
                            estratto = html_profilo[max(0, idx - 50):idx + 150].replace("\n", " ")
                            diagnostica_markup = f" [stringa presente, contesto: ...{estratto}...]"

                    ELEMENTI_UI_DA_SCARTARE = {
                        "vinted", "facebook", "instagram", "linkedin", "twitter", "x",
                        "tiktok", "app store", "google play", "logo", "logo di vinted",
                        "scarica l'app", "pinterest", "youtube", "whatsapp", "telegram",
                    }
                    titoli = [
                        t for t in titoli
                        if t.strip().lower() not in ELEMENTI_UI_DA_SCARTARE
                        and len(t.strip()) >= 4
                    ]

                    visti = set()
                    titoli_unici = []
                    for t in titoli:
                        t_clean = t.strip()
                        if t_clean.lower() not in visti and not t_clean.startswith("http"):
                            visti.add(t_clean.lower())
                            titoli_unici.append(t_clean)
                        if len(titoli_unici) >= 8:
                            break
                    result["seller_top_items"] = titoli_unici
                    if not titoli_unici:
                        result["seller_wardrobe_debug"] = f"pagina caricata (status {resp_profilo.status_code}, {len(html_profilo)} char) ma 0 titoli estratti.{diagnostica_markup}"
                        # Declassato a DEBUG: sistematico su tutti i profili
                        # (rendering lato client), inutile come INFO ricorrente.
                        log.debug("Scraping guardaroba venditore: pagina caricata ma nessun titolo estratto per %s", profilo_url)
                    else:
                        result["seller_wardrobe_debug"] = f"ok: {len(titoli_unici)} titoli trovati"
                else:
                    result["seller_wardrobe_debug"] = "fetch fallito dopo i retry (nessuna risposta valida)"
                    log.debug("Scraping guardaroba venditore fallito (nessuna risposta valida) per %s", profilo_url)
            except Exception as e:
                result["seller_wardrobe_debug"] = f"eccezione durante il parsing: {e}"
                log.warning("Scraping guardaroba venditore fallito (eccezione): %s", e)
        else:
            result["seller_wardrobe_debug"] = "nessun seller_id/seller_login trovato nella pagina annuncio -- profilo mai contattato"
            log.debug("Guardaroba venditore non tentato: ne' seller_id ne' seller_login trovati per %s", url)
    except Exception as e:
        result["seller_wardrobe_debug"] = f"eccezione: {e}"
        log.warning("Scraping guardaroba venditore fallito (eccezione esterna): %s", e)
